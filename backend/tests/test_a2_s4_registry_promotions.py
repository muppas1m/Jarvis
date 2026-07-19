"""A2 s4 — the registry promotions (validator / dedup signature / supersede key / enricher) +
tool-generic edit-by-word + the same-turn supersede exemption (governing line 1) + the
edit-no-mint honest floor. Tools declare; the core consumes — no per-tool branches in nodes.
"""
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import delete, select

from app.agent.nodes import (
    _card_edit_redraft,
    _pre_approve_error,
    _queue_signature,
    _supersede_prior_card,
    queued_finish_node,
)
from app.db.engine import async_session
from app.db.models import PendingApproval

_MARK = f"test-s4-{uuid.uuid4().hex[:8]}"


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
        return (await s.execute(
            select(PendingApproval).where(PendingApproval.thread_id == thread))).scalars().all()


async def _cleanup(thread):
    async with async_session() as s:
        await s.execute(delete(PendingApproval).where(PendingApproval.thread_id == thread))
        await s.commit()


def _ensure_registered():
    from app.agent.tools import calendar_tool, email_send
    from app.agent.tools.registry import tool_registry
    if tool_registry.approval_meta("email_send", "supersede_key") is None:
        email_send.register()
        calendar_tool.register()


# --------------------------------------------------------------------------- #
# Site 2 — the validator is declared, not branched                             #
# --------------------------------------------------------------------------- #
def test_validator_via_registry():
    _ensure_registered()
    assert _pre_approve_error("email_send", {"to": "not-an-address", "subject": "x"}) is not None
    assert _pre_approve_error("email_send", {"to": "bob@x.com", "subject": "x"}) is None
    assert _pre_approve_error("calendar_create", {"title": "T"}) is None   # undeclared → no validation


# --------------------------------------------------------------------------- #
# Site 3 — the dedup signature is declared (kind-normalized)                   #
# --------------------------------------------------------------------------- #
def test_dedup_signature_declared_kinds():
    _ensure_registered()
    a = _queue_signature("email_send", {"to": "Bob <BOB@x.com>", "subject": " Plan  Review ", "body": "b1"})
    b = _queue_signature("email_send", {"to": "bob@x.com", "subject": "plan review", "body": "DIFFERENT"})
    assert a == b                                     # body excluded; kinds normalize
    c = _queue_signature("calendar_update", {"event_id": "ev1", "title": "X"})
    d = _queue_signature("calendar_update", {"event_id": "ev1", "title": "totally different"})
    assert c == d                                     # update identity = the event
    # undeclared tool → exact-args JSON (the visible default)
    e = _queue_signature("mystery_tool", {"a": 1})
    f = _queue_signature("mystery_tool", {"a": 2})
    assert e != f


# --------------------------------------------------------------------------- #
# Site 4 — generalized supersede + THE SAME-TURN EXEMPTION (named test)        #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_calendar_update_supersedes_by_event_id():
    _ensure_registered()
    thread = f"web:{_MARK}-ev"
    old_id = await _seed(thread, "calendar_update", {"event_id": "ev9", "start_iso": "2026-07-08T15:00:00+00:00"})
    try:
        n = await _supersede_prior_card(thread, "calendar_update",
                                        {"event_id": "ev9", "start_iso": "2026-07-08T16:00:00+00:00"})
        assert n == 1                                 # ONE event = ONE card
        rows = await _rows(thread)
        assert rows[0].status == "discarded" and rows[0].resolved_via == "superseded"
    finally:
        await _cleanup(thread)


@pytest.mark.asyncio
async def test_same_turn_exemption_batched_two_same_title_events():
    """GOVERNING LINE 1 (named): a batched compound minting two same-title distinct events
    yields TWO cards — supersede matches PRIOR-turn cards only."""
    _ensure_registered()
    thread = f"web:{_MARK}-batch"
    first = await _seed(thread, "calendar_create", {"title": "Dinner", "start_iso": "2026-07-08T18:00:00+00:00"})
    try:
        # the second mint of the SAME turn: first's id is in queued_this_turn → excluded
        n = await _supersede_prior_card(thread, "calendar_create",
                                        {"title": "Dinner", "start_iso": "2026-07-09T18:00:00+00:00"},
                                        exclude_ids=[first])
        assert n == 0                                 # same-turn sibling protected
        assert all(r.status == "pending" for r in await _rows(thread))
        # …but a PRIOR-turn regeneration (no exemption) supersedes by [title]
        n2 = await _supersede_prior_card(thread, "calendar_create",
                                         {"title": "Dinner", "start_iso": "2026-07-10T18:00:00+00:00"})
        assert n2 == 1
    finally:
        await _cleanup(thread)


@pytest.mark.asyncio
async def test_undeclared_supersede_key_never_supersedes():
    thread = f"web:{_MARK}-undecl"
    await _seed(thread, "mystery_tool", {"a": "1"})
    try:
        assert await _supersede_prior_card(thread, "mystery_tool", {"a": "1"}) == 0
    finally:
        await _cleanup(thread)


# --------------------------------------------------------------------------- #
# Tool-generic edit-by-word (D14 class) + the honest no-mint floor             #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_edit_on_tool_card_issues_reemit_directive():
    """'Push the dentist to 4pm' → the edit routes to the agent with the re-emit directive
    (no nudge, no solicitation); the mint path's supersede key does the ONE-updated-card."""
    from types import SimpleNamespace
    import app.agent.runner as runner

    judged = SimpleNamespace(
        approval_id="a1", is_email_card=False, needs_drafting=False, change="move it to 4pm",
        row=SimpleNamespace(payload={"tool_name": "calendar_update",
                                     "tool_args": {"event_id": "ev1", "start_iso": "2026-07-08T15:00:00+00:00"}},
                            action_type="calendar_update", thread_id="web:x", status="pending",
                            description="d"),
    )
    out = await _card_edit_redraft(judged, "push the dentist to 4pm")
    assert out["card_handled"] is False               # routes to the AGENT
    assert out["edit_expected"] is True
    directive = out["card_context"]
    assert "calendar_update" in directive and "ev1" in directive and "4pm" in directive
    assert "shall i" not in directive.lower()          # the old nudge (and its solicit) is gone


@pytest.mark.asyncio
async def test_edit_no_mint_honest_floor():
    """The agent talked instead of re-emitting → the terminal says the change did NOT apply."""
    out = await queued_finish_node({
        "messages": [HumanMessage(content="push the dentist to 4pm"),
                     AIMessage(content="Certainly — I'll adjust the appointment timing.")],
        "final_response": "Certainly — I'll adjust the appointment timing.",
        "queued_this_turn": [], "edit_expected": True})
    final = out["final_response"]
    assert "didn't apply" in final and "unchanged" in final
    assert "Certainly" in final                        # the lead preserved (honest, not hidden)


# --------------------------------------------------------------------------- #
# The enricher — calendar_delete names what dies                               #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_delete_enricher_snapshots_title_and_time():
    _ensure_registered()
    from app.agent.tools import calendar_tool

    class _Events:
        def get(self, calendarId, eventId):
            class _Req:
                def execute(self_inner):
                    return {"summary": "Dentist", "start": {"dateTime": "2026-07-08T16:00:00+00:00"}}
            return _Req()

    class _Svc:
        def events(self):
            return _Events()

    async def _utc(_tz):
        return "UTC", True   # pin the TZ so this test stays about SNAPSHOT mechanics
    with patch.object(calendar_tool, "_service", return_value=_Svc()), \
         patch.object(calendar_tool, "_resolve_timezone", new=_utc):
        out = await calendar_tool.enrich_delete_args({"event_id": "ev1"})
    # (bridge-fix migration 2026-07-19: the old assertion relied on the DEAD legacy read never
    # finding the seeded profile TZ; TZ normalization has its own D32 test.)
    assert out["title"] == "Dentist" and out["start_iso"].startswith("2026-07-08T16")


@pytest.mark.asyncio
async def test_delete_enricher_fails_open():
    from app.agent.tools import calendar_tool
    with patch.object(calendar_tool, "_service", side_effect=RuntimeError("api down")):
        out = await calendar_tool.enrich_delete_args({"event_id": "ev1"})
    assert out == {"event_id": "ev1"}                  # unchanged — the mint proceeds, floor names bare action
