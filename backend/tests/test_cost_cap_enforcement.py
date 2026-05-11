"""
Cost-cap enforcement test.

The daily LLM-spend cap is enforced by the gateway, NOT by the agent
or by LLMUsageLog. The cap mechanism is Redis-only:

  Counter key: jarvis:llm_cost:<UTC_DATE>  (INCRBYFLOAT atomic)
  Hard cap:    DAILY_LLM_SPEND_CAP_USD     (default $5.00)
  Soft cap:    DAILY_LLM_SPEND_CAP_USD * DAILY_LLM_SOFT_CAP_PCT  (default 80%)

At 100% (hard cap):
  gateway.complete() reads cost_tracker.is_over_hard_cap() → True
  → raises CostCapExceededError → agent halts for the rest of the day.

At 80% (soft cap):
  gateway.complete() reads cost_tracker.is_over_soft_cap() → True
  → forces model_key="fast" regardless of TASK_ROUTING.

These tests pre-populate the Redis counter directly (NOT via
LLMUsageLog — the cap doesn't read from there) and assert each branch
fires correctly. Cleanup deletes the test counter key so the test
doesn't poison the production cap state for the rest of the day.
"""
from datetime import datetime, timezone

import pytest
import redis.asyncio as redis_aio

from app.config import settings
from app.llm.cost_tracker import CostTracker
from app.utils.exceptions import CostCapExceededError


def _today_key() -> str:
    return f"jarvis:llm_cost:{datetime.now(timezone.utc).date().isoformat()}"


@pytest.fixture
async def redis_client():
    client = redis_aio.from_url(settings.REDIS_URL)
    yield client
    await client.aclose()


@pytest.fixture
async def cost_counter_isolated(redis_client):
    """Snapshot the current value, restore on teardown.

    Without this fixture a test that SETs the counter to a high value
    would silently mark the rest of the day's traffic as "over cap"
    and the next real request would 500. Snapshotting + restoring keeps
    the test surgical."""
    key = _today_key()
    snapshot = await redis_client.get(key)
    yield key
    if snapshot is None:
        await redis_client.delete(key)
    else:
        await redis_client.set(key, snapshot)


@pytest.fixture
async def tracker():
    return CostTracker(
        daily_cap=settings.DAILY_LLM_SPEND_CAP_USD,
        soft_cap_pct=settings.DAILY_LLM_SOFT_CAP_PCT,
    )


@pytest.mark.asyncio
async def test_under_cap_returns_false(
    tracker: CostTracker,
    redis_client,
    cost_counter_isolated,
) -> None:
    """A counter value below soft and hard caps should return False on both."""
    await redis_client.set(cost_counter_isolated, "0.10")  # $0.10 << $5
    assert await tracker.is_over_soft_cap() is False
    assert await tracker.is_over_hard_cap() is False


@pytest.mark.asyncio
async def test_soft_cap_engages_at_80_percent(
    tracker: CostTracker,
    redis_client,
    cost_counter_isolated,
) -> None:
    """At 80% of daily_cap the gateway should downshift to FAST_MODEL —
    is_over_soft_cap() returning True is what triggers that branch."""
    soft_threshold = settings.DAILY_LLM_SPEND_CAP_USD * settings.DAILY_LLM_SOFT_CAP_PCT
    await redis_client.set(cost_counter_isolated, f"{soft_threshold + 0.01:.4f}")

    assert await tracker.is_over_soft_cap() is True, (
        f"Counter at ${soft_threshold + 0.01:.2f} should trigger soft cap "
        f"(threshold: ${soft_threshold:.2f}, daily_cap: "
        f"${settings.DAILY_LLM_SPEND_CAP_USD:.2f})"
    )
    # But still under the hard cap.
    assert await tracker.is_over_hard_cap() is False


@pytest.mark.asyncio
async def test_hard_cap_engages_at_100_percent(
    tracker: CostTracker,
    redis_client,
    cost_counter_isolated,
) -> None:
    """At 100% of daily_cap the gateway raises CostCapExceededError. The
    pre-condition that triggers that raise is is_over_hard_cap() == True."""
    await redis_client.set(
        cost_counter_isolated,
        f"{settings.DAILY_LLM_SPEND_CAP_USD + 0.01:.4f}",
    )
    assert await tracker.is_over_hard_cap() is True
    assert await tracker.is_over_soft_cap() is True   # past hard implies past soft


@pytest.mark.asyncio
async def test_gateway_raises_cost_cap_exceeded_when_over_hard_cap(
    redis_client,
    cost_counter_isolated,
) -> None:
    """End-to-end: pre-populate Redis above the cap, call gateway.complete(),
    assert CostCapExceededError raises BEFORE any LLM dispatch happens.

    Constructs a fresh LLMGateway (rather than importing the singleton) so
    the test doesn't depend on whatever state the singleton accumulated
    earlier in the test session."""
    await redis_client.set(
        cost_counter_isolated,
        f"{settings.DAILY_LLM_SPEND_CAP_USD + 0.01:.4f}",
    )

    from app.llm.gateway import LLMGateway

    gw = LLMGateway()
    with pytest.raises(CostCapExceededError) as excinfo:
        await gw.complete(
            messages=[{"role": "user", "content": "hello"}],
            task_type="reasoning",
        )

    assert "cap" in str(excinfo.value).lower(), (
        f"CostCapExceededError raised but message doesn't mention 'cap': "
        f"{excinfo.value!r}"
    )


@pytest.mark.asyncio
async def test_record_increments_counter_atomically(
    tracker: CostTracker,
    redis_client,
    cost_counter_isolated,
) -> None:
    """Sanity: tracker.record() bumps the counter so the next is_over_*
    check sees the new total. Catches a regression where the increment
    silently no-ops (e.g., wrong key, wrong dtype)."""
    await redis_client.set(cost_counter_isolated, "0")

    # Use "fallback" — it's gpt-4o-mini in Phase 1 (paid, in KNOWN_COSTS).
    # "primary" is Groq llama-3.3-70b which has $0 in models.py:KNOWN_COSTS
    # (Groq free tier — not in the pricing table). The increment-counter
    # contract we're testing here only fires when cost > 0.
    cost = await tracker.record(input_tokens=1000, output_tokens=200, model_key="fallback")
    assert cost > 0, (
        "Recording 1k input + 200 output tokens against the fallback model "
        "should yield a non-zero cost. If 0, either the model has no pricing "
        "or models.py changed the default keys / KNOWN_COSTS map."
    )

    counter_val = float(await redis_client.get(cost_counter_isolated) or 0)
    assert counter_val == pytest.approx(cost, rel=1e-6), (
        f"Counter after record() is {counter_val}, expected {cost}. "
        f"INCRBYFLOAT path is broken."
    )
