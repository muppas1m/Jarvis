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
import json
import uuid
from datetime import datetime, timedelta, timezone

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_litellm import ChatLiteLLM
from langgraph.types import interrupt

from app.agent.prompts import build_system_prompt
from app.agent.rate_limits import rate_limiter
from app.agent.safety import SafetyClassifier, SafetyLevel
from app.agent.sanitizer import sanitize_tool_result
from app.agent.state import AgentState
from app.config import settings
from app.db.engine import async_session
from app.db.models import AuditTrail, PendingApproval, ToolResult
from app.memory.manager import MemoryManager
from app.utils.exceptions import (
    ApprovalExpiredError,
    CostCapExceededError,
    RateLimitedError,
    SafetyBlockedError,
)
from app.utils.logging import get_logger

logger = get_logger(__name__)

# Heavy singletons — both wrap pool/connection state and shouldn't be built
# per-turn.
memory = MemoryManager()
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
    context = await memory.build_context(user_message=user_message)
    return {
        "user_profile_always_on": context["user_profile_always_on"],
        "user_profile_on_demand": context["user_profile_on_demand"],
        "relevant_memories": context["relevant_memories"],
    }


# ============================================================================
# Node 2 — agent (LLM call with bound tools)
# ============================================================================
def _build_chat_model(tools: list):
    """Build the agent's chat model — primary + fallback wrapped in
    FallbackChatLLM for resilience against Groq rate-limit and
    tool_use_failed errors.

    Both ChatLiteLLM instances are constructed per-turn (cheap; they're
    config objects, not heavy state). Tools are bound to BOTH before
    wrapping, so a fallback fires with the same tool set the primary
    had — agent_node downstream sees structured tool_calls regardless
    of which model produced them.

    Returns a Runnable that mirrors ChatLiteLLM's invoke/ainvoke
    interface; agent_node calls `.ainvoke(messages)` as before.

    See `project_agent_node_bypasses_gateway_fallback.md` for the
    architectural rationale.
    """
    from app.llm.fallback_llm import FallbackChatLLM

    primary = ChatLiteLLM(model=settings.PRIMARY_MODEL, temperature=0.7)
    fallback = ChatLiteLLM(model=settings.FALLBACK_MODEL, temperature=0.7)

    if tools:
        primary = primary.bind_tools(tools)
        fallback = fallback.bind_tools(tools)

    return FallbackChatLLM(primary=primary, fallback=fallback)


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
    selected_tools = await tool_registry.select_relevant_tools(
        query=latest_user_msg,
        top_k=15,
    )

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
        current_datetime=datetime.now(timezone.utc).isoformat(),
    )

    msgs: list[BaseMessage] = [SystemMessage(content=system_prompt)]
    msgs.extend(state["messages"])

    llm = _build_chat_model(selected_tools)
    response = await llm.ainvoke(msgs)

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
# Node 3 — tool_executor (one tool call per invocation; loops via the graph)
# ============================================================================
async def tool_executor_node(state: AgentState) -> dict:
    """Execute exactly ONE pending tool call from the most recent AIMessage.

    Single-call-per-invocation is deliberate. LangGraph's `interrupt()` does
    NOT commit the function's partial return value — it just snapshots state
    and exits. So if we processed multiple tool calls in a loop and hit
    interrupt() halfway, on resume the loop would restart and earlier tool
    calls would re-execute (gmail_send sends twice — catastrophic). Doing one
    call per invocation makes each invocation atomically idempotent: state
    is committed BETWEEN invocations, not within one.

    Routing: `should_continue_tools` after this node loops back here if the
    most recent AIMessage still has un-processed tool calls; otherwise the
    graph routes back to `agent`.

    For each call:
      1. Per-turn rate-limit check.
      2. Safety classification (SAFE / NOTIFY / APPROVE / BLOCKED).
      3. APPROVE → write a PendingApproval row, ping master, interrupt().
      4. Execute the tool (catching JarvisError family for friendly messages).
      5. Sanitize + optionally archive the result.
      6. Audit-log the row.
      7. NOTIFY → ping master that the tool ran.
    """
    # Lazy imports — these modules don't exist as module attributes; the
    # imports run at call time so test patches via `patch.object(...)` work.
    from app.agent.tools.registry import tool_registry
    from app.messaging.failure_alerter import (
        notify_tool_executed,
        send_approval_request_to_master,
    )

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
    ok = await rate_limiter.check_and_increment_tool(thread_id, turn_id, tool_name)
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

    # ---- APPROVE → pause via interrupt --------------------------------------
    if level == SafetyLevel.APPROVE:
        approval_id = await _create_pending_approval(
            thread_id=thread_id,
            interrupt_id=tool_call_id,
            tool_name=tool_name,
            tool_args=tool_args,
        )
        await send_approval_request_to_master(
            approval_id=str(approval_id),
            tool_name=tool_name,
            description=_describe_action(tool_name, tool_args),
        )
        # interrupt() snapshots state and exits. On resume, this same call
        # returns the resume value. Resume payload shape:
        #   {"approved": True}              -> proceed to execution below
        #   {"approved": False, "reason": ...} -> emit a [REJECTED] ToolMessage
        decision = interrupt(
            {
                "type": "approval_required",
                "approval_id": str(approval_id),
                "tool_name": tool_name,
                "tool_args": tool_args,
                "description": _describe_action(tool_name, tool_args),
            }
        )
        if not isinstance(decision, dict) or not decision.get("approved"):
            reason = (decision or {}).get("reason", "rejected by master")
            await _log_audit(
                thread_id, tool_name, level, tool_args,
                success=False, error=f"REJECTED: {reason}",
            )
            return {
                "messages": [
                    ToolMessage(
                        content=f"[REJECTED] Master rejected: {reason}",
                        tool_call_id=tool_call_id,
                    )
                ]
            }
        # Approved — fall through to execution below.

    # ---- execute (SAFE, NOTIFY, or approved-APPROVE) -----------------------
    try:
        raw_result = await tool_registry.execute(tool_name, tool_args)
        success = True
        err: str | None = None
    except RateLimitedError as exc:
        logger.warning("tool_rate_limited", tool=tool_name, error=str(exc))
        raw_result = (
            f"[RATE-LIMITED] Hit hourly cap on `{tool_name}`. Try again later. ({exc})"
        )
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
        raw_result = (
            f"[BUDGET] Daily LLM spend cap reached — `{tool_name}` deferred until tomorrow."
        )
        success = False
        err = f"COST_CAP_EXCEEDED: {exc}"
    except Exception as exc:  # noqa: BLE001 — keep one tool failure from killing the turn
        logger.error("tool_execution_failed", tool=tool_name, error=str(exc))
        raw_result = f"[ERROR] Tool '{tool_name}' failed: {exc}"
        success = False
        err = str(exc)

    # ---- sanitize + archive if oversized -----------------------------------
    sanitized, archived_full = sanitize_tool_result(
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
        sanitized += f"\n[archived:{archive_id}]"

    await _log_audit(thread_id, tool_name, level, tool_args, success=success, error=err)

    if level == SafetyLevel.NOTIFY:
        await notify_tool_executed(thread_id=thread_id, tool_name=tool_name)

    return {
        "messages": [ToolMessage(content=sanitized, tool_call_id=tool_call_id)]
    }


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
    user_msg = state.get("user_message", "")
    final = state.get("final_response", "")
    if user_msg and final and final != "rate_limited":
        try:
            await memory.persist_turn(
                thread_id=state["thread_id"],
                user_message=user_msg,
                assistant_response=final,
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("memory_persist_failed", error=str(exc))
    return {}


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
                datetime.now(timezone.utc)
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
) -> None:
    """Best-effort audit row. Never propagate logging failures into the agent path."""
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
                )
            )
            await session.commit()
    except Exception as exc:  # noqa: BLE001
        logger.error("audit_log_failed", error=str(exc))
