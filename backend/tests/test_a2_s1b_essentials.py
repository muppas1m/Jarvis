"""A2 s1b-1 — the Essentials registry + verify-and-keep (F2) + the calendar describe enrichment.

The registry standard (master-ruled): every APPROVE-tier tool DECLARES the payload fields its
approval message must name; undeclared tools fall back to the humanized name AND log a warning
(the weak path stays visible). The floor fires DELTA-ONLY over cards the prose did NOT name;
prose is ALWAYS kept (the inverse of the retired collapse); the solicitation contract guarantees
exactly one class-consistent closer.
"""
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from sqlalchemy import delete

from app.agent.approval_essentials import card_essentials_named, essentials_named
from app.agent.nodes import QUEUED_MARKER_TAG, queued_finish_node
from app.agent.tools.registry import tool_registry
from app.approvals_service import UnifiedApprovalCard, describe_card
from app.db.engine import async_session
from app.db.models import PendingApproval

_MARK = f"test-s1b-{uuid.uuid4().hex[:8]}"


def _card(tool_name, **targs):
    return UnifiedApprovalCard(
        approval_id="x", kind="email" if tool_name == "email_send" else "tool",
        thread_id="web:t", tool_name=tool_name, tool_args=targs, description="d",
        status="pending", created_at="2026-07-04T00:00:00+00:00")


async def _seed_card(thread, cid, tool_name, tool_args):
    async with async_session() as s:
        row = PendingApproval(
            thread_id=thread, interrupt_id=cid, action_type=tool_name, description="d",
            payload={"tool_name": tool_name, "tool_args": tool_args}, status="pending",
            expires_at=datetime.now(UTC) + timedelta(hours=24))
        s.add(row)
        await s.commit()
        await s.refresh(row)
        return str(row.id)


async def _cleanup(thread):
    async with async_session() as s:
        await s.execute(delete(PendingApproval).where(PendingApproval.thread_id == thread))
        await s.commit()


# --------------------------------------------------------------------------- #
# The registry declarations                                                    #
# --------------------------------------------------------------------------- #
def test_registry_declarations_present():
    from app.agent.tools import calendar_tool, email_send
    if tool_registry.approval_essentials("email_send") is None:
        email_send.register()
        calendar_tool.register()
    assert tool_registry.approval_essentials("email_send") == [
        {"field": "to", "kind": "recipient"}, {"field": "subject", "kind": "text"}]
    assert tool_registry.approval_essentials("calendar_create") == [
        {"field": "title", "kind": "text"}, {"field": "start_iso", "kind": "time"}]
    # FLIPPED in A2 s4 (declared): the mint-time enricher now guarantees {title, start_iso}
    # for deletes — the conscious-empty declaration became a real one (a delete approval
    # must NAME which event dies).
    assert tool_registry.approval_essentials("calendar_delete") == [
        {"field": "title", "kind": "text"}, {"field": "start_iso", "kind": "time"}]
    assert tool_registry.approval_essentials("no_such_tool") is None    # undeclared


def test_undeclared_tool_warns_and_floors(monkeypatch):
    """The silent-erosion guard: an undeclared APPROVE tool floors AND warns (visibly weak)."""
    from unittest.mock import MagicMock

    import app.agent.approval_essentials as ae
    spy = MagicMock()
    monkeypatch.setattr(ae, "logger", spy)
    named = card_essentials_named("I'll run the frobnicator now.", "frobnicate_tool", {"x": "1"})
    assert named is False                                               # floor fires
    spy.warning.assert_called_once_with("approval_essentials_undeclared", tool="frobnicate_tool")


def test_conscious_empty_declaration_floors_silently(monkeypatch):
    from unittest.mock import MagicMock

    import app.agent.approval_essentials as ae
    spy = MagicMock()
    monkeypatch.setattr(ae, "logger", spy)
    named = card_essentials_named("Deleting the standup event.", "calendar_delete", {"event_id": "e1"})
    assert named is False
    spy.warning.assert_not_called()                                     # a decision, not an omission


# --------------------------------------------------------------------------- #
# The matchers — structural presence, never prose surgery                      #
# --------------------------------------------------------------------------- #
def test_recipient_matches_address_or_local_part():
    args = {"to": "bob@example.com", "subject": "Q3 numbers"}
    assert card_essentials_named("I've drafted the Q3 numbers email to bob@example.com.", "email_send", args)
    assert card_essentials_named("I've drafted the Q3 numbers email to Bob.", "email_send", args)
    assert not card_essentials_named("I've drafted the Q3 numbers email.", "email_send", args)


def test_short_subject_needs_word_boundary():
    """'Hi' must not match inside 'this' — the D25 lesson (no substring traps)."""
    args = {"to": "bob@x.com", "subject": "Hi"}
    assert not card_essentials_named("I queued this email to Bob.", "email_send", args)
    assert card_essentials_named("I queued the 'Hi' email to Bob.", "email_send", args)


def test_time_matcher_tolerant_forms():
    args = {"title": "Standup", "start_iso": "2026-07-10T17:00:00+00:00"}
    for prose in ("Standup at 17:00.", "Standup at 5 pm.", "Standup at 5pm.",
                  "Standup on Friday."):
        assert card_essentials_named(prose, "calendar_create", args), prose
    assert not card_essentials_named("I scheduled the Standup.", "calendar_create", args)
    # unparseable time value → not nameable → floor (safe default)
    assert not card_essentials_named("Standup at 5 pm.", "calendar_create",
                                     {"title": "Standup", "start_iso": "whenever"})


def test_update_with_empty_fields_skips_them():
    """calendar_update that only changed the title: start_iso empty → skipped, title checked."""
    args = {"event_id": "e1", "title": "Team Sync", "start_iso": ""}
    assert card_essentials_named("I renamed it to Team Sync.", "calendar_update", args)
    assert not card_essentials_named("I renamed the event.", "calendar_update", args)
    # NOTHING checkable (all declared fields empty) → floor fires
    assert not card_essentials_named("I moved the location.", "calendar_update",
                                     {"event_id": "e1", "title": "", "start_iso": ""})


def test_turn_gate_requires_every_card():
    cards = [_card("email_send", to="bob@x.com", subject="Plan"),
             _card("email_send", to="amy@x.com", subject="Budget")]
    assert essentials_named("Emails to Bob about the plan and Amy about the budget.", cards)
    assert not essentials_named("Emails to Bob about the plan and one more.", cards)
    assert not essentials_named("Two emails queued.", cards)
    assert not essentials_named("anything", [])                        # nothing to verify → floor


# --------------------------------------------------------------------------- #
# queued_finish composition — delta-only floor + one closer (node-level)       #
# --------------------------------------------------------------------------- #
def _qmsg(cid):
    return ToolMessage(content=QUEUED_MARKER_TAG + " parked", tool_call_id=cid)


def _state(lead, cids_and_ids, human="do it"):
    msgs = [HumanMessage(content=human),
            AIMessage(content=lead, tool_calls=[
                {"name": "email_send", "args": {}, "id": cid} for cid, _ in cids_and_ids])]
    msgs += [_qmsg(cid) for cid, _ in cids_and_ids]
    return {"messages": msgs, "queued_this_turn": [rid for _, rid in cids_and_ids]}


@pytest.mark.asyncio
async def test_floor_fires_delta_only_prose_kept():
    """The master's probe: paraphrased-subject prose → the floor names ONLY the unnamed card;
    the prose survives verbatim; no double-say (the named card appears once)."""
    thread = f"web:{_MARK}-delta"
    r1 = await _seed_card(thread, "c1", "email_send",
                          {"to": "bob@x.com", "subject": "Plan", "body": "x"})
    r2 = await _seed_card(thread, "c2", "email_send",
                          {"to": "amy@x.com", "subject": "Budget", "body": "y"})
    try:
        lead = "I've queued the email to Bob about the plan, Sir."   # names card 1 only
        out = await queued_finish_node(_state(lead, [("c1", r1), ("c2", r2)]))
        final = out["final_response"]
        assert lead in final                                         # prose KEPT verbatim
        assert "amy@x.com" in final                                  # floor names the UNNAMED card
        assert final.count("bob@x.com") == 0                         # named card NOT re-described
        assert final.lower().count("shall i go ahead") == 1          # exactly one solicitation
    finally:
        await _cleanup(thread)


@pytest.mark.asyncio
async def test_fresh_lead_already_invites_exactly_one_solicitation():
    """The master's probe: a fresh mint whose lead already invites → the code invite stands
    down everywhere (floor variant without the invite / no closer) — exactly one solicitation."""
    thread = f"web:{_MARK}-oneinvite"
    r1 = await _seed_card(thread, "c1", "email_send",
                          {"to": "bob@x.com", "subject": "Plan", "body": "x"})
    try:
        # (a) lead invites but does NOT name essentials → floor fires WITHOUT its invite
        lead_a = "The draft's ready. Shall I send it?"
        out_a = await queued_finish_node(_state(lead_a, [("c1", r1)]))
        low_a = out_a["final_response"].lower()
        assert low_a.count("shall i") == 1                          # only the model's
        assert "bob@x.com" in low_a                                  # floor still names (no invite)
        # (b) lead invites AND names everything → empty-content linkage message, no addition
        lead_b = "I've drafted the Plan email to bob@x.com. Shall I send it?"
        out_b = await queued_finish_node(_state(lead_b, [("c1", r1)]))
        low_b = out_b["final_response"].lower()
        assert low_b.count("shall i") == 1
        msg = out_b["messages"][0]
        assert msg.content == ""                                     # linkage rides empty content
        assert msg.additional_kwargs["jarvis"]["approval_ids"] == [r1]
    finally:
        await _cleanup(thread)


@pytest.mark.asyncio
async def test_named_essentials_get_class_closer_only():
    thread = f"web:{_MARK}-closer"
    r1 = await _seed_card(thread, "c1", "email_send",
                          {"to": "bob@x.com", "subject": "Plan", "body": "x"})
    try:
        lead = "I've drafted the Plan email to bob@x.com."           # named, no invite
        out = await queued_finish_node(_state(lead, [("c1", r1)]))
        final = out["final_response"]
        assert lead in final
        assert "Shall I go ahead, Sir?" in final                     # the ONE code closer
        assert final.count("bob@x.com") == 1                         # never re-described
    finally:
        await _cleanup(thread)


# --------------------------------------------------------------------------- #
# The calendar describe enrichment (shared atom)                               #
# --------------------------------------------------------------------------- #
def test_describe_card_calendar_names_title_and_time():
    c = _card("calendar_create", title="Dinner Party", start_iso="2026-07-10T17:00:00+00:00")
    d = describe_card(c)
    assert "Dinner Party" in d
    assert "5:00 pm" in d and "Friday" in d
    assert d != "calendar create"                                    # the bare garble is gone


def test_describe_card_calendar_unparseable_time_degrades():
    c = _card("calendar_create", title="Dinner", start_iso="not-a-time")
    d = describe_card(c)
    assert "Dinner" in d and "at" not in d.split("'")[-1]            # title named, time omitted
