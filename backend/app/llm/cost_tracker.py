"""
Daily LLM-spend tracker.

A single Redis counter per UTC-day holds the running USD total. Every
`record()` call adds the cost of that completion; the helpers
`is_over_soft_cap()` / `is_over_hard_cap()` are checked before each LLM
dispatch in the gateway.

Behavior:
  - At 80% of `daily_cap` (soft cap): the gateway downshifts every request to
    FAST_MODEL regardless of TASK_ROUTING, stretching the budget to the end
    of the day.
  - At 100% (hard cap): the gateway raises CostCapExceededError and refuses
    further LLM calls until the next day.

Redis is the right place for this counter — TTL handles the daily reset for
free, and atomic INCRBYFLOAT means concurrent calls can't undercount.
"""
from datetime import datetime, timezone

import redis.asyncio as redis

from app.config import settings
from app.llm.models import get_models


class CostTracker:
    def __init__(self, daily_cap: float, soft_cap_pct: float = 0.80):
        self.daily_cap = daily_cap
        self.soft_cap = daily_cap * soft_cap_pct
        self.redis = redis.from_url(settings.REDIS_URL)

    @staticmethod
    def _today_key() -> str:
        # Use UTC so the counter rolls at the same instant for every caller.
        return f"jarvis:llm_cost:{datetime.now(timezone.utc).date().isoformat()}"

    async def record(self, input_tokens: int, output_tokens: int, model_key: str) -> float:
        """Compute cost for one call and add it to today's counter. Returns the
        cost added (callers want this for the LLMUsageLog row)."""
        model = get_models().get(model_key)
        if model is None:
            return 0.0
        cost = (
            (input_tokens / 1000.0) * model.cost_per_1k_input
            + (output_tokens / 1000.0) * model.cost_per_1k_output
        )
        if cost > 0:
            key = self._today_key()
            # INCRBYFLOAT is atomic; EXPIRE is a safety net so old day counters
            # don't accumulate forever if the app crashes before midnight.
            await self.redis.incrbyfloat(key, cost)
            await self.redis.expire(key, 86400 * 2)
        return cost

    async def is_over_hard_cap(self) -> bool:
        val = await self.redis.get(self._today_key())
        return float(val or 0.0) >= self.daily_cap

    async def is_over_soft_cap(self) -> bool:
        val = await self.redis.get(self._today_key())
        return float(val or 0.0) >= self.soft_cap

    async def get_today_spend(self) -> float:
        """Read-only view of today's running total. Used by the cost dashboard."""
        val = await self.redis.get(self._today_key())
        return round(float(val or 0.0), 4)
