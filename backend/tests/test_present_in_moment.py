"""3B — present-in-moment: when an APPROVE-tier tool QUEUES during a STREAMING
turn, stream_turn surfaces its card in-stream immediately (an `approval_required`
event), so a present master sees it without waiting for the /approvals/queue poll.

The contract under test:
  - the emitted event carries the SAME approval_id /approvals/queue returns for
    that row (THE dedup key — proven by reading both and asserting equality),
  - the payload is the SHARED UnifiedApprovalCard shape (built by the one
    app.approvals_service.to_unified_card both surfaces use) so the in-stream card
    and the polled card are byte-identical — they cannot drift,
  - run_turn (no live session) queues the SAME row WITHOUT emitting — its card
    surfaces only via the poll.

Real graph + AsyncPostgresSaver + Postgres (the [QUEUED] ToolMessage must flow
through the real updates stream for the detection to fire).
"""
import contextlib
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from sqlalchemy import delete, select

import app.agent.runner as runner
from app.agent.graph import init_checkpointer
from app.api.approvals import approval_queue
from app.db.engine import async_session
from app.db.models import PendingApproval

TOOL_ARGS = {"to": "x@y.com", "subject": "Hi", "body": "hello"}


@pytest.fixture
async def real_checkpointer():
    from app.agent import graph as graph_module

    if graph_module._checkpointer_cm is not None:
        with contextlib.suppress(Exception):
            await graph_module._checkpointer_cm.__aexit__(None, None, None)
        graph_module._checkpointer = None
        graph_module._checkpointer_cm = None
    await init_checkpointer()
    yield


@pytest.fixture
async def reset_runner_graph():
    runner._graph = None
    yield
    runner._graph = None


def _fake_llm(call_id: str):
    initial = AIMessage(
        content="",
        tool_calls=[{"name": "email_send", "args": TOOL_ARGS, "id": call_id}],
    )
    final = AIMessage(content="I've queued that email for your approval, Sir.")
    return FakeMessagesListChatModel(responses=[initial, final])


async def _row(thread_id: str, call_id: str) -> PendingApproval | None:
    async with async_session() as s:
        return (await s.execute(
            select(PendingApproval)
            .where(PendingApproval.thread_id == thread_id)
            .where(PendingApproval.interrupt_id == call_id)
        )).scalar_one_or_none()


async def _cleanup(thread_id: str):
    async with async_session() as s:
        await s.execute(delete(PendingApproval).where(PendingApproval.thread_id == thread_id))
        await s.commit()


@pytest.mark.asyncio
async def test_streaming_queue_emits_present_in_moment_card(real_checkpointer, reset_runner_graph):
    thread_id = f"test-3b-stream-{uuid.uuid4().hex[:8]}"
    call_id = f"call_{uuid.uuid4().hex[:6]}"
    fake_llm = _fake_llm(call_id)  # ONE instance — its response index must advance across agent calls

    def fake_build(tools, primary_model=None):  # noqa: ARG001
        return fake_llm

    try:
        with patch("app.agent.nodes._build_chat_model", fake_build), \
             patch("app.messaging.failure_alerter.send_approval_request_to_master", AsyncMock()):
            events = [
                ev async for ev in runner.stream_turn(
                    "send an email", thread_id, "web", "test-runner"
                )
            ]

        cards = [e for e in events if e["type"] == "approval_required"]
        assert len(cards) == 1, "the queued APPROVE tool must surface exactly one in-stream card"
        content = cards[0]["content"]

        row = await _row(thread_id, call_id)
        assert row is not None and row.status == "pending"  # surfacing only — still pending

        # THE contract: emitted approval_id == the canonical row id == what the queue returns
        assert content["approval_id"] == str(row.id)
        queue = await approval_queue()
        match = next((c for c in queue.approvals if c.approval_id == str(row.id)), None)
        assert match is not None, "the same row must be the dedup target in /approvals/queue"
        assert match.kind == "email"  # a chat-queued email_send is an EMAIL kind (the fix), not "tool"
        assert content["approval_id"] == match.approval_id  # one dedup key, both surfaces
        # The in-stream card IS the shared unified shape → byte-identical to the polled card.
        assert content["kind"] == "email" == match.kind
        assert content["tool_name"] == "email_send" == match.tool_name
        assert content["tool_args"] == TOOL_ARGS == match.tool_args
        assert content["description"]

        # the turn COMPLETED (queued, never interrupted)
        assert events[-1]["type"] == "done" and events[-1]["content"]["status"] == "complete"
    finally:
        await _cleanup(thread_id)


@pytest.mark.asyncio
async def test_run_turn_queues_same_row_without_emitting(real_checkpointer, reset_runner_graph):
    thread_id = f"test-3b-runturn-{uuid.uuid4().hex[:8]}"
    call_id = f"call_{uuid.uuid4().hex[:6]}"
    fake_llm = _fake_llm(call_id)  # ONE instance — its response index must advance across agent calls

    def fake_build(tools, primary_model=None):  # noqa: ARG001
        return fake_llm

    try:
        with patch("app.agent.nodes._build_chat_model", fake_build), \
             patch("app.messaging.failure_alerter.send_approval_request_to_master", AsyncMock()):
            env = await runner.run_turn("send an email", thread_id, "web", "test-runner")

        # run_turn returns an envelope (no event stream to emit into) — the turn
        # completes with the row queued; the card surfaces only via the poll.
        assert env["status"] == "complete"
        assert env.get("interrupt") is None

        row = await _row(thread_id, call_id)
        assert row is not None and row.status == "pending"  # the SAME row shape, queued
        queue = await approval_queue()
        assert any(c.approval_id == str(row.id) for c in queue.approvals)  # surfaces via poll
    finally:
        await _cleanup(thread_id)
