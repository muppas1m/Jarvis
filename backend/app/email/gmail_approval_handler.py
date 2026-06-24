"""Channel-origin approval handler for Gmail-originated approvals.

An inbound email that needs a reply becomes a SYNTHETIC ``PendingApproval``
(``thread_id="gmail:<msg_id>"``, ``action_type="gmail_reply"``) minted by
``app.email.gmail_pubsub._queue_email_approval`` — NOT a LangGraph interrupt. So
it can't be resolved by resuming a graph (there's no checkpoint to resume); it's
resolved by actually SENDING the drafted reply via ``gmail_send``.

This module is the ONE place that resolution lives. Extracted from
``app.messaging.router`` (the decoupling called out in
``project_gmail_handler_decoupling_deferral``) because the SAME resolution now
has to be driven by three transports — Telegram inline buttons, the dashboard
decide endpoint, and hands-free voice — and Gmail-domain logic (Gmail API
fetches, RFC822 threading headers, ``gmail_send`` dispatch) does not belong in
the channel router.

Two surfaces:

  dispatch_gmail_approval(thread_id, decision) -> GmailApprovalOutcome
      The transport-agnostic core. On approve, recovers the draft + recipient +
      threading info from the PendingApproval payload (Turn-17.5 enrichment;
      falls back to a Gmail header fetch for pre-17.5 rows) and sends. Returns a
      structured outcome — it announces NOTHING itself, so every transport can
      render the result its own way (a Telegram alert, an HTTP envelope, a spoken
      line). No channel coupling.

  resolve(thread_id, platform, decision) -> None
      The channel-alert wrapper used by the messaging router (Telegram today,
      WhatsApp later): dispatch + push the master-facing alert through the
      originating channel. Behaviour is byte-identical to the old
      ``router._resolve_gmail_approval`` so the working Telegram approve path
      does not regress.
"""
from __future__ import annotations

from dataclasses import dataclass
from email.utils import parseaddr
from typing import Any, Literal

from app.utils.logging import get_logger

logger = get_logger(__name__)

OutcomeStatus = Literal[
    "sent", "rejected", "row_missing", "payload_incomplete", "send_failed"
]


@dataclass(frozen=True)
class GmailApprovalOutcome:
    """Result of resolving a ``gmail:`` approval. The caller renders it for its
    transport — ``channel_alert_for`` (Telegram/dashboard) or a spoken line
    (voice). ``rejected`` carries no side effect (the original email stays in the
    inbox for the master to handle manually)."""

    status: OutcomeStatus
    recipient: str = ""
    subject: str = ""
    detail: str = ""  # gmail_send result on success; error text on send_failed


async def dispatch_gmail_approval(
    thread_id: str, decision: dict[str, Any]
) -> GmailApprovalOutcome:
    """Resolve a ``gmail:`` approval. The transport-agnostic core shared by every
    surface (Telegram, dashboard, voice).

    On approve: read the PendingApproval row's payload to recover the draft +
    recipient + threading info, call ``gmail_send`` directly. Falls back to
    fetching headers from Gmail if the payload is missing them (rows created
    before Turn 17.5 don't have ``subject`` + ``rfc822_message_id``).

    On reject: no action — ``resolve_approval`` already marked the DB row
    ``status='rejected'`` before this fired, and there's no outbound side effect
    to skip.

    decision shape:
        {"approved": True}
        {"approved": False, "reason": "..."}
    """
    if not decision.get("approved"):
        logger.info("gmail_approval_rejected", thread_id=thread_id)
        return GmailApprovalOutcome(status="rejected")

    # Look up the PendingApproval row by thread_id. Approvals here are 1:1 with
    # thread_id (a single email maps to one approval), so this is unambiguous.
    from sqlalchemy import select

    from app.db.engine import async_session
    from app.db.models import PendingApproval

    async with async_session() as session:
        result = await session.execute(
            select(PendingApproval).where(PendingApproval.thread_id == thread_id)
        )
        row = result.scalar_one_or_none()

    if row is None:
        logger.warning("gmail_approval_row_missing", thread_id=thread_id)
        return GmailApprovalOutcome(status="row_missing")

    payload = row.payload or {}
    gmail_message_id = payload.get("gmail_message_id")
    draft_body = payload.get("draft", "")
    sender = payload.get("sender", "")
    subject = payload.get("subject")
    rfc822_message_id = payload.get("rfc822_message_id")

    if not gmail_message_id or not draft_body or not sender:
        logger.error(
            "gmail_approval_payload_incomplete",
            thread_id=thread_id,
            has_msg_id=bool(gmail_message_id),
            has_draft=bool(draft_body),
            has_sender=bool(sender),
        )
        return GmailApprovalOutcome(status="payload_incomplete")

    # Fall back to fetching subject + Message-ID from Gmail for rows created
    # before Turn 17.5 stored them in the payload.
    if not subject or not rfc822_message_id:
        try:
            from app.email.gmail_watch import get_gmail_service

            service = get_gmail_service()
            original = service.users().messages().get(
                userId="me", id=gmail_message_id, format="metadata"
            ).execute()
            headers = {
                h["name"]: h["value"]
                for h in original.get("payload", {}).get("headers", [])
            }
            if not subject:
                subject = headers.get("Subject", "(No Subject)")
            if not rfc822_message_id:
                rfc822_message_id = (
                    headers.get("Message-ID") or headers.get("Message-Id") or ""
                )
            logger.info(
                "gmail_approval_headers_fetched_from_gmail",
                gmail_message_id=gmail_message_id,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "gmail_approval_header_fetch_failed",
                gmail_message_id=gmail_message_id,
                error=str(exc),
            )
            # Continue with whatever we have — gmail_send will work without
            # threading headers, just creates a fresh email rather than a
            # threaded reply.

    # Recipient = the original sender's address. parseaddr handles
    # "Display Name <addr@domain>" → ("Display Name", "addr@domain").
    _, recipient_addr = parseaddr(sender)
    if not recipient_addr:
        recipient_addr = sender  # parseaddr couldn't split — try raw

    reply_subject = subject or "(No Subject)"
    if not reply_subject.lower().startswith("re:"):
        reply_subject = f"Re: {reply_subject}"

    # Dispatch. gmail_send writes its own AuditTrail row + flips
    # EmailLog.auto_sent on success.
    from app.agent.tools.gmail_send import gmail_send

    try:
        send_result = await gmail_send(
            to=recipient_addr,
            subject=reply_subject,
            body=draft_body,
            in_reply_to_message_id=rfc822_message_id or None,
            gmail_message_id=gmail_message_id,
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("gmail_approval_send_failed", thread_id=thread_id, error=str(exc))
        return GmailApprovalOutcome(
            status="send_failed",
            recipient=recipient_addr,
            subject=reply_subject,
            detail=str(exc)[:500],
        )

    logger.info("gmail_approval_dispatched", thread_id=thread_id, result=send_result)
    return GmailApprovalOutcome(
        status="sent",
        recipient=recipient_addr,
        subject=reply_subject,
        detail=str(send_result),
    )


def channel_alert_for(outcome: GmailApprovalOutcome, thread_id: str) -> str | None:
    """Master-facing alert text for a channel transport (Telegram / dashboard).

    Returns ``None`` when nothing should be announced (a plain reject has no
    outbound side effect, so it's silent — matching the pre-extraction
    behaviour). Wording is unchanged from the old ``_resolve_gmail_approval`` so
    the Telegram approve path is byte-identical."""
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
        return (
            f"❌ Failed to send reply for `{thread_id}`:\n"
            f"```\n{outcome.detail}\n```"
        )
    # sent
    return (
        f"✅ Reply sent to {outcome.recipient}\n"
        f"Subject: {outcome.subject}\n"
        f"{outcome.detail}"
    )


async def resolve(
    thread_id: str, platform: str, decision: dict[str, Any]
) -> None:
    """Channel-origin approval entry for the messaging router (Telegram, etc.):
    resolve the approval, then push the master-facing alert back through the
    originating channel. Registered in ``router.CHANNEL_ORIGIN_HANDLERS``."""
    from app.messaging.channel_registry import channel_registry

    outcome = await dispatch_gmail_approval(thread_id, decision)
    text = channel_alert_for(outcome, thread_id)
    if text:
        await channel_registry.get(platform).send_alert(text)
