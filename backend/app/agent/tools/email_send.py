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

from pydantic import BaseModel, Field

from app.agent.tools.registry import tool_registry
from app.config import settings
from app.email.provider import EmailSendUncertain, ReplyRef
from app.email.send import send_email


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
