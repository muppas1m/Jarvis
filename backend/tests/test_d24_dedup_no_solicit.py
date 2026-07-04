"""D24 interim guard — solicit consent ONLY on new mints (the "yes-trap" amplifier removal).

The finding (A1.3 hands-on, 2026-07-03): the master tried to REJECT a queued email; the seal
refused on ambiguity (correct); the follow-up misrouted to the agent loop, which re-emitted the
same email_send → content-dedup ([ALREADY_QUEUED], no new card) → the read-back tail still
offered "— shall I go ahead?" — a consent invitation for the exact action the master was
rejecting. One committed "yes" would have dispatched it.

The guard: `queued_finish` derives mint-vs-dedup from the A1 marker split (fresh mint →
`[QUEUED]`; every dedup branch → `[ALREADY_QUEUED]`) and a dedup-only turn gets a NON-soliciting
read-back — names the card, no invitation. The full stateful disambiguation is B1; this only
removes the amplifier. Scope: the read-back template + its signal — the seal / card-resolution /
consent judging are untouched.
"""
import contextlib
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from sqlalchemy import delete

import app.agent.runner as runner
from app.agent.graph import init_checkpointer
from app.agent.nodes import (
    NO_PROGRESS_TAG,
    QUEUED_MARKER_TAG,
    _minted_new_this_turn,
    _readback_for_queued,
    queued_finish_node,
)
from app.db.engine import async_session
from app.db.models import PendingApproval

_MARK = f"test-d24-{uuid.uuid4().hex[:8]}"
_SOLICITS = ("shall i go ahead", "shall i send")


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


class _Scripted:
    def __init__(self, responses):
        self._responses = list(responses)

    async def ainvoke(self, _msgs):
        return self._responses.pop(0)


def _send_call(to, subject, body, cid):
    return {"name": "email_send", "args": {"to": to, "subject": subject, "body": body}, "id": cid}


# --------------------------------------------------------------------------- #
# Unit — the mint-vs-dedup signal (the A1 marker split, this-turn bounded)      #
# --------------------------------------------------------------------------- #
def test_fresh_mint_marker_detected():
    msgs = [HumanMessage(content="send it"),
            AIMessage(content="", tool_calls=[_send_call("t@x", "S", "b", "c1")]),
            ToolMessage(content=QUEUED_MARKER_TAG + " parked", tool_call_id="c1")]
    assert _minted_new_this_turn(msgs) is True


def test_dedup_only_round_is_not_a_mint():
    msgs = [HumanMessage(content="i ment the approval for timmy"),
            AIMessage(content="", tool_calls=[_send_call("t@x", "S", "b", "c1")]),
            ToolMessage(content=NO_PROGRESS_TAG + " already", tool_call_id="c1")]
    assert _minted_new_this_turn(msgs) is False


def test_prior_turn_mint_does_not_leak_across_the_boundary():
    """A fresh [QUEUED] from a PRIOR turn sits above this turn's HumanMessage — the scan
    must stop at the boundary and report no mint for THIS turn."""
    msgs = [AIMessage(content="", tool_calls=[_send_call("t@x", "S", "b", "c0")]),
            ToolMessage(content=QUEUED_MARKER_TAG + " parked", tool_call_id="c0"),   # prior turn
            HumanMessage(content="reject that"),                                      # this turn
            AIMessage(content="", tool_calls=[_send_call("t@x", "S", "b", "c1")]),
            ToolMessage(content=NO_PROGRESS_TAG + " already", tool_call_id="c1")]
    assert _minted_new_this_turn(msgs) is False


# --------------------------------------------------------------------------- #
# Unit — the template split                                                    #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_readback_dedup_names_card_without_soliciting():
    thread = f"web:{_MARK}-tpl"
    rid = await _seed_card(thread, "c1", "email_send",
                           {"to": "timmy@x.com", "subject": "Hello", "body": "x"})
    try:
        text = await _readback_for_queued([rid], "Sir", mint_class="none")
        low = text.lower()
        assert "timmy@x.com" in low                     # still NAMES the card (D1 guarantee)
        assert "already queued" in low and "awaiting your approval" in low
        for phrase in _SOLICITS:
            assert phrase not in low                     # no consent invitation
        assert "?" not in text                           # not a question at all
    finally:
        await _cleanup(thread)


@pytest.mark.asyncio
async def test_readback_mint_still_invites():
    """MIGRATED (A2 s2, declared): _readback_for_queued is now the ERROR-path contract and
    never solicits (a bare "yes" after an error must confirm — no anchor exists). The fresh
    INVITE lives in the terminal-composition floor (_render_approval_floor), asserted here."""
    from app.agent.nodes import _fetch_queued_cards, _render_approval_floor
    thread = f"web:{_MARK}-tpl2"
    rid = await _seed_card(thread, "c1", "email_send",
                           {"to": "bob@x.com", "subject": "Hi", "body": "x"})
    try:
        cards = await _fetch_queued_cards([rid])
        text = _render_approval_floor(cards, "Sir", "fresh")
        assert "shall i go ahead" in text.lower()        # the inviting tail is mint-only
        # …and the ERROR-path read-back for the same cards never solicits:
        err_text = await _readback_for_queued([rid], "Sir", mint_class="fresh")
        assert "shall i go ahead" not in err_text.lower()
        assert "bob@x.com" in err_text                    # still names the card
    finally:
        await _cleanup(thread)


@pytest.mark.asyncio
async def test_readback_fallbacks_split_too():
    assert "?" not in await _readback_for_queued([], "Sir", mint_class="none")
    assert "already queued" in (await _readback_for_queued([], "Sir", mint_class="none")).lower()


# --------------------------------------------------------------------------- #
# THE regression — the master's exact D24 sequence, end to end                  #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_d24_dedup_only_turn_does_not_solicit(real_checkpointer):
    """Queued card exists → a turn whose tool round is DEDUP-only (the misrouted follow-up
    re-emitting the same send) → the read-back names the card but must NOT offer consent."""
    thread = f"web:{_MARK}-e2e"
    args = {"to": "timmy@x.com", "subject": "Project Update", "body": "hello"}
    await _seed_card(thread, "orig-c1", "email_send", args)     # the card the master wants to reject
    reemit = AIMessage(content="", tool_calls=[
        {"name": "email_send", "args": args, "id": "re-c1"}])   # the agent re-emits the same send
    try:
        with patch("app.agent.nodes._build_chat_model", lambda *a, **k: _Scripted([reemit])), \
             patch("app.messaging.failure_alerter.send_approval_request_to_master", AsyncMock()):
            env = await runner.run_turn("i ment the approval for timmy", thread, "web", "u")
        low = (env["response"] or "").lower()
        assert env["status"] == "complete"
        assert "timmy@x.com" in low                              # names the card
        assert "already queued" in low
        for phrase in _SOLICITS:
            assert phrase not in low, f"yes-trap: still soliciting ({phrase!r}) after a dedup-only round"
    finally:
        await _cleanup(thread)


# --------------------------------------------------------------------------- #
# Site 2 — the D14 edit-refusal nudge (nodes.py _card_edit_redraft)             #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_d24_site2_edit_refusal_nudge_does_not_solicit():
    """MIGRATED (A2 s4, declared): the site-2 nudge BRANCH IS DEAD — edit-by-word is now
    tool-generic (the re-emit directive → ONE updated card). The D24 class property survives:
    an edit turn must never solicit a send. Asserted on the directive path."""
    from types import SimpleNamespace

    from app.agent.nodes import _card_edit_redraft

    judged = SimpleNamespace(
        approval_id="a1b2c3d4", is_email_card=False, needs_drafting=False,
        row=SimpleNamespace(thread_id="web:master", action_type="email_send", status="pending",
                            description="d",
                            payload={"tool_name": "email_send",
                                     "tool_args": {"to": "t@x.com", "subject": "S", "body": "b"}}),
        change="trim the body",
    )
    out = await _card_edit_redraft(judged, "trim the body")
    assert out["card_handled"] is False                 # routes to the agent (re-emit directive)
    assert out["edit_expected"] is True
    low = (out["card_context"] or "").lower()
    assert "i can only send or discard" not in low      # the nudge is gone
    for phrase in _SOLICITS:
        assert phrase not in low, f"yes-trap at site 2: directive solicits ({phrase!r})"


@pytest.mark.asyncio
async def test_d24_inverse_fresh_mint_still_invites(real_checkpointer):
    thread = f"web:{_MARK}-inv"
    mint = AIMessage(content="", tool_calls=[
        {"name": "email_send", "args": {"to": "bob@x.com", "subject": "New", "body": "x"}, "id": "c1"}])
    try:
        with patch("app.agent.nodes._build_chat_model", lambda *a, **k: _Scripted([mint])), \
             patch("app.messaging.failure_alerter.send_approval_request_to_master", AsyncMock()):
            env = await runner.run_turn("email bob about the new thing", thread, "web", "u")
        assert "shall i go ahead" in (env["response"] or "").lower()   # fresh mint keeps the invite
    finally:
        await _cleanup(thread)
