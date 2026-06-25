"""
The single most important test in Phase 3 (successor to the resume-dedup test).

Phase 3 retired ``interrupt()``: an APPROVE-tier tool no longer PAUSES the turn
and re-runs the whole ``tool_executor_node`` body on resume. Instead it QUEUES a
synthetic ``PendingApproval`` row + returns a ``[QUEUED]`` ToolMessage (the turn
COMPLETES), and the action executes OUT-OF-BAND on approve through the single
claim-then-dispatch gate (``resolve_and_dispatch`` → ``dispatch_approval`` →
``execute_tool_guarded``).

That removes the resume-re-execution hazard entirely (there is no resume), and
replaces it with TWO new exactly-once obligations this file proves end-to-end on
the REAL graph + AsyncPostgresSaver + Postgres + Redis:

  1. QUEUE has no in-turn side effect. A turn with a SAFE tool A (memory_search)
     + an APPROVE tool B (email_send): A executes once, B is QUEUED (NOT executed,
     a durable pending row), and the turn returns status=='complete' — never
     'interrupted'. Then a single approve dispatch executes B exactly once and
     does NOT re-execute A (no loop re-run).

  2. Concurrent double-resolve executes the tool ONCE. Two approve dispatches
     racing on the same row (the dashboard double-click / button+voice race) →
     the atomic claim lets exactly one through; the tool fires once.

Requires the live Postgres + Redis services (up in the docker-compose stack).
"""
import asyncio
import contextlib
import uuid
from unittest.mock import AsyncMock, patch

import pytest
import redis.asyncio as redis_aio
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, ToolMessage

from app.agent.approval_dispatch import resolve_and_dispatch
from app.agent.graph import init_checkpointer
from app.agent.runner import run_turn
from app.agent.tools.registry import tool_registry
from app.config import settings


def _counter_key(thread_id: str, tool_name: str) -> str:
    return f"jarvis:test:queue:{thread_id}:tool:{tool_name}"


@pytest.fixture
async def real_checkpointer():
    """Open the AsyncPostgresSaver against the live Postgres, scoped to THIS
    test's event loop (pytest-asyncio's per-function loop otherwise leaves the
    cached pool bound to a dead loop)."""
    from app.agent import graph as graph_module

    if graph_module._checkpointer_cm is not None:
        with contextlib.suppress(Exception):
            await graph_module._checkpointer_cm.__aexit__(None, None, None)
        graph_module._checkpointer = None
        graph_module._checkpointer_cm = None

    await init_checkpointer()
    yield
    # The runner's module-level cached graph holds a reference; the container's
    # shutdown cleans up at process exit.


@pytest.fixture
async def reset_runner_graph():
    """Force a graph rebuild so the _build_chat_model patch takes effect."""
    import app.agent.runner as runner

    runner._graph = None
    yield
    runner._graph = None


@pytest.fixture
async def redis_client():
    client = redis_aio.from_url(settings.REDIS_URL)
    yield client
    await client.aclose()


async def _pending_approval_id(interrupt_id: str):
    from sqlalchemy import select

    from app.db.engine import async_session
    from app.db.models import PendingApproval

    async with async_session() as session:
        row = (await session.execute(
            select(PendingApproval).where(PendingApproval.interrupt_id == interrupt_id)
        )).scalar_one_or_none()
    return row


@pytest.mark.asyncio
async def test_queue_completes_turn_then_dispatch_executes_exactly_once(
    real_checkpointer, reset_runner_graph, redis_client
) -> None:
    """Leg 1 (no in-turn side effect): A executes, B QUEUES, turn completes.
    Leg 2 (exactly-once on approve): one dispatch executes B once, never re-runs A."""
    thread_id = f"test-queue-{uuid.uuid4().hex[:8]}"
    call_a_id = f"call_A_{uuid.uuid4().hex[:6]}"
    call_b_id = f"call_B_{uuid.uuid4().hex[:6]}"
    counter_a_key = _counter_key(thread_id, "memory_search")
    counter_b_key = _counter_key(thread_id, "email_send")
    await redis_client.delete(counter_a_key, counter_b_key)

    initial_response = AIMessage(
        content="",
        tool_calls=[
            {"name": "memory_search", "args": {"query": "anything", "top_k": 1}, "id": call_a_id},
            {"name": "email_send", "args": {"to": "test@example.com", "body": "test"}, "id": call_b_id},
        ],
    )
    final_response = AIMessage(content="One done, one queued for your approval, Sir.")
    fake_llm = FakeMessagesListChatModel(responses=[initial_response, final_response])

    def fake_build_chat_model(tools, primary_model=None):  # noqa: ARG001
        return fake_llm

    async def fake_execute(name: str, args: dict) -> str:  # noqa: ARG001
        if name == "memory_search":
            await redis_client.incr(counter_a_key)
            return "fake memory_search result"
        if name == "email_send":
            await redis_client.incr(counter_b_key)
            return "fake email_send result"
        raise ValueError(f"Unexpected tool name in test: {name!r}")

    send_mock = AsyncMock(return_value=None)

    with patch("app.agent.nodes._build_chat_model", fake_build_chat_model), \
         patch.object(tool_registry, "execute", side_effect=fake_execute), \
         patch("app.messaging.failure_alerter.send_approval_request_to_master", send_mock):
        # ---- leg 1: run_turn → COMPLETE (not interrupted), B queued not executed ----
        result = await run_turn(
            user_message="Use both tools",
            thread_id=thread_id, platform="web", channel_user_id="test-runner",
        )
        assert result["status"] == "complete", (
            f"the turn must COMPLETE (APPROVE-tier no longer interrupts); "
            f"got {result['status']!r}, response={result['response']!r}"
        )
        assert result["interrupt"] is None, "no interrupt payload — nothing pauses"

        assert int(await redis_client.get(counter_a_key) or 0) == 1, "SAFE tool A runs once in-turn"
        assert int(await redis_client.get(counter_b_key) or 0) == 0, "APPROVE tool B is QUEUED, NOT run"
        assert send_mock.await_count == 1, "the master is pinged once for the queued action"

        row = await _pending_approval_id(call_b_id)
        assert row is not None and row.status == "pending", "B left a durable pending row"
        assert row.payload.get("tool_name") == "email_send"  # dispatch reads this back
        approval_id = str(row.id)

        # the [QUEUED] ToolMessage is in the thread (honest: not 'done')
        import app.agent.runner as runner
        state = await runner.graph().aget_state({"configurable": {"thread_id": thread_id}})
        queued = [
            m for m in (state.values.get("messages") or [])
            if isinstance(m, ToolMessage) and m.tool_call_id == call_b_id
        ]
        assert queued and queued[0].content.startswith("[QUEUED]"), "B's ToolMessage says QUEUED"

        # ---- leg 2: a single approve dispatch executes B once, never re-runs A ----
        outcome = await resolve_and_dispatch(approval_id, "approve", "web", {"approved": True})
        assert outcome.kind == "tool" and outcome.status == "executed" and outcome.success

        assert int(await redis_client.get(counter_b_key) or 0) == 1, "B executes EXACTLY once on approve"
        assert int(await redis_client.get(counter_a_key) or 0) == 1, "A is NOT re-executed (no resume re-run)"


@pytest.mark.asyncio
async def test_concurrent_double_resolve_executes_tool_once(
    real_checkpointer, reset_runner_graph, redis_client
) -> None:
    """The dashboard double-click / button+voice race: TWO approve dispatches on
    the SAME queued row, fired concurrently. The atomic claim
    (UPDATE ... WHERE status='pending' RETURNING) lets exactly one win — the tool
    fires once; the loser gets not_claimed."""
    thread_id = f"test-queue-race-{uuid.uuid4().hex[:8]}"
    call_id = f"call_RACE_{uuid.uuid4().hex[:6]}"
    counter_key = _counter_key(thread_id, "email_send")
    await redis_client.delete(counter_key)

    initial_response = AIMessage(
        content="",
        tool_calls=[{"name": "email_send", "args": {"to": "x@y.com", "body": "hi"}, "id": call_id}],
    )
    final_response = AIMessage(content="Queued for your approval, Sir.")
    fake_llm = FakeMessagesListChatModel(responses=[initial_response, final_response])

    def fake_build_chat_model(tools, primary_model=None):  # noqa: ARG001
        return fake_llm

    async def fake_execute(name: str, args: dict) -> str:  # noqa: ARG001
        await redis_client.incr(counter_key)
        return "fake email_send result"

    send_mock = AsyncMock(return_value=None)

    with patch("app.agent.nodes._build_chat_model", fake_build_chat_model), \
         patch.object(tool_registry, "execute", side_effect=fake_execute), \
         patch("app.messaging.failure_alerter.send_approval_request_to_master", send_mock):
        result = await run_turn(
            user_message="send an email",
            thread_id=thread_id, platform="web", channel_user_id="test-runner",
        )
        assert result["status"] == "complete"
        row = await _pending_approval_id(call_id)
        assert row is not None and row.status == "pending"
        approval_id = str(row.id)

        # fire the two approve dispatches CONCURRENTLY on the same row
        o1, o2 = await asyncio.gather(
            resolve_and_dispatch(approval_id, "approve", "web", {"approved": True}),
            resolve_and_dispatch(approval_id, "approve", "telegram", {"approved": True}),
        )

    statuses = sorted([o1.status, o2.status])
    assert statuses == ["executed", "not_claimed"], (
        f"exactly one dispatch must win the claim; got {statuses}"
    )
    assert int(await redis_client.get(counter_key) or 0) == 1, "the tool fired EXACTLY once under the race"
