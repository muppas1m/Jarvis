"""GET /approvals/queue (3A) — the unified one-at-a-time queue over BOTH origins.

A PURE READ. These tests insert REAL PendingApproval rows of each shape and assert
the discriminating behaviour: both origins returned oldest-first, the correct
``kind`` + origin-field normalization per row, and expired / resolved rows
excluded. (The queue must never claim or dispatch — there's no mock of
resolve_and_dispatch here precisely because the endpoint must not reach it.)
"""
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete

from app.api.approvals import approval_queue
from app.db.engine import async_session
from app.db.models import PendingApproval


async def _insert(**kw) -> str:
    """Insert one PendingApproval row, returning its id (str)."""
    async with async_session() as s:
        row = PendingApproval(**kw)
        s.add(row)
        await s.commit()
        await s.refresh(row)
        return str(row.id)


def _by_id(resp, approval_id: str):
    return next((c for c in resp.approvals if c.approval_id == approval_id), None)


@pytest.mark.asyncio
async def test_queue_unifies_both_origins_ordered_with_kinds_and_exclusions():
    base = datetime.now(UTC)
    soon = base + timedelta(hours=1)
    tag = uuid.uuid4().hex[:8]
    email_thread = f"email:gmail:qtest-{tag}"
    tool_thread = f"telegram:qtest-{tag}"  # non-email origin → kind "tool"; isolated from web:master

    ids: dict[str, str] = {}
    try:
        # OLDER inbound email reply (should be the earlier of the two in the queue).
        ids["email"] = await _insert(
            thread_id=email_thread, interrupt_id=f"ic-email-{tag}", action_type="email_reply",
            description="Reply to 'Q3' from Priya",
            payload={"provider": "gmail", "message_id": f"m-{tag}",
                     "sender": "Priya <priya@example.com>", "subject": "Q3 numbers",
                     "body": "Does Thursday work for the Q3 review?",
                     "draft": "Confirmed for Thursday."},
            status="pending", created_at=base - timedelta(minutes=10), expires_at=soon,
        )
        # NEWER chat-queued tool call.
        ids["tool"] = await _insert(
            thread_id=tool_thread, interrupt_id=f"ic-tool-{tag}", action_type="calendar_create",
            description="Create event 'Standup'",
            payload={"tool_name": "calendar_create",
                     "tool_args": {"title": "Standup", "when": "9am"}},
            status="pending", created_at=base - timedelta(minutes=5), expires_at=soon,
        )
        # EXPIRED pending row — must be filtered out.
        ids["expired"] = await _insert(
            thread_id=tool_thread, interrupt_id=f"ic-exp-{tag}", action_type="email_send",
            description="Send email (expired)",
            payload={"tool_name": "email_send", "tool_args": {"to": "x@y.com"}},
            status="pending", created_at=base - timedelta(minutes=20),
            expires_at=base - timedelta(minutes=1),
        )
        # RESOLVED row — must be filtered out.
        ids["resolved"] = await _insert(
            thread_id=email_thread, interrupt_id=f"ic-res-{tag}", action_type="email_reply",
            description="Already approved",
            payload={"sender": "a@b.com", "subject": "done", "draft": "ok"},
            status="approved", created_at=base - timedelta(minutes=15), expires_at=soon,
        )

        resp = await approval_queue()

        email_card = _by_id(resp, ids["email"])
        tool_card = _by_id(resp, ids["tool"])

        # --- both origins coexist in ONE queue ---
        assert email_card is not None and tool_card is not None

        # --- correct kind + origin-field normalization per row ---
        assert email_card.kind == "email"
        assert email_card.tool_name == "email_reply"
        # email card carries the ORIGINAL email + the draft (a simple, drafted reply).
        assert email_card.tool_args == {
            "to": "Priya <priya@example.com>", "subject": "Q3 numbers",
            "original": "Does Thursday work for the Q3 review?", "body": "Confirmed for Thursday."
        }
        assert email_card.needs_drafting is False  # a drafted simple reply, not a heads-up
        assert tool_card.kind == "tool"
        assert tool_card.tool_name == "calendar_create"
        assert tool_card.tool_args == {"title": "Standup", "when": "9am"}

        # --- oldest-first: the older email precedes the newer tool ---
        order = [c.approval_id for c in resp.approvals]
        assert order.index(ids["email"]) < order.index(ids["tool"])

        # --- expired + resolved excluded ---
        assert _by_id(resp, ids["expired"]) is None
        assert _by_id(resp, ids["resolved"]) is None

        # --- count is the list length (the explicit-count contract) ---
        assert resp.count == len(resp.approvals)
        # every returned card is pending + carries the dedup key + a kind
        assert all(c.status == "pending" and c.approval_id and c.kind in ("email", "tool")
                   for c in resp.approvals)
    finally:
        async with async_session() as s:
            await s.execute(
                delete(PendingApproval).where(
                    PendingApproval.id.in_([uuid.UUID(i) for i in ids.values()])
                )
            )
            await s.commit()
