"""
GET /api/costs — LLM spend snapshot, honestly labelled.

This endpoint reports two numbers from two DIFFERENT sources, and is explicit
about what each does and does not measure — presenting a single mixed "total
spend" would be a lie on two axes:

  1. COVERAGE (what's counted at all). The token/cost rollups come from
     `LLMUsageLog`, which only captures completions routed through
     `LLMGateway.complete()`. Three surfaces bypass the gateway and write
     nothing: agent_node (ChatLiteLLM via FallbackChatLLM), the embedding paths
     (`litellm.aembedding`), and Mem0's extraction LLM. So these numbers are a
     strict SUBSET of real spend — `coverage.excludes` says so in the payload,
     not just here. Full reconciliation is the Phase-4 gateway-bypass fix
     (Option C hybrid helper — `project_agent_llm_cost_attribution_gap.md`).

  2. SOURCE (which store). The `cap` block is the live Redis enforcement counter
     (`jarvis:llm_cost:<UTC_DATE>`) the gateway actually checks before each call;
     the window rollups are the durable `LLMUsageLog` ledger. They track the same
     gateway events but diverge after a Redis restart — the counter resets (TTL),
     the ledger persists — so `cap.spend_usd` can read LOWER than
     `today_utc.cost_usd` (`project_cost_cap_redis_only.md`). `cap.note` says so.

Windows: today (UTC) + trailing 7 days on the summary; daily series on /history.
Per-thread / per-tool drill-downs land with the Phase-4 dashboard.
"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Query
from pydantic import BaseModel
from sqlalchemy import func, select

from app.config import settings
from app.db.engine import async_session
from app.db.models import LLMUsageLog
from app.llm.cost_tracker import CostTracker

router = APIRouter(prefix="/costs", tags=["costs"])


# --------------------------------------------------------------------------- #
# Response models                                                             #
# --------------------------------------------------------------------------- #
class CostCoverage(BaseModel):
    """What the LLMUsageLog-sourced numbers do and do NOT measure."""

    source: str
    measures: str
    excludes: list[str]
    note: str


class CapStatus(BaseModel):
    """The live Redis enforcement counter — a different source from the ledger."""

    source: str
    spend_usd: float
    soft_cap_usd: float
    hard_cap_usd: float
    soft_cap_hit: bool
    hard_cap_hit: bool
    note: str


class WindowSummary(BaseModel):
    request_count: int
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    cost_usd: float
    by_model: dict[str, float]    # model_name -> cost_usd
    by_task: dict[str, float]     # task_type -> cost_usd


class CostsResponse(BaseModel):
    coverage: CostCoverage        # what's counted (gateway-only subset)
    cap: CapStatus                # live Redis enforcement counter (separate source)
    today_utc: WindowSummary      # LLMUsageLog ledger, today UTC
    last_7d: WindowSummary        # LLMUsageLog ledger, trailing 7 days
    generated_at: str


class DailyCost(BaseModel):
    day: str
    cost_usd: float
    request_count: int


class CostHistoryResponse(BaseModel):
    coverage: CostCoverage
    days: int
    history: list[DailyCost]
    generated_at: str


# --------------------------------------------------------------------------- #
# Honest-labelling helpers                                                    #
# --------------------------------------------------------------------------- #
def _coverage() -> CostCoverage:
    """The coverage caveat, surfaced IN the payload (not just the docstring)."""
    return CostCoverage(
        source="LLMUsageLog (completions routed through LLMGateway.complete())",
        measures="USD + token counts for gateway-tracked completions",
        excludes=[
            "agent_node (ChatLiteLLM via FallbackChatLLM)",
            "embeddings (litellm.aembedding)",
            "Mem0 extraction LLM",
        ],
        note=(
            "These three surfaces bypass the gateway and are NOT counted here, so "
            "this is a strict subset of real LLM spend. Full reconciliation is the "
            "Phase-4 gateway-bypass fix (project_agent_llm_cost_attribution_gap.md)."
        ),
    )


async def _cap_status() -> CapStatus:
    tracker = CostTracker(
        daily_cap=settings.DAILY_LLM_SPEND_CAP_USD,
        soft_cap_pct=settings.DAILY_LLM_SOFT_CAP_PCT,
    )
    spend = await tracker.get_today_spend()
    return CapStatus(
        source="Redis counter jarvis:llm_cost:<UTC_DATE> (live cap enforcement)",
        spend_usd=spend,
        soft_cap_usd=round(tracker.soft_cap, 4),
        hard_cap_usd=settings.DAILY_LLM_SPEND_CAP_USD,
        soft_cap_hit=spend >= tracker.soft_cap,
        hard_cap_hit=spend >= settings.DAILY_LLM_SPEND_CAP_USD,
        note=(
            "Same gateway-only coverage as the ledger. This is the counter the cap "
            "enforcer reads; it resets if Redis restarts mid-day, so it can read "
            "lower than today_utc.cost_usd after a restart (project_cost_cap_redis_only.md)."
        ),
    )


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


# --------------------------------------------------------------------------- #
# Endpoints                                                                   #
# --------------------------------------------------------------------------- #
@router.get("", response_model=CostsResponse)
async def get_costs() -> CostsResponse:
    now = datetime.now(timezone.utc)
    start_of_day_utc = now.replace(hour=0, minute=0, second=0, microsecond=0)
    seven_days_ago = now - timedelta(days=7)

    return CostsResponse(
        coverage=_coverage(),
        cap=await _cap_status(),
        today_utc=await _summarize_window(start_of_day_utc),
        last_7d=await _summarize_window(seven_days_ago),
        generated_at=now.isoformat(),
    )


@router.get("/history", response_model=CostHistoryResponse)
async def cost_history(
    days: int = Query(default=30, ge=1, le=365, description="Trailing days of daily spend"),
) -> CostHistoryResponse:
    """Daily gateway-tracked spend for the trailing N days (LLMUsageLog ledger)."""
    now = datetime.now(timezone.utc)
    since = now - timedelta(days=days)
    day_col = func.date(LLMUsageLog.created_at).label("day")

    async with async_session() as session:
        result = await session.execute(
            select(
                day_col,
                func.coalesce(func.sum(LLMUsageLog.cost_usd), 0.0).label("cost"),
                func.count(LLMUsageLog.id).label("count"),
            )
            .where(LLMUsageLog.created_at >= since)
            .group_by(day_col)
            .order_by(day_col.desc())
        )
        history = [
            DailyCost(
                day=str(row.day),
                cost_usd=round(float(row.cost or 0.0), 6),
                request_count=int(row.count or 0),
            )
            for row in result
        ]

    return CostHistoryResponse(
        coverage=_coverage(),
        days=days,
        history=history,
        generated_at=now.isoformat(),
    )
