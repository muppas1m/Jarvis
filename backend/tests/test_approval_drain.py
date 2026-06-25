"""Prod-confirm the deploy-time drain against a REAL paused-at-interrupt()
checkpoint (AsyncPostgresSaver + the real graph topology).

The cutover retired interrupt(), so the current graph can't MINT a paused
checkpoint anymore. To confirm the drain on a genuine one, we temporarily wire a
LEGACY interrupting node into the real graph (same "tool_executor" node name +
edges, just the pre-cutover body that creates a PendingApproval row and calls
interrupt()), drive a turn to PAUSE, then restore the REAL prod graph and drain
it. This exercises the exact deploy path: real checkpointer, real graph route,
the as_node advance, rows left pending.
"""
import contextlib
import uuid
from unittest.mock import patch

import pytest
import redis.asyncio as redis_aio  # noqa: F401 — parity with the queue-test fixtures
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, ToolMessage
from sqlalchemy import select

import app.agent.runner as runner
from app.agent.approval_drain import _all_checkpoint_thread_ids, drain_thread
from app.agent.graph import init_checkpointer
from app.db.engine import async_session
from app.db.models import PendingApproval


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


async def _legacy_interrupting_tool_executor(state):
    """The pre-cutover tool_executor body (the part that mattered): create the
    PendingApproval row, then interrupt() — pausing the graph exactly as it did
    before the cutover."""
    from langgraph.types import interrupt

    from app.agent.nodes import _create_pending_approval, _find_pending_approval

    last_ai = next(
        (m for m in reversed(state["messages"]) if isinstance(m, AIMessage) and m.tool_calls),
        None,
    )
    answered = {m.tool_call_id for m in state["messages"] if isinstance(m, ToolMessage)}
    tc = next(t for t in last_ai.tool_calls if t["id"] not in answered)
    approval_id = await _find_pending_approval(
        state["thread_id"], interrupt_id=tc["id"]
    ) or await _create_pending_approval(
        thread_id=state["thread_id"], interrupt_id=tc["id"],
        tool_name=tc["name"], tool_args=tc.get("args") or {},
    )
    interrupt({"approval_id": str(approval_id), "tool_name": tc["name"]})


async def _row_for(interrupt_id: str) -> PendingApproval | None:
    async with async_session() as session:
        return (await session.execute(
            select(PendingApproval).where(PendingApproval.interrupt_id == interrupt_id)
        )).scalar_one_or_none()


@pytest.mark.asyncio
async def test_drain_clears_legacy_paused_checkpoint_leaves_row_pending(real_checkpointer):
    thread_id = f"test-drain-{uuid.uuid4().hex[:8]}"
    call_id = f"call_LEGACY_{uuid.uuid4().hex[:6]}"

    initial = AIMessage(
        content="",
        tool_calls=[{"name": "email_send", "args": {"to": "x@y.com", "body": "hi"}, "id": call_id}],
    )
    final = AIMessage(content="(never reached — we drain instead of resuming)")
    fake_llm = FakeMessagesListChatModel(responses=[initial, final])

    def fake_build_chat_model(tools, primary_model=None):  # noqa: ARG001
        return fake_llm

    # --- create a REAL paused checkpoint via the real graph + legacy node ---
    with patch("app.agent.graph.tool_executor_node", _legacy_interrupting_tool_executor), \
         patch("app.agent.nodes._build_chat_model", fake_build_chat_model):
        runner._graph = None  # rebuild WITH the legacy interrupting node
        result = await runner.run_turn(
            user_message="send an email",
            thread_id=thread_id, platform="web", channel_user_id="test-runner",
        )
        assert result["status"] == "interrupted", (
            f"setup must produce a genuine paused checkpoint; got {result['status']!r}"
        )

    # the legacy pause left a PENDING approval row
    row = await _row_for(call_id)
    assert row is not None and row.status == "pending"

    # the checkpoint is genuinely paused at an interrupt (the drain's precondition)
    config = {"configurable": {"thread_id": thread_id}}
    before = await runner.graph().aget_state(config)
    assert runner._collect_interrupts(before), "checkpoint should be paused at interrupt"

    # --- drain with the REAL prod graph (legacy node restored on with-exit) ---
    runner._graph = None  # rebuild with the REAL prod graph
    verdict = await drain_thread(thread_id)
    assert verdict == "drained"

    # interrupt cleared; the orphaned tool_call now has an answering [DRAINED] msg
    after = await runner.graph().aget_state(config)
    assert not runner._collect_interrupts(after), "interrupt must be cleared after drain"
    msgs = after.values.get("messages") or []
    drained = [m for m in msgs if isinstance(m, ToolMessage) and m.tool_call_id == call_id]
    assert drained and drained[0].content.startswith("[DRAINED]")

    # the row is LEFT PENDING — the master still resolves it via the buttons
    row_after = await _row_for(call_id)
    assert row_after.status == "pending", "drain must NOT execute or resolve the action"

    # the enumerator finds the thread (drain_all_paused would have covered it)
    assert thread_id in await _all_checkpoint_thread_ids()

    # idempotent: a second drain is a no-op (no live interrupt anymore)
    assert await drain_thread(thread_id) == "skipped"
