"""B1.0 step 2 — the question-consume wiring (red-first: these assert the WIRED behavior).

The CH-matrix rows for step 2: Jarvis's confirm/disambiguation replies become first-class
jarvis-tagged QUESTIONS (type=question, state=open, intent + candidate_ids); the walk anchors on
open questions and skips spent ones (R1 in-place stamp); the answer is consumed through the pure
resolver (multi-target dispatch, re-confirm, abandon); persist suppresses the offer while a
question is open (R3); card_outcomes is a LIST so every dispatched card greys (CH-5) with
per-target honesty (CH-6).
"""
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import delete, select

import app.agent.approval_dispatch as approval_dispatch
import app.agent.nodes as nodes
import app.agent.runner as runner
from app.agent.approval_dispatch import ApprovalDispatchOutcome
from app.db.engine import async_session
from app.db.models import PendingApproval

_MARK = f"test-b1s2-{uuid.uuid4().hex[:8]}"


@pytest.fixture(autouse=True)
def _registry():
    from app.agent.tools import calendar_tool, email_send
    from app.agent.tools.registry import tool_registry
    if tool_registry.approval_essentials("email_send") is None:
        email_send.register()
        calendar_tool.register()


async def _seed(thread, tool_name, tool_args, status="pending"):
    async with async_session() as s:
        row = PendingApproval(
            thread_id=thread, interrupt_id=f"{_MARK}-{uuid.uuid4().hex[:6]}",
            action_type=tool_name, description="d",
            payload={"tool_name": tool_name, "tool_args": tool_args}, status=status,
            expires_at=datetime.now(UTC) + timedelta(hours=24))
        s.add(row)
        await s.commit()
        await s.refresh(row)
        return str(row.id)


async def _cleanup(thread):
    async with async_session() as s:
        await s.execute(delete(PendingApproval).where(PendingApproval.thread_id == thread))
        await s.commit()


def _linked(ids, solicited=True):
    return AIMessage(content="I've queued those for your approval, Sir — shall I go ahead?",
                     additional_kwargs={"jarvis": {"type": "approval", "approval_ids": ids,
                                                   "mint_class": "fresh", "solicited": solicited}})


def _offer():
    return AIMessage(content="2 items await, Sir. Shall I brief you?",
                     additional_kwargs={"jarvis": {"type": "briefing"}})


def _state(message, history, thread):
    return {"user_message": message, "thread_id": thread,
            "messages": [*history, HumanMessage(content=message)]}


def _spy_dispatch(monkeypatch):
    rec = {"calls": []}

    async def fake(approval_id, action, resolved_via, decision=None, *, ground_thread=True):
        rec["calls"].append((str(approval_id), action))
        return ApprovalDispatchOutcome(
            kind="tool", status="executed", success=True, detail="done", thread_id="web:x")
    monkeypatch.setattr(approval_dispatch, "resolve_and_dispatch", fake)
    return rec


def _judge(monkeypatch, intent, hedged=False, change=""):
    async def fake(aid, message, recent_context="", require_pending=True):
        row = SimpleNamespace(payload={"tool_name": "email_send",
                                       "tool_args": {"to": "chintu@gmail.com", "subject": "Lunch Invitation"}},
                              action_type="email_send", thread_id="web:x", status="pending",
                              description="d")
        return runner._PresentedJudgment(approval_id=aid, row=row, intent=intent,
                                         change=change, hedged=hedged)
    monkeypatch.setattr(runner, "_judge_presented", fake)


def _question_msgs(out):
    """The open-question messages the node emitted."""
    return [m for m in out.get("messages", [])
            if ((getattr(m, "additional_kwargs", None) or {}).get("jarvis") or {}).get("type") == "question"
            and (m.additional_kwargs["jarvis"].get("state") == "open")]


# --------------------------------------------------------------------------- #
# I2 closure — "go ahead" → a TAGGED question; "I mean both" → BOTH dispatch     #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_i2_go_ahead_emits_open_question_with_candidates(monkeypatch):
    thread = f"web:{_MARK}-i2a"
    r1 = await _seed(thread, "calendar_update",
                     {"event_id": "e", "title": "Lunch with friends", "start_iso": "2026-07-19T17:00:00-04:00"})
    r2 = await _seed(thread, "email_send", {"to": "chintu@gmail.com", "subject": "Lunch Invitation", "body": "x"})
    rec = _spy_dispatch(monkeypatch)
    _judge(monkeypatch, "approve")
    try:
        out = await nodes.card_resolution_node(_state("go ahead", [_linked([r1, r2])], thread))
        assert rec["calls"] == []                              # ambiguity never dispatches
        qs = _question_msgs(out)
        assert len(qs) == 1, f"the refuse must be a tagged OPEN question, got {out.get('messages')}"
        meta = qs[0].additional_kwargs["jarvis"]
        assert set(meta["candidate_ids"]) == {r1, r2}
        assert meta["intent"] == "approve"                     # the intent carries forward
    finally:
        await _cleanup(thread)


@pytest.mark.asyncio
async def test_i2_i_mean_both_consumes_and_dispatches_both(monkeypatch):
    thread = f"web:{_MARK}-i2b"
    r1 = await _seed(thread, "calendar_update",
                     {"event_id": "e", "title": "Lunch with friends", "start_iso": "2026-07-19T17:00:00-04:00"})
    r2 = await _seed(thread, "email_send", {"to": "chintu@gmail.com", "subject": "Lunch Invitation", "body": "x"})
    rec = _spy_dispatch(monkeypatch)
    _verb(monkeypatch, "none")                                 # selection-only answer: no verb
    q = AIMessage(content="There are 2 of those pending, Sir — which one did you mean?",
                  id="q-i2b",   # the graph's add_messages assigns ids; the R1 stamp keys on it
                  additional_kwargs={"jarvis": {"type": "question", "state": "open",
                                                "intent": "approve", "candidate_ids": [r1, r2], "kind": ""}})
    try:
        out = await nodes.card_resolution_node(_state("I mean both", [_linked([r1, r2]), q], thread))
        assert sorted(a for a, _ in rec["calls"]) == sorted([r1, r2])   # BOTH dispatched
        assert {v for _, v in rec["calls"]} == {"approve"}              # with the CARRIED intent
        outs = out.get("card_outcomes") or []
        assert len(outs) == 2                                           # CH-5: every card flips
        # R1: the question is stamped consumed IN PLACE (same id, state flipped)
        stamped = [m for m in out["messages"] if getattr(m, "id", None) == q.id]
        assert stamped and stamped[0].additional_kwargs["jarvis"]["state"] == "consumed"
    finally:
        await _cleanup(thread)


# --------------------------------------------------------------------------- #
# I3 closure — the unanchored confirm is a question; "approved" consumes it     #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_i3_unanchored_confirm_is_a_question_and_approved_consumes(monkeypatch):
    thread = f"web:{_MARK}-i3"
    r1 = await _seed(thread, "email_send", {"to": "chintu@gmail.com", "subject": "Lunch Invitation", "body": "x"})
    rec = _spy_dispatch(monkeypatch)
    _judge(monkeypatch, "approve")                             # turn 1 (direct path)
    _verb(monkeypatch, "approve")                              # turn 2 ("approved" = explicit verb)
    try:
        # turn 1: bare "Send it" on an UNSOLICITED mint → the confirm must be a tagged question
        out1 = await nodes.card_resolution_node(
            _state("Send it", [_linked([r1], solicited=False)], thread))
        assert rec["calls"] == []
        qs = _question_msgs(out1)
        assert len(qs) == 1, "the unanchored-bare confirm must be an OPEN question"
        # turn 2: "approved" consumes the question → dispatches (the I3 loop is dead)
        out2 = await nodes.card_resolution_node(
            _state("approved", [_linked([r1], solicited=False), qs[0]], thread))
        assert rec["calls"] == [(r1, "approve")]
        assert (out2.get("card_outcomes") or [{}])[0].get("decision_status") == "approved"
    finally:
        await _cleanup(thread)


# --------------------------------------------------------------------------- #
# CH-1 — a spent question never re-anchors                                      #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_ch1_consumed_question_is_skipped_by_the_walk(monkeypatch):
    thread = f"web:{_MARK}-ch1"
    r1 = await _seed(thread, "email_send", {"to": "chintu@gmail.com", "subject": "Lunch Invitation", "body": "x"},
                     status="approved")                        # already resolved
    rec = _spy_dispatch(monkeypatch)
    _judge(monkeypatch, "approve")
    consumed = AIMessage(content="Which one did you mean?",
                         additional_kwargs={"jarvis": {"type": "question", "state": "consumed",
                                                       "intent": "approve", "candidate_ids": [r1], "kind": ""}})
    try:
        out = await nodes.card_resolution_node(
            _state("yes", [_linked([r1]), consumed], thread))
        # the walk must skip the consumed question → the approval linkage owns the turn →
        # live=[] (already resolved) → the bare-consent stale ack; NEVER a re-dispatch
        assert rec["calls"] == []
        assert "already taken care of" in (out.get("final_response") or "")
    finally:
        await _cleanup(thread)


# --------------------------------------------------------------------------- #
# CH-9 backstop — an offer more recent than the question owns a bare "yes"      #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_ch9_offer_after_question_owns_bare_yes(monkeypatch):
    thread = f"web:{_MARK}-ch9"
    r1 = await _seed(thread, "email_send", {"to": "chintu@gmail.com", "subject": "Lunch Invitation", "body": "x"})
    rec = _spy_dispatch(monkeypatch)
    _verb(monkeypatch, "none")                                 # bare assent → no verb of its own
    q = AIMessage(content="Just to confirm, Sir — approve the email?",
                  additional_kwargs={"jarvis": {"type": "question", "state": "open",
                                                "intent": "approve", "candidate_ids": [r1], "kind": ""}})
    try:
        out = await nodes.card_resolution_node(_state("yes", [q, _offer()], thread))
        assert rec["calls"] == []                              # the offer wins the bare yes
        assert out.get("card_handled") is not True             # → the agent answers the OFFER
    finally:
        await _cleanup(thread)


# --------------------------------------------------------------------------- #
# R3 — persist suppresses the OFFER while a question is open                    #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_r3_offer_attach_suppressed_while_question_open(monkeypatch):
    q = AIMessage(content="Which one did you mean?",
                  additional_kwargs={"jarvis": {"type": "question", "state": "open",
                                                "intent": "approve", "candidate_ids": ["x"], "kind": ""}})

    async def fake_render(mode, offer, messages):
        return "3 items await, Sir. Shall I brief you?", False   # an OFFER wants to attach
    import app.agent.briefing_state as briefing_state
    monkeypatch.setattr(briefing_state, "render_attach", fake_render)
    out = await nodes.persist_node({
        "messages": [q, HumanMessage(content="hm")], "thread_id": f"web:{_MARK}-r3",
        "user_message": "hm", "final_response": "answered", "briefing_attached": False,
        "briefing_proactive": "surface_single", "briefing_offer": "3 items await"})
    attached = [m for m in out.get("messages", [])
                if ((getattr(m, "additional_kwargs", None) or {}).get("jarvis") or {}).get("type") == "briefing"]
    assert attached == [], "no offer may mint while a question awaits its answer (R3)"


# --------------------------------------------------------------------------- #
# CH-6 — per-target honesty: one already-handled card never reads as sent       #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_ch6_mixed_batch_reply_names_per_target_results(monkeypatch):
    thread = f"web:{_MARK}-ch6"
    r1 = await _seed(thread, "email_send", {"to": "chintu@gmail.com", "subject": "Lunch Invitation", "body": "x"})
    r2 = await _seed(thread, "email_send", {"to": "amy@x.com", "subject": "Budget", "body": "y"})
    _verb(monkeypatch, "none")

    async def fake(approval_id, action, resolved_via, decision=None, *, ground_thread=True):
        if str(approval_id) == r2:                             # r2 was resolved on Telegram
            return ApprovalDispatchOutcome(kind="tool", status="not_claimed", success=False,
                                           detail="", thread_id=thread)
        return ApprovalDispatchOutcome(kind="tool", status="executed", success=True,
                                       detail="done", thread_id=thread)
    monkeypatch.setattr(approval_dispatch, "resolve_and_dispatch", fake)
    q = AIMessage(content="Which one?",
                  additional_kwargs={"jarvis": {"type": "question", "state": "open",
                                                "intent": "approve", "candidate_ids": [r1, r2], "kind": ""}})
    try:
        out = await nodes.card_resolution_node(_state("both", [_linked([r1, r2]), q], thread))
        final = (out.get("final_response") or "").lower()
        assert "already" in final                              # the not_claimed card is NAMED as such
        outs = out.get("card_outcomes") or []
        assert {o.get("decision_status") for o in outs} == {"approved", "stale"}
    finally:
        await _cleanup(thread)


# --------------------------------------------------------------------------- #
# Hedged — a hedged selection re-confirms, never dispatches (master's #4)       #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_hedged_selection_reconfirms_at_the_node(monkeypatch):
    thread = f"web:{_MARK}-hedge"
    r1 = await _seed(thread, "email_send", {"to": "chintu@gmail.com", "subject": "Lunch Invitation", "body": "x"})
    r2 = await _seed(thread, "email_send", {"to": "amy@x.com", "subject": "Budget", "body": "y"})
    rec = _spy_dispatch(monkeypatch)
    _verb(monkeypatch, "none", hedged=True)
    q = AIMessage(content="Which one?",
                  additional_kwargs={"jarvis": {"type": "question", "state": "open",
                                                "intent": "approve", "candidate_ids": [r1, r2], "kind": ""}})
    try:
        out = await nodes.card_resolution_node(
            _state("maybe do them all later", [_linked([r1, r2]), q], thread))
        assert rec["calls"] == []                              # hedged NEVER dispatches
        assert _question_msgs(out), "a hedged answer re-confirms with a fresh open question"
    finally:
        await _cleanup(thread)


# --------------------------------------------------------------------------- #
# CH-5 — the runner event builder loops the outcomes list                       #
# --------------------------------------------------------------------------- #
def test_ch5_card_outcome_events_emit_one_per_outcome():
    events = runner._card_outcome_events("web:t", [
        {"approval_id": "a1", "decision_status": "approved", "thread_id": "web:t"},
        {"approval_id": "a2", "decision_status": "rejected", "thread_id": "web:t"},
    ])
    resolved = [e for e in events if e["type"] == "decision_resolved"]
    assert {e["content"]["approval_id"] for e in resolved} == {"a1", "a2"}


# --------------------------------------------------------------------------- #
# Golden pin — the solicited fresh mint + bare yes path is UNTOUCHED            #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_golden_solicited_bare_yes_still_dispatches(monkeypatch):
    thread = f"web:{_MARK}-gold"
    r1 = await _seed(thread, "email_send", {"to": "chintu@gmail.com", "subject": "Lunch Invitation", "body": "x"})
    rec = _spy_dispatch(monkeypatch)
    _judge(monkeypatch, "approve")
    try:
        out = await nodes.card_resolution_node(_state("yes", [_linked([r1], solicited=True)], thread))
        assert rec["calls"] == [(r1, "approve")]               # R4: solicited untouched
        assert out.get("card_handled") is True
    finally:
        await _cleanup(thread)


# --------------------------------------------------------------------------- #
# Review HIGH-1 — "both" is scoped to the choices the QUESTION named            #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_both_never_dispatches_cards_the_question_did_not_name(monkeypatch):
    """A third pending card linked by an OLDER approval message must NOT ride a 'both'
    answered to a two-card question — consent scope = what was asked."""
    thread = f"web:{_MARK}-scope"
    r1 = await _seed(thread, "email_send", {"to": "chintu@gmail.com", "subject": "Lunch Invitation", "body": "x"})
    r2 = await _seed(thread, "email_send", {"to": "amy@x.com", "subject": "Budget", "body": "y"})
    r3 = await _seed(thread, "email_send", {"to": "joe@x.com", "subject": "Old Plan", "body": "z"})  # older, unnamed
    rec = _spy_dispatch(monkeypatch)
    _verb(monkeypatch, "none")
    q = AIMessage(content="Which one did you mean — or both?", id="q-scope",
                  additional_kwargs={"jarvis": {"type": "question", "state": "open",
                                                "intent": "approve", "candidate_ids": [r1, r2], "kind": ""}})
    try:
        await nodes.card_resolution_node(
            _state("both", [_linked([r3]), _linked([r1, r2]), q], thread))
        assert sorted(a for a, _ in rec["calls"]) == sorted([r1, r2]), \
            f"'both' exceeded the question's named choices: {rec['calls']}"
    finally:
        await _cleanup(thread)


# --------------------------------------------------------------------------- #
# Review MED-3 — the confirm IS the anchor: "yes" to a 1-candidate question     #
# dispatches even when other pending cards are linked elsewhere in the thread   #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_committed_yes_to_single_candidate_question_dispatches_despite_other_cards(monkeypatch):
    thread = f"web:{_MARK}-anchor"
    r1 = await _seed(thread, "email_send", {"to": "chintu@gmail.com", "subject": "Lunch Invitation", "body": "x"})
    r_other = await _seed(thread, "calendar_update",
                          {"event_id": "e", "title": "Standup", "start_iso": "2026-07-20T13:00:00-04:00"})
    rec = _spy_dispatch(monkeypatch)
    _verb2(monkeypatch, "none", committed=True)                # a real "yes" = floor-committed
    q = AIMessage(content="Just to confirm, Sir — approve the email to chintu?", id="q-anchor",
                  additional_kwargs={"jarvis": {"type": "question", "state": "open",
                                                "intent": "approve", "candidate_ids": [r1], "kind": ""}})
    try:
        out = await nodes.card_resolution_node(
            _state("yes", [_linked([r_other]), _linked([r1], solicited=False), q], thread))
        assert rec["calls"] == [(r1, "approve")], f"the confirm anchor broke: {rec['calls']}"
        assert out.get("card_handled") is True
    finally:
        await _cleanup(thread)


# --------------------------------------------------------------------------- #
# Review MED-3b — CH-4 still holds: a KIND selection reaches BEYOND the set     #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_kind_selection_still_reaches_beyond_the_questions_set(monkeypatch):
    thread = f"web:{_MARK}-reach"
    r1 = await _seed(thread, "email_send", {"to": "chintu@gmail.com", "subject": "Lunch Invitation", "body": "x"})
    r_cal = await _seed(thread, "calendar_update",
                        {"event_id": "e", "title": "Standup", "start_iso": "2026-07-20T13:00:00-04:00"})
    rec = _spy_dispatch(monkeypatch)
    _verb(monkeypatch, "none")
    q = AIMessage(content="Just to confirm — approve the email?", id="q-reach",
                  additional_kwargs={"jarvis": {"type": "question", "state": "open",
                                                "intent": "approve", "candidate_ids": [r1], "kind": ""}})
    try:
        await nodes.card_resolution_node(
            _state("no — the calendar one", [_linked([r_cal]), _linked([r1], solicited=False), q], thread))
        assert rec["calls"] == [(r_cal, "approve")], f"kind reach failed: {rec['calls']}"
    finally:
        await _cleanup(thread)


# --------------------------------------------------------------------------- #
# Review HIGH-2 — a successful multi-reject reads as DISCARDED, never FAILED    #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_multi_reject_reply_says_discarded_not_failed(monkeypatch):
    thread = f"web:{_MARK}-rej"
    r1 = await _seed(thread, "email_send", {"to": "chintu@gmail.com", "subject": "Lunch Invitation", "body": "x"})
    r2 = await _seed(thread, "email_send", {"to": "amy@x.com", "subject": "Budget", "body": "y"})
    _verb(monkeypatch, "reject")

    async def fake(approval_id, action, resolved_via, decision=None, *, ground_thread=True):
        # a REAL reject outcome: status=rejected, success=False (nothing sends on a discard)
        return ApprovalDispatchOutcome(kind="tool", status="rejected", success=False,
                                       detail="", thread_id=thread)
    monkeypatch.setattr(approval_dispatch, "resolve_and_dispatch", fake)
    q = AIMessage(content="Which one?", id="q-rej",
                  additional_kwargs={"jarvis": {"type": "question", "state": "open",
                                                "intent": "approve", "candidate_ids": [r1, r2], "kind": ""}})
    try:
        out = await nodes.card_resolution_node(_state("reject both", [_linked([r1, r2]), q], thread))
        final = (out.get("final_response") or "")
        assert "FAILED" not in final, f"successful discards reported as failures: {final!r}"
        assert "discarded" in final.lower()
        assert "Chintu" not in final or True   # no capitalize() mangling assertion below
        # describe_card content survives un-mangled (no .capitalize() lowercasing)
        assert "chintu@gmail.com" in final
    finally:
        await _cleanup(thread)


# --------------------------------------------------------------------------- #
# Review LOW-5 — a committed answer to an all-resolved question gets the ack    #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_answer_to_fully_resolved_question_gets_honest_ack(monkeypatch):
    thread = f"web:{_MARK}-gone"
    r1 = await _seed(thread, "email_send", {"to": "chintu@gmail.com", "subject": "Lunch Invitation", "body": "x"},
                     status="approved")                          # resolved on another channel
    rec = _spy_dispatch(monkeypatch)
    _verb(monkeypatch, "none")
    q = AIMessage(content="Just to confirm — approve the email?", id="q-gone",
                  additional_kwargs={"jarvis": {"type": "question", "state": "open",
                                                "intent": "approve", "candidate_ids": [r1], "kind": ""}})
    try:
        out = await nodes.card_resolution_node(_state("yes", [q], thread))
        assert rec["calls"] == []
        assert "already taken care of" in (out.get("final_response") or "")
    finally:
        await _cleanup(thread)


# --------------------------------------------------------------------------- #
# Review MED-4 — an edit question carries the CHANGE through the narrow         #
# --------------------------------------------------------------------------- #
def test_question_message_carries_change():
    m = nodes._question_message("Which one should I change?", "edit", ["a", "b"],
                                change="make it shorter")
    assert m.additional_kwargs["jarvis"]["change"] == "make it shorter"


# --------------------------------------------------------------------------- #
# Step-2.1 — the ONE consent gate on BOTH dispatch paths                        #
# --------------------------------------------------------------------------- #
def _verb(monkeypatch, verb, hedged=False, change=""):
    """Pin the card-agnostic answer-verb judge (the consume path's verb source)."""
    from types import SimpleNamespace as NS

    async def fake(user_message, question, recent_context=""):
        return NS(verb=verb, hedged=hedged, change=change)
    import app.agent.decision_resolver as dr
    monkeypatch.setattr(dr, "resolve_answer_verb", fake)


@pytest.mark.asyncio
async def test_h1_hedged_direct_send_reconfirms(monkeypatch):
    """'send it, maybe after lunch' on a SOLICITED card: judge says approve+hedged → the
    DIRECT path must re-confirm, never dispatch (the gate lives on both surfaces)."""
    thread = f"web:{_MARK}-h1"
    r1 = await _seed(thread, "email_send", {"to": "chintu@gmail.com", "subject": "Lunch Invitation", "body": "x"})
    rec = _spy_dispatch(monkeypatch)
    _judge(monkeypatch, "approve", hedged=True)
    try:
        out = await nodes.card_resolution_node(
            _state("send it, maybe after lunch", [_linked([r1], solicited=True)], thread))
        assert rec["calls"] == [], f"a hedged send dispatched: {rec['calls']}"
        assert _question_msgs(out), "the hedged re-confirm must be an open question"
    finally:
        await _cleanup(thread)


@pytest.mark.asyncio
async def test_h2_wrong_card_name_on_consume_never_lone_singleton(monkeypatch):
    """'approve the one to bob@x.com' answering a question whose only live card is to chintu:
    a name matching ZERO candidates must re-confirm — never the lone-singleton dispatch."""
    thread = f"web:{_MARK}-h2"
    r1 = await _seed(thread, "email_send", {"to": "chintu@gmail.com", "subject": "Lunch Invitation", "body": "x"})
    rec = _spy_dispatch(monkeypatch)
    _verb(monkeypatch, "approve")
    q = AIMessage(content="Just to confirm — approve the email to chintu?", id="q-h2",
                  additional_kwargs={"jarvis": {"type": "question", "state": "open",
                                                "intent": "approve", "candidate_ids": [r1], "kind": ""}})
    try:
        out = await nodes.card_resolution_node(
            _state("approve the one to bob@x.com", [_linked([r1], solicited=False), q], thread))
        assert rec["calls"] == [], f"wrong-card name dispatched: {rec['calls']}"
        assert out.get("card_handled") is True                  # re-confirm, not a silent agent turn
    finally:
        await _cleanup(thread)


@pytest.mark.asyncio
async def test_reject_inversion_dead_bare_yes_to_reject_question_rejects(monkeypatch):
    """(1)'s node-level seal: 'yes' consenting to a REJECT question → verb none → the CARRIED
    reject dispatches. It must never send."""
    thread = f"web:{_MARK}-inv"
    r1 = await _seed(thread, "email_send", {"to": "chintu@gmail.com", "subject": "Lunch Invitation", "body": "x"})
    rec = _spy_dispatch(monkeypatch)
    _verb2(monkeypatch, "none", committed=True)                # a real "yes" = floor-committed
    q = AIMessage(content="Just to confirm, Sir — discard the email to chintu?", id="q-inv",
                  additional_kwargs={"jarvis": {"type": "question", "state": "open",
                                                "intent": "reject", "candidate_ids": [r1], "kind": ""}})
    try:
        await nodes.card_resolution_node(_state("yes", [_linked([r1], solicited=False), q], thread))
        assert rec["calls"] == [(r1, "reject")], f"the carried reject did not govern: {rec['calls']}"
    finally:
        await _cleanup(thread)


@pytest.mark.asyncio
async def test_hedged_consume_dispatch_blocked_by_the_gate(monkeypatch):
    """Belt at the gate: even if a hedged answer reached the dispatch branch, the ONE gate
    re-confirms ('do them all later' → hedged → zero resolve_and_dispatch)."""
    thread = f"web:{_MARK}-hgate"
    r1 = await _seed(thread, "email_send", {"to": "chintu@gmail.com", "subject": "Lunch Invitation", "body": "x"})
    r2 = await _seed(thread, "email_send", {"to": "amy@x.com", "subject": "Budget", "body": "y"})
    rec = _spy_dispatch(monkeypatch)
    _verb(monkeypatch, "none", hedged=True)
    q = AIMessage(content="Which one — or both?", id="q-hgate",
                  additional_kwargs={"jarvis": {"type": "question", "state": "open",
                                                "intent": "approve", "candidate_ids": [r1, r2], "kind": ""}})
    try:
        await nodes.card_resolution_node(_state("do them all later", [_linked([r1, r2]), q], thread))
        assert rec["calls"] == []
    finally:
        await _cleanup(thread)


# --------------------------------------------------------------------------- #
# Step-2.2 — the info route + the inverted bare-dispatch polarity (node level)  #
# --------------------------------------------------------------------------- #
def _verb2(monkeypatch, verb, hedged=False, change="", committed=False):
    from types import SimpleNamespace as NS

    async def fake(user_message, question, recent_context=""):
        return NS(verb=verb, hedged=hedged, change=change, committed=committed)
    import app.agent.decision_resolver as dr
    monkeypatch.setattr(dr, "resolve_answer_verb", fake)


@pytest.mark.asyncio
async def test_info_request_routes_to_agent_question_stays_open(monkeypatch):
    """'read it back to me' → the AGENT answers (no dispatch, no re-ask) and the question
    stays OPEN so the following 'yes' still consumes it."""
    thread = f"web:{_MARK}-info"
    r1 = await _seed(thread, "email_send", {"to": "chintu@gmail.com", "subject": "Lunch Invitation", "body": "x"})
    rec = _spy_dispatch(monkeypatch)
    _verb2(monkeypatch, "info")
    q = AIMessage(content="Just to confirm — approve the email to chintu?", id="q-info",
                  additional_kwargs={"jarvis": {"type": "question", "state": "open",
                                                "intent": "approve", "candidate_ids": [r1], "kind": ""}})
    try:
        out = await nodes.card_resolution_node(
            _state("read it back to me", [_linked([r1], solicited=False), q], thread))
        assert rec["calls"] == []                              # NO send on an info request
        assert out.get("card_handled") is not True             # the agent answers it
        stamped = [m for m in out.get("messages", []) if getattr(m, "id", None) == q.id]
        assert not stamped                                     # the question is NOT stamped — stays open
    finally:
        await _cleanup(thread)


@pytest.mark.asyncio
async def test_uncommitted_none_singleton_reconfirms_at_node(monkeypatch):
    """'works for me' (none, unhedged, NOT committed) on a 1-candidate question → re-confirm."""
    thread = f"web:{_MARK}-uncmt"
    r1 = await _seed(thread, "email_send", {"to": "chintu@gmail.com", "subject": "Lunch Invitation", "body": "x"})
    rec = _spy_dispatch(monkeypatch)
    _verb2(monkeypatch, "none", committed=False)
    q = AIMessage(content="Just to confirm — approve the email?", id="q-uncmt",
                  additional_kwargs={"jarvis": {"type": "question", "state": "open",
                                                "intent": "approve", "candidate_ids": [r1], "kind": ""}})
    try:
        out = await nodes.card_resolution_node(
            _state("works for me", [_linked([r1], solicited=False), q], thread))
        assert rec["calls"] == []
        assert _question_msgs(out), "must re-confirm with an open question"
    finally:
        await _cleanup(thread)


# --------------------------------------------------------------------------- #
# B1.1 — issue-5: a named kind reaches a live card OUTSIDE the referent's set   #
# on the DIRECT path (the 9cc01f1c class, reproduced locally)                   #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_b11_issue5_named_calendar_resolves_across_linkages(monkeypatch):
    """Referent = the (solicited) EMAIL approval message; a live calendar card is linked by an
    OLDER approval message. 'Now approve that pending calendar approval' must resolve the
    CALENDAR card — never re-mint, never 'already queued', never unresolvable."""
    thread = f"web:{_MARK}-i5"
    r_cal = await _seed(thread, "calendar_update",
                        {"event_id": "e", "title": "Lunch with friends", "start_iso": "2026-07-19T17:00:00-04:00"})
    r_email = await _seed(thread, "email_send", {"to": "chintu@gmail.com", "subject": "Lunch Invitation", "body": "x"})
    rec = _spy_dispatch(monkeypatch)
    _judge(monkeypatch, "approve")
    try:
        out = await nodes.card_resolution_node(
            _state("Now approve that pending calendar approval",
                   [_linked([r_cal]), _linked([r_email])], thread))
        assert rec["calls"] == [(r_cal, "approve")], f"issue-5 not closed: {rec['calls']}"
        assert (out.get("card_outcomes") or [{}])[0].get("approval_id") == r_cal
    finally:
        await _cleanup(thread)


@pytest.mark.asyncio
async def test_b11_named_kind_matching_two_cards_asks_which(monkeypatch):
    thread = f"web:{_MARK}-i5b"
    c1 = await _seed(thread, "calendar_update",
                     {"event_id": "e1", "title": "Lunch with friends", "start_iso": "2026-07-19T17:00:00-04:00"})
    c2 = await _seed(thread, "calendar_create",
                     {"title": "Standup", "start_iso": "2026-07-21T13:00:00-04:00"})
    r_email = await _seed(thread, "email_send", {"to": "chintu@gmail.com", "subject": "Lunch Invitation", "body": "x"})
    rec = _spy_dispatch(monkeypatch)
    _judge(monkeypatch, "approve")
    try:
        out = await nodes.card_resolution_node(
            _state("approve the calendar one",
                   [_linked([c1]), _linked([c2]), _linked([r_email])], thread))
        assert rec["calls"] == []                              # two calendars → never guess
        qs = _question_msgs(out)
        assert qs and set(qs[0].additional_kwargs["jarvis"]["candidate_ids"]) == {c1, c2}
    finally:
        await _cleanup(thread)
