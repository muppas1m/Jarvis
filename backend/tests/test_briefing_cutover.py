"""Briefing cutover (5.3) — FYI ingestion → briefing_item + the proactive 7am push.

The FYI inbound branch records a durable briefing_item (replacing the clear-on-build
Redis digest). The push windows (HWM, now] (capped, NULL-HWM floored) and NEVER
advances the HWM — a missed push must still surface under "what's the latest".
"""
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy import delete, select, update

import app.briefing as B
from app.briefing import BriefingDay, DigestWindow, render_push
from app.db.engine import async_session
from app.db.models import BriefingItem, EmailLog, UserProfile


async def _set_hwm_raw(value):
    async with async_session() as s:
        await s.execute(update(UserProfile).values(briefing_hwm=value))
        await s.commit()


async def _cleanup_title(tag):
    async with async_session() as s:
        await s.execute(delete(BriefingItem).where(BriefingItem.title.like(f"%{tag}%")))
        await s.commit()


def _bi(title, urgency="none", source=""):
    return SimpleNamespace(title=title, urgency=urgency, source=source)


# --- FYI ingestion → a durable briefing_item ---------------------------------
async def test_fyi_email_records_a_briefing_item(monkeypatch):
    from app.email.classifier import EmailTriageResult
    from app.email.inbound import _process_message

    msg_id = f"fyi-{uuid.uuid4().hex[:10]}"
    triage = EmailTriageResult(
        classification="fyi", urgency="today", intent="notification", confidence=0.9, suggested_action="none",
    )
    monkeypatch.setattr("app.email.inbound.classify_email", AsyncMock(return_value=triage))
    msg = SimpleNamespace(
        message_id=msg_id, subject="Newsletter", sender="Bob <bob@x.com>", body="newsletter body here",
    )
    provider = SimpleNamespace(name="gmail")
    try:
        await _process_message(provider, msg)
        async with async_session() as s:
            bi = (await s.execute(
                select(BriefingItem).where(BriefingItem.meta["message_id"].astext == msg_id)
            )).scalar_one_or_none()
        assert bi is not None
        assert (bi.kind, bi.title, bi.source, bi.urgency) == ("email", "Newsletter", "Bob <bob@x.com>", "today")
        assert bi.preview == "newsletter body here" and bi.meta["provider"] == "gmail"
    finally:
        async with async_session() as s:
            await s.execute(delete(BriefingItem).where(BriefingItem.meta["message_id"].astext == msg_id))
            await s.execute(delete(EmailLog).where(EmailLog.gmail_message_id == msg_id))
            await s.commit()


# --- the push: window (floor + cap) + NEVER advances -------------------------
async def test_push_null_hwm_floors_at_24h_and_does_not_advance():
    original = await B.read_hwm()
    tag = uuid.uuid4().hex[:8]
    try:
        await _set_hwm_raw(None)
        now = datetime.now(UTC)
        await B.record_briefing_item(kind="email", title=f"{tag} recent", source="x", preview="p",
                                     urgency="none", occurred_at=now - timedelta(hours=2))
        await B.record_briefing_item(kind="email", title=f"{tag} old", source="x", preview="p",
                                     urgency="none", occurred_at=now - timedelta(hours=30))
        win = await B.build_push_digest(now, cap_days=7)
        titles = [it.title for d in win.days for it in d.items]
        assert f"{tag} recent" in titles  # within the 24h NULL-HWM floor
        assert f"{tag} old" not in titles   # 30h ago → before the floor
        assert await B.read_hwm() is None   # the push did NOT advance the HWM
    finally:
        await _cleanup_title(tag)
        await _set_hwm_raw(original)


async def test_push_window_capped_when_hwm_is_old():
    original = await B.read_hwm()
    tag = uuid.uuid4().hex[:8]
    try:
        now = datetime.now(UTC)
        await _set_hwm_raw(now - timedelta(days=30))  # an unread HWM, 30 days old
        await B.record_briefing_item(kind="email", title=f"{tag} d10", source="x", preview="p",
                                     urgency="none", occurred_at=now - timedelta(days=10))
        await B.record_briefing_item(kind="email", title=f"{tag} d3", source="x", preview="p",
                                     urgency="none", occurred_at=now - timedelta(days=3))
        win = await B.build_push_digest(now, cap_days=7)
        titles = [it.title for d in win.days for it in d.items]
        assert f"{tag} d3" in titles      # within the 7-day cap
        assert f"{tag} d10" not in titles  # before the cap → not in the unbounded-growth window
    finally:
        await _cleanup_title(tag)
        await _set_hwm_raw(original)


def test_render_push_empty_and_present():
    now = datetime.now(UTC)
    assert "nothing new" in render_push(DigestWindow(now, now, "UTC", False, [], 0)).lower()
    day = BriefingDay(datetime(2026, 6, 25).date(), [_bi("Hi", "today", "bob")])
    out = render_push(DigestWindow(now, now, "UTC", False, [day], 1))
    assert "1 new" in out and "[today] Hi" in out and "bob" in out


# --- the proactive brief delivers via Telegram + leaves the HWM unchanged ----
async def test_morning_brief_delivers_and_does_not_advance(monkeypatch):
    import app.scheduler.tasks.morning_brief as MB

    original = await B.read_hwm()
    tag = uuid.uuid4().hex[:8]
    try:
        await _set_hwm_raw(None)
        now = datetime.now(UTC)
        await B.record_briefing_item(kind="email", title=f"{tag} item", source="x", preview="p",
                                     urgency="none", occurred_at=now - timedelta(hours=1))
        fake_ch = SimpleNamespace(send_alert=AsyncMock())
        monkeypatch.setattr(MB, "channel_registry", SimpleNamespace(get=lambda _: fake_ch))
        monkeypatch.setattr(MB, "reset_async_state_for_task", AsyncMock())

        await MB._send()

        assert fake_ch.send_alert.await_count == 1
        text = fake_ch.send_alert.await_args[0][0]
        assert f"{tag} item" in text and "Good Morning" in text
        assert await B.read_hwm() is None  # the proactive push NEVER advances the HWM
    finally:
        await _cleanup_title(tag)
        await _set_hwm_raw(original)
