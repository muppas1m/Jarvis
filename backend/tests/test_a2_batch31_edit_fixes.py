"""Batch 3.1 — the four live-probe fixes (D29–D32).

D29: an edit re-emit supersedes BY TARGET ID (key-matching can't see a key-field edit) and is
pinned SAME-TOOL (a wrong-tool re-emit → the honest floor, never a junk card).
D30: with no pending target, a message that NAMES anything is a real-world request → the agent;
the stale-ack fires only on bare card-consent.
D31: calendar outcomes compose from described fields — no event_id/link dumps, no ".," artifact.
D32: the delete-enricher snapshot is normalized to the master's timezone (one rendering).
"""
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import delete, select

import app.agent.nodes as nodes
import app.agent.runner as runner
from app.db.engine import async_session
from app.db.models import PendingApproval

_MARK = f"test-b31-{uuid.uuid4().hex[:8]}"


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


async def _rows(thread):
    async with async_session() as s:
        return (await s.execute(select(PendingApproval)
                .where(PendingApproval.thread_id == thread)
                .order_by(PendingApproval.created_at))).scalars().all()


async def _cleanup(thread):
    async with async_session() as s:
        await s.execute(delete(PendingApproval).where(PendingApproval.thread_id == thread))
        await s.commit()


class _Scripted:
    def __init__(self, responses):
        self._responses = list(responses)

    async def ainvoke(self, _msgs):
        return self._responses.pop(0)


def _patches(llm):
    return (patch("app.agent.nodes._build_chat_model", lambda *a, **k: llm),
            patch("app.messaging.failure_alerter.send_approval_request_to_master", AsyncMock()))


async def _drive_edit_turn(thread, target_id, tool, reemit_msg, user="change it"):
    """Simulate the post-directive turn: state carries the D29 edit pins (as card_resolution
    sets them) and the scripted agent answers the directive with `reemit_msg`."""
    g = runner.graph()
    cfg = {"configurable": {"thread_id": thread}}
    p1, p2 = _patches(_Scripted([reemit_msg]))
    with p1, p2:
        return await g.ainvoke({
            "messages": [HumanMessage(content=user)],
            "thread_id": thread, "platform": "web", "channel_user_id": "u",
            "user_message": user, "tool_calls_this_turn": 0,
            "queued_signatures": [], "queued_this_turn": [], "final_response": "",
            "terminal_delta": "", "briefing_attached": True,   # briefing quiet for the test
            "card_context": "", "card_handled": False, "card_outcome": {},
            "edit_expected": True, "edit_target_id": target_id, "edit_tool_name": tool,
        }, config=cfg)


@pytest.fixture
async def real_checkpointer():
    import contextlib
    from app.agent import graph as graph_module
    if graph_module._checkpointer_cm is not None:
        with contextlib.suppress(Exception):
            await graph_module._checkpointer_cm.__aexit__(None, None, None)
        graph_module._checkpointer = None
        graph_module._checkpointer_cm = None
    from app.agent.graph import init_checkpointer
    await init_checkpointer()
    runner._graph = None
    yield
    runner._graph = None


# --------------------------------------------------------------------------- #
# D29 regression 1 — subject edit (a KEY-field edit) → ONE updated card         #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_d29_subject_edit_one_updated_card_and_inform(real_checkpointer):
    thread = f"web:{_MARK}-subj"
    old_id = await _seed(thread, "email_send",
                         {"to": "amy@x.com", "subject": "Old Subject", "body": "b"})
    reemit = AIMessage(content="", tool_calls=[{
        "name": "email_send",
        "args": {"to": "amy@x.com", "subject": "Weekly Sync", "body": "b"}, "id": "e1"}])
    try:
        result = await _drive_edit_turn(thread, old_id, "email_send", reemit,
                                        user="change the subject to Weekly Sync")
        rows = await _rows(thread)
        by_status = {r.status for r in rows}
        assert len(rows) == 2 and by_status == {"discarded", "pending"}   # ONE live card
        assert next(r for r in rows if r.status == "discarded").resolved_via == "superseded"
        low = (result.get("final_response") or "").lower()
        assert "updated" in low                                # informs as an update
        assert "shall i go ahead" not in low                   # never invites on unseen content
    finally:
        await _cleanup(thread)


# --------------------------------------------------------------------------- #
# D29 regression 2 — calendar time edit on a PENDING create → ONE updated card  #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_d29_calendar_time_edit_one_updated_card(real_checkpointer):
    thread = f"web:{_MARK}-cal"
    old_id = await _seed(thread, "calendar_create",
                         {"title": "Reviewer Probe", "start_iso": "2026-07-08T09:00:00-05:00"})
    reemit = AIMessage(content="", tool_calls=[{
        "name": "calendar_create",
        "args": {"title": "Reviewer Probe", "start_iso": "2026-07-08T10:00:00-05:00"}, "id": "c1"}])
    try:
        result = await _drive_edit_turn(thread, old_id, "calendar_create", reemit,
                                        user="actually make it 10am instead.")
        rows = await _rows(thread)
        assert len(rows) == 2 and {r.status for r in rows} == {"discarded", "pending"}
        live = next(r for r in rows if r.status == "pending")
        assert "10:00" in (live.payload["tool_args"]["start_iso"])
        assert "updated" in (result.get("final_response") or "").lower()
    finally:
        await _cleanup(thread)


# --------------------------------------------------------------------------- #
# D29 regression 3 — WRONG-tool re-emit → the honest floor, never a junk card   #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_d29_wrong_tool_reemit_honest_floor_no_junk_card(real_checkpointer):
    thread = f"web:{_MARK}-wrong"
    old_id = await _seed(thread, "calendar_create",
                         {"title": "Reviewer Probe", "start_iso": "2026-07-08T09:00:00-05:00"})
    # the live failure: the model answered the create-edit with calendar_update + a
    # hallucinated event_id
    reemit = AIMessage(content="", tool_calls=[{
        "name": "calendar_update",
        "args": {"event_id": "calendar_create", "start_iso": "2026-07-08T10:00:00-05:00"},
        "id": "w1"}])
    try:
        result = await _drive_edit_turn(thread, old_id, "calendar_create", reemit,
                                        user="make it 10am")
        rows = await _rows(thread)
        assert len(rows) == 1 and rows[0].status == "pending"   # NO junk card; target untouched
        low = (result.get("final_response") or "").lower()
        assert "didn't apply" in low and "unchanged" in low     # the honest floor
    finally:
        await _cleanup(thread)


# --------------------------------------------------------------------------- #
# D30 — a named real-world request with no pending target routes to the agent   #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_d30_named_request_after_executed_card_goes_to_agent(monkeypatch):
    # the discriminator reads the tool's DECLARED essentials — ensure registration
    from app.agent.tools import calendar_tool, email_send
    from app.agent.tools.registry import tool_registry
    if tool_registry.approval_essentials("calendar_create") is None:
        email_send.register()
        calendar_tool.register()
    thread = f"web:{_MARK}-d30"
    rid = await _seed(thread, "calendar_create",
                      {"title": "Reviewer Probe", "start_iso": "2026-07-08T09:00:00-05:00"},
                      status="executed")

    async def fake_judge(aid, message, recent_context="", require_pending=True):
        from types import SimpleNamespace
        row = SimpleNamespace(payload={"tool_name": "calendar_create",
                                       "tool_args": {"title": "Reviewer Probe",
                                                     "start_iso": "2026-07-08T09:00:00-05:00"}},
                              action_type="calendar_create", thread_id=thread,
                              status="executed", description="d")
        return runner._PresentedJudgment(approval_id=aid, row=row, intent="reject", change="")
    monkeypatch.setattr(runner, "_judge_presented", fake_judge)
    linked = AIMessage(content="I've queued a calendar event for your approval, Sir — shall I go ahead?",
                       additional_kwargs={"jarvis": {"type": "approval", "approval_ids": [rid],
                                                     "mint_class": "fresh", "solicited": True}})
    try:
        # NAMED request ("Reviewer Probe") → to_agent (the agent runs the real delete)
        out = await nodes.card_resolution_node({
            "user_message": "Now delete the Reviewer Probe event.", "thread_id": thread,
            "messages": [linked, HumanMessage(content="Now delete the Reviewer Probe event.")]})
        assert out.get("card_handled") is not True              # routed to the agent
        # BARE consent at the dead card → the stale ack stays
        out2 = await nodes.card_resolution_node({
            "user_message": "reject it.", "thread_id": thread,
            "messages": [linked, HumanMessage(content="reject it.")]})
        assert out2.get("card_handled") is True
        assert "already taken care of" in out2["final_response"]
    finally:
        await _cleanup(thread)


# --------------------------------------------------------------------------- #
# D31 — humanized calendar outcomes (no ids/links, no ".," artifact)            #
# --------------------------------------------------------------------------- #
def test_d31_calendar_outcome_composes_from_described_fields():
    from types import SimpleNamespace
    from app.agent.nodes import _clean_resolution_reply
    from app.approvals_service import UnifiedApprovalCard

    card = UnifiedApprovalCard(
        approval_id="x", kind="tool", thread_id="web:t", tool_name="calendar_delete",
        tool_args={"event_id": "d4kqih", "title": "Reviewer Probe",
                   "start_iso": "2026-07-08T09:00:00-05:00"},
        description="d", status="pending", created_at="2026-07-04T00:00:00+00:00")
    outcome = SimpleNamespace(uncertain=False, kind="tool", success=True,
                              detail="Deleted event 'Reviewer Probe' (event_id: d4kqih). View: https://cal",
                              email_outcome=None)
    reply = _clean_resolution_reply(outcome, "approve", card, "Sir")
    assert "event_id" not in reply and "https" not in reply     # no internals
    assert "Reviewer Probe" in reply and "deleted" in reply.lower()
    assert ".," not in reply                                    # the artifact is gone


# --------------------------------------------------------------------------- #
# D32 — the enricher snapshot lands in the master's timezone                    #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_d32_enricher_normalizes_to_master_tz():
    from app.agent.tools import calendar_tool

    class _Events:
        def get(self, calendarId, eventId):
            class _Req:
                def execute(self_inner):
                    return {"summary": "Standup", "start": {"dateTime": "2026-07-08T14:00:00Z"}}
            return _Req()

    class _Svc:
        def events(self):
            return _Events()

    async def fake_tz(_tz):
        return "America/Chicago", False              # UTC-5 in July

    with patch.object(calendar_tool, "_service", return_value=_Svc()), \
         patch.object(calendar_tool, "_resolve_timezone", new=fake_tz):
        out = await calendar_tool.enrich_delete_args({"event_id": "ev1"})
    assert out["start_iso"].startswith("2026-07-08T09:00:00")   # 14:00Z → 9:00 am Chicago
    assert out["start_iso"].endswith("-05:00")
