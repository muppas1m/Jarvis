"""Channel-origin approval handler for inbound-email approvals (any provider).

An inbound email that needs a reply becomes a SYNTHETIC ``PendingApproval``
(``thread_id="email:<provider>:<message_id>"``, ``action_type="email_reply"``)
minted by the inbound pipeline — NOT a LangGraph interrupt, so it's resolved by
SENDING the drafted reply (via ``email.send.send_email`` → the configured
``EmailProvider``), not by resuming a graph.

This is the ONE place that resolution lives — shared by three transports
(Telegram inline buttons, the dashboard decide endpoint, hands-free voice).
Provider-agnostic: it reads the provider tag + opaque refs from the approval
payload and calls the interface; adding Outlook touches nothing here.

Backward-compat: rows minted before this generalization use
``thread_id="gmail:<id>"`` + payload keys ``gmail_message_id`` /
``rfc822_message_id`` and no ``provider``. The payload reader falls back to those
(provider defaults to "gmail"), so a live legacy approval still resolves.
"""
from __future__ import annotations

from dataclasses import dataclass
from email.utils import parseaddr
from typing import Any, Literal

from app.email.provider import ReplyRef, get_email_provider
from app.email.send import send_email
from app.utils.logging import get_logger

logger = get_logger(__name__)

# thread_id prefixes that mark an inbound-email (channel-origin) approval. New
# rows use "email:<provider>:"; "gmail:" is the legacy prefix (read-compat).
EMAIL_THREAD_PREFIXES = ("email:", "gmail:")


def is_email_approval(thread_id: str) -> bool:
    """True if this approval is an inbound-email one (resolved by sending, not by
    resuming a graph). Every transport keys its dispatch off this."""
    return thread_id.startswith(EMAIL_THREAD_PREFIXES)


OutcomeStatus = Literal["sent", "rejected", "row_missing", "payload_incomplete", "send_failed"]


@dataclass(frozen=True)
class EmailApprovalOutcome:
    """Result of resolving an inbound-email approval. The caller renders it for
    its transport — ``channel_alert_for`` (Telegram/dashboard) or a spoken line
    (voice). ``rejected`` has no side effect (the email stays in the inbox)."""

    status: OutcomeStatus
    recipient: str = ""
    subject: str = ""
    detail: str = ""  # send result on success; error text on send_failed


def _read_payload(payload: dict[str, Any]) -> dict[str, str]:
    """Normalize an approval payload into neutral fields, with legacy fallback.

    New rows: provider/message_id/thread_ref/rfc822_message_id/subject/sender/draft.
    Legacy (gmail:) rows: gmail_message_id + rfc822_message_id, no provider."""
    return {
        "provider": payload.get("provider") or "gmail",
        "message_id": payload.get("message_id") or payload.get("gmail_message_id") or "",
        "thread_ref": payload.get("thread_ref") or "",
        "rfc822_message_id": payload.get("rfc822_message_id") or "",
        "subject": payload.get("subject") or "",
        "sender": payload.get("sender") or "",
        "draft": payload.get("draft") or "",
    }


async def dispatch_email_approval(
    thread_id: str, decision: dict[str, Any]
) -> EmailApprovalOutcome:
    """Resolve an inbound-email approval. The transport-agnostic core shared by
    Telegram / dashboard / voice.

    On approve: recover the draft + recipient + threading refs from the payload,
    fetch missing headers via the provider if needed (legacy rows), and send via
    the configured provider. On reject: no action."""
    if not decision.get("approved"):
        logger.info("email_approval_rejected", thread_id=thread_id)
        return EmailApprovalOutcome(status="rejected")

    from sqlalchemy import select

    from app.db.engine import async_session
    from app.db.models import PendingApproval

    async with async_session() as session:
        result = await session.execute(
            select(PendingApproval).where(PendingApproval.thread_id == thread_id)
        )
        row = result.scalar_one_or_none()

    if row is None:
        logger.warning("email_approval_row_missing", thread_id=thread_id)
        return EmailApprovalOutcome(status="row_missing")

    p = _read_payload(row.payload or {})
    provider_name = p["provider"]
    message_id = p["message_id"]
    draft_body = p["draft"]
    sender = p["sender"]
    subject = p["subject"]
    rfc822_message_id = p["rfc822_message_id"]
    thread_ref = p["thread_ref"]

    if not message_id or not draft_body or not sender:
        logger.error(
            "email_approval_payload_incomplete",
            thread_id=thread_id,
            has_msg_id=bool(message_id), has_draft=bool(draft_body), has_sender=bool(sender),
        )
        return EmailApprovalOutcome(status="payload_incomplete")

    provider = get_email_provider(provider_name)

    # Legacy rows may lack subject / rfc822_message_id — recover them from the
    # provider (was a Gmail messages.get; now the neutral fetch_message).
    if not subject or not rfc822_message_id:
        try:
            original = await provider.fetch_message(message_id)
            subject = subject or original.subject
            rfc822_message_id = rfc822_message_id or original.rfc822_message_id
            thread_ref = thread_ref or original.thread_ref
            logger.info("email_approval_headers_fetched", provider=provider_name, message_id=message_id)
        except Exception as exc:  # noqa: BLE001 — send still works without threading headers
            logger.warning(
                "email_approval_header_fetch_failed",
                provider=provider_name, message_id=message_id, error=str(exc),
            )

    _, recipient_addr = parseaddr(sender)
    if not recipient_addr:
        recipient_addr = sender

    reply_subject = subject or "(No Subject)"
    if not reply_subject.lower().startswith("re:"):
        reply_subject = f"Re: {reply_subject}"

    try:
        result = await send_email(
            recipient_addr,
            reply_subject,
            draft_body,
            reply_to=ReplyRef(
                provider=provider_name,
                message_id=message_id,
                thread_ref=thread_ref,
                rfc822_message_id=rfc822_message_id,
            ),
            source_message_id=message_id,
            provider_name=provider_name,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("email_approval_send_failed", thread_id=thread_id, error=str(exc))
        return EmailApprovalOutcome(
            status="send_failed", recipient=recipient_addr, subject=reply_subject, detail=str(exc)[:500],
        )

    logger.info("email_approval_dispatched", thread_id=thread_id, sent_message_id=result.sent_message_id)
    return EmailApprovalOutcome(
        status="sent", recipient=recipient_addr, subject=reply_subject,
        detail=f"Email sent to {recipient_addr} (id: {result.sent_message_id})",
    )


def channel_alert_for(outcome: EmailApprovalOutcome, thread_id: str) -> str | None:
    """Master-facing alert text for a channel transport (Telegram / dashboard).
    None when nothing should be announced (a plain reject is silent). Wording is
    unchanged from the pre-extraction Gmail handler so Telegram is byte-identical
    (the ✅/❌ lines the master already sees)."""
    s = outcome.status
    if s == "rejected":
        return None
    if s == "row_missing":
        return (
            f"Approval for {thread_id} couldn't be dispatched — the "
            f"PendingApproval row wasn't found in the database."
        )
    if s == "payload_incomplete":
        return (
            f"Approval for {thread_id} can't be sent — the stored draft data "
            f"is incomplete. Check the pending_approvals row."
        )
    if s == "send_failed":
        return f"❌ Failed to send reply for `{thread_id}`:\n```\n{outcome.detail}\n```"
    return (
        f"✅ Reply sent to {outcome.recipient}\n"
        f"Subject: {outcome.subject}\n"
        f"{outcome.detail}"
    )


async def resolve(thread_id: str, platform: str, decision: dict[str, Any]) -> None:
    """Channel-origin approval entry for the messaging router (Telegram, etc.):
    resolve, then push the master-facing alert through the originating channel."""
    from app.messaging.channel_registry import channel_registry

    outcome = await dispatch_email_approval(thread_id, decision)
    text = channel_alert_for(outcome, thread_id)
    if text:
        await channel_registry.get(platform).send_alert(text)
