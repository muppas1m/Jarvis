"""
Public agent entry point.

The messaging layer (Telegram channel, web chat API, future iMessage / Discord
adapters) calls into this module ONLY. Everything below — graph wiring,
checkpointer state, interrupt detection — stays internal.

Two surfaces:

  run_turn(user_message, thread_id, platform, channel_user_id)
      Start a fresh turn. Returns a dict that says either:
        - status="complete"     — graph finished, response is the assistant text
        - status="interrupted"  — graph paused at an APPROVE; payload tells the
                                   caller what's pending
        - status="error"        — last-resort wrapper, internal error already logged

  resume_turn(thread_id, decision)
      Continue a paused graph after the master approves/rejects.
      decision: {"approved": True} or {"approved": False, "reason": "..."}.
      Same return shape; can re-pause if a follow-up tool also requires APPROVE.

Both compile the graph lazily (build_graph() reads the checkpointer singleton).
"""
from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.types import Command

from app.agent.graph import build_graph
from app.llm.observability import langfuse_callback_handler
from app.utils.logging import get_logger

logger = get_logger(__name__)


_graph = None


def graph():
    """Compiled graph singleton — built on first use, after init_checkpointer."""
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


def _config_for(thread_id: str) -> dict:
    """Per-call config: thread_id (LangGraph routing) + Langfuse callback if available."""
    callbacks = [cb for cb in [langfuse_callback_handler(thread_id)] if cb is not None]
    return {
        "configurable": {"thread_id": thread_id},
        "callbacks": callbacks,
    }


async def run_turn(
    user_message: str,
    thread_id: str,
    platform: str,
    channel_user_id: str,
) -> dict[str, Any]:
    """Execute one user turn through the agent graph."""
    config = _config_for(thread_id)

    initial_state = {
        "messages": [HumanMessage(content=user_message)],
        "thread_id": thread_id,
        "platform": platform,
        "channel_user_id": channel_user_id,
        "user_message": user_message,
        "turn_started_at": datetime.now(timezone.utc).isoformat(),
    }

    try:
        result = await graph().ainvoke(initial_state, config=config)
    except Exception as exc:
        logger.exception("graph_invoke_failed", thread_id=thread_id, error=str(exc))
        return {
            "status": "error",
            "response": "I hit an internal error. Please try again.",
            "interrupt": None,
        }

    return await _shape_result(result, config)


async def resume_turn(
    thread_id: str,
    decision: dict[str, Any],
) -> dict[str, Any]:
    """Resume a graph paused at an interrupt() (typically an APPROVE-level tool).

    decision shape:
        {"approved": True}
        {"approved": False, "reason": "looks risky"}
    """
    config = _config_for(thread_id)

    try:
        result = await graph().ainvoke(Command(resume=decision), config=config)
    except Exception as exc:
        logger.exception("graph_resume_failed", thread_id=thread_id, error=str(exc))
        return {
            "status": "error",
            "response": "I hit an internal error while resuming. Please try again.",
            "interrupt": None,
        }

    return await _shape_result(result, config)


async def _shape_result(result: dict, config: dict) -> dict[str, Any]:
    """Inspect post-invoke graph state to detect a fresh interrupt; otherwise
    return the assistant's response."""
    state = await graph().aget_state(config)

    if state.next:
        # The graph paused. Pull the interrupt payload off the pending tasks
        # so the caller knows what to ask the master about.
        interrupts = []
        for task in state.tasks:
            interrupts.extend(getattr(task, "interrupts", []) or [])
        if interrupts:
            first = interrupts[0]
            payload = first.value if hasattr(first, "value") else dict(first)
            return {"status": "interrupted", "response": None, "interrupt": payload}

    return {
        "status": "complete",
        "response": result.get("final_response") or _extract_last_assistant_text(result),
        "interrupt": None,
    }


def _extract_last_assistant_text(state_dict: dict) -> str:
    """Walk the message history backwards to find the most recent non-empty
    assistant message. Used as a fallback when final_response wasn't set
    (e.g. the graph's last step was a tool call rather than a text reply)."""
    msgs = state_dict.get("messages") or []
    for m in reversed(msgs):
        if isinstance(m, AIMessage) and isinstance(m.content, str) and m.content.strip():
            return m.content
    return ""
