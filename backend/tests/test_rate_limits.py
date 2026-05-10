"""
Tests for the agent-loop rate limiter.

Talks to a real Redis (the docker-compose `redis` service) and the real
Postgres for the audit-log side effect. Each test isolates itself by using
unique thread_id / turn_id keys so concurrent test runs don't collide.
"""
import time
import uuid

import pytest

from app.agent.rate_limits import (
    TOOL_SPECIFIC_LIMITS_PER_TURN,
    RateLimiter,
)
from app.config import settings


@pytest.fixture
def limiter() -> RateLimiter:
    return RateLimiter()


def _fresh_thread() -> str:
    return f"test-thread-{uuid.uuid4()}"


def _fresh_turn() -> str:
    return f"test-turn-{uuid.uuid4()}"


# ---------------------------------------------------------------------------
# Per-tool sliding window — global cap
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_tool_calls_under_global_cap_allowed(limiter: RateLimiter) -> None:
    thread_id = _fresh_thread()
    turn_id = _fresh_turn()

    # Tool with no per-tool override — uses the global MAX_TOOL_CALLS_PER_TURN.
    for i in range(settings.MAX_TOOL_CALLS_PER_TURN):
        ok = await limiter.check_and_increment_tool(thread_id, turn_id, "memory_search")
        assert ok, f"call {i + 1}/{settings.MAX_TOOL_CALLS_PER_TURN} should be allowed"


@pytest.mark.asyncio
async def test_tool_calls_over_global_cap_blocked(limiter: RateLimiter) -> None:
    thread_id = _fresh_thread()
    turn_id = _fresh_turn()

    # Burn through the budget.
    for _ in range(settings.MAX_TOOL_CALLS_PER_TURN):
        await limiter.check_and_increment_tool(thread_id, turn_id, "memory_search")
    # The next one trips.
    ok = await limiter.check_and_increment_tool(thread_id, turn_id, "memory_search")
    assert ok is False


# ---------------------------------------------------------------------------
# Per-tool tighter cap (e.g. web_research = 3)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_per_tool_cap_is_tighter_than_global(limiter: RateLimiter) -> None:
    thread_id = _fresh_thread()
    turn_id = _fresh_turn()
    cap = TOOL_SPECIFIC_LIMITS_PER_TURN["web_research"]
    # We only get `cap` allowed calls before web_research blocks, even though
    # global MAX_TOOL_CALLS_PER_TURN is much higher.
    for i in range(cap):
        ok = await limiter.check_and_increment_tool(thread_id, turn_id, "web_research")
        assert ok, f"web_research call {i + 1}/{cap} should be allowed"
    blocked = await limiter.check_and_increment_tool(thread_id, turn_id, "web_research")
    assert blocked is False


# ---------------------------------------------------------------------------
# Per-turn isolation — different turn_id starts a fresh counter
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_different_turn_id_resets_counter(limiter: RateLimiter) -> None:
    thread_id = _fresh_thread()
    turn_a = _fresh_turn()
    turn_b = _fresh_turn()

    # Saturate turn A.
    for _ in range(settings.MAX_TOOL_CALLS_PER_TURN):
        await limiter.check_and_increment_tool(thread_id, turn_a, "memory_search")
    blocked = await limiter.check_and_increment_tool(thread_id, turn_a, "memory_search")
    assert blocked is False

    # Turn B (same thread) should be unaffected.
    ok = await limiter.check_and_increment_tool(thread_id, turn_b, "memory_search")
    assert ok is True


# ---------------------------------------------------------------------------
# Per-turn isolation — different thread_id starts a fresh counter
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_different_thread_id_independent(limiter: RateLimiter) -> None:
    turn_id = _fresh_turn()
    thread_a = _fresh_thread()
    thread_b = _fresh_thread()

    for _ in range(settings.MAX_TOOL_CALLS_PER_TURN):
        await limiter.check_and_increment_tool(thread_a, turn_id, "memory_search")
    assert (
        await limiter.check_and_increment_tool(thread_a, turn_id, "memory_search")
        is False
    )
    # Other thread, same turn_id string — still independent because thread is
    # part of the Redis key.
    assert (
        await limiter.check_and_increment_tool(thread_b, turn_id, "memory_search")
        is True
    )


# ---------------------------------------------------------------------------
# Sliding-window per-hour turns
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_turn_rate_under_cap_allowed(limiter: RateLimiter) -> None:
    thread_id = _fresh_thread()
    # A handful of turns within the per-hour cap should all pass.
    for _ in range(5):
        assert await limiter.check_turn_rate(thread_id) is True


@pytest.mark.asyncio
async def test_turn_rate_over_cap_blocked(limiter: RateLimiter, monkeypatch) -> None:
    """Drop the cap to 3 so the test is fast, then prove the 4th turn blocks."""
    monkeypatch.setattr(settings, "MAX_AGENT_TURNS_PER_HOUR", 3)
    thread_id = _fresh_thread()
    for _ in range(3):
        assert await limiter.check_turn_rate(thread_id) is True
    assert await limiter.check_turn_rate(thread_id) is False


@pytest.mark.asyncio
async def test_old_turns_are_pruned(limiter: RateLimiter, monkeypatch) -> None:
    """Manually inject an old timestamp into the ZSET; check_turn_rate must
    drop entries older than 1h before counting."""
    monkeypatch.setattr(settings, "MAX_AGENT_TURNS_PER_HOUR", 2)
    thread_id = _fresh_thread()
    key = f"jarvis:turns:{thread_id}"
    # Plant a stale entry from 2 hours ago.
    await limiter.redis.zadd(key, {"stale": time.time() - 7200})

    # Two fresh turns — both should pass because the stale one is pruned.
    assert await limiter.check_turn_rate(thread_id) is True
    assert await limiter.check_turn_rate(thread_id) is True
    # The third still trips.
    assert await limiter.check_turn_rate(thread_id) is False
