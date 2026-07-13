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
    r"\b(both|them all|all of (them|these|those))\b", re.IGNORECASE)
# B1.1 #3 — a STATED COUNT is a cardinality claim, verified against the (kind-narrowed)
# universe: "the two emails" of exactly two acts as all-of-them; of three (or one) it
# re-confirms — a count that doesn't match is never a dispatch.
_CARDINAL_SELECTOR = re.compile(r"\b(?:the|all)\s+(?P<num>two|three|four|five)\b", re.IGNORECASE)
_CARDINALS = {"two": 2, "three": 3, "four": 4, "five": 5}
# B1.2 — ordinal selection is CODE-owned (E-axis ideal §6.2: "ordinal → position in the set"):
# position over the (kind-narrowed) candidate order, which IS the presented order (queue order =
# candidate_ids order = the order describe_card names them). Out-of-range → confirm, never guess.
# B1.2-b — a POSITIONAL-SELECTOR PHRASE only ("the <ord>" | "<ord> one(s)"): homograph fillers
# ("one second", "at last", "second that", "first of all") no longer read as selections. The
# branch is additionally gated on _is_bare — a content compound ("the first-quarter report")
# fires the phrase but its residual kills the positional read, letting NAME-matching win.
_ORDINAL_SELECTOR = re.compile(
    r"\b(?:the\s+(?P<ord1>first|second|third|fourth|fifth|last)\b"
    r"|(?P<ord2>first|second|third|fourth|fifth|last)\s+ones?\b)",
    re.IGNORECASE)
_ORDINALS = {"first": 0, "second": 1, "third": 2, "fourth": 3, "fifth": 4}
# Plural-aware (the live CRITICAL: "both calendars" didn't match → the pool never narrowed →
# a bulk dispatch over the whole mixed set). PRECISION only — the Part-4 guarantee below holds
# even when these match nothing. ONE copy: nodes.py imports these (the gate can't drift again).
_KIND_CALENDAR = re.compile(r"\b(calendars?|events?|meetings?|appointments?|schedules?)\b", re.IGNORECASE)
_KIND_EMAIL = re.compile(r"\b(e-?mails?|reply|replies)\b", re.IGNORECASE)
_CALENDAR_TOOLS = ("calendar_create", "calendar_update", "calendar_delete")
# Step-2.1 H2 — name-selector PRESENCE detection (an address / quoted string in the answer is a
# name-selection attempt even when it matches no candidate → no_match/confirm, never the bare
# fall-through). Local copies keep this module a pure leaf.
_EMAIL_ADDR = re.compile(r"[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}", re.IGNORECASE)
_QUOTED = re.compile(r"'([^']{2,80})'|\"([^\"]{2,80})\"")


# Fork B (reviewer-preferred) — "bare" via RESIDUAL EMPTINESS, fail-safe: strip the selector
# span, the matched kind tokens, a closed action-verb list, and a small CLOSED function-word
# set; ANY remaining alphabetic token ≥3 chars means the master scoped the request with a word
# we may not understand → NON-bare → confirm. An unknown token ("bookings") is non-bare BY
# CONSTRUCTION, so the Part-4 guarantee holds with every kind regex wrong. "mean" is in the
# closed set (the I2 acceptance phrase "I mean both" must stay bare).
_SELECTOR_TOKENS = frozenset({
    "both", "all", "of", "them", "these", "those", "the", "each", "every",
    "two", "three", "four", "five", "one", "ones",
    "first", "second", "third", "fourth", "fifth", "last",   # B1.2 ordinals
})
_ACTION_VERB_TOKENS = frozenset({
    "approve", "approved", "reject", "rejected", "send", "sent", "discard", "discarded",
    "cancel", "cancelled", "canceled", "delete", "deleted", "accept", "accepted", "confirm",
    "confirmed", "skip", "skipped", "proceed", "dispatch", "fire", "book", "scrap",
})
_FUNCTION_TOKENS = frozenset({
    "i", "we", "you", "it", "me", "my", "mean", "meant", "yes", "yeah", "yep", "ok", "okay",
    "sir", "please", "and", "to", "for", "on", "in", "a", "an", "that", "this", "do", "go",
    "ahead", "now", "just", "actually", "then", "so", "too", "also", "well", "right",
    "alright", "sure", "fine", "lets", "let", "us", "with", "no", "not", "dont", "them",
    # consent-DOMAIN words — they scope to the approval domain itself, never to content
    # ("approve that pending calendar approval" must stay bare; "the drafts" must not):
    "pending", "approval", "approvals", "card", "cards", "queued", "queue",
})


def _is_bare(answer: str) -> bool:
    """True when nothing but selector/kind/verb/function words remain — the ONLY state in
    which a bulk selector may act on a multi-kind pool (Part 4's bare-test, fail-safe)."""
    # FIX A — digits are SCOPING CONTENT ("both 1:1s", "5pm's"): erasing them read such
    # messages as bare and bypassed the Part-4 guard. Digits survive normalization and any
    # digit-bearing token is immediately non-bare.
    text = re.sub(r"[^a-z0-9 ]", " ", (answer or "").lower())
    text = _KIND_CALENDAR.sub(" ", text)
    text = _KIND_EMAIL.sub(" ", text)
    for tok in text.split():
        if any(ch.isdigit() for ch in tok):
            return False
        if len(tok) < 3:
            continue
        if tok in _SELECTOR_TOKENS or tok in _ACTION_VERB_TOKENS or tok in _FUNCTION_TOKENS:
            continue
        return False
    return True


def _kind_sig(c: Any) -> str:
    """The vocab-free kind signature (from STATE, never prose): calendar tools → "cal"; email
    cards → "email"; anything else → its own tool_name (a future tool is its own kind)."""
    if getattr(c, "tool_name", "") in _CALENDAR_TOOLS:
        return "cal"
    if getattr(c, "kind", "") == "email":
        return "email"
    return getattr(c, "tool_name", "") or "unknown"


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


def _selection(answer: str, candidates: list[Any],
               presented_order: tuple = ()) -> tuple[str, list[str]]:
    """Classify the SELECTION dimension purely. Returns (kind, matched_ids):
      ("all", all ids)      — an explicit all/both selector;
      ("filter", matched)   — a kind and/or name selector fired (matched MAY be empty → the named
                              kind/name is not among the candidates → the caller confirms);
      ("none", [])          — no selector at all (a bare answer)."""
    msg = answer or ""
    want_cal = bool(_KIND_CALENDAR.search(msg))
    want_email = bool(_KIND_EMAIL.search(msg))

    def _kind_ok(c) -> bool:
        is_cal = getattr(c, "tool_name", "") in _CALENDAR_TOOLS
        is_email = getattr(c, "kind", "") == "email"
        return (want_cal and is_cal) or (want_email and is_email)

    # B1.1 #1 — kind-narrow FIRST: "both EMAILS" acts within the named kind, never beyond it
    # (the sweep's scope-exceeding-all, now fixed for real; the interim mixed_kind_all confirm
    # retires). No kind named → the pool is the whole candidate set (bare "both" unchanged).
    pool = [c for c in candidates if _kind_ok(c)] if (want_cal or want_email) else list(candidates)

    m_cardinal = _CARDINAL_SELECTOR.search(msg)
    if _ALL_SELECTOR.search(msg) or m_cardinal:
        if not pool:
            return "filter", []            # a kind named with no such card live → no_match
        if m_cardinal and _CARDINALS[m_cardinal.group("num").lower()] != len(pool):
            # #3 — the stated count doesn't match the universe → never a dispatch.
            return "mismatch", [c.approval_id for c in pool]
        return "all", [c.approval_id for c in pool]

    # B1.2-b — the ordinal branch: positional phrase + BARE message only (the over-fire fix).
    m_ord = _ORDINAL_SELECTOR.search(msg)
    if m_ord and _is_bare(msg):
        word = (m_ord.group("ord1") or m_ord.group("ord2")).lower()
        if want_cal or want_email:
            # kind+ordinal: position over the LIVE kind pool — the DECLARED BOUNDED RESIDUAL
            # under drift (the pending-only fetch cannot kind already-resolved cards).
            idx = len(pool) - 1 if word == "last" else _ORDINALS[word]
            if 0 <= idx < len(pool):
                return "filter", [pool[idx].approval_id]
            return "mismatch", [c.approval_id for c in pool]
        # Bare ordinal (drift Option A): the FROZEN presented order picks the POSITION;
        # liveness decides the ACTION. Never re-index onto the shrunken live list.
        order = [str(x) for x in presented_order] or [c.approval_id for c in pool]
        idx = len(order) - 1 if word == "last" else _ORDINALS[word]
        if not (0 <= idx < len(order)):
            return "mismatch", [c.approval_id for c in pool]   # beyond the frozen list → confirm
        pick = order[idx]
        if pick in {c.approval_id for c in candidates}:
            return "filter", [pick]                             # frozen pick still live → act
        return "stale", [pick]                                  # frozen pick resolved → ack

    matched: list[str] = []
    for c in candidates:
        kind_hit = _kind_ok(c)
        name_hit = card_names_any_essential(msg, getattr(c, "tool_name", ""), getattr(c, "tool_args", None) or {})
        if kind_hit or name_hit:
            matched.append(c.approval_id)

    # H2 root: an address/quoted-string selector that matched NOTHING is still a selection
    # ATTEMPT — it must land in filter (→ no_match → confirm/widen), never fall through to the
    # bare branch where a lone live candidate would dispatch (the wrong-card send).
    has_name_selector = bool(_EMAIL_ADDR.search(msg) or _QUOTED.search(msg))
    if want_cal or want_email or matched or has_name_selector:
        return "filter", matched
    return "none", []


def resolve_answer(answer: str, candidates: list[Any], answer_verb: str, carried_intent: str,
                   *, hedged: bool = False, committed: bool = False,
                   presented_order: tuple = ()) -> ConsumeDecision:
    """Resolve the master's ANSWER to an open question.

    answer         — the master's reply text (for SELECTION parsing).
    candidates     — the LIVE pending cards, re-sourced from the conversation THIS turn (objects with
                     .approval_id / .kind / .tool_name / .tool_args). Never a frozen snapshot (CH-4).
    answer_verb    — the judge's intent classification of the answer (approve|reject|edit|skip|unclear|
                     unrelated|show_others). A verb OVERRIDES the carried intent (CH-2); a non-verb
                     means selector-only → the carried intent governs. F3 never parses verbs itself.
    carried_intent — the open question's original intent (approve|reject) — the selector-only fallback.
    hedged         — the judge's committed-vs-hedged axis on the answer (step-2 contract, master's #4
                     call): a hedged answer ("maybe do them all later", "maybe send it") RE-CONFIRMS,
                     never dispatches — regardless of verb or selection. The pure resolver cannot see
                     the hedge; it is judged, not parsed.
    """
    ids = [c.approval_id for c in candidates]
    if not candidates:
        return ConsumeDecision("abandon", reason="no_live_candidates")

    sel_kind, matched = _selection(answer, candidates, presented_order)

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

    # The hedged axis (#4): a hedged answer never dispatches — any would-be dispatch re-confirms
    # naming the candidates. Structural: the gate is on the ACTION, the language layer stays free.
    if hedged:
        return ConsumeDecision("confirm", verb, (), tuple(ids), "hedged")

    # --- the dispatch gate ---
    if sel_kind == "stale":
        # B1.2-b drift — the frozen-order pick was resolved out-of-band: an honest ack, never a
        # re-indexed dispatch onto a different card.
        return ConsumeDecision("abandon", verb, (), tuple(matched), "ordinal_stale")
    if sel_kind == "mismatch":
        # B1.1 #3 — the stated count ≠ the (narrowed) universe: confirm naming the pool.
        return ConsumeDecision("confirm", verb, (), tuple(matched), "cardinality_mismatch")
    if sel_kind == "all":
        pool_cards = [c for c in candidates if c.approval_id in set(matched)]
        # Part 4 (THE GUARANTEE — vocab-free homogeneity / narrow-failure): a bulk selector may
        # dispatch a pool spanning >1 card-kind ONLY when the message is BARE. Any extra
        # scoping token — a plural we missed, "bookings", a future tool's noun — is a FAILED
        # narrowing → confirm. Fires on the STRUCTURE of the result (kind signatures from
        # state), so it holds with every kind regex broken. "I mean both" (bare) dispatches;
        # "both bookings" confirms.
        if len({_kind_sig(c) for c in pool_cards}) > 1 and not _is_bare(answer):
            return ConsumeDecision("confirm", verb, (), tuple(matched), "unnarrowed_bulk")
        # Part 2 — "both" carries an IMPLICIT count of 2: any other pool size confirms
        # (count-less "them all"/"all of them" stay unbounded).
        if re.search(r"\bboth\b", answer or "", re.IGNORECASE) and len(matched) != 2:
            return ConsumeDecision("confirm", verb, (), tuple(matched), "cardinality_mismatch")
        return ConsumeDecision("dispatch", verb, tuple(matched), (), "explicit_all")

    if sel_kind == "filter":
        if len(matched) == 1:
            return ConsumeDecision("dispatch", verb, (matched[0],), (), "narrowed_singleton")
        if len(matched) > 1:
            return ConsumeDecision("confirm", verb, (), tuple(matched), "narrowed_ambiguous")
        # matched == 0 → the answer named a kind/name absent from the candidates → confirm, never guess.
        return ConsumeDecision("confirm", verb, (), tuple(ids), "no_match")

    # sel_kind == "none": a bare answer, no selector. F4 — a dispatch here must be EARNED by the
    # answer itself. Two vocabularies feed this (step-2.1): the card-agnostic answer judge returns
    # "none" for COMMITTED assent/selection ("yes" consenting to the ask) — its non-committal
    # boundary lives on the HEDGED axis (fillers come back hedged=True and the hedge gate above
    # already re-confirmed). The direct judge's "unclear" (and anything else non-verb) stays
    # non-committal here: the carried intent can never manufacture a dispatch from it — any
    # carried verb, approve OR reject ("hmm maybe" manufactures no send and no discard).
    if answer_verb not in _VERBS and answer_verb != "none":
        return ConsumeDecision("confirm", carried_intent, (), tuple(ids), "noncommittal")
    # Step-2.2 INVERTED POLARITY: a bare "none" may carry the question's intent ONLY when the
    # deterministic committed-affirmation floor matched. The absence of a verb is never consent
    # — "works for me" / "sounds good" / "👍" / a degenerate judge response all land here and
    # RE-CONFIRM. (The open non-committed set can't be enumerated; the committed set can.)
    if answer_verb == "none" and not committed:
        return ConsumeDecision("confirm", carried_intent, (), tuple(ids), "noncommittal")
    if len(candidates) == 1:
        # FIX B (the none-branch singleton gate, the Part-3 ruling arrived): a NON-bare message
        # over a lone candidate names a scope we couldn't resolve ("approve the invites") →
        # confirm, never the singleton dispatch. Committed-floor matches are bare by definition
        # (whole-message closed set); edit is exempt (its residual IS the change text).
        if verb != "edit" and not committed and not _is_bare(answer):
            return ConsumeDecision("confirm", verb, (), tuple(ids), "unnarrowed_singleton")
        return ConsumeDecision("dispatch", verb, (ids[0],), (), "singleton")
    # A bare affirmative to a >1 set → RE-CONFIRM naming the choices — never dispatch-all, never loop.
    return ConsumeDecision("confirm", verb, (), tuple(ids), "bare_ambiguous")
