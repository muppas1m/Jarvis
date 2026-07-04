"""A2 s2 — consent over the CONVERSATION: the seal's invariants ported red-bar-first.

The seal (cd1a732) protected these invariants with the queue-coupling machinery
(presented_approval_id + the token gate). s2 re-keys them onto the conversation: the target is
code-extracted from the most recent jarvis-tagged approval message (never a client pointer,
never oldest-pending, never token matching); the judge keeps intent only; the claim keeps
at-most-once; refusals name real state (fabricated reasons structurally impossible).

RED-BAR EVIDENCE: this file is written BEFORE s2's code exists and must FAIL against the
pre-s2 tree (the node passes through without a presented_approval_id — no dispatch, no honest
refusal). The red run (command + failure list) is captured in the batch narration.
"""
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import delete

import app.agent.approval_dispatch as approval_dispatch
import app.agent.nodes as nodes
import app.agent.runner as runner
from app.agent.approval_dispatch import ApprovalDispatchOutcome
from app.db.engine import async_session
from app.db.models import PendingApproval

_MARK = f"test-s2-{uuid.uuid4().hex[:8]}"


async def _seed_card(thread, tool_name="email_send",
                     tool_args=None, status="pending"):
    tool_args = tool_args or {"to": "fernandes@yahoo.me", "subject": "Delivery Pickup", "body": "hi"}
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


def _approval_msg(ids, solicited=True, text="I've queued an email for your approval, Sir — shall I go ahead?"):
    return AIMessage(content=text, additional_kwargs={"jarvis": {
        "type": "approval", "approval_ids": ids if isinstance(ids, list) else [ids],
        "mint_class": "fresh", "solicited": solicited}})


def _offer_msg(text="2 items await your attention when you're ready, Sir. Shall I brief you?"):
    return AIMessage(content=text, additional_kwargs={"jarvis": {"type": "briefing"}})


def _state(message, history, thread):
    return {"user_message": message, "thread_id": thread, "presented_approval_id": "",
            "presented_via": "", "messages": [*history, HumanMessage(content=message)]}


def _spy_dispatch(monkeypatch):
    rec = {"calls": []}

    async def fake(approval_id, action, resolved_via, decision=None, *, ground_thread=True):
        rec["calls"].append((str(approval_id), action))
        return ApprovalDispatchOutcome(
            kind="tool", status="executed", success=True, detail="done", thread_id="web:x")
    monkeypatch.setattr(approval_dispatch, "resolve_and_dispatch", fake)
    return rec


def _judge_intent(monkeypatch, intent):
    """Pin the strong-model judge's INTENT (the model-dependent half); the TARGET selection
    under test is code-owned and must never depend on this."""
    async def fake(aid, message, recent_context="", require_pending=True):
        from types import SimpleNamespace
        row = SimpleNamespace(payload={"tool_name": "email_send",
                                       "tool_args": {"to": "fernandes@yahoo.me", "subject": "x"}},
                              action_type="email_send", thread_id="web:x", status="pending",
                              description="Execute email_send")
        return runner._PresentedJudgment(approval_id=aid, row=row, intent=intent, change="")
    monkeypatch.setattr(runner, "_judge_presented", fake)


# --------------------------------------------------------------------------- #
# Ported seal invariant 1 — never resolve the wrong card / refuse honestly      #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_generic_send_with_two_linked_targets_refuses_honestly(monkeypatch):
    thread = f"web:{_MARK}-two"
    r1 = await _seed_card(thread, tool_args={"to": "fernandes@yahoo.me", "subject": "Pickup", "body": "a"})
    r2 = await _seed_card(thread, tool_args={"to": "boat@x.com", "subject": "Boat Party", "body": "b"})
    rec = _spy_dispatch(monkeypatch)
    _judge_intent(monkeypatch, "approve")
    try:
        out = await nodes.card_resolution_node(
            _state("Send it", [_approval_msg([r1, r2])], thread))
        assert rec["calls"] == []                                  # NOTHING dispatched
        assert out.get("card_handled") is True                     # the turn answered
        low = (out.get("final_response") or "").lower()
        assert "fernandes" in low and ("boat" in low)              # names the real choices
        assert "not what you named" not in low                     # never a fabricated reason
    finally:
        await _cleanup(thread)


# --------------------------------------------------------------------------- #
# Ported seal invariant 2 — stale/expired → honest ack, never substitute        #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_stale_target_honest_ack_never_substitutes(monkeypatch):
    thread = f"web:{_MARK}-stale"
    r1 = await _seed_card(thread, status="executed")               # the linked card: resolved
    r2 = await _seed_card(thread, tool_args={"to": "other@x.com", "subject": "Other", "body": "z"})
    rec = _spy_dispatch(monkeypatch)
    _judge_intent(monkeypatch, "approve")
    try:
        out = await nodes.card_resolution_node(
            _state("approve it", [_approval_msg([r1])], thread))   # r2 has NO linked message
        assert rec["calls"] == []                                  # NEVER substitute r2
        assert out.get("card_handled") is True
        assert "already" in (out.get("final_response") or "").lower()   # honest ack
    finally:
        await _cleanup(thread)


# --------------------------------------------------------------------------- #
# Ported seal invariant 3 — named-different-target → confirm, never dispatch    #
# (the deterministic backstop: addresses / quoted strings / KIND words)         #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_foreign_email_address_confirms_not_dispatches(monkeypatch):
    thread = f"web:{_MARK}-addr"
    r1 = await _seed_card(thread)                                  # to fernandes@yahoo.me
    rec = _spy_dispatch(monkeypatch)
    _judge_intent(monkeypatch, "approve")
    try:
        out = await nodes.card_resolution_node(
            _state("approve the email to zed@qmail.com", [_approval_msg([r1])], thread))
        assert rec["calls"] == []                                  # a foreign address → no dispatch
        assert "?" in (out.get("final_response") or "")            # it ASKS (confirm, not block)
    finally:
        await _cleanup(thread)


@pytest.mark.asyncio
async def test_kind_mismatch_confirms(monkeypatch):
    """Condition 4 (S4-class): the backstop's vocabulary includes KIND — 'approve the calendar
    event' with only an email target must confirm, never dispatch."""
    thread = f"web:{_MARK}-kind"
    r1 = await _seed_card(thread)                                  # an EMAIL card
    rec = _spy_dispatch(monkeypatch)
    _judge_intent(monkeypatch, "approve")
    try:
        out = await nodes.card_resolution_node(
            _state("approve the calendar event", [_approval_msg([r1])], thread))
        assert rec["calls"] == []
        assert "?" in (out.get("final_response") or "")
    finally:
        await _cleanup(thread)


# --------------------------------------------------------------------------- #
# The solicited anchor + the yes-collision (named acceptance cases)             #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_bare_yes_unanchored_confirms_not_dispatches(monkeypatch):
    """An UPDATE-class approval message (solicited=False — unseen content) + bare 'yes' →
    confirm, never dispatch (the D26 contract carried into consent)."""
    thread = f"web:{_MARK}-anchor"
    r1 = await _seed_card(thread)
    rec = _spy_dispatch(monkeypatch)
    _judge_intent(monkeypatch, "approve")
    try:
        out = await nodes.card_resolution_node(
            _state("yes.", [_approval_msg([r1], solicited=False,
                                          text="I've updated the email — it's awaiting your approval, Sir.")],
                   thread))
        assert rec["calls"] == []                                  # unanchored bare yes → no dispatch
        assert "?" in (out.get("final_response") or "")
    finally:
        await _cleanup(thread)


@pytest.mark.asyncio
async def test_bare_yes_after_offer_never_dispatches_the_card(monkeypatch):
    """THE yes-collision: a briefing offer is MORE RECENT than the approval message; bare
    'yes.' must never dispatch the card (it accepts the offer — routed to the agent/briefing)."""
    thread = f"web:{_MARK}-collide"
    r1 = await _seed_card(thread)
    rec = _spy_dispatch(monkeypatch)
    _judge_intent(monkeypatch, "approve")
    try:
        out = await nodes.card_resolution_node(
            _state("yes.", [_approval_msg([r1], solicited=True), _offer_msg()], thread))
        assert rec["calls"] == []                                  # the card MUST NOT dispatch
        assert out.get("card_handled") is not True                 # routed onward (agent/briefing)
    finally:
        await _cleanup(thread)


# --------------------------------------------------------------------------- #
# The D25 acceptance class — punctuation × phrasing all resolve                  #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
@pytest.mark.parametrize("phrase", [
    "Approve it.", "approve it", "Approved that email.", "send it", "send it.",
    "yes, send it.", "go ahead.", "approve the email to fernandes@yahoo.me",
])
async def test_single_card_resolves_across_phrasings(monkeypatch, phrase):
    thread = f"web:{_MARK}-{uuid.uuid4().hex[:4]}"
    r1 = await _seed_card(thread)
    rec = _spy_dispatch(monkeypatch)
    _judge_intent(monkeypatch, "approve")
    try:
        out = await nodes.card_resolution_node(
            _state(phrase, [_approval_msg([r1], solicited=True)], thread))
        assert rec["calls"] == [(r1, "approve")], f"{phrase!r} did not resolve"
        assert out.get("card_handled") is True
    finally:
        await _cleanup(thread)


@pytest.mark.asyncio
async def test_single_card_reject_resolves_and_names_the_card(monkeypatch):
    thread = f"web:{_MARK}-rej"
    r1 = await _seed_card(thread)
    rec = _spy_dispatch(monkeypatch)
    _judge_intent(monkeypatch, "reject")
    try:
        out = await nodes.card_resolution_node(
            _state("reject it.", [_approval_msg([r1], solicited=True)], thread))
        assert rec["calls"] == [(r1, "reject")]
        assert "fernandes" in (out.get("final_response") or "").lower()   # D16: names the card
    finally:
        await _cleanup(thread)


# --------------------------------------------------------------------------- #
# D28 — the phrasing matrix: CLASS-asserted, never regex-asserted               #
# --------------------------------------------------------------------------- #
_INVITE_MATRIX = [
    # the 5 demonstrated evasions
    "Want me to send it?", "Ready to send?", "Just say the word and I'll fire it off.",
    "Give me the go-ahead and it's gone.", "Say yes and I'll send it right now.",
    # ~10 diverse forms
    "Shall I send it?", "Should I go ahead?", "Would you like me to send it now?",
    "Do you want me to dispatch it?", "Can I fire this off?", "Good to go?",
    "Just confirm and I'll ship it.", "Green-light it and I'll proceed.",
    "I'll send it right away.", "Say the word, Sir.",
]


@pytest.mark.asyncio
@pytest.mark.parametrize("invite", _INVITE_MATRIX)
async def test_update_class_no_invitation_survives(invite):
    """The CLASS assertion (D28-a): on an UPDATE-class turn, whatever invite phrasing the model
    writes, the final message carries NO surviving invitation — it ends with the inform closer.
    The row asserts the OUTPUT class, never what the detector matched."""
    from app.agent.nodes import queued_finish_node

    thread = f"web:{_MARK}-m{abs(hash(invite)) % 10000}"
    rid = await _seed_card(thread, tool_args={"to": "amy@x.com", "subject": "Plan", "body": "v2"})
    try:
        from app.agent.nodes import QUEUED_UPDATE_TAG
        from langchain_core.messages import ToolMessage
        lead = f"I've redrafted the plan email to amy@x.com. {invite}"
        state = {
            "messages": [HumanMessage(content="redo it"),
                         AIMessage(content=lead, tool_calls=[
                             {"name": "email_send", "args": {}, "id": "c1"}]),
                         ToolMessage(content=QUEUED_UPDATE_TAG + " replaced", tool_call_id="c1")],
            "queued_this_turn": [rid],
        }
        out = await queued_finish_node(state)
        final = out["final_response"]
        assert invite not in final, f"invite survived verbatim: {invite!r}"
        assert final.rstrip().endswith("awaiting your approval, Sir."), \
            f"update turn must end with the inform closer: {final!r}"
        assert "?" not in final.split("I've redrafted")[-1] or "awaiting" in final, \
            f"a question survived after the lead: {final!r}"
    finally:
        await _cleanup(thread)


@pytest.mark.asyncio
async def test_fresh_class_exactly_one_solicitation_across_matrix():
    """Fresh class: a lead that already invites (any phrasing) yields EXACTLY one solicitation
    in the final message (the code invite stands down)."""
    from app.agent.nodes import queued_finish_node, QUEUED_MARKER_TAG
    from langchain_core.messages import ToolMessage

    for invite in _INVITE_MATRIX[:5]:
        thread = f"web:{_MARK}-f{abs(hash(invite)) % 10000}"
        rid = await _seed_card(thread, tool_args={"to": "amy@x.com", "subject": "Plan", "body": "v1"})
        try:
            lead = f"I've drafted the Plan email to amy@x.com. {invite}"
            state = {
                "messages": [HumanMessage(content="email amy"),
                             AIMessage(content=lead, tool_calls=[
                                 {"name": "email_send", "args": {}, "id": "c1"}]),
                             ToolMessage(content=QUEUED_MARKER_TAG + " parked", tool_call_id="c1")],
                "queued_this_turn": [rid],
            }
            out = await queued_finish_node(state)
            final = out["final_response"].lower()
            code_invites = final.count("shall i go ahead")
            assert invite.lower() in final or code_invites >= 1   # someone invites…
            assert (invite.lower() in final) + code_invites == 1, \
                f"not exactly one solicitation for {invite!r}: {final!r}"
        finally:
            await _cleanup(thread)
