"""15-min Gmail safety-net poll.

Pub/Sub's at-least-once guarantee covers messages the broker accepted from
the publisher. It does NOT cover Gmail's internal publisher failures (rare
but real). This poll closes the remaining gap: list recent INBOX messages,
dedup against email_logs, process anything new. ~100 list calls/day,
well under quota; LLM calls only fire when the poll actually finds an
unprocessed message.

Same shared helper as the Pub/Sub handler and gmail_renew — single
fetch+dedup+process pipeline, three callers.

Wrapped in @critical_task because silent polling failures over multiple
hours could mean Jarvis is missing emails without anyone noticing. The
3-consecutive-failure alert catches it.
"""
import asyncio

from app.email.gmail_pubsub import sweep_recent_inbox
from app.scheduler.task_helpers import reset_async_state_for_task
from app.scheduler.task_wrapper import critical_task
from app.scheduler.tasks.inbound_health import mark_inbound_poll_success
from app.utils.logging import get_logger

logger = get_logger(__name__)


@critical_task(name="app.scheduler.tasks.gmail_check.check_gmail_inbox")
def check_gmail_inbox():
    """Poll Gmail INBOX as a Pub/Sub safety net."""
    asyncio.run(_check())


async def _check():
    await reset_async_state_for_task()

    swept = await sweep_recent_inbox(history_id=None)
    if swept > 0:
        logger.info("gmail_check_swept", recent_inbox_count=swept)

    # Heartbeat: this poll completed without error. The inbound-health canary
    # reads it — keying on poll success (not on captured email) so a quiet
    # inbox never false-alarms while a real failure (the Jun-11 invalid_grant)
    # is caught. Reached only if sweep_recent_inbox didn't raise.
    mark_inbound_poll_success()
