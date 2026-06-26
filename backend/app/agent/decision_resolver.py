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
- "approve": ONLY an UNAMBIGUOUS, COMMITTED confirmation or command to do THIS action. It either ISSUES the action — "go ahead", "do it", "send it", "delete it", "book it" — or clearly AFFIRMS THIS SPECIFIC PROPOSAL — "yes", "yes send it", "that works", "confirmed", "approved", "accepted", "go for it", "proceed". (The deliberate word "yes" approves; its CASUAL contractions "yeah" / "yep" / "yup" do NOT — they are reactions, see "unclear".) The deciding test: would a careful assistant be CERTAIN the master is commanding it to act on THIS, right now? Only then. This bar is the SAME for EVERY action — a committed confirmation approves a delete, a booking, or a calendar change EXACTLY as a send. A casual, low-commitment reaction that merely SOUNDS positive ("ok", "sure", "cool", …) is NOT this — see "unclear".
- "reject": the master clearly wants it cancelled / abandoned — e.g. "no", "cancel", "don't send", "forget it", "scrap it", "stop".
- "edit": the master wants THIS action CHANGED before it proceeds — e.g. "make it shorter", "use her name Priya", "change the recipient to X", "add that we'll be late", "more formal". Put the requested change in "change".
- "skip": the master wants to DEFER this specific pending action for now and move on, WITHOUT cancelling it — e.g. "skip", "skip this", "next", "not now", "later", "come back to this". (Different from reject — skip leaves it pending; reject abandons it.)
- "show_others": the master wants to know what OTHER pending approvals are waiting — e.g. "what else is pending?", "show me the other pending emails", "anything else waiting for me?". About the approval QUEUE specifically — NOT a general "show me my emails / calendar" request.
- "unclear": the reply engages THIS action but is NOT a committed confirmation → re-ask. This is a PRINCIPLE, not a list: a BARE CASUAL TOKEN or low-commitment reaction that merely sounds affirmative does NOT commit to acting — "ok", "okay", "k", "yeah", "yup", "yep", "sure", "cool", "great", "perfect", "nice", "mm", "alright", "fine", "fine by me", "why not", AND any similar casual one-word-ish reaction you weren't shown here. Also a PASSIVE / DEFLECTING reply that hands the decision back to you — "I guess so", "whatever you think", "up to you", "if you think so" — or a vague topic echo that names the subject but commands nothing ("right, the Q3 numbers", "the Priya one"). A casual token only approves when BUILT INTO a clear command ("ok, send it", "yeah do it"). When a reply could go either way, RE-ASK — never guess "approve".
- "unrelated": the reply is about something ELSE entirely — a new question or topic not about this pending action (e.g. "what's on my calendar?", "show me my unread emails", "what's the weather?"). (The caller will ANSWER it and remind the master the action is still pending.)

CRITICAL — the ONE test before you choose "approve": is the reply an UNAMBIGUOUS, COMMITTED confirmation or command to do THIS action — or just a casual reaction that happens to sound affirmative? If it is a casual reaction, RE-ASK ("unclear"); do NOT approve. A bare "ok" / "okay" / "k" / "yeah" / "yup" / "sure" / "cool" / "fine" / "alright" / "why not" / "fine by me" must NEVER fire an action on its own — on ANY flow. This is intentionally STRICT and IDENTICAL for a send and a delete (a casual token re-asks an email send too — only a real "yes"/"go ahead"/"that works"/"do it" approves it). These also never approve:
- A TOPIC echo instead of a confirmation — "right, the Q3 numbers", "yes, that's the budget one", "Q3, exactly", "oh right, that one".
- A PASSIVE / DEFLECTING reply — "I guess so", "whatever you think", "up to you", "if you think so". Handing the decision back to YOU is not a yes.
When in ANY doubt, "unclear" — the safe landing is always re-ask.

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
    context. ONE consent bar for EVERY action (no harm tier): a CLEAR confirmation
    ("go ahead", "approved", "confirmed", "that works", "delete it") → ``approve``,
    identically for a send or a delete; a genuinely-ambiguous filler ("yeah", "ok",
    "I guess so") → ``unclear`` (re-ask); a topic echo / different topic → never
    approves (``unclear`` / ``unrelated``). Any failure degrades to ``unrelated``
    (never an auto-approve)."""
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
