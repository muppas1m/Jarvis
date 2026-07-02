"""Step B Stage 1 — L0 in-turn idempotency guard + L1 deterministic read-back + D22 capture.

Reproduce-first: the canned "I've queued both" (D1) becomes a deterministic read-back that NAMES
the queued cards (the guarantee, not the LLM); the in-turn signature deduper is subject-discriminated
(two distinct emails to one recipient both queue); queued_finish STAYS the terminator (loop-safe); a
compound turn's tool_calls survive finalize (constraint #3)."""
import uuid
from datetime import UTC, datetime, timedelta

from langchain_core.messages import AIMessage, ToolMessage
from sqlalchemy import delete, select

from app.agent.nodes import QUEUED_MARKER_TAG, _queue_signature, queued_finish_node
from app.db.engine import async_session
from app.db.models import PendingApproval


# --- L0 signature (unit, deterministic) --------------------------------------
def test_queue_signature_email_subject_discriminated():
    s_a = _queue_signature("email_send", {"to": "bob@x.com", "subject": "Agenda", "body": "a"})
    s_a2 = _queue_signature("email_send", {"to": "bob@x.com", "subject": "Agenda", "body": "REGEN"})
    s_b = _queue_signature("email_send", {"to": "bob@x.com", "subject": "Directions", "body": "d"})
    assert s_a == s_a2          # same to+subject, regenerated body → SAME signature (dedups the bug)
    assert s_a != s_b           # different subject → DISTINCT (two emails to bob in one turn both queue)
    assert _queue_signature("email_send", {"to": "Bob <BOB@x.com>", "subject": " agenda "}) == \
        _queue_signature("email_send", {"to": "bob@x.com", "subject": "Agenda"})  # parseaddr + norm


def test_queue_signature_calendar():
    a = _queue_signature("calendar_create", {"start_iso": "2026-07-05T17:00:00+00:00", "title": "Dinner"})
    b = _queue_signature("calendar_create", {"start_iso": "2026-07-05T17:00:00+00:00", "title": "dinner"})
    c = _queue_signature("calendar_create", {"start_iso": "2026-07-06T17:00:00+00:00", "title": "Dinner"})
    assert a == b and a != c


# --- L1 deterministic read-back (DB-backed) ----------------------------------
async def _seed(thread, cid, action_type, payload):
    """Seed a pending card; return its row PK (str) — A1 keys the read-back on the row id, not cid."""
    async with async_session() as s:
        row = PendingApproval(
            thread_id=thread, interrupt_id=cid, action_type=action_type, description="d",
            payload=payload, expires_at=datetime.now(UTC) + timedelta(hours=24))
        s.add(row)
        await s.commit()
        await s.refresh(row)
        return str(row.id)


async def _cleanup(thread):
    async with async_session() as s:
        await s.execute(delete(PendingApproval).where(PendingApproval.thread_id == thread))
        await s.commit()


def _qmsg(cid):
    return ToolMessage(content=QUEUED_MARKER_TAG + " parked", tool_call_id=cid)


async def test_readback_names_queued_cards():
    """D1 fix: a terminal queued round → the reply NAMES the cards, deterministically (no model),
    not the old canned 'I've queued both for your approval, Sir'. A1: keyed on queued_this_turn."""
    thread = f"web:test-readback-{uuid.uuid4().hex[:8]}"
    id1 = await _seed(thread, "c1", "email_send",
                {"tool_name": "email_send", "tool_args": {"to": "supriya@gmail.com", "subject": "Reminder", "body": "x"}})
    id2 = await _seed(thread, "c2", "calendar_create",
                {"tool_name": "calendar_create", "tool_args": {"title": "Dinner Party", "start_iso": "2026-07-05T17:00:00+00:00"}})
    try:
        ai = AIMessage(content="", tool_calls=[
            {"name": "email_send", "args": {}, "id": "c1"},
            {"name": "calendar_create", "args": {}, "id": "c2"}])
        out = await queued_finish_node({"messages": [ai, _qmsg("c1"), _qmsg("c2")], "queued_this_turn": [id1, id2]})
        reply = out["final_response"].lower()
        assert "supriya" in reply                                  # names the email card
        assert "dinner party" in reply or "calendar" in reply      # names the calendar card
        assert "queued both" not in reply                          # NOT the old canned closing
    finally:
        await _cleanup(thread)


async def test_readback_single_card_names_it():
    thread = f"web:test-readback1-{uuid.uuid4().hex[:8]}"
    id1 = await _seed(thread, "c1", "email_send",
                {"tool_name": "email_send", "tool_args": {"to": "bob@x.com", "subject": "Hi", "body": "x"}})
    try:
        ai = AIMessage(content="", tool_calls=[{"name": "email_send", "args": {}, "id": "c1"}])
        out = await queued_finish_node({"messages": [ai, _qmsg("c1")], "queued_this_turn": [id1]})
        assert "bob@x.com" in out["final_response"]
    finally:
        await _cleanup(thread)


async def test_readback_compound_preserves_answer_and_toolcalls():
    """Constraint #3: a compound's genuine answer is preserved AND the agent's tool_calls survive
    finalize — the read-back is APPENDED as its own message, never rewriting the tool_calls AIMessage
    (no orphaned tool_call / Jun-11 poisoning)."""
    thread = f"web:test-compound-{uuid.uuid4().hex[:8]}"
    id1 = await _seed(thread, "c1", "email_send",
                {"tool_name": "email_send", "tool_args": {"to": "bob@x.com", "subject": "Hi", "body": "x"}})
    try:
        ai = AIMessage(content="2 plus 2 is 4.", tool_calls=[{"name": "email_send", "args": {}, "id": "c1"}])
        out = await queued_finish_node({"messages": [ai, _qmsg("c1")], "queued_this_turn": [id1]})
        assert "2 plus 2 is 4" in out["final_response"]              # genuine answer preserved
        assert "bob@x.com" in out["final_response"]                  # read-back appended
        assert all(not getattr(m, "tool_calls", None) for m in out["messages"])  # appended msg has NO tool_calls
        assert ai.tool_calls                                         # the original tool_calls message is untouched
    finally:
        await _cleanup(thread)
