"""Step A integration — presented-card interactions THROUGH the real graph + checkpointer.

End-to-end proof of the Critical fixes (was a runner short-circuit that ran BEFORE the graph):
  - D2/NV1 — a card interaction now PERSISTS (get_history shows it; it used to vanish on reload).
  - D3     — a card-context QUESTION routes to the AGENT (a real answer), not a canned summary.
  - L1     — a resolution still hits resolve_and_dispatch (the atomic claim); the card flip
             event is reconstructed for the frontend from the node-set card_outcome.

The judge (LLM) and the dispatch (real send) are mocked; the GRAPH + CHECKPOINTER are real.
"""
import contextlib
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import delete, select

import app.agent.approval_dispatch as approval_dispatch
import app.agent.runner as runner
from app.agent.approval_dispatch import ApprovalDispatchOutcome
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
    runner._graph = None
    yield
    runner._graph = None


class _Scripted:
    def __init__(self, responses):
        self._responses = list(responses)

    async def ainvoke(self, _msgs):
        return self._responses.pop(0)


async def _make_card(thread_id):
    async with async_session() as s:
        row = PendingApproval(
            thread_id=thread_id, interrupt_id="cid-1", action_type="calendar_create",
            description="calendar create — My Wedding",
            payload={"tool_name": "calendar_create", "tool_args": {"summary": "My Wedding"}},
            expires_at=datetime.now(UTC) + timedelta(hours=24),
        )
        s.add(row)
        await s.commit()
        await s.refresh(row)
        return str(row.id)


async def _make_email_card(card_thread):
    """A CROSS-THREAD inbound-email reply card — its thread_id (the email thread) differs
    from the conversation thread the master resolves it on."""
    async with async_session() as s:
        row = PendingApproval(
            thread_id=card_thread, interrupt_id=card_thread, action_type="email_reply",
            description="Reply to 'Q3' from Priya",
            payload={"sender": "Priya <p@x.com>", "subject": "Q3", "draft": "On it."},
            expires_at=datetime.now(UTC) + timedelta(hours=24),
        )
        s.add(row)
        await s.commit()
        await s.refresh(row)
        return str(row.id)


async def _wipe_pending():
    """Clean slate for the wrong-card referent gate: in production it reads the GLOBAL live set
    (list_pending_cards = the unified queue), so an integration test that expects count==1 must be
    the only pending card in the (isolated) test DB — other tests' residue would make it ambiguous."""
    async with async_session() as s:
        await s.execute(delete(PendingApproval).where(PendingApproval.status == "pending"))
        await s.commit()


async def _cleanup(thread_id):
    async with async_session() as s:
        await s.execute(delete(PendingApproval).where(PendingApproval.thread_id == thread_id))
        await s.commit()
    with contextlib.suppress(Exception):
        await runner.reset_thread(thread_id)


async def _collect(agen):
    return [ev async for ev in agen]


def _judgment(intent, row):
    return runner._PresentedJudgment(approval_id=str(row.id), row=row, intent=intent, change="")


def _patch_judge(monkeypatch, intent):
    async def fake_judge(approval_id, message, recent_context="", require_pending=True):
        async with async_session() as s:
            row = (await s.execute(
                select(PendingApproval).where(PendingApproval.id == uuid.UUID(approval_id))
            )).scalar_one()
        return _judgment(intent, row)
    monkeypatch.setattr(runner, "_judge_presented", fake_judge)


async def _seed_linked_message(thread_id, aid, solicited=True):
    """A2 s2 migration: consent resolves against the CONVERSATION's jarvis-linked approval
    message (the presented_approval_id no longer targets) — seed the message the real
    queued_finish would have written."""
    from langchain_core.messages import AIMessage
    g = runner.graph()
    await g.aupdate_state(
        {"configurable": {"thread_id": thread_id}},
        {"messages": [AIMessage(
            content="I've queued it for your approval, Sir — shall I go ahead?",
            additional_kwargs={"jarvis": {"type": "approval", "approval_ids": [str(aid)],
                                          "mint_class": "fresh", "solicited": solicited}})]},
        as_node="agent")


def _hist_text(hist):
    return " ".join(m.get("content", "") or "" for m in hist)


async def test_approve_through_graph_persists_and_claims(real_checkpointer, monkeypatch):
    """D2 + L1: approve via stream_turn now runs IN the graph → the exchange PERSISTS and
    the atomic claim (resolve_and_dispatch) ran. The card flip event is reconstructed."""
    await _wipe_pending()  # the gate reads the global live set → keep this card the only one
    thread_id = f"web:test-cardres-{uuid.uuid4().hex[:8]}"
    aid = await _make_card(thread_id)
    try:
        rec: dict = {}

        async def fake_rad(approval_id, action, resolved_via, decision, *, ground_thread=True):
            rec["call"] = (action, resolved_via)
            rec["ground_thread"] = ground_thread
            return ApprovalDispatchOutcome(
                kind="tool", status="executed", success=True,
                detail="Event created.", thread_id=thread_id,
            )

        _patch_judge(monkeypatch, "approve")
        monkeypatch.setattr(approval_dispatch, "resolve_and_dispatch", fake_rad)

        await _seed_linked_message(thread_id, aid)
        events = await _collect(runner.stream_turn(
            "yes, go ahead", thread_id, "web", "u"))

        assert rec["call"] == ("approve", "web")  # L1 — the claim ran
        assert rec["ground_thread"] is False      # the node owns the thread reply
        assert any(e["type"] == "decision_resolved" and e["content"]["status"] == "approved"
                   for e in events)
        hist = await runner.get_history(thread_id)
        text = _hist_text(hist)
        assert "yes, go ahead" in text     # D2 — the master's words PERSISTED
        assert "Event created" in text     # D2 — the outcome reply PERSISTED
    finally:
        await _cleanup(thread_id)


async def test_approve_no_double_write_real_dispatch(real_checkpointer, monkeypatch):
    """Q3 / no-double-write, END-TO-END: the REAL resolve_and_dispatch runs (only the tool
    exec is mocked, no Google call). A chat-queued tool card's thread_id IS the conversation
    thread, so the OLD grounding would have written the outcome a SECOND time. With
    ground_thread=False the outcome reply appears in the thread EXACTLY ONCE, and the row is
    still marked executed (the HUD record survives a crash before the turn checkpoint)."""
    from app.agent.nodes import ToolExecResult

    await _wipe_pending()  # the gate reads the global live set → keep this card the only one
    thread_id = f"web:test-carddbl-{uuid.uuid4().hex[:8]}"
    aid = await _make_card(thread_id)
    try:
        _patch_judge(monkeypatch, "approve")

        async def fake_exec(thread_id_, tool_name, tool_args, *, level, tool_call_id=""):
            return ToolExecResult(content="Event created.", success=True,
                                  error=None, latency_ms=5)
        # mock ONLY the tool execution; the claim + dispatch + _record_outcome run for real
        monkeypatch.setattr("app.agent.nodes.execute_tool_guarded", fake_exec)

        await _seed_linked_message(thread_id, aid)
        events = await _collect(runner.stream_turn(
            "yes, go ahead", thread_id, "web", "u"))

        assert any(e["type"] == "decision_resolved" for e in events)
        hist = await runner.get_history(thread_id)
        text = _hist_text(hist)
        # EXACTLY ONCE — not the node reply AND a "✅ Event created." grounding marker
        assert text.count("Event created") == 1
        assert "✅" not in text  # grounding marker suppressed in-graph
        # the durable row record still flipped (HUD survives even if the turn checkpoint is lost)
        async with async_session() as s:
            row = (await s.execute(
                select(PendingApproval).where(PendingApproval.id == uuid.UUID(aid))
            )).scalar_one()
        assert row.status == "executed"
    finally:
        await _cleanup(thread_id)


async def test_question_through_graph_routes_to_agent_and_persists(real_checkpointer, monkeypatch):
    """D3: a card-context question routes to the AGENT (real answer), persisted — not the old
    canned wrong-context summary. The card stays pending (a question doesn't resolve it)."""
    thread_id = f"web:test-cardq-{uuid.uuid4().hex[:8]}"
    aid = await _make_card(thread_id)
    try:
        _patch_judge(monkeypatch, "unrelated")
        llm = AIMessage(content="Tomorrow you have the 10am standup, Sir.")
        with patch("app.agent.nodes._build_chat_model", lambda *a, **k: _Scripted([llm])):
            events = await _collect(runner.stream_turn(
                "what's on my calendar tomorrow?", thread_id, "web", "u"))

        assert not any(e["type"] == "decision_resolved" for e in events)  # not a resolution
        hist = await runner.get_history(thread_id)
        text = _hist_text(hist)
        assert "what's on my calendar tomorrow?" in text  # D2 — persisted
        assert "10am standup" in text                     # D3 — the AGENT answered
        async with async_session() as s:
            row = (await s.execute(
                select(PendingApproval).where(PendingApproval.id == uuid.UUID(aid))
            )).scalar_one()
        assert row.status == "pending"  # a question leaves the card pending
    finally:
        await _cleanup(thread_id)


async def test_edit_through_graph_emits_card_thread_id(real_checkpointer, monkeypatch):
    """Fix #1 + the real-graph edit test: editing a CROSS-THREAD inbound-email card runs in
    the graph → the decision_resolved(discarded) event carries the CARD's thread_id
    (email:gmail:…), NOT the conversation thread. A new card is re-queued; the master's edit
    persists on the conversation thread; the original card flips to discarded."""
    conv_thread = f"web:test-cardedit-{uuid.uuid4().hex[:8]}"
    card_thread = f"email:gmail:test-{uuid.uuid4().hex[:8]}"
    aid = await _make_email_card(card_thread)
    try:
        _patch_judge(monkeypatch, "edit")

        async def fake_revise(**k):
            return "Shorter draft."
        monkeypatch.setattr("app.email.responder.revise_draft", fake_revise)

        await _seed_linked_message(conv_thread, aid)
        events = await _collect(runner.stream_turn(
            "make it shorter", conv_thread, "web", "u"))

        flips = [e for e in events if e["type"] == "decision_resolved"]
        assert flips and flips[0]["content"]["status"] == "discarded"
        assert flips[0]["thread_id"] == card_thread          # fix #1 — the CARD's thread, not conv
        assert any(e["type"] == "approval_required" for e in events)  # the re-queued card surfaced
        text = _hist_text(await runner.get_history(conv_thread))
        assert "make it shorter" in text and "revised" in text.lower()  # D2 — edit persisted
        async with async_session() as s:
            orig = (await s.execute(
                select(PendingApproval).where(PendingApproval.id == uuid.UUID(aid))
            )).scalar_one()
        assert orig.status == "discarded"
    finally:
        await _cleanup(conv_thread)
        await _cleanup(card_thread)


async def test_supersede_prior_email_card_discards_revision():
    """Liveness (the D15 duplicate-target trigger): re-queuing a REVISED draft for the same
    (email_send, recipient, subject) discards the prior pending card (E2 supersedes E1); a
    genuinely-DIFFERENT email (different subject) to the same person survives (gentle, not a
    hard uniqueness constraint)."""
    from app.agent.nodes import _supersede_prior_card

    thread = f"web:test-supersede-{uuid.uuid4().hex[:8]}"

    async def _email_card(subject, body):
        async with async_session() as s:
            row = PendingApproval(
                thread_id=thread, interrupt_id=uuid.uuid4().hex, action_type="email_send",
                description="d",
                payload={"tool_name": "email_send",
                         "tool_args": {"to": "fernandes@yahoo.me", "subject": subject, "body": body}},
                expires_at=datetime.now(UTC) + timedelta(hours=24))
            s.add(row)
            await s.commit()
            await s.refresh(row)
            return str(row.id)

    e1 = await _email_card("Amazon Delivery Pickup", "Hi [Your Name]")
    other = await _email_card("Lunch next week", "Different email")
    try:
        n = await _supersede_prior_card(
            thread, "email_send",
            {"to": "fernandes@yahoo.me", "subject": "Amazon Delivery Pickup", "body": "Hi Mahesh"})
        assert n == 1
        async with async_session() as s:
            e1_row = (await s.execute(
                select(PendingApproval).where(PendingApproval.id == uuid.UUID(e1)))).scalar_one()
            other_row = (await s.execute(
                select(PendingApproval).where(PendingApproval.id == uuid.UUID(other)))).scalar_one()
        assert e1_row.status == "discarded"     # the revision superseded it
        assert other_row.status == "pending"    # a different-subject email to the same person survives
    finally:
        await _cleanup(thread)
