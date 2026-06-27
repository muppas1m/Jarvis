"""
Graph nodes — the four steps of an agent turn.

Topology (driven by graph.py's `build_graph`):

    START -> memory_load -> agent -> [should_continue]
                              ^       ├─ tool_calls?  -> tool_executor
                              |       └─ no           -> persist -> END
                              |
                              |     [should_continue_tools after tool_executor]
                              |       ├─ more pending? -> tool_executor
                              └───────└─ all done      -> agent

Each node receives the AgentState dict and returns a partial-state dict
that LangGraph merges via the per-field reducers declared in state.py.

Resume safety (the load-bearing design choice, see test_resume_dedup.py):
  `tool_executor` processes exactly ONE tool call per invocation. The
  conditional edge `should_continue_tools` loops it back to itself until
  every tool call in the most recent AIMessage has produced a ToolMessage,
  then routes to `agent`. State commits BETWEEN invocations, not within
  one — so when an APPROVE-tier call hits `interrupt()` and pauses, any
  tool calls processed in earlier invocations are already durable. On
  resume only the interrupted call re-runs.

  An older loop-inside-node design tried to dedup via "skip if a
  ToolMessage with this tool_call_id is already in state". That doesn't
  work because `interrupt()` does NOT commit the node's partial return
  value — it just snapshots state and exits. So earlier-iteration
  ToolMessages built up in a local list never reached the reducer, and
  resume re-executed them.
"""
import asyncio
import json
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    RemoveMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_litellm import ChatLiteLLM
from sqlalchemy import select, update

from app.agent.message_repair import repair_orphaned_tool_calls
from app.agent.prompts import build_system_prompt
from app.agent.rate_limits import rate_limiter
from app.agent.safety import SafetyClassifier, SafetyLevel
from app.agent.sanitizer import sanitize_tool_result
from app.agent.state import AgentState
from app.config import settings
from app.db.engine import async_session
from app.db.models import AuditTrail, PendingApproval, ToolResult
from app.llm.leak_sanitize import strip_function_leak
from app.memory.manager import get_memory
from app.utils.exceptions import (
    ApprovalExpiredError,
    CostCapExceededError,
    RateLimitedError,
    SafetyBlockedError,
)
from app.utils.logging import get_logger

logger = get_logger(__name__)

# Heavy singleton — built once, not per-turn. (MemoryManager is lazy too, via
# get_memory() in app.memory.manager — building it fires an Ollama call, so we
# defer it to first use instead of at import time.)
safety = SafetyClassifier()


# ============================================================================
# Node 1 — memory_load
# ============================================================================
async def memory_load_node(state: AgentState) -> dict:
    """Load Tier 5 (split profile) + Tiers 3/4 (Mem0 recall) for this turn.

    Tier 2 (message history) is already in state["messages"] courtesy of the
    LangGraph checkpointer. We don't touch it.
    """
    user_message = state["user_message"]
    _t0 = time.monotonic()
    context = await get_memory().build_context(user_message=user_message)

    # Proactive-briefing check-in (5.4): ONE cheap read at turn START → the deterministic
    # directive (model guidance) + the proactive MODE and OFFER text the runner renders
    # post-turn (code guarantees the output; the model only writes the wrapper + the
    # deliver_briefing() signal). Read the gap/cooldown from the CURRENT state, then advance
    # last_seen. Fully fail-soft — the briefing intelligence must never break a turn.
    directive, proactive, offer = "", "suppress", ""
    try:
        from app.agent.briefing_state import (
            briefing_directive,
            load_live_state,
            proactive_mode,
            render_offer,
            touch_last_seen,
        )
        now = datetime.now(UTC)
        live = await load_live_state(now)
        directive, proactive, offer = briefing_directive(live), proactive_mode(live), render_offer(live)
        await touch_last_seen(now)
    except Exception as exc:  # noqa: BLE001 — never fail a turn on the briefing read
        logger.warning("briefing_checkin_state_failed", error=str(exc))

    logger.info("node_timing", node="memory_load", ms=int((time.monotonic() - _t0) * 1000))
    return {
        "user_profile_always_on": context["user_profile_always_on"],
        "user_profile_on_demand": context["user_profile_on_demand"],
        "relevant_memories": context["relevant_memories"],
        "briefing_directive": directive,
        "briefing_proactive": proactive,
        "briefing_offer": offer,
    }


# ============================================================================
# Node 2 — agent (LLM call with bound tools)
# ============================================================================
def _build_chat_model(tools: list, primary_model: str | None = None):
    """Build the agent's chat model — primary + fallback wrapped in
    FallbackChatLLM for resilience against Groq rate-limit and
    tool_use_failed errors.

    `primary_model` overrides the primary slot — the §B two-speed cascade uses
    this to route voice turns to the FAST tier (settings.FAST_MODEL). Defaults
    to settings.PRIMARY_MODEL (the frontier model) for every non-voice caller.

    Both ChatLiteLLM instances are constructed per-turn (cheap; they're
    config objects, not heavy state). Tools are bound to BOTH before
    wrapping, so a fallback fires with the same tool set the primary
    had — agent_node downstream sees structured tool_calls regardless
    of which model produced them.

    Returns a Runnable that mirrors ChatLiteLLM's invoke/ainvoke
    interface; agent_node calls `.ainvoke(messages)` as before.

    See `project_agent_node_bypasses_gateway_fallback.md` for the
    architectural rationale.

    `streaming` is driven by the `stream_tokens` contextvar (set only by
    `stream_turn`): True makes ChatLiteLLM stream internally so its
    on_llm_new_token callbacks fire, which LangGraph's stream_mode="messages"
    turns into a token-by-token stream. Default False leaves the non-streaming
    run_turn path unchanged. See `app.llm.stream_mode`.
    """
    from app.llm.fallback_llm import FallbackChatLLM
    from app.llm.stream_mode import stream_tokens

    streaming = stream_tokens.get()
    primary = ChatLiteLLM(
        model=primary_model or settings.PRIMARY_MODEL, temperature=0.7, streaming=streaming
    )
    fallback = ChatLiteLLM(model=settings.FALLBACK_MODEL, temperature=0.7, streaming=streaming)

    if tools:
        primary = primary.bind_tools(tools)
        fallback = fallback.bind_tools(tools)

    return FallbackChatLLM(primary=primary, fallback=fallback)


def _depoison_for_llm(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Return the history with any `<function…>` leak stripped from prior ASSISTANT
    messages — copies only, so state (the stored thread) is never mutated. Human +
    tool messages pass through untouched, so a user message that merely says the
    word 'function' is left alone."""
    out: list[BaseMessage] = []
    for m in messages:
        if isinstance(m, AIMessage) and isinstance(m.content, str):
            clean = strip_function_leak(m.content)
            if clean != m.content:
                m = m.model_copy(update={"content": clean})
        out.append(m)
    return out


async def agent_node(state: AgentState) -> dict:
    """Reasoning step. Builds the system prompt, calls the LLM with bound
    tools, appends the LLM's response to messages."""
    # Tool registry doesn't exist until Turn 10 — lazy-import so this module
    # stays importable in the meantime.
    from app.agent.tools.registry import tool_registry

    # Per-thread sliding-window cap — only checked on the first agent_node
    # call of a turn (tool_calls_this_turn is unset at turn start).
    if not state.get("tool_calls_this_turn"):
        ok = await rate_limiter.check_turn_rate(state["thread_id"])
        if not ok:
            return {
                "messages": [
                    AIMessage(
                        content=(
                            "I've hit the per-hour conversation rate limit. "
                            "Please try again in a few minutes."
                        )
                    )
                ],
                "final_response": "rate_limited",
            }

    # Top-k tool selection — registry embeds tool descriptions and returns
    # only the most relevant ones for this query, plus any "always_loaded"
    # tools (memory_search, etc.).
    latest_user_msg = next(
        (m.content for m in reversed(state["messages"]) if isinstance(m, HumanMessage)),
        state["user_message"],
    )
    _t_sel = time.monotonic()
    selected_tools = await tool_registry.select_relevant_tools(
        query=latest_user_msg,
        top_k=15,
    )
    logger.info("node_timing", node="tool_select", ms=int((time.monotonic() - _t_sel) * 1000))

    # Voice mode (set by voice_turn) → a brevity directive in the prompt + fast-tier
    # routing below. Read once here; both consumers reuse it.
    from app.llm.stream_mode import voice_mode

    is_voice = voice_mode.get()

    # Stable-prefix-first system prompt for KV cache friendliness.
    always_on_dict = state.get("user_profile_always_on") or {}
    system_prompt = build_system_prompt(
        always_on_profile={
            "name": always_on_dict.get("name", "Master"),
            "always_on": always_on_dict.get("always_on", {}),
        },
        on_demand_profile=state.get("user_profile_on_demand", []),
        memories=state.get("relevant_memories", []),
        platform=state["platform"],
        current_datetime=datetime.now(UTC).isoformat(),
        voice=is_voice,
        briefing_directive=state.get("briefing_directive", ""),
    )

    msgs: list[BaseMessage] = [SystemMessage(content=system_prompt)]
    # Compaction (4.B.3): if older turns were summarized, inject the rolling
    # summary as a context block AFTER the stable prompt and BEFORE the recent
    # verbatim messages — so the conversational thread survives without resending
    # the full history. Durable facts are already in the <memories> block above.
    running_summary = (state.get("running_summary") or "").strip()
    if running_summary:
        msgs.append(SystemMessage(content=(
            "[Earlier conversation summary — older turns were compacted to save "
            "context; specific facts live in long-term memory above]\n" + running_summary
        )))
    # De-poison (open-weights leak): strip any `<function…>` tool-call leak the
    # model emitted as TEXT in a PRIOR assistant turn from the history it now sees,
    # so it can't anchor on its own past format and re-emit it (in-context
    # poisoning). Copies only — the stored thread is untouched (no checkpoint clear).
    msgs.extend(_depoison_for_llm(state["messages"]))

    # Defense-in-depth: an orphaned tool_call (an AIMessage tool_call with no
    # answering ToolMessage — e.g. a pending approval interrupt that a free-text
    # turn landed on top of) makes the OpenAI fallback 400 the whole history.
    # run_turn prevents that orphan at source; this neutralizes any that slip
    # through so the fallback can never choke. See app.agent.message_repair.
    msgs = repair_orphaned_tool_calls(msgs)

    # Two-speed cascade (§B): in voice mode the reasoning LLM defaults to the
    # FAST tier for sub-second first-token; escalate to the frontier model once
    # tools have run (synthesising a tool result is where deep reasoning earns
    # its latency). The brain is unchanged — only the model speed is tuned.
    primary_model = settings.PRIMARY_MODEL
    if is_voice and settings.VOICE_FAST_TIER:
        has_tool_results = any(isinstance(m, ToolMessage) for m in state["messages"])
        primary_model = settings.PRIMARY_MODEL if has_tool_results else settings.FAST_MODEL

    llm = _build_chat_model(selected_tools, primary_model=primary_model)
    _t_llm = time.monotonic()
    response = await llm.ainvoke(msgs)
    logger.info(
        "node_timing", node="agent_llm", model=primary_model,
        ms=int((time.monotonic() - _t_llm) * 1000),
    )

    # Safety net (open-weights leak): if a `<function…>` leak slipped past the
    # FallbackChatLLM re-issue (e.g. the fallback model also leaked), strip it
    # before the response is persisted to the thread OR shown — it must never reach
    # the stored history. (Normal answers have no `<function` tag → no-op.)
    if isinstance(response, AIMessage) and isinstance(response.content, str):
        cleaned = strip_function_leak(response.content)
        if cleaned != response.content:
            logger.warning("agent_response_function_leak_stripped")
            response = response.model_copy(update={"content": cleaned})

    has_tool_calls = bool(getattr(response, "tool_calls", None))
    update: dict = {"messages": [response]}
    if not has_tool_calls:
        update["final_response"] = (
            response.content
            if isinstance(response.content, str)
            else str(response.content)
        )
    return update


# ============================================================================
# Shared guarded tool execution (graph node + execute-on-approve dispatcher)
# ============================================================================
@dataclass
class ToolExecResult:
    """Outcome of one guarded tool execution — the sanitized result string plus
    success/error/latency. The graph node wraps ``content`` in a ToolMessage; the
    out-of-band execute-on-approve dispatcher (Phase 3) renders it for the master.

    ``uncertain`` is the THIRD outcome (success is not a bool here): a send that hit
    ``EmailSendUncertain`` — could NOT be confirmed (timeout / 5xx, may already have gone
    out). success=False + uncertain=True so the outcome reads "may have sent — couldn't
    confirm" (⚠️), never a clean ✅ and never a definite ❌."""

    content: str
    success: bool
    error: str | None
    latency_ms: int
    uncertain: bool = False


async def execute_tool_guarded(
    thread_id: str,
    tool_name: str,
    tool_args: dict,
    *,
    level: SafetyLevel,
    tool_call_id: str = "",
) -> ToolExecResult:
    """Execute ONE tool with the execute-time guards — the shared core used by
    BOTH ``tool_executor_node`` (SAFE / NOTIFY / approved-APPROVE, inline) and the
    out-of-band execute-on-approve dispatcher. Maps the JarvisError family to
    friendly messages, captures latency, sanitizes + archives the result, audits,
    and (NOTIFY-tier) pings the master. The whole post-execute block is wrapped so
    a render/DB/notify failure never loses the result.

    It does NOT apply the per-TURN rate limit: that's a QUEUE-time runaway guard
    (``tool_executor_node`` still checks it before an APPROVE-tier tool is queued,
    and it matters more now that one turn can queue several cards). The out-of-band
    execute of a single master-approved action is exempt by design (Phase 3
    rate-limit split)."""
    from app.agent.tools.registry import tool_registry
    from app.email.provider.base import EmailSendUncertain
    from app.messaging.failure_alerter import notify_tool_executed

    dispatch_start = time.monotonic()
    uncertain = False
    try:
        raw_result = await tool_registry.execute(tool_name, tool_args)
        success = True
        err: str | None = None
    except EmailSendUncertain as exc:
        # The send could NOT be confirmed (timeout / 5xx — may already have gone out). The
        # THIRD outcome: not a clean success, not a definite failure. The tool carries the
        # honest, recipient-specific wording on the exception.
        logger.warning("tool_send_uncertain", tool=tool_name)
        raw_result = str(exc)
        success = False
        uncertain = True
        err = None
    except RateLimitedError as exc:
        logger.warning("tool_rate_limited", tool=tool_name, error=str(exc))
        raw_result = f"[RATE-LIMITED] Hit hourly cap on `{tool_name}`. Try again later. ({exc})"
        success = False
        err = f"RATE_LIMITED: {exc}"
    except SafetyBlockedError as exc:
        logger.warning("tool_safety_blocked_runtime", tool=tool_name, error=str(exc))
        raw_result = f"[BLOCKED] Safety layer rejected `{tool_name}`: {exc}"
        success = False
        err = f"SAFETY_BLOCKED: {exc}"
    except ApprovalExpiredError as exc:
        logger.warning("tool_approval_expired", tool=tool_name, error=str(exc))
        raw_result = f"[EXPIRED] Approval window for `{tool_name}` lapsed: {exc}"
        success = False
        err = f"APPROVAL_EXPIRED: {exc}"
    except CostCapExceededError as exc:
        logger.error("tool_cost_cap_exceeded", tool=tool_name, error=str(exc))
        raw_result = f"[BUDGET] Daily LLM spend cap reached — `{tool_name}` deferred until tomorrow."
        success = False
        err = f"COST_CAP_EXCEEDED: {exc}"
    except Exception as exc:  # noqa: BLE001 — keep one tool failure from killing the turn
        logger.error("tool_execution_failed", tool=tool_name, error=str(exc))
        raw_result = f"[ERROR] Tool '{tool_name}' failed: {exc}"
        success = False
        err = str(exc)
    latency_ms = int((time.monotonic() - dispatch_start) * 1000)

    # ---- post-execute: sanitize / archive / audit / notify -----------------
    # Wrapped as a whole: a failure in ANY of these must NOT leave the result
    # un-recorded (and, in the node, the tool_call unanswered — the P1 orphan).
    content = f"[ERROR] Tool '{tool_name}' ran but its result could not be recorded."
    try:
        content, archived_full = sanitize_tool_result(
            tool_name=tool_name,
            raw_result=raw_result,
            max_chars=settings.TOOL_RESULT_MAX_CHARS,
        )
        if archived_full is not None:
            archive_id = await _archive_tool_result(
                thread_id=thread_id,
                tool_name=tool_name,
                tool_call_id=tool_call_id,
                full_result=archived_full,
            )
            content += f"\n[archived:{archive_id}]"

        await _log_audit(
            thread_id, tool_name, level, tool_args,
            success=success, error=err, latency_ms=latency_ms,
        )

        if level == SafetyLevel.NOTIFY:
            await notify_tool_executed(thread_id=thread_id, tool_name=tool_name)
    except Exception as exc:  # noqa: BLE001 — never drop the result (P1 orphan guard)
        logger.error("tool_post_execute_failed", tool=tool_name, error=str(exc))

    return ToolExecResult(
        content=content, success=success, error=err, latency_ms=latency_ms, uncertain=uncertain
    )


# The result handed back to the agent when an APPROVE-tier tool is QUEUED (Phase
# 3). It must read as NOT-done so the agent relays "queued for approval", never
# "sent/done" (no-hallucinated-actions). The card is the durable record either way.
# The honest tag fronting a queued tool's ToolMessage. The streaming layer
# (runner._queued_approval_event) matches this prefix to surface the just-queued
# card in-stream the moment it's queued (3B present-in-moment).
QUEUED_MARKER_TAG = "[QUEUED]"
_QUEUED_MARKER = (
    QUEUED_MARKER_TAG + " The `{tool}` action is NOT done — it has been QUEUED for the "
    "master's approval and will run ONLY after they approve it. Tell the master you've "
    "queued it for their approval; do NOT say it is sent / done / created / scheduled."
)


# ============================================================================
# Node 3 — tool_executor (one tool call per invocation; loops via the graph)
# ============================================================================
async def tool_executor_node(state: AgentState) -> dict:
    """Execute exactly ONE pending tool call from the most recent AIMessage.

    Single-call-per-invocation loops via `should_continue_tools` (which re-enters
    this node while the latest AIMessage still has un-processed tool calls, else
    routes back to `agent`). Each invocation commits its own ToolMessage, so a
    turn with mixed tool calls (e.g. a SAFE calendar read + an APPROVE-tier email
    send) executes the SAFE one and QUEUES the APPROVE one, all in one completing
    turn — no blocking.

    (Phase 3 retired `interrupt()`: APPROVE-tier tools no longer pause the turn;
    they queue + return a [QUEUED] ToolMessage and execute out-of-band on approve.
    The old one-call rationale — "interrupt() doesn't commit partial returns" — no
    longer applies; the per-call loop simply keeps each ToolMessage commit clean.)

    For each call:
      1. Per-turn rate-limit check (the QUEUE-time runaway guard).
      2. Safety classification (SAFE / NOTIFY / APPROVE / BLOCKED).
      3. APPROVE → write a PendingApproval row, ping master, return [QUEUED]
         (NON-blocking — no interrupt, no in-turn side effect).
      4. SAFE/NOTIFY → execute the tool (catching JarvisError family).
      5. Sanitize + optionally archive the result.
      6. Audit-log the row.
      7. NOTIFY → ping master that the tool ran.
    """
    # Lazy imports — these modules don't exist as module attributes; the
    # imports run at call time so test patches via `patch.object(...)` work.
    from app.messaging.failure_alerter import send_approval_request_to_master

    # Walk BACK to the most recent AIMessage with tool_calls. We can't just
    # look at state["messages"][-1] because once we've processed at least one
    # tool call, the last message is the ToolMessage we just emitted — not
    # the AIMessage carrying the tool_calls list.
    last_ai_with_tools = next(
        (m for m in reversed(state["messages"])
         if isinstance(m, AIMessage) and m.tool_calls),
        None,
    )
    if last_ai_with_tools is None:
        return {}

    # Find the FIRST tool call without a matching ToolMessage already in state.
    already_processed = {
        m.tool_call_id
        for m in state["messages"]
        if isinstance(m, ToolMessage)
    }
    next_tc = next(
        (tc for tc in last_ai_with_tools.tool_calls if tc["id"] not in already_processed),
        None,
    )
    if next_tc is None:
        # All tool calls in the last AIMessage have been processed — nothing
        # to do. The conditional edge after this node will route to agent.
        return {}

    tool_call_id = next_tc["id"]
    tool_name = next_tc["name"]
    tool_args = next_tc.get("args") or {}

    thread_id = state["thread_id"]
    turn_id = state.get("turn_started_at", "no-turn")

    # ---- per-turn rate limit ------------------------------------------------
    ok = await rate_limiter.check_and_increment_tool(
        thread_id, turn_id, tool_name, tool_call_id=tool_call_id
    )
    if not ok:
        await _log_audit(
            thread_id, tool_name, SafetyLevel.SAFE, tool_args,
            success=False, error="RATE_LIMITED",
        )
        return {
            "messages": [
                ToolMessage(
                    content=f"[RATE-LIMITED] Tool '{tool_name}' exceeded per-turn limit.",
                    tool_call_id=tool_call_id,
                )
            ]
        }

    # ---- classify -----------------------------------------------------------
    level = safety.classify(tool_name, tool_args)

    if level == SafetyLevel.BLOCKED:
        await _log_audit(
            thread_id, tool_name, level, tool_args,
            success=False, error="BLOCKED",
        )
        return {
            "messages": [
                ToolMessage(
                    content=f"[BLOCKED] Tool '{tool_name}' is not permitted.",
                    tool_call_id=tool_call_id,
                )
            ]
        }

    # ---- APPROVE → QUEUE (non-blocking; executes out-of-band on approve) ----
    if level == SafetyLevel.APPROVE:
        # Pre-queue validation: reject obviously-bad input (e.g. a placeholder/missing email
        # recipient the LLM emitted) BEFORE minting a card. The agent reads the error and asks
        # the master for the real value; nothing is queued, nothing dispatches to a 400.
        pre_error = _pre_approve_error(tool_name, tool_args)
        if pre_error is not None:
            await _log_audit(
                thread_id, tool_name, level, tool_args, success=False, error="INVALID_ARGS",
            )
            return {"messages": [ToolMessage(content=pre_error, tool_call_id=tool_call_id)]}

        # Phase 3 — APPROVE-tier tools are NON-BLOCKING: QUEUE, never interrupt().
        # The graph used to interrupt() here and BLOCK the whole turn until a
        # resume re-entered the node and executed. Now the node creates the
        # synthetic PendingApproval row, pings the master, and returns a [QUEUED]
        # ToolMessage so the TURN COMPLETES cleanly. The action executes
        # OUT-OF-BAND on approve via the execute-on-approve dispatcher
        # (resolve_and_dispatch → dispatch_approval), reusing THIS row's payload.
        # Retiring interrupt() kills its whole fragility class (orphaned
        # tool_calls, resume-fail, async-rebind-on-resume). NO side effect fires
        # in this turn — only the durable queue row + the ping.
        #
        # Idempotency: interrupt_id (the tool_call_id) is unique per call; the
        # find-or-create keeps the should_continue_tools loop (or any re-process)
        # from minting a duplicate row + a second ping.
        approval_id = await _find_pending_approval(thread_id, interrupt_id=tool_call_id)
        if approval_id is None:
            # Enrich the prompt with a pre-approval warning (calendar conflict
            # check today) so the master sees overlaps before deciding.
            description = _describe_action(tool_name, tool_args)
            warning = await _approval_warning(tool_name, tool_args)
            if warning:
                description = f"{description}\n\n{warning}"
            approval_id = await _create_pending_approval(
                thread_id=thread_id,
                interrupt_id=tool_call_id,
                tool_name=tool_name,
                tool_args=tool_args,
            )
            await send_approval_request_to_master(
                approval_id=str(approval_id),
                tool_name=tool_name,
                description=description,
            )
        else:
            logger.info(
                "approval_already_queued_skip_duplicate",
                thread_id=thread_id, interrupt_id=tool_call_id, tool_name=tool_name,
            )
        # Audit the QUEUE event (not an execute — the tool has NOT run).
        await _log_audit(
            thread_id, tool_name, level, tool_args, success=False, error="QUEUED",
        )
        return {
            "messages": [
                ToolMessage(
                    content=_QUEUED_MARKER.format(tool=tool_name),
                    tool_call_id=tool_call_id,
                )
            ]
        }

    # ---- execute (SAFE or NOTIFY — APPROVE is queued above, never reaches here)
    # The execute + JarvisError handling + sanitize/archive/audit/notify is the
    # shared guarded core (execute_tool_guarded), reused by the execute-on-approve
    # dispatcher. The node wraps the result in a ToolMessage (always — the P1
    # orphan guard).
    exec_result = await execute_tool_guarded(
        thread_id, tool_name, tool_args, level=level, tool_call_id=tool_call_id
    )
    return {"messages": [ToolMessage(content=exec_result.content, tool_call_id=tool_call_id)]}


def should_continue_tools(state: AgentState) -> str:
    """Routing after `tool_executor`. Loop back to itself if the latest
    AIMessage still has unprocessed tool calls; otherwise return to the
    agent so it can react to the tool results."""
    # Walk back to find the most recent AIMessage with tool_calls (skip any
    # ToolMessages we just emitted).
    last_ai_msg = None
    for m in reversed(state["messages"]):
        if isinstance(m, AIMessage) and m.tool_calls:
            last_ai_msg = m
            break
    if last_ai_msg is None:
        return "agent"   # no tool calls anywhere — odd, but safe default

    already_processed = {
        m.tool_call_id
        for m in state["messages"]
        if isinstance(m, ToolMessage)
    }
    pending = [tc for tc in last_ai_msg.tool_calls if tc["id"] not in already_processed]
    return "tool_executor" if pending else "agent"


# ============================================================================
# Node 4 — persist (Mem0 extraction at end of turn)
# ============================================================================
async def persist_node(state: AgentState) -> dict:
    """End-of-turn: extract memories via Mem0. LangGraph already persisted
    raw messages; this hands the (user, assistant) pair to Mem0 so it can
    extract durable facts."""
    from app.llm.eval_mode import eval_mode

    # Eval runs skip persistence so they don't pollute the master's Mem0.
    if eval_mode.get():
        return {}

    user_msg = state.get("user_message", "")
    final = state.get("final_response", "")
    if user_msg and final and final != "rate_limited":
        try:
            await get_memory().persist_turn(
                thread_id=state["thread_id"],
                user_message=user_msg,
                assistant_response=final,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("memory_persist_failed", error=str(exc))
    return {}


# ============================================================================
# Conversation compaction (4.B.3) — turn-boundary rolling summary
# ============================================================================
_TOKEN_ENCODER = None  # lazy tiktoken encoder


def _encoder():
    """cl100k_base BPE — bundled with tiktoken (no network fetch). NOTE: this is
    OpenAI's tokenizer and only an APPROXIMATION of the llama/Groq token count.
    That's fine here: the count only feeds a tunable threshold + the context
    meter, nothing that needs to match the model's exact accounting."""
    global _TOKEN_ENCODER
    if _TOKEN_ENCODER is None:
        import tiktoken

        _TOKEN_ENCODER = tiktoken.get_encoding("cl100k_base")
    return _TOKEN_ENCODER


def _msg_text(m: BaseMessage) -> str:
    c = m.content
    return c if isinstance(c, str) else str(c)


def count_message_tokens(messages: list[BaseMessage]) -> int:
    """Approximate token count of a message list (tiktoken ~ llama; see _encoder)."""
    enc = _encoder()
    return sum(len(enc.encode(_msg_text(m))) for m in messages)


def split_for_compaction(
    messages: list[BaseMessage], keep_recent_tokens: int
) -> tuple[list[BaseMessage], list[BaseMessage]]:
    """(to_summarize=oldest, keep=most-recent within keep_recent_tokens). Walks
    from the newest accumulating tokens; everything past the keep window is
    summarized. Returns ([], all) when the whole history fits the keep window."""
    enc = _encoder()
    used = 0
    kept = 0
    for m in reversed(messages):
        t = len(enc.encode(_msg_text(m)))
        if used + t > keep_recent_tokens and kept > 0:
            break
        used += t
        kept += 1
    split = len(messages) - kept
    return messages[:split], messages[split:]


_SUMMARY_PROMPT = """You maintain a rolling summary of an ongoing conversation between a user and their AI assistant, so older turns can be dropped from the context window without losing the thread.

Update the summary to fold in the new earlier turns below. Preserve the CONVERSATIONAL THREAD — what was discussed, asked, decided, and any open threads or the user's intent — in a few tight paragraphs. Specific durable facts are stored separately in long-term memory, so do NOT try to capture every fact exhaustively; focus on continuity so the assistant can pick up naturally. Write in third person ("The user asked…", "The assistant…").

EXISTING SUMMARY:
{existing}

NEW EARLIER TURNS TO FOLD IN:
{conversation}

Return ONLY the updated summary text."""


def _convo_role(m: BaseMessage) -> str:
    if isinstance(m, HumanMessage):
        return "User"
    if isinstance(m, AIMessage):
        return "Assistant"
    if isinstance(m, ToolMessage):
        return "Tool"
    return "System"


async def _summarize_messages(existing: str, messages: list[BaseMessage]) -> str:
    from app.llm.gateway import llm_gateway

    convo = "\n".join(
        f"{_convo_role(m)}: {_msg_text(m)}" for m in messages if _msg_text(m).strip()
    )
    resp = await llm_gateway.complete(
        messages=[{"role": "user", "content": _SUMMARY_PROMPT.format(
            existing=existing or "(none yet)", conversation=convo)}],
        force_model=settings.COMPACT_MODEL_SLOT,  # fallback (gpt-4o-mini) — off the rate-limited Groq fast tier
        temperature=0.0,
    )
    return (resp["choices"][0]["message"].get("content") or "").strip()


async def compact_node(state: AgentState) -> dict:
    """Turn-boundary compaction. Runs AFTER persist (the turn's response is sent
    and memories are written). If the verbatim history exceeds the threshold,
    summarize the OLDEST messages into running_summary and drop them via
    RemoveMessage, keeping the most recent ~KEEP_RECENT verbatim.

    Safety: best-effort (any failure → no compaction this turn); NEVER drops a
    message without a successful summary; skips a thread mid-approval; only ever
    touches already-completed turns (an interrupted turn pauses before persist, so
    it never reaches this node)."""
    if not settings.COMPACT_ENABLED:
        return {"compacted_last_turn": False}
    messages = state.get("messages") or []
    if count_message_tokens(messages) <= settings.COMPACT_THRESHOLD_TOKENS:
        return {"compacted_last_turn": False}

    # skip-on-approval: don't compact across an unresolved interrupt (an AIMessage
    # tool_call with no answering ToolMessage). Belt-and-suspenders — by topology
    # an interrupted turn never reaches this node anyway.
    last = messages[-1] if messages else None
    if isinstance(last, AIMessage) and getattr(last, "tool_calls", None):
        return {"compacted_last_turn": False}

    to_summarize, _keep = split_for_compaction(messages, settings.COMPACT_KEEP_RECENT_TOKENS)
    # RemoveMessage targets by id — only summarize+drop messages that carry one.
    removable = [m for m in to_summarize if getattr(m, "id", None)]
    if not removable:
        return {"compacted_last_turn": False}

    try:
        new_summary = await asyncio.wait_for(
            _summarize_messages(state.get("running_summary", ""), removable),
            timeout=settings.COMPACT_TIMEOUT_S,
        )
    except Exception as exc:  # noqa: BLE001 — never drop a message without a successful summary
        logger.warning("compaction_summarize_failed", error=f"{type(exc).__name__}: {exc}")
        return {"compacted_last_turn": False}
    if not new_summary:
        return {"compacted_last_turn": False}

    logger.info(
        "conversation_compacted",
        dropped=len(removable),
        kept_verbatim=len(messages) - len(removable),
        summary_chars=len(new_summary),
    )
    return {
        "running_summary": new_summary,
        "messages": [RemoveMessage(id=m.id) for m in removable],
        "compacted_last_turn": True,
    }


# ============================================================================
# Conditional edge after agent_node — tool_executor or persist?
# ============================================================================
def should_continue(state: AgentState) -> str:
    """Routing function for the agent → ? edge."""
    last = state["messages"][-1] if state["messages"] else None
    if isinstance(last, AIMessage) and last.tool_calls:
        return "tool_executor"
    return "persist"


# ============================================================================
# Internal helpers
# ============================================================================
def _describe_action(tool_name: str, tool_args: dict) -> str:
    """Human-readable description for approval messages."""
    args_pretty = json.dumps(tool_args, indent=2, default=str)
    return f"Execute `{tool_name}` with arguments:\n```json\n{args_pretty}\n```"


async def _approval_warning(tool_name: str, tool_args: dict) -> str | None:
    """Pre-approval enrichment surfaced in the master's Approve/Reject prompt.

    Today only calendar_create (a named conflict check). Keyed on tool_name so a
    second enricher is a one-line add here, not an if-ladder in the APPROVE
    branch. Best-effort by contract — the enricher itself fails open (returns
    None) so a check failure never blocks the approval."""
    if tool_name == "calendar_create":
        from app.agent.tools.calendar_tool import calendar_conflict_warning
        return await calendar_conflict_warning(
            tool_args.get("start_iso", ""), tool_args.get("end_iso", ""),
        )
    return None


def _pre_approve_error(tool_name: str, tool_args: dict) -> str | None:
    """BLOCKING pre-queue validation for APPROVE-tier tools — return an agent-facing error
    string to REFUSE queuing (so the agent reads it and asks the master to fix the input),
    or None to proceed. Keyed on tool_name; the validation logic lives WITH the tool. Catches
    bad input (e.g. a placeholder recipient the LLM emitted) BEFORE a card the master can only
    reject is minted. Distinct from _approval_warning, which is a non-blocking card enricher."""
    if tool_name == "email_send":
        from app.agent.tools.email_send import validate_recipient
        return validate_recipient(tool_args.get("to", ""))
    return None


async def _find_pending_approval(thread_id: str, interrupt_id: str) -> uuid.UUID | None:
    """Return the id of an existing PendingApproval for this interrupt_id, else None.

    The APPROVE branch re-runs from the top on every resume (``interrupt()``
    doesn't commit the node's partial return), so without this check each resume
    created a fresh PendingApproval row AND re-pinged the master — the duplicate-
    prompt bug (27 rows for ~14 requests in the Jun-11 test). ``interrupt_id`` is
    the tool_call_id, unique per tool call, so a row's existence (ANY status —
    it may already be approved/rejected by the time we re-run) means we've
    already created + sent for it. Scoped by thread_id to use that index."""
    async with async_session() as session:
        result = await session.execute(
            select(PendingApproval.id)
            .where(
                PendingApproval.thread_id == thread_id,
                PendingApproval.interrupt_id == interrupt_id,
            )
            .limit(1)
        )
        row = result.first()
        return row[0] if row else None


async def _discard_pending_approval(thread_id: str, interrupt_id: str) -> None:
    """Mark a proposal superseded by an edit (status='discarded'). The row stays
    so the dashboard renders the card greyed in history — a record of what was
    proposed before the master asked for the change."""
    async with async_session() as session:
        await session.execute(
            update(PendingApproval)
            .where(
                PendingApproval.thread_id == thread_id,
                PendingApproval.interrupt_id == interrupt_id,
                PendingApproval.status == "pending",
            )
            .values(
                status="discarded",
                resolved_at=datetime.now(UTC),
                resolved_via="web",
            )
        )
        await session.commit()
    logger.info("approval_discarded", thread_id=thread_id, interrupt_id=interrupt_id)


async def _create_pending_approval(
    thread_id: str,
    interrupt_id: str,
    tool_name: str,
    tool_args: dict,
) -> uuid.UUID:
    async with async_session() as session:
        approval = PendingApproval(
            thread_id=thread_id,
            interrupt_id=interrupt_id,
            action_type=tool_name,
            description=_describe_action(tool_name, tool_args),
            payload={"tool_name": tool_name, "tool_args": tool_args},
            expires_at=(
                datetime.now(UTC)
                + timedelta(hours=settings.APPROVAL_EXPIRY_HOURS)
            ),
        )
        session.add(approval)
        await session.commit()
        await session.refresh(approval)
        return approval.id


async def _archive_tool_result(
    thread_id: str,
    tool_name: str,
    tool_call_id: str,
    full_result: str,
) -> uuid.UUID:
    async with async_session() as session:
        archive = ToolResult(
            thread_id=thread_id,
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            full_result=full_result,
            summary=full_result[:500],
            char_count=len(full_result),
        )
        session.add(archive)
        await session.commit()
        await session.refresh(archive)
        return archive.id


async def _log_audit(
    thread_id: str,
    tool_name: str,
    level: SafetyLevel,
    args: dict,
    success: bool,
    error: str | None = None,
    latency_ms: int | None = None,
) -> None:
    """Best-effort audit row. Never propagate logging failures into the agent path.

    ``latency_ms`` is set only on rows that actually dispatched a tool (the
    execution path); the rate-limited / blocked / rejected rows leave it None —
    they have no execution to time."""
    try:
        async with async_session() as session:
            session.add(
                AuditTrail(
                    thread_id=thread_id,
                    action=f"{tool_name}({list(args.keys())})",
                    tool_name=tool_name,
                    safety_level=level.value,
                    input_summary=str(args)[:500],
                    success=success,
                    error=error,
                    latency_ms=latency_ms,
                )
            )
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.error("audit_log_failed", error=str(exc))
