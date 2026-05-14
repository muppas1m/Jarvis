"""
FallbackChatLLM — agent_node resilience wrapper for primary → fallback dispatch.

Closes the architectural seam documented in
`project_agent_node_bypasses_gateway_fallback.md`: `agent_node` calls
`ChatLiteLLM` directly via `bind_tools()`, bypassing `LLMGateway`'s
cross-provider fallback chain. When Groq's primary model (llama-3.3-70b)
returns RateLimitError on multi-tool synthesis queries OR BadRequestError
with `code: "tool_use_failed"` (Groq llama emitting malformed Llama-native
function-call syntax; see
`project_open_weights_tool_schema_and_conversation_poisoning.md`), the
turn fails as "I hit an internal error." Master sees this on a non-trivial
fraction of multi-tool turns.

This wrapper sits between agent_node and ChatLiteLLM as a Runnable. Two
pre-bound (tools already attached) Runnables go in (primary + fallback);
it tries primary, on retry-worthy exception falls over to fallback,
emits an `agent_llm_fallback` log event for monitoring.

Design choices vs. `Runnable.with_fallbacks()` (langchain built-in):
  - Built-in `with_fallbacks` exception filtering is class-based only,
    no predicate support. We need to narrow `BadRequestError` to ONLY
    `tool_use_failed` cases — other BadRequestErrors (model not found,
    malformed input) won't recover via fallback.
  - Built-in doesn't surface a log event on fall-over; we lose visibility
    into how often fallback fires. The `agent_llm_fallback` log is
    load-bearing for production monitoring.

The string-match predicate on "tool_use_failed" is documented as a known
fragility in `project_groq_error_message_string_match_dependency.md` —
worth a re-check if Groq updates their error message shape.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

import litellm
from langchain_core.runnables import Runnable, RunnableConfig

from app.utils.logging import get_logger

logger = get_logger(__name__)


def _default_retry_predicate(exc: BaseException) -> bool:
    """Should this primary-LLM exception trigger fallback to the secondary?

    Yes for transient failures + Groq's tool_use_failed pattern.
    No for AuthenticationError (real config), model-not-found (real
    config), and other BadRequestError shapes where retry can't help.
    """
    # Transient infrastructure / rate failures — always retry-worthy
    if isinstance(exc, litellm.RateLimitError):
        return True
    if isinstance(exc, litellm.APIConnectionError):
        return True
    if isinstance(exc, litellm.Timeout):
        return True

    # BadRequestError is overloaded. Narrow to the specific Groq tool-call
    # malformation pattern; let other shapes propagate so we notice them.
    if isinstance(exc, litellm.BadRequestError):
        msg = str(exc).lower()
        if "tool_use_failed" in msg:
            return True
        if "failed to call a function" in msg:
            return True
        return False

    # Everything else — including AuthenticationError, InvalidRequestError
    # for genuinely-bad input, RecursionError, etc. — propagate.
    return False


class FallbackChatLLM(Runnable):
    """Wraps a primary Runnable + fallback Runnable. Tries primary; on
    retry-worthy exception, falls over to fallback. Both runnables
    should be pre-`bind_tools()`'d if tools are needed — the wrapper is
    transparent to whatever tool binding state the underlying runnables
    carry.

    Inputs to ainvoke/invoke pass through unchanged; the wrapper does NOT
    transform input or output. ChatLiteLLM's AIMessage with tool_calls
    comes back as-is from whichever model succeeded.
    """

    def __init__(
        self,
        primary: Runnable,
        fallback: Runnable,
        retry_predicate: Optional[Callable[[BaseException], bool]] = None,
    ) -> None:
        self.primary = primary
        self.fallback = fallback
        self.retry_predicate = retry_predicate or _default_retry_predicate

    def invoke(self, input: Any, config: Optional[RunnableConfig] = None, **kwargs: Any) -> Any:
        try:
            return self.primary.invoke(input, config=config, **kwargs)
        except Exception as exc:  # noqa: BLE001 — predicate decides which propagate
            if not self.retry_predicate(exc):
                raise
            self._log_fallback(exc)
            return self.fallback.invoke(input, config=config, **kwargs)

    async def ainvoke(self, input: Any, config: Optional[RunnableConfig] = None, **kwargs: Any) -> Any:
        try:
            return await self.primary.ainvoke(input, config=config, **kwargs)
        except Exception as exc:  # noqa: BLE001
            if not self.retry_predicate(exc):
                raise
            self._log_fallback(exc)
            return await self.fallback.ainvoke(input, config=config, **kwargs)

    def _log_fallback(self, exc: BaseException) -> None:
        """Structured log event for every fall-over. Production monitoring
        anchors on this event; a sudden drop in fallback rate while
        graph_invoke_failed rate stays high is the signal that the
        retry_predicate's string-match has stopped catching what it used
        to (e.g., Groq renamed an error message)."""
        logger.warning(
            "agent_llm_fallback",
            primary_error_type=type(exc).__name__,
            primary_error_msg=str(exc)[:200],
        )
