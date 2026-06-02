"""
GET /api/costs — LLM spend snapshot.

Powers the dashboard cost panel and gives ops the answer to "how much
did I spend today" without opening Langfuse. Two windows for the Phase
1 surface — today (UTC) and the trailing 7 days (rolling, not calendar
week). Both windows aggregate across model + task_type so a sudden
spike in memory_extraction tokens vs primary-agent tokens is visible.

Source: LLMUsageLog rows. The LiteLLM success callback writes one row
per completion call; this endpoint just sums them. No dedup logic
because each callback fires per-completion (no duplicates).

CAVEAT — what this endpoint is NOT authoritative about:
LLMUsageLog itself only captures completions that flow through
`LLMGateway.complete()`. Three current surfaces bypass the gateway and
write nothing to LLMUsageLog: agent_node (uses ChatLiteLLM via
FallbackChatLLM directly), the embedding paths (`litellm.aembedding`),
and Mem0's extraction LLM (`provider: litellm` in Mem0 config). See
`project_agent_llm_cost_attribution_gap.md` for the full landscape.
So /api/costs is authoritative for what the GATEWAY tracked — a strict
subset of real LLM spend. Real spend reconciliation lands with Phase 4
dashboard cost-visibility work (Option C hybrid helper in the memory
note closes all three bypass surfaces in one structural change).

Phase 3 will add per-thread / per-tool breakdowns + a daily history
chart. For Phase 1 just the rollups.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import case, func, select

from app.db.engine import async_session
from app.db.models import LLMUsageLog

router = APIRouter(prefix="/costs", tags=["costs"])


class WindowSummary(BaseModel):
    request_count: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float
    by_model: dict[str, float]    # model_name -> cost_usd
    by_task: dict[str, float]     # task_type -> cost_usd


class CostsResponse(BaseModel):
    today_utc: WindowSummary
    last_7d: WindowSummary
    generated_at: str


async def _summarize_window(start: datetime) -> WindowSummary:
    """Aggregate LLMUsageLog rows whose created_at >= start."""
    async with async_session() as session:
        totals_result = await session.execute(
            select(
                func.count(LLMUsageLog.id).label("count"),
                func.coalesce(func.sum(LLMUsageLog.prompt_tokens), 0).label("prompt"),
                func.coalesce(func.sum(LLMUsageLog.completion_tokens), 0).label("completion"),
                func.coalesce(func.sum(LLMUsageLog.cost_usd), 0.0).label("cost"),
            ).where(LLMUsageLog.created_at >= start)
        )
        totals = totals_result.one()

        by_model_result = await session.execute(
            select(
                LLMUsageLog.model,
                func.coalesce(func.sum(LLMUsageLog.cost_usd), 0.0).label("cost"),
            )
            .where(LLMUsageLog.created_at >= start)
            .group_by(LLMUsageLog.model)
        )
        by_model = {row.model: float(row.cost) for row in by_model_result}

        by_task_result = await session.execute(
            select(
                LLMUsageLog.task_type,
                func.coalesce(func.sum(LLMUsageLog.cost_usd), 0.0).label("cost"),
            )
            .where(LLMUsageLog.created_at >= start)
            .group_by(LLMUsageLog.task_type)
        )
        by_task = {row.task_type: float(row.cost) for row in by_task_result}

    prompt_tokens = int(totals.prompt or 0)
    completion_tokens = int(totals.completion or 0)
    return WindowSummary(
        request_count=int(totals.count or 0),
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        total_tokens=prompt_tokens + completion_tokens,
        cost_usd=round(float(totals.cost or 0.0), 6),
        by_model=by_model,
        by_task=by_task,
    )


@router.get("", response_model=CostsResponse)
async def get_costs() -> CostsResponse:
    now = datetime.now(timezone.utc)
    start_of_day_utc = now.replace(hour=0, minute=0, second=0, microsecond=0)
    seven_days_ago = now - timedelta(days=7)

    today_summary = await _summarize_window(start_of_day_utc)
    week_summary = await _summarize_window(seven_days_ago)

    return CostsResponse(
        today_utc=today_summary,
        last_7d=week_summary,
        generated_at=now.isoformat(),
    )
