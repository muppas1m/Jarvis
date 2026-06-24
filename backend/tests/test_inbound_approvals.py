"""GET /approvals/inbound/next — the one-at-a-time inbound surface primitive.

Seeds REAL PendingApproval rows (the SQL filter — oldest-first, expired excluded,
conversation-origin excluded, limit 1 — is the thing under test, so a fake
session that bypasses the WHERE/ORDER would prove nothing). Cleans up in a
finally so the row set is restored regardless of assertion outcome.
"""
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select

import app.api.approvals as ap
from app.db.engine import async_session
from app.db.models import PendingApproval

MARK = "inbtest"  # unique thread_id marker so cleanup targets only our rows

# The dev DB is shared and may already hold REAL pending gmail approvals (master
# data — never deleted here; cleanup is %inbtest%-scoped). So we can't assert a
# clean slate or a global "None". Instead: seed our rows with ANCIENT created_at
# so they're deterministically the oldest eligible rows (any real row is recent),
# and assert "ours are exhausted" rather than a global null.
_ANCIENT = datetime(2020, 1, 1, tzinfo=UTC)


def _approval(thread_id, *, created_at, expires_min, payload=None, status="pending"):
    return PendingApproval(
        id=uuid.uuid4(),
        thread_id=thread_id,
        interrupt_id=thread_id,
        action_type="gmail_reply",
        description=f"Reply for {thread_id}",
        payload=payload or {"sender": "Bob <bob@x.com>", "subject": "Hi", "draft": "Sure."},
        status=status,
        created_at=created_at,
        expires_at=datetime.now(UTC) + timedelta(minutes=expires_min),
    )


async def _seed(rows):
    async with async_session() as s:
        for r in rows:
            s.add(r)
        await s.commit()


async def _cleanup():
    async with async_session() as s:
        await s.execute(
            delete(PendingApproval).where(PendingApproval.thread_id.like(f"%{MARK}%"))
        )
        await s.commit()


async def _mark_resolved(thread_id):
    async with async_session() as s:
        rows = (
            await s.execute(
                select(PendingApproval).where(PendingApproval.thread_id == thread_id)
            )
        ).scalars().all()
        for r in rows:
            r.status = "approved"
        await s.commit()


async def test_inbound_next_one_at_a_time_and_filters():
    older = f"gmail:{MARK}-older"
    newer = f"gmail:{MARK}-newer"
    convo = f"web:{MARK}-convo"  # conversation-origin → must be EXCLUDED
    expired = f"gmail:{MARK}-expired"  # past expiry → must be EXCLUDED
    mine = {older, newer, convo, expired}
    try:
        await _cleanup()  # start clean (in case a prior crashed run left rows)
        await _seed([
            # convo is the oldest of all, but it's not channel-origin → must skip.
            _approval(convo, created_at=_ANCIENT - timedelta(days=2), expires_min=60),
            # expired is older than `older` too, but past expiry → must skip.
            _approval(expired, created_at=_ANCIENT - timedelta(days=1), expires_min=-1),
            _approval(older, created_at=_ANCIENT, expires_min=60,
                      payload={"sender": "Priya <p@x.com>", "subject": "Q3", "draft": "On it."}),
            _approval(newer, created_at=_ANCIENT + timedelta(days=1), expires_min=60),
        ])

        # 1) oldest ELIGIBLE gmail surfaces — `older`, NOT convo (wrong prefix)
        #    nor expired (past expiry), even though both are older.
        resp = await ap.next_inbound_approval()
        assert resp.approval is not None
        assert resp.approval.thread_id == older
        # card maps the payload → ApprovalCard fields (To / Subject / Body).
        assert resp.approval.tool_args == {"to": "Priya <p@x.com>", "subject": "Q3", "body": "On it."}
        assert resp.approval.tool_name == "gmail_reply"

        # 2) resolve it → the NEXT of ours surfaces (one at a time).
        await _mark_resolved(older)
        resp = await ap.next_inbound_approval()
        assert resp.approval is not None and resp.approval.thread_id == newer

        # 3) resolve it → none of OURS remain eligible. (A real pre-existing row
        #    may still surface — we don't assert global null on a shared DB.)
        await _mark_resolved(newer)
        resp = await ap.next_inbound_approval()
        assert resp.approval is None or resp.approval.thread_id not in mine
    finally:
        await _cleanup()
