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
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
    ToolMessage,
)
from langgraph.types import Command

from app.agent.decision_resolver import resolve_decision
from app.agent.graph import build_graph
from app.agent.nodes import count_message_tokens
from app.config import settings
from app.llm.leak_sanitize import make_stream_leak_filter, strip_function_leak
from app.llm.observability import langfuse_callback_handler
from app.llm.stream_mode import stream_tokens, voice_mode
from app.utils import runtime_stats
from app.utils.exceptions import CostCapExceededError
from app.utils.logging import get_logger
from app.voice.chunker import SentenceChunker
from app.voice.markdown_strip import strip_markdown_for_speech
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


# The master is a single continuous web conversation, not multi-thread: the
# dashboard's thread is anchored SERVER-SIDE to the authenticated identity, NOT a
# client-minted uuid, so it's identical across reloads, browsers, devices, and a
# cleared cache. A future "start fresh" lever resets THIS thread's checkpoint
# (reset_thread) rather than minting a new id — so no persisted pointer is needed.
# The "web:" scope is explicit so a later cross-channel unification (one thread
# across web + Telegram) is a clean seam, not a rename.
def canonical_thread_id(channel_user_id: str) -> str:
    """The master's stable web thread id, derived from the authenticated identity
    (UserContext.user_id). Server-authoritative — replaces per-request uuid
    minting. Endpoints still ACCEPT an explicit thread_id (debugging); this is the
    default when the client sends none."""
    return f"web:{channel_user_id}"


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


def _context_from_state(state: dict[str, Any], *, live: bool) -> dict[str, Any]:
    """Context-meter snapshot from a graph state: verbatim-recent + rolling-summary
    token counts vs the compaction threshold (4.B.3). Tokens are tiktoken-approximate
    (see nodes._encoder). ``compacted`` is the live "just compacted" signal — only
    true in a turn's done event, never on a history reload (the divider is live)."""
    messages = state.get("messages") or []
    summary = (state.get("running_summary") or "").strip()
    recent = count_message_tokens(messages)
    summ = count_message_tokens([SystemMessage(content=summary)]) if summary else 0
    return {
        "used_tokens": recent + summ,
        "threshold_tokens": settings.COMPACT_THRESHOLD_TOKENS,
        "recent_tokens": recent,
        "summary_tokens": summ,
        "compacted": bool(live and state.get("compacted_last_turn")),
    }


async def thread_context(thread_id: str, *, live: bool = False) -> dict[str, Any]:
    """Context-meter snapshot loaded from a thread's checkpoint (used by /history)."""
    snapshot = await graph().aget_state({"configurable": {"thread_id": thread_id}})
    values = getattr(snapshot, "values", None) or {}
    return _context_from_state(values, live=live)


async def note_document_upload(
    thread_id: str, filename: str, result: dict[str, Any]
) -> None:
    """Append a persistent '📎' marker to the thread so a reload shows an in-chat
    document upload in conversation position (frontier-consistency with the
    decision cards + message history).

    Skipped when the thread is paused at an approval interrupt — appending a
    message after a pending tool_call would disturb its resolution; there the
    dashboard's transient upload status is the record. Best-effort: a failure
    (including a rare race with a concurrently-streaming turn) is logged and never
    fails the upload itself."""
    try:
        if await _is_awaiting_approval(thread_id):
            return
        chunks = result.get("chunks_stored", 0)
        if result.get("deduplicated"):
            note = f"📎 {filename} is already indexed — nothing to re-ingest."
        elif result.get("replaced"):
            note = f"📎 Re-indexed {filename} — {chunks} chunks (updated to the latest pipeline)."
        else:
            note = f"📎 Indexed {filename} — {chunks} chunks. Ask me anything about it."
        config = {"configurable": {"thread_id": thread_id}}
        await graph().aupdate_state(config, {"messages": [AIMessage(content=note)]})
        logger.info("document_upload_noted", thread_id=thread_id, filename=filename)
    except Exception as exc:  # noqa: BLE001 — the marker is best-effort
        logger.warning("document_upload_note_failed", thread_id=thread_id, error=str(exc))


async def run_turn(
    user_message: str,
    thread_id: str,
    platform: str,
    channel_user_id: str,
) -> dict[str, Any]:
    """Execute one user turn through the agent graph."""
    runtime_stats.record_turn()
    config, handler = _config_with_handler(thread_id)

    # A pending approval interrupt: do NOT start a fresh turn (a free-text
    # HumanMessage appended after the pending AIMessage tool_call would orphan it
    # → the next LLM call 400s the thread — the Jun-11 terminal error). Instead,
    # A2 Piece 2 resolves the message AGAINST the pending decision (approve /
    # reject / edit / unrelated) via the resume path; the master's words persist
    # correctly (after the resolving ToolMessage). Only a genuinely unrelated /
    # ambiguous message falls back to the nudge.
    if await _is_awaiting_approval(thread_id):
        logger.info("run_turn_resolving_pending_interrupt", thread_id=thread_id)
        resolved = await _resolve_pending(thread_id, user_message)
        if resolved["outcome"] == "unrelated":
            return _pending_interrupt_envelope(thread_id)
        return resolved["envelope"]

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
        "turn_started_at": datetime.now(UTC).isoformat(),
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
    return envelope  # context already on the envelope (set in _build_envelope)


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
# Natural-language resolution of a pending decision (A2 Piece 2)              #
# --------------------------------------------------------------------------- #


async def _load_pending_decision(thread_id: str) -> dict[str, Any] | None:
    """The thread's current pending decision (tool + args + description), or None.
    One interrupt pauses at a time, so there's at most one pending row."""
    from app.api.approvals import get_thread_decisions  # lazy — avoid import cycle

    decisions = await get_thread_decisions(thread_id)
    pending = [d for d in decisions if d.get("status") == "pending"]
    return pending[-1] if pending else None


async def _resolve_approval_row(approval_id: str, action: str) -> None:
    from app.api.approvals import resolve_approval  # lazy — avoid import cycle

    await resolve_approval(approval_id, action, resolved_via="web")


async def _resolve_pending(thread_id: str, user_message: str) -> dict[str, Any]:
    """Resolve the thread's pending decision against a natural-language message.

    Returns ``{"outcome": "approved"|"rejected"|"discarded"|"unrelated",
    "approval_id": <id|None>, "envelope": <resumed turn envelope|None>}``.
    ``unrelated`` resumes nothing — the caller keeps the card pending and nudges.
    The master's message persists in the thread via the resume's ``user_msg``
    (added as a HumanMessage after the resolving ToolMessage — see
    tool_executor_node), so a reload shows the negotiation in order. Modality-
    agnostic: the voice path (Piece 3) calls this same function."""
    pending = await _load_pending_decision(thread_id)
    if not pending:
        return {"outcome": "unrelated", "approval_id": None, "envelope": None}

    approval_id = pending["approval_id"]
    res = await resolve_decision(
        pending.get("tool_name", "action"),
        pending.get("tool_args") or {},
        pending.get("description"),
        user_message,
    )
    logger.info("pending_decision_routed", thread_id=thread_id, intent=res.intent)

    if res.intent == "unrelated":
        return {"outcome": "unrelated", "approval_id": approval_id, "envelope": None}
    if res.intent == "approve":
        await _resolve_approval_row(approval_id, "approve")
        env = await resume_turn(thread_id, {"approved": True, "user_msg": user_message})
        return {"outcome": "approved", "approval_id": approval_id, "envelope": env}
    if res.intent == "reject":
        await _resolve_approval_row(approval_id, "reject")
        env = await resume_turn(thread_id, {"approved": False, "user_msg": user_message})
        return {"outcome": "rejected", "approval_id": approval_id, "envelope": env}
    # edit → discard this card + the agent re-drafts a new one (tool_executor_node)
    env = await resume_turn(
        thread_id,
        {"approved": False, "revise": True, "feedback": res.change, "user_msg": user_message},
    )
    return {
        "outcome": "discarded",
        "approval_id": approval_id,
        "envelope": env,
        "change": res.change,  # surfaced so the voice path can echo the edit
    }


async def _resolve_pending_stream(
    thread_id: str, user_message: str
) -> AsyncIterator[dict[str, Any]]:
    """SSE events for resolving a pending decision by natural language: a
    ``decision_resolved`` signal for the affected card, then the resumed turn's
    result (a new ``approval_required`` card for an edit, else ``done``). An
    ``unrelated`` message leaves the card pending and emits the gentle nudge."""
    result = await _resolve_pending(thread_id, user_message)
    if result["outcome"] == "unrelated":
        yield {"type": "done", "content": _terminal_payload(_pending_interrupt_envelope(thread_id))}
        return
    yield {
        "type": "decision_resolved",
        "thread_id": thread_id,
        "content": {"approval_id": result["approval_id"], "status": result["outcome"]},
    }
    env = result["envelope"] or {}
    if env.get("status") == "interrupted":
        yield {"type": "approval_required", "thread_id": thread_id, "content": env.get("interrupt")}
    else:
        yield {"type": "done", "content": _terminal_payload(env)}


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
    runtime_stats.record_turn()
    yield {"type": "thread_id", "content": thread_id}

    config, handler = _config_with_handler(thread_id)

    # A pending decision: resolve it by natural language (approve / reject / edit
    # / unrelated) instead of blanket-nudging — A2 Piece 2. Same prevent-at-source
    # discipline as run_turn (no raw HumanMessage at the pending tool_call).
    if await _is_awaiting_approval(thread_id):
        logger.info("stream_turn_resolving_pending_interrupt", thread_id=thread_id)
        async for ev in _resolve_pending_stream(thread_id, user_message):
            yield ev
        return

    await _recover_cancellation_residue(thread_id)  # clean barge-in residue first
    msgs_before = await _existing_message_count(thread_id)
    initial_state = {
        "messages": [HumanMessage(content=user_message)],
        "thread_id": thread_id,
        "platform": platform,
        "channel_user_id": channel_user_id,
        "user_message": user_message,
        "turn_started_at": datetime.now(UTC).isoformat(),
    }

    started_ms = time.monotonic()
    flag = stream_tokens.set(True)
    # Drop a <function…> leak from the LIVE token stream so it never flashes in the
    # transcript before the re-issued clean answer lands (secondary fix; the final
    # message is already clean via the ainvoke re-issue + sanitize).
    leak_filter = make_stream_leak_filter()
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
                    visible = leak_filter(text)
                    if visible:
                        yield {"type": "token", "content": visible}
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
        "context": envelope.get("context"),  # 4.B.3 meter (None on synthetic envelopes)
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


def _approval_speech(
    interrupt: dict[str, Any], revised: bool = False, change: str = ""
) -> str:
    """Concise spoken form of an approval request, NAMING the key fields so the
    master can confirm by ear (hands-free voice resolution, A2 Piece 3). When
    ``revised`` (a re-drafted card after an edit), lead with "Updated" so the
    master hears that their change landed — echoing ``change`` (their requested
    edit) when given; the card still carries the full detail."""
    h = settings.MASTER_HONORIFIC
    tool = (interrupt or {}).get("tool_name", "an action")
    args = (interrupt or {}).get("tool_args") or {}
    if tool == "gmail_send":
        to = args.get("to") or "someone"
        subj = args.get("subject")
        detail = f"an email to {to}" + (f", subject '{subj}'" if subj else "")
        verb = "send it"
    elif tool == "calendar_create":
        title = args.get("summary") or args.get("title") or "an event"
        detail = f"the event '{title}'"
        verb = "add it"
    else:
        keys = ", ".join(f"{k} {v}" for k, v in list(args.items())[:2])
        detail = tool + (f" — {keys}" if keys else "")
        verb = "go ahead"
    if revised:
        if change:
            return f"Updated — {change}. Shall I {verb}?"
        return f"Updated, {h} — {detail}. Shall I {verb}?"
    return f"{h}, I've prepared {detail}. Shall I {verb}?"


async def _speak_text(text: str) -> dict[str, Any] | None:
    """Synthesize one spoken line → an audio event (None if TTS yields nothing).
    Module-level twin of voice_turn's inner _speak, for the voice resolver path.
    Strips the <function…> leak + markdown so the audio + caption (same string)
    speak clean words — a leaked chunk → "" → nothing spoken or captioned."""
    text = strip_markdown_for_speech(strip_function_leak(text))
    if not text:
        return None
    audio = await synthesize(text)
    return _audio_event(text, audio) if audio else None


async def synth_line(text: str) -> dict[str, Any] | None:
    """Synthesize one line → the SSE-audio CONTENT dict ``{text, audio, mime,
    filler}`` (or None if TTS yields nothing). Public twin of ``_speak_text`` for
    non-stream callers — e.g. the announce-approval endpoint, which plays Jarvis
    reading a freshly-surfaced inbound card over the same audio path."""
    ev = await _speak_text(text)
    return ev["content"] if ev else None


async def _resolve_pending_voice(
    thread_id: str, transcript: str
) -> AsyncIterator[dict[str, Any]]:
    """Voice variant of _resolve_pending_stream: the SAME decision_resolved /
    approval_required / done events (so the card updates identically to text),
    PLUS a concise spoken response so the master resolves the card hands-free.
    Reuses _resolve_pending unchanged — no forked resolution logic."""
    result = await _resolve_pending(thread_id, transcript)
    outcome = result["outcome"]
    if outcome == "unrelated":
        env = _pending_interrupt_envelope(thread_id)
        ev = await _speak_text(env["response"])
        if ev:
            yield ev
        yield {"type": "done", "content": _terminal_payload(env)}
        return
    yield {
        "type": "decision_resolved",
        "thread_id": thread_id,
        "content": {"approval_id": result["approval_id"], "status": outcome},
    }
    env = result["envelope"] or {}
    if env.get("status") == "interrupted":
        interrupt = env.get("interrupt") or {}
        speech = _approval_speech(interrupt, revised=True, change=result.get("change", ""))
        ev = await _speak_text(speech)
        if ev:
            yield ev
        yield {"type": "approval_required", "thread_id": thread_id, "content": interrupt}
    else:
        h = settings.MASTER_HONORIFIC
        spoken = (env.get("response") or "").strip() or (
            f"Done, {h}." if outcome == "approved" else f"Cancelled, {h}."
        )
        ev = await _speak_text(spoken)
        if ev:
            yield ev
        yield {"type": "done", "content": _terminal_payload(env)}


# --------------------------------------------------------------------------- #
# Hands-free resolution of a CROSS-THREAD presented approval (inbound email)   #
# --------------------------------------------------------------------------- #


async def _load_approval_by_id(approval_id: str):
    """The PendingApproval row for `approval_id`, or None (bad id / gone)."""
    import uuid

    from sqlalchemy import select

    from app.db.engine import async_session
    from app.db.models import PendingApproval

    try:
        aid = uuid.UUID(approval_id)
    except ValueError:
        return None
    async with async_session() as session:
        result = await session.execute(
            select(PendingApproval).where(PendingApproval.id == aid)
        )
        return result.scalar_one_or_none()


def _gmail_outcome_speech(outcome: Any) -> str:
    """Spoken line for a gmail send outcome — voice presentation of the SAME
    `dispatch_gmail_approval` core the buttons use (not duplicated logic)."""
    h = settings.MASTER_HONORIFIC
    if outcome.status == "sent":
        return f"Sent to {outcome.recipient}, {h}."
    # Approved, but the send didn't go through (e.g. expired OAuth). Honest: the
    # card still shows approved (the master DID decide), the voice says it failed.
    return (
        f"I approved it, {h}, but the reply couldn't be sent — "
        f"you may need to handle that one in Gmail."
    )


async def _resolve_presented_approval_voice(
    approval_id: str, transcript: str
) -> AsyncIterator[dict[str, Any]]:
    """Resolve a CROSS-THREAD presented approval (an inbound auto-drafted email
    reply, surfaced in the HUD from its own `gmail:<msg_id>` thread) by voice.

    The conversation thread isn't paused at an interrupt — this card lives on a
    different thread — so the normal `_resolve_pending_voice` path can't see it.
    Mirrors that path's contract (decision_resolved → spoken reply → done) but
    judges intent against the PRESENTED card and dispatches via the shared gmail
    core. Same conservative `resolve_decision` (ambient / ambiguous → unrelated →
    nudge, NEVER approve) is the gate: room noise leaves the card pending."""
    from app.email.gmail_approval_handler import dispatch_gmail_approval, is_gmail_approval

    h = settings.MASTER_HONORIFIC
    row = await _load_approval_by_id(approval_id)

    # Stale / already-resolved / not a channel-origin card → don't act; the
    # frontend's next poll drops it. Speak a brief acknowledgement and end.
    if row is None or row.status != "pending" or not is_gmail_approval(row.thread_id):
        ev = await _speak_text(f"That one's already taken care of, {h}.")
        if ev:
            yield ev
        yield {"type": "done", "content": _terminal_payload(
            {"thread_id": (row.thread_id if row else ""), "status": "complete", "response": ""}
        )}
        return

    thread_id = row.thread_id
    payload = row.payload or {}
    tool_args = {
        "to": payload.get("sender", ""),
        "subject": payload.get("subject", ""),
        "body": payload.get("draft", ""),
    }
    res = await resolve_decision(row.action_type, tool_args, row.description, transcript)
    logger.info("presented_approval_routed", approval_id=approval_id, intent=res.intent)

    if res.intent == "approve":
        await _resolve_presented_row(approval_id, "approve")
        outcome = await dispatch_gmail_approval(thread_id, {"approved": True})
        yield _decision_resolved_event(thread_id, approval_id, "approved")
        ev = await _speak_text(_gmail_outcome_speech(outcome))
        if ev:
            yield ev
        yield {"type": "done", "content": _terminal_payload(
            {"thread_id": thread_id, "status": "complete", "response": _gmail_outcome_speech(outcome)}
        )}
        return

    if res.intent == "reject":
        await _resolve_presented_row(approval_id, "reject")
        spoken = f"Discarded, {h} — I'll leave it in your inbox."
        yield _decision_resolved_event(thread_id, approval_id, "rejected")
        ev = await _speak_text(spoken)
        if ev:
            yield ev
        yield {"type": "done", "content": _terminal_payload(
            {"thread_id": thread_id, "status": "complete", "response": spoken}
        )}
        return

    # edit (not supported for an inbound reply this slice) or unrelated / ambient
    # → leave the card PENDING (no decision_resolved) and nudge.
    if res.intent == "edit":
        spoken = f"I can only send or discard this reply for now, {h}. Shall I send it?"
    else:
        spoken = f"I still have that reply drafted, {h}. Shall I send it, or discard it?"
    ev = await _speak_text(spoken)
    if ev:
        yield ev
    yield {"type": "done", "content": _terminal_payload(
        {"thread_id": thread_id, "status": "complete", "response": spoken}
    )}


def _decision_resolved_event(thread_id: str, approval_id: str, status: str) -> dict[str, Any]:
    """The card-flip signal the frontend matches by approval_id (thread_id is
    informational — the inbound card lives on a different thread than the turn)."""
    return {
        "type": "decision_resolved",
        "thread_id": thread_id,
        "content": {"approval_id": approval_id, "status": status},
    }


async def _resolve_presented_row(approval_id: str, action: str) -> None:
    from app.api.approvals import resolve_approval  # lazy — avoid import cycle

    await resolve_approval(approval_id, action, resolved_via="voice")


async def voice_turn(
    user_message: str,
    thread_id: str,
    platform: str,
    channel_user_id: str,
    presented_approval_id: str | None = None,
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
    runtime_stats.record_turn()
    yield {"type": "thread_id", "content": thread_id}

    config, handler = _config_with_handler(thread_id)

    if await _is_awaiting_approval(thread_id):
        # A live decision card + a spoken reply → resolve it by voice through the
        # SAME resolver as text (approve / reject / edit / unrelated), with a
        # concise spoken response. The conservative resolver (ambient/ambiguous →
        # unrelated, never approve) is the safety; capture only fires on real
        # speech. A2 Piece 3. (The wake transport / barge-in is untouched.)
        logger.info("voice_turn_resolving_pending_interrupt", thread_id=thread_id)
        async for ev in _resolve_pending_voice(thread_id, user_message):
            yield ev
        return

    if presented_approval_id:
        # A CROSS-THREAD inbound card (an auto-drafted email reply) is presented in
        # the HUD and the master spoke. It lives on its OWN gmail:<msg_id> thread,
        # so the conversation thread isn't "awaiting" (the check above is False) —
        # resolve it against the presented card, gated by the same conservative
        # resolver. Checked AFTER the conversation interrupt so a live in-thread
        # approval always wins (and one-at-a-time means only one is ever active).
        logger.info(
            "voice_turn_resolving_presented_approval",
            thread_id=thread_id,
            approval_id=presented_approval_id,
        )
        async for ev in _resolve_presented_approval_voice(presented_approval_id, user_message):
            yield ev
        return

    await _recover_cancellation_residue(thread_id)  # clean barge-in residue first
    msgs_before = await _existing_message_count(thread_id)
    initial_state = {
        "messages": [HumanMessage(content=user_message)],
        "thread_id": thread_id,
        "platform": platform,
        "channel_user_id": channel_user_id,
        "user_message": user_message,
        "turn_started_at": datetime.now(UTC).isoformat(),
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
        # Strip the <function…> tool-call leak (open-weights), THEN markdown, on the
        # SAME string that feeds both TTS + the caption. A leaked chunk → "" → not
        # synthesized, no caption — so Jarvis never SPEAKS the function syntax that
        # streamed before the ainvoke-level re-issue; only the clean answer is
        # voiced. Audio + caption stay clean AND in lockstep.
        sentence = strip_markdown_for_speech(strip_function_leak(sentence))
        if not sentence:
            return None
        audio = await synthesize(sentence)
        if audio:
            return _audio_event(sentence, audio, filler=filler)
        return None

    # Drop a <function…> leak from the live token stream (the visual transcript) —
    # the spoken path is handled by _speak above; this is the secondary visual fix.
    leak_filter = make_stream_leak_filter()

    try:
        while True:
            try:
                timeout = filler_budget if (not first_token and not filler_sent) else None
                kind, payload = await asyncio.wait_for(queue.get(), timeout=timeout)
            except TimeoutError:
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
                    visible = leak_filter(text)
                    if visible:
                        yield {"type": "token", "content": visible}
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
        # Verify state.next cleared. If the surgical advance half-failed and next
        # is STILL dirty, DO NOT wipe the thread — that would now delete the
        # master's entire canonical conversation (web:master). The old throwaway
        # web:<uuid> threads made a reset look harmless; the server-anchor funnels
        # everything into one permanent thread, so the nuclear reset is now
        # catastrophic AND unnecessary: the orphaned AIMessages + their committed
        # ToolMessages are already removed, so a resumed tool_executor walks back
        # to the most-recent AIMessage WITH tool_calls and runs only an UNanswered
        # call — there are none left → it no-ops and routes to agent (verified:
        # tool_executor_node / should_continue_tools in nodes.py). agent_node's
        # repair_orphaned_tool_calls then neutralizes any residual orphan before
        # the LLM call. So a still-dirty next with the orphans gone is safe to
        # proceed on. (Durable-context bounding is B's rolling compaction.)
        after = await graph().aget_state(config)
        if after and getattr(after, "next", None):
            logger.warning(
                "cancellation_recovery_incomplete_proceeding_no_reset",
                thread_id=thread_id,
                still_next=str(after.next),
                dropped=len(to_remove),
            )
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
    """Envelope for a message that arrived while a decision is pending AND the
    resolver judged it unrelated/ambiguous (A2 Piece 2). status='complete' with a
    gentle nudge; the pending card stays live and still resolves by button or by a
    clearer natural-language reply. No interrupt payload (the card already carries
    the buttons; re-sending would mint a duplicate row)."""
    return {
        "thread_id": thread_id,
        "status": "complete",
        "stop_reason": "pending_approval",
        "response": (
            "You've a decision waiting, Sir — approve it, reject it, or tell me "
            "what to change."
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

    # Context meter (4.B.3) — computed ONCE here at envelope finalization so it
    # rides EVERY terminal path (run_turn, stream_turn, voice_turn, resume) via
    # _terminal_payload, not just the text done-sites. `live=True` surfaces the
    # "just compacted" signal that drives the in-chat divider.
    context = _context_from_state(result, live=True)

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
            "context": context,
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
        "context": context,
    }


def _extract_last_assistant_text(state_dict: dict) -> str:
    """Walk the message history backwards to find the most recent non-empty
    assistant message. Used as a fallback when final_response wasn't set
    (e.g. the graph's last step was a tool call rather than a text reply)."""
    msgs = state_dict.get("messages") or []
    for m in reversed(msgs):
        if isinstance(m, AIMessage) and isinstance(m.content, str):
            # Strip any <function…> leak so an already-poisoned message never
            # surfaces as the answer; skip if nothing real is left.
            clean = strip_function_leak(m.content)
            if clean.strip():
                return clean
    return ""


# --------------------------------------------------------------------------- #
# Serialization helpers                                                       #
# --------------------------------------------------------------------------- #


def _serialize_message(m: BaseMessage) -> dict[str, Any]:
    """LangChain BaseMessage → compact dict for HTTP. Keeps tool_calls and
    tool_call_id for transparency; drops bulky internals (response_metadata,
    usage_metadata — usage is aggregated separately)."""
    if isinstance(m, AIMessage):
        # Strip any <function…> leak on the way to the screen — covers OLD poison
        # already stored in a thread (reload) as well as anything live.
        out: dict[str, Any] = {
            "role": "ai",
            "content": strip_function_leak(m.content) if isinstance(m.content, str) else str(m.content),
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
                # Pricing not in litellm's table for this model — skip; the /costs
                # endpoint reconciles from LLMUsageLog rows once the persistence
                # callback has flushed.
                with contextlib.suppress(Exception):
                    cost_usd += float(completion_cost(
                        model=model_name,
                        prompt_tokens=in_t,
                        completion_tokens=out_t,
                    ) or 0.0)

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
