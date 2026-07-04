"""approvals_pending — the agent's read of the approval queue + recent outcomes (Phase 4).

SAFE: a pure read of the SAME shared service the HUD reads — ``list_pending_cards()`` (GET
/approvals/queue) for what's AWAITING a decision, plus ``list_recent_outcomes()`` for what
HAPPENED to actions the master already approved (sent / created / failed). So "what's
pending" AND "did that email send / what happened to that?" answer identically whether or
not a card is on screen, and across channels — the agent and the dashboard can't drift. It
never sends or approves; the master still decides via the cards/buttons.

D6 (A2 s0): a ``kind`` filter — "pending calendar approvals?" answers with CALENDAR cards
only, not the whole queue. Flat string ("email" | "calendar" | "" = all) per the
open-weights schema doctrine (no Optional / anyOf).
"""
from pydantic import BaseModel, Field

from app.agent.tools.registry import tool_registry
from app.approvals_service import (
    UnifiedApprovalCard,
    list_pending_cards,
    list_recent_outcomes,
    render_for_agent,
    render_outcomes_for_agent,
)
from app.config import settings
from app.utils.logging import get_logger

logger = get_logger(__name__)


def _matches_kind(card: UnifiedApprovalCard, kind: str) -> bool:
    """Deterministic kind test over the card's structured fields (never its prose):
    email = the unified email kind (chat-queued sends + inbound replies);
    calendar = the calendar_* tool family."""
    if kind == "email":
        return card.kind == "email"
    if kind == "calendar":
        return card.tool_name.startswith("calendar_")
    return True  # unknown/empty → no filter (never hide the queue on a bad arg)


async def approvals_pending(kind: str = "") -> str:
    """What's awaiting approval AND what recently happened to approved actions, as readable
    text — optionally filtered to one kind. A read failure → a graceful line (never errors
    the turn)."""
    h = settings.MASTER_HONORIFIC
    kind = (kind or "").strip().lower()
    try:
        pending = await list_pending_cards()
        outcomes = await list_recent_outcomes()
    except Exception as exc:  # noqa: BLE001 — a read failure → a graceful, vague line
        logger.warning("approvals_pending_failed", error=str(exc))
        return f"I couldn't check your approval queue just now, {h}."
    if kind in ("email", "calendar"):
        # outcomes are UnifiedApprovalCards too — the ONE kind test covers both lists
        pending = [c for c in pending if _matches_kind(c, kind)]
        outcomes = [o for o in outcomes if _matches_kind(o, kind)]
        if not pending and not outcomes:
            return f"No {kind} approvals are awaiting your decision, {h}."
        if not pending:
            return render_outcomes_for_agent(outcomes, h) or (
                f"No {kind} approvals are awaiting your decision, {h}.")
    out = render_for_agent(pending, h)
    resolved = render_outcomes_for_agent(outcomes, h)
    return f"{out}\n\n{resolved}" if resolved else out


class _ApprovalsPendingArgs(BaseModel):
    kind: str = Field(
        default="",
        description=(
            "Filter by approval kind: 'email' (queued sends + drafted replies), 'calendar' "
            "(event create/update/delete), or '' for the whole queue. Use the kind the "
            "master asked about — 'pending calendar approvals?' -> 'calendar'."
        ),
    )


def register() -> None:
    tool_registry.register(
        name="approvals_pending",
        handler=approvals_pending,
        description=(
            "The master's approval queue AND what happened to actions they already "
            "approved. Reports two things: (a) everything AWAITING approval — queued email "
            "sends, auto-drafted inbound replies, any action paused for a yes/no; and (b) "
            "RECENT OUTCOMES — whether an approved action succeeded or FAILED (the email "
            "sent / the event was created / it failed and why). "
            "Takes an optional kind filter ('email' | 'calendar') — when the master asks "
            "about ONE kind ('pending calendar approvals?', 'any email drafts waiting?'), "
            "pass it so the answer covers only that kind. "
            "Use for: 'what's pending', \"what's in my approval queue\", 'what did you "
            "draft', 'what are the pending draft emails', 'show me the approvals', "
            "'anything to approve'; AND 'did that email send', 'did it go through', 'what "
            "happened to that', \"what's the failure / the error / what went wrong\", 'did "
            "the calendar event get created'. "
            "PURE READ — it never sends or approves anything; the master still decides via "
            "the cards/buttons. Does NOT search past/sent/received emails — for email "
            "history use email_history_search. Does NOT brief on new emails (use "
            "'briefing') or list tasks (use task_list)."
        ),
        args_schema=_ApprovalsPendingArgs,
        capability="Tell you what's awaiting your approval and what happened to actions you approved.",
    )
