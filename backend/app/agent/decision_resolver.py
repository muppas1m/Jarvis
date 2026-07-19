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
import re
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
    # B1.0 step 2 — the committed-vs-hedged axis (master's design call): True when the reply
    # DEFERS or hedges ("maybe", "maybe later", "perhaps", "I guess we could") even if it names a
    # selection or sounds affirmative. A hedged answer makes the consume path RE-CONFIRM, never
    # dispatch. Defaults False (a missing field never blocks a committed confirmation; the
    # unclear-intent bar remains the primary non-consent guard).
    hedged: bool = False


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
- "approve": ONLY an UNAMBIGUOUS, COMMITTED confirmation or command to do THIS action. It either ISSUES the action — "go ahead", "do it", "send it", "book it" — or clearly AFFIRMS THIS SPECIFIC PROPOSAL — "yes", "yes send it", "that works", "confirmed", "approved", "accepted", "go for it", "proceed". (The deliberate word "yes" approves; its CASUAL contractions "yeah" / "yep" / "yup" do NOT — they are reactions, see "unclear".) The deciding test: would a careful assistant be CERTAIN the master is commanding it to act on THIS, right now? Only then. This bar is the SAME for EVERY action — a committed confirmation approves a delete, a booking, or a calendar change EXACTLY as a send. A casual, low-commitment reaction that merely SOUNDS positive ("ok", "sure", "cool", …) is NOT this — see "unclear".
- "reject": the master clearly wants THIS WHOLE action cancelled / abandoned — e.g. "no", "cancel", "don't send", "forget it", "scrap it", "stop". DESTRUCTION VERBS ARE CARD-AWARE (read the `tool:` above): "delete it" / "trash it" / "get rid of it" target the PROPOSAL unless the pending action itself IS a deletion. Only an explicit destruction COMMAND counts — a topic echo ("oh right, that one", "right, the Q3 one") commands nothing on ANY card, a delete card included → "unclear". Worked examples: tool `email_send` + "delete it" → "reject" (discard the draft; nothing sends); tool `calendar_delete` + "delete it" / "trash it" → "approve" (the deletion IS the pending action being commanded; abandon words — "cancel", "forget it", "scrap it" — still reject it).
- "edit": the master wants THIS action CHANGED before it proceeds — e.g. "make it shorter", "use her name Priya", "change the recipient to X", "add that we'll be late", "more formal" — INCLUDING FIELD REMOVAL: "remove the attendees", "take Priya off the invite", "drop the location" are edits to that part, never rejections. THE PRINCIPLE: "reject" abandons the WHOLE action; a request naming a PART of the action (a field, a recipient, the attendees, the location, a line of the draft) is an "edit" to that part. Only an INSTRUCTION — an imperative to change a part, including polite "can you remove…?" — is an edit. A QUESTION about a part is NOT: anything that merely ASKS about a part's current value, contents, or membership commands no change → "unclear" (re-ask). This covers correctness checks ("is that the right address?", "is the time right?"), membership/content questions ("is Pavan on the invite?", "are the attendees correct?", "does this include the location?", "who's on it?"), and "did you…" checks. Deciding test: if the reply issues NO imperative to change and only asks about a part → "unclear". The minimal pair: "are the attendees correct?" ASKS → "unclear"; "correct the attendees" INSTRUCTS → "edit". (A bare "remove it" / "delete it" names no part — that is the whole action: see "reject".) Put the requested change in "change".
- "skip": the master wants to DEFER this specific pending action for now and move on, WITHOUT cancelling it — e.g. "skip", "skip this", "next", "not now", "later", "come back to this". (Different from reject — skip leaves it pending; reject abandons it.)
- "show_others": the master wants to know what OTHER pending approvals are waiting — e.g. "what else is pending?", "show me the other pending emails", "anything else waiting for me?". About the approval QUEUE specifically — NOT a general "show me my emails / calendar" request.
- "unclear": the reply engages THIS action but is NOT a committed confirmation → re-ask. QUESTIONS ABOUT THE ACTION'S PARTS land HERE: a reply that only ASKS about a part's current value, contents, or membership — "is that the right address?", "is the time right?", "is Pavan on the invite?", "are the attendees correct?", "does this include the location?", "who's on it?", "did you use her work email?" — commands NO change: it is "unclear" (re-ask), NEVER "edit" (see the deciding test under "edit"). SELECTION-ONLY replies land HERE: when the assistant just asked WHICH of several pending actions the master means, a reply that only SELECTS — "both", "all of them", "the calendar one", "the one to Timmy" — is "unclear": it identifies, it does not consent. NEVER "unrelated" for such a reply, and NEVER "approve" (identification is not consent, even with a leading "yes"/"right"/"oh right" — "yes, that's the budget one" and "oh right, that one" are "unclear", on EVERY card kind including a delete). This is a PRINCIPLE, not a list: a BARE CASUAL TOKEN or low-commitment reaction that merely sounds affirmative does NOT commit to acting — "ok", "okay", "k", "yeah", "yup", "yep", "sure", "cool", "great", "perfect", "nice", "mm", "alright", "fine", "fine by me", "why not", AND any similar casual one-word-ish reaction you weren't shown here. Also a PASSIVE / DEFLECTING reply that hands the decision back to you — "I guess so", "whatever you think", "up to you", "if you think so" — or a vague topic echo that names the subject but commands nothing ("right, the Q3 numbers", "the Priya one"). A casual token only approves when BUILT INTO a clear command ("ok, send it", "yeah do it"). When a reply could go either way, RE-ASK — never guess "approve".
- "unrelated": the reply is about something ELSE entirely — a new question or topic not about this pending action (e.g. "what's on my calendar?", "show me my unread emails", "what's the weather?"). (The caller will ANSWER it and remind the master the action is still pending.)

CRITICAL — the ONE test before you choose "approve": is the reply an UNAMBIGUOUS, COMMITTED confirmation or command to do THIS action — or just a casual reaction that happens to sound affirmative? If it is a casual reaction, RE-ASK ("unclear"); do NOT approve. A bare "ok" / "okay" / "k" / "yeah" / "yup" / "sure" / "cool" / "fine" / "alright" / "why not" / "fine by me" must NEVER fire an action on its own — on ANY flow. This is intentionally STRICT and IDENTICAL for a send and a delete (a casual token re-asks an email send too — only a real "yes"/"go ahead"/"that works"/"do it" approves it). These also never approve:
- A TOPIC echo instead of a confirmation — "right, the Q3 numbers", "yes, that's the budget one", "Q3, exactly", "oh right, that one".
- A PASSIVE / DEFLECTING reply — "I guess so", "whatever you think", "up to you", "if you think so". Handing the decision back to YOU is not a yes.
When in ANY doubt, "unclear" — the safe landing is always re-ask.

ALSO judge one independent axis — "hedged": is the reply COMMITTED or does it HEDGE/DEFER? "hedged" is true when the reply defers, hedges, or postpones — "maybe", "maybe later", "perhaps", "I guess we could", "possibly", "at some point", "later", "not now", "hold off", "do them all later", "maybe after lunch", conditional/future framing — EVEN IF it names a selection, sounds affirmative, or contains a command ("send it, maybe after lunch" → hedged true; "do them all later" → hedged true). A DEFERRAL is never a fireable go-ahead. A committed reply ("both", "yes", "go ahead", "reject it") → hedged false. This axis is independent of intent.

Respond with JSON only:
{{"intent": "approve|reject|edit|skip|show_others|unclear|unrelated", "change": "<the requested change, or empty unless intent is edit>", "hedged": true|false}}"""


# --------------------------------------------------------------------------- #
# Step-2.1 — the DETERMINISTIC bare-filler floor (guarantee layer). The consent
# doctrine ENUMERATES these tokens ("ok"/"sure"/"k" re-ask — the same bar on
# every flow); live probing showed the model boundary wobbles FIREABLE on them
# ("sure" → approve+unhedged 4/6 runs on a delete). An enumerated class belongs
# in code: a message that IS one of these (whole-message match, punctuation
# stripped) short-circuits to re-ask/hedged without a model call — deterministic,
# model-migration-proof (NV4), and the judge still owns every unenumerated
# phrasing. "yes" is deliberately NOT here (the deliberate word that approves);
# a filler BUILT INTO a command ("ok, send it") does not match and reaches the
# model as before.
# --------------------------------------------------------------------------- #
_BARE_FILLERS = frozenset({
    "ok", "okay", "k", "kk", "yeah", "yep", "yup", "sure", "sure thing", "cool", "great",
    "perfect", "nice", "mm", "mhm", "alright", "fine", "fine by me", "why not", "i guess",
    "i guess so", "up to you", "whatever you think", "if you think so",
})


def _is_bare_filler(message: str) -> bool:
    t = re.sub(r"[^a-z ]", " ", (message or "").lower())
    return " ".join(t.split()) in _BARE_FILLERS


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
    ("go ahead", "approved", "confirmed", "that works") → ``approve``,
    identically for a send or a delete; a genuinely-ambiguous filler ("yeah", "ok",
    "I guess so") → ``unclear`` (re-ask); a topic echo / different topic → never
    approves (``unclear`` / ``unrelated``). Any failure degrades to ``unrelated``
    (never an auto-approve)."""
    if _is_bare_filler(user_message):
        logger.info("decision_resolved", intent="unclear", has_change=False, hedged=True,
                    floor="bare_filler")
        return DecisionResolution(intent="unclear", hedged=True)
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
        hedged = bool(data.get("hedged", False))
        logger.info("decision_resolved", intent=intent, has_change=bool(change), hedged=hedged)
        return DecisionResolution(intent=intent, change=change, hedged=hedged)
    except Exception as exc:  # noqa: BLE001 — never auto-approve on a resolver failure
        logger.warning("decision_resolver_failed", error=f"{type(exc).__name__}: {exc}")
        return DecisionResolution(intent="unrelated")


# --------------------------------------------------------------------------- #
# B1.0 step-2.1 — the CARD-AGNOSTIC answer-verb judge (the question-consume     #
# path's verb source).                                                          #
# --------------------------------------------------------------------------- #
AnswerVerb = Literal["approve", "reject", "edit", "skip", "none", "info", "unrelated"]
_VALID_ANSWER_VERBS = ("approve", "reject", "edit", "skip", "none", "info", "unrelated")

# Step-2.2 — the COMMITTED-AFFIRMATION floor (inverted polarity, master-ratified set): the
# bare-branch dispatch of a question's carried intent requires an explicit POSITIVE COMMITTED
# affirmation from this CLOSED deterministic set (whole-message match, punctuation stripped).
# Pure assent forms ONLY — they carry the QUESTION's verb ("go ahead" on a discard-confirm
# discards). Action verbs ("send it") are deliberately NOT here: they reach the model and
# override as explicit verbs (CH-2). The absence of a verb is never consent — everything
# outside this set re-confirms. ("👍" and other emoji are outside → re-confirm; say the word
# to enumerate them.)
_COMMITTED_AFFIRMATIONS = frozenset({
    "yes", "yes sir", "yes please", "go ahead", "go ahead please", "go for it", "proceed",
    "do it", "please do", "confirmed", "confirm", "approved", "approve", "accepted", "accept",
    "that works", "correct", "affirmative", "absolutely", "definitely",
})


@dataclass(frozen=True)
class AnswerVerbResolution:
    verb: AnswerVerb
    hedged: bool = False
    change: str = ""
    # True ONLY via the deterministic committed floor — the sole enabler of a bare-branch
    # carried-intent dispatch. The model can never set it (guarantee layer owns it).
    committed: bool = False


_ANSWER_VERB_PROMPT = """The assistant asked the master a question about pending action(s) and the master replied. You are shown ONLY the reply — not the question and not the cards, ON PURPOSE: the deterministic layer owns which item is meant and what the question asked; you classify only what the reply's OWN WORDS express. There is nothing here to borrow a verb from — if the reply does not itself command a verb, it has none.

MASTER'S REPLY
  "{user_message}"

Classify the reply's OWN verb — what the reply itself commands, independent of any particular item:
- "approve": ONLY when the reply contains an explicit ACTION COMMAND — a verb acting on the item: "send it", "go ahead and send", "book it", "fire it off", "actually approve it". Agreement or assent WITHOUT an action verb — "yes", "works for me", "sounds good", "aye", "fine by me", a thumbs-up emoji — is NOT approve: it is "none" (the deterministic layer alone decides whether assent may act; if you call assent "approve" you bypass that layer).
- "reject": the reply itself commands cancel/discard — "reject both", "cancel", "don't send", "scrap it", "discard the calendar one".
- "edit": the reply asks for a CHANGE before proceeding — "make it shorter", "change the time to 6pm". Put the change in "change".
- "skip": the reply defers navigation explicitly — "skip", "skip this one".
- "info": the reply ASKS ABOUT the pending item(s) THEMSELVES — "read it back to me", "what does it say?", "is that the right address?", "who is it to?", "when is it scheduled?". A question about the item is NEVER assent — the assistant should ANSWER it. A question about ANYTHING ELSE ("what's the weather?", "show me my inbox") is "unrelated", not "info".
- "none": the reply expresses NO verb of its own — it merely AFFIRMS the question ("yes", "yeah go ahead" as bare assent) or SELECTS/IDENTIFIES items ("both", "all of them", "the calendar one", "the one to Timmy", "yes, that's the budget one"). A verb comes ONLY from the reply's own words. When in doubt between "none" and a verb, choose "none".
- "unrelated": the reply is about something else entirely ("what's the weather?", "show me my inbox").

ALSO judge "hedged": true when the reply is anything short of COMMITTED — it defers/hedges/postpones ("maybe", "perhaps", "later", "not now", "hold off", "do them all later", "maybe after lunch", conditional/future framing) OR it is a non-committal casual token or deflection ("ok", "okay", "k", "sure", "cool", "fine", "alright", "why not", "I guess", "I guess so", "up to you", "whatever you think", "if you think so") — even if it also affirms, selects, or commands. A hedged or casual reply is never a fireable go-ahead. COMMITTED replies → false: the deliberate "yes", "yeah go ahead", "go for it", "do it", "both", "reject both", "the calendar one".

Respond with JSON only:
{{"verb": "approve|reject|edit|skip|none|info|unrelated", "hedged": true|false, "change": "<the requested change, or empty unless verb is edit>"}}"""


async def resolve_answer_verb(
    user_message: str,
    question: str,
    recent_context: str = "",
) -> AnswerVerbResolution:
    """Classify the master's ANSWER to an open question — CARD-AGNOSTICALLY (step-2.1 root
    fix): the judge never sees card facts, so the verb cannot vary by which card it was judged
    against (the run-varying unclear/unrelated/hallucinated-approve class is dead). A bare
    affirmative or bare selection is "none" — it never manufactures a verb; the consume layer
    applies the question's carried intent. Failure → verb="none" + hedged=True (a resolver
    failure can only RE-CONFIRM, never dispatch)."""
    norm = " ".join(re.sub(r"[^a-z ]", " ", (user_message or "").lower()).split())
    if norm in _COMMITTED_AFFIRMATIONS:
        # The guarantee floor — the ONLY source of committed=True (deterministic, no model).
        logger.info("answer_verb_resolved", verb="none", hedged=False, has_change=False,
                    floor="committed_affirmation")
        return AnswerVerbResolution(verb="none", hedged=False, committed=True)
    if _is_bare_filler(user_message):
        # Fast-path (subsumed by the inversion — uncommitted none re-confirms anyway; this
        # just skips the model call for the enumerated filler class).
        logger.info("answer_verb_resolved", verb="none", hedged=True, has_change=False,
                    floor="bare_filler")
        return AnswerVerbResolution(verb="none", hedged=True)
    # The question/context are deliberately NOT shown to the model (nothing to borrow a verb
    # from — the borrowing failure was live-proven); the signature keeps them for telemetry.
    prompt = _ANSWER_VERB_PROMPT.format(user_message=user_message.strip())
    try:
        response = await llm_gateway.complete(
            messages=[{"role": "user", "content": prompt}],
            task_type="classification",
            force_model="decision",       # the same strong slot — this gates dispatch
            temperature=0.0,
            response_format={"type": "json_object"},
            tool_name_context="answer_verb_resolve",
        )
        data = json.loads(response["choices"][0]["message"].get("content") or "")
        verb = data.get("verb")
        coerced = verb not in _VALID_ANSWER_VERBS
        if coerced:
            verb = "none"
        change = (data.get("change") or "").strip() if verb == "edit" else ""
        if verb == "edit" and not change:
            verb = "none"                 # an edit with no concrete change is not actionable
        # FAIL-CLOSED (step-2.2): a degenerate/wrong-schema response (missing verb, a sibling
        # judge's keys) forces hedged=True — a coerced none can never look dispatch-capable.
        hedged = True if coerced else bool(data.get("hedged", False))
        logger.info("answer_verb_resolved", verb=verb, hedged=hedged, has_change=bool(change))
        return AnswerVerbResolution(verb=verb, hedged=hedged, change=change)
    except Exception as exc:  # noqa: BLE001 — a failed judge can only re-confirm
        logger.warning("answer_verb_resolver_failed", error=f"{type(exc).__name__}: {exc}")
        return AnswerVerbResolution(verb="none", hedged=True)
