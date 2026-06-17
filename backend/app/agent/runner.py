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
import asyncio
import base64
import contextlib
import time
from datetime import datetime, timezone
from typing import Any, AsyncIterator

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    RemoveMessage,
    ToolMessage,
)
from langgraph.types import Command

from app.agent.graph import build_graph, reset_thread
from app.config import settings
from app.llm.observability import langfuse_callback_handler
from app.llm.stream_mode import stream_tokens, voice_mode
from app.utils.exceptions import CostCapExceededError
from app.utils.logging import get_logger
from app.voice.chunker import SentenceChunker
from app.voice.tts import audio_mime, synthesize

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


async def get_history(thread_id: str) -> list[dict[str, Any]]:
    """Replay a thread's persisted messages from the checkpointer (read-only).

    Queries the compiled graph's saved state for ``thread_id`` and serializes the
    history with the same ``_serialize_message`` live turns use, so the dashboard
    renders a reloaded conversation identically to a streamed one. Returns ``[]``
    for a thread with no checkpoint yet (fresh or unknown id). No langfuse
    handler/trace is created — this is a read, not a turn."""
    config = {"configurable": {"thread_id": thread_id}}
    snapshot = await graph().aget_state(config)
    values = getattr(snapshot, "values", None) or {}
    messages: list[BaseMessage] = values.get("messages") or []
    return [_serialize_message(m) for m in messages]


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

    # Clean any barge-in / send-over cancellation residue (dirty state.next +
    # orphaned tool_call) so this fresh turn starts on a consistent thread.
    await _recover_cancellation_residue(thread_id)

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
# Streaming surface (Phase 4 — true token streaming through the same graph)   #
# --------------------------------------------------------------------------- #


async def stream_turn(
    user_message: str,
    thread_id: str,
    platform: str,
    channel_user_id: str,
) -> AsyncIterator[dict[str, Any]]:
    """Token-streaming variant of run_turn over the SAME agent graph.

    Yields ready-to-serialize event dicts for the SSE/WebSocket transport:
      {"type": "thread_id", "content": <id>}              once, first
      {"type": "token", "content": <text delta>}          per LLM token (agent node)
      {"type": "tool",  "content": <tool_name>}            when the agent calls a tool
      {"type": "approval_required", "content": <payload>, "thread_id": <id>}
      {"type": "done",  "content": <terminal envelope subset>}
      {"type": "error", "content": <msg>, "stop_reason": <reason>}

    The brain is untouched. This drives `graph().astream(..., stream_mode=
    ["messages","updates"])` with the `stream_tokens` contextvar set, so the
    agent's ChatLiteLLM streams its tokens (messages mode) while node-level
    updates surface tool calls (updates mode). The interrupt()/approval path
    is preserved exactly — a paused graph stops yielding, and the post-stream
    checkpoint read surfaces the interrupt the same way run_turn does.

    The authoritative final text + usage come from the post-stream checkpoint
    and ship in the terminal event — so even if a mid-stream FallbackChatLLM
    fall-over re-emits tokens (rare; the primary streamed a partial before
    erroring), the client renders the canonical answer from "done"/"approval".
    """
    yield {"type": "thread_id", "content": thread_id}

    config, handler = _config_with_handler(thread_id)

    # Same prevent-at-source guard as run_turn: a fresh free-text turn while an
    # approval is pending would orphan the tool_call and poison the thread.
    if await _is_awaiting_approval(thread_id):
        logger.info("stream_turn_blocked_pending_interrupt", thread_id=thread_id)
        yield {"type": "done", "content": _terminal_payload(_pending_interrupt_envelope(thread_id))}
        return

    await _recover_cancellation_residue(thread_id)  # clean barge-in residue first
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
    flag = stream_tokens.set(True)
    try:
        async for mode, data in graph().astream(
            initial_state, config=config, stream_mode=["messages", "updates"]
        ):
            if mode == "messages":
                chunk, meta = data
                # Only the agent node produces user-facing LLM tokens.
                if (meta or {}).get("langgraph_node") != "agent":
                    continue
                text = _chunk_text(chunk)
                if text:
                    yield {"type": "token", "content": text}
            elif mode == "updates":
                # Surface tool calls as the agent decides them (THINKING state).
                for node, upd in (data or {}).items():
                    if node != "agent":
                        continue
                    for m in (upd or {}).get("messages", []) or []:
                        for tc in getattr(m, "tool_calls", None) or []:
                            yield {"type": "tool", "content": tc.get("name", "")}
    except Exception as exc:
        logger.exception("graph_stream_failed", thread_id=thread_id, error=str(exc))
        yield {
            "type": "error",
            "content": "I hit an internal error. Please try again.",
            "stop_reason": _stop_reason_for_error(exc),
        }
        return
    finally:
        stream_tokens.reset(flag)

    duration_ms = int((time.monotonic() - started_ms) * 1000)
    # The post-stream checkpoint is authoritative for interrupt detection,
    # the final assistant text, and usage — same source _build_envelope uses
    # for run_turn, so streaming and non-streaming agree on the terminal shape.
    state = await graph().aget_state(config)
    result = dict(state.values) if state and state.values else {}
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
        streamed=True,
    )
    if envelope["status"] == "interrupted":
        yield {"type": "approval_required", "thread_id": thread_id, "content": envelope["interrupt"]}
    else:
        yield {"type": "done", "content": _terminal_payload(envelope)}


def _chunk_text(chunk: Any) -> str:
    """Printable text from a streamed message chunk.

    Text tokens carry a string `.content`; pure tool-call chunks carry empty
    content (their payload is in tool_call_chunks) so they filter out here.
    Some providers deliver content as a list of parts."""
    content = getattr(chunk, "content", None)
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        out: list[str] = []
        for p in content:
            if isinstance(p, str):
                out.append(p)
            elif isinstance(p, dict) and p.get("type") == "text":
                out.append(p.get("text", ""))
        return "".join(out)
    return ""


def _terminal_payload(envelope: dict[str, Any]) -> dict[str, Any]:
    """Subset of the TurnEnvelope the streaming "done" event carries — the
    client renders this as the canonical final (reconciling any mid-stream
    token noise)."""
    return {
        "status": envelope["status"],
        "stop_reason": envelope.get("stop_reason"),
        "response": envelope.get("response", ""),
        "usage": envelope.get("usage"),
        "thread_id": envelope["thread_id"],
    }


# --------------------------------------------------------------------------- #
# Voice surface (Phase 4 sub-phase 4.1 — "Jarvis speaks")                      #
# --------------------------------------------------------------------------- #

_FILLERS = (
    "One moment, {h}.",
    "Right away, {h}.",
    "Let me see to that, {h}.",
    "Looking into it, {h}.",
)


def _filler_line(index: int) -> str:
    return _FILLERS[index % len(_FILLERS)].format(h=settings.MASTER_HONORIFIC)


def _audio_event(text: str, audio: bytes, *, filler: bool = False) -> dict[str, Any]:
    """An SSE 'audio' event: a spoken sentence + its caption, base64 audio."""
    return {
        "type": "audio",
        "content": {
            "text": text,
            "audio": base64.b64encode(audio).decode("ascii"),
            "mime": audio_mime(),
            "filler": filler,
        },
    }


def _approval_speech(interrupt: dict[str, Any]) -> str:
    """Spoken form of an approval request. In 4.1 the master still resolves it
    with the Approve/Reject buttons; the hands-free voice resolver is 4.3."""
    tool = (interrupt or {}).get("tool_name", "an action")
    h = settings.MASTER_HONORIFIC
    return f"{h}, I've prepared {tool}. Please review and approve it when you're ready."


async def voice_turn(
    user_message: str,
    thread_id: str,
    platform: str,
    channel_user_id: str,
) -> AsyncIterator[dict[str, Any]]:
    """Voice-OUT turn over the SAME graph as run_turn — but speed-tuned and spoken.

    Sets the `voice_mode` (fast-tier routing, §B) + `stream_tokens` contextvars,
    drives `graph().astream(...)`, slices the token stream into sentences, and
    synthesises each sentence to streaming TTS so audio starts on the first
    sentence (§D-1). An instant filler masks first-token latency. The interrupt
    approval path is preserved — Jarvis speaks the request; the buttons resolve
    it in 4.1 (the hands-free voice resolver is 4.3).

    Yields the stream_turn events plus, per spoken sentence:
      {"type": "audio", "content": {"text", "audio"(b64), "mime", "filler"}}

    The turn is fully cancellable — if the consumer (an aborted SSE / a future
    barge-in) stops iterating, the producer task and the in-flight graph turn
    are cancelled. That is the barge-in foundation architected from 4.1.
    """
    yield {"type": "thread_id", "content": thread_id}

    config, handler = _config_with_handler(thread_id)

    if await _is_awaiting_approval(thread_id):
        env = _pending_interrupt_envelope(thread_id)
        audio = await synthesize(env["response"])
        if audio:
            yield _audio_event(env["response"], audio)
        yield {"type": "done", "content": _terminal_payload(env)}
        return

    await _recover_cancellation_residue(thread_id)  # clean barge-in residue first
    msgs_before = await _existing_message_count(thread_id)
    initial_state = {
        "messages": [HumanMessage(content=user_message)],
        "thread_id": thread_id,
        "platform": platform,
        "channel_user_id": channel_user_id,
        "user_message": user_message,
        "turn_started_at": datetime.now(timezone.utc).isoformat(),
    }

    chunker = SentenceChunker()
    filler_budget = settings.VOICE_FILLER_DELAY_MS / 1000.0
    started_ms = time.monotonic()

    # Set the contextvars BEFORE create_task so the producer task inherits them.
    flag_v = voice_mode.set(True)
    flag_s = stream_tokens.set(True)
    queue: asyncio.Queue = asyncio.Queue()

    async def _produce() -> None:
        try:
            async for item in graph().astream(
                initial_state, config=config, stream_mode=["messages", "updates"]
            ):
                await queue.put(("stream", item))
        except Exception as exc:  # noqa: BLE001 — surfaced to the consumer below
            await queue.put(("error", exc))
        finally:
            await queue.put(("end", None))

    producer = asyncio.create_task(_produce())
    first_token = False
    filler_sent = False
    error_exc: BaseException | None = None

    async def _speak(sentence: str, *, filler: bool = False):
        audio = await synthesize(sentence)
        if audio:
            return _audio_event(sentence, audio, filler=filler)
        return None

    try:
        while True:
            try:
                timeout = filler_budget if (not first_token and not filler_sent) else None
                kind, payload = await asyncio.wait_for(queue.get(), timeout=timeout)
            except asyncio.TimeoutError:
                # No first token within the budget — mask the wait with a filler.
                filler_sent = True
                ev = await _speak(_filler_line(0), filler=True)
                if ev:
                    yield ev
                continue

            if kind == "end":
                break
            if kind == "error":
                error_exc = payload
                break

            mode, data = payload
            if mode == "messages":
                chunk, meta = data
                if (meta or {}).get("langgraph_node") != "agent":
                    continue
                text = _chunk_text(chunk)
                if text:
                    if not first_token:
                        logger.info(
                            "voice_timing", seg="first_token",
                            ms=int((time.monotonic() - started_ms) * 1000),
                        )
                    first_token = True
                    yield {"type": "token", "content": text}
                    for sentence in chunker.push(text):
                        ev = await _speak(sentence)
                        if ev:
                            yield ev
            elif mode == "updates":
                for node, upd in (data or {}).items():
                    if node != "agent":
                        continue
                    for m in (upd or {}).get("messages", []) or []:
                        for tc in getattr(m, "tool_calls", None) or []:
                            yield {"type": "tool", "content": tc.get("name", "")}

        # Speak any trailing partial sentence.
        tail = chunker.flush()
        if tail:
            ev = await _speak(tail)
            if ev:
                yield ev
    except asyncio.CancelledError:
        producer.cancel()
        raise
    finally:
        if not producer.done():
            producer.cancel()
            with contextlib.suppress(Exception):
                await producer
        stream_tokens.reset(flag_s)
        voice_mode.reset(flag_v)

    if error_exc is not None:
        logger.exception("voice_stream_failed", thread_id=thread_id, error=str(error_exc))
        msg = "I hit an internal error. Please try again."
        ev = await _speak(msg)
        if ev:
            yield ev
        yield {"type": "error", "content": msg, "stop_reason": _stop_reason_for_error(error_exc)}
        return

    duration_ms = int((time.monotonic() - started_ms) * 1000)
    state = await graph().aget_state(config)
    result = dict(state.values) if state and state.values else {}
    envelope = await _build_envelope(
        thread_id=thread_id,
        result=result,
        config=config,
        msgs_before=msgs_before,
        duration_ms=duration_ms,
        handler=handler,
    )
    logger.info(
        "turn_complete", thread_id=thread_id, status=envelope["status"],
        stop_reason=envelope.get("stop_reason"), voiced=True,
    )
    if envelope["status"] == "interrupted":
        interrupt = envelope.get("interrupt") or {}
        ev = await _speak(_approval_speech(interrupt))
        if ev:
            yield ev
        yield {"type": "approval_required", "thread_id": thread_id, "content": interrupt}
    else:
        yield {"type": "done", "content": _terminal_payload(envelope)}


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


def _collect_interrupts(state: Any) -> list:
    """The REAL interrupt payloads on a paused graph — ``task.interrupts``, the
    same signal `_build_envelope` surfaces. A non-empty ``state.next`` alone is
    NOT enough: a barge-in / send-over cancels the graph mid-step and leaves
    ``state.next`` dirty with NO interrupt (cancellation residue). Only a genuine
    ``interrupt()`` pause (an approval) populates ``task.interrupts``."""
    if not (state and getattr(state, "next", None)):
        return []
    interrupts: list = []
    for task in getattr(state, "tasks", []) or []:
        interrupts.extend(getattr(task, "interrupts", None) or [])
    return interrupts


async def _is_awaiting_approval(thread_id: str) -> bool:
    """True only if the thread is genuinely paused at an ``interrupt()`` (an
    unresolved approval), i.e. there's a real ``task.interrupts``.

    NOT merely a non-empty ``state.next`` — a barge-in cancels the graph mid-step
    and leaves ``state.next`` dirty with no interrupt, which the old check
    false-positived into a phantom "approval waiting" nudge (empty Approvals
    screen). Cancellation residue is handled by `_recover_cancellation_residue`,
    not here. Fail-open (return False) on any state-read error: never block a
    normal turn because the checkpoint read hiccuped."""
    config = {"configurable": {"thread_id": thread_id}}
    try:
        state = await graph().aget_state(config)
    except Exception:  # noqa: BLE001
        return False
    return bool(_collect_interrupts(state))


async def _recover_cancellation_residue(thread_id: str) -> None:
    """Clean barge-in / send-over residue BEFORE a fresh turn starts.

    Cancelling the graph mid-step (e.g. while a tool was pending) leaves a
    non-empty ``state.next`` with NO interrupt and, if it died mid-tool, an
    orphaned ``AIMessage`` tool_call (no matching ``ToolMessage``) — which would
    poison the next LLM call (provider 400s the whole thread) and/or double-run
    the cancelled tool. Drop the orphaned tool_call messages and advance the
    pending step to END (``as_node="persist"``) so the thread starts clean.

    No-op when the thread is already clean OR genuinely paused at an approval
    interrupt (that's left intact for its Approve/Reject buttons)."""
    config = {"configurable": {"thread_id": thread_id}}
    try:
        state = await graph().aget_state(config)
    except Exception:  # noqa: BLE001
        return
    if not (state and getattr(state, "next", None)):
        return  # clean
    if _collect_interrupts(state):
        return  # genuine approval pause — don't touch it
    msgs = (state.values or {}).get("messages", []) if state.values else []
    answered = {m.tool_call_id for m in msgs if isinstance(m, ToolMessage)}
    # Orphaned AIMessages — at least one tool_call with no answering ToolMessage.
    orphan_ai = [
        m
        for m in msgs
        if isinstance(m, AIMessage)
        and m.tool_calls
        and any(tc.get("id") not in answered for tc in m.tool_calls)
    ]
    # Drop the orphaned AIMessages AND every ToolMessage that answered ANY of
    # their tool_calls. tool_executor runs one call per invocation and commits
    # each ToolMessage as it goes, so a barge-in mid-loop on a PARALLEL-tool_call
    # AIMessage leaves committed ToolMessages for the calls that already ran —
    # removing only the AIMessage would orphan THOSE (a dangling ToolMessage 400s
    # the next LLM call just as badly). Remove the whole block, parentless-free.
    orphan_tc_ids = {tc.get("id") for m in orphan_ai for tc in m.tool_calls}
    to_remove = [m.id for m in orphan_ai]
    to_remove += [
        m.id
        for m in msgs
        if isinstance(m, ToolMessage) and m.tool_call_id in orphan_tc_ids
    ]
    try:
        # Empty RemoveMessage list is fine — as_node="persist" still advances the
        # dirty pending step to END, clearing a residue with no orphan too.
        await graph().aupdate_state(
            config,
            {"messages": [RemoveMessage(id=i) for i in to_remove]},
            as_node="persist",
        )
        # Verify state.next actually cleared — if the surgical fix half-failed,
        # escalate to the nuclear reset rather than start a fresh turn on a still-
        # dirty thread (better to lose recent context than to poison/double-run).
        after = await graph().aget_state(config)
        if after and getattr(after, "next", None):
            logger.warning(
                "cancellation_recovery_incomplete_escalating_reset",
                thread_id=thread_id,
                still_next=str(after.next),
            )
            await reset_thread(thread_id)
        else:
            logger.info(
                "recovered_cancellation_residue",
                thread_id=thread_id,
                dropped=len(to_remove),
                was_next=str(state.next),
            )
    except Exception as exc:  # noqa: BLE001 — recovery is best-effort, never fatal
        logger.warning("cancellation_recovery_failed", thread_id=thread_id, error=str(exc))


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

    Detects fresh interrupts by querying graph.aget_state — a real
    ``task.interrupts`` (not merely a non-empty state.next) means the graph
    paused on an approval and we surface the interrupt payload. Otherwise the
    turn is complete (or last-resort error)."""
    state = await graph().aget_state(config)
    all_messages: list[BaseMessage] = result.get("messages") or []
    new_messages = all_messages[msgs_before:]
    serialized = [_serialize_message(m) for m in new_messages]
    usage = _aggregate_usage(new_messages, duration_ms)
    trace_id = _safe_trace_id(handler)

    interrupts = _collect_interrupts(state)
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
