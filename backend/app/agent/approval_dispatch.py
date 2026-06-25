"""Generic execute-on-approve dispatcher (Phase 3 — Step 1).

Resolves a CLAIMED ``PendingApproval`` into its real-world action, dispatching by
the row's shape:

  - ``action_type == "email_reply"`` (or a legacy ``email:``/``gmail:`` thread) →
    the inbound-email handler ``dispatch_email_approval``, UNTOUCHED — preserving
    its idempotent send + the maybe-delivered/definite taxonomy across surfaces.
  - any other ``action_type`` (a tool name) → the shared guarded execution
    ``execute_tool_guarded`` → the tool registry → the SAME send path for
    ``email_send`` — with a safety RE-CLASSIFY as defense-in-depth (a tool that
    has since become BLOCKED must not execute on approve).

IDEMPOTENCY is the CALLER's job. ``resolve_approval``'s atomic claim
(``UPDATE … WHERE status='pending' AND expires_at > now() RETURNING``) gates this:
the dispatcher runs only for the call that WON the claim, so a tool executes at
most once across any resolve path / race / retry. This module assumes the claim
already succeeded; it never re-claims, and never re-checks expiry (the claim did).

NOT wired into ``decide_approval`` / ``route_approval_decision`` yet — Step 1
builds + tests this in isolation. The cutover that retires ``interrupt()`` and
routes ALL tool-call resolution here is Step 2.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import select

from app.agent.safety import SafetyClassifier, SafetyLevel
from app.db.engine import async_session
from app.db.models import PendingApproval
from app.email.approval_handler import (
    EmailApprovalOutcome,
    dispatch_email_approval,
    is_email_approval,
)
from app.utils.logging import get_logger

logger = get_logger(__name__)
_safety = SafetyClassifier()

DispatchStatus = Literal["executed", "rejected", "row_missing", "blocked", "not_claimed"]


@dataclass(frozen=True)
class ApprovalDispatchOutcome:
    """Result of resolving one approval. ``kind`` tells the caller which renderer
    to use; for an email row it carries the original ``EmailApprovalOutcome`` so
    the existing 4-surface maybe-delivered taxonomy is rendered verbatim (no
    regression). ``kind="none"`` + ``status="not_claimed"`` means the claim was
    lost (already resolved / expired / gone) — the caller must NOT dispatch."""

    kind: Literal["email", "tool", "none"]
    status: str  # tool: DispatchStatus ; email: the EmailApprovalOutcome.status
    detail: str = ""  # the tool result string / a short rendered detail
    success: bool = False
    thread_id: str = ""
    email_outcome: EmailApprovalOutcome | None = None


_NOT_CLAIMED = ApprovalDispatchOutcome(kind="none", status="not_claimed")


async def resolve_and_dispatch(
    approval_id: str, action: str, resolved_via: str, decision: dict[str, Any]
) -> ApprovalDispatchOutcome:
    """THE single claim-then-dispatch gate every transport (dashboard / Telegram /
    voice / typed) calls. It atomically CLAIMS the approval (``resolve_approval``)
    and dispatches ONLY if THIS call won the claim.

    This is the cutover invariant (no double-execution): a raw ``dispatch_approval``
    anywhere else is a hole, so the gate lives in ONE function — it is structurally
    impossible to dispatch an unclaimed approval through it. On a lost claim
    (already resolved / expired / missing) it returns ``not_claimed`` and the tool
    NEVER runs."""
    from app.api.approvals import resolve_approval  # lazy — avoid an import cycle

    thread_id = await resolve_approval(approval_id, action, resolved_via)
    if thread_id is None:
        logger.info("resolve_and_dispatch_not_claimed", approval_id=approval_id, action=action)
        return _NOT_CLAIMED
    return await dispatch_approval(approval_id, decision)


def alert_text_for(outcome: ApprovalDispatchOutcome) -> str | None:
    """Master-facing Telegram alert text for a resolved outcome — None when there
    is nothing to announce (a lost claim, or a plain reject already shown by the
    message edit). Email reuses the unchanged ``channel_alert_for`` (preserving
    the maybe-delivered taxonomy); a tool reports its deterministic result."""
    if outcome.kind == "email" and outcome.email_outcome is not None:
        from app.email.approval_handler import channel_alert_for
        return channel_alert_for(outcome.email_outcome, outcome.thread_id)
    if outcome.kind == "tool":
        if outcome.status == "executed":
            return outcome.detail if outcome.success else f"❌ {outcome.detail}"
        if outcome.status == "blocked":
            return "❌ That action isn't permitted."
    return None  # rejected / row_missing / not_claimed → no follow-up


async def _load_approval(approval_id: str) -> PendingApproval | None:
    try:
        aid = uuid.UUID(approval_id)
    except ValueError:
        return None
    async with async_session() as session:
        result = await session.execute(
            select(PendingApproval).where(PendingApproval.id == aid)
        )
        return result.scalar_one_or_none()


async def dispatch_approval(approval_id: str, decision: dict[str, Any]) -> ApprovalDispatchOutcome:
    """Execute the action for a CLAIMED approval (the caller already won the
    atomic claim). Dispatches by row shape. On reject, no side effect."""
    row = await _load_approval(approval_id)
    if row is None:
        logger.warning("dispatch_approval_row_missing", approval_id=approval_id)
        return ApprovalDispatchOutcome(kind="tool", status="row_missing")

    # Inbound email → the untouched handler (its own approve/reject + taxonomy).
    if row.action_type == "email_reply" or is_email_approval(row.thread_id):
        outcome = await dispatch_email_approval(row.thread_id, decision)
        return ApprovalDispatchOutcome(
            kind="email",
            status=outcome.status,
            detail=outcome.detail,
            success=(outcome.status == "sent"),
            thread_id=row.thread_id,
            email_outcome=outcome,
        )

    # Tool-call approval.
    if not decision.get("approved"):
        logger.info("dispatch_approval_rejected", approval_id=approval_id, tool=row.action_type)
        return ApprovalDispatchOutcome(kind="tool", status="rejected", thread_id=row.thread_id)

    payload = row.payload or {}
    tool_name = payload.get("tool_name") or row.action_type
    tool_args = payload.get("tool_args") or {}

    # Defense-in-depth: re-classify at execute-time. A tool that's since become
    # BLOCKED must NOT execute on approve, even though it was APPROVE-tier when
    # queued. (Safety still gates — invariant 5.)
    level = _safety.classify(tool_name, tool_args)
    if level == SafetyLevel.BLOCKED:
        logger.warning("dispatch_approval_now_blocked", approval_id=approval_id, tool=tool_name)
        return ApprovalDispatchOutcome(kind="tool", status="blocked", thread_id=row.thread_id)

    # Lazy import — execute_tool_guarded lives in the graph-node module; importing
    # it at module scope would drag the whole graph in (and risk a cycle).
    from app.agent.nodes import execute_tool_guarded

    exec_result = await execute_tool_guarded(
        row.thread_id, tool_name, tool_args, level=level, tool_call_id=row.interrupt_id,
    )
    logger.info(
        "dispatch_approval_executed",
        approval_id=approval_id, tool=tool_name, success=exec_result.success,
    )
    return ApprovalDispatchOutcome(
        kind="tool", status="executed", detail=exec_result.content,
        success=exec_result.success, thread_id=row.thread_id,
    )
