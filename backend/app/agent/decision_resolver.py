"""Natural-language resolution of a pending decision (A2 Piece 2).

Modality-agnostic: text (stream_turn / run_turn) and voice feed the SAME judgment.
Given the pending action (tool + args + description), the RECENT CONVERSATION, and
the master's reply, an LLM classifies intent → approve / reject / edit / skip /
show_others / unclear / unrelated. No keyword matching — it resolves by understanding
and generalizes to any decision type (no per-tool code).

CONTEXT-AWARE: the judge sees the recent conversation turns, so it can tell whether
an ambiguous reply is RESPONDING to the pending action (→ unclear → the caller
re-asks) or starting a NEW topic (→ unrelated → the caller answers it and reminds the
action is still pending). "right, the Q3 numbers" right after the assistant asked
"shall I send the Priya reply?" means something different than out of nowhere — context
is what disambiguates.

APPROVE is the highest-harm path: a single classification gates a REAL, IRREVERSIBLE
action. The invariant is "an ambiguous acknowledgment NEVER reaches approve", held by:
  1. NOT the weakest tier. The fast model (llama-3.1-8b) leaked, mis-reading a topic-
     echo ("right, the Q3 numbers") as approve. The judge runs on a strong, instruction-
     faithful model (settings.DECISION_MODEL, force_model="decision"); a false send is
     wildly asymmetric to the fractional per-call cost.
  2. The prompt names the exact leak patterns (topic echo / soft yes / acknowledgment)
     as explicit NOT-approve cases → "unclear" or "unrelated", never approve.
  3. A live regression test (tests/test_decision_judge_live.py) locks the boundary:
     ZERO false-approves on the adversarial set, zero clean-misses, so a model/prompt
     drift can't silently reopen the false-send. (The earlier runtime "verify" gate was
     retired — the strong model + negatives + context classified every adversarial case
     correctly on their own; the gate only ever caused false-negatives + a redundant
     call. The regression test is the durable safety net, not a second runtime LLM call.)

reject / edit / skip / show_others are all SAFE (nothing sends). Any failure →
``unrelated`` (never an auto-approve).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Literal

from app.llm.gateway import llm_gateway
from app.utils.logging import get_logger

logger = get_logger(__name__)

Intent = Literal["approve", "reject", "edit", "skip", "show_others", "unclear", "unrelated"]
_VALID_INTENTS = ("approve", "reject", "edit", "skip", "show_others", "unclear", "unrelated")


@dataclass(frozen=True)
class DecisionResolution:
    intent: Intent
    change: str = ""  # the requested edit, verbatim-ish, when intent == "edit"


_RESOLVER_PROMPT = """You are mediating a PENDING ACTION the assistant proposed and is waiting for the master to confirm BEFORE it runs. Using the recent conversation for context, classify the master's reply toward THIS action.

PENDING ACTION
  tool: {tool_name}
  details:
{details}

RECENT CONVERSATION (context — use it to tell whether the reply is RESPONDING to this pending action or starting a NEW topic)
{recent_context}

MASTER'S REPLY
  "{user_message}"

Choose exactly ONE intent:
- "approve": the master gives an EXPLICIT, ACTIVE instruction to proceed with THIS action AS-IS — e.g. "yes send it", "go ahead", "do it", "send the reply", "ship it", "approved", "yes, send that". Approving runs a REAL, IRREVERSIBLE action, so choose it ONLY for an unmistakable command to GO.
- "reject": the master clearly wants it cancelled / abandoned — e.g. "no", "cancel", "don't send", "forget it", "scrap it", "stop".
- "edit": the master wants THIS action CHANGED before it proceeds — e.g. "make it shorter", "use her name Priya", "change the recipient to X", "add that we'll be late", "more formal". Put the requested change in "change".
- "skip": the master wants to DEFER this specific pending action for now and move on, WITHOUT cancelling it — e.g. "skip", "skip this", "next", "not now", "later", "come back to this". (Different from reject — skip leaves it pending; reject abandons it.)
- "show_others": the master wants to know what OTHER pending approvals are waiting — e.g. "what else is pending?", "show me the other pending emails", "anything else waiting for me?". About the approval QUEUE specifically — NOT a general "show me my emails / calendar" request.
- "unclear": the reply is engaging with THIS pending action but is NOT a clear approve / reject / edit / skip — an ambiguous acknowledgment, a topic echo, or a soft / passive yes. Use the RECENT CONVERSATION: if the assistant just raised this action and the reply vaguely responds to it ("right, the Q3 numbers", "yeah", "I guess so", "mm okay", "the Priya one"), it is "unclear" — you must NOT guess "approve". (The caller will RE-ASK the master to clarify.)
- "unrelated": the reply is about something ELSE entirely — a new question or topic not about this pending action (e.g. "what's on my calendar?", "show me my unread emails", "what's the weather?"). (The caller will ANSWER it and remind the master the action is still pending.)

CRITICAL — NEVER choose "approve" unless the master gave an EXPLICIT, ACTIVE command to GO ("send it", "do it", "go ahead", "yes send it", "approved"). The following are NOT approve and must NEVER send:
- Echoing or confirming the TOPIC instead of commanding the action — "right, the Q3 numbers", "yes, that's the budget one", "Q3, exactly".
- Acknowledging you've heard of or seen it — "yeah she emailed me about that earlier", "I saw that", "I know the one".
- A passive, hedged, or uncertain reply — "I guess so", "whatever you think", "mm, fine", "sure, I suppose", "okay then".
Merely repeating the subject, naming the recipient, or vaguely assenting is NOT a command to send. Classify it "unclear" (it is about this action but ambiguous) or "unrelated" (a different topic) — when in ANY doubt, one of those, NEVER "approve".

Respond with JSON only:
{{"intent": "approve|reject|edit|skip|show_others|unclear|unrelated", "change": "<the requested change, or empty unless intent is edit>"}}"""


def _details(tool_args: dict, description: str | None) -> str:
    lines = [f"  - {k}: {v}" for k, v in (tool_args or {}).items()]
    return "\n".join(lines) if lines else (f"  {description}" if description else "  (no parameters)")


async def resolve_decision(
    tool_name: str,
    tool_args: dict,
    description: str | None,
    user_message: str,
    recent_context: str = "",
) -> DecisionResolution:
    """Classify the master's reply against the pending action on the strong
    ``decision`` slot (never the fast tier), using the recent conversation for
    context. Conservative on approve (only an explicit command to GO); an ambiguous
    reply about the card → ``unclear`` (re-ask), a different topic → ``unrelated``
    (answer + remind). Any failure degrades to ``unrelated`` (never an auto-approve)."""
    prompt = _RESOLVER_PROMPT.format(
        tool_name=tool_name,
        details=_details(tool_args, description),
        recent_context=recent_context.strip() or "(no recent conversation)",
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
        # An "edit" with no concrete change isn't actionable → ambiguous about the card.
        if intent == "edit" and not change:
            intent = "unclear"
        logger.info("decision_resolved", intent=intent, has_change=bool(change))
        return DecisionResolution(intent=intent, change=change)
    except Exception as exc:  # noqa: BLE001 — never auto-approve on a resolver failure
        logger.warning("decision_resolver_failed", error=f"{type(exc).__name__}: {exc}")
        return DecisionResolution(intent="unrelated")
