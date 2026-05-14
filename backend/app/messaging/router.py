"""
Inbound + resume routing.

Two entry points the messaging layer calls into:

  route_inbound(NormalizedMessage)
      Take a freshly-normalized inbound message, drive run_turn(), and send
      the reply back via the same channel. Updates ConversationAnalytics on
      the way through. If the agent paused at an APPROVE interrupt, do NOT
      send a reply — the tool_executor node already pushed the approval
      prompt to master via failure_alerter; the conversation continues on
      `route_approval_decision`.

  route_approval_decision(thread_id, platform, decision)
      Triggered by the channel's UI callback (Telegram inline button,
      WhatsApp quick reply, web dashboard click). Resumes the paused graph
      with the master's approve/reject decision. The continuation reply is
      sent as a system alert (no original-message context to reply-to).

The agent (`runner.py`) is callable from anywhere; the router is what knows
about channels.
"""
from typing import Any

from app.agent.runner import resume_turn, run_turn
from app.memory.session import SessionManager
from app.messaging.channel import NormalizedMessage
from app.messaging.normalizer import channel_registry
from app.utils.logging import get_logger

logger = get_logger(__name__)
session_mgr = SessionManager()


async def route_inbound(msg: NormalizedMessage) -> None:
    """Drive a single inbound message through the agent and send the reply."""
    logger.info(
        "route_inbound",
        platform=msg.platform,
        thread_id=msg.thread_id,
        is_master=msg.is_master,
        text_len=len(msg.text or ""),
    )
    ch = channel_registry.get(msg.platform)

    if not msg.is_master:
        # Phase 1: politely refuse non-master messages. Phase 4 introduces
        # the auto-responder for known contacts.
        await ch.send_reply(msg, "I only serve my master.")
        return

    # Update the analytics rollup. LangGraph owns the actual message rows
    # via its checkpointer; this is just for the dashboard.
    await session_mgr.upsert_analytics(
        thread_id=msg.thread_id,
        platform=msg.platform,
        channel_user_id=msg.channel_user_id,
    )

    await ch.show_typing(msg)

    try:
        result = await run_turn(
            user_message=msg.text,
            thread_id=msg.thread_id,
            platform=msg.platform,
            channel_user_id=msg.channel_user_id,
        )
    except Exception as exc:
        logger.exception(
            "route_inbound_failed",
            thread_id=msg.thread_id,
            error=str(exc),
        )
        await ch.send_reply(msg, f"Something went wrong: {str(exc)[:200]}")
        return

    if result["status"] == "complete":
        if result["response"]:
            await ch.send_reply(msg, result["response"])
        return

    if result["status"] == "interrupted":
        # Approval prompt was already sent by the tool_executor node via
        # failure_alerter.send_approval_request_to_master. Nothing to do
        # here — master will Approve/Reject and that triggers
        # route_approval_decision below.
        logger.info("turn_interrupted_for_approval", thread_id=msg.thread_id)
        return

    # status == "error"
    await ch.send_reply(msg, result.get("response") or "I hit an error.")


async def route_approval_decision(
    thread_id: str,
    platform: str,
    decision: dict[str, Any],
) -> None:
    """Resume a paused graph after master approves/rejects — OR, for channel-
    originated approvals (Gmail today, calendar/booking later), dispatch the
    action directly without going through LangGraph resume.

    Channel-originated approvals don't have a real LangGraph thread to resume
    (they were created by app.email.gmail_pubsub._queue_email_approval, not by
    a tool_executor_node interrupt). Trying to resume_turn() against
    `gmail:<msg_id>` fails with a "no checkpoint" error, which used to surface
    as a "Resume failed" noise alert on every Gmail approval (see
    project_gmail_approval_resume_fails_no_langgraph_thread.md). The dispatch
    table below routes those approvals to channel-specific resolvers instead.

    decision shape:
        {"approved": True}
        {"approved": False, "reason": "..."}
    """
    # Channel-originated dispatch: prefix-match the thread_id.
    # Future channels (calendar:, booking:, web_form:) plug in here.
    if thread_id.startswith("gmail:"):
        await _resolve_gmail_approval(thread_id, platform, decision)
        return

    # Default: LangGraph-tool-call approval, resume via the checkpointer.
    result = await resume_turn(thread_id=thread_id, decision=decision)
    ch = channel_registry.get(platform)

    if result["status"] == "complete" and result["response"]:
        # No original-message context to reply-to; surface as a system alert.
        await ch.send_alert(result["response"])
    elif result["status"] == "interrupted":
        logger.info("resume_paused_again", thread_id=thread_id)
    elif result["status"] == "error":
        await ch.send_alert(result.get("response") or "Resume failed.")


async def _resolve_gmail_approval(
    thread_id: str,
    platform: str,
    decision: dict[str, Any],
) -> None:
    """Approve/Reject handler for Gmail-originated approvals.

    On approve: read the PendingApproval row's payload to recover the draft +
    recipient + threading info, call gmail_send directly. Falls back to
    fetching headers from Gmail if the payload is missing them (rows created
    before Turn 17.5 don't have subject + rfc822_message_id).

    On reject: no action — `resolve_approval` already marked the DB row
    `status='rejected'` before this function fired, and there's no outbound
    side effect to skip. The original email stays in INBOX for master to
    handle manually."""
    ch = channel_registry.get(platform)

    if not decision.get("approved"):
        logger.info("gmail_approval_rejected", thread_id=thread_id)
        return

    # Look up the PendingApproval row by thread_id. Approvals here are 1:1
    # with thread_id (a single email maps to one approval), so this is
    # unambiguous.
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
        await ch.send_alert(
            f"Approval for {thread_id} couldn't be dispatched — the "
            f"PendingApproval row wasn't found in the database."
        )
        return

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
        await ch.send_alert(
            f"Approval for {thread_id} can't be sent — the stored draft data "
            f"is incomplete. Check the pending_approvals row."
        )
        return

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
    from email.utils import parseaddr

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
        logger.info("gmail_approval_dispatched", thread_id=thread_id, result=send_result)
        await ch.send_alert(
            f"✅ Reply sent to {recipient_addr}\n"
            f"Subject: {reply_subject}\n"
            f"{send_result}"
        )
    except Exception as exc:  # noqa: BLE001
        logger.exception("gmail_approval_send_failed", thread_id=thread_id, error=str(exc))
        await ch.send_alert(
            f"❌ Failed to send reply for `{thread_id}`:\n```\n{str(exc)[:500]}\n```"
        )
