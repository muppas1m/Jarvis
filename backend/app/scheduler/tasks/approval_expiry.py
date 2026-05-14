"""Hourly sweeper — auto-rejects approvals whose expires_at has passed.
Resumes the paused graphs with a rejection so the agent can move on."""
import asyncio
from datetime import datetime, timezone
from sqlalchemy import select

from app.scheduler.celery_app import celery_app
from app.scheduler.task_helpers import reset_async_state_for_task
from app.db.engine import async_session
from app.db.models import PendingApproval
import structlog

logger = structlog.get_logger()


@celery_app.task(name="app.scheduler.tasks.approval_expiry.sweep_expired_approvals")
def sweep_expired_approvals():
    asyncio.run(_sweep())


async def _sweep():
    await reset_async_state_for_task()

    from app.messaging.router import route_approval_decision
    async with async_session() as session:
        result = await session.execute(
            select(PendingApproval).where(
                PendingApproval.status == "pending",
                PendingApproval.expires_at < datetime.now(timezone.utc),
            )
        )
        expired = result.scalars().all()

        for approval in expired:
            approval.status = "expired"
            approval.resolved_at = datetime.now(timezone.utc)
            approval.resolved_via = "system"
        await session.commit()
        logger.info("approval_expiry_swept", count=len(expired))

    # Resume each expired graph with a rejection (out of session)
    for approval in expired:
        try:
            platform = approval.thread_id.split(":", 1)[0] if ":" in approval.thread_id else "web"
            await route_approval_decision(
                approval.thread_id, platform,
                {"approved": False, "reason": "approval expired (no response within 24h)"},
            )
        except Exception as e:
            logger.error("expiry_resume_failed", approval_id=str(approval.id), error=str(e))
