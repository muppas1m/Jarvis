"""Approved-action OUTCOMES — restore what the non-blocking cutover (88ad34d) dropped:
the agent knowing what HAPPENED to an action it approved, generically for any APPROVE-tier
tool. Three layers, proven without an LLM:

  (1) DURABLE — the row reaches a terminal executed/failed status + an outcome_detail.
  (2) VISIBLE — the outcome is grounded into the conversation thread as a safe AIMessage
      marker (NOT a tool response → it never re-answers the [QUEUED] tool_call).
  (3) READ — list_recent_outcomes() + the approvals_pending tool surface it across channels.

execute_tool_guarded is mocked so the dispatch result is deterministic; everything downstream
(_record_outcome → persist + grounding + read) runs for real against the isolated test DB.
"""
import contextlib
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from sqlalchemy import delete, select

import app.agent.runner as runner
from app.agent.approval_dispatch import resolve_and_dispatch
from app.agent.graph import init_checkpointer
from app.agent.tools.approvals_pending import approvals_pending
from app.approvals_service import list_recent_outcomes
from app.db.engine import async_session
from app.db.models import PendingApproval

_MARK = f"test-outcome-{uuid.uuid4().hex[:8]}"


@pytest.fixture
async def real_checkpointer():
    from app.agent import graph as graph_module
    if graph_module._checkpointer_cm is not None:
        with contextlib.suppress(Exception):
            await graph_module._checkpointer_cm.__aexit__(None, None, None)
        graph_module._checkpointer = None
        graph_module._checkpointer_cm = None
    await init_checkpointer()
    runner._graph = None  # rebuild against this checkpointer
    yield
    runner._graph = None


async def _seed(thread_id, action_type, payload):
    aid = uuid.uuid4()
    async with async_session() as s:
        s.add(PendingApproval(
            id=aid, thread_id=thread_id, interrupt_id=f"call_{uuid.uuid4().hex[:6]}",
            action_type=action_type, description=f"{action_type} desc", payload=payload,
            status="pending", expires_at=datetime.now(UTC) + timedelta(hours=24),
        ))
        await s.commit()
    return str(aid)


async def _row(aid):
    async with async_session() as s:
        return (await s.execute(select(PendingApproval).where(PendingApproval.id == uuid.UUID(aid)))).scalar_one()


async def _thread_messages(thread_id):
    state = await runner.graph().aget_state({"configurable": {"thread_id": thread_id}})
    return (getattr(state, "values", None) or {}).get("messages") or []


async def _cleanup(thread_id):
    async with async_session() as s:
        await s.execute(delete(PendingApproval).where(PendingApproval.thread_id == thread_id))
        await s.commit()
    # The thread checkpoint is left in the throwaway test DB (dropped next session).


@pytest.mark.asyncio
async def test_failed_email_send_is_durable_visible_and_readable(real_checkpointer):
    thread_id = f"web:{_MARK}-mail"
    aid = await _seed(thread_id, "email_send", {
        "tool_name": "email_send",
        "tool_args": {"to": "not-an-email", "subject": "Q3", "body": "hi"},
    })
    try:
        # the send FAILS at dispatch (mock the guarded execution → success=False).
        fail = SimpleNamespace(success=False, content="[ERROR] invalid recipient: 'not-an-email'", uncertain=False)
        with patch("app.agent.nodes.execute_tool_guarded", AsyncMock(return_value=fail)):
            outcome = await resolve_and_dispatch(aid, "approve", "web", {"approved": True})
        assert outcome.kind == "tool" and outcome.success is False

        # (1) DURABLE — terminal status + detail on the row.
        row = await _row(aid)
        assert row.status == "failed"
        assert "invalid recipient" in (row.outcome_detail or "")

        # (2) VISIBLE — grounded into the thread as an AIMessage marker (not a ToolMessage).
        msgs = await _thread_messages(thread_id)
        marker = msgs[-1]
        assert isinstance(marker, AIMessage) and not isinstance(marker, ToolMessage)
        assert marker.content.startswith("❌") and "invalid recipient" in marker.content

        # (3) READ — the recent-outcomes service + the agent tool surface the failure.
        outcomes = await list_recent_outcomes()
        mine = next(c for c in outcomes if c.approval_id == aid)
        assert mine.status == "failed" and "invalid recipient" in mine.outcome_detail
        tool_out = await approvals_pending()
        assert "❌" in tool_out and "email to not-an-email" in tool_out
        assert "invalid recipient" in tool_out
    finally:
        await _cleanup(thread_id)


@pytest.mark.asyncio
async def test_successful_calendar_create_is_durable_visible_and_readable(real_checkpointer):
    thread_id = f"web:{_MARK}-cal"
    aid = await _seed(thread_id, "calendar_create", {
        "tool_name": "calendar_create",
        "tool_args": {"summary": "Standup", "start_iso": "2026-06-28T09:00"},
    })
    try:
        ok = SimpleNamespace(success=True, content="Calendar event 'Standup' created: https://cal/x", uncertain=False)
        with patch("app.agent.nodes.execute_tool_guarded", AsyncMock(return_value=ok)):
            outcome = await resolve_and_dispatch(aid, "approve", "web", {"approved": True})
        assert outcome.success is True

        row = await _row(aid)
        assert row.status == "executed" and "created" in (row.outcome_detail or "")

        marker = (await _thread_messages(thread_id))[-1]
        assert isinstance(marker, AIMessage) and marker.content.startswith("✅")
        assert "created" in marker.content

        mine = next(c for c in await list_recent_outcomes() if c.approval_id == aid)
        assert mine.status == "executed"
        tool_out = await approvals_pending()
        assert "✅" in tool_out and "calendar create" in tool_out
    finally:
        await _cleanup(thread_id)


@pytest.mark.asyncio
async def test_inbound_email_outcome_persists_without_a_thread_writeback(real_checkpointer):
    # An inbound-email approval has no conversation thread the agent converses in → NO
    # write-back, but the persisted status + the read still cover it (the cross-channel path).
    thread_id = f"email:gmail:{_MARK}"
    aid = await _seed(thread_id, "email_reply", {
        "sender": "Bob <bob@x.com>", "subject": "Re: lunch", "draft": "Noon works.",
    })
    try:
        from app.agent.approval_dispatch import ApprovalDispatchOutcome, _record_outcome
        out = ApprovalDispatchOutcome(kind="email", status="send_failed",
                                      detail="SMTP 550 rejected", thread_id=thread_id)
        # Simulate the post-claim state resolve_approval leaves (status approved + resolved_at
        # stamped) — then run the recorder directly to test the persist + no-write-back path.
        async with async_session() as s:
            await s.execute(
                PendingApproval.__table__.update()
                .where(PendingApproval.id == uuid.UUID(aid))
                .values(status="approved", resolved_at=datetime.now(UTC))
            )
            await s.commit()
        await _record_outcome(aid, out)

        row = await _row(aid)
        assert row.status == "failed" and "550" in (row.outcome_detail or "")
        # no AIMessage was written to the (non-conversational) email thread
        assert await _thread_messages(thread_id) == []
        assert any(c.approval_id == aid for c in await list_recent_outcomes())
    finally:
        await _cleanup(thread_id)
