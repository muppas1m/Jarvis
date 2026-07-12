"""B1.0 F3 — the pure answer-consumption resolver, unit-tested in ISOLATION (the seam-first mandate).

These are the reproduce-first guards for the Round-2 red-team holes, encoded at the resolver level
before any node wiring:
  CH-2 (HIGHEST-PRIORITY seal): a verb-flipping answer never dispatches the carried verb.
  CH-3: a bare affirmative to a >1 set RE-CONFIRMS — never dispatch-all, never an identical re-ask.
  CH-4: SELECTION is computed over the LIVE candidates passed in — never a frozen set.
Each assertion states the CORRECT behavior; the pre-F3 node (dispatch-all / infinite loop) would
violate it — that is the "red" these guards lock down before step-2 wiring reproduces them live.
"""
import pytest

from app.agent.answer_consumption import ConsumeDecision, resolve_answer
from app.agent.tools import calendar_tool, email_send
from app.agent.tools.registry import tool_registry


@pytest.fixture(autouse=True)
def _registry():
    # NAME selection reads the declared essentials — ensure the tools are registered.
    if tool_registry.approval_essentials("email_send") is None:
        email_send.register()
        calendar_tool.register()


class _Card:
    """A light stand-in for UnifiedApprovalCard (duck-typed: approval_id/kind/tool_name/tool_args)."""
    def __init__(self, approval_id, tool_name, tool_args, kind=None):
        self.approval_id = approval_id
        self.tool_name = tool_name
        self.tool_args = tool_args
        self.kind = kind or ("email" if tool_name == "email_send" else "tool")


def _cal(aid="cal", title="Lunch with friends", start="2026-07-05T17:00:00-04:00"):
    return _Card(aid, "calendar_update", {"event_id": "e1", "title": title, "start_iso": start})


def _email(aid="email", to="chintu@gmail.com", subject="Lunch Invitation"):
    return _Card(aid, "email_send", {"to": to, "subject": subject, "body": "hi"})


# --------------------------------------------------------------------------- #
# CH-2 ⭐ — the wrong-verb seal: the answer's verb OVERRIDES the carried intent  #
# --------------------------------------------------------------------------- #
def test_ch2_reject_both_on_approve_question_dispatches_zero_approves():
    """question{approve,[cal,email]} + 'reject both' ⇒ reject both, ZERO approves."""
    d = resolve_answer("reject both", [_cal(), _email()], answer_verb="reject", carried_intent="approve")
    assert d.action == "dispatch" and d.verb == "reject"          # the answer's verb wins
    assert set(d.selection) == {"cal", "email"}
    assert d.verb != "approve"                                    # the carried intent NEVER leaks through


def test_ch2_mirror_approve_both_on_reject_question_dispatches_zero_rejects():
    """Mirror: question{reject,[cal,email]} + 'approve both' ⇒ approve both, ZERO rejects."""
    d = resolve_answer("approve both", [_cal(), _email()], answer_verb="approve", carried_intent="reject")
    assert d.action == "dispatch" and d.verb == "approve"
    assert set(d.selection) == {"cal", "email"} and d.verb != "reject"


def test_ch2_cancel_both_is_a_reject_not_the_carried_approve():
    """'cancel both' judged reject ⇒ reject both — never send/create what the master cancelled."""
    d = resolve_answer("actually cancel both", [_cal(), _email()], answer_verb="reject", carried_intent="approve")
    assert d.verb == "reject" and d.action == "dispatch"


def test_ch2_selector_only_answer_uses_the_carried_intent():
    """A pure selector ('both') expresses NO verb (judge → unclear) ⇒ the carried intent governs."""
    approve = resolve_answer("both", [_cal(), _email()], answer_verb="unclear", carried_intent="approve")
    assert approve.verb == "approve" and approve.action == "dispatch" and set(approve.selection) == {"cal", "email"}
    reject = resolve_answer("both", [_cal(), _email()], answer_verb="unclear", carried_intent="reject")
    assert reject.verb == "reject"                                # selector-only ⇒ carried, not a guess


# --------------------------------------------------------------------------- #
# CH-3 — a bare affirmative to a >1 set RE-CONFIRMS (never dispatch-all/loop)   #
# --------------------------------------------------------------------------- #
def test_ch3_bare_yes_to_multi_reconfirms_naming_choices():
    d = resolve_answer("yeah, go ahead", [_cal(), _email()], answer_verb="approve", carried_intent="approve")
    assert d.action == "confirm"                                 # NOT dispatch (seal), NOT a silent re-ask
    assert set(d.choices) == {"cal", "email"}                    # names the choices → progress, not a loop
    assert d.selection == ()                                     # nothing dispatched on ambiguity


def test_ch3_bare_yes_to_singleton_dispatches():
    d = resolve_answer("yes", [_cal()], answer_verb="approve", carried_intent="approve")
    assert d.action == "dispatch" and d.selection == ("cal",)


# --------------------------------------------------------------------------- #
# CH-4 — SELECTION over the LIVE candidates (never a frozen set)                #
# --------------------------------------------------------------------------- #
def test_ch4_kind_reaches_the_calendar_card_among_live_candidates():
    """'the calendar one' resolves the live calendar card even amid emails (issue-5 target class)."""
    d = resolve_answer("approve the calendar one", [_cal(), _email()], answer_verb="approve", carried_intent="approve")
    assert d.action == "dispatch" and d.selection == ("cal",) and d.verb == "approve"


def test_ch4_named_kind_absent_from_candidates_confirms_never_misnames():
    """'the calendar one' with only emails live → confirm (never resolve an email as 'the calendar')."""
    d = resolve_answer("the calendar one", [_email("e1"), _email("e2", to="amy@x.com", subject="Budget")],
                       answer_verb="unclear", carried_intent="approve")
    assert d.action == "confirm" and d.reason == "no_match" and set(d.choices) == {"e1", "e2"}


def test_ch4_kind_narrowed_to_multiple_confirms():
    """Two calendar cards + 'the calendar one' → ambiguous → confirm naming both (seal: never guess)."""
    d = resolve_answer("the calendar event", [_cal("c1"), _cal("c2", title="Standup")],
                       answer_verb="approve", carried_intent="approve")
    assert d.action == "confirm" and set(d.choices) == {"c1", "c2"} and d.reason == "narrowed_ambiguous"


def test_ch4_name_selection_by_recipient_local_part():
    """'send the one to chintu' selects the email card by recipient (reuses the s1b matcher)."""
    d = resolve_answer("send the one to chintu", [_cal(), _email(to="chintu@gmail.com")],
                       answer_verb="approve", carried_intent="approve")
    assert d.action == "dispatch" and d.selection == ("email",)


# --------------------------------------------------------------------------- #
# Reject-both closing + edit/skip pass-through + abandon + empty               #
# --------------------------------------------------------------------------- #
def test_reject_both_multi_target_closes_the_1454_gap():
    """The locked constraint: the multi-card path must close 'reject both' (the :1454 refuse
    blocked BOTH verbs today)."""
    d = resolve_answer("reject both of them", [_cal(), _email()], answer_verb="reject", carried_intent="approve")
    assert d.action == "dispatch" and d.verb == "reject" and len(d.selection) == 2


def test_edit_verb_passes_through_on_singleton():
    d = resolve_answer("change the time to 10am", [_cal()], answer_verb="edit", carried_intent="approve")
    assert d.action == "dispatch" and d.verb == "edit"


def test_off_topic_with_no_selection_abandons():
    d = resolve_answer("what's the weather today?", [_cal(), _email()], answer_verb="unrelated", carried_intent="approve")
    assert d.action == "abandon" and d.reason == "off_topic"


def test_unrelated_answer_that_names_a_card_still_abandons_never_dispatches():
    """Self-adversarial guard: a non-consent comment that MENTIONS a card ('the calendar one is
    wrong') is judged `unrelated` → abandon, NEVER a carried-intent dispatch of the named card."""
    d = resolve_answer("the calendar one is wrong", [_cal(), _email()],
                       answer_verb="unrelated", carried_intent="approve")
    assert d.action == "abandon" and d.selection == ()           # the named card is NOT dispatched


def test_show_others_request_abandons_to_the_agent():
    d = resolve_answer("what else is pending?", [_cal(), _email()], answer_verb="show_others", carried_intent="approve")
    assert d.action == "abandon"


def test_no_live_candidates_abandons():
    d = resolve_answer("both", [], answer_verb="approve", carried_intent="approve")
    assert d.action == "abandon" and d.reason == "no_live_candidates"


def test_decision_is_immutable():
    d = resolve_answer("yes", [_cal()], answer_verb="approve", carried_intent="approve")
    assert isinstance(d, ConsumeDecision)
    with pytest.raises(Exception):
        d.verb = "reject"          # frozen dataclass — the decision can't be mutated after the fact


# --------------------------------------------------------------------------- #
# F4 — the non-committal gate: an unclear verb with NO selector never dispatches#
# (reviewer live catch: "hmm, maybe" on a single card returned dispatch/approve)#
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("noncommittal", ["hmm, maybe", "up to you", "ok", "yeah maybe later"])
def test_f4_noncommittal_answer_reasks_never_dispatches(noncommittal):
    """Single card × a judged-unclear, selector-less answer → RE-ASK. Zero (*, approve) in the
    decision — the carried intent can never manufacture a dispatch ('hmm maybe' ≠ yes)."""
    d = resolve_answer(noncommittal, [_email()], answer_verb="unclear", carried_intent="approve")
    assert d.action == "confirm", f"{noncommittal!r} must re-ask, got {d}"
    assert d.selection == ()                                     # nothing dispatched
    assert d.choices == ("email",)                               # the re-ask names the card
    assert d.reason == "noncommittal"


def test_f4_noncommittal_never_manufactures_a_reject_either():
    """Same bar every flow: 'hmm maybe' to a reject-origin question manufactures no discard."""
    d = resolve_answer("hmm, maybe", [_email()], answer_verb="unclear", carried_intent="reject")
    assert d.action == "confirm" and d.selection == ()


def test_f4_golden_committed_yes_still_dispatches():
    """The golden path survives the gate: a committed verb on one card dispatches."""
    for msg in ("yes", "send it", "go ahead"):
        d = resolve_answer(msg, [_email()], answer_verb="approve", carried_intent="approve")
        assert d.action == "dispatch" and d.selection == ("email",), msg


def test_f4_selector_only_fallback_survives():
    """The frozen selector-only rule is untouched: 'both' (judged unclear) still dispatches with
    the carried intent — a selection IS a committed answer to 'which one?'."""
    d = resolve_answer("both", [_cal(), _email()], answer_verb="unclear", carried_intent="approve")
    assert d.action == "dispatch" and d.verb == "approve" and len(d.selection) == 2


# --------------------------------------------------------------------------- #
# F4 domain seal — a dispatch can only ever carry a judge-vocabulary verb       #
# (red-team catch: garbage/empty carried_intent dispatched through all/filter)  #
# --------------------------------------------------------------------------- #
def test_f4_out_of_domain_carried_never_dispatches_via_all_selector():
    """('both', unclear, carried='') must never dispatch verb='' — nothing was consented to."""
    d = resolve_answer("both", [_cal(), _email()], answer_verb="unclear", carried_intent="")
    assert d.action == "confirm" and d.selection == ()
    assert d.reason == "no_committed_verb"


def test_f4_out_of_domain_carried_never_dispatches_via_filter():
    """('the one to chintu', unclear, carried='show_others') → confirm, never dispatch(show_others)."""
    d = resolve_answer("the one to chintu", [_cal(), _email()],
                       answer_verb="unclear", carried_intent="show_others")
    assert d.action == "confirm" and d.selection == ()


# --------------------------------------------------------------------------- #
# F5.1 — the all-selector fires ONLY on explicit selector forms                 #
# (red-team: idioms/content-words manufactured dispatch-all)                    #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("idiom", [
    "yes go ahead — that's all for now",       # idiom: "that's all"
    "don't send the email at all",             # intensifier: "at all"
    "you don't have to ask every time — just send it",   # content: "every time"
])
def test_f51_idiomatic_all_never_dispatches_all(idiom):
    """An idiom containing 'all'/'every' is NOT an all-selection — with >1 candidates the
    mandated CH-3 path (confirm) applies, never dispatch-all."""
    d = resolve_answer(idiom, [_email("e1"), _email("e2", to="amy@x.com", subject="Budget"),
                               _email("e3", to="joe@x.com", subject="Plan")],
                       answer_verb="approve", carried_intent="approve")
    assert d.action == "confirm", f"{idiom!r} dispatched: {d}"
    assert d.selection == ()


@pytest.mark.parametrize("explicit", ["both", "approve them all", "all of them",
                                      "reject all of them", "all three"])
def test_f51_true_selector_forms_still_dispatch_all(explicit):
    d = resolve_answer(explicit, [_cal(), _email()],
                       answer_verb="unclear" if explicit == "both" else "approve",
                       carried_intent="approve")
    assert d.action == "dispatch" and len(d.selection) == 2, f"{explicit!r} -> {d}"


def test_f51_the_two_falls_to_kind_filter_confirms():
    """'reject the two emails' of THREE email candidates: no longer an all-selection — the kind
    filter matches all three → confirm (the safe interim until B1.1 does cardinality)."""
    d = resolve_answer("reject the two emails",
                       [_email("e1"), _email("e2", to="amy@x.com", subject="Budget"),
                        _email("e3", to="joe@x.com", subject="Plan")],
                       answer_verb="reject", carried_intent="reject")
    assert d.action == "confirm" and d.selection == ()


# --------------------------------------------------------------------------- #
# F5.2 — common-word local-parts don't count as naming a recipient              #
# (red-team: "yes I will" narrowed to will@company.com via the auxiliary)       #
# --------------------------------------------------------------------------- #
def test_f52_auxiliary_will_never_selects_the_will_card():
    """'yes I will — go ahead' on [will@, bob@]: the auxiliary 'will' is not a selection —
    the CH-3 re-confirm applies (never a fabricated narrowed_singleton)."""
    cards = [_email("ew", to="will@company.com", subject="Q3"),
             _email("e2", to="bob@x.com", subject="Budget")]
    d = resolve_answer("yes I will — go ahead", cards, answer_verb="approve", carried_intent="approve")
    assert d.action == "confirm", f"fabricated selection: {d}"
    assert d.selection == ()


@pytest.mark.parametrize("word,addr", [("may", "may@corp.com"), ("mark", "mark@corp.com")])
def test_f52_dictionary_word_locals_dont_select(word, addr):
    cards = [_email("ex", to=addr, subject="Q3"), _email("e2", to="bob@x.com", subject="Budget")]
    d = resolve_answer(f"you {word} as well go ahead", cards, answer_verb="approve", carried_intent="approve")
    assert d.action == "confirm" and d.selection == ()


def test_f52_full_address_is_always_sufficient_evidence():
    """The stop-set gates only the local-part shortcut — the full address still selects."""
    cards = [_email("ew", to="will@company.com", subject="Q3"),
             _email("e2", to="bob@x.com", subject="Budget")]
    d = resolve_answer("send the one to will@company.com", cards,
                       answer_verb="approve", carried_intent="approve")
    assert d.action == "dispatch" and d.selection == ("ew",)


def test_f52_normal_name_locals_still_select():
    """bob/chintu-class locals are untouched — selection by name survives."""
    d = resolve_answer("send the one to chintu", [_cal(), _email(to="chintu@gmail.com")],
                       answer_verb="approve", carried_intent="approve")
    assert d.action == "dispatch" and d.selection == ("email",)


# --- floor regressions: the s1b matcher is SHARED with the honest floors — they must not move ---
def test_f52_floor_regression_bob_amy_unchanged():
    from app.agent.approval_essentials import card_essentials_named
    args = {"to": "bob@example.com", "subject": "Q3 numbers"}
    assert card_essentials_named("I've drafted the Q3 numbers email to Bob.", "email_send", args)
    assert card_essentials_named("I've drafted the Q3 numbers email to bob@example.com.", "email_send", args)
    assert not card_essentials_named("I've drafted the Q3 numbers email.", "email_send", args)
    args2 = {"to": "amy@x.com", "subject": "Budget"}
    assert card_essentials_named("Queued the Budget email to Amy.", "email_send", args2)


def test_f52_floor_consequence_stopword_local_floors():
    """DECLARED consequence: prose naming a stop-word local ('to Will') no longer counts as
    naming → the floor fires (describes the card). Safe direction: floor MORE, never less."""
    from app.agent.approval_essentials import card_essentials_named
    args = {"to": "will@company.com", "subject": "Q3"}
    assert not card_essentials_named("I've drafted the Q3 email to Will.", "email_send", args)
    # the full address still names it — the floor stands down on unambiguous evidence
    assert card_essentials_named("I've drafted the Q3 email to will@company.com.", "email_send", args)


# --------------------------------------------------------------------------- #
# Step 2 — the hedged axis (master's #4 call): a hedged answer NEVER dispatches #
# --------------------------------------------------------------------------- #
def test_hedged_selection_reconfirms_never_dispatches():
    """'maybe do them all later' (judge: hedged selection) → re-confirm, never dispatch-all."""
    d = resolve_answer("maybe do them all later", [_cal(), _email()],
                       answer_verb="unclear", carried_intent="approve", hedged=True)
    assert d.action == "confirm" and d.selection == () and d.reason == "hedged"


def test_hedged_verb_reconfirms_too():
    """'maybe send it' (judge: approve but hedged) on one card → re-confirm, never send."""
    d = resolve_answer("maybe send it", [_email()],
                       answer_verb="approve", carried_intent="approve", hedged=True)
    assert d.action == "confirm" and d.selection == ()


def test_unhedged_default_keeps_the_golden_path():
    d = resolve_answer("both", [_cal(), _email()], answer_verb="unclear", carried_intent="approve")
    assert d.action == "dispatch"          # the default (hedged=False) changes nothing


# --------------------------------------------------------------------------- #
# Step 2 — the INTERIM mixed-kind-all guard (B1.1 addendum): a kind-qualified   #
# "all" over a set containing OTHER kinds re-confirms until B1.1 can scope it   #
# --------------------------------------------------------------------------- #
def test_kind_qualified_all_over_mixed_set_reconfirms():
    """'approve both emails' over [e1,e2,cal] → confirm (never dispatches the calendar card)."""
    d = resolve_answer("approve both emails, send them",
                       [_email("e1"), _email("e2", to="amy@x.com", subject="Budget"), _cal()],
                       answer_verb="approve", carried_intent="approve")
    assert d.action == "confirm", f"scope-exceeding all dispatched: {d}"
    assert d.selection == () and d.reason == "mixed_kind_all"


def test_bare_both_on_mixed_set_still_dispatches_all():
    """The I2 golden: bare 'I mean both' (no kind qualifier) keeps the frozen dispatch-all."""
    d = resolve_answer("I mean both", [_cal(), _email()], answer_verb="unclear", carried_intent="approve")
    assert d.action == "dispatch" and len(d.selection) == 2


def test_kind_qualified_all_over_homogeneous_set_dispatches():
    """'both emails' when EVERY candidate is an email → the kind adds nothing → dispatch-all."""
    d = resolve_answer("send both emails",
                       [_email("e1"), _email("e2", to="amy@x.com", subject="Budget")],
                       answer_verb="approve", carried_intent="approve")
    assert d.action == "dispatch" and len(d.selection) == 2
