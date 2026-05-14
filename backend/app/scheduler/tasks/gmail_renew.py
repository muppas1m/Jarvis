"""Renew the Gmail Pub/Sub watch every 6 days + sweep the recent inbox.

The renewal itself just re-calls users.watch(), which Gmail treats as an
extension of the existing watch rather than a tear-down + recreate. So
there's no literal "watch dies and is reborn" gap. But there's still a
short seam where the new watch's reported historyId may be ahead of what
the old subscription's push deliveries already covered — anything Gmail
published into the old watch but the push subscription hadn't fully ACKed
yet could be missed.

Closes that seam with `sweep_recent_inbox()` immediately after renewal:
the recent INBOX list + dedup against email_logs picks up anything the
push deliveries dropped. Cheap (one Gmail list call), runs every 6 days.

Wrapped in @critical_task because a silently-failing renewal is exactly
the operational disaster mode — watch expires, Pub/Sub pushes stop,
emails stop arriving in Jarvis. The 3-consecutive-failure Telegram alert
is what catches it before master notices "I haven't seen emails today."
"""
import asyncio

from app.email.gmail_pubsub import sweep_recent_inbox
from app.email.gmail_watch import setup_gmail_watch
from app.scheduler.task_helpers import reset_async_state_for_task
from app.scheduler.task_wrapper import critical_task
from app.utils.logging import get_logger

logger = get_logger(__name__)


@critical_task(name="app.scheduler.tasks.gmail_renew.renew_gmail_watch")
def renew_gmail_watch():
    """Re-register the Gmail watch + sweep recent INBOX for any seam gaps."""
    asyncio.run(_renew())


async def _renew():
    await reset_async_state_for_task()

    result = await setup_gmail_watch()
    logger.info("gmail_watch_renewed", expiration=result.get("expiration"))

    swept = await sweep_recent_inbox(history_id=None)
    logger.info("gmail_watch_renew_swept", recent_inbox_count=swept)
