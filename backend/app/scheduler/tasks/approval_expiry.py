"""Hourly sweeper — auto-rejects approvals whose expires_at has passed.
Resumes the paused graphs with a rejection so the agent can move on.

Wrapped in @critical_task because a silently-failing sweep leaves interrupted
turns stuck mid-graph (paused on the original interrupt) AND lets stale
approvals accumulate without bound. Both are the exact 3-day-silent-regression
risk that `feedback_verify_before_claiming.md` originated on this surface to
prevent. Sibling discipline to email_check / email_renew / morning_brief
wrappers — every belt-and-braces scheduled task should be fail-loud."""
import asyncio
from datetime import UTC, datetime

import structlog
from sqlalchemy import select

from app.db.engine import async_session
from app.db.models import PendingApproval
from app.scheduler.task_helpers import reset_async_state_for_task
from app.scheduler.task_wrapper import critical_task

logger = structlog.get_logger()


@critical_task(name="app.scheduler.tasks.approval_expiry.sweep_expired_approvals")
def sweep_expired_approvals():
    """Wrapped in @critical_task — alerts master after 3 failed runs."""
    asyncio.run(_sweep())


async def _sweep():
    await reset_async_state_for_task()

    async with async_session() as session:
        result = await session.execute(
            select(PendingApproval).where(
                PendingApproval.status == "pending",
                PendingApproval.expires_at < datetime.now(UTC),
            )
        )
        expired = result.scalars().all()

        for approval in expired:
            approval.status = "expired"
            approval.resolved_at = datetime.now(UTC)
            approval.resolved_via = "system"
        await session.commit()
        logger.info("approval_expiry_swept", count=len(expired))

    # Phase 3: marking the row 'expired' IS the cleanup. There is no paused graph
    # to resume (APPROVE-tier tools no longer interrupt), and the atomic claim's
    # `expires_at > now()` gate already prevents any expired row from executing
    # (invariant 7) — so no resume/route-to-reject step is needed anymore.
