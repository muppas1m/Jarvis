"""approvals_pending — the agent reads the SAME pending-approvals source the HUD shows.

Seeds several real pending approvals (a chat-queued email_send, an inbound email_reply, a
non-email tool) in the isolated test DB and proves:
  - "what's pending?" lists them with REAL content (recipient + subject + snippet for
    emails; humanized action + args for tools),
  - the answer is identical whether or not a card is surfaced — the agent tool, the HUD
    queue, and the in-stream card all flow through app.approvals_service (one source),
  - the "email send; email send" garble is gone (email_send is an EMAIL kind now).
"""
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete

import app.agent.runner as runner
from app.agent.tools.approvals_pending import approvals_pending
from app.api.approvals import approval_queue
from app.approvals_service import list_pending_cards, to_unified_card
from app.db.engine import async_session
from app.db.models import PendingApproval

_MARK = f"test-ap-{uuid.uuid4().hex[:8]}"


def _row(action_type, thread_suffix, payload, *, age_min=0):
    return PendingApproval(
        thread_id=f"{thread_suffix}:{_MARK}",
        interrupt_id=f"{_MARK}-{uuid.uuid4().hex[:6]}",
        action_type=action_type,
        description=f"{action_type} desc",
        payload=payload,
        status="pending",
        created_at=datetime.now(UTC) - timedelta(minutes=age_min),
        expires_at=datetime.now(UTC) + timedelta(hours=24),
    )


async def _seed():
    rows = [
        _row("email_send", "web", {  # a chat-queued OUTBOUND email (the garble case)
            "tool_name": "email_send",
            "tool_args": {"to": "alice@example.com", "subject": "Q3 numbers",
                          "body": "Hi Alice, here are the Q3 numbers you asked for. Best, M."},
        }, age_min=130),
        _row("email_reply", "email:gmail", {  # an inbound auto-drafted REPLY
            "sender": "Bob <bob@example.com>", "subject": "Lunch Thursday?",
            "body": "Are you free for lunch Thursday?", "draft": "Sure, noon works for me.",
        }, age_min=5),
        _row("calendar_create", "web", {  # a NON-email tool action
            "tool_name": "calendar_create",
            "tool_args": {"summary": "Standup", "start_iso": "2026-06-28T09:00"},
        }),
    ]
    async with async_session() as s:
        for r in rows:
            s.add(r)
        await s.commit()


async def _cleanup():
    async with async_session() as s:
        await s.execute(delete(PendingApproval).where(PendingApproval.thread_id.like(f"%{_MARK}")))
        await s.commit()


@pytest.mark.asyncio
async def test_pending_tool_lists_real_content_and_no_garble():
    await _seed()
    try:
        out = await approvals_pending()

        # email_send → REAL recipient + subject + body snippet (not the "email send" garble).
        assert "alice@example.com" in out and "Q3 numbers" in out and "Hi Alice" in out
        # email_reply → recipient + subject + the drafted body.
        assert "Bob <bob@example.com>" in out and "Lunch Thursday?" in out and "noon works" in out
        # non-email tool → humanized action + key args.
        assert "calendar create" in out and "Standup" in out
        # THE garble is gone: no bare-tool-name "email send" anywhere.
        assert "email send" not in out.lower()
        # age surfaced for the old one.
        assert "h ago" in out or "m ago" in out
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_identical_whether_or_not_a_card_is_surfaced():
    await _seed()
    try:
        # The agent tool's answer is rendered from the SAME cards the HUD queue returns…
        cards = await list_pending_cards()
        queue = await approval_queue()
        mine = [c for c in cards if c.approval_id in {q.approval_id for q in queue.approvals}
                and _MARK in c.thread_id]
        assert len(mine) == 3, "the tool and the HUD queue read the one shared source"

        # …and the in-stream card a present master sees is byte-identical to the queue card
        # (both built by to_unified_card) — so the answer can't differ card-or-no-card.
        async with async_session() as s:
            from sqlalchemy import select
            rows = (await s.execute(select(PendingApproval)
                    .where(PendingApproval.thread_id.like(f"%{_MARK}")))).scalars().all()
        by_id = {str(r.id): to_unified_card(r).model_dump() for r in rows}
        for q in queue.approvals:
            if q.approval_id in by_id:
                assert by_id[q.approval_id] == q.model_dump()  # in-stream == polled, no drift

        # The email_send card is an EMAIL kind on BOTH surfaces (the fix).
        send = next(c for c in mine if c.tool_name == "email_send")
        assert send.kind == "email"
        assert send.tool_args == {"to": "alice@example.com", "subject": "Q3 numbers",
                                  "body": "Hi Alice, here are the Q3 numbers you asked for. Best, M."}
    finally:
        await _cleanup()


# (Removed test_summarize_pending_uses_shared_renderer_no_garble — it drove the now-removed
#  runner._summarize_pending, whose underlying renderer approvals_service.summarize_others is
#  itself now-dead collateral, flagged for a follow-up. The approvals_pending TOOL renderer
#  (render_for_agent) is covered by the tests above.)


# --------------------------------------------------------------------------- #
# D6 (A2 s0) — kind filter: "pending calendar approvals?" answers ONE kind.    #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_kind_filter_calendar_excludes_emails():
    await _seed()
    try:
        out = await approvals_pending(kind="calendar")
        assert "Standup" in out or "calendar" in out.lower()   # the calendar card is there
        assert "alice@example.com" not in out                  # the outbound email is NOT
        assert "bob@example.com" not in out                    # the inbound reply is NOT
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_kind_filter_email_excludes_calendar():
    await _seed()
    try:
        out = await approvals_pending(kind="email")
        assert "alice@example.com" in out                      # both email kinds present
        assert "bob@example.com" in out
        assert "Standup" not in out                            # the calendar card is NOT
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_kind_filter_empty_returns_whole_queue():
    await _seed()
    try:
        out = await approvals_pending()                        # no filter → everything
        assert "alice@example.com" in out and "Standup" in out
        # an unknown kind never hides the queue (fail-open read)
        out2 = await approvals_pending(kind="bogus")
        assert "alice@example.com" in out2 and "Standup" in out2
    finally:
        await _cleanup()


@pytest.mark.asyncio
async def test_kind_filter_no_matches_honest_line():
    # empty DB for this mark → a kind ask answers honestly, never errors
    out = await approvals_pending(kind="calendar")
    assert "no calendar approvals" in out.lower() or "awaiting" in out.lower()
