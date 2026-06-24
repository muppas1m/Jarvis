"""
Per-turn / per-conversation rate limiting for the agent loop.

Two layered limits:
  - MAX_TOOL_CALLS_PER_TURN: ceiling across ALL tools within one user turn.
  - TOOL_SPECIFIC_LIMITS_PER_TURN: tighter per-tool caps for things that are
    expensive (web_research, firecrawl_crawl) or risky (email_send,
    browser_form_submit).
  - MAX_AGENT_TURNS_PER_HOUR: per-thread sliding window of total turns.

Authoritative state lives in Redis. Each block writes a `rate_limit_events`
row to Postgres for audit (the dashboard queries this; logs alone get rotated).

Per-turn keys are scoped by `(thread_id, turn_id)` where turn_id is the
ISO-timestamp the agent stamped at turn start. This means each user message
gets its own counter — no cross-turn contamination if the agent is in a
fast back-and-forth.

NOT to be confused with `app/security/rate_limiter.py` (Phase 4 Task 4.17).
That one enforces real-world side-effect caps (max N email_sends per hour
across ALL turns); this one is the agent-loop hygiene layer that prevents a
single-turn runaway.
"""
import time

import redis.asyncio as redis

from app.config import settings
from app.db.engine import async_session
from app.db.models import RateLimitEvent
from app.utils.logging import get_logger

logger = get_logger(__name__)


# Per-tool overrides — tighter than the global per-turn cap.
TOOL_SPECIFIC_LIMITS_PER_TURN: dict[str, int] = {
    "web_research":         3,
    "tavily_search":        3,
    "firecrawl_crawl":      3,
    "email_send":           5,
    "browser_form_submit":  2,
    # Cap the expensive RAG re-hunt: each call reranks the whole corpus. Two
    # tries is plenty; the prompt tells the agent to stop after an empty result.
    "document_search":      2,
}


class RateLimiter:
    def __init__(self) -> None:
        self.redis = redis.from_url(settings.REDIS_URL)

    async def check_and_increment_tool(
        self,
        thread_id: str,
        turn_id: str,
        tool_name: str,
        tool_call_id: str | None = None,
    ) -> bool:
        """Increment the per-turn counter for `tool_name` and return True if
        the call is still under both the global and per-tool caps. False
        means the call was blocked; the audit row has already been written.

        Idempotent per `tool_call_id`: an APPROVE interrupt makes tool_executor
        RE-RUN the same node (same tool_call) on every resume, and an edit loop
        re-runs it repeatedly — so a tool_call already counted this turn is NOT
        re-counted (otherwise the resume would exhaust the cap and block the
        approved send). Each DISTINCT tool_call (incl. every edit's re-draft)
        still counts once.
        """
        key = f"jarvis:tool_count:{thread_id}:{turn_id}"

        # Count each tool_call ONCE per turn — resume re-runs must not re-count.
        if tool_call_id:
            seen_key = f"jarvis:tool_seen:{thread_id}:{turn_id}"
            is_new = await self.redis.sadd(seen_key, tool_call_id)
            await self.redis.expire(seen_key, 3600)
            if not is_new:
                return True

        # Global per-turn ceiling first.
        total = await self.redis.hincrby(key, "_total", 1)
        await self.redis.expire(key, 3600)
        if total > settings.MAX_TOOL_CALLS_PER_TURN:
            await self._log_block(
                thread_id, "tools_per_turn",
                settings.MAX_TOOL_CALLS_PER_TURN, total,
            )
            return False

        # Tighter per-tool ceiling, only for tools that have one.
        per_tool_limit = TOOL_SPECIFIC_LIMITS_PER_TURN.get(tool_name)
        if per_tool_limit is not None:
            per_tool_count = await self.redis.hincrby(key, tool_name, 1)
            if per_tool_count > per_tool_limit:
                await self._log_block(
                    thread_id, f"tool:{tool_name}",
                    per_tool_limit, per_tool_count,
                )
                return False

        return True

    async def check_turn_rate(self, thread_id: str) -> bool:
        """Sliding window: cap MAX_AGENT_TURNS_PER_HOUR per thread.

        Records the new turn first, then counts; this means the limit
        triggers exactly at N+1, not N. ZSET score is the unix timestamp,
        which doubles as the window's natural expiry pivot.
        """
        key = f"jarvis:turns:{thread_id}"
        now = time.time()
        cutoff = now - 3600

        async with self.redis.pipeline() as pipe:
            pipe.zremrangebyscore(key, 0, cutoff)
            pipe.zadd(key, {str(now): now})
            pipe.zcard(key)
            pipe.expire(key, 3600)
            results = await pipe.execute()
        current_count: int = results[2]

        if current_count > settings.MAX_AGENT_TURNS_PER_HOUR:
            await self._log_block(
                thread_id, "turns_per_hour",
                settings.MAX_AGENT_TURNS_PER_HOUR, current_count,
            )
            return False
        return True

    async def _log_block(
        self,
        thread_id: str,
        limit_type: str,
        limit_value: int,
        actual: int,
    ) -> None:
        """Persist a blocked-event row. Failure to log does NOT propagate —
        the limiter must keep working even when the DB is sad."""
        try:
            async with async_session() as session:
                session.add(
                    RateLimitEvent(
                        thread_id=thread_id,
                        limit_type=limit_type,
                        limit_value=limit_value,
                        actual_value=actual,
                        blocked=True,
                    )
                )
                await session.commit()
            logger.warning(
                "rate_limit_blocked",
                thread_id=thread_id,
                limit_type=limit_type,
                limit_value=limit_value,
                actual=actual,
            )
        except Exception as exc:  # noqa: BLE001 — last-resort guard
            logger.error("rate_limit_log_failed", error=str(exc))


# Module-level singleton. Stateless aside from the redis connection pool.
rate_limiter = RateLimiter()
