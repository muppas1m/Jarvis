"""Morning brief → HUD surface (persist-then-poll).

The 7am brief is persisted to morning_briefs (the SAME structured content the Telegram
push renders) so the HUD can poll /briefing/latest. Telegram delivery is unchanged.
What this locks: the serializer shape (empty / single-day+urgency / multi-day), that
untrusted email content rides through the payload VERBATIM (the frontend escapes at
render), the freshness-window endpoint (latest / null / stale / empty), and that the
task persists AND still sends Telegram.

morning_briefs is a NEW, undeployed table → tests own it (wipe in finally). HWM +
briefing_items are restored like test_briefing_cutover does.
"""
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy import delete, select, update

import app.briefing as B
from app.api.briefing import briefing_latest
from app.briefing import BriefingDay, DigestWindow, digest_to_payload, record_morning_brief
from app.db.engine import async_session
from app.db.models import BriefingItem, MorningBrief, UserProfile


def _item(title="S", source="bob@x.com", preview="body", urgency="none", kind="email", occurred_at=None):
    return SimpleNamespace(
        title=title, source=source, preview=preview, urgency=urgency,
        kind=kind, occurred_at=occurred_at or datetime.now(UTC),
    )


async def _wipe_briefs():
    async with async_session() as s:
        await s.execute(delete(MorningBrief))
        await s.commit()


async def _set_hwm_raw(value):
    async with async_session() as s:
        await s.execute(update(UserProfile).values(briefing_hwm=value))
        await s.commit()


async def _cleanup_title(tag):
    async with async_session() as s:
        await s.execute(delete(BriefingItem).where(BriefingItem.title.like(f"%{tag}%")))
        await s.commit()


# --- serializer (pure) -------------------------------------------------------
def test_digest_to_payload_empty():
    now = datetime.now(UTC)
    p = digest_to_payload(DigestWindow(now, now, "UTC", False, [], 0))
    assert p["empty"] is True and p["total"] == 0 and p["days"] == []


def test_digest_to_payload_single_day_with_urgency():
    now = datetime.now(UTC)
    day = BriefingDay(now.date(), [_item(title="Hi", urgency="today"), _item(title="Lo", urgency="none")])
    p = digest_to_payload(DigestWindow(now, now, "America/New_York", False, [day], 2))
    assert p["empty"] is False and p["total"] == 2 and p["timezone"] == "America/New_York"
    assert len(p["days"]) == 1 and len(p["days"][0]["items"]) == 2
    first = p["days"][0]["items"][0]
    assert first["title"] == "Hi" and first["urgency"] == "today" and first["kind"] == "email"
    assert first["source"] == "bob@x.com" and first["preview"] == "body"


def test_digest_to_payload_multi_day():
    now = datetime.now(UTC)
    d1 = BriefingDay((now - timedelta(days=1)).date(), [_item(title="Yesterday")])
    d2 = BriefingDay(now.date(), [_item(title="Today")])
    p = digest_to_payload(DigestWindow(now - timedelta(days=1), now, "UTC", False, [d1, d2], 2))
    assert len(p["days"]) == 2
    assert [it["title"] for d in p["days"] for it in d["items"]] == ["Yesterday", "Today"]


def test_digest_to_payload_preserves_untrusted_content_verbatim():
    # Untrusted subject/snippet carried through UNTOUCHED — the frontend escapes at
    # render (never markdown). Verify the payload doesn't mangle/strip/sanitize it
    # (sanitization at the wrong layer would be a false sense of safety).
    now = datetime.now(UTC)
    evil = "<img src=x onerror=alert(1)> **bold** [x](javascript:alert(1))"
    day = BriefingDay(now.date(), [_item(title=evil, source=evil, preview=evil)])
    it = digest_to_payload(DigestWindow(now, now, "UTC", False, [day], 1))["days"][0]["items"][0]
    assert it["title"] == evil and it["source"] == evil and it["preview"] == evil


# --- persist + freshness endpoint --------------------------------------------
async def test_endpoint_returns_latest_within_window():
    await _wipe_briefs()
    try:
        await record_morning_brief({
            "empty": False, "total": 1, "timezone": "UTC",
            "days": [{"day": "2026-06-25", "items": [{
                "title": "Hi", "source": "bob", "preview": "p",
                "urgency": "today", "kind": "email", "occurred_at": "2026-06-25T06:00:00+00:00"}]}],
        })
        resp = await briefing_latest()
        assert resp.brief is not None
        assert resp.brief.total == 1 and resp.brief.empty is False
        assert resp.brief.days[0].items[0].title == "Hi"
        assert resp.brief.days[0].items[0].urgency == "today"
    finally:
        await _wipe_briefs()


async def test_endpoint_null_when_no_brief():
    await _wipe_briefs()
    assert (await briefing_latest()).brief is None


async def test_endpoint_null_when_stale():
    await _wipe_briefs()
    try:
        await record_morning_brief({"empty": True, "total": 0, "days": []})
        async with async_session() as s:  # backdate beyond the freshness window
            await s.execute(update(MorningBrief).values(created_at=datetime.now(UTC) - timedelta(hours=48)))
            await s.commit()
        assert (await briefing_latest()).brief is None
    finally:
        await _wipe_briefs()


async def test_record_morning_brief_prunes_stale_rows():
    # The table self-limits: a stale brief (older than the freshness window) is REMOVED
    # by the next insert's prune, not just hidden by the endpoint filter.
    await _wipe_briefs()
    try:
        await record_morning_brief({"empty": True, "total": 0, "days": []})
        async with async_session() as s:  # backdate the existing brief past the window
            await s.execute(update(MorningBrief).values(created_at=datetime.now(UTC) - timedelta(hours=48)))
            await s.commit()
        # a fresh insert prunes the stale row → table holds only the new brief
        await record_morning_brief({
            "empty": False, "total": 1, "days": [{"day": "2026-06-25", "items": [{
                "title": "fresh", "source": "x", "preview": "p", "urgency": "today",
                "kind": "email", "occurred_at": "2026-06-25T06:00:00+00:00"}]}],
        })
        async with async_session() as s:
            rows = (await s.execute(select(MorningBrief))).scalars().all()
        assert len(rows) == 1, f"table did not self-limit; got {len(rows)} rows"
        assert rows[0].payload.get("total") == 1  # the stale row is gone, the fresh one remains
    finally:
        await _wipe_briefs()


async def test_endpoint_empty_brief_still_surfaces():
    await _wipe_briefs()
    try:
        await record_morning_brief({"empty": True, "total": 0, "days": [], "error": False})
        resp = await briefing_latest()
        assert resp.brief is not None and resp.brief.empty is True and resp.brief.total == 0
    finally:
        await _wipe_briefs()


# --- the task persists for the HUD AND still sends Telegram -------------------
async def test_morning_brief_persists_for_hud_and_still_sends_telegram(monkeypatch):
    import app.scheduler.tasks.morning_brief as MB

    await _wipe_briefs()
    original = await B.read_hwm()
    tag = uuid.uuid4().hex[:8]
    try:
        await _set_hwm_raw(None)
        now = datetime.now(UTC)
        await B.record_briefing_item(kind="email", title=f"{tag} subj", source="bob@x.com",
                                     preview="snippet", urgency="today", occurred_at=now - timedelta(hours=1))
        fake_ch = SimpleNamespace(send_alert=AsyncMock())
        monkeypatch.setattr(MB, "channel_registry", SimpleNamespace(get=lambda _: fake_ch))
        monkeypatch.setattr(MB, "reset_async_state_for_task", AsyncMock())

        await MB._send()

        # (e) Telegram delivery unchanged.
        assert fake_ch.send_alert.await_count == 1
        text = fake_ch.send_alert.await_args[0][0]
        assert "Good Morning" in text and f"{tag} subj" in text
        # HUD brief persisted with the SAME item (a).
        resp = await briefing_latest()
        assert resp.brief is not None and resp.brief.total >= 1
        titles = [it.title for d in resp.brief.days for it in d.items]
        assert f"{tag} subj" in titles
    finally:
        await _cleanup_title(tag)
        await _set_hwm_raw(original)
        await _wipe_briefs()
