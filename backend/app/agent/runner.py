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

from langgraph.errors import GraphRecursionError

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


def _log_turn_error(thread_id: str, exc: BaseException, where: str) -> str:
    """D22 — structured turn-error capture so an opaque 'Could not reach Jarvis' is diagnosable
    next time. Distinguishes the GraphRecursionError loop-terminal (the L1 backstop) from a real
    fault, and logs the exception TYPE. Returns the master-facing message."""
    if isinstance(exc, GraphRecursionError):
        logger.error("graph_recursion_terminal", thread_id=thread_id, where=where,
                     limit=settings.GRAPH_RECURSION_LIMIT)
        return "That request got stuck in a loop and I stopped it, Sir — could you rephrase it?"
    logger.exception(where, thread_id=thread_id, error_type=type(exc).__name__, error=str(exc))
    return "I hit an internal error. Please try again."


async def _queued_readback_envelope(thread_id: str) -> dict[str, Any] | None:
    """A1 Fix 5 — if the turn QUEUED approval cards before it errored / hit the recursion cap, NAME
    them deterministically (the D1 read-back guarantee) instead of a raw 'stuck in a loop' / 'internal
    error': the rows are durable, so the master hears what's pending, not a dead end. Reads
    `queued_this_turn` off the last checkpoint (each tool_executor super-step persists it). Returns
    None when nothing was queued (→ the caller falls back to the plain error message)."""
    try:
        snap = await graph().aget_state({"configurable": {"thread_id": thread_id}})
        values = getattr(snap, "values", None) or {}
        queued = list(values.get("queued_this_turn") or [])
    except Exception as exc:  # noqa: BLE001 — the recovery path must never raise
        logger.warning("queued_readback_state_read_failed", thread_id=thread_id, error=str(exc))
        return None
    if not queued:
        return None
    # D24+D26: the same solicitation contract as queued_finish — a dedup-only or SUPERSEDE-mint
    # turn that errored must not re-offer consent (unseen/refused content); class from markers.
    from app.agent.nodes import _mint_class_this_turn, _readback_for_queued
    text = await _readback_for_queued(
        queued, settings.MASTER_HONORIFIC,
        mint_class=_mint_class_this_turn(values.get("messages") or []),
    )
    env = _error_envelope(thread_id, text, stop_reason="queued_before_error")
    env["status"] = "complete"   # the cards ARE queued — a real outcome, not a failure
    return env


def _config_with_handler(thread_id: str) -> tuple[dict, Any | None]:
    """Per-call config + the langfuse handler reference (so we can pull
    trace_id off it after the run). Returns (config, handler_or_None)."""
    handler = langfuse_callback_handler(thread_id)
    callbacks = [handler] if handler is not None else []
    config = {
        "configurable": {"thread_id": thread_id},
        "callbacks": callbacks,
        # Explicit recursion backstop (D22 / L1): a runaway loop hits this as a logged terminal,
        # not LangGraph's silent default-25 GraphRecursionError surfaced as a generic error.
        "recursion_limit": settings.GRAPH_RECURSION_LIMIT,
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
        "queued_signatures": [],  # L0 in-turn idempotency — turn-scoped, MUST reset (replace reducer)
        "queued_this_turn": [],   # A1 — cards queued this turn (read-back source); MUST reset per turn
        "terminal_delta": "",     # A2 s1b — the un-streamed terminal text (voice speaks it); turn-reset
        "briefing_attached": False,  # A2 s1b — persist's briefing re-entrancy guard; turn-reset
        "final_response": "",     # A1 Fix 1 — turn-reset so a re-emit-spin read-back can't prepend a
        #                           PRIOR turn's answer (final_response is a replace-reducer field too)
        # Card-resolution fields reset per turn (replace reducer persists them in the
        # checkpoint; a stale value would re-inject a dead card note / re-emit an old
        # decision_resolved). run_turn (Telegram) never carries a presented card.
        "card_context": "",
        "card_handled": False,
        "card_outcome": {},
    }

    started_ms = time.monotonic()
    try:
        result = await graph().ainvoke(initial_state, config=config)
    except Exception as exc:
        msg = _log_turn_error(thread_id, exc, "graph_invoke_failed")
        logger.info(
            "turn_complete", thread_id=thread_id, status="error",
            stop_reason=_stop_reason_for_error(exc), tool_calls=None,
        )
        rb = await _queued_readback_envelope(thread_id)   # Fix 5 — name any cards queued before the fault
        if rb is not None:
            return rb
        return _error_envelope(thread_id, msg, stop_reason=_stop_reason_for_error(exc))

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
    # A2 s1b: the briefing attaches IN-GRAPH (persist_node) — final_response already carries
    # it, persisted (D19 closed). The post-graph bolt-on is gone.
    return envelope  # context already on the envelope (set in _build_envelope)


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

    # Legacy paused-at-interrupt checkpoint backstop (see run_turn) — nudge to the
    # buttons, never resume. Nothing new pauses post-cutover; the drain clears any
    # pre-deploy paused checkpoint.
    if await _is_awaiting_approval(thread_id):
        logger.info("stream_turn_legacy_pending_checkpoint_nudge", thread_id=thread_id)
        yield {"type": "done",
               "content": _terminal_payload(_pending_interrupt_envelope(thread_id))}
        return

    # Step A: a presented card no longer short-circuits before the graph. The card id is
    # passed INTO the graph; `card_resolution_node` judges it on the strong model and either
    # resolves it (claim-gated) or routes to the agent — either way the exchange persists
    # (kills D2/NV1) and a question gets a real answer (kills D3). card_reminder retired (the
    # agent notes a pending card via the injected card_context); "" keeps the payload helper inert.
    card_reminder = ""

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
        "queued_signatures": [],  # L0 in-turn idempotency — turn-scoped, MUST reset (replace reducer)
        "queued_this_turn": [],   # A1 — cards queued this turn (read-back source); MUST reset per turn
        "terminal_delta": "",     # A2 s1b — the un-streamed terminal text (voice speaks it); turn-reset
        "briefing_attached": False,  # A2 s1b — persist's briefing re-entrancy guard; turn-reset
        "final_response": "",     # A1 Fix 1 — turn-reset so a re-emit-spin read-back can't prepend a
        #                           PRIOR turn's answer (final_response is a replace-reducer field too)
        # reset per turn (replace reducer) so a prior turn's card state can't leak.
        "card_context": "",
        "card_handled": False,
        "card_outcome": {},
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
        msg = _log_turn_error(thread_id, exc, "graph_stream_failed")
        rb = await _queued_readback_envelope(thread_id)   # Fix 5 — name any cards queued before the fault
        if rb is not None:
            yield {"type": "done", "content": _terminal_payload(rb)}
        else:
            yield {
                "type": "error",
                "content": msg,
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
        # Step A: a presented-card resolution handled in-graph → emit the frontend events
        # (decision_resolved / approval_required for an edit re-queue / presented_nav for skip)
        # reconstructed from the node-set card_outcome, so the dashboard greys/surfaces cards
        # exactly as before — now from a PERSISTED turn.
        for ev in _card_outcome_events(thread_id, result.get("card_outcome") or {}):
            yield ev
        # A2 s1b: the briefing is in-graph (persist_node) → already inside the envelope's
        # response, persisted. The done payload is canonical → it shows exactly once.
        payload = _with_reminder(_terminal_payload(envelope), card_reminder)
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
    from app.agent.nodes import QUEUED_MARKER_TAG, QUEUED_UPDATE_TAG

    content = getattr(message, "content", "")
    tool_call_id = getattr(message, "tool_call_id", None)
    # Both MINT markers surface a card in-stream: a fresh [QUEUED] and a D26 supersede-mint
    # [QUEUED_UPDATE] (a NEW row exists either way; [ALREADY_QUEUED] minted nothing → no event).
    if not (isinstance(message, ToolMessage) and tool_call_id
            and isinstance(content, str)
            and (content.startswith(QUEUED_MARKER_TAG) or content.startswith(QUEUED_UPDATE_TAG))):
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
    approval_id: str, message: str, recent_context: str = "",
    require_pending: bool = True,
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
        if row is None:
            return None
        # A2 s2: the conversation-referent caller judges INTENT against a row of ANY status
        # (liveness gates DISPATCH separately, so a resolved card still gets an honest ack
        # instead of a blind pass-through). The legacy pending-only contract stays the default.
        if require_pending and row.status != "pending":
            return None
        # Expiry guard (wrong-card seal): the hourly sweeper can lag, leaving an EXPIRED row at
        # status='pending'. list_pending_cards() filters expires_at>now, so an expired presented
        # card would be admitted here but ABSENT from the gate's live set — risking a wrong-card
        # substitution. Treat an expired row as stale (gone) so the turn acks, never re-targets.
        if require_pending and getattr(row, "expires_at", None) is not None \
                and row.expires_at <= datetime.now(UTC):
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


def _decision_resolved_event(thread_id: str, approval_id: str, status: str) -> dict[str, Any]:
    """The card-flip signal the frontend matches by approval_id (thread_id is
    informational — the inbound card lives on a different thread than the turn)."""
    return {
        "type": "decision_resolved",
        "thread_id": thread_id,
        "content": {"approval_id": approval_id, "status": status},
    }


def _card_outcome_events(thread_id: str, outcome: dict[str, Any]) -> list[dict[str, Any]]:
    """Reconstruct the frontend events for a presented-card resolution that
    `card_resolution_node` handled IN the graph (Step A). The node sets `card_outcome`
    in state; the runner emits the same events the old runner short-circuits did —
    a card flip (decision_resolved), a skip nav (presented_nav), and/or the NEW card
    from an edit re-draft (approval_required) — so the dashboard greys/surfaces cards
    exactly as before, now from a PERSISTED turn."""
    events: list[dict[str, Any]] = []
    if not outcome:
        return events
    approval_id = outcome.get("approval_id", "")
    status = outcome.get("decision_status") or ""
    if outcome.get("nav") == "skip":
        events.append({
            "type": "presented_nav", "thread_id": thread_id,
            "content": {"action": "skip", "approval_id": approval_id},
        })
    elif status in ("approved", "rejected", "discarded"):
        events.append(_decision_resolved_event(
            outcome.get("thread_id") or thread_id, approval_id, status
        ))
    if outcome.get("new_card"):
        events.append({
            "type": "approval_required", "thread_id": thread_id,
            "content": outcome["new_card"],
        })
    return events


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
    runtime_stats.record_turn()
    yield {"type": "thread_id", "content": thread_id}

    config, handler = _config_with_handler(thread_id)

    if await _is_awaiting_approval(thread_id):
        # Legacy paused-at-interrupt checkpoint backstop (see run_turn) — speak the
        # nudge, never resume. Nothing new pauses post-cutover; the drain clears any
        # pre-deploy paused checkpoint. (A spoken card is resolved hands-free via
        # the conversation-linked resolution path, through the claim-gated dispatcher.)
        logger.info("voice_turn_legacy_pending_checkpoint_nudge", thread_id=thread_id)
        env = _pending_interrupt_envelope(thread_id)
        ev = await _speak_text(env["response"])
        if ev:
            yield ev
        yield {"type": "done", "content": _terminal_payload(env)}
        return

    # Step A: a presented card no longer short-circuits before the graph (voice parity with
    # text). The card id is passed INTO the graph; `card_resolution_node` judges it on the
    # strong model and either resolves it (claim-gated, spoken via the post-stream reply) or
    # routes to the agent — either way the exchange persists (kills NV1) and a question gets a
    # real answer (kills D3). card_reminder retired (the agent notes a pending card via the
    # injected card_context); "" keeps the payload/speak helpers inert.
    card_reminder = ""

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
        "queued_signatures": [],  # L0 in-turn idempotency — turn-scoped, MUST reset (replace reducer)
        "queued_this_turn": [],   # A1 — cards queued this turn (read-back source); MUST reset per turn
        "terminal_delta": "",     # A2 s1b — the un-streamed terminal text (voice speaks it); turn-reset
        "briefing_attached": False,  # A2 s1b — persist's briefing re-entrancy guard; turn-reset
        "final_response": "",     # A1 Fix 1 — turn-reset so a re-emit-spin read-back can't prepend a
        #                           PRIOR turn's answer (final_response is a replace-reducer field too)
        # reset per turn (replace reducer) so a prior turn's card state can't leak.
        "card_context": "",
        "card_handled": False,
        "card_outcome": {},
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
        msg = _log_turn_error(thread_id, error_exc, "voice_stream_failed")
        rb = await _queued_readback_envelope(thread_id)   # Fix 5 — speak/name cards queued before the fault
        if rb is not None:
            ev = await _speak(rb["response"])
            if ev:
                yield ev
            yield {"type": "done", "content": _terminal_payload(rb)}
            return
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
        # The ONE terminal delta (A2 s1b — closes NV7, keeps 10e7431): when NO agent text was
        # streamed, nothing was spoken yet → speak the whole response (it includes the delta).
        # When tokens DID stream, they were already spoken — speak ONLY the un-streamed
        # terminal delta (the in-graph approval message + briefing), never re-speaking tokens.
        terminal_delta = (result.get("terminal_delta") or "").strip()
        if not first_token and (envelope.get("response") or "").strip():
            ev = await _speak(envelope["response"])
            if ev:
                yield ev
        elif first_token and terminal_delta:
            ev = await _speak(terminal_delta)
            if ev:
                yield ev
        # Step A: a presented-card resolution handled in-graph → emit the frontend events
        # (decision_resolved / approval_required for an edit re-queue / presented_nav for skip)
        # reconstructed from the node-set card_outcome. The spoken outcome reply is already
        # voiced above (it's the post-stream response); these are the silent card-state signals.
        for ev in _card_outcome_events(thread_id, result.get("card_outcome") or {}):
            yield ev
        # Off-topic-while-pending: after answering, SPEAK the card reminder + append it
        # to the response (voice parity with text — answer, then a one-line reminder).
        if card_reminder:
            ev = await _speak(card_reminder)
            if ev:
                yield ev
        # A2 s1b: the briefing is in-graph -> already inside the envelope's response, persisted.
        payload = _with_reminder(_terminal_payload(envelope), card_reminder)
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
