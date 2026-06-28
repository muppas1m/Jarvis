"""Duplicate-cards bug: one "send an email to X" produced 5 identical EMAIL_SEND cards.

Root cause: after an APPROVE-tier tool QUEUEd and returned [QUEUED], should_continue_tools routed
BACK to agent_node, which re-queued the same action round after round. Two layers fix it:
  (1) ROOT — an all-[QUEUED] round ENDS the turn (queued_finish), never back to agent → no re-queue.
  (2) DEFENSE — content-level dedup: the same un-resolved action under a new tool_call_id reuses the
      existing row (no second card / ping).
"""
import contextlib
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from sqlalchemy import delete, select

import app.agent.runner as runner
from app.agent.graph import init_checkpointer
from app.agent.nodes import (
    QUEUED_MARKER_TAG,
    _find_pending_approval_by_content,
    queued_finish_node,
    should_continue_tools,
)
from app.db.engine import async_session
from app.db.models import PendingApproval

_MARK = f"test-qdup-{uuid.uuid4().hex[:8]}"


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


def _send_call(to, subject, body, cid):
    return {"name": "email_send", "args": {"to": to, "subject": subject, "body": body}, "id": cid}


class _AlwaysEmailSend:
    """Returns the SAME email_send tool_call (new id) on EVERY invocation — without the root fix
    this loops and mints a fresh card each round. Counts invocations to prove the loop ended."""
    def __init__(self):
        self.calls = 0

    async def ainvoke(self, _msgs):
        self.calls += 1
        return AIMessage(content="", tool_calls=[_send_call("bob@x.com", "Hi", "yo", f"c{self.calls}")])


class _Scripted:
    def __init__(self, responses):
        self._responses = list(responses)

    async def ainvoke(self, _msgs):
        return self._responses.pop(0)


async def _cards(thread_id):
    async with async_session() as s:
        return (await s.execute(
            select(PendingApproval).where(PendingApproval.thread_id == thread_id)
        )).scalars().all()


async def _cleanup(thread_id):
    async with async_session() as s:
        await s.execute(delete(PendingApproval).where(PendingApproval.thread_id == thread_id))
        await s.commit()


# --------------------------------------------------------------------------- #
# Unit — should_continue_tools routing (the root-fix decision).                #
# --------------------------------------------------------------------------- #
def _q(cid):  # a [QUEUED] ToolMessage
    return ToolMessage(content=QUEUED_MARKER_TAG + " parked", tool_call_id=cid)


def test_routing_all_queued_round_ends_turn():
    ai = AIMessage(content="", tool_calls=[_send_call("a@x.com", "A", "a", "c1")])
    state = {"messages": [ai, _q("c1")]}
    assert should_continue_tools(state) == "queued_finish"


def test_routing_two_queued_actions_ends_turn():
    ai = AIMessage(content="", tool_calls=[_send_call("a@x", "A", "a", "c1"), _send_call("b@x", "B", "b", "c2")])
    state = {"messages": [ai, _q("c1"), _q("c2")]}
    assert should_continue_tools(state) == "queued_finish"


def test_routing_mixed_round_goes_to_agent():
    # SAFE read result (non-QUEUED) + a QUEUED approval → the agent must consume the SAFE result.
    ai = AIMessage(content="", tool_calls=[
        {"name": "task_list", "args": {}, "id": "c1"}, _send_call("b@x", "B", "b", "c2")])
    state = {"messages": [ai, ToolMessage(content="You have 2 open tasks.", tool_call_id="c1"), _q("c2")]}
    assert should_continue_tools(state) == "agent"


def test_routing_pending_calls_drain_first():
    ai = AIMessage(content="", tool_calls=[_send_call("a@x", "A", "a", "c1"), _send_call("b@x", "B", "b", "c2")])
    state = {"messages": [ai, _q("c1")]}  # c2 not processed yet
    assert should_continue_tools(state) == "tool_executor"


@pytest.mark.asyncio
async def test_queued_finish_node_closing_is_count_aware():
    ai2 = AIMessage(content="", tool_calls=[_send_call("a@x", "A", "a", "c1"), _send_call("b@x", "B", "b", "c2")])
    out = await queued_finish_node({"messages": [ai2, _q("c1"), _q("c2")]})
    assert "queued both" in out["final_response"].lower()
    ai1 = AIMessage(content="", tool_calls=[_send_call("a@x", "A", "a", "c1")])
    out1 = await queued_finish_node({"messages": [ai1, _q("c1")]})
    assert "queued it" in out1["final_response"].lower()


# --------------------------------------------------------------------------- #
# Unit — content dedup.                                                        #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_find_by_content_matches_same_args_only():
    thread_id = f"web:{_MARK}-content"
    args = {"to": "bob@x.com", "subject": "Hi", "body": "yo"}
    aid = uuid.uuid4()
    async with async_session() as s:
        s.add(PendingApproval(
            id=aid, thread_id=thread_id, interrupt_id="orig", action_type="email_send",
            description="d", payload={"tool_name": "email_send", "tool_args": args}, status="pending",
            expires_at=datetime.now(UTC) + timedelta(hours=24)))
        await s.commit()
    try:
        assert await _find_pending_approval_by_content(thread_id, "email_send", args) == aid
        assert await _find_pending_approval_by_content(thread_id, "email_send", {**args, "to": "x@x"}) is None
        assert await _find_pending_approval_by_content(thread_id, "calendar_create", args) is None
        # a RESOLVED row is not a dedup target
        async with async_session() as s:
            await s.execute(PendingApproval.__table__.update().where(PendingApproval.id == aid).values(status="executed"))
            await s.commit()
        assert await _find_pending_approval_by_content(thread_id, "email_send", args) is None
    finally:
        await _cleanup(thread_id)


# --------------------------------------------------------------------------- #
# End-to-end through the real graph — the master's self-test.                  #
# --------------------------------------------------------------------------- #
def _patches():
    return patch("app.messaging.failure_alerter.send_approval_request_to_master", AsyncMock())


@pytest.mark.asyncio
async def test_one_send_yields_exactly_one_card(real_checkpointer):
    thread_id = f"web:{_MARK}-one"
    llm = _AlwaysEmailSend()
    try:
        with patch("app.agent.nodes._build_chat_model", lambda *a, **k: llm), _patches():
            env = await runner.run_turn("send an email to bob", thread_id, "web", "u")
        assert env["status"] == "complete"
        assert "queued it for your approval" in env["response"].lower()
        cards = await _cards(thread_id)
        assert len(cards) == 1, f"expected exactly 1 card, got {len(cards)}"
        # the root fix: the agent ran ONCE — no re-queue loop (pre-fix this looped to the rate cap).
        assert llm.calls == 1, f"agent looped {llm.calls}× — the turn didn't end after the queue"
    finally:
        await _cleanup(thread_id)


@pytest.mark.asyncio
async def test_two_distinct_emails_yield_two_cards(real_checkpointer):
    thread_id = f"web:{_MARK}-two"
    two = AIMessage(content="", tool_calls=[
        _send_call("alice@x.com", "A", "a", "ca"), _send_call("bob@x.com", "B", "b", "cb")])
    try:
        with patch("app.agent.nodes._build_chat_model", lambda *a, **k: _Scripted([two])), _patches():
            env = await runner.run_turn("email alice and also bob", thread_id, "web", "u")
        cards = await _cards(thread_id)
        assert len(cards) == 2, f"two DIFFERENT actions must both queue, got {len(cards)}"
        tos = sorted((c.payload or {}).get("tool_args", {}).get("to") for c in cards)
        assert tos == ["alice@x.com", "bob@x.com"]
        assert "queued both" in env["response"].lower()
    finally:
        await _cleanup(thread_id)


@pytest.mark.asyncio
async def test_reissue_same_send_in_one_turn_no_duplicate(real_checkpointer):
    thread_id = f"web:{_MARK}-dup"
    args = ("bob@x.com", "Hi", "yo")
    two_same = AIMessage(content="", tool_calls=[_send_call(*args, "c1"), _send_call(*args, "c2")])
    try:
        with patch("app.agent.nodes._build_chat_model", lambda *a, **k: _Scripted([two_same])), _patches():
            await runner.run_turn("send the same email twice", thread_id, "web", "u")
        assert len(await _cards(thread_id)) == 1, "identical content must dedup to one card"
    finally:
        await _cleanup(thread_id)
