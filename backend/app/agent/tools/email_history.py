"""Email history search — query email_logs + pending_approvals for recall.

Phase 2's triage system (gmail_pubsub.handle_gmail_push + classify_email +
generate_draft) creates a structured record of every email that arrives:
classification, draft response, approval status, expiry, sent-or-not. That
data lives in `email_logs` and `pending_approvals` tables but had no agent-
facing surface until this tool.

Use cases the tool covers (Turn 17.6 motivation):
  - "What emails came in over the weekend?"
  - "Any messages from <person>?"
  - "What's still pending reply?"
  - "Did the email from <X> get answered?"
  - "Did I miss anything important?"

Use cases this tool does NOT cover (intentional boundary with memory_search):
  - "What did I tell Jarvis about my preferences?" → memory_search
  - "Who is <person> to me?" → memory_search
  - Anything about CONVERSATION history (master ↔ Jarvis) rather than EMAIL
    history (master ↔ third-party correspondents) → memory_search

Cross-source queries that legitimately span both ("did anyone mention the
contract last week" — could be in emails OR in past conversations with
Jarvis) are documented in project_cross_source_recall_pattern.md. Current
mitigation: sharpened tool descriptions on both sides, relying on the LLM
to chain when it sees both tools as relevant. Structural fix deferred until
real usage surfaces the gap.

Safety classification: SAFE (read-only DB query, no side effects). Set in
app.agent.safety:TOOL_SAFETY_MAP.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agent.tools.registry import tool_registry
from app.db.engine import async_session
from app.db.models import EmailLog, PendingApproval
from app.utils.logging import get_logger

logger = get_logger(__name__)


# Result limit ceiling — bounded so a "show me everything from this year"
# query doesn't return 10k rows. The LLM gets summary stats over the full
# window anyway; the bulleted detail list is just for action_required items.
_MAX_LIMIT = 100


class EmailHistorySearchArgs(BaseModel):
    """Plain-types-only schema. No Optional[X] or Literal unions — those
    serialize to JSON Schema as `anyOf: [..., {"type": "null"}]` which
    Groq's llama-3.3-70b-versatile (and likely other open-weights models)
    can't parse cleanly, causing them to fall back to native function-
    call format instead of OpenAI structured tool_calls. Empty-string
    sentinels stand in for None; the handler maps them back.

    See project_open_weights_tool_schema_anyof_null.md (saved in this turn)
    for the full diagnosis."""

    days_back: int = Field(
        default=7,
        description="How far back to look (days). 1-365, default 7.",
    )
    classification: str = Field(
        default="",
        description="Filter: 'spam' | 'fyi' | 'action_required'. Empty string for all.",
    )
    sender: str = Field(
        default="",
        description="Partial-match sender filter (ILIKE %sender%). Empty string for all.",
    )
    status: str = Field(
        default="",
        description="Approval status: 'pending' | 'approved' | 'rejected' | 'expired'. Empty string for no filter.",
    )
    limit: int = Field(
        default=20,
        description="Max detail rows (1-100, default 20).",
    )


async def email_history_search(
    days_back: int = 7,
    classification: str = "",
    sender: str = "",
    status: str = "",
    limit: int = 20,
) -> str:
    """Query email_logs (LEFT JOIN pending_approvals) and return a natural-
    language summary. See module docstring for usage scope."""
    # Bounds + sentinel-to-None conversion (the schema uses str defaults
    # for tool-calling compatibility; runtime treats empty string as "no filter").
    days_back = max(1, min(int(days_back), 365))
    limit = max(1, min(int(limit), _MAX_LIMIT))

    valid_classifications = {"spam", "fyi", "action_required"}
    valid_statuses = {"pending", "approved", "rejected", "expired"}

    classification_filter: Optional[str] = classification.strip() or None
    if classification_filter and classification_filter not in valid_classifications:
        classification_filter = None  # silently drop invalid filter

    sender_filter: Optional[str] = sender.strip() or None

    status_filter: Optional[str] = status.strip() or None
    if status_filter and status_filter not in valid_statuses:
        status_filter = None

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days_back)

    stmt = (
        select(
            EmailLog.gmail_message_id,
            EmailLog.created_at,
            EmailLog.sender,
            EmailLog.subject,
            EmailLog.classification,
            EmailLog.response_complexity,
            EmailLog.auto_sent,
            PendingApproval.status.label("approval_status"),
            PendingApproval.resolved_via,
            PendingApproval.resolved_at,
            PendingApproval.expires_at,
        )
        .outerjoin(
            PendingApproval,
            PendingApproval.payload["gmail_message_id"].astext == EmailLog.gmail_message_id,
        )
        .where(EmailLog.created_at >= cutoff)
    )

    if classification_filter:
        stmt = stmt.where(EmailLog.classification == classification_filter)
    if sender_filter:
        stmt = stmt.where(EmailLog.sender.ilike(f"%{sender_filter}%"))
    if status_filter:
        stmt = stmt.where(PendingApproval.status == status_filter)

    stmt = stmt.order_by(EmailLog.created_at.desc()).limit(limit)

    async with async_session() as session:
        result = await session.execute(stmt)
        rows = list(result.all())

    return _format_summary(
        rows=rows,
        days_back=days_back,
        now=now,
        classification=classification_filter,
        sender=sender_filter,
        status=status_filter,
    )


def _format_summary(
    rows: list,
    days_back: int,
    now: datetime,
    classification: Optional[str],
    sender: Optional[str],
    status: Optional[str],
) -> str:
    """Build the natural-language summary from query results.

    Shape:
      - Header with total + window + active filters
      - Action_required: per-item bullets (master wants the detail)
      - FYI / spam: counts only (master doesn't need each promotional ping)
    """
    filter_bits = []
    if classification:
        filter_bits.append(f"classification={classification}")
    if sender:
        filter_bits.append(f"sender~'{sender}'")
    if status:
        filter_bits.append(f"status={status}")
    filter_str = f" [filters: {', '.join(filter_bits)}]" if filter_bits else ""

    window_str = f"last {days_back} day{'s' if days_back != 1 else ''}"
    header = f"📧 Email history — {window_str}, {len(rows)} email(s){filter_str}"

    if not rows:
        return header + "\n\n(No matching emails found in this window.)"

    # Bucket by classification.
    action_rows = [r for r in rows if r.classification == "action_required"]
    fyi_count = sum(1 for r in rows if r.classification == "fyi")
    spam_count = sum(1 for r in rows if r.classification == "spam")
    other_count = len(rows) - len(action_rows) - fyi_count - spam_count

    parts = [header, ""]

    if action_rows:
        parts.append(f"🔴 Action required ({len(action_rows)}):")
        for r in action_rows:
            parts.append(f"  - {_format_action_row(r, now)}")
        parts.append("")

    if fyi_count > 0:
        parts.append(f"📬 FYI / digest: {fyi_count} email(s) (appear in morning brief)")

    if spam_count > 0:
        parts.append(f"🚮 Spam: {spam_count} archived")

    if other_count > 0:
        # Defensive: shouldn't happen with current classifications but future-proof.
        parts.append(f"❓ Other / unclassified: {other_count}")

    return "\n".join(parts).rstrip()


def _format_action_row(r, now: datetime) -> str:
    """One action_required row as a bullet line.

    Format: '"<subject>" — <sender_short> — <status_phrase>'

    Status phrase shape:
      - approval pending: "pending (expires in Xh)"
      - approval approved + auto_sent: "approved, sent <Y>"
      - approval approved but NOT auto_sent: "approved (send failed?)"
      - approval rejected: "rejected"
      - approval expired: "expired without reply"
      - no approval row (complex draft via send_system_alert): "complex (needs your input)"
    """
    subject = (r.subject or "(no subject)")[:80]
    sender = _shorten_sender(r.sender or "(unknown)")
    status_phrase = _status_phrase(r, now)
    return f'"{subject}" — {sender} — {status_phrase}'


def _shorten_sender(raw: str) -> str:
    """Display name if present, else email-local-part. Avoids printing the
    full "Name <addr@domain>" verbatim — that's noisy in summaries."""
    from email.utils import parseaddr

    display, addr = parseaddr(raw)
    if display.strip():
        return display.strip()
    if addr and "@" in addr:
        return addr  # full address is fine when no display name
    return raw[:60]


def _status_phrase(r, now: datetime) -> str:
    """Per-row human phrase for the approval lifecycle state."""
    status = r.approval_status

    if status is None:
        # No approval row exists. For an action_required email this means
        # it was complex-classified and went through send_system_alert.
        if r.response_complexity == "complex":
            return "complex (needs your input)"
        # Otherwise it's an action_required that somehow skipped queuing
        # — shouldn't happen with current code but defensive.
        return "drafted (no approval row)"

    if status == "pending":
        if r.expires_at:
            delta = r.expires_at - now
            hours = int(delta.total_seconds() / 3600)
            if hours <= 0:
                return "pending (overdue — approval sweeper hasn't run yet)"
            if hours < 1:
                return "pending (expires in <1h)"
            return f"pending (expires in {hours}h)"
        return "pending"

    if status == "approved":
        if r.auto_sent:
            sent_ago = _relative_time(r.resolved_at, now)
            return f"approved, reply sent {sent_ago}"
        return "approved (send not confirmed — check audit_trail)"

    if status == "rejected":
        return f"rejected {_relative_time(r.resolved_at, now)}"

    if status == "expired":
        # Distinguish auto-expiry from manual cleanup if needed
        if r.resolved_via and "cleanup" in r.resolved_via:
            return "expired (manual cleanup, not aged out)"
        return "expired without reply"

    return f"status={status}"  # forward-compat for unknown statuses


def _relative_time(when: Optional[datetime], now: datetime) -> str:
    """Format a timestamp as 'Nh ago' / 'Nd ago' / 'just now'."""
    if when is None:
        return "(time unknown)"
    delta = now - when
    if delta.total_seconds() < 60:
        return "just now"
    minutes = int(delta.total_seconds() / 60)
    if minutes < 60:
        return f"{minutes}m ago"
    hours = int(minutes / 60)
    if hours < 24:
        return f"{hours}h ago"
    days = int(hours / 24)
    return f"{days}d ago"


def register() -> None:
    tool_registry.register(
        name="email_history_search",
        handler=email_history_search,
        description=(
            "Search the master's email history — what messages came in, who "
            "sent them, were they replied to, what's pending. "
            "Does NOT search conversation memory; use memory_search for that. "
            "Use for: 'what emails came in', 'any messages from X', 'did the "
            "email from Y get answered', 'what's still pending reply'. "
            "Returns a grouped summary by classification (action_required gets "
            "per-item detail; fyi/spam get counts) plus approval status for "
            "each pending or sent reply."
        ),
        args_schema=EmailHistorySearchArgs,
    )
