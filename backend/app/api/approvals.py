"""
Approvals API + helpers.

This module currently contains only the helper `resolve_approval()` that
the Telegram callback handler calls when the master clicks Approve/Reject.
It updates the `pending_approvals` row with the master's decision and
returns the thread_id so the caller can resume the graph.

Turn 12 will extend this module with the proper API router endpoints
(`GET /approvals/pending`, `POST /approvals/{id}/decide`) for the web
dashboard. The router import in `main.py` is gated behind a try/except
until Turn 12 lands the router declaration.
"""
import uuid
from datetime import datetime, timezone

from sqlalchemy import select

from app.db.engine import async_session
from app.db.models import PendingApproval
from app.utils.logging import get_logger

logger = get_logger(__name__)


async def resolve_approval(
    approval_id: str,
    action: str,
    resolved_via: str,
) -> str | None:
    """Mark an approval as approved/rejected and return its thread_id.

    Returns None if the approval row doesn't exist (already cleaned up,
    expired, or a stale callback). Returning None signals to the caller
    that there's nothing to resume.

    Args:
        approval_id: PendingApproval.id (UUID as string).
        action: "approve" or "reject".
        resolved_via: which channel completed the action ("telegram", "web", ...).
    """
    if action not in ("approve", "reject"):
        raise ValueError(f"action must be 'approve' or 'reject', got {action!r}")

    try:
        approval_uuid = uuid.UUID(approval_id)
    except ValueError:
        logger.warning("resolve_approval_bad_uuid", approval_id=approval_id)
        return None

    async with async_session() as session:
        result = await session.execute(
            select(PendingApproval).where(PendingApproval.id == approval_uuid)
        )
        approval = result.scalar_one_or_none()
        if approval is None:
            logger.warning("resolve_approval_not_found", approval_id=approval_id)
            return None

        if approval.status != "pending":
            # Idempotent — a duplicate Approve click won't error, but we
            # don't re-write the resolution metadata either.
            logger.info(
                "resolve_approval_already_resolved",
                approval_id=approval_id,
                current_status=approval.status,
            )
            return approval.thread_id

        approval.status = "approved" if action == "approve" else "rejected"
        approval.resolved_at = datetime.now(timezone.utc)
        approval.resolved_via = resolved_via
        await session.commit()
        logger.info(
            "approval_resolved",
            approval_id=approval_id,
            action=action,
            resolved_via=resolved_via,
            thread_id=approval.thread_id,
        )
        return approval.thread_id
