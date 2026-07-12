"""B1.0 F3 — the pure answer-consumption resolver (the seam-first core).

When the master answers an OPEN question ("which one?", "just to confirm…"), this decides what to
do with the answer. It is the load-bearing B1.0 mechanism, built PURE and unit-tested in ISOLATION
before any node wiring (the master's seam-first mandate — the load-bearing step must not be one
untestable monolith diff).

The Round-2 red-team's root finding (CH-0): a correct consume path must classify TWO orthogonal
dimensions SEPARATELY — never collapse them into one "judge the answer" hand-wave:

  • SELECTION — which cards the answer picks: all/both · by kind · by name · none. Computed PURELY
    over the answer + the LIVE candidate set the caller re-sources from the conversation THIS turn
    (never a frozen snapshot — CH-4). Reuses the s1b essentials matchers for NAME (no D25 token-trap)
    and the kind vocabulary for KIND.
  • VERB — what the answer wants done: approve · reject · edit · skip. Taken from the JUDGE's
    classification of the answer (`answer_verb`), which OVERRIDES the question's carried intent
    (CH-2 — the catastrophic wrong-verb guard: "reject both" on an approve-origin question must
    reject, never approve). The carried intent is the FALLBACK used ONLY for a selector-only answer
    that expresses no verb ("both", "the Timmy one") — i.e. when the judge returns a non-verb intent.

The dispatch gate then dispatches ONLY on a resolved singleton (or an explicit all/both); a bare
affirmative to a >1 set RE-CONFIRMS naming the choices (CH-3) — never dispatch-all (a seal breach),
never an identical re-ask (the loop).

PURE: zero I/O, zero graph state, zero LLM/DB calls. The only external read is the in-memory tool
registry (via `card_names_any_essential`) — deterministic config, safe for isolated unit tests.
The caller (card_resolution_node, step 2) supplies the live candidates + the judged verb and executes
the returned decision.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.agent.approval_essentials import card_names_any_essential

# The verbs the judge can express on the answer (the _PresentedJudgment.intent vocabulary). Only
# these OVERRIDE the carried intent; any other intent (unclear/unrelated/show_others) means the
# answer expressed no verb → selector-only → the carried intent governs.
_VERBS = frozenset({"approve", "reject", "edit", "skip"})

# SELECTION vocabulary — self-contained here (the resolver owns selection). At step-2 wiring,
# nodes.py's duplicate _CARD_KIND_* are unified by importing these; kept local now to avoid a
# circular import (nodes imports the resolver, not vice-versa).
# F5.1 — EXPLICIT selector forms ONLY. A bare "all"/"every"/"each"/"the two" is struck: idioms
# ("that's all for now", "at all"), content words ("every time", "everyone on the team"), and
# unverified cardinals ("the two" of three) manufactured dispatch-alls the master never selected.
# Precision, not semantics — the intent was always explicit all/both; anything less re-confirms
# (kind-scoped + cardinality-checked selection is B1.1).
_ALL_SELECTOR = re.compile(
    r"\b(both|them all|all of (them|these|those)|all (two|three|four|five)( of them)?)\b",
    re.IGNORECASE)
_KIND_CALENDAR = re.compile(r"\b(calendar|event|meeting|appointment|schedule)\b", re.IGNORECASE)
_KIND_EMAIL = re.compile(r"\b(e-?mails?|reply|replies)\b", re.IGNORECASE)
_CALENDAR_TOOLS = ("calendar_create", "calendar_update", "calendar_delete")


@dataclass(frozen=True)
class ConsumeDecision:
    """The pure decision — the caller executes it, this function never acts.

    action:
      "dispatch"  — resolve `selection` (one, or an explicit all/both) with `verb`.
      "confirm"   — re-ask, NAMING `choices` (a bare affirmative to >1, a kind narrowed to >1, or a
                    named kind/name not among the candidates). Never dispatch, never an identical re-ask.
      "abandon"   — the answer is off-topic (no verb, no selection) or no live candidate remains; the
                    caller marks the question `abandoned` and lets the agent own the turn.
    """
    action: str
    verb: str = ""                       # approve|reject|edit|skip — meaningful for dispatch/confirm
    selection: tuple[str, ...] = ()      # approval_ids to act on (action == "dispatch")
    choices: tuple[str, ...] = ()        # approval_ids to NAME in a re-confirm (action == "confirm")
    reason: str = ""                     # telemetry: singleton | explicit_all | narrowed_singleton |
    #                                      narrowed_ambiguous | no_match | bare_ambiguous | off_topic |
    #                                      no_live_candidates


def _selection(answer: str, candidates: list[Any]) -> tuple[str, list[str]]:
    """Classify the SELECTION dimension purely. Returns (kind, matched_ids):
      ("all", all ids)      — an explicit all/both selector;
      ("filter", matched)   — a kind and/or name selector fired (matched MAY be empty → the named
                              kind/name is not among the candidates → the caller confirms);
      ("none", [])          — no selector at all (a bare answer)."""
    msg = answer or ""
    if _ALL_SELECTOR.search(msg):
        return "all", [c.approval_id for c in candidates]

    want_cal = bool(_KIND_CALENDAR.search(msg))
    want_email = bool(_KIND_EMAIL.search(msg))
    matched: list[str] = []
    for c in candidates:
        is_cal = getattr(c, "tool_name", "") in _CALENDAR_TOOLS
        is_email = getattr(c, "kind", "") == "email"
        kind_hit = (want_cal and is_cal) or (want_email and is_email)
        name_hit = card_names_any_essential(msg, getattr(c, "tool_name", ""), getattr(c, "tool_args", None) or {})
        if kind_hit or name_hit:
            matched.append(c.approval_id)

    if want_cal or want_email or matched:
        return "filter", matched
    return "none", []


def resolve_answer(answer: str, candidates: list[Any], answer_verb: str, carried_intent: str) -> ConsumeDecision:
    """Resolve the master's ANSWER to an open question.

    answer         — the master's reply text (for SELECTION parsing).
    candidates     — the LIVE pending cards, re-sourced from the conversation THIS turn (objects with
                     .approval_id / .kind / .tool_name / .tool_args). Never a frozen snapshot (CH-4).
    answer_verb    — the judge's intent classification of the answer (approve|reject|edit|skip|unclear|
                     unrelated|show_others). A verb OVERRIDES the carried intent (CH-2); a non-verb
                     means selector-only → the carried intent governs. F3 never parses verbs itself.
    carried_intent — the open question's original intent (approve|reject) — the selector-only fallback.
    """
    ids = [c.approval_id for c in candidates]
    if not candidates:
        return ConsumeDecision("abandon", reason="no_live_candidates")

    sel_kind, matched = _selection(answer, candidates)

    # VERB — the answer's judged verb overrides the carried intent; carried is the selector-only fallback.
    verb = answer_verb if answer_verb in _VERBS else carried_intent

    # NOT consent → abandon, even if a card string matched. The judge's `unrelated` means "this
    # isn't resolving the card" and `show_others` means "list them" — so a name/kind that happens to
    # appear ("the calendar one is wrong", "what about the email?") must NOT dispatch with the carried
    # intent. Abandon (→ the agent owns the turn) is the safe failure direction; a genuine selection
    # answer to the open question is judged `unclear` (related-but-no-verb), never `unrelated`.
    if answer_verb in ("unrelated", "show_others"):
        return ConsumeDecision("abandon", verb="", choices=tuple(ids), reason="off_topic")

    # F4 domain seal — a dispatch can only ever carry a judge-vocabulary verb. If neither the
    # answer nor the carried intent supplies one (an empty / out-of-domain carried value reaching
    # a selector branch), nothing was consented to on ANY branch → confirm, never dispatch. The
    # pure function enforces its own precondition rather than trusting future callers.
    if verb not in _VERBS:
        return ConsumeDecision("confirm", "", (), tuple(ids), "no_committed_verb")

    # --- the dispatch gate ---
    if sel_kind == "all":
        return ConsumeDecision("dispatch", verb, tuple(ids), (), "explicit_all")

    if sel_kind == "filter":
        if len(matched) == 1:
            return ConsumeDecision("dispatch", verb, (matched[0],), (), "narrowed_singleton")
        if len(matched) > 1:
            return ConsumeDecision("confirm", verb, (), tuple(matched), "narrowed_ambiguous")
        # matched == 0 → the answer named a kind/name absent from the candidates → confirm, never guess.
        return ConsumeDecision("confirm", verb, (), tuple(ids), "no_match")

    # sel_kind == "none": a bare answer, no selector. F4 — a dispatch here must be EARNED by the
    # answer itself: only a committed verb from the judge counts. A non-committal answer ("hmm
    # maybe", "up to you", a bare "ok" — judged `unclear`) commits to nothing, and the carried
    # intent can NEVER manufacture a dispatch from it (the selector-only fallback applies only when
    # the answer expressed an actual selection — the all/filter branches above). Any carried verb,
    # approve OR reject: "hmm maybe" manufactures no send and no discard — same bar every flow.
    if answer_verb not in _VERBS:
        return ConsumeDecision("confirm", carried_intent, (), tuple(ids), "noncommittal")
    if len(candidates) == 1:
        return ConsumeDecision("dispatch", verb, (ids[0],), (), "singleton")
    # A bare affirmative to a >1 set → RE-CONFIRM naming the choices — never dispatch-all, never loop.
    return ConsumeDecision("confirm", verb, (), tuple(ids), "bare_ambiguous")
