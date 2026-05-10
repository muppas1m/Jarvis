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
    """Resume a paused graph after the master approves/rejects.

    decision shape:
        {"approved": True}
        {"approved": False, "reason": "..."}
    """
    result = await resume_turn(thread_id=thread_id, decision=decision)
    ch = channel_registry.get(platform)

    if result["status"] == "complete" and result["response"]:
        # No original-message context to reply-to; surface as a system alert.
        await ch.send_alert(result["response"])
    elif result["status"] == "interrupted":
        logger.info("resume_paused_again", thread_id=thread_id)
    elif result["status"] == "error":
        await ch.send_alert(result.get("response") or "Resume failed.")
