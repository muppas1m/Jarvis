"""A2 s1a — the approval message: row linkage (F1) + the solicitation contract (D24+D26).

D26 (reviewer live probe): a paraphrased repeat regenerates the body → sails past the exact-match
dedup → `_supersede_prior_email_card` discards the old card and a NEW one mints → the old read-back
INVITED consent on content the master has never seen. The contract (master-ruled Condition 1):
solicit ONLY on fresh, non-superseding mints; a supersede-mint INFORMS as an update; dedup-only
acknowledges. The class is derived from the round's markers (fresh `[QUEUED]` / supersede
`[QUEUED_UPDATE]` / dedup `[ALREADY_QUEUED]`) — code, never the model.

F1: the terminal approval message carries its row linkage as a code-attached namespaced
`additional_kwargs["jarvis"]` key — invisible at every render surface, persisted by the
checkpointer, never consumed by any wire converter, extracted in CODE for s2's consent targeting.
Condition 2: the D22 heal/repair must preserve the key untouched.
"""
import contextlib
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from sqlalchemy import delete, select

import app.agent.runner as runner
from app.agent.graph import init_checkpointer
from app.agent.nodes import (
    NO_PROGRESS_TAG,
    QUEUED_MARKER_TAG,
    QUEUED_UPDATE_TAG,
    _mint_class_this_turn,
    _readback_for_queued,
    _strip_solicitation,
)
from app.db.engine import async_session
from app.db.models import PendingApproval

_MARK = f"test-s1a-{uuid.uuid4().hex[:8]}"
_SOLICITS = ("shall i go ahead", "shall i send", "should i send", "want me to send")


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


async def _rows(thread):
    async with async_session() as s:
        return (await s.execute(
            select(PendingApproval).where(PendingApproval.thread_id == thread))).scalars().all()


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


# --------------------------------------------------------------------------- #
# Unit — the 3-class mint signal                                                #
# --------------------------------------------------------------------------- #
def test_mint_class_update_tag():
    msgs = [HumanMessage(content="draft that email again"),
            AIMessage(content="", tool_calls=[{"name": "email_send", "args": {}, "id": "c1"}]),
            ToolMessage(content=QUEUED_UPDATE_TAG + " replaced", tool_call_id="c1")]
    assert _mint_class_this_turn(msgs) == "update"


def test_mint_class_mixed_fresh_and_update_is_update():
    """A turn that minted one fresh card AND superseded another must NOT invite —
    one invitation covering unseen content is exactly the D26 trap."""
    msgs = [HumanMessage(content="do both"),
            AIMessage(content="", tool_calls=[{"name": "email_send", "args": {}, "id": "c1"},
                                              {"name": "email_send", "args": {}, "id": "c2"}]),
            ToolMessage(content=QUEUED_MARKER_TAG + " parked", tool_call_id="c1"),
            ToolMessage(content=QUEUED_UPDATE_TAG + " replaced", tool_call_id="c2")]
    assert _mint_class_this_turn(msgs) == "update"


def test_mint_class_prior_turn_update_does_not_leak():
    msgs = [ToolMessage(content=QUEUED_UPDATE_TAG + " replaced", tool_call_id="c0"),  # prior turn
            HumanMessage(content="thanks"),                                            # this turn
            AIMessage(content="You're welcome, Sir.")]
    assert _mint_class_this_turn(msgs) == "none"


# --------------------------------------------------------------------------- #
# Unit — the update template + the solicit-strip guard                          #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_readback_update_informs_never_invites():
    thread = f"web:{_MARK}-tpl"
    rid = await _seed_card(thread, "c1", "email_send",
                           {"to": "mahesh@x.com", "subject": "Site Visit", "body": "v2"})
    try:
        text = await _readback_for_queued([rid], "Sir", mint_class="update")
        low = text.lower()
        assert "updated" in low                        # informs as an update
        assert "mahesh@x.com" in low                   # names the card (D1 guarantee)
        assert "awaiting your approval" in low
        for phrase in _SOLICITS:
            assert phrase not in low
        assert "?" not in text                         # never a question
    finally:
        await _cleanup(thread)


def test_strip_solicitation_drops_only_the_inviting_sentence():
    assert _strip_solicitation("I've drafted the update. Shall I send it?") == "I've drafted the update."
    assert _strip_solicitation("Done. Do you want me to go ahead?") == "Done."
    assert _strip_solicitation("The total is 42.") == "The total is 42."   # preserve-biased
    assert _strip_solicitation("") == ""


# --------------------------------------------------------------------------- #
# THE D26 regression — paraphrased repeat → supersede-mint → INFORM, not invite #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_d26_supersede_mint_informs_never_solicits(real_checkpointer):
    """The reviewer's live catch, reproduced: a pending card exists; the model re-emits the
    same (to, subject) with a REGENERATED body → past the exact-match dedup → supersede fires →
    a NEW card mints. The terminal message must inform as an update and never invite."""
    thread = f"web:{_MARK}-d26"
    args_v1 = {"to": "mahesh@x.com", "subject": "Site Visit", "body": "original body"}
    args_v2 = {"to": "mahesh@x.com", "subject": "Site Visit", "body": "REGENERATED different body"}
    await _seed_card(thread, "orig-c1", "email_send", args_v1)
    reemit = AIMessage(content="", tool_calls=[{"name": "email_send", "args": args_v2, "id": "re-c1"}])
    p1, p2 = _patches(_Scripted([reemit]))
    try:
        with p1, p2:
            env = await runner.run_turn("draft that site visit email again", thread, "web", "u")
        low = (env["response"] or "").lower()
        assert env["status"] == "complete"
        assert "updated" in low, f"supersede-mint must inform as an update: {low!r}"
        assert "mahesh@x.com" in low
        for phrase in _SOLICITS:
            assert phrase not in low, f"D26: solicited consent on unseen content ({phrase!r})"
        rows = await _rows(thread)
        by_status = {r.status for r in rows}
        assert "discarded" in by_status and "pending" in by_status   # old superseded, new pending
        assert next(r for r in rows if r.status == "discarded").resolved_via == "superseded"
    finally:
        await _cleanup(thread)


@pytest.mark.asyncio
async def test_fresh_mint_still_invites_and_carries_linkage(real_checkpointer):
    """The inverse guard + F1: a fresh mint keeps the invitation AND the terminal approval
    message carries the code-attached jarvis linkage, persisted in the checkpoint."""
    thread = f"web:{_MARK}-fresh"
    mint = AIMessage(content="", tool_calls=[
        {"name": "email_send", "args": {"to": "bob@x.com", "subject": "New", "body": "x"}, "id": "c1"}])
    p1, p2 = _patches(_Scripted([mint]))
    try:
        with p1, p2:
            env = await runner.run_turn("email bob about the new thing", thread, "web", "u")
        assert "shall i go ahead" in (env["response"] or "").lower()
        # linkage: the persisted terminal message carries jarvis.approval_ids == the pending row
        snap = await runner.graph().aget_state({"configurable": {"thread_id": thread}})
        msgs = snap.values["messages"]
        terminal = next(m for m in reversed(msgs)
                        if isinstance(m, AIMessage) and (m.additional_kwargs or {}).get("jarvis"))
        meta = terminal.additional_kwargs["jarvis"]
        rows = await _rows(thread)
        assert meta["type"] == "approval" and meta["mint_class"] == "fresh"
        assert meta["approval_ids"] == [str(rows[0].id)]
    finally:
        await _cleanup(thread)


@pytest.mark.asyncio
async def test_update_class_strips_model_solicitation_from_lead(real_checkpointer):
    """Contract enforcement on the model's half: a model-written invite ('Shall I send it?')
    in the lead of an UPDATE-class turn must not survive."""
    thread = f"web:{_MARK}-strip"
    args_v1 = {"to": "amy@x.com", "subject": "Plan", "body": "v1"}
    args_v2 = {"to": "amy@x.com", "subject": "Plan", "body": "v2 regenerated"}
    await _seed_card(thread, "orig-c1", "email_send", args_v1)
    reemit = AIMessage(content="I've redrafted the plan email. Shall I send it?",
                       tool_calls=[{"name": "email_send", "args": args_v2, "id": "re-c1"}])
    p1, p2 = _patches(_Scripted([reemit]))
    try:
        with p1, p2:
            env = await runner.run_turn("redo the plan email", thread, "web", "u")
        low = (env["response"] or "").lower()
        for phrase in _SOLICITS:
            assert phrase not in low, f"model solicitation survived the update class: {low!r}"
        assert "updated" in low
    finally:
        await _cleanup(thread)


# --------------------------------------------------------------------------- #
# Condition 2 — the D22 heal/repair preserve the jarvis linkage key             #
# --------------------------------------------------------------------------- #
def test_strip_divergent_residue_preserves_jarvis_key():
    from app.agent.message_repair import strip_divergent_tool_call_residue

    poisoned_with_link = AIMessage(
        content="",
        tool_calls=[],
        invalid_tool_calls=[{"name": "x", "args": "null", "id": "bad1",
                             "error": None, "type": "invalid_tool_call"}],
        additional_kwargs={
            "tool_calls": [{"id": "bad1", "function": {"arguments": "null", "name": "x"},
                            "type": "function"}],
            "jarvis": {"type": "approval", "approval_ids": ["row-1"], "mint_class": "fresh"},
        },
    )
    fixed = strip_divergent_tool_call_residue(poisoned_with_link)
    assert fixed is not None
    assert "tool_calls" not in fixed.additional_kwargs           # residue stripped
    assert fixed.additional_kwargs["jarvis"]["approval_ids"] == ["row-1"]   # linkage UNTOUCHED


def test_repair_pass_preserves_jarvis_key_on_clean_messages():
    from app.agent.message_repair import repair_orphaned_tool_calls

    approval_msg = AIMessage(
        content="I've queued an email to bob@x.com for your approval, Sir — shall I go ahead?",
        additional_kwargs={"jarvis": {"type": "approval", "approval_ids": ["row-9"],
                                      "mint_class": "fresh"}},
    )
    out = repair_orphaned_tool_calls([HumanMessage(content="q"), approval_msg])
    kept = next(m for m in out if isinstance(m, AIMessage))
    assert kept.additional_kwargs["jarvis"]["approval_ids"] == ["row-9"]
