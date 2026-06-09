"""
LLM gateway — every model call in the codebase goes through here.

Responsibilities:
  - Provider-agnostic dispatch via LiteLLM (Anthropic / OpenAI / Groq / Ollama
    / Gemini all behind one `acompletion()` call).
  - Cost-aware routing: at 80% of the daily budget every request gets force-
    routed to FAST_MODEL; at 100% the gateway raises and the agent halts for
    the rest of the day.
  - Fallback on provider failure — primary fails → fallback model gets the
    same prompt with no caller intervention.
  - Two parallel observability channels: Langfuse (auto-traces every call via
    the LiteLLM callback) and our own `llm_usage_logs` table (powers the
    cost dashboard, joins to other custom tables, doesn't depend on Langfuse
    being up).
  - Retry on transient errors via tenacity (2 attempts, exponential backoff).

The single `llm_gateway` singleton at the bottom is what the rest of the
codebase imports.
"""
import time
import uuid

import litellm
from litellm import acompletion
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config import settings
from app.db.engine import async_session
from app.db.models import LLMUsageLog
from app.llm.bootstrap import wire_all
from app.llm.cost_tracker import CostTracker
from app.llm.models import TASK_ROUTING, get_models
from app.utils.exceptions import CostCapExceededError
from app.utils.logging import get_logger

logger = get_logger(__name__)

# Wire provider creds + Langfuse callback. Both are idempotent — see
# app.llm.bootstrap for why this lives in a separate module.
wire_all()


class LLMGateway:
    def __init__(self) -> None:
        self.cost_tracker = CostTracker(
            daily_cap=settings.DAILY_LLM_SPEND_CAP_USD,
            soft_cap_pct=settings.DAILY_LLM_SOFT_CAP_PCT,
        )
        self._models = get_models()

    async def complete(
        self,
        messages: list[dict],
        task_type: str = "reasoning",
        tools: list[dict] | None = None,
        force_model: str | None = None,
        temperature: float = 0.7,
        thread_id: str | None = None,
        tool_name_context: str | None = None,
        response_format: dict | None = None,
    ) -> dict:
        """Dispatch a chat-completion. Returns the LiteLLM response dict.

        `task_type` selects the slot in TASK_ROUTING; `force_model` overrides
        the routing if you need a specific slot for one call. `response_format`
        is passed through to the provider (e.g. `{"type": "json_object"}` for
        JSON mode) — supported by Groq + OpenAI, so it survives the fallback hop.
        """
        # Hard cap → halt for the rest of the day.
        if await self.cost_tracker.is_over_hard_cap():
            raise CostCapExceededError(
                f"Daily LLM spend cap (${settings.DAILY_LLM_SPEND_CAP_USD:.2f}) reached. "
                "Agent halted until UTC midnight."
            )

        # Soft cap → degrade everything to fast.
        soft_cap_hit = await self.cost_tracker.is_over_soft_cap()
        if soft_cap_hit and not force_model:
            model_key = "fast"
            logger.warning(
                "soft_cap_degradation",
                requested_task_type=task_type,
                forced_to="fast",
            )
        else:
            model_key = force_model or TASK_ROUTING.get(task_type, "primary")

        model = self._models[model_key]
        start = time.time()

        try:
            response = await self._call_llm(
                model.model_id, messages, tools, temperature, thread_id, task_type, response_format
            )
        except Exception as exc:
            logger.error(
                "llm_call_failed",
                model=model.model_id,
                slot=model_key,
                error=str(exc),
            )
            # Don't recurse if we already hit the fallback slot.
            if model_key == "fallback":
                raise
            fallback = self._models["fallback"]
            logger.info(
                "falling_back",
                from_=model.model_id,
                to=fallback.model_id,
            )
            response = await self._call_llm(
                fallback.model_id, messages, tools, temperature, thread_id, task_type, response_format
            )
            model = fallback   # cost-tracking should reflect the fallback model
            model_key = "fallback"

        duration_ms = int((time.time() - start) * 1000)

        usage = response.get("usage") or {}
        prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
        completion_tokens = int(usage.get("completion_tokens", 0) or 0)

        cost = await self.cost_tracker.record(
            input_tokens=prompt_tokens,
            output_tokens=completion_tokens,
            model_key=model_key,
        )

        await self._log_to_db(
            model=model.model_id,
            task_type=task_type,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd=cost,
            tool_name=tool_name_context,
            thread_id=thread_id,
            duration_ms=duration_ms,
            langfuse_trace_id=response.get("_langfuse_trace_id"),
        )

        return response

    @retry(stop=stop_after_attempt(2), wait=wait_exponential(min=1, max=10))
    async def _call_llm(
        self,
        model: str,
        messages: list[dict],
        tools: list[dict] | None,
        temperature: float,
        thread_id: str | None,
        task_type: str,
        response_format: dict | None = None,
    ) -> dict:
        # Langfuse-readable metadata. session_id groups all calls for a
        # conversation; tags surface in the trace browser for filtering.
        provider_tag = model.split("/", 1)[0] if "/" in model else "direct"
        kwargs: dict = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
            "metadata": {
                "trace_name": f"llm-{task_type}",
                "session_id": thread_id or f"adhoc-{uuid.uuid4().hex[:8]}",
                "tags": [task_type, provider_tag],
            },
        }
        if tools:
            kwargs["tools"] = tools
        if response_format:
            kwargs["response_format"] = response_format

        response = await acompletion(**kwargs)
        # LiteLLM responses are pydantic models; pin to dict for stable downstream access.
        return response.model_dump()

    async def _log_to_db(self, **fields) -> None:
        """Persist usage to llm_usage_logs. Never lets a logging failure abort the call."""
        try:
            async with async_session() as session:
                session.add(LLMUsageLog(**fields))
                await session.commit()
        except Exception as exc:  # noqa: BLE001 — last-resort guard
            logger.error("llm_usage_log_failed", error=str(exc))


# Singleton — every other module imports this.
llm_gateway = LLMGateway()
