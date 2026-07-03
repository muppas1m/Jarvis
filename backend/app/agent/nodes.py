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
import re
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

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

from app.agent.message_repair import (
    repair_orphaned_tool_calls,
    strip_divergent_tool_call_residue,
)
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
    update = {
        "user_profile_always_on": context["user_profile_always_on"],
        "user_profile_on_demand": context["user_profile_on_demand"],
        "relevant_memories": context["relevant_memories"],
        "briefing_directive": directive,
        "briefing_proactive": proactive,
        "briefing_offer": offer,
    }

    # D22 durable heal — THE single checkpoint-load point (every turn on all 3 surfaces
    # starts here). Any committed AIMessage carrying malformed/divergent tool-call residue
    # (llama's parse-failed call in invalid_tool_calls / additional_kwargs — the shape that
    # bricked web:master) is replaced IN THE CHECKPOINT via an add_messages same-id update,
    # so no downstream consumer ever sees it and the thread heals itself at turn start.
    # Healthy ak-mirrors of real parsed tool_calls are untouched (strip is divergent-only).
    healed = [
        fixed
        for m in (state.get("messages") or [])
        if (fixed := strip_divergent_tool_call_residue(m)) is not None
    ]
    if healed:
        logger.warning(
            "thread_poison_healed",
            thread_id=state.get("thread_id"),
            count=len(healed),
            message_ids=[m.id for m in healed],
        )
        update["messages"] = healed
    return update


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


# --------------------------------------------------------------------------- #
# #3 draft-email backstop — force the email_send call when the model describes  #
# an email as prose instead of calling the tool (the describe-instead-of-call   #
# drop, silent in voice). Detection is deliberately tight (a clear "draft/write/#
# send an email to X" imperative + an email-shaped reply) so soft "what would   #
# you say?" prose isn't caught.                                                 #
# --------------------------------------------------------------------------- #
# Genuine "send/draft an EMAIL to a recipient" intent = an explicit email token + a compose/send
# verb (or "email" used AS the verb) + a recipient marker. Requiring the word "email" is deliberate:
# a bare "message"/"note" may be a non-email channel (whatsapp/SMS), and forcing an email card there
# would be wrong — so the backstop scopes to email-send-to-a-recipient only.
# Email-COMPOSE intent (channel-scoped). Email-NATIVE verbs (reply / respond / get back to) are
# email on their own — that's the most common email action ("reply to Priya"). Channel-AMBIGUOUS
# verbs (draft / write / send / …) need an email token OR an @-address, so "send a message to Bob"
# (whatsapp/SMS) stays out. Used to GATE the backstop on a recent compose context — NOT to guess
# intent from the latest message alone (the email-shaped RESPONSE is the primary signal below).
_EMAIL_NATIVE_VERB = re.compile(r"\b(reply|respond|get\s+back|write\s+back|circle\s+back)\b", re.IGNORECASE)
_AMBIGUOUS_COMPOSE_VERB = re.compile(
    r"\b(draft|write|compose|send|shoot|fire\s+off|pen|forward)\b", re.IGNORECASE
)
_EMAIL_TOKEN = re.compile(r"\be-?mails?\b", re.IGNORECASE)
_AT_ADDRESS = re.compile(r"[^\s@]+@[^\s@]+\.[^\s@]+")
_EMAIL_AS_VERB = re.compile(r"\be-?mail\s+(to\b|him\b|her\b|them\b|[^\s@]+@)", re.IGNORECASE)

# Doctrine exceptions where PROSE is the RIGHT answer, so the backstop must NOT force a card:
#   see-only — prompts.py: the card is the review surface EXCEPT when the master asks to see the
#   text without sending ("just show me a draft, don't do anything");
#   meta/how-to — "how do I write a formal email?" wants an explanation, not an email.
_SEE_ONLY = re.compile(
    r"\b(do\s*n'?t\s+(send|actually\s+send|do\s+anything|deliver|fire)"
    r"|without\s+(actually\s+)?sending"
    r"|just\s+show\s+me|show\s+me\s+(the|a|what)|let\s+me\s+see"
    r"|see\s+(the|a)\s+(draft|text|wording)|preview\s+(it|the)|don'?t\s+queue)\b",
    re.IGNORECASE,
)
_META_HOWTO = re.compile(
    r"\b(how\s+(do|should|would|could|can|to)\b|how'?s\s+the\s+best"
    r"|what'?s?\s+(a|the)\s+(good|best|right|proper)\s+way"
    r"|explain\s+how|teach\s+me|tips?\s+(for|on)|advice\s+on|example\s+of\s+a)\b",
    re.IGNORECASE,
)
# Email-SHAPED reply = the PRIMARY drop signal. A Subject: line (whatsapp/SMS have none), OR a
# salutation AND a formal sign-off (a casual "hi Bob, running late" has a salutation but no formal
# sign-off, so it doesn't qualify). This is what a drafted email looks like regardless of phrasing.
_SUBJECT_LINE = re.compile(r"^\s*subject\s*:", re.IGNORECASE | re.MULTILINE)
_SALUTATION = re.compile(r"\b(dear|hi|hello|hey)\b[^,\n]{0,30},", re.IGNORECASE)
_SIGNOFF = re.compile(
    r"\b(best|best regards|kind regards|warm regards|regards|sincerely|thanks|thank you|"
    r"cheers|yours( truly| sincerely)?|respectfully)\b\s*,?\s*\n",
    re.IGNORECASE,
)
_DRAFT_BACKSTOP_NUDGE = (
    "You wrote that email as chat text instead of calling the email_send tool. The master "
    "cannot review, approve, or send a draft that isn't on an approval card. Call email_send "
    "NOW with to, subject, and body filled in from the draft you just wrote. If you don't have "
    "the recipient's email address, ask the master for it — do not invent one."
)


def _is_email_compose_intent(text: str) -> bool:
    """Channel-scoped compose intent. Email-native verbs (reply/respond/get back) are email on
    their own; ambiguous verbs (draft/write/send) need an email token or an @-address; "email X"
    counts. So "reply to Priya" → True, "send a message to Bob" → False."""
    t = text or ""
    if _EMAIL_NATIVE_VERB.search(t) or _EMAIL_AS_VERB.search(t):
        return True
    return bool(_AMBIGUOUS_COMPOSE_VERB.search(t)) and bool(_EMAIL_TOKEN.search(t) or _AT_ADDRESS.search(t))


def _is_email_shaped(text: str) -> bool:
    # Subject: line, OR salutation + a formal sign-off. A casual "Hi Sir, …" (salutation only) or a
    # plain answer never qualifies, so a normal reply isn't mistaken for a drafted email.
    t = text or ""
    if _SUBJECT_LINE.search(t):
        return True
    return bool(_SALUTATION.search(t)) and bool(_SIGNOFF.search(t))


# A1 Fix 4 — the agent, following the [QUEUED] marker's instruction, often relays "I've queued it for
# your approval" itself. When queued_finish then appends the deterministic read-back, that would ack
# the queue TWICE. This detects such an ack so the preserved content collapses to the read-back only.
# FIRST alt = the primary ack the marker instructs ("I've queued it … for approval"); the [^.?!] guard
# keeps it from spanning into an unrelated later sentence. SECOND alt = the card-STATE phrasings
# ("awaiting/pending your approval"). Deliberately NOT a bare "for approval" — that over-matches a
# genuine remainder ("the board needs the budget for approval") and would make queued_finish silently
# DROP real content (the review-caught Fix-4 hole).
_QUEUE_ACK = re.compile(
    r"\bqueued\b[^.?!]{0,80}?\bapprov|\b(?:awaiting|pending)\s+(?:your\s+)?approval\b",
    re.IGNORECASE,
)


def _is_queue_ack(text: str) -> bool:
    """True when the text is a 'queued it for your approval' ack — so the read-back doesn't double-say
    it. A genuine compound remainder ('2 plus 2 is 4', 'the budget needs approval') → False (it must
    NOT collapse real content; the double-ack is the only thing this suppresses)."""
    return bool(_QUEUE_ACK.search(text or ""))


def _in_compose_email_context(state: AgentState, k: int = 4) -> bool:
    """Did the master express email-compose intent in the current OR a recent prior turn? Scanning
    the recent user turns is what catches the multi-turn follow-up drop ("okay send it" / "bob@x.com"
    after "send an email to my manager") — those follow-ups aren't compose imperatives themselves."""
    if _is_email_compose_intent(state.get("user_message", "")):
        return True
    seen = 0
    for m in reversed(state.get("messages", []) or []):
        if isinstance(m, HumanMessage) and isinstance(m.content, str):
            if _is_email_compose_intent(m.content):
                return True
            seen += 1
            if seen >= k:
                break
    return False


def _is_draft_email_drop(state: AgentState, response: AIMessage) -> bool:
    """The describe-instead-of-call drop. PRIMARY signal: an email-SHAPED reply (Subject line, or
    salutation + formal sign-off — whatsapp/SMS lack these). Gated by: NOT see-only/meta on the
    latest turn (prose is right there), AND a recent email-COMPOSE context. Response-shape-first
    catches reply phrasing AND the multi-turn follow-up drop, and won't fire on a non-email channel."""
    if not (isinstance(response, AIMessage) and isinstance(response.content, str)):
        return False
    if not _is_email_shaped(response.content):
        return False
    current = state.get("user_message", "") or ""
    if _SEE_ONLY.search(current) or _META_HOWTO.search(current):
        return False  # the master wants to SEE the text / asked how-to — prose is right
    return _in_compose_email_context(state)


def _append_queue_offer(response: AIMessage) -> AIMessage:
    """Make the non-completion explicit (never a silent drop) when the retry still didn't call."""
    content = response.content if isinstance(response.content, str) else str(response.content)
    offer = (
        "\n\n(I've written that draft above but haven't queued it for your approval yet — "
        "say the word and I'll send it, Sir.)"
    )
    return response.model_copy(update={"content": content + offer})


async def _draft_email_backstop(
    state: AgentState, response: AIMessage, llm: Any, msgs: list[BaseMessage]
) -> AIMessage:
    """If the model described an email instead of calling email_send, force the call ONCE via a
    re-prompt (not prose-parsing). On success the retry's email_send tool_call REPLACES the prose
    (the card is the review surface); if it still drops, append an explicit offer — never silent."""
    if getattr(response, "tool_calls", None):
        return response
    if not _is_draft_email_drop(state, response):
        return response

    logger.info("draft_email_backstop_retry", thread_id=state.get("thread_id"))
    retry = await llm.ainvoke([*msgs, response, HumanMessage(content=_DRAFT_BACKSTOP_NUDGE)])
    if isinstance(retry, AIMessage) and isinstance(retry.content, str):
        retry = retry.model_copy(update={"content": strip_function_leak(retry.content)})
    if getattr(retry, "tool_calls", None):
        return retry  # it called email_send → a card queues this turn

    logger.info("draft_email_backstop_still_dropped", thread_id=state.get("thread_id"))
    return _append_queue_offer(response)


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
    # Presented-card context (Step A): card_resolution_node routed a card QUESTION here.
    # Give the agent the referent so it answers about THIS card (D3), not a different one,
    # and can briefly note it's still awaiting approval if the message was off-topic.
    card_context = (state.get("card_context") or "").strip()
    if card_context:
        msgs.append(SystemMessage(content=(
            "[The master is viewing a pending approval card. " + card_context +
            " If their latest message is ABOUT this card, answer about THIS specific item; "
            "if it's a new topic, answer it and you may briefly note the card is still "
            "awaiting their approval. Do NOT approve or send anything yourself — the master "
            "decides via the card.]"
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

    # D22 mint guard (belt-and-suspenders behind FallbackChatLLM's shape-3 re-issue): if the
    # SURVIVING response still carries malformed tool-call residue (both models malformed — the
    # re-issue is bounded to one), strip it BEFORE it can persist and poison the thread. The
    # trpv0ek1t brick was exactly this shape reaching the checkpoint. D23 floor: a stripped
    # response with no tool_calls and no content must never persist as a silent BLANK reply.
    if isinstance(response, AIMessage):
        stripped = strip_divergent_tool_call_residue(response)
        if stripped is not None:
            logger.warning(
                "agent_response_invalid_toolcalls_stripped",
                invalid_ids=[_tc_id for tc in (response.invalid_tool_calls or [])
                             if (_tc_id := (tc.get("id") if isinstance(tc, dict) else None))],
            )
            response = stripped
            if not response.tool_calls and not (
                response.content if isinstance(response.content, str) else ""
            ).strip():
                h = settings.MASTER_HONORIFIC
                response = response.model_copy(update={"content": (
                    f"I couldn't produce a proper response there, {h} — "
                    f"could you say that again?"
                )})

    # #3 — force a card when the model described an email instead of calling email_send.
    if isinstance(response, AIMessage):
        response = await _draft_email_backstop(state, response, llm, msgs)

    has_tool_calls = bool(getattr(response, "tool_calls", None))
    # Mark that the agent has run this turn so the once-per-turn hourly rate check (above) is NOT
    # re-run on later agent passes. (state.py field was read but never written → the check ran on
    # EVERY pass, over-counting the cap.) Reset to 0 in each turn's initial_state.
    update: dict = {"messages": [response], "tool_calls_this_turn": (state.get("tool_calls_this_turn") or 0) + 1}
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

# A1 (natural loop) — the NO_PROGRESS marker: a re-emit of an action ALREADY queued this turn (L0
# signature hit) OR a reused row (already-queued / content-dedup) — NO new card was minted. Distinct
# from QUEUED_MARKER_TAG so `should_continue_tools` can tell "a fresh card was queued" from "nothing
# new happened", and so the runner does NOT re-surface a duplicate card event on a re-emit
# (`_queued_approval_event` keys on QUEUED_MARKER_TAG). It is a VERBATIM-re-emit guard only — the
# structural drift defense is that a pure-queue round ends the turn (no continuation pass to drift in),
# NOT this marker (do not turn it into a drift-catching dedup — that would re-break two-emails-to-Bob).
NO_PROGRESS_TAG = "[ALREADY_QUEUED]"
_NO_PROGRESS_MARKER = (
    NO_PROGRESS_TAG + " The `{tool}` action was ALREADY queued for the master's approval earlier "
    "this turn — no new card was created. Tell the master it's already queued; do NOT re-queue it."
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
        #
        # L0 (in-turn idempotency guard): the SAME action re-emitted THIS turn (a NEW tool_call_id)
        # returns the existing [QUEUED] — no new card, no re-ping — IN FRONT of the durable DB
        # dedups below (additive, never a replacement; on a mid-turn crash the in-memory set is
        # lost but the DB content-dedup at _find_pending_approval_by_content still catches it).
        sigs = list(state.get("queued_signatures") or [])
        sig = _queue_signature(tool_name, tool_args)
        if sig in sigs:
            # VERBATIM re-emit of an action already queued THIS turn → NO_PROGRESS (no new card, no
            # re-ping). Its card is already in queued_this_turn (recorded when first queued this turn,
            # since queued_signatures is turn-reset → a sig-hit can only be same-turn). A1: this makes
            # a pure-re-emit round terminate at should_continue_tools instead of routing back.
            logger.info("queued_signature_hit_skip", thread_id=thread_id, tool_name=tool_name)
            await _log_audit(thread_id, tool_name, level, tool_args, success=False, error="QUEUED_DEDUP")
            return {"messages": [ToolMessage(
                content=_NO_PROGRESS_MARKER.format(tool=tool_name), tool_call_id=tool_call_id)]}

        minted_new = False   # A1: True ONLY when a NEW card row is created (the else branch) → the
        #                      progress signal that keeps QUEUED distinct from NO_PROGRESS.
        approval_id = await _find_pending_approval(thread_id, interrupt_id=tool_call_id)
        if approval_id is not None:
            logger.info(
                "approval_already_queued_skip_duplicate",
                thread_id=thread_id, interrupt_id=tool_call_id, tool_name=tool_name,
            )
        elif (dup := await _find_pending_approval_by_content(thread_id, tool_name, tool_args)) is not None:
            # Content dedup (defense-in-depth): the SAME un-resolved action under a NEW tool_call_id
            # must NOT mint a second card or re-ping (the 5-identical-cards bug). Reuse the row.
            approval_id = dup
            logger.info(
                "approval_duplicate_content_skip",
                thread_id=thread_id, tool_name=tool_name,
            )
        else:
            minted_new = True
            # Liveness: a re-queued REVISION of the same email (same recipient+subject)
            # supersedes the prior pending card, so the queue doesn't stack stale duplicates
            # (the D15 duplicate-target trigger). Gentle — different-subject emails survive.
            await _supersede_prior_email_card(thread_id, tool_name, tool_args)
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
        # Audit the QUEUE event (not an execute — the tool has NOT run).
        await _log_audit(
            thread_id, tool_name, level, tool_args, success=False,
            error="QUEUED" if minted_new else "QUEUED_DEDUP",
        )
        # A1 marker split: a NEW card → QUEUED (progress); a reused row → NO_PROGRESS (no new card),
        # so should_continue_tools can tell a fresh queue from a re-emit and the runner doesn't
        # re-surface a duplicate card event. Fixes 2+3: record the row PK in queued_this_turn on
        # EVERY branch (fresh OR reused) — read-prior-accumulate (never a bare overwrite, or a
        # two-APPROVE round drops the first card from the read-back) — so the deterministic read-back
        # NAMES every card touched this turn, even the deduped ones.
        marker = _QUEUED_MARKER if minted_new else _NO_PROGRESS_MARKER
        return {
            "messages": [
                ToolMessage(
                    content=marker.format(tool=tool_name),
                    tool_call_id=tool_call_id,
                )
            ],
            "queued_signatures": sigs + [sig],  # L0: record so a re-emit this turn is deduped
            "queued_this_turn": list(state.get("queued_this_turn") or []) + [str(approval_id)],
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
    """Routing after `tool_executor` (A1 — the natural agentic loop):
      - unprocessed tool calls remain in the latest round → loop back to drain them;
      - the round carries a genuine SAFE-read/execute result the agent must synthesize → `agent`
        (the loop runs naturally — a real N-part compound with a read completes);
      - the round carries NOTHING to consume (every result is a queue marker — fresh `[QUEUED]`
        and/or `[ALREADY_QUEUED]`) → END the turn (`queued_finish`).

    The RULE is "nothing to consume ends the turn", not "no progress ends the turn": a fresh
    `[QUEUED]` IS progress, but the turn ends because there is nothing for the agent to react to.
    Ending a pure-queue round is the STRUCTURAL drift defense against the 5-duplicate-cards bug —
    with no continuation pass, a weak model gets no round in which to drift-re-emit a near-duplicate
    card. (The marker split only catches VERBATIM re-emits via L0; the loop-kill floor catches
    drift. Do NOT loosen the dedup to catch drift — that re-breaks two-different-emails-to-Bob.)
    A MIXED round (SAFE read + APPROVE queue) has a non-queue result → `agent`; the queued card is
    still named at termination via `queued_this_turn` (the mixed-round read-back A1 adds)."""
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
    if pending:
        return "tool_executor"

    round_ids = {tc["id"] for tc in last_ai_msg.tool_calls}
    round_results = [
        m for m in state["messages"]
        if isinstance(m, ToolMessage) and m.tool_call_id in round_ids
    ]
    if round_results and all(_is_queue_marker(m) for m in round_results):
        return "queued_finish"   # nothing to consume → end the turn (safety floor + re-emit spin)
    return "agent"               # a read/execute result to synthesize (or an odd empty round)


def _is_queue_marker(m: BaseMessage) -> bool:
    """A1 — a ToolMessage that parked an approval (fresh [QUEUED]) or re-emitted an already-queued
    one ([ALREADY_QUEUED]): nothing for the agent to consume. Anything else (a SAFE-read/execute
    result, an error) is consumable → routes back to the agent."""
    content = getattr(m, "content", None)
    return isinstance(content, str) and (
        content.startswith(QUEUED_MARKER_TAG) or content.startswith(NO_PROGRESS_TAG)
    )


def _minted_new_this_turn(messages: list) -> bool:
    """D24 — did THIS turn mint a NEW approval card? The A1 marker split encodes it in the
    round's ToolMessages: a fresh mint returns `[QUEUED]`; every dedup branch (L0 sig-hit /
    already-queued / content-dedup) returns `[ALREADY_QUEUED]`. Reversed scan bounded at this
    turn's HumanMessage (the Fix-1 boundary), so a PRIOR turn's mint never counts."""
    for m in reversed(messages or []):
        if isinstance(m, HumanMessage):
            break
        if isinstance(m, ToolMessage) and isinstance(m.content, str) \
                and m.content.startswith(QUEUED_MARKER_TAG):
            return True
    return False


async def _readback_for_queued(row_ids: list, h: str, minted_new: bool = True) -> str:
    """L1 — the DETERMINISTIC read-back (the GUARANTEE, not the LLM prose): NAME the approval cards
    TOUCHED this turn (`queued_this_turn` — row PKs), fetched by id. describe_card gives "an email to
    X about 'Y'" / the humanized tool action. Never depends on the model, so D1 stays fixed on the
    llama primary REGARDLESS of the new termination. Falls back to a generic ack if the rows can't be
    read. (A1 keys on the row PK, not the tool_call_id, so the read-back fires from ANY terminal round
    — the pure-queue terminate AND the mixed-round natural-answer path — not only the queuing round.
    De-dups + preserves queue order; a same-card id can appear twice when a content-dedup re-emit
    re-records it.)

    D24 (the yes-trap): the inviting tail ("— shall I go ahead?") SOLICITS consent — one committed
    "yes" dispatches. That's right after a fresh mint, and an amplifier after a dedup-only round
    (the master may have just REFUSED this very action; the re-emit that hit the dedup must not
    re-offer it). `minted_new=False` → a non-soliciting acknowledgment instead. The full stateful
    disambiguation is B1 — this is only the amplifier removal."""
    import uuid as _uuid

    from app.approvals_service import describe_card, to_unified_card
    if not row_ids:
        return (f"I've queued it for your approval, {h}." if minted_new
                else f"That's already queued awaiting your approval, {h}.")
    try:
        pks = []
        for rid in row_ids:
            try:
                pks.append(rid if isinstance(rid, _uuid.UUID) else _uuid.UUID(str(rid)))
            except (ValueError, AttributeError, TypeError):
                continue
        async with async_session() as session:
            rows = (await session.execute(
                select(PendingApproval).where(PendingApproval.id.in_(pks))
            )).scalars().all()
        by_id = {str(r.id): r for r in rows if r.status == "pending"}
        seen: set[str] = set()
        cards = []
        for rid in row_ids:                    # preserve queue order; the id-IN result is unordered
            key = str(rid)
            if key in seen or key not in by_id:
                continue
            seen.add(key)
            cards.append(to_unified_card(by_id[key]))
    except Exception as exc:  # noqa: BLE001 — never break the turn on the read-back fetch
        logger.warning("readback_fetch_failed", error=str(exc))
        cards = []
    if not cards:
        return (f"I've queued it for your approval, {h}." if minted_new
                else f"That's already queued awaiting your approval, {h}.")
    phrases = [describe_card(c) for c in cards]
    if len(phrases) == 1:
        joined = phrases[0]
    elif len(phrases) == 2:
        joined = f"{phrases[0]} and {phrases[1]}"
    else:
        joined = "; ".join(phrases[:-1]) + f"; and {phrases[-1]}"
    if minted_new:
        return f"I've queued {joined} for your approval, {h} — shall I go ahead?"
    verb = "is" if len(phrases) == 1 else "are"
    return f"{joined[0].upper()}{joined[1:]} {verb} already queued awaiting your approval, {h}."


async def queued_finish_node(state: AgentState) -> dict:
    """A1 terminal node — the deterministic LOOP TERMINATOR (kept) AND the D1 read-back, now fired
    from BOTH terminal paths: a pure-queue round (`should_continue_tools`) AND a natural answer with
    cards queued this turn (`should_continue`). The read-back NAMES the cards via `queued_this_turn`
    (row PKs), model-independent — so D1 survives the new termination on the weak llama.

    A GENUINE non-queue answer (a compound's other half, e.g. "…and what's 2+2", or the mixed-round
    natural answer) is PRESERVED with the read-back appended — but NOT email-shaped prose (the card
    IS the draft) and NOT a bare queue-ack (else the ack + the read-back say the same thing twice —
    Fix 4). The read-back is APPENDED as its OWN AIMessage (constraint #3 — never rewrite the agent's
    tool_calls message → no orphaned tool_call)."""
    h = settings.MASTER_HONORIFIC
    # D24: solicit consent ONLY when this turn minted a NEW card. A dedup-only round (pure
    # [ALREADY_QUEUED] — e.g. a re-emit right after the master tried to REJECT this action)
    # gets a non-soliciting acknowledgment — never a fresh "shall I go ahead?" offer.
    read_back = await _readback_for_queued(
        list(state.get("queued_this_turn") or []), h,
        minted_new=_minted_new_this_turn(state.get("messages") or []),
    )

    # The genuine answer to preserve: the natural answer (final_response — set by agent_node on a
    # no-tool-call terminal, turn-reset so never stale) else the last content-bearing AIMessage of
    # THIS turn (stop at this turn's HumanMessage so a prior turn's answer never leaks in — Fix 1).
    content = (state.get("final_response") or "").strip()
    if not content:
        for m in reversed(state.get("messages") or []):
            if isinstance(m, HumanMessage):
                break                          # reached this turn's user message — don't walk prior turns
            if isinstance(m, AIMessage) and isinstance(m.content, str) and m.content.strip():
                content = m.content.strip()
                break
    # Fix 4 — keep the preserved content only if it's a GENUINE remainder: not email-shaped prose
    # (the card holds it) and not itself a "queued for approval" ack (the deterministic read-back is
    # the single canonical ack).
    keep = bool(content) and not _is_email_shaped(content) and not _is_queue_ack(content)
    final = f"{content}\n\n{read_back}" if keep else read_back
    return {"messages": [AIMessage(content=read_back)], "final_response": final}


# ============================================================================
# Node 1b — card_resolution (Step A — presented-card interactions THROUGH the graph)
# ============================================================================
async def _card_edit_redraft(judged: Any, message: str, resolved_via: str = "web") -> dict:
    """Edit re-draft INSIDE the graph: claim-gated discard → revise → re-queue a NEW card.
    Mirrors runner._revise_presented_card's core but returns STATE — the runner emits the
    decision_resolved(discarded) + the new approval_required card from `card_outcome`. The
    master's words are already in `messages` (the turn's HumanMessage), so we add only the
    confirmation AIMessage; the checkpoint persists the negotiation (kills D2 for edits too)."""
    from app.api.approvals import resolve_approval
    from app.agent.runner import _requeue_revised_email
    from app.email.responder import revise_draft

    h = settings.MASTER_HONORIFIC
    aid = judged.approval_id
    # Carry the CARD's thread_id (not the conversation thread) into card_outcome so the
    # decision_resolved event matches the old path exactly. For a chat card they're equal;
    # for a CROSS-THREAD inbound-email card they differ — the old runner path emitted
    # row.thread_id, so omitting it was a divergence. (The frontend greys by approval_id, so
    # this is cosmetic today, but the contract stays faithful for any thread_id consumer.)
    tid = judged.row.thread_id

    # Only an email card with a draft can be revised; a tool card / heads-up → a nudge.
    if not (judged.is_email_card and not judged.needs_drafting):
        nudge = f"I can only send or discard this for now, {h}. Shall I go ahead?"
        return {"messages": [AIMessage(content=nudge)], "final_response": nudge,
                "card_outcome": {"approval_id": aid, "thread_id": tid}, "card_handled": True}

    # 1. Claim-gated discard (pending→discarded) — the SAME atomic claim, so a concurrent
    #    approve can't race it. A lost claim → already resolved → ack. resolved_via threads
    #    the real channel (voice/web) into the audit field instead of a hardcoded "web".
    if await resolve_approval(aid, "discard", resolved_via) is None:
        reply = f"That one's already taken care of, {h}."
        return {"messages": [AIMessage(content=reply)], "final_response": reply,
                "card_outcome": {"approval_id": aid, "decision_status": "stale", "thread_id": tid},
                "card_handled": True}

    payload = judged.row.payload or {}
    change = judged.change or message
    try:
        revised = await revise_draft(
            subject=payload.get("subject", ""), sender=payload.get("sender", ""),
            draft=payload.get("draft", ""), change=change,
        )
        if not (revised or "").strip():
            raise ValueError("empty revised draft")
        card = await _requeue_revised_email(judged.row, revised)
    except Exception as exc:  # noqa: BLE001 — never error the turn / never send
        logger.warning("card_edit_redraft_failed", approval_id=aid, error=str(exc))
        reply = f"I couldn't revise that one, {h} — ask me again and I'll redo it."
        # The old card is already discarded → emit the flip so the UI greys it; no new card.
        return {"messages": [AIMessage(content=reply)], "final_response": reply,
                "card_outcome": {"approval_id": aid, "decision_status": "discarded", "thread_id": tid},
                "card_handled": True}

    reply = f"I've revised that reply, {h} — the new draft is queued for your approval."
    return {"messages": [AIMessage(content=reply)], "final_response": reply,
            "card_outcome": {"approval_id": aid, "decision_status": "discarded",
                             "thread_id": tid, "new_card": card},
            "card_handled": True}


# --------------------------------------------------------------------------- #
# Wrong-card-resolution SEAL (D15/D16) — resolve the AUTHORITATIVE live target,  #
# NOT the (possibly stale, oldest-pending) client presented_approval_id.         #
# --------------------------------------------------------------------------- #
_CARD_KIND_CALENDAR = re.compile(r"\b(calendar|event|meeting|appointment|schedule)\b", re.IGNORECASE)
_CARD_KIND_EMAIL = re.compile(r"\b(e-?mails?|reply|replies)\b", re.IGNORECASE)
_CALENDAR_TOOLS = ("calendar_create", "calendar_update", "calendar_delete")
# Anaphoric / command / filler tokens that DON'T name a specific target. A message made only of
# these is a bare generic command ("send it" / "yes go ahead") → resolve the one live card.
_GENERIC_TOKENS = frozenset({
    "approve", "approved", "approves", "approving", "reject", "rejected", "rejects", "rejecting",
    "send", "sent", "sends", "sending", "discard", "cancel", "cancelled", "confirm", "confirmed",
    "go", "ahead", "do", "done", "it", "this", "that", "the", "one", "yes", "no", "nope", "yeah",
    "yep", "yup", "sure", "ok", "okay", "k", "please", "now", "right", "them", "those", "thing",
    "i", "my", "me", "you", "your", "to", "a", "an", "and", "with", "for", "is", "are", "of", "on",
    "just", "actually", "still", "want", "wanted", "like", "would", "could", "can", "shall", "let",
    "there", "here", "we", "should", "out", "off", "up", "good", "fine", "great",
})


# Kind / action / meta words that describe the CARD'S KIND, not a distinguishing target. Clause (a)
# owns the kind check; these are stripped from clause (b) on BOTH the message and the card referent,
# so a content match is on DISTINGUISHING content only. Otherwise the tool name ("email send") in the
# referent lets a NEW same-kind request ("send an email to bob") match on the bare word "email" — and
# the gate, which must be the BACKSTOP when the judge mis-fires (the llama primary might), would fail.
_KIND_INDICATOR_WORDS = frozenset({
    "calendar", "event", "events", "meeting", "meetings", "appointment", "appointments", "schedule",
    "email", "emails", "mail", "reply", "replies", "send", "sends", "sent", "create", "creates",
    "update", "delete", "draft", "drafts", "card", "approval", "action", "message", "messages",
})


def _card_distinguishing_text(card: Any) -> str:
    """The card's DISTINGUISHING content (recipient / subject / title) with kind/action words removed —
    so a content match is on what identifies THIS card, never on its kind."""
    targs = card.tool_args or {}
    text = " ".join(str(targs.get(k, "")) for k in ("to", "subject", "title")).lower()
    return " ".join(w for w in re.findall(r"[a-z0-9@.]+", text) if w not in _KIND_INDICATOR_WORDS)


def _names_mismatched_target(message: str, card: Any) -> bool:
    """Deterministic count==1 guard (master refinement #1) — refuse when the master NAMES a target
    that doesn't match the single live card; resolve a bare generic command. Code only, NO LLM,
    and errs SAFE (over-refusing just asks). Two clauses:
      (a) a KIND word for a DIFFERENT kind ("approve the calendar event" with one email card) → refuse.
      (b) the message names DISTINGUISHING content (non-generic, non-kind tokens) and NONE of it
          references the card ("approve the boat party" — or a NEW "send an email to bob" — with one
          Fernandes-email card) → refuse. Kind words are excluded here, so a same-kind new request is
          refused on its distinguishing token ("bob"), not matched on "email".
    A message of only generic/anaphoric/kind tokens ("send it" / "yes") → resolve the one card."""
    msg = (message or "").lower()
    is_calendar = card.tool_name in _CALENDAR_TOOLS
    is_email = card.kind == "email"
    # (a) hard kind mismatch
    if _CARD_KIND_CALENDAR.search(msg) and not is_calendar:
        return True
    if _CARD_KIND_EMAIL.search(msg) and not is_email:
        return True
    # (b) distinguishing-content mismatch — significant tokens, minus generic AND kind words
    tokens = [t for t in re.findall(r"[a-z0-9@.]+", msg)
              if len(t) > 2 and t not in _GENERIC_TOKENS and t not in _KIND_INDICATOR_WORDS]
    if not tokens:
        return False  # bare generic → resolve the one card
    referent = _card_distinguishing_text(card)
    return not any(t in referent for t in tokens)  # named a target this card isn't → refuse


def _clean_resolution_reply(outcome: Any, intent: str, target: Any, h: str) -> str:
    """The human reply for a resolved card — NAMES the actual card (D16, not an unconditional
    "Discarded, Sir") and never leaks the raw <tool_output trust="untrusted"> wrapper (D18)."""
    from app.agent.runner import _email_outcome_speech
    from app.agent.sanitizer import unwrap_tool_output
    from app.approvals_service import describe_card

    subj = describe_card(target)
    if intent == "reject":
        return f"Discarded {subj}, {h}."
    # approve
    if outcome.uncertain:
        return f"I tried to send {subj}, {h}, but couldn't confirm it went through."
    if outcome.kind == "tool" and not outcome.success:
        return f"That action failed, {h} — {subj} did not go through."
    if target.tool_name == "email_send":
        to = target.tool_args.get("to") or "the recipient"
        return f"Sent the email to {to}, {h}."
    if outcome.kind == "email" and outcome.email_outcome is not None:
        return _email_outcome_speech(outcome.email_outcome)
    clean = unwrap_tool_output(outcome.detail)
    return f"Done — {clean}, {h}." if clean else f"Done, {h}."


async def _resolve_with_referent_gate(intent: str, message: str, resolved_via: str, h: str, aid: str) -> dict:
    """Layer 0 + Layer 1 — the wrong-card SEAL. Reads the AUTHORITATIVE live APPROVE set and
    resolves ONLY when exactly one target is unambiguous AND it is the card the master was shown:
      - >1 live card → REFUSE + name the choices (never guess which the master meant).
      - the single live card is NOT the presented one (`aid`) → the shown card is gone; ACK stale,
        NEVER substitute a different live card (closes the expiry-race / TOCTOU substitution hole).
      - the single live card IS `aid` but the master's WORDS name a different target → REFUSE.
      - the single live card IS `aid` + a bare/matching command → resolve it.
    Referent selection is deterministic code; the strong judge only classified intent. Both
    approve and reject are sealed; an irreversible action can never resolve a card not referred to."""
    from app.agent.approval_dispatch import resolve_and_dispatch
    from app.approvals_service import describe_card, list_pending_cards

    live = await list_pending_cards()  # pending + unexpired; the queue holds APPROVE-tier only
    verb = "approve" if intent == "approve" else "reject"

    # >1 live → ambiguous → REFUSE + name the choices. NOTHING is resolved.
    if len(live) > 1:
        choices = "; ".join(describe_card(c) for c in live[:5])
        more = f", and {len(live) - 5} more" if len(live) > 5 else ""
        # Point to the buttons, not a question — until the Stage-2 among-many matcher ships, a
        # spoken/typed answer would just refuse again (the gate can't disambiguate from chat).
        reply = (f"You have {len(live)} awaiting your approval, {h}: {choices}{more}. "
                 f"Please tap Approve or Reject on the card you mean — with several pending I can't "
                 f"safely tell which from a chat command yet.")
        logger.info("card_resolution_refused", intent=intent, live=len(live), reason="ambiguous")
        return {"messages": [AIMessage(content=reply)], "final_response": reply, "card_handled": True}

    # 0 live, OR the single live card is NOT the one the master was shown → the shown card is gone;
    # ACK stale and NEVER substitute a different card (the expiry-race / TOCTOU substitution hole).
    if not live or live[0].approval_id != aid:
        reply = f"That one's already taken care of, {h}."
        logger.info("card_resolution_stale_no_substitute", intent=intent, live=len(live))
        return {"messages": [AIMessage(content=reply)], "final_response": reply,
                "card_outcome": {"decision_status": "stale"}, "card_handled": True}

    target = live[0]  # == the presented card, and the ONLY live one
    # The master's WORDS must not name a DIFFERENT target than this card (kind or named content).
    if _names_mismatched_target(message, target):
        reply = (f"The only one awaiting approval is {describe_card(target)}, {h} — that's not what "
                 f"you named. Shall I {verb} that one, or did you mean something else?")
        logger.info("card_resolution_refused", intent=intent, live=1, reason="named_mismatch")
        return {"messages": [AIMessage(content=reply)], "final_response": reply, "card_handled": True}

    outcome = await resolve_and_dispatch(
        target.approval_id, intent, resolved_via, {"approved": intent == "approve"}, ground_thread=False
    )
    if outcome.status == "not_claimed":
        reply = f"That one's already taken care of, {h}."
        return {"messages": [AIMessage(content=reply)], "final_response": reply,
                "card_outcome": {"approval_id": target.approval_id, "decision_status": "stale"},
                "card_handled": True}
    flip = "approved" if intent == "approve" else "rejected"
    reply = _clean_resolution_reply(outcome, intent, target, h)
    logger.info("card_resolution_resolved", approval_id=target.approval_id, intent=intent, status=outcome.status)
    return {"messages": [AIMessage(content=reply)], "final_response": reply,
            "card_outcome": {"approval_id": target.approval_id, "decision_status": flip,
                             "thread_id": outcome.thread_id}, "card_handled": True}


async def card_resolution_node(state: AgentState) -> dict:
    """Step A (L1): presented-card interactions run THROUGH the graph, so they persist
    (kills D2/NV1) and a question about a card gets a REAL agent answer (kills D3).

    When the master is viewing a card (`presented_approval_id` set), judge their message
    against it on the STRONG decision model (`_judge_presented` → `resolve_decision`,
    the consent gate — unchanged), then:
      - approve/reject → `resolve_and_dispatch` (the atomic claim → at-most-once),
        deterministic outcome reply; the runner emits decision_resolved from `card_outcome`.
      - edit          → claim-gated discard → re-draft → re-queue a NEW card.
      - skip          → DB-inert client nav (the row stays pending).
      - stale/gone    → a brief ack.
      - show_others / unclear / unrelated → NOT a resolution → route to the agent as a
        normal, persisted turn, injecting the card context so it answers about THIS card.
    No presented card → straight through to the agent.

    L1 invariants preserved: the strong-model judge + the atomic claim both run here. A graph
    re-process is safe — the claim returns not_claimed on the second pass, so no double-fire."""
    aid = (state.get("presented_approval_id") or "").strip()
    if not aid:
        return {}  # no card → straight to the agent (no-op pass-through)

    from app.agent.runner import _card_context_line, _judge_presented

    h = settings.MASTER_HONORIFIC
    message = state.get("user_message", "") or ""
    resolved_via = state.get("presented_via") or "web"

    # Recent context for the judge, built from in-state history (no DB read needed —
    # the turn's messages are already on the state).
    recent: list[str] = []
    for m in (state.get("messages") or [])[-6:]:
        if isinstance(m, HumanMessage) and isinstance(m.content, str):
            recent.append(f"User: {m.content}")
        elif isinstance(m, AIMessage) and isinstance(m.content, str) and m.content.strip():
            recent.append(f"Assistant: {m.content}")
    recent_context = "\n".join(recent)

    judged = await _judge_presented(aid, message, recent_context)

    # Stale / gone card → brief ack, end the turn (persisted).
    if judged is None:
        ack = f"That one's already taken care of, {h}."
        return {"messages": [AIMessage(content=ack)], "final_response": ack,
                "card_outcome": {"approval_id": aid, "decision_status": "stale"}, "card_handled": True}

    intent = judged.intent

    # Questions (NOT a resolution) → the agent, with the card context so it answers about
    # THIS card (D3) and may note it's still pending. Persisted as a normal turn.
    if intent in ("show_others", "unclear", "unrelated"):
        logger.info("card_resolution_to_agent", approval_id=aid, intent=intent)
        return {"card_context": _card_context_line(judged.row) if judged.row else "",
                "card_handled": False}

    # approve / reject → the wrong-card SEAL (D15/D16). The client `aid` was used ONLY to
    # classify intent above; the RESOLVE TARGET comes from the authoritative live set, and an
    # ambiguous/mismatched command REFUSES (never guesses) — so a stale pointer can never send
    # the wrong card. ground_thread=False: this turn writes the outcome reply itself (no
    # double-write); the row-persist still feeds the HUD.
    if intent in ("approve", "reject"):
        return await _resolve_with_referent_gate(intent, message, resolved_via, h, aid)

    # skip → DB-inert client nav (the row stays pending, reappears on reload).
    if intent == "skip":
        reply = f"Skipped, {h}."
        return {"messages": [AIMessage(content=reply)], "final_response": reply,
                "card_outcome": {"approval_id": aid, "nav": "skip"}, "card_handled": True}

    # edit → claim-gated re-draft (its own helper).
    if intent == "edit":
        return await _card_edit_redraft(judged, message, resolved_via)

    # Unreachable taxonomy gap → safe default: route to the agent.
    return {"card_handled": False}


def route_after_card(state: AgentState) -> str:
    """After card_resolution: a fully-resolved card ends the turn (persist); a question /
    no-card flows to the agent for a normal, persisted turn."""
    return "persist" if state.get("card_handled") else "agent"


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
    """Routing after `agent`:
      - the agent emitted tool_calls → drain them (`tool_executor`);
      - a NATURAL answer (no tool_calls) with cards queued THIS turn → `queued_finish` so the
        deterministic read-back still fires (A1: the mixed-round path — the agent queued in an
        earlier round, consumed a read, and now answers — must still name the queued card, not
        slip straight to persist without a read-back);
      - a natural answer with nothing queued → `persist` (a plain turn)."""
    last = state["messages"][-1] if state["messages"] else None
    if isinstance(last, AIMessage) and last.tool_calls:
        return "tool_executor"
    if state.get("queued_this_turn"):
        return "queued_finish"
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


async def _find_pending_approval_by_content(
    thread_id: str, action_type: str, tool_args: dict
) -> uuid.UUID | None:
    """Content-level dedup (defense-in-depth): the id of an UN-RESOLVED (status='pending')
    PendingApproval for the SAME (thread_id, action_type, tool_args), else None.

    ``_find_pending_approval`` dedups by interrupt_id (the tool_call_id), so it only catches the
    SAME call re-processed. This catches the SAME action re-queued under a NEW tool_call_id — the
    5-identical-cards bug — so an identical action can never queue twice under any re-entrancy.
    Compares tool_args in Python over the (tiny) set of pending rows — robust + index-free."""
    async with async_session() as session:
        rows = (await session.execute(
            select(PendingApproval.id, PendingApproval.payload)
            .where(PendingApproval.thread_id == thread_id)
            .where(PendingApproval.action_type == action_type)
            .where(PendingApproval.status == "pending")
        )).all()
    for row_id, payload in rows:
        if (payload or {}).get("tool_args") == tool_args:
            return row_id
    return None


def _queue_signature(tool_name: str, tool_args: dict) -> str:
    """L0 — the in-turn idempotency key: "the same action re-emitted this turn". Subject-
    discriminated for email (matching supersession's (to, subject) key) so a REGENERATED same
    email dedups but two DISTINCT emails to one recipient in a compound turn both queue;
    (tool, start, title) for calendar; exact-args otherwise. Turn-scoped (AgentState), ADDITIVE
    in front of the durable DB dedups — never a replacement."""
    from email.utils import parseaddr
    if tool_name == "email_send":
        to = parseaddr(tool_args.get("to") or "")[1].strip().lower()
        subj = " ".join((tool_args.get("subject") or "").split()).lower()
        return f"email_send|{to}|{subj}"
    if tool_name == "calendar_create":
        start = (tool_args.get("start_iso") or "").strip()
        title = " ".join((tool_args.get("title") or "").split()).lower()
        return f"calendar_create|{start}|{title}"
    return f"{tool_name}|" + json.dumps(tool_args, sort_keys=True, default=str)


async def _supersede_prior_email_card(thread_id: str, tool_name: str, tool_args: dict) -> int:
    """Liveness hygiene (NOT the safety mechanism — Layer 1's referent gate is): when a REVISED
    draft is re-queued for the same (email_send, recipient, subject), DISCARD the prior pending
    card so the queue doesn't accumulate stale duplicates of one email (E2 supersedes E1 — the
    D15 trigger). Keyed on SUBJECT too, so two genuinely-DIFFERENT emails to the same person
    (different subject) are NOT superseded (master's call: gentle, not a hard uniqueness
    constraint). Scoped to email_send (the observed revision case). Returns # discarded."""
    if tool_name != "email_send":
        return 0
    from email.utils import parseaddr

    def _norm_to(v: str) -> str:  # parse "Name <addr>" → addr so a reformatted revision still matches
        return parseaddr(v or "")[1].strip().lower()

    def _norm_subj(v: str) -> str:
        return " ".join((v or "").split()).lower()

    to = _norm_to(tool_args.get("to"))
    subject = _norm_subj(tool_args.get("subject"))
    if not to:
        return 0
    async with async_session() as session:
        rows = (await session.execute(
            select(PendingApproval).where(
                PendingApproval.thread_id == thread_id,
                PendingApproval.action_type == "email_send",
                PendingApproval.status == "pending",
            )
        )).scalars().all()
        n = 0
        for row in rows:
            targs = (row.payload or {}).get("tool_args") or {}
            if _norm_to(targs.get("to")) == to and _norm_subj(targs.get("subject")) == subject:
                row.status = "discarded"
                row.resolved_at = datetime.now(UTC)
                row.resolved_via = "superseded"
                n += 1
        if n:
            await session.commit()
            logger.info("email_card_superseded", thread_id=thread_id, discarded=n)
    return n


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
