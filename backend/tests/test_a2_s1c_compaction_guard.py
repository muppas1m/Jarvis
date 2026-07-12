"""A2 s1c — the compaction keep-guard: a message LINKED to a still-pending approval row
(the F1 jarvis linkage) is never summarized away; resolved links compact normally; the
jarvis key survives on kept messages (Condition 2's s1c half). Fail-safe on read errors.
"""
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from langchain_core.messages import AIMessage
from sqlalchemy import delete

from app.agent.nodes import _drop_pending_linked
from app.db.engine import async_session
from app.db.models import PendingApproval

_MARK = f"test-s1c-{uuid.uuid4().hex[:8]}"


async def _seed(thread, status="pending"):
    async with async_session() as s:
        row = PendingApproval(
            thread_id=thread, interrupt_id=f"{_MARK}-{uuid.uuid4().hex[:6]}",
            action_type="email_send", description="d",
            payload={"tool_name": "email_send", "tool_args": {"to": "b@x", "subject": "S", "body": "x"}},
            status=status, expires_at=datetime.now(UTC) + timedelta(hours=24))
        s.add(row)
        await s.commit()
        await s.refresh(row)
        return str(row.id)


async def _cleanup(thread):
    async with async_session() as s:
        await s.execute(delete(PendingApproval).where(PendingApproval.thread_id == thread))
        await s.commit()


def _linked(rid, text="I've queued an email for your approval, Sir."):
    m = AIMessage(content=text,
                  additional_kwargs={"jarvis": {"type": "approval", "approval_ids": [rid],
                                                "mint_class": "fresh"}})
    m.id = f"msg-{uuid.uuid4().hex[:8]}"
    return m


def _plain(text):
    m = AIMessage(content=text)
    m.id = f"msg-{uuid.uuid4().hex[:8]}"
    return m


@pytest.mark.asyncio
async def test_pending_linked_message_survives_compaction_window():
    thread = f"web:{_MARK}-keep"
    rid = await _seed(thread, status="pending")
    try:
        window = [_plain("old chatter"), _linked(rid), _plain("more chatter")]
        removable = await _drop_pending_linked(window)
        assert [m.content for m in removable] == ["old chatter", "more chatter"]
        kept = next(m for m in window if m not in removable)
        assert kept.additional_kwargs["jarvis"]["approval_ids"] == [rid]  # key intact (Cond. 2)
    finally:
        await _cleanup(thread)


@pytest.mark.asyncio
async def test_resolved_link_compacts_normally():
    thread = f"web:{_MARK}-resolved"
    rid = await _seed(thread, status="executed")
    try:
        window = [_linked(rid), _plain("chatter")]
        removable = await _drop_pending_linked(window)
        assert len(removable) == 2                              # nothing pending → all compactable
    finally:
        await _cleanup(thread)


@pytest.mark.asyncio
async def test_unlinked_messages_untouched():
    window = [_plain("a"), _plain("b")]
    assert await _drop_pending_linked(window) == window


@pytest.mark.asyncio
async def test_read_error_fails_safe_keeps_linked():
    """On a DB error every LINKED message is kept (never compact what can't be verified)."""
    window = [_plain("a"), _linked("00000000-0000-0000-0000-000000000001")]
    with patch("app.agent.nodes.async_session", side_effect=RuntimeError("db down")):
        removable = await _drop_pending_linked(window)
    assert [m.content for m in removable] == ["a"]              # linked one kept


# --------------------------------------------------------------------------- #
# B1.0 CH-7 (second half) — the un-consumed OFFER keep-rule: the most recent    #
# briefing-tagged message is never compacted (compacting it flips offer_pending #
# False → a bare "yes" meant for the OFFER would dispatch a CARD).              #
# --------------------------------------------------------------------------- #
def _offer(text="2 items await, Sir. Shall I brief you?"):
    return AIMessage(content=text, additional_kwargs={"jarvis": {"type": "briefing"}})


@pytest.mark.asyncio
async def test_ch7_most_recent_offer_survives_compaction():
    thread = f"web:{_MARK}-ch7"
    rid = await _seed(thread)
    try:
        offer = _offer()
        window = [AIMessage(content="old chatter"), _linked(rid), offer,
                  AIMessage(content="more chatter")]
        removable = await _drop_pending_linked(window)
        assert offer not in removable, "the un-consumed offer was compactable (CH-7)"
        # and the walk outcome is preserved: offer more recent than the approval → pending
        from app.agent.nodes import _conversation_referent
        kept_like = [m for m in window if m not in removable]
        ref = _conversation_referent(kept_like)
        assert ref["type"] == "approval" and ref["offer_pending"] is True
    finally:
        await _cleanup(thread)


@pytest.mark.asyncio
async def test_ch7_only_the_most_recent_offer_is_kept():
    """Older briefing messages are inert for the walk — they compact normally."""
    old_offer, new_offer = _offer("old offer"), _offer("new offer")
    window = [old_offer, AIMessage(content="chat"), new_offer]
    removable = await _drop_pending_linked(window)
    assert old_offer in removable                              # inert → compacts
    assert new_offer not in removable                          # the active one is kept
