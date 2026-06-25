"""calendar_period (4.2) — the internal, TZ-aware period read for readiness.

The headline is TIMEZONE CORRECTNESS: the [start, end] range boundaries are LOCAL
midnight in the master's TZ converted to UTC (DST-safe), NOT UTC midnight — so an
event late on the last local day lands in the right period. The Google client is
mocked (no live calendar); the tests capture the timeMin/timeMax actually sent and
assert the boundaries, plus normalization, all-day handling, the flagged TZ
fallback, and fail-soft.
"""
import app.agent.tools.calendar_tool as cal
from app.config import settings


def _fake_service(items, captured):
    """A stand-in Google service whose events().list(**kwargs) records kwargs and
    returns canned items (it does NOT filter — the boundaries we ASSERT are the
    proof we'd ask Google for the right window)."""
    class _Exec:
        def execute(self):
            return {"items": items}

    class _Events:
        def list(self, **kwargs):
            captured.update(kwargs)
            return _Exec()

    class _Svc:
        def events(self):
            return _Events()

    return _Svc()


# --- TZ correctness (the headline) -------------------------------------------
async def test_boundaries_are_local_midnight_not_utc(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(cal, "_service", lambda: _fake_service([], captured))
    res = await cal.calendar_period("2026-06-25", "2026-06-25", tz="America/New_York")
    # 2026-06-25 is EDT (UTC-4): local midnight = 04:00Z; timeMax exclusive = next
    # local midnight. A naive-UTC range would use 00:00Z and DROP a 23:30-EDT event
    # (= 03:30Z next day); these boundaries INCLUDE it.
    assert captured["timeMin"] == "2026-06-25T04:00:00+00:00"
    assert captured["timeMax"] == "2026-06-26T04:00:00+00:00"
    assert res.timezone == "America/New_York" and res.timezone_fallback is False


async def test_boundaries_are_dst_safe(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(cal, "_service", lambda: _fake_service([], captured))
    # winter: the SAME zone is EST (UTC-5) → local midnight = 05:00Z, not 04:00Z.
    await cal.calendar_period("2026-01-15", "2026-01-15", tz="America/New_York")
    assert captured["timeMin"] == "2026-01-15T05:00:00+00:00"
    assert captured["timeMax"] == "2026-01-16T05:00:00+00:00"


# --- structured, normalized output -------------------------------------------
async def test_explicit_range_returns_normalized_events(monkeypatch):
    items = [{
        "id": "e1", "summary": "Meeting",
        "start": {"dateTime": "2026-06-26T10:00:00-04:00"},
        "end": {"dateTime": "2026-06-26T11:00:00-04:00"},
        "location": "Room 1", "attendees": [{"email": "a@x.com"}],
    }]
    monkeypatch.setattr(cal, "_service", lambda: _fake_service(items, {}))
    res = await cal.calendar_period("2026-06-25", "2026-06-30", tz="America/New_York")
    assert res.ok and len(res.events) == 1
    e = res.events[0]
    assert (e.title, e.location, e.attendees, e.event_id) == ("Meeting", "Room 1", ["a@x.com"], "e1")
    assert e.all_day is False


async def test_normalizes_timed_to_master_tz_and_handles_all_day(monkeypatch):
    items = [
        # timed, given in UTC → must be normalized to EDT (09:00-04:00)
        {"id": "t1", "summary": "Standup",
         "start": {"dateTime": "2026-06-25T13:00:00+00:00"},
         "end": {"dateTime": "2026-06-25T13:30:00+00:00"}},
        # all-day → kept as a date, all_day True (no TZ conversion)
        {"id": "a1", "summary": "Holiday",
         "start": {"date": "2026-06-25"}, "end": {"date": "2026-06-26"}},
    ]
    monkeypatch.setattr(cal, "_service", lambda: _fake_service(items, {}))
    res = await cal.calendar_period("2026-06-25", "2026-06-25", tz="America/New_York")
    by = {e.title: e for e in res.events}
    assert by["Standup"].all_day is False
    assert by["Standup"].start == "2026-06-25T09:00:00-04:00"  # UTC → EDT
    assert by["Holiday"].all_day is True
    assert by["Holiday"].start == "2026-06-25"  # date kept raw


# --- TZ resolution: profile vs flagged default -------------------------------
async def test_unset_tz_falls_back_to_default_and_flags(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(cal, "_service", lambda: _fake_service([], captured))

    class _Mem:
        async def get_always_on(self):
            return {}  # no timezone on the profile

    monkeypatch.setattr("app.memory.manager.get_memory", lambda: _Mem())
    res = await cal.calendar_period("2026-06-25", "2026-06-25", tz="")
    assert res.timezone == settings.DEFAULT_TIMEZONE  # "UTC" by default
    assert res.timezone_fallback is True  # FLAGGED — never silent
    assert captured["timeMin"] == "2026-06-25T00:00:00+00:00"  # UTC boundary (default)


async def test_profile_tz_used_when_arg_empty(monkeypatch):
    captured: dict = {}
    monkeypatch.setattr(cal, "_service", lambda: _fake_service([], captured))

    class _Mem:
        async def get_always_on(self):
            return {"timezone": "America/New_York"}

    monkeypatch.setattr("app.memory.manager.get_memory", lambda: _Mem())
    res = await cal.calendar_period("2026-06-25", "2026-06-25", tz="")
    assert res.timezone == "America/New_York" and res.timezone_fallback is False
    assert captured["timeMin"] == "2026-06-25T04:00:00+00:00"  # EDT, from the profile TZ


async def test_invalid_tz_falls_back_flagged(monkeypatch):
    monkeypatch.setattr(cal, "_service", lambda: _fake_service([], {}))
    res = await cal.calendar_period("2026-06-25", "2026-06-25", tz="Mars/Olympus")
    assert res.timezone == settings.DEFAULT_TIMEZONE and res.timezone_fallback is True


# --- fail-soft ----------------------------------------------------------------
async def test_calendar_failure_is_fail_soft(monkeypatch):
    def _boom():
        raise RuntimeError("calendar down")

    monkeypatch.setattr(cal, "_service", _boom)
    res = await cal.calendar_period("2026-06-25", "2026-06-25", tz="UTC")
    assert res.ok is False and res.events == [] and "calendar down" in res.error


async def test_bad_date_range_is_fail_soft(monkeypatch):
    monkeypatch.setattr(cal, "_service", lambda: _fake_service([], {}))
    res = await cal.calendar_period("not-a-date", "2026-06-25", tz="UTC")
    assert res.ok is False and "bad date range" in res.error
