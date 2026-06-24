"""Part B1: resolve→send fires AT MOST ONCE per approval. A duplicate email must
be impossible under a button+voice race or a retry. Proven against a REAL seeded
approval + the REAL atomic-claim resolve_approval; only send_email is mocked (to
count dispatches). Both sequential double-decide and CONCURRENT double-decide are
asserted to send exactly once.
"""
import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from sqlalchemy import delete

import app.api.approvals as ap
from app.db.engine import async_session
from app.db.models import PendingApproval
from app.email.provider import SendResult


async def _seed() -> str:
    """Insert a pending inbound-email approval; return its id (str)."""
    aid = uuid.uuid4()
    mid = f"idem-{uuid.uuid4().hex[:10]}"
    async with async_session() as s:
        s.add(PendingApproval(
            id=aid,
            thread_id=f"email:gmail:{mid}",
            interrupt_id=f"email:gmail:{mid}",
            action_type="email_reply",
            description="Reply to 'Hi' from Bob",
            payload={
                "provider": "gmail", "message_id": mid, "thread_ref": "t1",
                "rfc822_message_id": "<x@mail>", "subject": "Hi",
                "sender": "bob@example.com", "draft": "Sure thing.",
            },
            expires_at=datetime.now(UTC) + timedelta(hours=24),
        ))
        await s.commit()
    return str(aid)


async def _cleanup(approval_id: str):
    async with async_session() as s:
        await s.execute(delete(PendingApproval).where(PendingApproval.id == uuid.UUID(approval_id)))
        await s.commit()


def _count_sends(monkeypatch) -> list:
    sends: list = []

    async def fake_send(to, subject, body, reply_to=None, *, source_message_id="", provider_name=""):
        sends.append(to)
        return SendResult(provider="gmail", sent_message_id="sent-1")

    monkeypatch.setattr("app.email.approval_handler.send_email", fake_send)
    return sends


async def test_sequential_double_decide_sends_once(monkeypatch):
    approval_id = await _seed()
    sends = _count_sends(monkeypatch)
    try:
        env1 = await ap.decide_approval(ap.DecideRequest(approved=True), approval_id)
        assert env1["status"] == "complete"  # first claims + sends

        # Second decide: the row is no longer pending → claim fails → 404, NO send.
        with pytest.raises(HTTPException) as ei:
            await ap.decide_approval(ap.DecideRequest(approved=True), approval_id)
        assert ei.value.status_code == 404

        assert len(sends) == 1, f"a duplicate decide must NOT re-send; got {len(sends)} sends"
    finally:
        await _cleanup(approval_id)


async def test_concurrent_double_decide_sends_once(monkeypatch):
    """The button+voice race: two decides fire at once. The atomic claim
    (UPDATE … WHERE status='pending' RETURNING) lets exactly one win."""
    approval_id = await _seed()
    sends = _count_sends(monkeypatch)
    try:
        results = await asyncio.gather(
            ap.decide_approval(ap.DecideRequest(approved=True), approval_id),
            ap.decide_approval(ap.DecideRequest(approved=True), approval_id),
            return_exceptions=True,
        )
        ok = [r for r in results if not isinstance(r, Exception)]
        errs = [r for r in results if isinstance(r, HTTPException)]
        assert len(sends) == 1, f"concurrent decides must send once; got {len(sends)}"
        assert len(ok) == 1 and len(errs) == 1  # one claimed, one 404'd
    finally:
        await _cleanup(approval_id)


async def test_resolve_approval_returns_thread_id_only_to_claimer(monkeypatch):
    """The claim primitive directly: first resolve gets the thread_id, the second
    gets None (already resolved)."""
    approval_id = await _seed()
    try:
        first = await ap.resolve_approval(approval_id, "approve", "web")
        second = await ap.resolve_approval(approval_id, "approve", "voice")
        assert first is not None and first.startswith("email:gmail:")
        assert second is None  # already resolved → not claimed
    finally:
        await _cleanup(approval_id)
