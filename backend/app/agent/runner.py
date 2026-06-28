"""
Public agent entry point.

The messaging layer (Telegram channel, web chat API, future iMessage / Discord
adapters) calls into this module ONLY. Everything below — graph wiring,
checkpointer state — stays internal.

Primary surface:

  run_turn(user_message, thread_id, platform, channel_user_id)
      Start a fresh turn. Returns a TurnEnvelope dict. An APPROVE-tier tool no
      longer pauses the turn (Phase 3 retired interrupt()/resume): it QUEUES a
      PendingApproval and the turn completes; the action executes out-of-band on
      approve via the claim-gated dispatcher (app/agent/approval_dispatch.py).

It compiles the graph lazily (build_graph() reads the checkpointer singleton).

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
from dataclasses import dataclass
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


async def note_approval_outcome(thread_id: str, marker: str) -> None:
    """Ground a resolved-action OUTCOME into the conversation thread so the agent knows
    next turn what happened (the email sent/failed, the event created). Restores what the
    non-blocking cutover dropped.

    A plain AIMessage note — NOT a tool response, so it never re-answers the original
    [QUEUED] tool_call (no double-answer). Best-effort: a write failure (incl. a rare race
    with a concurrently-streaming turn) is logged and never breaks the dispatch result."""
    try:
        config = {"configurable": {"thread_id": thread_id}}
        await graph().aupdate_state(config, {"messages": [AIMessage(content=marker)]})
        logger.info("approval_outcome_noted", thread_id=thread_id)
    except Exception as exc:  # noqa: BLE001 — the marker is best-effort
        logger.warning("approval_outcome_note_failed", thread_id=thread_id, error=str(exc))


async def run_turn(
    user_message: str,
    thread_id: str,
    platform: str,
    channel_user_id: str,
) -> dict[str, Any]:
    """Execute one user turn through the agent graph."""
    runtime_stats.record_turn()
    config, handler = _config_with_handler(thread_id)

    # Legacy paused-at-interrupt checkpoint (pre-Phase-3). APPROVE-tier tools no
    # longer interrupt, so NOTHING new pauses here; the deploy-time drain clears
    # any pre-cutover paused checkpoint. This guard is the belt-and-braces backstop
    # for the deploy window: NUDGE to the buttons (which resolve through the claim-
    # gated dispatcher), and NEVER resume the graph. The old Command(resume) path is
    # retired — resuming a legacy checkpoint would flip the row to approved WITHOUT
    # dispatching the tool (a silent action-drop), so the only safe response is the
    # nudge. The orphan-repair (message_repair) still protects the Jun-11 shape.
    if await _is_awaiting_approval(thread_id):
        logger.info("run_turn_legacy_pending_checkpoint_nudge", thread_id=thread_id)
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
        "turn_started_at": datetime.now(UTC).isoformat(),
        "tool_calls_this_turn": 0,  # reset per turn → the hourly rate check runs once (first agent pass)
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
    if envelope.get("status") != "interrupted":
        attach = await _briefing_attach(result)  # 5.4 — code-guaranteed brief/offer
        if attach:
            envelope["response"] = _append_block(envelope.get("response", ""), attach)
    return envelope  # context already on the envelope (set in _build_envelope)


# --------------------------------------------------------------------------- #
# Streaming surface (Phase 4 — true token streaming through the same graph)   #
# --------------------------------------------------------------------------- #


async def stream_turn(
    user_message: str,
    thread_id: str,
    platform: str,
    channel_user_id: str,
    presented_approval_id: str | None = None,
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

    # Legacy paused-at-interrupt checkpoint backstop (see run_turn) — nudge to the
    # buttons, never resume. Nothing new pauses post-cutover; the drain clears any
    # pre-deploy paused checkpoint.
    if await _is_awaiting_approval(thread_id):
        logger.info("stream_turn_legacy_pending_checkpoint_nudge", thread_id=thread_id)
        yield {"type": "done",
               "content": _terminal_payload(_pending_interrupt_envelope(thread_id))}
        return

    card_reminder = ""   # set when an off-topic message is answered with a card pending
    if presented_approval_id:
        # A card is presented and the master TYPED something. Judge it against the card
        # (context-aware), then take the UNIFIED disposition (same for voice + text):
        # resolve an actionable intent; re-ask an ambiguous one; ACK a stale/gone card;
        # otherwise (off-topic) FALL THROUGH to a normal turn + a once-per-card reminder.
        recent_context = await _recent_context(thread_id)
        disp, judged = await _presented_disposition(presented_approval_id, user_message, recent_context)
        logger.info(
            "stream_turn_presented", thread_id=thread_id, approval_id=presented_approval_id,
            disp=disp, intent=(judged.intent if judged else "stale"),
        )
        if disp == "resolve":
            async for ev in _resolve_presented_decision(
                judged, speak=False, message=user_message, conversation_thread_id=thread_id
            ):
                yield ev
            return
        if disp == "reask":
            async for ev in _reask_presented(judged, speak=False):
                yield ev
            return
        if disp == "plain":  # stale/gone card → brief ack, never answer it as a turn
            async for ev in _stale_ack(speak=False):
                yield ev
            return
        if disp == "remind":  # off-topic → answer below + remind ONCE per card
            card_reminder = await _reminder_for(judged)
        # only 'remind' reaches here now → answer the message in the normal turn below.

    await _recover_cancellation_residue(thread_id)  # clean barge-in residue first
    msgs_before = await _existing_message_count(thread_id)
    initial_state = {
        "messages": [HumanMessage(content=user_message)],
        "thread_id": thread_id,
        "platform": platform,
        "channel_user_id": channel_user_id,
        "user_message": user_message,
        "turn_started_at": datetime.now(UTC).isoformat(),
        "tool_calls_this_turn": 0,  # reset per turn → the hourly rate check runs once (first agent pass)
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
                for node, upd in (data or {}).items():
                    for m in (upd or {}).get("messages", []) or []:
                        if node == "agent":
                            # Surface tool calls as the agent decides them (THINKING state).
                            for tc in getattr(m, "tool_calls", None) or []:
                                yield {"type": "tool", "content": tc.get("name", "")}
                        elif node == "tool_executor":
                            # Present-in-moment (3B): an APPROVE-tier tool just QUEUED →
                            # surface its card in-stream now (same event + approval_id the
                            # /approvals/queue poll would, so 3C dedups them to one).
                            ev = await _queued_approval_event(thread_id, m)
                            if ev:
                                yield ev
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
        # 5.4 — code-guaranteed brief/offer in the DONE payload ONLY (like the card reminder),
        # NOT also as a live token: the client's done does patch(response), so a token + done
        # would render it twice. The done's response is canonical → it shows exactly once.
        attach = await _briefing_attach(result)
        payload = _with_reminder(_terminal_payload(envelope), card_reminder)
        if attach:
            payload["response"] = _append_block(payload.get("response", ""), attach)
        yield {"type": "done", "content": payload}


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


def _with_reminder(payload: dict[str, Any], reminder: str) -> dict[str, Any]:
    """Append a brief card-pending reminder to a terminal payload's response — the
    off-topic-while-pending case answers the master, then reminds (never blocks). No-op
    when there's no reminder."""
    if not reminder:
        return payload
    base = (payload.get("response") or "").rstrip()
    payload["response"] = f"{base} {reminder}".strip() if base else reminder
    return payload


def _append_block(base: str, block: str) -> str:
    """Append a code-attached block (briefing / offer) as its own paragraph — the model's
    wrapper, then the system-guaranteed content."""
    base = (base or "").rstrip()
    return f"{base}\n\n{block}".strip() if base else block


async def _briefing_attach(result: dict[str, Any]) -> str:
    """Phase 5.4 — CODE-render the proactive briefing into the reply (the model wrote only
    the wrapper + the deliver_briefing() signal). Reads the turn-START mode + offer (stored
    in state by memory_load_node) and the model's signal (a tool call in the final messages);
    returns the brief (deliver) or the offer line (floor), or "" for suppress/already-done.
    Fail-soft — a hiccup here must never break the reply."""
    try:
        from app.agent.briefing_state import mark_offered, render_attach
        text, delivered = await render_attach(
            result.get("briefing_proactive") or "suppress",
            result.get("briefing_offer") or "",
            result.get("messages") or [],
        )
        # An OFFER is a throttled proactive surface too — stamp the cooldown so a string of
        # ordinary messages with items pending gets AT MOST ONE offer, not one per message.
        # (A delivery already stamped it via mark_briefed inside briefing('latest').)
        if text and not delivered:
            await mark_offered(datetime.now(UTC))
        return text
    except Exception as exc:  # noqa: BLE001 — never break the reply on the briefing attach
        logger.warning("briefing_attach_failed", error=str(exc))
        return ""


async def _queued_approval_event(thread_id: str, message: Any) -> dict[str, Any] | None:
    """Present-in-moment (3B). If ``message`` is the ``[QUEUED]`` ToolMessage an
    APPROVE-tier tool emits when it queues, look up the synthetic PendingApproval row
    it just created (by interrupt_id == the tool_call_id) and shape it as the SAME
    ``approval_required`` event the chat path already renders — so the present master
    sees the card the instant it's queued, without waiting for the /approvals/queue poll.

    The content carries the CANONICAL approval_id (= ``str(row.id)``, exactly what
    /approvals/queue returns) so the in-stream card and the poll dedup to one, plus a
    tool-kind payload (tool_name / tool_args / description) so the frontend renders it
    through the identical path as a polled card. SURFACING ONLY — it reads the row,
    never claims or dispatches. Best-effort: None on a non-queued message or a missing
    row (the poll is the durable fallback; this never breaks the turn)."""
    from app.agent.nodes import QUEUED_MARKER_TAG

    content = getattr(message, "content", "")
    tool_call_id = getattr(message, "tool_call_id", None)
    if not (isinstance(message, ToolMessage) and tool_call_id
            and isinstance(content, str) and content.startswith(QUEUED_MARKER_TAG)):
        return None

    from sqlalchemy import select

    from app.db.engine import async_session
    from app.db.models import PendingApproval
    try:
        async with async_session() as session:
            row = (await session.execute(
                select(PendingApproval)
                .where(PendingApproval.thread_id == thread_id)
                .where(PendingApproval.interrupt_id == tool_call_id)
                .where(PendingApproval.status == "pending")
                .order_by(PendingApproval.created_at.desc())
                .limit(1)
            )).scalar_one_or_none()
    except Exception as exc:  # noqa: BLE001 — present-in-moment is best-effort
        logger.warning("queued_approval_event_lookup_failed", thread_id=thread_id, error=str(exc))
        return None
    if row is None:
        return None

    # Shape the in-stream card through the SHARED mapping (app.approvals_service) so it's
    # byte-identical to the /approvals/queue card — same kind / tool_args / fields. The two
    # surfaces literally can't drift because they're built by the one function.
    from app.approvals_service import to_unified_card

    return {
        "type": "approval_required",
        "thread_id": thread_id,
        "content": to_unified_card(row).model_dump(),
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
    if tool == "email_send":
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


def _is_email_row(row: Any) -> bool:
    """True for an inbound-email reply approval row (vs a chat-queued tool card). The
    ONE predicate — used by the judgment, the card framing, and the context line."""
    from app.email.approval_handler import is_email_approval

    return bool(row) and (
        is_email_approval(row.thread_id) or row.action_type in ("email_reply", "gmail_reply")
    )


@dataclass
class _PresentedJudgment:
    """The classification of a typed/spoken message against a PRESENTED card.
    ``actionable`` (anything but ``unrelated``) means the message is ABOUT this card
    or the queue → resolve / navigate / nudge. ``unrelated`` means it is NOT → the
    caller decides (text falls through to a normal turn; voice nudges)."""

    approval_id: str
    row: Any  # the PendingApproval row, or None when the judge failed (fail-open)
    intent: str  # approve | reject | edit | skip | show_others | unrelated
    change: str

    @property
    def actionable(self) -> bool:
        # approve/reject/edit resolve; skip/show_others navigate — these are intercepted
        # + handled by _resolve_presented_decision. "unclear" → re-ask, "unrelated" →
        # answer + remind (both handled by the caller's disposition, NOT here).
        return self.intent in ("approve", "reject", "edit", "skip", "show_others")

    @property
    def is_email_card(self) -> bool:
        """True for an inbound-email reply card (re-draftable) vs a chat-queued tool
        card. Edit (re-draft) is email-only; approve/reject/skip/show_others are
        kind-agnostic."""
        return _is_email_row(self.row)

    @property
    def needs_drafting(self) -> bool:
        """True for a COMPLEX-email heads-up card (no draft yet) — "go"/approve DRAFTS
        it (handled by the dispatcher), and there's no draft to edit (edit → nudge)."""
        return bool(self.row and (self.row.payload or {}).get("needs_drafting"))


async def _judge_presented(
    approval_id: str, message: str, recent_context: str = ""
) -> _PresentedJudgment | None:
    """Load the presented card + classify the message against it via the SAME
    context-aware ``resolve_decision`` (ambiguous → unclear/unrelated, NEVER approve).
    Works for BOTH card kinds — an inbound-email reply (tool_args = the draft) and a
    chat-queued tool call (tool_args = the real args) — so every action has voice/text
    parity regardless of origin. ``recent_context`` is the conversation's recent turns;
    we ALSO append the card's own framing (``_card_context_line``) so the judge sees "I
    just raised this with you" UNIFORMLY — including for an inbound card, which is
    surfaced via the poll/announce and never lands in the conversation thread. Returns
    None if the card is stale / gone — the caller acks ("already taken care of").

    FAILS OPEN: the load is a DB call and resolve_decision is an LLM call, either of
    which can raise. The guard lives HERE (not at each caller) because this is the ONE
    place the judgment happens — guarding once means neither the text nor the voice
    caller can forget, and the load-bearing invariant ("an errored or ambiguous judge
    is NEVER a decision that sends") is enforced in a single auditable spot. A failure
    returns ``unrelated`` with ``row=None``: the caller answers the message normally and
    (row=None) adds no card reminder — never errors, never sends."""
    try:
        row = await _load_approval_by_id(approval_id)
        if row is None or row.status != "pending":
            return None
        payload = row.payload or {}
        if _is_email_row(row):
            tool_name = row.action_type
            if payload.get("needs_drafting"):
                # Heads-up card: the pending action is "draft a reply" (no draft yet) —
                # present the ORIGINAL email so "go"/"draft it"/"yes" reads as approve.
                tool_name = "draft_email_reply"
                tool_args = {
                    "to": payload.get("sender", ""),
                    "subject": payload.get("subject", ""),
                    "original_email": (payload.get("body", "") or "")[:600],
                }
            else:
                tool_args = {
                    "to": payload.get("sender", ""),
                    "subject": payload.get("subject", ""),
                    "body": payload.get("draft", ""),
                }
        else:  # chat-queued tool card — judge against the REAL tool + args
            tool_name = payload.get("tool_name") or row.action_type
            tool_args = payload.get("tool_args") or {}
        # The judge's context = the recent conversation + the card's OWN surfacing line
        # (last = most recent). This makes the context-awareness fire for inbound cards.
        context = "\n".join(c for c in (recent_context.strip(), _card_context_line(row)) if c)
        res = await resolve_decision(tool_name, tool_args, row.description, message, context)
        return _PresentedJudgment(
            approval_id=approval_id, row=row, intent=res.intent, change=res.change
        )
    except Exception as exc:  # noqa: BLE001 — fail OPEN, never error the turn / approve
        logger.warning("judge_presented_failed_open", approval_id=approval_id, error=str(exc))
        return _PresentedJudgment(approval_id=approval_id, row=None, intent="unrelated", change="")


def _email_outcome_speech(outcome: Any) -> str:
    """Spoken line for an inbound-email send outcome — voice (and typed) presentation
    of the SAME `dispatch_email_approval` core the buttons use (not duplicated
    logic). Distinguishes a DEFINITE fail from a MAYBE-delivered send."""
    h = settings.MASTER_HONORIFIC
    if outcome.status == "sent":
        return f"Sent to {outcome.recipient}, {h}."
    if outcome.status == "send_uncertain":
        # Maybe-delivered — don't claim it failed; tell the master to verify.
        return (
            f"I couldn't confirm that send, {h} — it may have gone out. "
            f"Worth checking your Sent folder."
        )
    # Approved, but the send DEFINITELY didn't go through. Honest: the card still
    # shows approved (the master DID decide), the voice says it failed.
    return (
        f"I approved it, {h}, but the reply couldn't be sent — "
        f"you may need to handle that one in your inbox."
    )


def _summarize_pending(rows: list, exclude_approval_id: str, h: str) -> str:
    """Pure: the spoken/typed summary of the OTHER pending approvals (rows minus the
    presented card), via the SHARED renderer (app.approvals_service.summarize_others) so
    it agrees with the approvals_pending tool + the HUD and never prints a bare tool name
    (the "email send; email send" garble). Rows in / string out — testable without the DB."""
    from app.approvals_service import summarize_others, to_unified_card

    cards = [to_unified_card(r) for r in rows]
    return summarize_others(cards, exclude_approval_id, h)


async def _pending_queue_summary(exclude_approval_id: str = "") -> str:
    """The voice/text answer to "what else is pending?" — reads the SHARED
    ``list_pending_cards()`` (the same source the tool + HUD read) and formats via the
    pure ``summarize_others``. A read failure → a graceful vague line (never errors)."""
    from app.approvals_service import list_pending_cards, summarize_others

    h = settings.MASTER_HONORIFIC
    try:
        cards = await list_pending_cards()
    except Exception as exc:  # noqa: BLE001 — a read failure → a graceful, vague line
        logger.warning("pending_queue_summary_failed", error=str(exc))
        return f"I couldn't check the rest of the queue just now, {h}."
    return summarize_others(cards, exclude_approval_id, h)


async def _recent_context(thread_id: str, k: int = 6) -> str:
    """The last ~k conversation messages, formatted "User: …/Assistant: …", for the
    decision judge — so it can tell a reply RESPONDING to the pending card from one
    starting a NEW topic. Best-effort: "" on any read failure (the judge stays
    conservative without it)."""
    try:
        snapshot = await graph().aget_state({"configurable": {"thread_id": thread_id}})
        messages = (getattr(snapshot, "values", None) or {}).get("messages") or []
    except Exception:  # noqa: BLE001 — context is best-effort
        return ""
    lines: list[str] = []
    for m in messages[-k:]:
        if isinstance(m, HumanMessage):
            role = "User"
        elif isinstance(m, AIMessage):
            role = "Assistant"
        else:
            continue
        content = m.content if isinstance(m.content, str) else str(m.content)
        content = strip_function_leak(content).strip()
        if content:
            lines.append(f"{role}: {content}")
    return "\n".join(lines)


def _card_phrase(judged: "_PresentedJudgment | None") -> str:
    """A short human reference to the pending card — "the reply to Priya" for an email,
    "that pending action" for a tool — for the re-ask + reminder lines."""
    if judged is None or judged.row is None:
        return "that pending action"
    if judged.is_email_card:
        from email.utils import parseaddr

        sender = (judged.row.payload or {}).get("sender") or ""
        name, addr = parseaddr(sender)
        who = name.strip() or (addr.split("@")[0] if addr else "")
        return f"the reply to {who}" if who else "that email reply"
    return "that pending action"


def _card_context_line(row: Any) -> str:
    """Synthesize the assistant's OWN framing of a just-surfaced card, as a context line
    for the judge — "Assistant: I've drafted a reply to Priya about 'Q3' — shall I send
    it?". An inbound card is surfaced via the poll/announce and never written to the
    conversation thread, so without this the judge would have no "I just raised this"
    signal for inbound mail; adding it uniformly (inbound + chat) makes context-awareness
    fire everywhere. Mirrors the announce/lead-in copy."""
    payload = row.payload or {}
    if _is_email_row(row):
        from email.utils import parseaddr

        name, addr = parseaddr(payload.get("sender", ""))
        who = name.strip() or (addr.split("@")[0] if addr else "someone")
        subject = payload.get("subject") or "your message"
        if payload.get("needs_drafting"):
            return f"Assistant: You've got a more involved email from {who} about '{subject}' — shall I draft a reply?"
        return f"Assistant: I've drafted a reply to {who} about '{subject}' — shall I send it?"
    action = (row.description or "an action").rstrip(".")
    return f"Assistant: I've queued this for your approval — {action}. Shall I go ahead?"


def _card_reminder(judged: "_PresentedJudgment | None") -> str:
    """A brief "still pending" tail appended when an OFF-TOPIC message is answered
    while a card is pending — answer the master, then a one-line reminder (never block).
    "" when there's no live card to reference (a failed-open judge / no row)."""
    if judged is None or judged.row is None:
        return ""
    return f"By the way, {_card_phrase(judged)} is still pending your approval, {settings.MASTER_HONORIFIC}."


async def _mark_reminded(approval_id: str) -> bool:
    """Atomically claim the FIRST off-topic reminder for a card. Returns True only to the
    call that flips the durable per-card ``reminded`` flag from unset → set (the same
    conditional-UPDATE claim idiom as approvals), so a reload / a later off-topic turn /
    a concurrent turn never re-nags. False if already reminded, already acted on
    (status flipped out of 'pending' — "silent until acted on"), gone, or a bad id."""
    import uuid

    from sqlalchemy import text

    from app.db.engine import async_session

    try:
        aid = uuid.UUID(approval_id)
    except ValueError:
        return False
    try:
        async with async_session() as session:
            res = await session.execute(
                text(
                    "UPDATE pending_approvals "
                    "SET payload = payload || '{\"reminded\": true}'::jsonb "
                    "WHERE id = :id AND status = 'pending' "
                    "AND COALESCE((payload->>'reminded')::boolean, false) = false "
                    "RETURNING id"
                ),
                {"id": aid},
            )
            claimed = res.first() is not None
            await session.commit()
        return claimed
    except Exception as exc:  # noqa: BLE001 — reminder is a nicety; never break the turn
        logger.warning("mark_reminded_failed", approval_id=approval_id, error=str(exc))
        return False


async def _reminder_for(judged: "_PresentedJudgment | None") -> str:
    """The once-then-quiet reminder: the line on the FIRST off-topic turn after a card
    appears (claiming the durable flag), then "" forever for that card. "" when there's
    no live card to reference (failed-open judge / no row)."""
    if judged is None or judged.row is None:
        return ""
    if not await _mark_reminded(judged.approval_id):
        return ""  # already reminded once for this card → stay quiet
    return _card_reminder(judged)


async def _reask_presented(
    judged: "_PresentedJudgment", *, speak: bool
) -> AsyncIterator[dict[str, Any]]:
    """Shared RE-ASK for an AMBIGUOUS reply about the card (voice == text): name the
    pending action and ask for a clear decision rather than guessing. NEVER sends."""
    h = settings.MASTER_HONORIFIC
    reask = (
        f"Sorry, {h} — I wasn't sure what you meant. Shall I go ahead with "
        f"{_card_phrase(judged)}, or would you like to change it or skip it?"
    )
    thread_id = judged.row.thread_id if judged.row else ""
    if speak:
        ev = await _speak_text(reask)
        if ev:
            yield ev
    yield {"type": "done", "content": _terminal_payload(
        {"thread_id": thread_id, "status": "complete", "response": reask}
    )}


async def _stale_ack(*, speak: bool) -> AsyncIterator[dict[str, Any]]:
    """A card the master speaks/types to was already resolved elsewhere (stale/gone):
    a brief ack, IDENTICAL voice + text, then stop — never answer it as a normal turn
    ('send what?'). The plain disposition."""
    ack = f"That one's already taken care of, {settings.MASTER_HONORIFIC}."
    if speak:
        ev = await _speak_text(ack)
        if ev:
            yield ev
    yield {"type": "done", "content": _terminal_payload(
        {"thread_id": "", "status": "complete", "response": ack}
    )}


async def _presented_disposition(
    approval_id: str, message: str, recent_context: str
) -> tuple[str, "_PresentedJudgment | None"]:
    """Classify a typed/spoken message against the presented card (context-aware) and
    decide the UNIFIED disposition — IDENTICAL for voice and text:
      'resolve' → an actionable intent (approve/reject/edit/skip/show_others).
      'reask'   → the reply engages the card but is ambiguous → re-ask to clarify.
      'remind'  → off-topic → answer it normally + remind the card is still pending (once).
      'plain'   → stale/gone card → a brief ack ("already taken care of"), then stop.
    The caller dispatches resolve / reask / plain-ack itself, or (only 'remind') falls
    through to a normal turn, appending the once-per-card reminder."""
    judged = await _judge_presented(approval_id, message, recent_context)
    if judged is None:
        return "plain", None
    if judged.actionable:
        return "resolve", judged
    if judged.intent == "unclear":
        return "reask", judged
    return "remind", judged  # unrelated (off-topic); row may be None (failed-open) → no reminder


async def _resolve_presented_decision(
    judged: _PresentedJudgment, *, speak: bool,
    message: str = "", conversation_thread_id: str = "",
) -> AsyncIterator[dict[str, Any]]:
    """Resolve an ACTIONABLE judgment for ANY presented card — inbound email OR
    chat-queued tool call (Phase 3) — with full voice/text parity:

      approve / reject → the ONE claim-then-dispatch gate (``resolve_and_dispatch``);
                         a lost claim → acknowledge, never double-execute.
      skip             → a ``presented_nav`` signal the client turns into the SAME
                         client-side skip the button does (grey + surface next). No
                         DB change — skip is deliberately session-local + DB-inert.
      show_others      → speak/type a summary of the OTHER pending approvals (the
                         current card stays pending).
      edit             → email cards re-draft (TEXT *and* VOICE now — the re-queued
                         card is the safety net, so a mis-heard edit is caught at
                         re-approval before anything sends); non-email / no-context
                         → a nudge. NEVER errors or sends.

    Shared by text and voice (``speak`` adds the audio). ``message`` /
    ``conversation_thread_id`` are the edit re-draft inputs (the master's actual
    words + their thread) and the ``presented_nav`` thread."""
    from app.agent.approval_dispatch import resolve_and_dispatch

    h = settings.MASTER_HONORIFIC
    thread_id = judged.row.thread_id
    approval_id = judged.approval_id
    resolved_via = "voice" if speak else "web"

    async def _emit(response: str):
        if speak:
            ev = await _speak_text(response)
            if ev:
                yield ev
        yield {"type": "done", "content": _terminal_payload(
            {"thread_id": thread_id, "status": "complete", "response": response}
        )}

    if judged.intent in ("approve", "reject"):
        action = "approve" if judged.intent == "approve" else "reject"
        outcome = await resolve_and_dispatch(
            approval_id, action, resolved_via, {"approved": judged.intent == "approve"}
        )
        if outcome.status == "not_claimed":  # lost the claim → never double-execute
            async for ev in _emit(f"That one's already taken care of, {h}."):
                yield ev
            return
        flip = "approved" if judged.intent == "approve" else "rejected"
        yield _decision_resolved_event(thread_id, approval_id, flip)
        async for ev in _emit(_presented_outcome_speech(outcome, judged.intent)):
            yield ev
        return

    # skip ("not now / next") — DB-INERT client nav. Signal the client to grey THIS
    # card (the SAME markSkipped the button calls) so the next queued card surfaces;
    # the row stays pending and reappears on reload. NEVER claims, sends, or rejects.
    if judged.intent == "skip":
        yield {
            "type": "presented_nav",
            "thread_id": conversation_thread_id or thread_id,
            "content": {"action": "skip", "approval_id": approval_id},
        }
        # Just "Skipped" — the NEXT card (if any) surfaces with its own lead-in
        # ("Here's another…"), so promising "here's the next" here would double-
        # announce, and be wrong on the last card (the backend can't know the
        # client's session-local seen-set). Accurate regardless of what's left.
        async for ev in _emit(f"Skipped, {h}."):
            yield ev
        return

    # show_others — summarize what ELSE is pending (kind-agnostic). The current card
    # stays pending; the master can then approve / skip / "send it" as usual.
    if judged.intent == "show_others":
        summary = await _pending_queue_summary(exclude_approval_id=approval_id)
        async for ev in _emit(summary):
            yield ev
        return

    # edit (REVISE). A HEADS-UP card has no draft to revise yet → nudge to "go" first.
    if judged.needs_drafting:
        async for ev in _emit(
            f"I haven't drafted that one yet, {h} — say the word and I'll draft it, then you can tweak it."
        ):
            yield ev
        return
    # email cards re-draft (text AND voice); the re-queued card is re-approved before
    # anything sends, so a mis-heard voice edit is caught there. Tool / no-context → nudge.
    if judged.is_email_card and message and conversation_thread_id:
        async for ev in _revise_presented_card(
            judged, message, conversation_thread_id, _emit, speak=speak
        ):
            yield ev
        return
    async for ev in _emit(f"I can only send or discard this for now, {h}. Shall I go ahead?"):
        yield ev


async def _requeue_revised_email(row: Any, revised_draft: str) -> dict[str, Any]:
    """Create a NEW email_reply card from the discarded one's payload + the revised
    draft (same email thread → still a threaded reply to the same message; new
    approval_id). Returns the present-in-moment card content (the SAME tool-kind
    shape the queue / 3B emit, so 3C renders it identically)."""
    from datetime import timedelta

    from app.db.engine import async_session
    from app.db.models import PendingApproval

    payload = dict(row.payload or {})
    payload["draft"] = revised_draft
    sender = payload.get("sender", "")
    subject = payload.get("subject", "")
    description = f"Reply to '{subject}' from {sender}:\n\n{revised_draft}"
    async with async_session() as session:
        approval = PendingApproval(
            thread_id=row.thread_id,      # same email thread — a reply to the same message
            interrupt_id=row.thread_id,   # mirrors thread_id (no LangGraph token; not unique)
            action_type="email_reply",
            description=description,
            payload=payload,
            expires_at=datetime.now(UTC) + timedelta(hours=settings.APPROVAL_EXPIRY_HOURS),
        )
        session.add(approval)
        await session.commit()
        await session.refresh(approval)
    # Same SHARED mapping as the queue / present-in-moment card → identical UnifiedApprovalCard
    # shape (kind="email", incl. the quoted original), so the revised card can't drift either.
    from app.approvals_service import to_unified_card

    return to_unified_card(approval).model_dump()


async def _persist_edit_to_conversation(thread_id: str, message: str) -> None:
    """History fidelity: append the master's ACTUAL edit words + a brief confirmation
    to the conversation thread so a reload shows the negotiation. The re-draft CONTEXT
    (original draft + the change) is NOT persisted — it lived only in the re-draft
    prompt. Best-effort: a persistence hiccup never fails the edit."""
    h = settings.MASTER_HONORIFIC
    try:
        await graph().aupdate_state(
            {"configurable": {"thread_id": thread_id}},
            {"messages": [
                HumanMessage(content=message),
                AIMessage(content=f"I've revised that reply, {h} — the new draft is queued for your approval."),
            ]},
        )
    except Exception as exc:  # noqa: BLE001 — best-effort persistence
        logger.warning("persist_edit_to_conversation_failed", thread_id=thread_id, error=str(exc))


async def _revise_presented_card(
    judged: _PresentedJudgment, message: str, conversation_thread_id: str, emit, *, speak: bool = False
) -> AsyncIterator[dict[str, Any]]:
    """Edit re-draft (TEXT or VOICE). DISCARD-FIRST (claim-gated, reusing the atomic
    claim so a concurrent approve can't race it), THEN re-draft + re-queue a NEW
    email_reply card. A failed re-draft leaves NO card (the old is already discarded;
    the master re-asks) — never two approvable cards, never a send.

    VOICE parity: a voice-dictated edit re-drafts exactly like text, then SPEAKS a
    confirmation that ECHOES the requested change before surfacing the new card — so
    a mis-heard edit is audible, and the re-queued card must still be RE-APPROVED
    before anything sends (the re-approval is the safety net that makes voice-edit
    safe)."""
    from app.api.approvals import resolve_approval
    from app.email.responder import revise_draft

    h = settings.MASTER_HONORIFIC
    # 1. Claim-gated discard (pending→discarded). A lost claim → already resolved
    # (e.g. a concurrent approve won) → acknowledge, do nothing else.
    if await resolve_approval(judged.approval_id, "discard", "web") is None:
        async for ev in emit(f"That one's already taken care of, {h}."):
            yield ev
        return
    yield _decision_resolved_event(judged.row.thread_id, judged.approval_id, "discarded")

    payload = judged.row.payload or {}
    change = judged.change or message
    # 2. Re-draft + re-queue. On ANY failure → no new card (the old is discarded),
    # so the master is never left with two cards or a silent half-state.
    try:
        revised = await revise_draft(
            subject=payload.get("subject", ""),
            sender=payload.get("sender", ""),
            draft=payload.get("draft", ""),
            change=change,
        )
        if not (revised or "").strip():
            raise ValueError("empty revised draft")
        card = await _requeue_revised_email(judged.row, revised)
    except Exception as exc:  # noqa: BLE001 — never error the turn / never send
        logger.warning("revise_presented_failed", approval_id=judged.approval_id, error=str(exc))
        async for ev in emit(f"I couldn't revise that one, {h} — ask me again and I'll redo it."):
            yield ev
        return

    # 3. Persist the master's actual words (history fidelity), speak a change-echoing
    # confirmation (voice), and surface the NEW card present-in-moment (the queue poll
    # is the durable fallback for other sessions). The new card is RE-APPROVED next.
    await _persist_edit_to_conversation(conversation_thread_id, message)
    if speak:
        confirm = (
            f"Updated, {h} — {change}. Shall I send it?" if change
            else f"Revised, {h}. Shall I send the new draft?"
        )
        ev = await _speak_text(confirm)
        if ev:
            yield ev
    yield {"type": "approval_required", "thread_id": conversation_thread_id, "content": card}
    yield {"type": "done", "content": _terminal_payload(
        {"thread_id": conversation_thread_id, "status": "complete", "response": ""}
    )}


def _presented_outcome_speech(outcome: Any, intent: str) -> str:
    """The spoken/typed line for a resolved presented card: the draft-on-"go" line for
    a heads-up card, the inbound-email taxonomy for a send, the tool's result for a tool."""
    h = settings.MASTER_HONORIFIC
    # Heads-up "go"→draft / "leave it" — its own copy ("I've drafted it…" / "Left in your
    # inbox…"), not the send taxonomy (nothing was sent).
    if outcome.kind == "draft_request":
        return outcome.detail or f"Done, {h}."
    if intent == "reject":
        return f"Discarded, {h}."
    if outcome.kind == "email":
        return _email_outcome_speech(outcome.email_outcome)
    return outcome.detail or f"Done, {h}."


def _decision_resolved_event(thread_id: str, approval_id: str, status: str) -> dict[str, Any]:
    """The card-flip signal the frontend matches by approval_id (thread_id is
    informational — the inbound card lives on a different thread than the turn)."""
    return {
        "type": "decision_resolved",
        "thread_id": thread_id,
        "content": {"approval_id": approval_id, "status": status},
    }


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
        # Legacy paused-at-interrupt checkpoint backstop (see run_turn) — speak the
        # nudge, never resume. Nothing new pauses post-cutover; the drain clears any
        # pre-deploy paused checkpoint. (A spoken card is resolved hands-free via
        # the presented_approval_id path below, through the claim-gated dispatcher.)
        logger.info("voice_turn_legacy_pending_checkpoint_nudge", thread_id=thread_id)
        env = _pending_interrupt_envelope(thread_id)
        ev = await _speak_text(env["response"])
        if ev:
            yield ev
        yield {"type": "done", "content": _terminal_payload(env)}
        return

    card_reminder = ""   # set when an off-topic utterance is answered with a card pending
    if presented_approval_id:
        # A card is presented and the master SPOKE. Identical disposition to text (one
        # shared judge + classifier): resolve an actionable intent; re-ask an ambiguous
        # one; ACK a stale/gone card; otherwise (off-topic) FALL THROUGH to a normal
        # spoken turn (answer it) + a once-per-card spoken reminder. This replaces the
        # old voice-only nudge-and-block: voice now answers off-topic exactly like text.
        # Checked AFTER the conversation interrupt so a live in-thread approval wins.
        recent_context = await _recent_context(thread_id)
        disp, judged = await _presented_disposition(presented_approval_id, user_message, recent_context)
        logger.info(
            "voice_turn_presented", thread_id=thread_id, approval_id=presented_approval_id,
            disp=disp, intent=(judged.intent if judged else "stale"),
        )
        if disp == "resolve":
            async for ev in _resolve_presented_decision(
                judged, speak=True, message=user_message, conversation_thread_id=thread_id
            ):
                yield ev
            return
        if disp == "reask":
            async for ev in _reask_presented(judged, speak=True):
                yield ev
            return
        if disp == "plain":  # stale/gone card → brief spoken ack, never answer it as a turn
            async for ev in _stale_ack(speak=True):
                yield ev
            return
        if disp == "remind":  # off-topic → answer below + remind ONCE per card
            card_reminder = await _reminder_for(judged)
        # only 'remind' reaches here now → answer the utterance in the normal voice turn below.

    await _recover_cancellation_residue(thread_id)  # clean barge-in residue first
    msgs_before = await _existing_message_count(thread_id)
    initial_state = {
        "messages": [HumanMessage(content=user_message)],
        "thread_id": thread_id,
        "platform": platform,
        "channel_user_id": channel_user_id,
        "user_message": user_message,
        "turn_started_at": datetime.now(UTC).isoformat(),
        "tool_calls_this_turn": 0,  # reset per turn → the hourly rate check runs once (first agent pass)
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
                    for m in (upd or {}).get("messages", []) or []:
                        if node == "agent":
                            for tc in getattr(m, "tool_calls", None) or []:
                                yield {"type": "tool", "content": tc.get("name", "")}
                        elif node == "tool_executor":
                            # Present-in-moment (3B): surface the just-queued card in the
                            # HUD now (same approval_required event the text path emits).
                            ev = await _queued_approval_event(thread_id, m)
                            if ev:
                                yield ev

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
        # Off-topic-while-pending: after answering, SPEAK the card reminder + append it
        # to the response (voice parity with text — answer, then a one-line reminder).
        if card_reminder:
            ev = await _speak(card_reminder)
            if ev:
                yield ev
        # 5.4 proactive briefing: code-attach the brief/offer — SPOKEN (voice parity, the
        # caption rides the audio event) + in the DONE payload, exactly like the card reminder.
        # No live token: the caption comes from the audio event, and the done response is
        # canonical — so it's heard + shown once, never twice.
        attach = await _briefing_attach(result)
        if attach:
            ev = await _speak(attach)
            if ev:
                yield ev
        payload = _with_reminder(_terminal_payload(envelope), card_reminder)
        if attach:
            payload["response"] = _append_block(payload.get("response", ""), attach)
        yield {"type": "done", "content": payload}


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
