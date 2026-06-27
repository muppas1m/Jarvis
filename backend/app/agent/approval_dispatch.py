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

Wired into EVERY transport through the single ``resolve_and_dispatch`` gate
(dashboard ``decide_approval``, Telegram ``_on_callback``, the voice/typed
presented-card resolvers). The cutover that retired ``interrupt()`` and routes
ALL tool-call resolution here has landed; there is no graph resume anymore.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from typing import Any, Literal

from sqlalchemy import select, update

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

    kind: Literal["email", "tool", "none", "draft_request"]
    status: str  # tool: DispatchStatus ; email: EmailApprovalOutcome.status ; draft_request: drafted|left|draft_failed
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
    outcome = await dispatch_approval(approval_id, decision)
    # Restore what the non-blocking cutover dropped: make the action's fate durable (on the
    # row) + visible (grounded into the conversation thread). Runs in the ONE gate so it
    # covers EVERY channel (dashboard / Telegram / voice / typed) and every APPROVE-tier
    # action generically. Best-effort — never alters the outcome the transport renders.
    await _record_outcome(approval_id, outcome)
    return outcome


def _clean_detail(detail: str) -> str:
    """A short, human, single-line outcome detail — strip a leading ``[TAG]`` marker
    (``[ERROR]`` / ``[QUEUED]`` …), collapse whitespace, cap length."""
    s = re.sub(r"^\s*\[[A-Z_]+\]\s*", "", detail or "")
    return " ".join(s.split())[:1000]


def _terminal_outcome(outcome: ApprovalDispatchOutcome) -> tuple[str, str] | None:
    """Map a dispatch result to (terminal_status, detail) to persist, or None to SKIP —
    rejected / row_missing / not_claimed / the draft-request sub-flow are not action
    executions to record. ``executed`` = the action succeeded; ``failed`` = it didn't."""
    if outcome.kind == "tool":
        if outcome.status == "executed":
            return ("executed" if outcome.success else "failed", _clean_detail(outcome.detail))
        if outcome.status == "blocked":
            return ("failed", "That action isn't permitted.")
        return None
    if outcome.kind == "email":
        if outcome.status == "sent":
            return ("executed", _clean_detail(outcome.detail) or "Reply sent.")
        if outcome.status == "send_uncertain":
            # EmailSendUncertain — the send could NOT be confirmed. A DISTINCT terminal state,
            # never a clean ✅ "sent": the agent says "may have sent — I couldn't confirm".
            return ("unconfirmed",
                    _clean_detail(outcome.detail) or "The send couldn't be confirmed — it may have gone out.")
        if outcome.status in ("send_failed", "row_missing", "payload_incomplete"):
            return ("failed", _clean_detail(outcome.detail) or "Send failed.")
        return None  # rejected
    return None  # draft_request / none


async def _persist_outcome(approval_id: str, status: str, detail: str) -> None:
    """Persist the terminal dispatch outcome on the row (status executed/failed + the short
    detail) so the recent-outcomes read surfaces it across ALL channels — including HUD/
    Telegram-resolved actions that have no chat thread to ground. Best-effort."""
    try:
        aid = uuid.UUID(approval_id)
    except ValueError:
        return
    try:
        async with async_session() as session:
            await session.execute(
                update(PendingApproval)
                .where(PendingApproval.id == aid)
                .values(status=status, outcome_detail=detail or None)
            )
            await session.commit()
    except Exception as exc:  # noqa: BLE001 — outcome persistence is best-effort
        logger.warning("approval_outcome_persist_failed", approval_id=approval_id, error=str(exc))


async def _record_outcome(approval_id: str, outcome: ApprovalDispatchOutcome) -> None:
    """Persist the terminal outcome AND ground the conversation thread, generically for any
    APPROVE-tier action. Best-effort end-to-end — never affects the returned outcome."""
    terminal = _terminal_outcome(outcome)
    if terminal is None:
        return
    status, detail = terminal
    await _persist_outcome(approval_id, status, detail)

    # Ground the CONVERSATION thread (web / voice) so the agent knows next turn what
    # happened. Inbound-email threads aren't conversations the agent converses in → skip
    # (the persisted status + the recent-outcomes read cover those). The marker is a plain
    # AIMessage note — it never re-answers the original [QUEUED] tool_call (no double-answer).
    thread_id = outcome.thread_id
    if thread_id and not is_email_approval(thread_id):
        icon = {"executed": "✅", "failed": "❌", "unconfirmed": "⚠️"}.get(status, "•")
        default = {
            "executed": "Done.",
            "failed": "That action failed.",
            "unconfirmed": "The send couldn't be confirmed — it may have gone out.",
        }.get(status, "")
        marker = f"{icon} " + (detail or default)
        try:
            from app.agent.runner import note_approval_outcome
            await note_approval_outcome(thread_id, marker)
        except Exception as exc:  # noqa: BLE001 — grounding is best-effort
            logger.warning("approval_outcome_grounding_failed", thread_id=thread_id, error=str(exc))


async def _dispatch_email_draft_request(
    row: PendingApproval, decision: dict[str, Any]
) -> ApprovalDispatchOutcome:
    """Resolve a needs_drafting (complex-email heads-up) card. The row is already
    CLAIMED. Approve = DRAFT the reply now + re-queue a normal simple card (which the
    master approves to send); reject = leave it in the inbox. Drafting failure leaves
    no new card (the master re-asks) — never a send, never a half-state."""
    if not decision.get("approved"):
        logger.info("email_draft_request_left", approval_id=str(row.id))
        return ApprovalDispatchOutcome(
            kind="draft_request", status="left", thread_id=row.thread_id,
            detail="Left in your inbox.",
        )
    payload = row.payload or {}
    try:
        from app.email.inbound import requeue_drafted_email_card
        from app.email.responder import generate_draft

        draft = await generate_draft(
            subject=payload.get("subject", ""), sender=payload.get("sender", ""),
            body=payload.get("body", ""),
        )
        if not (draft or "").strip():
            raise ValueError("empty draft")
        await requeue_drafted_email_card(row, draft)
    except Exception as exc:  # noqa: BLE001 — never error the turn / never send
        logger.warning("email_draft_request_failed", approval_id=str(row.id), error=str(exc))
        return ApprovalDispatchOutcome(
            kind="draft_request", status="draft_failed", thread_id=row.thread_id,
            detail="I couldn't draft that one just now — ask me again and I'll redo it.",
        )
    logger.info("email_draft_request_drafted", approval_id=str(row.id))
    return ApprovalDispatchOutcome(
        kind="draft_request", status="drafted", success=True, thread_id=row.thread_id,
        detail="I've drafted it — it's queued for your approval.",
    )


def alert_text_for(outcome: ApprovalDispatchOutcome) -> str | None:
    """Master-facing Telegram alert text for a resolved outcome — None when there
    is nothing to announce (a lost claim, or a plain reject already shown by the
    message edit). Email reuses the unchanged ``channel_alert_for`` (preserving
    the maybe-delivered taxonomy); a tool reports its deterministic result."""
    if outcome.kind == "email" and outcome.email_outcome is not None:
        from app.email.approval_handler import channel_alert_for
        return channel_alert_for(outcome.email_outcome, outcome.thread_id)
    if outcome.kind == "draft_request":
        return outcome.detail or None  # "drafted / left / couldn't draft"
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

    payload = row.payload or {}
    is_email = row.action_type == "email_reply" or is_email_approval(row.thread_id)

    # Complex inbound email surfaced as a HEADS-UP (needs_drafting): "go" (approve) =
    # DRAFT it, not send. Draft + re-queue a normal simple card (the master approves
    # THAT to send); reject = leave it in the inbox. Nothing is sent here either way.
    if is_email and payload.get("needs_drafting"):
        return await _dispatch_email_draft_request(row, decision)

    # Inbound email (with a draft) → the untouched handler (its own approve/reject +
    # taxonomy). Pass the claimed approval_id so the SPECIFIC row sends — after a REVISE
    # the discarded original + the new card share a thread_id (a thread_id query would
    # match both). row.id == this approval_id (we loaded it by id above).
    if is_email:
        outcome = await dispatch_email_approval(row.thread_id, decision, approval_id=approval_id)
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
