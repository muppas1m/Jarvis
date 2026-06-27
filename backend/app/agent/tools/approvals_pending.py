"""approvals_pending — the agent's read of the approval queue + recent outcomes (Phase 4).

SAFE: a pure read of the SAME shared service the HUD reads — ``list_pending_cards()`` (GET
/approvals/queue) for what's AWAITING a decision, plus ``list_recent_outcomes()`` for what
HAPPENED to actions the master already approved (sent / created / failed). So "what's
pending" AND "did that email send / what happened to that?" answer identically whether or
not a card is on screen, and across channels — the agent and the dashboard can't drift. It
never sends or approves; the master still decides via the cards/buttons.
"""
from pydantic import BaseModel

from app.agent.tools.registry import tool_registry
from app.approvals_service import (
    list_pending_cards,
    list_recent_outcomes,
    render_for_agent,
    render_outcomes_for_agent,
)
from app.config import settings
from app.utils.logging import get_logger

logger = get_logger(__name__)


async def approvals_pending() -> str:
    """What's awaiting approval AND what recently happened to approved actions, as readable
    text. A read failure → a graceful line (never errors the turn)."""
    h = settings.MASTER_HONORIFIC
    try:
        pending = await list_pending_cards()
        outcomes = await list_recent_outcomes()
    except Exception as exc:  # noqa: BLE001 — a read failure → a graceful, vague line
        logger.warning("approvals_pending_failed", error=str(exc))
        return f"I couldn't check your approval queue just now, {h}."
    out = render_for_agent(pending, h)
    resolved = render_outcomes_for_agent(outcomes, h)
    return f"{out}\n\n{resolved}" if resolved else out


class _ApprovalsPendingArgs(BaseModel):
    pass  # no arguments — it always reports the whole pending queue


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
