"""Renew the provider's push subscription twice weekly + sweep recent inbox.

The provider's push watch expires (Gmail ~7 days, Graph ~3); re-registering
extends it. There's a short seam where the new watch's cursor may be ahead of
what the old subscription's deliveries covered, so we ``sweep_recent_inbox()``
immediately after renewal to pick up anything dropped in the gap.

Wrapped in @critical_task because a silently-failing renewal is the operational
disaster mode — the watch expires, pushes stop, email stops arriving in Jarvis.
The 3-consecutive-failure alert catches it before the master notices.
"""
import asyncio

from app.email.inbound import sweep_recent_inbox
from app.email.provider import get_email_provider
from app.scheduler.task_helpers import reset_async_state_for_task
from app.scheduler.task_wrapper import critical_task
from app.utils.logging import get_logger

logger = get_logger(__name__)


@critical_task(name="app.scheduler.tasks.email_renew.renew_watch")
def renew_watch():
    """Re-register the provider watch + sweep recent inbox for any seam gaps."""
    asyncio.run(_renew())


async def _renew():
    await reset_async_state_for_task()

    result = await get_email_provider().setup_watch()
    logger.info("email_watch_renewed", expiration=result.get("expiration"))

    swept = await sweep_recent_inbox()
    logger.info("email_watch_renew_swept", recent_inbox_count=swept)
