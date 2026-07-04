"""D33 — an unapplied edit must never leave a soliciting stale restatement.

Instrumented repro pinned the real mechanism (correcting the judge-bypass hypothesis): the judge
IS reached and the edit directive IS issued (card_resolution_judge_entered); the failure was the
agent RESTATING the stale card with a fresh invite instead of re-emitting, and the honest floor
appending WITHOUT stripping that invite. A "yes" to a surviving invite is materially misinformed
consent. Fix: the edit-no-mint floor strips ALL solicitation from the lead — the honest floor is
the only closer. (The engaged path — model re-emits → ONE updated card @10:00 — is pinned by
test_a2_batch31_edit_fixes::test_d29_calendar_time_edit_one_updated_card.)
"""
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import delete

import app.agent.nodes as nodes
from app.agent.nodes import _conversation_referent, queued_finish_node
from app.db.engine import async_session
from app.db.models import PendingApproval

_MARK = f"test-d33-{uuid.uuid4().hex[:8]}"
_INVITES = ("shall i go ahead", "shall i send", "want me to", "ready to send", "go ahead?")


async def _cleanup(thread):
    async with async_session() as s:
        await s.execute(delete(PendingApproval).where(PendingApproval.thread_id == thread))
        await s.commit()


# --------------------------------------------------------------------------- #
# The fix — a restated invite after an unapplied edit is stripped               #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("restate", [
    "Your Reviewer Probe event at 9 am is queued — shall I go ahead?",
    "The event is still set for 9am. Want me to go ahead and create it?",
    "I've got the 9 am event queued. Ready to send?",
    "It's queued for 9 am, Sir. Shall I proceed?",
])
@pytest.mark.asyncio
async def test_edit_no_mint_strips_the_stale_invite(restate):
    """No mint followed the edit directive + the model restated WITH an invite → the final
    reply carries NO invitation (misinformed consent is structurally impossible) and states
    plainly that the change didn't apply."""
    out = await queued_finish_node({
        "messages": [HumanMessage(content="actually make it 10am instead."),
                     AIMessage(content=restate)],
        "final_response": restate, "queued_this_turn": [], "edit_expected": True})
    final = out["final_response"].lower()
    # THE requirement (rule #3): NO invite survives → a bare "yes" can never dispatch the stale
    # card (misinformed consent is structurally impossible). A residual non-soliciting factual
    # sentence is fine — it's honest alongside "the card is unchanged".
    for phrase in _INVITES:
        assert phrase not in final, f"stale invite survived: {phrase!r} in {final!r}"
    assert "?" not in final                                  # not a question → nothing to say yes to
    assert "didn't apply" in final and "unchanged" in final


@pytest.mark.asyncio
async def test_edit_no_mint_keeps_a_genuine_non_soliciting_lead():
    """A non-soliciting lead (a real remark) is preserved — only solicitation is stripped."""
    lead = "I understand — you want it an hour later."
    out = await queued_finish_node({
        "messages": [HumanMessage(content="make it 10am"), AIMessage(content=lead)],
        "final_response": lead, "queued_this_turn": [], "edit_expected": True})
    final = out["final_response"]
    assert lead in final and "didn't apply" in final


# --------------------------------------------------------------------------- #
# The instrumentation — the walk + judge-entry are logged (never invisible)      #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_resolution_walk_and_judge_entry_are_logged(monkeypatch):
    thread = f"web:{_MARK}-log"
    async with async_session() as s:
        row = PendingApproval(
            thread_id=thread, interrupt_id=f"{_MARK}-r", action_type="calendar_create",
            description="d", payload={"tool_name": "calendar_create",
                                      "tool_args": {"title": "Reviewer Probe",
                                                    "start_iso": "2026-07-08T09:00:00-05:00"}},
            status="pending", expires_at=datetime.now(UTC) + timedelta(hours=24))
        s.add(row)
        await s.commit()
        await s.refresh(row)
        rid = str(row.id)

    async def fake_judge(aid, message, recent_context="", require_pending=True):
        from types import SimpleNamespace
        import app.agent.runner as runner
        r = SimpleNamespace(payload={"tool_name": "calendar_create",
                                     "tool_args": {"title": "Reviewer Probe",
                                                   "start_iso": "2026-07-08T09:00:00-05:00"}},
                            action_type="calendar_create", thread_id=thread, status="pending",
                            description="d", is_email_card=False, needs_drafting=False,
                            change="change the start time to 10am")
        return runner._PresentedJudgment(approval_id=aid, row=r, intent="edit", change="to 10am")
    import app.agent.runner as runner
    monkeypatch.setattr(runner, "_judge_presented", fake_judge)

    spy = MagicMock()
    monkeypatch.setattr(nodes, "logger", spy)
    linked = AIMessage(content="I've queued a calendar event 'Reviewer Probe' at 9:00 am for your approval, Sir — shall I go ahead?",
                       additional_kwargs={"jarvis": {"type": "approval", "approval_ids": [rid],
                                                     "mint_class": "fresh", "solicited": True}})
    try:
        out = await nodes.card_resolution_node({
            "user_message": "actually make it 10am instead.", "thread_id": thread,
            "messages": [linked, HumanMessage(content="actually make it 10am instead.")]})
        events = [c.args[0] for c in spy.info.call_args_list]
        assert "card_resolution_walk" in events               # the walk outcome is logged
        assert "card_resolution_judge_entered" in events       # the judge WAS entered (not skipped)
        assert "card_resolution_judge_skipped" not in events
        assert out.get("edit_expected") is True                # the directive was issued
    finally:
        await _cleanup(thread)


def test_referent_walk_finds_the_linked_approval():
    """The walk itself: an approval message anywhere in history is found regardless of a later
    briefing (the D33 dump confirmed this holds)."""
    approval = AIMessage(content="queued", additional_kwargs={"jarvis": {
        "type": "approval", "approval_ids": ["row-9"], "mint_class": "fresh", "solicited": True}})
    briefing = AIMessage(content="2 items await", additional_kwargs={"jarvis": {"type": "briefing"}})
    ref = _conversation_referent([approval, briefing, HumanMessage(content="make it 10am")])
    assert ref["type"] == "approval" and ref["ids"] == ["row-9"] and ref["offer_pending"] is True
