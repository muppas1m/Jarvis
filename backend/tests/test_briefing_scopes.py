"""Briefing scope behaviors + tool (5.2).

PURE (now injected): resolve_scope maps each scope to a window + advance rule —
assert the bounds AND advances-vs-not per scope, the inclusive-midnight epsilon, the
NULL-HWM 24h floor, and the earlier-catch-up window. format_digest narration. Then
the handler orchestration (resolve_scope mocked → wall-clock-independent): latest
advances, today/yesterday don't, the offer fires iff pre-today unheard exists,
tomorrow watches, off-enum → menu, alias → latest, TZ-fallback surfaced.
"""
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

import app.agent.tools.briefing_tool as BT
from app.agent.tools.briefing_tool import ScopeWindow, format_digest, resolve_scope
from app.briefing import BriefingDay, DigestWindow

NY = "America/New_York"
NOW = datetime(2026, 6, 25, 18, 0, tzinfo=UTC)        # 14:00 EDT → today (NY) = Jun 25
TODAY_START = datetime(2026, 6, 25, 4, 0, tzinfo=UTC)  # NY local midnight (EDT −4)
Y_START = datetime(2026, 6, 24, 4, 0, tzinfo=UTC)
EPS = timedelta(microseconds=1)


# --- resolve_scope: window + advance per scope (PURE) ------------------------
def test_latest_window_is_hwm_to_now_and_advances():
    hwm = datetime(2026, 6, 25, 9, 0, tzinfo=UTC)
    sw = resolve_scope("latest", hwm, NOW, NY)
    assert (sw.start, sw.end, sw.advances) == (hwm, NOW, True)
    assert sw.earlier_start is None


def test_latest_null_hwm_floors_at_24h():
    sw = resolve_scope("latest", None, NOW, NY)
    assert sw.start == NOW - timedelta(hours=24) and sw.advances is True


def test_today_is_inclusive_midnight_no_advance_with_earlier_window():
    hwm = datetime(2026, 6, 24, 12, 0, tzinfo=UTC)  # before today → earlier exists
    sw = resolve_scope("today", hwm, NOW, NY)
    assert sw.start == TODAY_START - EPS  # midnight-exact item NOT dropped
    assert (sw.end, sw.advances) == (NOW, False)
    assert (sw.earlier_start, sw.earlier_end) == (hwm, TODAY_START)


def test_today_no_earlier_window_when_hwm_already_into_today():
    hwm = datetime(2026, 6, 25, 10, 0, tzinfo=UTC)  # ≥ today_start
    sw = resolve_scope("today", hwm, NOW, NY)
    assert sw.earlier_start is None and sw.earlier_end is None


def test_today_null_hwm_earlier_window_floors():
    sw = resolve_scope("today", None, NOW, NY)
    assert sw.earlier_start == NOW - timedelta(hours=24) and sw.earlier_end == TODAY_START


def test_yesterday_window_no_advance():
    sw = resolve_scope("yesterday", datetime(2026, 6, 20, tzinfo=UTC), NOW, NY)
    assert sw.start == Y_START - EPS  # inclusive of yesterday's midnight
    assert (sw.end, sw.advances) == (TODAY_START - EPS, False)  # today-midnight EXCLUDED


def test_today_midnight_item_is_today_only_not_yesterday():
    """A today-local-midnight item must land in today, not double-attributed to
    yesterday (the (start, end] primitive is inclusive at end)."""
    sw_y = resolve_scope("yesterday", None, NOW, NY)
    sw_t = resolve_scope("today", datetime(2026, 6, 20, tzinfo=UTC), NOW, NY)
    at_midnight = TODAY_START  # exactly today's local midnight
    in_window = lambda sw: sw.start < at_midnight <= sw.end  # noqa: E731 — the (start, end] test
    assert not in_window(sw_y)  # NOT yesterday
    assert in_window(sw_t)      # IS today


def test_tomorrow_and_unknown_resolve_to_none():
    assert resolve_scope("tomorrow", None, NOW, NY) is None
    assert resolve_scope("blah", None, NOW, NY) is None


# --- format_digest (PURE) ----------------------------------------------------
def _dw(total, days, tz="UTC", fallback=False):
    return DigestWindow(NOW, NOW, tz, fallback, days, total)


def _bi(title, urgency="none", source=""):
    return SimpleNamespace(title=title, urgency=urgency, source=source)


def test_format_empty_latest():
    out = format_digest(ScopeWindow("latest", NOW, NOW, True), _dw(0, []), fallback=False, earlier_count=0)
    assert "all caught up" in out.lower()


def test_format_single_day_has_no_day_header():
    day = BriefingDay(date(2026, 6, 25), [_bi("Receipt"), _bi("Alert", "today")])
    out = format_digest(ScopeWindow("latest", NOW, NOW, True), _dw(2, [day]), fallback=False, earlier_count=0)
    assert "2 new" in out and "Receipt" in out and "[today] Alert" in out
    assert "2026-06-25" not in out  # single day → no header


def test_format_multi_day_has_day_headers():
    days = [BriefingDay(date(2026, 6, 24), [_bi("a")]), BriefingDay(date(2026, 6, 25), [_bi("b")])]
    out = format_digest(ScopeWindow("latest", NOW, NOW, True), _dw(2, days), fallback=False, earlier_count=0)
    assert "2026-06-24" in out and "2026-06-25" in out  # missed-days segmentation


def test_format_earlier_offer_and_tz_flag():
    day = BriefingDay(date(2026, 6, 25), [_bi("x")])
    out = format_digest(ScopeWindow("today", NOW, NOW, False), _dw(1, [day], fallback=True),
                        fallback=True, earlier_count=3)
    assert "3 from before today" in out and "shall i catch you up" in out.lower()
    assert "set your timezone" in out.lower()


# --- handler orchestration (resolve_scope mocked → wall-clock-independent) ----
def _mock(monkeypatch, *, sw=None, total=0, days=None, earlier=0, tz=("UTC", False)):
    advanced: dict = {}

    async def fake_resolve(_):
        return tz

    async def fake_read():
        return None

    async def fake_advance(now):
        advanced["now"] = now
        return now

    async def fake_dw(start, end, tz=""):
        return DigestWindow(start, end, tz or "UTC", False, days or [], total)

    async def fake_earlier(s, e, t):
        return earlier

    monkeypatch.setattr(BT, "_resolve_timezone", fake_resolve)
    monkeypatch.setattr(BT, "read_hwm", fake_read)
    monkeypatch.setattr(BT, "advance_hwm", fake_advance)
    monkeypatch.setattr(BT, "digest_window", fake_dw)
    monkeypatch.setattr(BT, "_earlier_unheard", fake_earlier)
    if sw is not None:
        monkeypatch.setattr(BT, "resolve_scope", lambda *a, **k: sw)
    return advanced


async def test_latest_advances_hwm(monkeypatch):
    adv = _mock(monkeypatch, sw=ScopeWindow("latest", NOW, NOW, advances=True))
    out = await BT.briefing("latest")
    assert "now" in adv and "caught up" in out.lower()


async def test_today_does_not_advance_and_offers_when_earlier_exists(monkeypatch):
    sw = ScopeWindow("today", NOW, NOW, advances=False, earlier_start=NOW, earlier_end=NOW)
    adv = _mock(monkeypatch, sw=sw, total=1,
                days=[BriefingDay(date(2026, 6, 25), [_bi("x")])], earlier=2)
    out = await BT.briefing("today")
    assert "now" not in adv  # NEVER advances on a scoped recall
    assert "2 from before today" in out  # offer fires (earlier > 0)


async def test_today_no_offer_when_no_earlier_unheard(monkeypatch):
    sw = ScopeWindow("today", NOW, NOW, advances=False, earlier_start=None, earlier_end=None)
    adv = _mock(monkeypatch, sw=sw, total=0, earlier=0)
    out = await BT.briefing("today")
    assert "now" not in adv and "before today" not in out  # no earlier window → no offer


async def test_tomorrow_watches_and_does_not_advance(monkeypatch):
    adv = _mock(monkeypatch)
    out = await BT.briefing("tomorrow")
    assert "watch" in out.lower() and "now" not in adv


async def test_off_enum_scope_returns_menu(monkeypatch):
    _mock(monkeypatch)
    out = await BT.briefing("next_year")
    assert all(w in out for w in ("latest", "today", "yesterday", "tomorrow"))


async def test_catch_up_alias_maps_to_latest_and_advances(monkeypatch):
    adv = _mock(monkeypatch, sw=ScopeWindow("latest", NOW, NOW, advances=True))
    await BT.briefing("catch_up")
    assert "now" in adv


async def test_tz_fallback_surfaced(monkeypatch):
    sw = ScopeWindow("latest", NOW, NOW, advances=True)
    _mock(monkeypatch, sw=sw, total=1, days=[BriefingDay(date(2026, 6, 25), [_bi("x")])], tz=("UTC", True))
    out = await BT.briefing("latest")
    assert "set your timezone" in out.lower()
