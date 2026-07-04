"""ONE shared read surface for pending approvals — so the HUD and the agent can't drift.

This is the first instance of a standing pattern: every surface the HUD shows should be
readable by the agent through ONE function, so the two answer identically. Here the
pending-approvals query AND the row→card content mapping live in exactly one place,
called by:

  - ``GET /approvals/queue`` (the HUD)            — app/api/approvals.py
  - the ``approvals_pending`` agent tool          — app/agent/tools/approvals_pending.py
  - ``runner._pending_queue_summary`` (voice/text) — app/agent/runner.py

So "what's pending / what did you draft / show me the approvals" answers the same whether
or not a card happens to be on screen. PURE READ — nothing here claims or dispatches.
"""
from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import BaseModel
from sqlalchemy import select

from app.db.engine import async_session
from app.db.models import PendingApproval
from app.email.approval_handler import is_email_approval


class UnifiedApprovalCard(BaseModel):
    """One pending approval, normalized across BOTH origins for the unified queue.

    ``kind`` — "email" (an inbound auto-drafted reply OR a chat-queued ``email_send``)
    or "tool" (any other APPROVE-tier action). The discriminator the HUD card AND the
    agent renderer both branch on, so a card never claims a kind one surface would show
    differently. Origin fields ride in ``tool_args`` (email → {to, subject, body}; tool →
    the real args) so the frontend ApprovalCard renders both with no special-casing.
    ``approval_id`` is THE dedup key; ``created_at`` the stable oldest-first sort key."""

    approval_id: str
    kind: Literal["email", "tool"]
    thread_id: str
    tool_name: str
    tool_args: dict
    description: str
    status: str  # pending | approved | rejected | discarded | expired | executed | failed | unconfirmed
    created_at: str
    # True for a COMPLEX inbound email surfaced as a heads-up (no draft yet) — the card
    # renders "say go and I'll draft it" instead of Approve/Send.
    needs_drafting: bool = False
    # The dispatch result for a RESOLVED action (status executed/failed) — the short human
    # detail ("Email sent to X" / "invalid recipient") + when it resolved. Empty for pending rows.
    outcome_detail: str = ""
    resolved_at: str = ""


def to_unified_card(row: PendingApproval) -> UnifiedApprovalCard:
    """Normalize a PendingApproval row into the unified card.

    THREE shapes collapse to two kinds:
      - inbound reply  (action_type=="email_reply" OR an email-origin thread) → kind=email,
        fields from the row payload {sender, subject, body(original), draft(body)}.
      - chat-queued ``email_send`` (action_type/payload tool_name == "email_send")  → kind=email,
        fields from payload.tool_args {to, subject, body}. (Previously mis-rendered as a
        "tool" card → the "email send; email send" garble.)
      - anything else → kind=tool, the real tool name + args.
    """
    payload = row.payload or {}
    tool_name_raw = payload.get("tool_name") or row.action_type
    needs_drafting = bool(payload.get("needs_drafting"))
    is_reply = row.action_type == "email_reply" or is_email_approval(row.thread_id)
    is_send = tool_name_raw == "email_send"

    if is_reply:
        tool_name = row.action_type
        # "original" = the email being replied to (always shown); "body" = the draft
        # (omitted until drafted, so a heads-up shows just the email + the prompt).
        tool_args: dict = {
            "to": payload.get("sender", ""),
            "subject": payload.get("subject", ""),
            "original": payload.get("body", ""),
        }
        if not needs_drafting:
            tool_args["body"] = payload.get("draft", "")
        kind: Literal["email", "tool"] = "email"
    elif is_send:
        targs = payload.get("tool_args") or {}
        tool_name = "email_send"
        tool_args = {
            "to": targs.get("to", ""),
            "subject": targs.get("subject", ""),
            "body": targs.get("body", ""),
        }
        kind = "email"
    else:
        tool_name = tool_name_raw
        tool_args = payload.get("tool_args") or {}
        kind = "tool"

    return UnifiedApprovalCard(
        approval_id=str(row.id),
        kind=kind,
        thread_id=row.thread_id,
        tool_name=tool_name,
        tool_args=tool_args,
        description=row.description,
        status=row.status,
        created_at=row.created_at.isoformat() if row.created_at else "",
        needs_drafting=needs_drafting,
        outcome_detail=getattr(row, "outcome_detail", "") or "",
        resolved_at=(_resolved.isoformat() if (_resolved := getattr(row, "resolved_at", None)) else ""),
    )


# Terminal outcome states a RESOLVED+dispatched action lands in (set by the dispatch gate).
# unconfirmed = EmailSendUncertain — the send could NOT be confirmed (neither clean success
# nor a definite failure); rendered ⚠️, never a clean ✅.
TERMINAL_OUTCOME_STATES = ("executed", "failed", "unconfirmed")


async def list_pending_cards() -> list[UnifiedApprovalCard]:
    """THE shared read: pending + unexpired approvals, oldest-first, each normalized to a
    UnifiedApprovalCard. The single query both the HUD queue and the agent tool call, so
    they can never drift. Filters expired rows (never surfaces a stale approval as
    actionable). PURE READ — never claims or dispatches."""
    now = datetime.now(UTC)
    async with async_session() as session:
        rows = list((await session.execute(
            select(PendingApproval)
            .where(PendingApproval.status == "pending")
            .where(PendingApproval.expires_at > now)
            .order_by(PendingApproval.created_at.asc())
        )).scalars().all())
    return [to_unified_card(r) for r in rows]


async def list_recent_outcomes(within_hours: int = 24, limit: int = 10) -> list[UnifiedApprovalCard]:
    """THE shared read for RESOLVED actions — what HAPPENED to things the master approved
    (executed/failed, with the dispatch detail), most-recent-first, across ALL channels
    (the row carries the outcome regardless of where it was resolved). The agent reads this
    to answer "did X send / what happened to that?"; the HUD could read it too. PURE READ.

    Restores what the non-blocking cutover dropped: the agent's knowledge of an action's fate
    once the [QUEUED] turn has long completed. Within-window so it stays a "recent" view."""
    cutoff = datetime.now(UTC) - timedelta(hours=within_hours)
    async with async_session() as session:
        rows = list((await session.execute(
            select(PendingApproval)
            .where(PendingApproval.status.in_(TERMINAL_OUTCOME_STATES))
            .where(PendingApproval.resolved_at > cutoff)
            .order_by(PendingApproval.resolved_at.desc())
            .limit(limit)
        )).scalars().all())
    return [to_unified_card(r) for r in rows]


# --------------------------------------------------------------------------- #
# Renderers — ONE per-card classification, shared by the brief voice summary    #
# and the full agent-tool answer, so neither can print the bare tool name.      #
# --------------------------------------------------------------------------- #
def _email_verb(card: UnifiedApprovalCard) -> str:
    """An outbound chat-composed email is "an email to"; an inbound auto-draft is "a
    reply to". Both are kind=email; the tool_name carries the reply-vs-send distinction."""
    return "an email to" if card.tool_name == "email_send" else "a reply to"


def describe_card(card: UnifiedApprovalCard) -> str:
    """One short human phrase for a single card — the shared atom both renderers use.
    email → "a reply to <to> about '<subject>'"; calendar → the event NAME + a human time
    (A2 s1b — a bare "calendar create" tells the master nothing recognizable); other tools →
    the humanized action."""
    if card.kind == "email":
        to = card.tool_args.get("to") or "someone"
        subj = card.tool_args.get("subject")
        return f"{_email_verb(card)} {to}" + (f" about '{subj}'" if subj else "")
    if card.tool_name.startswith("calendar_"):
        verb = {"calendar_create": "a calendar event", "calendar_update": "an update to the event",
                "calendar_delete": "deleting the event"}.get(card.tool_name, card.tool_name.replace("_", " "))
        title = (card.tool_args.get("title") or "").strip()
        when = _human_time(card.tool_args.get("start_iso") or "")
        out = f"{verb} '{title}'" if title else verb
        return f"{out} at {when}" if when else out
    return card.tool_name.replace("_", " ")


def _human_time(iso_value: str) -> str:
    """A recognizable human form of an ISO instant ("5:00 pm on Friday, July 4") — empty on an
    unparseable value (the caller just omits the time)."""
    try:
        dt = datetime.fromisoformat((iso_value or "").strip().replace("Z", "+00:00"))
    except ValueError:
        return ""
    h12 = dt.hour % 12 or 12
    ampm = "am" if dt.hour < 12 else "pm"
    return f"{h12}:{dt.minute:02d} {ampm} on {dt.strftime('%A')}, {dt.strftime('%B')} {dt.day}"


def summarize_others(cards: list[UnifiedApprovalCard], exclude_approval_id: str, honorific: str) -> str:
    """The brief voice/text line for "what else is pending?" — the OTHER cards (minus the
    one already presented), bounded to 5 + "and N more". Uses ``describe_card`` so a
    chat-queued email_send reads "an email to X", never the "email send" garble."""
    others = [c for c in cards if c.approval_id != exclude_approval_id]
    if not others:
        return f"That's the only one pending, {honorific}."
    descriptions = [describe_card(c) for c in others[:5]]
    n = len(others)
    more = f", and {n - 5} more" if n > 5 else ""
    count = "one" if n == 1 else str(n)
    plural = "" if n == 1 else "s"
    return f"You have {count} other{plural} pending, {honorific}: {'; '.join(descriptions)}{more}."


def _snippet(text: str, limit: int = 140) -> str:
    """A one-line, whitespace-collapsed body preview, ellipsized."""
    flat = " ".join((text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 1].rstrip() + "…"


def _compact_args(args: dict, limit: int = 3) -> str:
    """The first few key=value pairs of a tool's args, values truncated — the "key args"
    in a non-email card's line. Skips the email-card keys (rendered explicitly elsewhere)."""
    parts = []
    for k, v in list(args.items())[:limit]:
        s = " ".join(str(v).split())
        parts.append(f"{k}={s if len(s) <= 40 else s[:39] + '…'}")
    return ", ".join(parts)


def _age(created_at_iso: str, now: datetime) -> str:
    """Human age of a card from its ISO created_at (for "queued 3h ago")."""
    if not created_at_iso:
        return "just now"
    try:
        created = datetime.fromisoformat(created_at_iso)
    except ValueError:
        return "just now"
    secs = max(0, int((now - created).total_seconds()))
    if secs < 90:
        return "just now"
    if secs < 3600:
        return f"{secs // 60}m ago"
    if secs < 86400:
        return f"{secs // 3600}h ago"
    return f"{secs // 86400}d ago"


def render_for_agent(cards: list[UnifiedApprovalCard], honorific: str, now: datetime | None = None) -> str:
    """The full, readable answer the ``approvals_pending`` tool returns — one line per
    card. email → recipient + subject + a body snippet; any other action → the humanized
    action + its key args; each with an age. The exact-same card list the HUD renders."""
    now = now or datetime.now(UTC)
    if not cards:
        return f"Nothing's awaiting your approval right now, {honorific}."

    n = len(cards)
    head = f"{n} item{'' if n == 1 else 's'} awaiting your approval, {honorific}:"
    lines = [head]
    for c in cards:
        age = _age(c.created_at, now)
        if c.kind == "email":
            to = c.tool_args.get("to") or "(no recipient)"
            subj = c.tool_args.get("subject") or "(no subject)"
            verb = "Send email to" if c.tool_name == "email_send" else "Reply to"
            if c.needs_drafting:
                tail = "— not drafted yet (say the word and I'll draft it)"
            else:
                body = (c.tool_args.get("body") or "").strip()
                tail = f"— “{_snippet(body)}”" if body else "— (no body)"
            lines.append(f"• {verb} {to} — subject “{subj}” {tail}  ({age})")
        else:
            action = c.tool_name.replace("_", " ")
            args = _compact_args(c.tool_args)
            lines.append(f"• {action}" + (f" — {args}" if args else "") + f"  ({age})")
    return "\n".join(lines)


def _outcome_subject(card: UnifiedApprovalCard) -> str:
    """A short human reference to WHAT the resolved action was (no per-kind branch in the
    caller). email → "email to <to>"; tool → the humanized action."""
    if card.kind == "email":
        to = card.tool_args.get("to") or "someone"
        verb = "email to" if card.tool_name == "email_send" else "reply to"
        return f"{verb} {to}"
    return card.tool_name.replace("_", " ")


def render_outcomes_for_agent(cards: list[UnifiedApprovalCard], honorific: str, now: datetime | None = None) -> str:
    """Readable summary of recently-RESOLVED actions and what happened to each — the agent's
    grounding for "did X send / what happened to that?". ✅ executed / ❌ failed + the dispatch
    detail + age. Same card source the HUD could read. Empty list → "" (caller omits the section)."""
    if not cards:
        return ""
    now = now or datetime.now(UTC)
    _icon = {"executed": "✅", "failed": "❌", "unconfirmed": "⚠️"}
    _default_tail = {"executed": "done", "failed": "failed",
                     "unconfirmed": "may have sent — couldn't confirm"}
    lines = [f"Recently resolved, {honorific}:"]
    for c in cards:
        icon = _icon.get(c.status, "•")
        detail = (c.outcome_detail or "").strip()
        tail = f" — {detail}" if detail else f" — {_default_tail.get(c.status, c.status)}"
        lines.append(f"{icon} {_outcome_subject(c)}{tail}  ({_age(c.resolved_at or c.created_at, now)})")
    return "\n".join(lines)
