"""Inbound-email health canary.

The Jun-11 outage was silent for ~2 weeks: `gmail_check` failed every cycle on
an expired Google token, but the only signal was a cryptic `@critical_task`
"task failed" alert that never said "you are missing email." This canary closes
that gap with a plain, symptom-named alert.

Design — heartbeat-on-successful-poll, not raw email_logs freshness:
  `gmail_check` calls `mark_inbound_poll_success()` after every poll that
  completes without error. This task reads that heartbeat and alerts when it's
  older than ``INBOUND_HEALTH_MAX_STALE_HOURS``. Keying on poll *success* (not
  on "a new email arrived") means a genuinely quiet inbox — which still polls
  cleanly every 15 min — never false-alarms; only a real failure (expired
  token, lapsed watch, wedged worker) lets the heartbeat go stale. That is
  exactly the failure mode that went undetected.

Only a *stale* heartbeat (one that exists but has aged out) alerts — a missing
heartbeat (cold start / never-succeeded) does not, since that fires on every
restart before the first poll and is already covered by gmail_check's
``@critical_task`` failure alert.

Debounce: alert at most once per ``INBOUND_HEALTH_REALERT_HOURS`` during a
sustained outage (a Redis flag with TTL), and clear the flag the moment a poll
succeeds so a later outage re-alerts immediately.
"""
import asyncio
from datetime import datetime, timezone

import redis

from app.config import settings
from app.scheduler.task_wrapper import critical_task
from app.utils.logging import get_logger

logger = get_logger(__name__)

# DB 1 (same as the critical-task failure counters) keeps the app cache (DB 0)
# clean. from_url is lazy — no connection until first use.
_redis = redis.from_url(settings.REDIS_URL.replace("/0", "/1"))

HEARTBEAT_KEY = "jarvis:inbound:last_poll_success"
_ALERTED_KEY = "jarvis:inbound:health_alerted"


def mark_inbound_poll_success() -> None:
    """Record a successful inbound poll + clear any standing outage alert.

    Called by `gmail_check` after a clean sweep. Best-effort: a Redis hiccup
    here must never fail the poll itself, so failures are swallowed (logged)."""
    try:
        _redis.set(HEARTBEAT_KEY, datetime.now(timezone.utc).isoformat())
        _redis.delete(_ALERTED_KEY)  # recovery → re-arm the canary
    except Exception as exc:  # noqa: BLE001
        logger.warning("inbound_heartbeat_write_failed", error=str(exc))


def _parse(raw: object) -> datetime | None:
    if raw is None:
        return None
    text = raw.decode() if isinstance(raw, (bytes, bytearray)) else str(raw)
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


@critical_task(name="app.scheduler.tasks.inbound_health.check_inbound_health")
def check_inbound_health():
    """Beat-scheduled canary — alert if inbound polling has gone stale."""
    asyncio.run(_check())


async def _check() -> None:
    now = datetime.now(timezone.utc)
    last = _parse(_redis.get(HEARTBEAT_KEY))
    stale_after = settings.INBOUND_HEALTH_MAX_STALE_HOURS * 3600

    if last is None:
        # No heartbeat yet — cold start / fresh deploy / never-succeeded. We do
        # NOT alert here: alerting on "never" fires on every restart before the
        # first poll writes its heartbeat (and a worker that has genuinely never
        # polled is already covered by gmail_check's @critical_task failure
        # alert). The canary's job is to catch a pipeline that WAS healthy and
        # went stale — which is exactly the Jun-11 token-expiry shape.
        logger.info("inbound_health_no_heartbeat_yet")
        return

    if (now - last).total_seconds() <= stale_after:
        return  # healthy — a poll succeeded recently

    if _redis.get(_ALERTED_KEY):
        return  # already alerted for this outage (debounce window still open)

    age = f"{int((now - last).total_seconds() // 3600)}h+"
    logger.error("inbound_health_stale", last_success=str(last), age=age)
    await _alert(age)
    _redis.set(
        _ALERTED_KEY, now.isoformat(),
        ex=settings.INBOUND_HEALTH_REALERT_HOURS * 3600,
    )


async def _alert(age: str) -> None:
    from app.messaging.failure_alerter import send_system_alert

    await send_system_alert(
        "⚠️ *Inbound email looks DOWN.*\n\n"
        f"No successful inbox poll in *{age}* (threshold "
        f"{settings.INBOUND_HEALTH_MAX_STALE_HOURS}h). New emails may not be "
        "reaching me.\n\n"
        "Most likely: an expired Google token in the Celery worker, a lapsed "
        "Gmail watch, or a stopped worker. Check the worker log for "
        "`invalid_grant`; the fix is usually "
        "`docker compose up -d --force-recreate celery-worker celery-beat` "
        "+ re-registering the watch."
    )
