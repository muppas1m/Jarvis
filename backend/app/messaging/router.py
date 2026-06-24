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
from app.email.approval_handler import EMAIL_THREAD_PREFIXES
from app.email.approval_handler import resolve as resolve_email
from app.memory.session import SessionManager
from app.messaging.channel import NormalizedMessage
from app.messaging.channel_registry import channel_registry
from app.utils.logging import get_logger

logger = get_logger(__name__)
session_mgr = SessionManager()

# Channel-originated approvals don't have a LangGraph thread to resume — they
# were minted by an ingestion path (Gmail today; calendar/booking/web-form
# later), not by a tool_executor interrupt. Each prefix maps to a domain handler
# that resolves the action directly. Adding a 2nd handler is one dict entry + its
# module (see project_gmail_handler_decoupling_deferral). The router stays a thin
# dispatcher — no domain logic lives here.
CHANNEL_ORIGIN_HANDLERS = {
    prefix: resolve_email for prefix in EMAIL_THREAD_PREFIXES
}


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
    (they were created by app.email.inbound._queue_email_approval, not by
    a tool_executor_node interrupt). Trying to resume_turn() against
    `gmail:<msg_id>` fails with a "no checkpoint" error, which used to surface
    as a "Resume failed" noise alert on every Gmail approval (see
    project_gmail_approval_resume_fails_no_langgraph_thread.md). The
    CHANNEL_ORIGIN_HANDLERS dispatch table routes those to their domain handler
    instead.

    decision shape:
        {"approved": True}
        {"approved": False, "reason": "..."}
    """
    # Channel-originated dispatch: prefix-match the thread_id to a domain handler.
    for prefix, handler in CHANNEL_ORIGIN_HANDLERS.items():
        if thread_id.startswith(prefix):
            await handler(thread_id, platform, decision)
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
