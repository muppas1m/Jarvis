"""Readiness intelligence (4.3). The scrutinized logic is PURE with an INJECTED
`now` (no wall-clock): resolve_period (period boundaries incl. weekend / next-week /
month edges + a DST week) and select_lookahead (priority × distance). Plus
categorize / verdict, and fail-soft integration of the three sources.
"""
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import app.agent.tools.readiness_tool as R
from app.agent.tools.calendar_tool import CalendarPeriodResult
from app.agent.tools.readiness_tool import (
    PeriodRange,
    categorize_tasks,
    compute_verdict,
    format_report,
    resolve_period,
    select_lookahead,
)

NY = "America/New_York"
# Verified weekdays: 2026-01-01 is Thursday → 2026-01-05 Mon … 2026-01-11 Sun.


def _now(y, m, d, h=12, tz=NY) -> datetime:
    return datetime(y, m, d, h, 0, tzinfo=ZoneInfo(tz))


def _task(content, priority, due):
    return SimpleNamespace(content=content, priority=priority, due_date=due)


# --- resolve_period: boundaries + edges (PURE) -------------------------------
def test_today_and_tomorrow():
    now = _now(2026, 1, 7)  # Wed
    assert resolve_period("today", NY, now) == PeriodRange("today", "today", date(2026, 1, 7), date(2026, 1, 7))
    assert resolve_period("tomorrow", NY, now).start == date(2026, 1, 8)


def test_this_week_midweek_to_coming_sunday():
    p = resolve_period("this_week", NY, _now(2026, 1, 7))  # Wed
    assert (p.start, p.end) == (date(2026, 1, 7), date(2026, 1, 11))
    assert p.end.weekday() == 6  # Sunday


def test_this_week_on_sunday_is_just_today():
    p = resolve_period("this_week", NY, _now(2026, 1, 11))  # Sun
    assert (p.start, p.end) == (date(2026, 1, 11), date(2026, 1, 11))


def test_this_weekend_midweek_is_coming_sat_sun():
    p = resolve_period("this_weekend", NY, _now(2026, 1, 7))  # Wed
    assert (p.start, p.end) == (date(2026, 1, 10), date(2026, 1, 11))


def test_this_weekend_on_saturday():
    p = resolve_period("this_weekend", NY, _now(2026, 1, 10))  # Sat
    assert (p.start, p.end) == (date(2026, 1, 10), date(2026, 1, 11))


def test_this_weekend_on_sunday_is_today_only():
    p = resolve_period("this_weekend", NY, _now(2026, 1, 11))  # Sun
    assert (p.start, p.end) == (date(2026, 1, 11), date(2026, 1, 11))


def test_next_week_is_following_mon_to_sun():
    p = resolve_period("next_week", NY, _now(2026, 1, 7))  # Wed
    assert (p.start, p.end) == (date(2026, 1, 12), date(2026, 1, 18))
    assert p.start.weekday() == 0 and p.end.weekday() == 6


def test_next_week_asked_on_monday_is_the_following_monday():
    p = resolve_period("next_week", NY, _now(2026, 1, 5))  # Mon
    assert (p.start, p.end) == (date(2026, 1, 12), date(2026, 1, 18))


def test_this_month_and_last_day_and_december_rollover():
    assert resolve_period("this_month", NY, _now(2026, 1, 7)).end == date(2026, 1, 31)
    # asked on the last day → [last, last]
    p = resolve_period("this_month", NY, _now(2026, 1, 31))
    assert (p.start, p.end) == (date(2026, 1, 31), date(2026, 1, 31))
    # December → year rollover for the month-end computation
    assert resolve_period("this_month", NY, _now(2026, 12, 15)).end == date(2026, 12, 31)


def test_unknown_keyword_is_none():
    assert resolve_period("next_year", NY, _now(2026, 1, 7)) is None


# --- DST correctness ---------------------------------------------------------
def test_local_date_resolved_across_dst_boundary():
    # Spring-forward 2026 = Sun Mar 8, 02:00 local. 04:30Z on Mar 8 is 23:30 EST on
    # Mar 7 (before the 07:00Z transition) → the LOCAL date is Mar 7, not the UTC date.
    p = resolve_period("today", NY, datetime(2026, 3, 8, 4, 30, tzinfo=UTC))
    assert p.start == date(2026, 3, 7)


def test_this_week_spanning_dst_has_correct_dates():
    # Thu Mar 5 → Sun Mar 8 (the DST transition Sunday). Date math is DST-agnostic;
    # the dates must still be right.
    p = resolve_period("this_week", NY, _now(2026, 3, 5))
    assert (p.start, p.end) == (date(2026, 3, 5), date(2026, 3, 8))


# --- select_lookahead: priority × distance (PURE) ----------------------------
_H = {"high": 30, "medium": 7, "low": 0}
_END = date(2026, 6, 28)


def test_lookahead_high_within_horizon_included():
    t = _task("renew licence", "high", _END + timedelta(days=20))
    assert select_lookahead([t], _END, _H) == [t]


def test_lookahead_high_beyond_horizon_excluded():
    t = _task("far", "high", _END + timedelta(days=40))
    assert select_lookahead([t], _END, _H) == []


def test_lookahead_medium_in_then_out():
    near = _task("m-near", "medium", _END + timedelta(days=5))
    far = _task("m-far", "medium", _END + timedelta(days=10))
    assert select_lookahead([near, far], _END, _H) == [near]


def test_lookahead_low_never_surfaces_ahead():
    t = _task("errand", "low", _END + timedelta(days=1))
    assert select_lookahead([t], _END, _H) == []


def test_lookahead_excludes_in_period_and_no_due():
    inp = _task("at-end", "high", _END)  # not AFTER end
    nodue = _task("nodue", "high", None)
    assert select_lookahead([inp, nodue], _END, _H) == []


# --- categorize_tasks (PURE) -------------------------------------------------
def test_categorize_splits_overdue_inperiod_nodue_high_ahead():
    period = PeriodRange("this_week", "this week", date(2026, 6, 24), date(2026, 6, 28))
    today = date(2026, 6, 24)
    tasks = [
        _task("overdue", "high", date(2026, 6, 20)),     # < today
        _task("inperiod", "medium", date(2026, 6, 26)),  # in [24,28]
        _task("nodue-high", "high", None),               # surfaced (capped)
        _task("nodue-low", "low", None),                 # NOT surfaced
        _task("ahead-high", "high", date(2026, 7, 10)),  # within 30d horizon
    ]
    overdue, inp, nodue, ahead = categorize_tasks(tasks, period, today, _H)
    assert [t.content for t in overdue] == ["overdue"]
    assert [t.content for t in inp] == ["inperiod"]
    assert [t.content for t in nodue] == ["nodue-high"]
    assert [t.content for t in ahead] == ["ahead-high"]


# --- compute_verdict (PURE) --------------------------------------------------
def test_verdict_rules():
    assert compute_verdict(overdue=[1], expiring=[], tasks_ok=True, approvals_ok=True) == "not all set"
    assert compute_verdict(overdue=[], expiring=[1], tasks_ok=True, approvals_ok=True) == "not all set"
    assert compute_verdict(overdue=[], expiring=[], tasks_ok=False, approvals_ok=True) == "uncertain"
    assert compute_verdict(overdue=[], expiring=[], tasks_ok=True, approvals_ok=True) == "all set"
    # a real problem dominates an unread source
    assert compute_verdict(overdue=[1], expiring=[], tasks_ok=False, approvals_ok=True) == "not all set"


# --- gather_readiness: three sources, fail-soft (integration) ----------------
def _mock(monkeypatch, *, tasks=None, approvals=None, cal_ok=True, cal_events=None,
          tz=("UTC", False), tasks_raise=False, approvals_raise=False):
    async def fake_resolve(_):
        return tz

    async def fake_tasks():
        if tasks_raise:
            raise RuntimeError("db down")
        return tasks or []

    async def fake_appr(now):
        if approvals_raise:
            raise RuntimeError("db down")
        return approvals or []

    async def fake_cal(start, end, tz=""):
        return CalendarPeriodResult(cal_events or [], tz or "UTC", False, ok=cal_ok,
                                    error="" if cal_ok else "calendar down")

    monkeypatch.setattr(R, "_resolve_timezone", fake_resolve)
    monkeypatch.setattr(R, "_open_tasks", fake_tasks)
    monkeypatch.setattr(R, "_pending_approvals", fake_appr)
    monkeypatch.setattr(R, "calendar_period", fake_cal)


_NOW = datetime(2026, 6, 24, 12, tzinfo=UTC)


async def test_gather_all_set_when_clean(monkeypatch):
    _mock(monkeypatch)
    rep = await R.gather_readiness("today", _NOW)
    assert rep.verdict == "all set" and rep.notes == []


async def test_gather_not_set_on_overdue(monkeypatch):
    overdue = _task("late", "high", date(2026, 6, 20))
    _mock(monkeypatch, tasks=[overdue])
    rep = await R.gather_readiness("today", _NOW)
    assert rep.verdict == "not all set" and rep.overdue == [overdue]


async def test_gather_calendar_failsoft_does_not_flip_verdict(monkeypatch):
    _mock(monkeypatch, cal_ok=False)
    rep = await R.gather_readiness("today", _NOW)
    assert "couldn't reach your calendar" in rep.notes
    assert rep.verdict == "all set"  # a calendar outage alone isn't "not set"


async def test_gather_tasks_failsoft_is_uncertain(monkeypatch):
    _mock(monkeypatch, tasks_raise=True)
    rep = await R.gather_readiness("today", _NOW)
    assert "couldn't reach your task list" in rep.notes
    assert rep.verdict == "uncertain"  # can't confirm → not a false 'all set'


async def test_gather_approval_expiring_in_period_flips_verdict(monkeypatch):
    appr = SimpleNamespace(expires_at=datetime(2026, 6, 24, 18, tzinfo=UTC))  # expires today
    _mock(monkeypatch, approvals=[appr])
    rep = await R.gather_readiness("today", _NOW)
    assert rep.approvals_total == 1 and len(rep.approvals_expiring) == 1
    assert rep.verdict == "not all set"


async def test_gather_tz_fallback_surfaced_in_narration(monkeypatch):
    _mock(monkeypatch, tz=("UTC", True))
    rep = await R.gather_readiness("today", _NOW)
    assert rep.timezone_fallback is True
    assert "set your timezone" in format_report(rep).lower()


async def test_unknown_period_keyword_handler_asks(monkeypatch):
    out = await R.readiness_check(period="next_decade")
    assert all(w in out for w in ("today", "this_week", "this_month"))  # the menu
