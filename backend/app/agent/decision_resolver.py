"""Natural-language resolution of a pending decision (A2 Piece 2).

Modality-agnostic: text (stream_turn / run_turn) and voice (Piece 3) feed the
SAME judgment. Given the pending action (tool + args + description) and the
master's reply, an LLM classifies intent → approve / reject / edit / skip /
show_others / unrelated. No keyword matching — "yes send it", "looks good",
"actually make it shorter", "use her name Priya", "cancel that", "skip this one",
"what else is pending?" all resolve by understanding, and it generalizes to any
decision type (no per-tool code).

APPROVE is the highest-harm path: a single classification gates a REAL, IRREVERSIBLE
action, so it gets defence-in-depth — the invariant is "an ambiguous acknowledgment
NEVER reaches approve":
  1. It does NOT run on the weakest tier. The fast model (llama-3.1-8b) leaked,
     mis-reading a topic-echo ("right, the Q3 numbers") as approve and breaking its
     own "when in doubt never approve" rule. The judge runs on a strong, instruction-
     faithful model (settings.DECISION_MODEL, force_model="decision"); a false send is
     wildly asymmetric to the fractional per-call cost.
  2. The prompt names the exact leak patterns as explicit NOT-approve negatives.
  3. A second, STRICTER verification gate runs on the approve path ONLY — an
     independent binary "explicit go?" check (``_verify_explicit_go``). Approve
     requires passing BOTH the multi-class judge AND this gate, so no single
     mis-classification can send. It fails CLOSED (any doubt → not approved).

reject / edit / skip / show_others are all SAFE (nothing sends); ``skip`` (defer,
queue stays) and ``show_others`` (what else is pending) are queue-navigation intents —
they must be ABOUT this card / the approval queue, not a general question, which stays
``unrelated`` so it falls through to a normal turn. Any failure → ``unrelated`` (never
an auto-approve).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from app.llm.gateway import llm_gateway
from app.utils.logging import get_logger

logger = get_logger(__name__)

Intent = Literal["approve", "reject", "edit", "skip", "show_others", "unrelated"]
_VALID_INTENTS = ("approve", "reject", "edit", "skip", "show_others", "unrelated")


@dataclass(frozen=True)
class DecisionResolution:
    intent: Intent
    change: str = ""  # the requested edit, verbatim-ish, when intent == "edit"


_RESOLVER_PROMPT = """You are mediating a PENDING ACTION the assistant proposed and is waiting for the master to confirm BEFORE it runs. Classify the master's reply toward THIS action.

PENDING ACTION
  tool: {tool_name}
  details:
{details}

MASTER'S REPLY
  "{user_message}"

Choose exactly ONE intent:
- "approve": the master gives an EXPLICIT, ACTIVE instruction to proceed with THIS action AS-IS — e.g. "yes send it", "go ahead", "do it", "send the reply", "ship it", "approved", "yes, send that". Approving runs a REAL, IRREVERSIBLE action, so choose it ONLY for an unmistakable command to GO.
- "reject": the master clearly wants it cancelled / abandoned — e.g. "no", "cancel", "don't send", "forget it", "scrap it", "stop".
- "edit": the master wants THIS action CHANGED before it proceeds — e.g. "make it shorter", "use her name Priya", "change the recipient to X", "add that we'll be late", "more formal". Put the requested change in "change".
- "skip": the master wants to DEFER this specific pending action for now and move on, WITHOUT cancelling it — e.g. "skip", "skip this", "skip this one", "next", "next one", "not now", "later", "come back to this", "I'll deal with this one later". (Different from reject — skip leaves it pending; reject abandons it.)
- "show_others": the master wants to know what OTHER pending approvals are waiting — e.g. "what else is pending?", "show me the other pending emails", "what other approvals do I have?", "anything else waiting for me?". This is about the approval QUEUE specifically — NOT a general "show me my emails / calendar" request.
- "unrelated": the reply is about something else, a new question / topic (e.g. "what's on my calendar?", "show me my unread emails", "what's the weather?"), or is too ambiguous to be sure. WHEN IN DOUBT, choose this — never guess "approve" or "skip".

CRITICAL — these are NOT "approve" (classify them "unrelated"; they must NOT send):
- Echoing or confirming the TOPIC instead of commanding the action — "right, the Q3 numbers", "yes, that's the budget one", "the email to Priya, mm", "Q3, exactly".
- Acknowledging you've heard of or seen it — "yeah she emailed me about that earlier", "I saw that", "I know the one", "oh right that".
- A passive, hedged, or uncertain reply — "I guess so", "whatever you think", "mm, fine", "sure, I suppose", "if you think it's right", "okay then".
Merely repeating the subject, naming the recipient, or vaguely assenting is NOT a command to send — it is "unrelated". Approval must be an ACTIVE instruction to GO. When in any doubt, choose "unrelated", NEVER "approve".

Respond with JSON only:
{{"intent": "approve|reject|edit|skip|show_others|unrelated", "change": "<the requested change, or empty unless intent is edit>"}}"""


_VERIFY_PROMPT = """The assistant is about to take a REAL, IRREVERSIBLE action and needs the master's UNAMBIGUOUS go-ahead before it runs.

ACTION
  tool: {tool_name}
  details:
{details}

THE MASTER SAID
  "{user_message}"

Is this an EXPLICIT, ACTIVE instruction to perform that action RIGHT NOW?
- YES for a direct command to act — "send it", "do it", "go ahead", "yes do it", "send the reply", "approved", "yes, send that". A bare imperative to act ("do it", "go ahead", "send it") IS a yes: it tells the assistant to proceed.
- NO for anything that is NOT a command to act: echoing or confirming the topic ("right, the Q3 numbers"), acknowledging you've heard of it ("yeah she emailed me about that"), a passive / hedged / uncertain reply ("I guess so", "whatever you think", "mm fine", "okay then"), a question, a change request, or anything ambiguous.
The test is whether the master COMMANDED the action, not whether they merely acknowledged or assented. When in any doubt, answer NO — a wrong YES sends an irreversible action with no real consent.

Respond with JSON only: {{"explicit_go": true}} or {{"explicit_go": false}}"""


def _details(tool_args: dict, description: str | None) -> str:
    lines = [f"  - {k}: {v}" for k, v in (tool_args or {}).items()]
    return "\n".join(lines) if lines else (f"  {description}" if description else "  (no parameters)")


async def _verify_explicit_go(
    tool_name: str, tool_args: dict, description: str | None, user_message: str
) -> bool:
    """Second, STRICTER gate on the approve path ONLY (the irreversible one): an
    independent binary check that the master gave an EXPLICIT command to proceed —
    not a topic echo / soft yes. A different, skeptical framing than the multi-class
    judge, so an ambiguous acknowledgment that slips the first pass is caught here.

    Runs on the same strong ``decision`` slot. FAILS CLOSED: a non-true answer, a
    parse error, OR a gateway failure all return False → the caller downgrades approve
    to ``unrelated``. The cost (one extra call) lands ONLY when the first pass said
    approve — exactly the high-harm case where it's worth it."""
    prompt = _VERIFY_PROMPT.format(
        tool_name=tool_name,
        details=_details(tool_args, description),
        user_message=user_message.strip(),
    )
    try:
        response = await llm_gateway.complete(
            messages=[{"role": "user", "content": prompt}],
            task_type="classification",
            force_model="decision",       # the strong model, never the fast tier
            temperature=0.0,
            response_format={"type": "json_object"},
            tool_name_context="decision_verify",
        )
        content = response["choices"][0]["message"].get("content") or ""
        return json.loads(content).get("explicit_go") is True
    except Exception as exc:  # noqa: BLE001 — fail CLOSED: any doubt → not approved
        logger.warning("decision_verify_failed_closed", error=f"{type(exc).__name__}: {exc}")
        return False


async def resolve_decision(
    tool_name: str,
    tool_args: dict,
    description: str | None,
    user_message: str,
) -> DecisionResolution:
    """Classify the master's reply against the pending action on the strong
    ``decision`` slot (never the fast tier). Conservative on approve: an approve
    classification must ALSO pass the strict ``_verify_explicit_go`` gate or it is
    downgraded to ``unrelated``. Any failure degrades to ``unrelated`` (never an
    auto-approve)."""
    prompt = _RESOLVER_PROMPT.format(
        tool_name=tool_name,
        details=_details(tool_args, description),
        user_message=user_message.strip(),
    )
    try:
        response = await llm_gateway.complete(
            messages=[{"role": "user", "content": prompt}],
            task_type="classification",
            force_model="decision",       # strong tier — this gates an irreversible send
            temperature=0.0,
            response_format={"type": "json_object"},
            tool_name_context="decision_resolve",
        )
        content = response["choices"][0]["message"].get("content") or ""
        data = json.loads(content)
        intent = data.get("intent")
        if intent not in _VALID_INTENTS:
            intent = "unrelated"
        change = (data.get("change") or "").strip() if intent == "edit" else ""
        # An "edit" with no concrete change isn't actionable → treat as ambiguous.
        if intent == "edit" and not change:
            intent = "unrelated"
        # The approve gate (defence-in-depth): an irreversible send requires BOTH the
        # multi-class judge AND the strict explicit-go verification. A topic echo / soft
        # yes that leaks the first pass is downgraded here → unrelated (the safe nudge).
        if intent == "approve" and not await _verify_explicit_go(
            tool_name, tool_args, description, user_message
        ):
            logger.info("decision_approve_downgraded_by_verify", user_message=user_message[:80])
            intent = "unrelated"
        logger.info("decision_resolved", intent=intent, has_change=bool(change))
        return DecisionResolution(intent=intent, change=change)
    except Exception as exc:  # noqa: BLE001 — never auto-approve on a resolver failure
        logger.warning("decision_resolver_failed", error=f"{type(exc).__name__}: {exc}")
        return DecisionResolution(intent="unrelated")
