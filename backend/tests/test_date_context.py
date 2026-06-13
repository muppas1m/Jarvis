"""P5b — timezone-aware date context for the prompt's volatile section.

The Jun-11 bug: "this weekend" tasks landed on the test day because the model
did date math on a raw UTC datetime. `_date_context` now hands the model
concrete dates computed in the master's timezone.
"""
from app.agent.prompts import _date_context


def test_converts_utc_to_local_timezone():
    # 16:00 UTC on 2026-06-11 == 12:00 EDT (America/New_York is UTC-4 in June).
    out = _date_context("2026-06-11T16:00:00+00:00", "America/New_York")
    assert "12:00" in out, f"expected local (EDT) time, got: {out!r}"
    assert "America/New_York" in out


def test_weekend_dates_are_correct():
    # Thursday 2026-06-11 → this weekend is Sat 06-13 / Sun 06-14 (the dates the
    # Jun-11 tasks SHOULD have used instead of landing on the 11th).
    out = _date_context("2026-06-11T16:00:00+00:00", "America/New_York")
    assert "Today is Thursday 2026-06-11" in out
    assert "Saturday 2026-06-13" in out
    assert "Sunday 2026-06-14" in out


def test_next_seven_days_listed():
    out = _date_context("2026-06-11T16:00:00+00:00", "America/New_York")
    # the day after today must appear in the 7-day map
    assert "Fri 2026-06-12" in out
    assert "Thu 2026-06-18" in out  # 7 days out


def test_local_date_can_differ_from_utc_date():
    """22:00 EDT Friday == 02:00 UTC Saturday. The weekend must be computed from
    the LOCAL date (Friday), not the UTC date — that's the bug this fixes."""
    out = _date_context("2026-06-13T02:00:00+00:00", "America/New_York")
    assert "Today is Friday 2026-06-12" in out, f"should be local Friday, got: {out!r}"


def test_falls_back_gracefully_on_bad_input():
    out = _date_context("not-a-datetime", "America/New_York")
    assert "not-a-datetime" in out  # raw fallback, no raise
