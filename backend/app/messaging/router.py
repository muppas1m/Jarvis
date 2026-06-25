"""
Inbound routing.

  route_inbound(NormalizedMessage)
      Take a freshly-normalized inbound message, drive run_turn(), and send
      the reply back via the same channel. Updates ConversationAnalytics on
      the way through. An APPROVE-tier tool no longer pauses the turn (Phase 3
      retired interrupt()): it QUEUES a PendingApproval and the turn completes.
      The master approves/rejects from the channel UI, which resolves through
      the claim-gated dispatcher (resolve_and_dispatch) — not this router.

The agent (`runner.py`) is callable from anywhere; the router is what knows
about channels.
"""
from app.agent.runner import run_turn
from app.memory.session import SessionManager
from app.messaging.channel import NormalizedMessage
from app.messaging.channel_registry import channel_registry
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
        # Defensive: a fresh turn no longer interrupts (Phase 3 — APPROVE-tier
        # tools QUEUE instead). An APPROVE tool surfaces its own card via
        # failure_alerter.send_approval_request_to_master and the turn completes;
        # the master resolves it from the channel UI through the claim-gated
        # dispatcher. Kept only as a belt-and-braces no-reply for any legacy state.
        logger.info("turn_interrupted_for_approval", thread_id=msg.thread_id)
        return

    # status == "error"
    await ch.send_reply(msg, result.get("response") or "I hit an error.")
