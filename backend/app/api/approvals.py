"""
Approvals API + helpers.

Two surfaces in this module:

  resolve_approval(approval_id, action, resolved_via)
      Helper. Updates the pending_approvals row with the master's decision
      and returns the thread_id so the caller can resume the graph. Used
      by BOTH the Telegram inline-button callback (in
      messaging/channels/telegram.py) AND the dashboard POST below —
      single helper, two transports.

  router (FastAPI)
      GET  /approvals/pending           — list approvals awaiting decision
      POST /approvals/{id}/decide       — record decision + resume graph

The router endpoints are mounted under the protected_router so they
inherit Depends(get_current_user). The decide endpoint is synchronous
and returns the same TurnEnvelope shape as /api/chat — the resume IS
a turn continuation and clients render it with the same code path. If
the resumed chain hits another interrupt() (chained HITL), the response
carries status="interrupted" with the new approval_id and the dashboard
loops back to present the next decision.
"""
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Path, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agent.runner import resume_turn
from app.db.engine import async_session
from app.db.models import PendingApproval
from app.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/approvals", tags=["approvals"])


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


# --------------------------------------------------------------------------- #
# HTTP API                                                                    #
# --------------------------------------------------------------------------- #


class PendingApprovalView(BaseModel):
    """Wire shape for a pending approval row."""

    id: str
    thread_id: str
    action_type: str
    description: str
    payload: dict
    created_at: str
    expires_at: str


class DecideRequest(BaseModel):
    approved: bool
    reason: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Optional rejection reason; surfaced in the audit trail.",
    )


@router.get("/pending", response_model=list[PendingApprovalView])
async def list_pending_approvals() -> list[PendingApprovalView]:
    """All approvals currently awaiting a decision, oldest first.

    Filters out expired rows (expires_at <= now) so the dashboard never
    surfaces stale approvals as actionable. Phase 1 has no expiry sweeper;
    expired rows accumulate in the table but are invisible here. A Phase
    3 Celery job sweeps them (and updates status='expired' so audit
    queries still see the trail). Single-master Phase 1 has no per-user
    filter — every pending approval belongs to the master."""
    now = datetime.now(timezone.utc)
    async with async_session() as session:
        result = await session.execute(
            select(PendingApproval)
            .where(PendingApproval.status == "pending")
            .where(PendingApproval.expires_at > now)
            .order_by(PendingApproval.created_at.asc())
        )
        rows = result.scalars().all()

    return [
        PendingApprovalView(
            id=str(row.id),
            thread_id=row.thread_id,
            action_type=row.action_type,
            description=row.description,
            payload=row.payload or {},
            created_at=row.created_at.isoformat() if row.created_at else "",
            expires_at=row.expires_at.isoformat() if row.expires_at else "",
        )
        for row in rows
    ]


@router.post("/{approval_id}/decide")
async def decide_approval(
    body: DecideRequest,
    approval_id: str = Path(..., description="PendingApproval row UUID"),
) -> dict[str, Any]:
    """Record the master's decision, then resume the paused graph.

    Returns the same TurnEnvelope shape /api/chat returns. status="complete"
    means the resumed chain finished cleanly. status="interrupted" means
    the chain hit ANOTHER interrupt() — the response carries the new
    approval payload and the dashboard renders the next decision UI."""
    action = "approve" if body.approved else "reject"
    thread_id = await resolve_approval(
        approval_id=approval_id,
        action=action,
        resolved_via="web",
    )
    if thread_id is None:
        # Either bad UUID or row not found. Both surface as 404 — the
        # caller's job is to refresh /pending; we don't differentiate
        # because both states tell them the same thing ("this approval
        # is no longer actionable").
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="approval not found or already resolved",
        )

    decision: dict[str, Any] = {"approved": body.approved}
    if not body.approved and body.reason:
        decision["reason"] = body.reason

    return await resume_turn(thread_id=thread_id, decision=decision)
