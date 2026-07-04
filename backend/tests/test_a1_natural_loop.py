"""A1 — the natural agentic loop. Reproduce-first proof that the destructive "all-queued ends the
turn" is replaced by "the round ends the turn when there's nothing to CONSUME", and that closing the
BLOCKER (fresh-queue-continuation drift-spam) is STRUCTURAL — a pure-queue round ends the turn, so no
continuation pass exists in which a weak model can drift-re-emit.

Three distinct mechanisms proven:
  1. Verbatim re-emit → L0 sig-hit → NO_PROGRESS marker → the round is all-queue-markers → terminate.
  2. Structural drift defense → a pure-queue round ends the turn, the agent is NEVER re-invoked, so a
     drift-re-emit model (subject regenerated each pass) gets no pass to drift → exactly one card.
  3. Read-loop → a SAFE read is consumable → back to agent; a pathological loop is bounded by the
     recursion cap (asserted at the routing level; the full loop is bounded by GRAPH_RECURSION_LIMIT).

Plus the mixed-round read-back (carry-in #1) and red-team fixes #1 (stale final_response), #4
(double-ack collapse) and #5 (recursion/error terminal read-back).
"""
import contextlib
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from sqlalchemy import delete, select

import app.agent.runner as runner
from app.agent.graph import init_checkpointer
from app.agent.nodes import (
    NO_PROGRESS_TAG,
    QUEUED_MARKER_TAG,
    queued_finish_node,
    should_continue,
    should_continue_tools,
)
from app.db.engine import async_session
from app.db.models import PendingApproval

_MARK = f"test-a1-{uuid.uuid4().hex[:8]}"


# --------------------------------------------------------------------------- #
# Helpers / fixtures                                                           #
# --------------------------------------------------------------------------- #
@pytest.fixture
async def real_checkpointer():
    from app.agent import graph as graph_module
    if graph_module._checkpointer_cm is not None:
        with contextlib.suppress(Exception):
            await graph_module._checkpointer_cm.__aexit__(None, None, None)
        graph_module._checkpointer = None
        graph_module._checkpointer_cm = None
    await init_checkpointer()
    runner._graph = None
    yield
    runner._graph = None


def _qm(cid, tag=QUEUED_MARKER_TAG):
    return ToolMessage(content=tag + " parked", tool_call_id=cid)


def _send(to, subject, body, cid):
    return {"name": "email_send", "args": {"to": to, "subject": subject, "body": body}, "id": cid}


async def _seed_card(thread, cid, payload):
    async with async_session() as s:
        row = PendingApproval(
            thread_id=thread, interrupt_id=cid, action_type=payload["tool_name"], description="d",
            payload=payload, status="pending", expires_at=datetime.now(UTC) + timedelta(hours=24))
        s.add(row)
        await s.commit()
        await s.refresh(row)
        return str(row.id)


async def _cards(thread):
    async with async_session() as s:
        return (await s.execute(
            select(PendingApproval).where(PendingApproval.thread_id == thread))).scalars().all()


async def _cleanup(thread):
    async with async_session() as s:
        await s.execute(delete(PendingApproval).where(PendingApproval.thread_id == thread))
        await s.commit()


class _Scripted:
    def __init__(self, responses):
        self._responses = list(responses)

    async def ainvoke(self, _msgs):
        return self._responses.pop(0)


def _patches():
    return patch("app.messaging.failure_alerter.send_approval_request_to_master", AsyncMock())


# =========================================================================== #
# 1. should_continue_tools — the termination RULE (nothing to consume ends it) #
# =========================================================================== #
def test_pure_fresh_queue_round_terminates():
    ai = AIMessage(content="", tool_calls=[_send("a@x", "A", "a", "c1")])
    assert should_continue_tools({"messages": [ai, _qm("c1")]}) == "queued_finish"


def test_no_progress_round_terminates():
    # a VERBATIM re-emit round — every result is [ALREADY_QUEUED] (the re-emit spin) → end the turn.
    ai = AIMessage(content="", tool_calls=[_send("a@x", "A", "a", "c1")])
    assert should_continue_tools({"messages": [ai, _qm("c1", NO_PROGRESS_TAG)]}) == "queued_finish"


def test_mixed_fresh_and_no_progress_terminates():
    # a fresh queue + a re-emit of an already-queued action: still nothing to CONSUME → terminate.
    ai = AIMessage(content="", tool_calls=[_send("a@x", "A", "a", "c1"), _send("a@x", "A", "a", "c2")])
    state = {"messages": [ai, _qm("c1"), _qm("c2", NO_PROGRESS_TAG)]}
    assert should_continue_tools(state) == "queued_finish"


def test_read_plus_queue_routes_to_agent():
    # a SAFE read result the agent must synthesize + a queued approval → back to agent (natural loop).
    ai = AIMessage(content="", tool_calls=[{"name": "task_list", "args": {}, "id": "r1"}, _send("b@x", "B", "b", "c2")])
    state = {"messages": [ai, ToolMessage(content="You have 2 open tasks.", tool_call_id="r1"), _qm("c2")]}
    assert should_continue_tools(state) == "agent"


def test_read_only_routes_to_agent():
    ai = AIMessage(content="", tool_calls=[{"name": "task_list", "args": {}, "id": "r1"}])
    state = {"messages": [ai, ToolMessage(content="You have 2 open tasks.", tool_call_id="r1")]}
    assert should_continue_tools(state) == "agent"


# =========================================================================== #
# 2. should_continue — natural answer routes to the read-back when queued      #
# =========================================================================== #
def test_natural_answer_with_queued_goes_to_read_back():
    ai = AIMessage(content="Here's what I found, Sir.")
    assert should_continue({"messages": [ai], "queued_this_turn": ["some-id"]}) == "queued_finish"


def test_natural_answer_no_queue_goes_to_persist():
    ai = AIMessage(content="The capital of France is Paris.")
    assert should_continue({"messages": [ai], "queued_this_turn": []}) == "persist"
    assert should_continue({"messages": [ai]}) == "persist"


def test_tool_calls_go_to_tool_executor():
    ai = AIMessage(content="", tool_calls=[_send("a@x", "A", "a", "c1")])
    assert should_continue({"messages": [ai], "queued_this_turn": ["x"]}) == "tool_executor"


# =========================================================================== #
# 3. queued_finish — read-back keyed on queued_this_turn + Fix 4 + Fix 1       #
# =========================================================================== #
async def test_mixed_round_readback_names_card_and_keeps_answer():
    """Carry-in #1 + D1: the mixed-round natural-answer path names the queued card deterministically
    AND preserves the genuine answer (the read-back is appended, not a replacement)."""
    thread = f"web:{_MARK}-mixed"
    cid = await _seed_card(thread, "e1", {"tool_name": "email_send",
        "tool_args": {"to": "bob@x.com", "subject": "Report", "body": "hi"}})
    try:
        out = await queued_finish_node({
            "messages": [HumanMessage(content="email bob and how many tasks?"),
                         AIMessage(content="You have 3 open tasks, Sir.")],
            "final_response": "You have 3 open tasks, Sir.",
            "queued_this_turn": [cid]})
        r = out["final_response"]
        assert "3 open tasks" in r                       # genuine answer preserved
        assert "bob@x.com" in r                          # queued card NAMED (deterministic read-back)
        assert "queued" in r.lower()
    finally:
        await _cleanup(thread)


async def test_fix4_queue_ack_content_collapses_to_readback():
    """FLIPPED in A2 s1b (declared): the Fix-4 ack-DROP is retired — verify-and-keep. The
    model's ack prose is KEPT; the floor fires DELTA-ONLY (the prose named Bob but not the
    subject → the floor names the card once); the solicitation contract still guarantees
    exactly one invitation on the fresh class."""
    thread = f"web:{_MARK}-ack"
    cid = await _seed_card(thread, "e1", {"tool_name": "email_send",
        "tool_args": {"to": "bob@x.com", "subject": "Hi", "body": "x"}})
    try:
        out = await queued_finish_node({
            "messages": [AIMessage(content="I've queued the email to Bob for your approval, Sir.",
                                   tool_calls=[_send("bob@x.com", "Hi", "x", "e1")]), _qm("e1")],
            "queued_this_turn": [cid]})
        r = out["final_response"].lower()
        assert "i've queued the email to bob for your approval, sir." in r  # prose KEPT (affirmative)
        assert "bob@x.com" in r                                  # floor names the card (delta)
        assert r.count("shall i go ahead") == 1                  # exactly ONE solicitation
    finally:
        await _cleanup(thread)


async def test_fix4_does_not_over_collapse_genuine_for_approval_remainder():
    """Fix-4 hole (review-caught): a GENUINE compound remainder that merely mentions 'for approval'
    ("the board needs the budget for approval") must be PRESERVED — only a real queue-ack collapses.
    Over-matching 'for approval' would silently drop real content (the opposite of Fix 4's intent)."""
    thread = f"web:{_MARK}-forapproval"
    cid = await _seed_card(thread, "e1", {"tool_name": "email_send",
        "tool_args": {"to": "bob@x.com", "subject": "Hi", "body": "x"}})
    try:
        answer = "The board needs the budget for approval, and you have 3 open tasks, Sir."
        out = await queued_finish_node({
            "messages": [HumanMessage(content="email bob and what's my status"),
                         AIMessage(content=answer)],
            "final_response": answer,
            "queued_this_turn": [cid]})
        r = out["final_response"]
        assert "the budget for approval" in r     # genuine remainder PRESERVED, not collapsed
        assert "3 open tasks" in r
        assert "bob@x.com" in r                    # read-back still appended
    finally:
        await _cleanup(thread)


async def test_fix1_scan_stops_at_this_turn_humanmessage():
    """Fix 1 (scan half): the genuine-answer fallback scan must not walk into a PRIOR turn — a prior
    turn's answer sitting above this turn's HumanMessage must NOT be prepended to the read-back."""
    thread = f"web:{_MARK}-scope"
    cid = await _seed_card(thread, "e1", {"tool_name": "email_send",
        "tool_args": {"to": "bob@x.com", "subject": "Hi", "body": "x"}})
    try:
        out = await queued_finish_node({
            "messages": [
                AIMessage(content="PRIOR-TURN ANSWER about tacos."),   # a prior turn's answer
                HumanMessage(content="now email bob"),                 # THIS turn's user message
                AIMessage(content="", tool_calls=[_send("bob@x.com", "Hi", "x", "e1")]),  # empty content
                _qm("e1"),
            ],
            "queued_this_turn": [cid]})   # no final_response (agent had tool_calls)
        assert "PRIOR-TURN ANSWER" not in out["final_response"], "leaked a prior turn's answer"
        assert "bob@x.com" in out["final_response"]
    finally:
        await _cleanup(thread)


# =========================================================================== #
# 4. STRUCTURAL drift defense (the BLOCKER closed) — E2E through the graph      #
# =========================================================================== #
class _DriftingEmailSend:
    """Re-drafts the SAME email with a DRIFTED subject each pass — the exact weak-model behavior that
    escapes every exact-match dedup. The structural defense: a pure-queue round ENDS the turn, so this
    model is NEVER re-invoked → it gets no pass in which to drift → exactly one card, ever."""
    def __init__(self):
        self.calls = 0

    async def ainvoke(self, _msgs):
        self.calls += 1
        return AIMessage(content="", tool_calls=[
            _send("bob@x.com", f"Follow up v{self.calls}", "hi", f"c{self.calls}")])


@pytest.mark.asyncio
async def test_structural_drift_defense_one_card_agent_runs_once(real_checkpointer):
    thread = f"web:{_MARK}-drift"
    llm = _DriftingEmailSend()
    try:
        with patch("app.agent.nodes._build_chat_model", lambda *a, **k: llm), _patches():
            env = await runner.run_turn("send bob a follow up", thread, "web", "u")
        assert env["status"] == "complete"
        assert "bob@x.com" in env["response"]                     # deterministic read-back
        cards = await _cards(thread)
        assert len(cards) == 1, f"drift escaped the structural defense → {len(cards)} cards"
        # THE structural proof: the agent was NEVER re-invoked, so drift had no pass to spam in.
        assert llm.calls == 1, f"pure-queue round did NOT end the turn — agent looped {llm.calls}×"
    finally:
        await _cleanup(thread)


@pytest.mark.asyncio
async def test_batched_compound_completes_and_names_both(real_checkpointer):
    """N-part batched compound: both actions emitted in ONE round drain together → pure-queue round →
    terminate → read-back NAMES both. The un-batched sequenced pair is the batch-nudge's job (A1
    partial); this proves the batched path completes cleanly with no extra pass."""
    thread = f"web:{_MARK}-batch"
    both = AIMessage(content="", tool_calls=[
        _send("alice@x.com", "A", "a", "ca"),
        {"name": "calendar_create", "args": {"title": "Dinner", "start_iso": "2026-07-09T18:00:00+00:00"}, "id": "cb"}])
    try:
        with patch("app.agent.nodes._build_chat_model", lambda *a, **k: _Scripted([both])), _patches():
            env = await runner.run_turn("email alice and add dinner", thread, "web", "u")
        assert len(await _cards(thread)) == 2
        # both cards NAMED via the shared describe_card: the email by recipient, the tool card by its
        # humanized name ("calendar create" — surfacing the event TITLE is describe_card's job, A2/C3).
        assert "alice@x.com" in env["response"] and "calendar" in env["response"].lower()
    finally:
        await _cleanup(thread)


# =========================================================================== #
# 5. Fix 5 — recursion/error terminal read-back (name cards queued before fault)#
# =========================================================================== #
async def test_fix5_error_path_names_queued_cards():
    thread = f"web:{_MARK}-fix5"
    cid = await _seed_card(thread, "e1", {"tool_name": "email_send",
        "tool_args": {"to": "bob@x.com", "subject": "Hi", "body": "x"}})
    try:
        class _Snap:
            values = {"queued_this_turn": [cid]}
        with patch.object(runner, "graph") as g:
            g.return_value.aget_state = AsyncMock(return_value=_Snap())
            env = await runner._queued_readback_envelope(thread)
        assert env is not None
        assert env["status"] == "complete"
        assert "bob@x.com" in env["response"] and "queued" in env["response"].lower()
    finally:
        await _cleanup(thread)


async def test_fix5_returns_none_when_nothing_queued():
    class _Snap:
        values = {"queued_this_turn": []}
    with patch.object(runner, "graph") as g:
        g.return_value.aget_state = AsyncMock(return_value=_Snap())
        assert await runner._queued_readback_envelope("web:none") is None
