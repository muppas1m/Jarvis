"""
Public agent entry point.

The messaging layer (Telegram channel, web chat API, future iMessage / Discord
adapters) calls into this module ONLY. Everything below — graph wiring,
checkpointer state, interrupt detection — stays internal.

Two surfaces:

  run_turn(user_message, thread_id, platform, channel_user_id)
      Start a fresh turn. Returns a TurnEnvelope dict.

  resume_turn(thread_id, decision)
      Continue a paused graph after the master approves/rejects.
      decision: {"approved": True} or {"approved": False, "reason": "..."}.
      Same return shape; can re-pause if a follow-up tool also requires APPROVE.

Both compile the graph lazily (build_graph() reads the checkpointer singleton).

The TurnEnvelope is the canonical shape both for HTTP responses (/api/chat,
/api/approvals/{id}/decide) and for the messaging layer's reply rendering.
One shape, two transports — no factoring drift between Telegram callbacks
and dashboard POSTs. Old fields (status, response, interrupt) are kept
backward-compatible; new fields (thread_id, messages, trace_id, usage) are
added on top.
"""
import time
from datetime import datetime, timezone
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, ToolMessage
from langgraph.types import Command

from app.agent.graph import build_graph
from app.llm.observability import langfuse_callback_handler
from app.utils.exceptions import CostCapExceededError
from app.utils.logging import get_logger

logger = get_logger(__name__)


# Exit-path → stop_reason. status and stop_reason are derived together at each
# exit so they can't disagree (same dual-field discipline as 17.8's classification
# column + meta). Vocabulary follows the Claude SDK:
#   end_turn    — natural completion                  (status "complete")
#   rate_limit  — per-hour turn cap hit; agent returned a graceful notice
#                 (status "complete", final_response sentinel "rate_limited")
#   interrupted — paused on an approval               (status "interrupted")
#   pending_approval — free-text turn declined because an approval is still
#                 pending; nudge to use the buttons    (status "complete")
#   cost_cap    — gateway refused on the daily hard cap (status "error")
#   error       — any other exception                 (status "error")
# Note: the per-turn TOOL budget (MAX_TOOL_CALLS_PER_TURN) is NOT a turn-terminal
# reason — a blocked tool degrades to a ToolMessage and the agent still ends the
# turn naturally (end_turn). That event is captured per-tool in audit_trail +
# rate_limit_events, not at the envelope level.
def _stop_reason_for_completion(result: dict) -> str:
    return "rate_limit" if result.get("final_response") == "rate_limited" else "end_turn"


def _stop_reason_for_error(exc: BaseException) -> str:
    return "cost_cap" if isinstance(exc, CostCapExceededError) else "error"


_graph = None


def graph():
    """Compiled graph singleton — built on first use, after init_checkpointer."""
    global _graph
    if _graph is None:
        _graph = build_graph()
    return _graph


def _config_with_handler(thread_id: str) -> tuple[dict, Any | None]:
    """Per-call config + the langfuse handler reference (so we can pull
    trace_id off it after the run). Returns (config, handler_or_None)."""
    handler = langfuse_callback_handler(thread_id)
    callbacks = [handler] if handler is not None else []
    config = {
        "configurable": {"thread_id": thread_id},
        "callbacks": callbacks,
    }
    return config, handler


async def run_turn(
    user_message: str,
    thread_id: str,
    platform: str,
    channel_user_id: str,
) -> dict[str, Any]:
    """Execute one user turn through the agent graph."""
    config, handler = _config_with_handler(thread_id)

    # Prevent-at-source: if this thread is paused at an approval interrupt, a
    # fresh free-text turn would append a HumanMessage *after* the pending
    # AIMessage tool_call — orphaning it (no ToolMessage) and poisoning the
    # history, so the next LLM call (the OpenAI fallback) 400s the whole thread.
    # That was the Jun-11 terminal "internal error": the master confirmed an
    # approval by typing instead of tapping the button. Don't start a new turn;
    # leave the interrupt intact (its Approve/Reject buttons still resolve it)
    # and nudge. Honoring free text AS the approval is the deferred
    # conversational-send path (project_email_action_capability_gap) — out of
    # scope here; this only stops the crash.
    if await _is_awaiting_approval(thread_id):
        logger.info("run_turn_blocked_pending_interrupt", thread_id=thread_id)
        return _pending_interrupt_envelope(thread_id)

    # Snapshot existing message count so we can slice "this turn's" messages
    # out of the post-invoke state. Cheaper and more reliable than timestamp-
    # filtering on response_metadata (which not every provider stamps).
    msgs_before = await _existing_message_count(thread_id)

    initial_state = {
        "messages": [HumanMessage(content=user_message)],
        "thread_id": thread_id,
        "platform": platform,
        "channel_user_id": channel_user_id,
        "user_message": user_message,
        "turn_started_at": datetime.now(timezone.utc).isoformat(),
    }

    started_ms = time.monotonic()
    try:
        result = await graph().ainvoke(initial_state, config=config)
    except Exception as exc:
        logger.exception("graph_invoke_failed", thread_id=thread_id, error=str(exc))
        logger.info(
            "turn_complete", thread_id=thread_id, status="error",
            stop_reason=_stop_reason_for_error(exc), tool_calls=None,
        )
        return _error_envelope(
            thread_id, "I hit an internal error. Please try again.",
            stop_reason=_stop_reason_for_error(exc),
        )

    duration_ms = int((time.monotonic() - started_ms) * 1000)
    envelope = await _build_envelope(
        thread_id=thread_id,
        result=result,
        config=config,
        msgs_before=msgs_before,
        duration_ms=duration_ms,
        handler=handler,
    )
    logger.info(
        "turn_complete",
        thread_id=thread_id,
        status=envelope["status"],
        stop_reason=envelope.get("stop_reason"),
        tool_calls=sum(
            1 for m in (result.get("messages") or []) if isinstance(m, ToolMessage)
        ),
    )
    return envelope


async def resume_turn(
    thread_id: str,
    decision: dict[str, Any],
) -> dict[str, Any]:
    """Resume a graph paused at an interrupt() (typically an APPROVE-level tool).

    decision shape:
        {"approved": True}
        {"approved": False, "reason": "looks risky"}
    """
    config, handler = _config_with_handler(thread_id)
    msgs_before = await _existing_message_count(thread_id)

    started_ms = time.monotonic()
    try:
        result = await graph().ainvoke(Command(resume=decision), config=config)
    except Exception as exc:
        logger.exception("graph_resume_failed", thread_id=thread_id, error=str(exc))
        return _error_envelope(
            thread_id, "I hit an internal error while resuming. Please try again.",
            stop_reason=_stop_reason_for_error(exc),
        )

    duration_ms = int((time.monotonic() - started_ms) * 1000)
    return await _build_envelope(
        thread_id=thread_id,
        result=result,
        config=config,
        msgs_before=msgs_before,
        duration_ms=duration_ms,
        handler=handler,
    )


# --------------------------------------------------------------------------- #
# Envelope construction                                                       #
# --------------------------------------------------------------------------- #


async def _existing_message_count(thread_id: str) -> int:
    """Read the current persisted message count for this thread.

    Returns 0 for a brand-new thread (checkpointer has nothing for it yet).
    Used as the slice boundary for "messages produced by this turn"."""
    config = {"configurable": {"thread_id": thread_id}}
    try:
        state = await graph().aget_state(config)
    except Exception:  # noqa: BLE001
        return 0
    if state is None or not state.values:
        return 0
    return len(state.values.get("messages") or [])


async def _is_awaiting_approval(thread_id: str) -> bool:
    """True if the thread is paused at an interrupt (an unresolved approval).

    A non-empty ``state.next`` means the graph stopped mid-step waiting on
    ``Command(resume=...)`` — the same signal `_build_envelope` uses to surface
    an interrupt payload. A fresh `run_turn` here would orphan the pending
    tool_call, so the caller routes to the nudge instead. Fail-open (return
    False) on any state-read error: never block a normal turn because the
    checkpoint read hiccuped."""
    config = {"configurable": {"thread_id": thread_id}}
    try:
        state = await graph().aget_state(config)
    except Exception:  # noqa: BLE001
        return False
    # getattr-defensive: a StateSnapshot always has .next, but never block a
    # normal turn if some state shape lacks it.
    return bool(state and getattr(state, "next", None))


def _error_envelope(
    thread_id: str, response_text: str, stop_reason: str = "error"
) -> dict[str, Any]:
    return {
        "thread_id": thread_id,
        "status": "error",
        "stop_reason": stop_reason,
        "response": response_text,
        "messages": [],
        "interrupt": None,
        "trace_id": None,
        "usage": _empty_usage(0),
    }


def _pending_interrupt_envelope(thread_id: str) -> dict[str, Any]:
    """Envelope for a free-text turn that arrived while an approval is still
    pending. status='complete' (nothing failed — we deliberately declined to
    start a turn) with a nudge to use the Approve/Reject buttons. No interrupt
    payload: the original approval message already carries the live buttons, so
    we don't re-send them (which would mint a duplicate approval row). The
    pending interrupt is left untouched and still resolves via those buttons."""
    return {
        "thread_id": thread_id,
        "status": "complete",
        "stop_reason": "pending_approval",
        "response": (
            "You've got an action waiting for your approval. Please tap "
            "**Approve** or **Reject** on that message first, then send this again."
        ),
        "messages": [],
        "interrupt": None,
        "trace_id": None,
        "usage": _empty_usage(0),
    }


async def _build_envelope(
    thread_id: str,
    result: dict,
    config: dict,
    msgs_before: int,
    duration_ms: int,
    handler: Any | None,
) -> dict[str, Any]:
    """Assemble the standard TurnEnvelope from a graph invoke result.

    Detects fresh interrupts by querying graph.aget_state — if state.next
    is non-empty the graph paused mid-step and we surface the interrupt
    payload. Otherwise the turn is complete (or last-resort error)."""
    state = await graph().aget_state(config)
    all_messages: list[BaseMessage] = result.get("messages") or []
    new_messages = all_messages[msgs_before:]
    serialized = [_serialize_message(m) for m in new_messages]
    usage = _aggregate_usage(new_messages, duration_ms)
    trace_id = _safe_trace_id(handler)

    if state and state.next:
        interrupts = []
        for task in state.tasks:
            interrupts.extend(getattr(task, "interrupts", []) or [])
        if interrupts:
            first = interrupts[0]
            payload = first.value if hasattr(first, "value") else dict(first)
            return {
                "thread_id": thread_id,
                "status": "interrupted",
                "stop_reason": "interrupted",
                "response": "",
                "messages": serialized,
                "interrupt": payload,
                "trace_id": trace_id,
                "usage": usage,
            }

    return {
        "thread_id": thread_id,
        "status": "complete",
        "stop_reason": _stop_reason_for_completion(result),
        "response": result.get("final_response") or _extract_last_assistant_text(result),
        "messages": serialized,
        "interrupt": None,
        "trace_id": trace_id,
        "usage": usage,
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


# --------------------------------------------------------------------------- #
# Serialization helpers                                                       #
# --------------------------------------------------------------------------- #


def _serialize_message(m: BaseMessage) -> dict[str, Any]:
    """LangChain BaseMessage → compact dict for HTTP. Keeps tool_calls and
    tool_call_id for transparency; drops bulky internals (response_metadata,
    usage_metadata — usage is aggregated separately)."""
    if isinstance(m, AIMessage):
        out: dict[str, Any] = {
            "role": "ai",
            "content": m.content if isinstance(m.content, str) else str(m.content),
        }
        if m.tool_calls:
            out["tool_calls"] = [
                {"name": tc["name"], "args": tc.get("args") or {}, "id": tc["id"]}
                for tc in m.tool_calls
            ]
        return out
    if isinstance(m, ToolMessage):
        return {
            "role": "tool",
            "tool_call_id": m.tool_call_id,
            "name": getattr(m, "name", None),
            "content": m.content if isinstance(m.content, str) else str(m.content),
        }
    if isinstance(m, HumanMessage):
        return {"role": "human", "content": m.content if isinstance(m.content, str) else str(m.content)}
    return {"role": getattr(m, "type", "unknown"), "content": str(m.content)}


def _empty_usage(duration_ms: int) -> dict[str, Any]:
    return {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "cost_usd": 0.0,
        "duration_ms": duration_ms,
    }


def _aggregate_usage(new_messages: list[BaseMessage], duration_ms: int) -> dict[str, Any]:
    """Sum tokens across all AIMessages produced this turn. Cost is best-
    effort via litellm.completion_cost — providers without pricing data
    in litellm's table contribute 0.

    Skipping LLMUsageLog on purpose: the persistence callback writes after
    this function returns, so a SELECT here would read-after-write race."""
    input_tokens = 0
    output_tokens = 0
    cost_usd = 0.0

    try:
        from litellm import completion_cost
    except ImportError:
        completion_cost = None  # type: ignore[assignment]

    for m in new_messages:
        if not isinstance(m, AIMessage):
            continue
        meta = getattr(m, "usage_metadata", None) or {}
        in_t = int(meta.get("input_tokens", 0) or 0)
        out_t = int(meta.get("output_tokens", 0) or 0)
        input_tokens += in_t
        output_tokens += out_t

        if completion_cost is not None and (in_t or out_t):
            model_name = (
                (m.response_metadata or {}).get("model_name")
                or (m.response_metadata or {}).get("model")
                or ""
            )
            if model_name:
                try:
                    cost_usd += float(completion_cost(
                        model=model_name,
                        prompt_tokens=in_t,
                        completion_tokens=out_t,
                    ) or 0.0)
                except Exception:  # noqa: BLE001
                    # Pricing not in litellm's table for this model — skip,
                    # the /costs endpoint reconciles from LLMUsageLog rows
                    # once the persistence callback has flushed.
                    pass

    return {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "cost_usd": round(cost_usd, 6),
        "duration_ms": duration_ms,
    }


def _safe_trace_id(handler: Any | None) -> str | None:
    """Pull the langfuse trace_id off the per-call handler.

    Different langfuse versions expose it differently — try the documented
    method first, fall back to attributes, return None if neither works.
    Never raises — observability data is best-effort."""
    if handler is None:
        return None
    try:
        if hasattr(handler, "get_trace_id"):
            tid = handler.get_trace_id()
            if tid:
                return tid
    except Exception:  # noqa: BLE001
        pass
    try:
        trace = getattr(handler, "trace", None)
        if trace is not None:
            tid = getattr(trace, "id", None)
            if tid:
                return tid
    except Exception:  # noqa: BLE001
        pass
    return None
