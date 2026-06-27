"""email_send recipient validation — reject placeholder/missing recipients IN the tool,
BEFORE a card is queued (the "[Manager's Email Address]" → queue → dispatch → Gmail 400 bug).

Two layers:
  - validate_recipient (pure) — the Python gate that rejects placeholders the LLM itself
    emits and accepts real addresses (incl. "Name <addr>").
  - tool_executor_node (integration) — a placeholder recipient mints NO PendingApproval card
    and returns an agent-facing "ask for the address" result; a real recipient queues normally.
"""
import uuid
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from sqlalchemy import delete, select

from app.agent.nodes import tool_executor_node
from app.agent.tools.email_send import validate_recipient
from app.db.engine import async_session
from app.db.models import PendingApproval

_MARK = f"test-recip-{uuid.uuid4().hex[:8]}"


@pytest.mark.parametrize("bad", [
    "", "   ",
    "[Manager's Email Address]", "<recipient email>", "<recipient's email here>",
    "TBD", "manager's email", "your_email_here", "the client's address",
    "Bob", "no-at-sign", "a@b", "@example.com", "name@", "two@@at.com",
])
def test_validate_rejects_placeholders_and_non_addresses(bad):
    err = validate_recipient(bad)
    assert err is not None and "[NEEDS RECIPIENT]" in err


@pytest.mark.parametrize("good", [
    "alice@example.com",
    "bob.smith+tag@sub.example.co.uk",
    "Bob <bob@x.com>",          # RFC "Name <addr>" — the real address is extracted
    "  alice@example.com  ",    # surrounding whitespace is fine
])
def test_validate_accepts_real_addresses(good):
    assert validate_recipient(good) is None


def _state(to, thread_id, call_id):
    return {
        "messages": [AIMessage(content="", tool_calls=[
            {"name": "email_send", "args": {"to": to, "subject": "Hi", "body": "Yo"}, "id": call_id},
        ])],
        "thread_id": thread_id,
        "turn_started_at": "turn-x",
    }


async def _cards(thread_id):
    async with async_session() as s:
        return (await s.execute(
            select(PendingApproval).where(PendingApproval.thread_id == thread_id)
        )).scalars().all()


async def _cleanup(thread_id):
    async with async_session() as s:
        await s.execute(delete(PendingApproval).where(PendingApproval.thread_id == thread_id))
        await s.commit()


@pytest.mark.asyncio
async def test_placeholder_recipient_queues_no_card_and_asks(monkeypatch):
    ping = AsyncMock()
    monkeypatch.setattr("app.messaging.failure_alerter.send_approval_request_to_master", ping)
    thread_id = f"web:{_MARK}-ph"
    call_id = f"call_{uuid.uuid4().hex[:6]}"
    try:
        result = await tool_executor_node(_state("[Manager's Email Address]", thread_id, call_id))
        msg = result["messages"][0]
        assert isinstance(msg, ToolMessage) and msg.tool_call_id == call_id
        assert "[NEEDS RECIPIENT]" in msg.content and "ask the master" in msg.content.lower()
        assert "[QUEUED]" not in msg.content
        # the crux: NO approval card was minted, and the master was NOT pinged
        assert await _cards(thread_id) == []
        ping.assert_not_awaited()
    finally:
        await _cleanup(thread_id)


@pytest.mark.asyncio
async def test_real_recipient_queues_normally(monkeypatch):
    ping = AsyncMock()
    monkeypatch.setattr("app.messaging.failure_alerter.send_approval_request_to_master", ping)
    thread_id = f"web:{_MARK}-ok"
    call_id = f"call_{uuid.uuid4().hex[:6]}"
    try:
        result = await tool_executor_node(_state("alice@example.com", thread_id, call_id))
        assert "[QUEUED]" in result["messages"][0].content
        rows = await _cards(thread_id)
        assert len(rows) == 1
        assert rows[0].payload["tool_args"]["to"] == "alice@example.com"
        assert rows[0].status == "pending"
        ping.assert_awaited_once()
    finally:
        await _cleanup(thread_id)
