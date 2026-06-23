"""
Channel-routed system alerts.

Every "system needs to ping master" path goes through here:
  - tool_executor_node calls `notify_tool_executed` after a NOTIFY-tier tool
    runs (ping master "I just sent that email").
  - tool_executor_node calls `send_approval_request_to_master` for
    APPROVE-tier tools (push the inline-button approval prompt).
  - Phase 2's `@critical_task` Celery decorator calls `send_system_alert`
    after 3 consecutive failures of a scheduled job.

All three resolve through the channel registry to the master's primary
channel — Telegram in Phase 1. If/when we make the alert channel
configurable per master preference, swap the constant for a Settings field.

All three are best-effort — a delivery failure logs but never raises into
the caller, so a Telegram outage can't take down the agent path.
"""
from app.db.engine import async_session
from app.db.models import SystemAlert
from app.messaging.channel_registry import channel_registry
from app.utils.logging import get_logger

logger = get_logger(__name__)


# Master's primary alert channel. Phase 1 hard-codes Telegram; if we ever
# add per-user routing rules they can override this.
PRIMARY_ALERT_CHANNEL = "telegram"


async def notify_tool_executed(thread_id: str, tool_name: str) -> None:
    """NOTIFY-tier tool was executed — ping master so they're aware."""
    try:
        ch = channel_registry.get(PRIMARY_ALERT_CHANNEL)
        await ch.send_alert(f"🔔 Executed: `{tool_name}`")
    except Exception as exc:
        logger.error(
            "notify_tool_executed_failed",
            thread_id=thread_id,
            tool_name=tool_name,
            error=str(exc),
        )


async def send_approval_request_to_master(
    approval_id: str,
    tool_name: str,
    description: str,
) -> None:
    """APPROVE-tier — push the inline approve/reject prompt to master."""
    try:
        ch = channel_registry.get(PRIMARY_ALERT_CHANNEL)
        await ch.send_approval_request(approval_id=approval_id, description=description)
    except Exception as exc:
        logger.error(
            "send_approval_request_failed",
            approval_id=approval_id,
            tool_name=tool_name,
            error=str(exc),
        )


async def _persist_alert(text: str) -> None:
    """Best-effort persist of a system alert so the HUD Activity feed can surface
    it. Fully wrapped + INDEPENDENT of the Telegram send: a DB failure here can't
    break the alerter — it's literally reporting that something already went
    wrong, so it must never raise into the caller."""
    try:
        async with async_session() as session:
            session.add(SystemAlert(text=text))
            await session.commit()
    except Exception as exc:  # noqa: BLE001 — alerting path; never raise
        logger.error("system_alert_persist_failed", error=str(exc))


async def send_system_alert(text: str) -> None:
    """Generic system alert. Used by `@critical_task` Celery wrapper and any
    other path that needs to surface a non-conversational ping.

    Persisted (for the HUD Activity feed) AND pushed to Telegram, INDEPENDENTLY +
    best-effort: each is wrapped so neither a DB nor a Telegram outage can sink the
    other or raise into the caller. Persist first so the feed records it even if
    delivery is down."""
    await _persist_alert(text)  # wrapped internally; never raises
    try:
        ch = channel_registry.get(PRIMARY_ALERT_CHANNEL)
        await ch.send_alert(f"🚨 *SYSTEM*\n\n{text}")
    except Exception as exc:
        logger.error("send_system_alert_failed", error=str(exc))
