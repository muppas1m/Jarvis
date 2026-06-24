"""
The single most important test in Phase 1.

LangGraph re-runs the entire `tool_executor_node` body on resume from
`interrupt()`. If the for-loop iterates from index 0 again, side effects of
tool calls EARLIER in the loop (rate-limit increments, audit rows, the
actual tool execution) re-run too. For an `email_send`, that means the
email goes out twice.

The defense in nodes.py is to skip any tool call whose ToolMessage already
exists in `state["messages"]`. The reducer keeps those messages around
across invocations — they ARE the durable record of what's been processed.

This test proves that defense works:
  1. Real graph topology (memory_load → agent → tool_executor → … →
     persist), real AsyncPostgresSaver checkpointer.
  2. A FakeMessagesListChatModel injects a canned AIMessage carrying TWO
     tool calls in one response: A=SAFE (memory_search), B=APPROVE
     (email_send). Then a second canned AIMessage with no tool calls so
     the agent terminates after the resume.
  3. tool_registry.execute is patched to INCR per-tool Redis counters
     instead of running the real tools.
  4. send_approval_request_to_master is patched to no-op (we don't want
     to actually message the master during tests).
  5. Drive run_turn → assert status=="interrupted" and counter[A]==1,
     counter[B]==0.
  6. Drive resume_turn({"approved": True}) → assert status=="complete"
     and counter[A]==1 (DID NOT double-execute) and counter[B]==1.

The test runs in pytest's asyncio mode and requires the real Postgres +
Redis services to be up (which they are in our docker-compose stack).
"""
import uuid
from typing import Any
from unittest.mock import patch

import pytest
import redis.asyncio as redis_aio
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage

from app.agent.graph import close_checkpointer, init_checkpointer
from app.agent.runner import resume_turn, run_turn
from app.agent.tools.registry import tool_registry
from app.config import settings


# Distinct keys per test run so a previous (failed) test doesn't poison this one.
def _counter_key(thread_id: str, tool_name: str) -> str:
    return f"jarvis:test:dedup:{thread_id}:tool:{tool_name}"


@pytest.fixture
async def real_checkpointer():
    """Open the AsyncPostgresSaver against the live Postgres for the test.

    Force a clean (re)initialization scoped to THIS test's event loop.
    pytest-asyncio's default per-function loop scope means the cached
    checkpointer + connection pool from any prior test in the session is
    bound to a now-dead loop. Closing + reopening pins the connections
    to the current loop so reads don't fail with 'connection is closed'.
    """
    from app.agent import graph as graph_module

    if graph_module._checkpointer_cm is not None:
        try:
            await graph_module._checkpointer_cm.__aexit__(None, None, None)
        except Exception:
            pass
        graph_module._checkpointer = None
        graph_module._checkpointer_cm = None

    await init_checkpointer()
    yield
    # Don't close — the runner.py module-level cached graph holds a
    # reference. Closing here breaks subsequent tests in the same session.
    # The container's shutdown will clean up at process exit.


@pytest.fixture
async def reset_runner_graph():
    """Force the runner to rebuild the graph on next call. We need this
    because the patches we apply (FakeMessagesListChatModel) only take
    effect on a freshly-built graph."""
    import app.agent.runner as runner

    runner._graph = None
    yield
    runner._graph = None


@pytest.fixture
async def redis_client():
    client = redis_aio.from_url(settings.REDIS_URL)
    yield client
    await client.aclose()


@pytest.mark.asyncio
async def test_resume_does_not_re_execute_safe_tool_from_earlier_iteration(
    real_checkpointer, reset_runner_graph, redis_client
) -> None:
    """End-to-end exactly-once test on the resume-from-interrupt path."""

    # Unique IDs so this test never collides with a previous run.
    thread_id = f"test-resume-dedup-{uuid.uuid4().hex[:8]}"
    call_a_id = f"call_A_{uuid.uuid4().hex[:6]}"
    call_b_id = f"call_B_{uuid.uuid4().hex[:6]}"

    counter_a_key = _counter_key(thread_id, "memory_search")
    counter_b_key = _counter_key(thread_id, "email_send")

    # Make sure counters are clean before we start.
    await redis_client.delete(counter_a_key, counter_b_key)

    # --- the canned LLM responses -----------------------------------------
    # First invocation: emit BOTH tool calls in a single AIMessage.
    # Second invocation (after both tools have executed and we re-enter
    # agent_node): emit a final answer with no tool_calls so the graph
    # routes to persist → END.
    initial_response = AIMessage(
        content="",
        tool_calls=[
            {
                "name": "memory_search",
                "args": {"query": "anything", "top_k": 1},
                "id": call_a_id,
            },
            {
                "name": "email_send",
                "args": {"to": "test@example.com", "body": "test"},
                "id": call_b_id,
            },
        ],
    )
    final_response = AIMessage(content="Both tools completed. Done.")

    fake_llm = FakeMessagesListChatModel(responses=[initial_response, final_response])

    # FakeMessagesListChatModel.bind_tools is a no-op pass-through; the
    # canned responses are what come back regardless of the tools list.
    def fake_build_chat_model(tools, primary_model=None):  # noqa: ARG001 — ignore tools + tier
        return fake_llm

    # --- the fake tool executor -------------------------------------------
    # Increments a thread+tool-scoped Redis counter then returns a stub
    # result. This is what proves "exactly-once": after the full
    # run+resume, each counter must be exactly 1.
    async def fake_execute(name: str, args: dict) -> str:
        if name == "memory_search":
            await redis_client.incr(counter_a_key)
            return "fake memory_search result"
        if name == "email_send":
            await redis_client.incr(counter_b_key)
            return "fake email_send result"
        raise ValueError(f"Unexpected tool name in test: {name!r}")

    # --- the no-op approval request ---------------------------------------
    # Don't actually push a Telegram approval prompt during tests.
    async def noop_approval_request(*args, **kwargs):  # noqa: ARG001
        return None

    # --- patch + drive ----------------------------------------------------
    # tool_registry is imported lazily inside tool_executor_node, so we patch
    # the singleton's .execute method directly rather than via dotted path on
    # app.agent.nodes (which doesn't expose tool_registry as a module attr).
    with patch("app.agent.nodes._build_chat_model", fake_build_chat_model), \
         patch.object(tool_registry, "execute", side_effect=fake_execute), \
         patch(
             "app.messaging.failure_alerter.send_approval_request_to_master",
             side_effect=noop_approval_request,
         ):
        # ---- first leg: run_turn → expect interrupt ----
        result = await run_turn(
            user_message="Use both tools",
            thread_id=thread_id,
            platform="web",
            channel_user_id="test-runner",
        )

        assert result["status"] == "interrupted", (
            f"Expected status='interrupted' (graph should pause at the APPROVE "
            f"tool); got status={result['status']!r}, response={result['response']!r}"
        )
        assert result["interrupt"] is not None, "interrupt payload missing"
        assert result["interrupt"].get("tool_name") == "email_send", (
            f"Wrong tool paused for approval: {result['interrupt']!r}"
        )

        # --- approval_id contract assertion ----------------------------------
        # /api/approvals/{id}/decide depends on this — the dashboard's approve
        # button calls that endpoint with the UUID it pulled from this payload.
        # If approval_id is missing or doesn't match a real PendingApproval row,
        # the resume-from-dashboard path is structurally broken even if the
        # exactly-once defense holds.
        approval_id_raw = result["interrupt"].get("approval_id")
        assert approval_id_raw, (
            f"interrupt payload must carry approval_id (load-bearing for "
            f"/api/approvals/{{id}}/decide), got {result['interrupt']!r}"
        )
        try:
            approval_uuid = uuid.UUID(approval_id_raw)
        except ValueError as exc:
            raise AssertionError(
                f"approval_id is not a valid UUID: {approval_id_raw!r} ({exc})"
            )

        # And the row had better actually exist with that UUID + the right
        # interrupt_id pointing at this turn's tool_call_id.
        from sqlalchemy import select
        from app.db.engine import async_session
        from app.db.models import PendingApproval

        async with async_session() as session:
            row_result = await session.execute(
                select(PendingApproval).where(PendingApproval.id == approval_uuid)
            )
            approval_row = row_result.scalar_one_or_none()
        assert approval_row is not None, (
            f"approval_id {approval_id_raw} surfaced in interrupt payload but "
            f"no PendingApproval row exists with that UUID"
        )
        assert approval_row.thread_id == thread_id, (
            f"PendingApproval.thread_id mismatch: row says "
            f"{approval_row.thread_id!r}, turn was {thread_id!r}"
        )
        assert approval_row.interrupt_id == call_b_id, (
            f"PendingApproval.interrupt_id should be the email_send tool_call_id "
            f"({call_b_id!r}), got {approval_row.interrupt_id!r}"
        )
        assert approval_row.status == "pending", (
            f"PendingApproval.status should be 'pending' before resume, got "
            f"{approval_row.status!r}"
        )

        count_a_after_run = int(await redis_client.get(counter_a_key) or 0)
        count_b_after_run = int(await redis_client.get(counter_b_key) or 0)
        assert count_a_after_run == 1, (
            f"After run_turn: SAFE tool A should have executed once "
            f"(counter == 1), got {count_a_after_run}"
        )
        assert count_b_after_run == 0, (
            f"After run_turn: APPROVE tool B should NOT have executed yet "
            f"(counter == 0), got {count_b_after_run}"
        )

        # ---- second leg: resume_turn → expect complete + exactly-once ----
        resume_result = await resume_turn(
            thread_id=thread_id,
            decision={"approved": True},
        )

        assert resume_result["status"] == "complete", (
            f"After resume: expected status='complete', got "
            f"{resume_result['status']!r}, response={resume_result['response']!r}"
        )

        count_a_after_resume = int(await redis_client.get(counter_a_key) or 0)
        count_b_after_resume = int(await redis_client.get(counter_b_key) or 0)
        assert count_a_after_resume == 1, (
            f"REGRESSION: SAFE tool A double-executed on resume. "
            f"counter_a went from 1 to {count_a_after_resume}. "
            f"The ToolMessage-dedup logic in tool_executor_node is broken."
        )
        assert count_b_after_resume == 1, (
            f"After resume: APPROVE tool B should have executed exactly once, "
            f"got {count_b_after_resume}"
        )

    # ---- inspect final state: both ToolMessages should be present --------
    # We pull state off the graph after the run-resume cycle finished.
    import app.agent.runner as runner

    config = {"configurable": {"thread_id": thread_id}}
    state = await runner.graph().aget_state(config)
    messages = state.values.get("messages") or []

    from langchain_core.messages import ToolMessage

    tool_message_ids = {
        m.tool_call_id for m in messages if isinstance(m, ToolMessage)
    }
    assert call_a_id in tool_message_ids, (
        f"Final state missing ToolMessage for tool A (id={call_a_id!r}). "
        f"Tool messages found: {sorted(tool_message_ids)}"
    )
    assert call_b_id in tool_message_ids, (
        f"Final state missing ToolMessage for tool B (id={call_b_id!r}). "
        f"Tool messages found: {sorted(tool_message_ids)}"
    )


@pytest.mark.asyncio
async def test_resume_does_not_duplicate_pending_approval_or_prompt(
    real_checkpointer, reset_runner_graph, redis_client
) -> None:
    """P3: the APPROVE branch re-runs from the top on resume. Without the
    interrupt_id idempotency guard it created a SECOND PendingApproval row AND
    re-pinged the master each resume (the Jun-11 double-prompt bug: 27 rows for
    ~14 requests). After the guard, a full run+resume yields exactly ONE row and
    ONE prompt. (Execution exactly-once is covered by the sibling test; this
    pins the approval-creation side.)"""
    from unittest.mock import AsyncMock
    from sqlalchemy import select
    from app.db.engine import async_session
    from app.db.models import PendingApproval

    thread_id = f"test-approval-dedup-{uuid.uuid4().hex[:8]}"
    call_id = f"call_APV_{uuid.uuid4().hex[:6]}"

    initial_response = AIMessage(
        content="",
        tool_calls=[{
            "name": "email_send",
            "args": {"to": "test@example.com", "body": "test"},
            "id": call_id,
        }],
    )
    final_response = AIMessage(content="Sent. Done.")
    fake_llm = FakeMessagesListChatModel(responses=[initial_response, final_response])

    def fake_build_chat_model(tools, primary_model=None):  # noqa: ARG001
        return fake_llm

    async def fake_execute(name: str, args: dict) -> str:  # noqa: ARG001
        return "fake email_send result"

    async def count_pending() -> int:
        async with async_session() as session:
            rows = await session.execute(
                select(PendingApproval.id).where(PendingApproval.interrupt_id == call_id)
            )
            return len(rows.all())

    # AsyncMock so we can count how many times the master was pinged.
    send_mock = AsyncMock(return_value=None)

    with patch("app.agent.nodes._build_chat_model", fake_build_chat_model), \
         patch.object(tool_registry, "execute", side_effect=fake_execute), \
         patch("app.messaging.failure_alerter.send_approval_request_to_master", send_mock):
        # ---- first leg: run_turn → interrupt; exactly one row + one ping ----
        result = await run_turn(
            user_message="send an email",
            thread_id=thread_id,
            platform="web",
            channel_user_id="test-runner",
        )
        assert result["status"] == "interrupted", (
            f"graph should pause at the APPROVE tool; got {result['status']!r}"
        )
        assert await count_pending() == 1, "first pass should create exactly one PendingApproval"
        assert send_mock.await_count == 1, "first pass should ping the master exactly once"

        # ---- second leg: resume re-runs the APPROVE branch from the top ----
        resume_result = await resume_turn(thread_id=thread_id, decision={"approved": True})
        assert resume_result["status"] == "complete", (
            f"after resume expected 'complete', got {resume_result['status']!r}"
        )

        # ---- the P3 regression assertions ----
        final_rows = await count_pending()
        assert final_rows == 1, (
            f"REGRESSION: resume created a duplicate PendingApproval row "
            f"(count={final_rows}). The interrupt_id idempotency guard is broken."
        )
        assert send_mock.await_count == 1, (
            f"REGRESSION: resume re-pinged the master (await_count="
            f"{send_mock.await_count}). The duplicate-prompt guard is broken."
        )
