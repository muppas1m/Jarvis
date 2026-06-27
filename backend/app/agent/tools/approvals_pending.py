"""approvals_pending — the agent's read of the approval queue (Phase 4).

SAFE: a pure read of the SAME ``list_pending_cards()`` the HUD's GET /approvals/queue
reads, rendered to readable text. So "what's pending / what did you draft / show me the
approvals" answers identically whether or not a card is currently on screen — the agent
and the dashboard can't drift. It never sends or approves; the master still decides via
the cards/buttons.
"""
from pydantic import BaseModel

from app.agent.tools.registry import tool_registry
from app.approvals_service import list_pending_cards, render_for_agent
from app.config import settings
from app.utils.logging import get_logger

logger = get_logger(__name__)


async def approvals_pending() -> str:
    """List everything awaiting the master's approval, as readable text. A read failure →
    a graceful line (never errors the turn)."""
    h = settings.MASTER_HONORIFIC
    try:
        cards = await list_pending_cards()
    except Exception as exc:  # noqa: BLE001 — a read failure → a graceful, vague line
        logger.warning("approvals_pending_failed", error=str(exc))
        return f"I couldn't check your approval queue just now, {h}."
    return render_for_agent(cards, h)


class _ApprovalsPendingArgs(BaseModel):
    pass  # no arguments — it always reports the whole pending queue


def register() -> None:
    tool_registry.register(
        name="approvals_pending",
        handler=approvals_pending,
        description=(
            "List everything awaiting the master's approval — queued email sends, "
            "auto-drafted inbound replies, and any other action paused for a yes/no — as "
            "readable text (recipient, subject and a snippet for emails; the action, its "
            "key details and age for others). "
            "Use for: 'what's pending', \"what's in my approval queue\", 'what did you "
            "draft', 'what are the pending draft emails', 'what did you queue', \"what's "
            "waiting on me\", 'show me the approvals', 'anything to approve', 'do I have "
            "anything to sign off on'. "
            "PURE READ — it never sends or approves anything; the master still decides via "
            "the cards/buttons. Does NOT search past/sent/received emails — for email "
            "history use email_history_search. Does NOT brief on new emails (use "
            "'briefing') or list tasks (use task_list)."
        ),
        args_schema=_ApprovalsPendingArgs,
    )
