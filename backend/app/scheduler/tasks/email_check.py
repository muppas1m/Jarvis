"""15-min inbox safety-net poll (provider-agnostic).

A provider push (Gmail Pub/Sub today) is at-least-once for messages the broker
accepted, but doesn't cover the provider's own internal publisher failures (rare
but real). This poll closes the gap: list recent inbox messages, dedup against
email_logs, process anything new. Cheap; LLM calls only fire on a genuinely
unprocessed message.

Same shared ``sweep_recent_inbox`` pipeline as the push handler + email_renew.

Wrapped in @critical_task because silent polling failures over hours could mean
Jarvis is missing emails unnoticed; the 3-consecutive-failure alert catches it.
"""
import asyncio

from app.email.inbound import sweep_recent_inbox
from app.scheduler.task_helpers import reset_async_state_for_task
from app.scheduler.task_wrapper import critical_task
from app.scheduler.tasks.inbound_health import mark_inbound_poll_success
from app.utils.logging import get_logger

logger = get_logger(__name__)


@critical_task(name="app.scheduler.tasks.email_check.check_inbox")
def check_inbox():
    """Poll the configured provider's inbox as a push safety net."""
    asyncio.run(_check())


async def _check():
    await reset_async_state_for_task()

    swept = await sweep_recent_inbox()
    if swept > 0:
        logger.info("email_check_swept", recent_inbox_count=swept)

    # Heartbeat: this poll completed without error. The inbound-health canary
    # reads it — keying on poll success (not on captured email) so a quiet inbox
    # never false-alarms while a real failure is caught.
    mark_inbound_poll_success()
