"""Read-state briefing foundation (5.1).

Pure: segment_by_day groups items by LOCAL day (not UTC). Integration: digest_window
returns only items in (start, end] and segments multi-day windows. The HWM advance
is ATOMIC + MONOTONIC — proven to never move backward under a concurrent
double-advance. (The HWM is single-row shared state, so the HWM tests save/restore
the real mark.)
"""
import asyncio
import uuid
from datetime import UTC, date, datetime
from types import SimpleNamespace

from sqlalchemy import delete, update

import app.briefing as B
from app.briefing import segment_by_day
from app.db.engine import async_session
from app.db.models import BriefingItem, UserProfile


def _it(occurred_at, title="x"):
    return SimpleNamespace(occurred_at=occurred_at, title=title)


# --- segment_by_day (PURE) ---------------------------------------------------
def test_segment_single_day_is_one_bucket():
    items = [_it(datetime(2026, 6, 25, 9, tzinfo=UTC)), _it(datetime(2026, 6, 25, 15, tzinfo=UTC))]
    days = segment_by_day(items, "UTC")
    assert len(days) == 1 and days[0].day == date(2026, 6, 25) and len(days[0].items) == 2


def test_segment_multi_day_is_chronological_buckets():
    items = [
        _it(datetime(2026, 6, 26, 9, tzinfo=UTC)),
        _it(datetime(2026, 6, 24, 9, tzinfo=UTC)),
        _it(datetime(2026, 6, 25, 9, tzinfo=UTC)),
    ]
    days = segment_by_day(items, "UTC")
    assert [d.day for d in days] == [date(2026, 6, 24), date(2026, 6, 25), date(2026, 6, 26)]


def test_segment_groups_by_local_day_not_utc():
    # 2026-06-25T02:00Z in America/New_York (EDT −4) = 2026-06-24T22:00 → local Jun 24.
    days = segment_by_day([_it(datetime(2026, 6, 25, 2, 0, tzinfo=UTC))], "America/New_York")
    assert days[0].day == date(2026, 6, 24)  # local day, not the UTC date (the 25th)


# --- digest_window (integration; far-future dates → no real-data collision) --
async def _seed(tag, occurred_ats):
    async with async_session() as s:
        for i, oa in enumerate(occurred_ats):
            s.add(BriefingItem(kind="email", occurred_at=oa, title=f"{tag}-{i}", source="x", preview="p"))
        await s.commit()


async def _cleanup(tag):
    async with async_session() as s:
        await s.execute(delete(BriefingItem).where(BriefingItem.title.like(f"{tag}%")))
        await s.commit()


async def test_digest_window_returns_only_in_window_and_segments():
    tag = uuid.uuid4().hex[:8]
    try:
        await _seed(tag, [
            datetime(2099, 6, 24, 12, tzinfo=UTC),  # before (start is exclusive)
            datetime(2099, 6, 25, 12, tzinfo=UTC),  # in
            datetime(2099, 6, 26, 12, tzinfo=UTC),  # in
            datetime(2099, 6, 28, 12, tzinfo=UTC),  # after
        ])
        win = await B.digest_window(
            datetime(2099, 6, 25, 0, tzinfo=UTC), datetime(2099, 6, 27, 0, tzinfo=UTC), tz="UTC"
        )
        assert win.total == 2  # 2099 → no other data in this window
        assert [d.day for d in win.days] == [date(2099, 6, 25), date(2099, 6, 26)]  # day-segmented
    finally:
        await _cleanup(tag)


async def test_digest_window_segments_by_local_day_under_non_utc_tz():
    tag = uuid.uuid4().hex[:8]
    try:
        # 02:00Z → 22:00 EDT prev day (Jun 24 local); 18:00Z → 14:00 EDT (Jun 25 local)
        await _seed(tag, [datetime(2099, 6, 25, 2, tzinfo=UTC), datetime(2099, 6, 25, 18, tzinfo=UTC)])
        win = await B.digest_window(
            datetime(2099, 6, 24, 0, tzinfo=UTC), datetime(2099, 6, 26, 0, tzinfo=UTC),
            tz="America/New_York",
        )
        assert [d.day for d in win.days] == [date(2099, 6, 24), date(2099, 6, 25)]
        assert win.timezone == "America/New_York"
    finally:
        await _cleanup(tag)


# --- HWM: atomic + monotonic -------------------------------------------------
async def _set_hwm_raw(value):
    """Unconditional set — for test setup/teardown ONLY (NOT the monotonic advance)."""
    async with async_session() as s:
        await s.execute(update(UserProfile).values(briefing_hwm=value))
        await s.commit()


async def test_hwm_advances_forward():
    original = await B.read_hwm()
    try:
        await _set_hwm_raw(datetime(2026, 1, 1, tzinfo=UTC))
        t = datetime(2026, 6, 25, 12, tzinfo=UTC)
        assert (await B.advance_hwm(t)) == t
        assert (await B.read_hwm()) == t
    finally:
        await _set_hwm_raw(original)


async def test_hwm_never_moves_backward():
    original = await B.read_hwm()
    try:
        later = datetime(2026, 6, 25, 12, tzinfo=UTC)
        earlier = datetime(2026, 6, 20, 12, tzinfo=UTC)
        await B.advance_hwm(later)
        res = await B.advance_hwm(earlier)  # earlier than current → no-op
        assert res == later and (await B.read_hwm()) == later
    finally:
        await _set_hwm_raw(original)


async def test_hwm_from_null_sets():
    original = await B.read_hwm()
    try:
        await _set_hwm_raw(None)
        t = datetime(2026, 6, 25, 12, tzinfo=UTC)
        assert (await B.advance_hwm(t)) == t
    finally:
        await _set_hwm_raw(original)


async def test_concurrent_double_advance_never_goes_backward():
    """THE race: two advances fired concurrently. Whatever the execution order, the
    monotonic WHERE-gate leaves the mark at the LATER value — never the earlier."""
    original = await B.read_hwm()
    try:
        await _set_hwm_raw(None)
        t_early = datetime(2026, 6, 25, 10, tzinfo=UTC)
        t_late = datetime(2026, 6, 25, 16, tzinfo=UTC)
        await asyncio.gather(B.advance_hwm(t_late), B.advance_hwm(t_early))
        assert (await B.read_hwm()) == t_late  # max wins; t_early can't move it back
    finally:
        await _set_hwm_raw(original)
