"""P2 — inbound-email health canary.

The canary alerts (in plain language) when no Gmail poll has succeeded within
INBOUND_HEALTH_MAX_STALE_HOURS — the signal that was missing during the Jun-11
~2-week silent outage. Keyed on poll *success* (heartbeat), so a quiet inbox
never false-alarms; debounced so a sustained outage doesn't spam.
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

import app.scheduler.tasks.inbound_health as ih


class _FakeRedis:
    """Minimal sync-Redis stand-in (str values, ignores TTL semantics)."""

    def __init__(self):
        self.store: dict = {}

    def get(self, k):
        return self.store.get(k)

    def set(self, k, v, ex=None):  # noqa: ARG002 — TTL irrelevant for the test
        self.store[k] = v

    def delete(self, k):
        self.store.pop(k, None)


@pytest.fixture
def fake_redis(monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(ih, "_redis", fake)
    return fake


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# heartbeat write                                                             #
# --------------------------------------------------------------------------- #
def test_mark_success_writes_heartbeat_and_clears_alert(fake_redis):
    fake_redis.store[ih._ALERTED_KEY] = "stale-alert"
    ih.mark_inbound_poll_success()
    assert ih.HEARTBEAT_KEY in fake_redis.store          # heartbeat recorded
    assert ih._ALERTED_KEY not in fake_redis.store        # outage flag re-armed


# --------------------------------------------------------------------------- #
# canary logic                                                                #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_healthy_heartbeat_no_alert(fake_redis):
    fake_redis.store[ih.HEARTBEAT_KEY] = _iso(_now() - timedelta(minutes=20))
    with patch("app.messaging.failure_alerter.send_system_alert", new=AsyncMock()) as alert:
        await ih._check()
    alert.assert_not_called()


@pytest.mark.asyncio
async def test_stale_heartbeat_alerts_and_sets_flag(fake_redis):
    fake_redis.store[ih.HEARTBEAT_KEY] = _iso(_now() - timedelta(hours=5))  # > 3h
    with patch("app.messaging.failure_alerter.send_system_alert", new=AsyncMock()) as alert:
        await ih._check()
    alert.assert_awaited_once()
    assert ih._ALERTED_KEY in fake_redis.store  # debounce flag set


@pytest.mark.asyncio
async def test_missing_heartbeat_no_alert_cold_start(fake_redis):
    """No heartbeat at all (cold start / never-succeeded) must NOT alert — that
    fires on every restart and is covered by gmail_check's @critical_task alert.
    The canary only fires on a stale (was-healthy-then-broke) heartbeat."""
    with patch("app.messaging.failure_alerter.send_system_alert", new=AsyncMock()) as alert:
        await ih._check()
    alert.assert_not_called()
    assert ih._ALERTED_KEY not in fake_redis.store  # no debounce flag set either


@pytest.mark.asyncio
async def test_debounced_no_realert_when_flag_present(fake_redis):
    fake_redis.store[ih.HEARTBEAT_KEY] = _iso(_now() - timedelta(hours=5))
    fake_redis.store[ih._ALERTED_KEY] = _iso(_now())  # already alerted
    with patch("app.messaging.failure_alerter.send_system_alert", new=AsyncMock()) as alert:
        await ih._check()
    alert.assert_not_called()


@pytest.mark.asyncio
async def test_recovery_after_outage_rearms(fake_redis):
    """stale → alert (flag set); then a successful poll clears the flag; then a
    fresh outage alerts again (not debounced by the old flag)."""
    fake_redis.store[ih.HEARTBEAT_KEY] = _iso(_now() - timedelta(hours=5))
    with patch("app.messaging.failure_alerter.send_system_alert", new=AsyncMock()) as a1:
        await ih._check()
    a1.assert_awaited_once()

    ih.mark_inbound_poll_success()                 # recovery clears the flag
    assert ih._ALERTED_KEY not in fake_redis.store

    fake_redis.store[ih.HEARTBEAT_KEY] = _iso(_now() - timedelta(hours=5))  # new outage
    with patch("app.messaging.failure_alerter.send_system_alert", new=AsyncMock()) as a2:
        await ih._check()
    a2.assert_awaited_once()
