"""Gmail send tool — outbound email via the OAuth-authenticated Gmail account.

Two invocation pathways:

  1. Agent-direct (LangGraph reasoning) — the agent decides during a turn
     that it should send an email. Goes through tool_executor_node, which
     handles the APPROVE-tier safety classification (defined in
     app.agent.safety:TOOL_SAFETY_MAP since Phase 1). For Phase 2, this
     pathway is unreachable in practice because no LangGraph thread
     currently emits gmail_send tool calls — but the tool is registered so
     the agent has the capability available when future prompts/scenarios
     reach for it.

  2. Approval dispatch (Gmail-originated approvals) — when master taps
     Approve on a Telegram inline keyboard for a queued gmail_reply,
     app.messaging.router.route_approval_decision detects the
     `thread_id.startswith("gmail:")` pattern and calls `gmail_send` DIRECTLY
     (NOT via the tool_registry) with the data from PendingApproval.payload.
     This is the primary Phase 2 use — closes the action-no-op gap from
     project_email_action_capability_gap.md.

Threading: if `in_reply_to_message_id` (the RFC822 Message-ID header value,
NOT Gmail's internal message ID) is provided, the reply gets proper
In-Reply-To + References headers so Gmail clients show it as a reply in
the original thread. Without it, the message goes out as a fresh email
that Gmail's conversation view groups by Subject (less reliable).

Logs to AuditTrail and updates EmailLog.auto_sent on success. Tool-level
side effects, NOT caller responsibility — both pathways get the same
audit semantics."""
from __future__ import annotations

import base64
import time
import uuid
from datetime import datetime, timezone
from email.mime.text import MIMEText
from typing import Optional

from googleapiclient.discovery import build
from pydantic import BaseModel, Field
from sqlalchemy import update

from app.agent.tools.registry import tool_registry
from app.config import settings
from app.db.engine import async_session
from app.db.models import AuditTrail, EmailLog
from app.email.gmail_watch import get_gmail_service
from app.utils.logging import get_logger

logger = get_logger(__name__)


class GmailSendArgs(BaseModel):
    """Plain-types-only schema. Optional[str] would serialize to
    `anyOf: [{"type": "string"}, {"type": "null"}]` which breaks tool-calling
    on Groq's llama-3.3-70b-versatile (and likely other open-weights models).
    Empty-string sentinels for "not provided"; handler maps back to None.
    See project_open_weights_tool_schema_and_conversation_poisoning.md."""

    to: str = Field(description="Recipient email address. Single recipient only for Phase 2.")
    subject: str = Field(description="Subject line. 'Re: <original>' for replies.")
    body: str = Field(description="Plain-text message body. HTML not supported yet.")
    in_reply_to_message_id: str = Field(
        default="",
        description=(
            "RFC822 Message-ID header value (e.g. '<CABc123@mail.gmail.com>') of the email "
            "being replied to. Sets In-Reply-To + References headers for Gmail threading. "
            "Empty string when not a reply. NOT the Gmail-internal message ID."
        ),
    )
    gmail_message_id: str = Field(
        default="",
        description=(
            "Gmail-internal message ID (e.g. '19e2274ca914e6b6'). When set, the corresponding "
            "EmailLog row gets auto_sent=True. Empty string for agent-direct invocations."
        ),
    )


async def gmail_send(
    to: str,
    subject: str,
    body: str,
    in_reply_to_message_id: str = "",
    gmail_message_id: str = "",
) -> str:
    """Send an email via the master's Gmail account. Returns a short status string."""
    # Normalize sentinel → effective None for internal logic.
    irt = in_reply_to_message_id.strip() or None
    gmid = gmail_message_id.strip() or None

    service = get_gmail_service()

    # Build MIME message with optional threading headers.
    mime = MIMEText(body, "plain", "utf-8")
    mime["To"] = to
    mime["Subject"] = subject
    if irt:
        mime["In-Reply-To"] = irt
        mime["References"] = irt

    raw = base64.urlsafe_b64encode(mime.as_bytes()).decode("utf-8")

    request_body: dict = {"raw": raw}
    # If we know the Gmail message ID being replied to, also set threadId so
    # Gmail places the reply in the SAME conversation rather than starting a
    # new one. Belt-and-braces alongside In-Reply-To.
    if gmid:
        try:
            original = service.users().messages().get(
                userId="me", id=gmid, format="metadata"
            ).execute()
            thread_id_gmail = original.get("threadId")
            if thread_id_gmail:
                request_body["threadId"] = thread_id_gmail
        except Exception as exc:  # noqa: BLE001
            # Fetch failure shouldn't block the send — In-Reply-To header alone
            # gives correct threading in most clients. Log and continue.
            logger.warning(
                "gmail_send_thread_lookup_failed",
                gmail_message_id=gmid,
                error=str(exc),
            )

    # Latency captured around the send dispatch and threaded into _audit —
    # mirrors tool_executor_node's capture so the two genuinely-separate audit
    # paths (agent-loop via tool_registry.execute vs. this approval-dispatch
    # direct call) record latency_ms consistently and can't drift.
    send_start = time.monotonic()
    try:
        result = service.users().messages().send(
            userId="me", body=request_body
        ).execute()
        sent_id = result.get("id", "(no-id)")
        logger.info(
            "gmail_send_ok",
            to=to,
            subject=subject[:80],
            sent_message_id=sent_id,
            in_reply_to=irt is not None,
        )
    except Exception as exc:  # noqa: BLE001 — re-raised below after audit
        await _audit(
            to=to, subject=subject, gmail_message_id=gmid,
            success=False, error=str(exc)[:500],
            latency_ms=int((time.monotonic() - send_start) * 1000),
        )
        logger.error("gmail_send_failed", to=to, subject=subject[:80], error=str(exc))
        raise

    await _audit(
        to=to, subject=subject, gmail_message_id=gmid,
        success=True, error=None, sent_message_id=sent_id,
        latency_ms=int((time.monotonic() - send_start) * 1000),
    )

    # Close the audit loop on the original EmailLog row — mark auto_sent=True
    # so /api/costs and future history-search tools can distinguish "draft
    # auto-sent" from "drafted but never sent."
    if gmid:
        await _mark_email_auto_sent(gmid)

    return f"Email sent to {to} (Gmail id: {sent_id})"


async def _audit(
    to: str,
    subject: str,
    gmail_message_id: Optional[str],
    success: bool,
    error: Optional[str],
    sent_message_id: Optional[str] = None,
    latency_ms: Optional[int] = None,
) -> None:
    """Write an AuditTrail row for the send attempt. Same shape that
    tool_executor_node uses for SAFE/NOTIFY/APPROVE tool calls so audit
    queries see a uniform schema regardless of invocation pathway."""
    thread_id = f"gmail:{gmail_message_id}" if gmail_message_id else None
    input_summary = f"to={to}, subject={subject[:120]}"
    output_summary = (
        f"sent_message_id={sent_message_id}" if success else f"error={error}"
    )

    async with async_session() as session:
        session.add(
            AuditTrail(
                id=uuid.uuid4(),
                thread_id=thread_id,
                action="gmail_send",
                tool_name="gmail_send",
                safety_level="approve",
                input_summary=input_summary[:500],
                output_summary=output_summary[:500] if output_summary else None,
                success=success,
                error=error,
                cost_usd=0.0,
                latency_ms=latency_ms,
            )
        )
        await session.commit()


async def _mark_email_auto_sent(gmail_message_id: str) -> None:
    """Flip EmailLog.auto_sent on the row corresponding to the source email.

    Best-effort: if the row doesn't exist (edge case — agent-direct invocation
    against a message that wasn't classified via the pubsub pipeline), log
    and continue. The audit trail is the canonical record either way."""
    try:
        async with async_session() as session:
            await session.execute(
                update(EmailLog)
                .where(EmailLog.gmail_message_id == gmail_message_id)
                .values(auto_sent=True)
            )
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "gmail_send_email_log_update_failed",
            gmail_message_id=gmail_message_id,
            error=str(exc),
        )


def register() -> None:
    tool_registry.register(
        name="gmail_send",
        handler=gmail_send,
        description=(
            "Send an email via the master's Gmail account. APPROVE-tier — the agent "
            "must request master approval before this fires. Use for replying to "
            "incoming emails (set in_reply_to_message_id + gmail_message_id for "
            "proper threading) or composing new ones. ONE recipient at a time in "
            "Phase 2; multi-recipient and HTML body land later."
        ),
        args_schema=GmailSendArgs,
    )
