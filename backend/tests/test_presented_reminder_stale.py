"""Once-then-quiet reminder (durable per-card flag), the stale-card ack (voice==text),
the synthesized card-context line, and the Telegram heads-up confirmation label."""
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy import delete, select

import app.agent.runner as runner
from app.db.engine import async_session
from app.db.models import PendingApproval


async def _collect(agen):
    return [e async for e in agen]


def _email_row(needs_drafting=False):
    return SimpleNamespace(
        thread_id="email:gmail:x", action_type="email_reply",
        description="Reply to 'Q3' from Priya",
        payload={"sender": "Priya <p@x.com>", "subject": "Q3", "body": "orig",
                 "draft": "d", "needs_drafting": needs_drafting},
    )


# --- the synthesized card-context line (pure, used by production AND the live test) ---
def test_card_context_line_email_send():
    line = runner._card_context_line(_email_row())
    assert line.startswith("Assistant:") and "Priya" in line and "send it" in line.lower()


def test_card_context_line_headsup():
    line = runner._card_context_line(_email_row(needs_drafting=True))
    assert "Priya" in line and "draft a reply" in line.lower()  # framed as "shall I draft?"


def test_card_context_line_tool():
    row = SimpleNamespace(thread_id="web:master", action_type="calendar_create",
                          description="Create event 'Standup'", payload={})
    line = runner._card_context_line(row)
    assert line.startswith("Assistant:") and "Standup" in line


# --- stale-card ack (voice == text) ------------------------------------------
async def test_stale_ack_text_no_audio():
    events = await _collect(runner._stale_ack(speak=False))
    done = [e for e in events if e["type"] == "done"][-1]
    assert "already taken care of" in done["content"]["response"].lower()
    assert not any(e["type"] == "audio" for e in events)  # TEXT → no audio


async def test_stale_ack_voice_speaks(monkeypatch):
    synth = AsyncMock(return_value=b"AUDIO")
    monkeypatch.setattr(runner, "synthesize", synth)
    events = await _collect(runner._stale_ack(speak=True))
    assert any(e["type"] == "audio" for e in events)  # VOICE → spoke the ack
    assert synth.await_count == 1
    done = [e for e in events if e["type"] == "done"][-1]
    assert "already taken care of" in done["content"]["response"].lower()  # SAME text as the text path


# --- once-then-quiet reminder (durable per-card flag) ------------------------
async def _insert_card():
    async with async_session() as s:
        row = PendingApproval(
            thread_id=f"email:gmail:rem-{uuid.uuid4().hex[:8]}", interrupt_id="i",
            action_type="email_reply", description="Reply to 'Q3' from Priya",
            payload={"sender": "Priya <p@x.com>", "subject": "Q3", "body": "o", "draft": "d", "needs_drafting": False},
            status="pending", expires_at=datetime.now(UTC) + timedelta(hours=24),
        )
        s.add(row)
        await s.commit()
        await s.refresh(row)
        return row


async def _cleanup(rid):
    async with async_session() as s:
        await s.execute(delete(PendingApproval).where(PendingApproval.id == rid))
        await s.commit()


def _j(row):
    return runner._PresentedJudgment(approval_id=str(row.id), row=row, intent="unrelated", change="")


async def test_reminder_once_then_quiet_per_card():
    row1 = await _insert_card()
    try:
        # Turn 1 (off-topic) → reminds + claims the durable flag.
        first = await runner._reminder_for(_j(row1))
        assert "still pending" in first and "Priya" in first
        # The flag is in the DB now → any later off-topic turn (fresh judgment) stays quiet,
        # surviving reload (the check reads the row, not in-memory state).
        async with async_session() as s:
            row1b = (await s.execute(select(PendingApproval).where(PendingApproval.id == row1.id))).scalar_one()
        assert await runner._reminder_for(_j(row1b)) == ""   # Turn 2 → silent
        assert row1b.payload.get("reminded") is True          # durable flag set
        # A NEW card reminds again for ITSELF (per-card).
        row2 = await _insert_card()
        try:
            assert "still pending" in await runner._reminder_for(_j(row2))
        finally:
            await _cleanup(row2.id)
    finally:
        await _cleanup(row1.id)


async def test_reminder_empty_when_no_row():
    j = runner._PresentedJudgment(approval_id="x", row=None, intent="unrelated", change="")
    assert await runner._reminder_for(j) == ""  # failed-open judge → no reminder, no flag write


async def test_reminder_silent_once_acted_on():
    # "silent until acted on": if the card is resolved (status flips out of 'pending') in the
    # TOCTOU window before the FIRST reminder claims, the claim must NOT fire (no stale
    # "still pending" for an already-handled card). The status guard in _mark_reminded enforces it.
    row = await _insert_card()
    try:
        async with async_session() as s:
            await s.execute(
                PendingApproval.__table__.update()
                .where(PendingApproval.id == row.id)
                .values(status="approved")
            )
            await s.commit()
            acted = (await s.execute(select(PendingApproval).where(PendingApproval.id == row.id))).scalar_one()
        assert await runner._reminder_for(_j(acted)) == ""          # acted on → silent
        assert acted.payload.get("reminded") is None                # and the flag was NOT claimed
    finally:
        await _cleanup(row.id)


# --- Telegram heads-up confirmation label (pure) -----------------------------
def test_telegram_decision_label():
    from app.messaging.channels.telegram import _telegram_decision_label

    def outcome(kind, status):
        return SimpleNamespace(kind=kind, status=status)

    assert "Drafted" in _telegram_decision_label("approve", outcome("draft_request", "drafted"))
    assert "inbox" in _telegram_decision_label("reject", outcome("draft_request", "left")).lower()
    assert "couldn't draft" in _telegram_decision_label("approve", outcome("draft_request", "draft_failed")).lower()
    assert _telegram_decision_label("approve", outcome("email", "sent")) == "✅ Approved."
    assert _telegram_decision_label("reject", outcome("email", "rejected")) == "❌ Rejected."
    assert "already handled" in _telegram_decision_label("approve", outcome("none", "not_claimed")).lower()
