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
from datetime import UTC, datetime
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Path, status
from pydantic import BaseModel, Field
from sqlalchemy import select, update

from app.db.engine import async_session
from app.db.models import PendingApproval
from app.email.approval_handler import EmailApprovalOutcome, is_email_approval
from app.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/approvals", tags=["approvals"])


async def resolve_approval(
    approval_id: str,
    action: str,
    resolved_via: str,
) -> str | None:
    """Atomically CLAIM + mark an approval, returning its thread_id ONLY to the
    call that transitions it out of ``pending``.

    Idempotency gate (Part B1): the resolve→side-effect (send a reply / resume a
    graph) must fire AT MOST ONCE per approval — a button+voice race or a retry
    must NOT send a duplicate email. The single conditional UPDATE
    (``WHERE id AND status='pending' RETURNING thread_id``) is the claim: under
    Postgres row locking, exactly one concurrent caller matches the still-pending
    row and gets the thread_id back; every other caller (already resolved, or
    lost the race) gets None and MUST NOT dispatch.

    Returns None for: a malformed id, a missing row, an already-resolved row, OR
    a lost claim race. The caller treats None as "nothing to do here."

    Args:
        approval_id: PendingApproval.id (UUID as string).
        action: "approve", "reject", or "discard" (superseded by an edit/revision —
            same atomic claim, so a concurrent approve can't race a discard).
        resolved_via: which channel completed the action ("telegram", "web", "voice").
    """
    _STATUS = {"approve": "approved", "reject": "rejected", "discard": "discarded"}
    if action not in _STATUS:
        raise ValueError(f"action must be one of {tuple(_STATUS)}, got {action!r}")

    try:
        approval_uuid = uuid.UUID(approval_id)
    except ValueError:
        logger.warning("resolve_approval_bad_uuid", approval_id=approval_id)
        return None

    new_status = _STATUS[action]
    async with async_session() as session:
        result = await session.execute(
            update(PendingApproval)
            .where(
                PendingApproval.id == approval_uuid,
                PendingApproval.status == "pending",
                # Expiry/staleness gate (Phase 3 invariant 7): an expired-but-not-
                # yet-swept row can't be claimed → can't execute. The atomic
                # WHERE makes the expiry check part of the SAME claim — no TOCTOU.
                PendingApproval.expires_at > datetime.now(UTC),
            )
            .values(status=new_status, resolved_at=datetime.now(UTC), resolved_via=resolved_via)
            .returning(PendingApproval.thread_id)
        )
        row = result.first()
        await session.commit()

    if row is None:
        # Missing OR already-resolved OR EXPIRED OR lost the claim race — no dispatch.
        logger.info("resolve_approval_not_claimed", approval_id=approval_id, action=action)
        return None
    logger.info(
        "approval_resolved",
        approval_id=approval_id, action=action, resolved_via=resolved_via, thread_id=row[0],
    )
    return row[0]


async def get_thread_decisions(thread_id: str) -> list[dict[str, Any]]:
    """All decision rows for a thread (ANY status), oldest first — the source for
    the dashboard's in-stream decision cards.

    Scoped to thread_id so another channel's approvals (e.g. a Telegram-origin
    decision) never leak into the web conversation. Each dict is positioned in the
    message stream by ``interrupt_id`` (== the proposing tool_call_id)."""
    async with async_session() as session:
        result = await session.execute(
            select(PendingApproval)
            .where(PendingApproval.thread_id == thread_id)
            .order_by(PendingApproval.created_at.asc())
        )
        rows = result.scalars().all()
    return [
        {
            "approval_id": str(r.id),
            "interrupt_id": r.interrupt_id,
            "tool_name": (r.payload or {}).get("tool_name") or r.action_type,
            "tool_args": (r.payload or {}).get("tool_args") or {},
            "description": r.description,
            "status": r.status,
            "created_at": r.created_at.isoformat() if r.created_at else "",
            "resolved_at": r.resolved_at.isoformat() if r.resolved_at else None,
        }
        for r in rows
    ]


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
    reason: str | None = Field(
        default=None,
        max_length=500,
        description="Optional rejection reason; surfaced in the audit trail.",
    )


class UnifiedApprovalCard(BaseModel):
    """One pending approval, normalized across BOTH origins for the unified queue.

    A superset of the frontend's ApprovalRequest (approval_id / tool_name /
    tool_args / description / status) plus the queue metadata it needs:

      - ``kind`` — "email" (inbound auto-drafted reply) or "tool" (chat-queued
        APPROVE-tier tool call). The SAME discriminator dispatch uses, so the
        card's kind always matches how /decide will actually route it.
      - ``approval_id`` — THE dedup key. A card surfaced in-stream the moment it
        was queued (3B) and the same card returned by this queue poll carry the
        identical approval_id, so the consumer presents it exactly once.
      - ``created_at`` — the stable oldest-first sort key (carried so the consumer
        can reason about ordering without a second read).

    Origin fields ride in ``tool_args``: an email card is {to, subject, body}
    (from the row's payload); a tool card is the real tool args. So the existing
    ApprovalCard renders both with no special-casing."""

    approval_id: str
    kind: Literal["email", "tool"]
    thread_id: str
    tool_name: str
    tool_args: dict
    description: str
    status: str
    created_at: str
    # True for a COMPLEX inbound email surfaced as a heads-up (no draft yet) — the card
    # renders "say go and I'll draft it" + "Draft it"/"Leave it" instead of Approve/Send.
    needs_drafting: bool = False


class ApprovalQueueResponse(BaseModel):
    """The full ordered queue + its size. The list (not just the head) is returned
    so the consumer can show "1 of N", dedup against in-stream cards, and skip/next
    — all client-side over one read, no second call. ``count`` == len(approvals);
    carried explicitly so the "N waiting" badge needs no derivation."""

    approvals: list[UnifiedApprovalCard]
    count: int


@router.get("/pending", response_model=list[PendingApprovalView])
async def list_pending_approvals() -> list[PendingApprovalView]:
    """All approvals currently awaiting a decision, oldest first.

    Filters out expired rows (expires_at <= now) so the dashboard never
    surfaces stale approvals as actionable. Phase 1 has no expiry sweeper;
    expired rows accumulate in the table but are invisible here. A Phase
    3 Celery job sweeps them (and updates status='expired' so audit
    queries still see the trail). Single-master Phase 1 has no per-user
    filter — every pending approval belongs to the master."""
    now = datetime.now(UTC)
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


def _unified_card(row: PendingApproval) -> UnifiedApprovalCard:
    """Normalize a PendingApproval row into the unified card. The kind predicate is
    the SAME compound check dispatch_approval uses (action_type=="email_reply" OR
    an email-origin thread_id) so a card never claims a kind dispatch would route
    differently. Origin fields go into tool_args — email → {to, subject, body} from
    the payload; tool → the real tool args — so the renderer needs no per-kind branch."""
    payload = row.payload or {}
    is_email = row.action_type == "email_reply" or is_email_approval(row.thread_id)
    needs_drafting = bool(payload.get("needs_drafting"))
    if is_email:
        tool_name = row.action_type
        # "original" = the email being replied to (always shown); "body" = the draft
        # (omitted until drafted, so the card shows just the email + the heads-up).
        tool_args = {
            "to": payload.get("sender", ""),
            "subject": payload.get("subject", ""),
            "original": payload.get("body", ""),
        }
        if not needs_drafting:
            tool_args["body"] = payload.get("draft", "")
    else:
        tool_name = payload.get("tool_name") or row.action_type
        tool_args = payload.get("tool_args") or {}
    return UnifiedApprovalCard(
        approval_id=str(row.id),
        kind="email" if is_email else "tool",
        thread_id=row.thread_id,
        tool_name=tool_name,
        tool_args=tool_args,
        description=row.description,
        status=row.status,
        created_at=row.created_at.isoformat() if row.created_at else "",
        needs_drafting=needs_drafting,
    )


@router.get("/queue", response_model=ApprovalQueueResponse)
async def approval_queue() -> ApprovalQueueResponse:
    """The unified one-at-a-time approval QUEUE over BOTH origins — inbound email
    replies AND chat-queued APPROVE-tier tool calls — oldest-first, pending and
    unexpired, each row normalized to a UnifiedApprovalCard.

    PURE READ. It never claims or dispatches anything (resolve_and_dispatch /
    dispatch_approval are untouched), so the cutover's exactly-once and the email
    taxonomy stay frozen — this only SURFACES what is already queued.

    The contract the consumer (3B present-in-moment + 3C poll) composes on:
      - ORDER is stable oldest-first (created_at asc). A freshly chat-queued card
        is the NEWEST, so it sits at the BACK of this queue — yet 3B surfaces it
        in-stream the instant it's queued. The two don't fight: one-at-a-time means
        the in-stream card suppresses the poll until it resolves, and dedup keeps
        the poll from re-surfacing it.
      - approval_id is THE dedup key across both surfaces.
      - The full ordered list + count come back in one read so the consumer does
        "1 of N", dedup, and skip/next without a second call."""
    now = datetime.now(UTC)
    async with async_session() as session:
        result = await session.execute(
            select(PendingApproval)
            .where(PendingApproval.status == "pending")
            .where(PendingApproval.expires_at > now)
            .order_by(PendingApproval.created_at.asc())
        )
        rows = result.scalars().all()

    cards = [_unified_card(row) for row in rows]
    return ApprovalQueueResponse(approvals=cards, count=len(cards))


@router.post("/{approval_id}/decide")
async def decide_approval(
    body: DecideRequest,
    approval_id: str = Path(..., description="PendingApproval row UUID"),
) -> dict[str, Any]:
    """Record the master's decision and resolve it through the ONE claim-then-
    dispatch gate (``resolve_and_dispatch``), unified across every approval origin
    (Phase 3). The gate atomically claims the row and executes ONLY if this call
    won the claim — chat-queued tool calls and inbound-email replies both resolve
    here, executing out-of-band (no graph resume, no interrupt).

    Returns the TurnEnvelope shape /api/chat returns: status="complete" on a clean
    resolution (the deterministic outcome text in `response`), "error" on a
    failure. A lost claim (already resolved / expired) → 404."""
    from app.agent.approval_dispatch import resolve_and_dispatch

    action = "approve" if body.approved else "reject"
    decision: dict[str, Any] = {"approved": body.approved}
    if not body.approved and body.reason:
        decision["reason"] = body.reason

    outcome = await resolve_and_dispatch(approval_id, action, "web", decision)
    if outcome.status == "not_claimed":
        # Lost claim: bad UUID / not found / already resolved / EXPIRED. All
        # surface as 404 — the caller refreshes /pending; the tool NEVER ran.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="approval not found or already resolved",
        )
    if outcome.kind == "draft_request":
        # Heads-up "go"→draft / "leave it" — not a send; surface the drafted/left line.
        ok = outcome.status in ("drafted", "left")
        return _decide_envelope(outcome.thread_id, "complete" if ok else "error", outcome.detail)
    if outcome.kind == "email":
        return _email_decide_envelope(outcome.thread_id, outcome.email_outcome)
    return _tool_decide_envelope(outcome.thread_id, outcome)


def _tool_decide_envelope(thread_id: str, outcome: Any) -> dict[str, Any]:
    """Render a tool-call execute-on-approve outcome into the dashboard's
    TurnEnvelope fields. The tool's own result string is the deterministic
    confirmation (e.g. "Email sent to X", "Event created …", or a [QUEUED]-class
    failure marker)."""
    if outcome.status == "executed":
        return _decide_envelope(
            thread_id, "complete" if outcome.success else "error", outcome.detail
        )
    if outcome.status == "rejected":
        return _decide_envelope(thread_id, "complete", "Discarded, Sir.")
    if outcome.status == "blocked":
        return _decide_envelope(thread_id, "error", "That action isn't permitted.")
    return _decide_envelope(thread_id, "error", "That approval is no longer actionable.")


def _email_decide_envelope(thread_id: str, outcome: EmailApprovalOutcome) -> dict[str, Any]:
    """Render an inbound-email-approval outcome into the minimal TurnEnvelope
    fields the dashboard's decide handler reads (status + response; no chained
    interrupt). Distinct wording from the Telegram alert by design — same
    resolution core, per-transport presentation."""
    if outcome.status == "sent":
        return _decide_envelope(thread_id, "complete", f"✅ Reply sent to {outcome.recipient}.")
    if outcome.status == "rejected":
        return _decide_envelope(thread_id, "complete", "Discarded — I left the email in your inbox.")
    if outcome.status == "send_failed":
        return _decide_envelope(
            thread_id, "error", f"❌ I couldn't send that reply: {outcome.detail}"
        )
    if outcome.status == "send_uncertain":
        # Maybe-delivered — soft (complete, not a red error) but distinctly honest.
        return _decide_envelope(
            thread_id, "complete",
            "⚠️ I couldn't confirm that send — it may have gone out. Worth checking your Sent folder.",
        )
    # row_missing / payload_incomplete — the row was just resolved, so this is a
    # data problem worth surfacing rather than a silent success.
    return _decide_envelope(
        thread_id, "error", "❌ That reply couldn't be dispatched — its stored draft data is incomplete."
    )


def _decide_envelope(thread_id: str, status_: str, response: str) -> dict[str, Any]:
    return {
        "thread_id": thread_id,
        "status": status_,
        "response": response,
        "interrupt": None,
    }
