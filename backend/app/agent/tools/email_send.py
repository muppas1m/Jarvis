"""Email send tool — provider-agnostic outbound email for the agent.

Thin LLM-facing wrapper over ``app.email.send.send_email``: it carries the
args_schema the agent reasons with and delegates to the neutral send path (which
resolves the configured EmailProvider adapter + writes audit/auto_sent). The
provider — Gmail today, Outlook tomorrow — is a config choice the agent never
sees.

Two invocation pathways (unchanged from the Gmail-only era, just neutral):
  1. Agent-direct — the agent calls this during a turn (APPROVE-tier; the
     tool_executor pauses for the master's approval).
  2. Approval dispatch — an inbound auto-drafted reply, resolved by the approval
     handler calling ``send_email`` directly (not this tool).
"""
from __future__ import annotations

import re
from email.utils import parseaddr

from pydantic import BaseModel, Field

from app.agent.tools.registry import tool_registry
from app.config import settings
from app.email.provider import EmailSendUncertain, ReplyRef
from app.email.send import send_email

# A real-looking address AFTER display-name extraction: one @, a dotted domain, no spaces
# or brackets. Deliberately strict — its job is to reject the LLM's templated placeholders
# ("[Manager's Email Address]", "<recipient email>", "TBD", "manager's email"), all of which
# fail this naturally, while accepting real addresses incl. plus-tags / subdomains.
_EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


def validate_recipient(to: str) -> str | None:
    """Validate an outbound recipient BEFORE an email_send card is queued. Returns an
    agent-facing error string when the address is missing or a placeholder/non-address (so
    the agent ASKS the master for the real one), or None when it's usable.

    Python-side by design — the placeholder is text the LLM ITSELF emitted when it lacked a
    real address, so we can't rely on it to notice. ``parseaddr`` extracts the address from a
    valid "Name <addr>" form (which IS accepted); a templated "<recipient email>" / "[...]"
    parses to a non-address and is rejected by the strict pattern."""
    raw = (to or "").strip()
    if not raw:
        return _need_recipient(raw, "no recipient was provided")
    addr = parseaddr(raw)[1].strip()  # "Bob <bob@x.com>" → "bob@x.com"; "[Mgr email]" → itself
    if not _EMAIL_RE.match(addr):
        return _need_recipient(raw, "it isn't a real email address — it looks like a placeholder")
    return None


def _need_recipient(value: str, reason: str) -> str:
    """The tool result that steers the agent to ask the master for the real address."""
    shown = f" ({value!r})" if value else ""
    return (
        f"[NEEDS RECIPIENT] I can't queue this email — the recipient{shown} is not usable: "
        f"{reason}. I won't guess or send to a placeholder. Ask the master for the actual "
        f"recipient email address, then call email_send again with it."
    )


class EmailSendArgs(BaseModel):
    """Plain-types-only schema (no Optional/Literal — they serialize to
    ``anyOf:[…,null]`` which Groq's llama-3.3-70b can't tool-call cleanly; see
    project_open_weights_tool_schema_and_conversation_poisoning). Empty-string
    sentinels stand in for None."""

    to: str = Field(description="Recipient email address. Single recipient only for now.")
    subject: str = Field(description="Subject line. 'Re: <original>' for replies.")
    body: str = Field(description="Plain-text message body. HTML not supported yet.")
    in_reply_to_message_id: str = Field(
        default="",
        description=(
            "RFC822 Message-ID header value (e.g. '<CABc123@mail>') of the email being "
            "replied to — the cross-provider threading standard (In-Reply-To/References). "
            "Empty string when not a reply."
        ),
    )
    source_message_id: str = Field(
        default="",
        description=(
            "Opaque provider id of the source message being replied to. When set, the "
            "matching email record is marked auto-sent and the reply is threaded. Empty "
            "for a fresh email."
        ),
    )


async def email_send(
    to: str,
    subject: str,
    body: str,
    in_reply_to_message_id: str = "",
    source_message_id: str = "",
) -> str:
    """Send an email via the master's configured provider. Returns a status string.

    Maybe-delivered (``EmailSendUncertain`` — a timeout / 5xx where the send may
    already have gone out) is caught and returned as the SAME honest, deterministic
    wording the approval transports use — so the master gets that signal on this
    agent-direct surface too, not a generic "failed". A DEFINITE failure is left
    to propagate → tool_executor's standard ``[ERROR]`` path (``success=False``),
    consistent with every other tool — it really did fail and should read so."""
    irt = in_reply_to_message_id.strip()
    smid = source_message_id.strip()
    reply_to = (
        ReplyRef(provider="", message_id=smid, rfc822_message_id=irt)
        if (irt or smid)
        else None
    )
    try:
        result = await send_email(to, subject, body, reply_to=reply_to, source_message_id=smid)
    except EmailSendUncertain:
        h = settings.MASTER_HONORIFIC
        return (
            f"I couldn't confirm the email to {to} sent, {h} — it may have gone out. "
            f"Worth checking your Sent folder."
        )
    return f"Email sent to {to} (id: {result.sent_message_id})"


def register() -> None:
    tool_registry.register(
        name="email_send",
        handler=email_send,
        description=(
            "Send an email via the master's account. APPROVE-tier — the agent must "
            "request master approval before this fires. Use for replying to incoming "
            "emails (set in_reply_to_message_id + source_message_id for proper "
            "threading) or composing new ones. ONE recipient at a time; multi-recipient "
            "and HTML body land later."
        ),
        args_schema=EmailSendArgs,
    )
