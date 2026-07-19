"""B1-TZ — one resolved timezone at every render, fail-visible until set (R2/CH-11/D-B1-9).
The issue-2 class: a 1 PM request stored 17:00Z must render '1:00 pm', never a silent '5:00 pm'."""
import uuid
from unittest.mock import AsyncMock

import pytest

from app.agent.master_tz import _master_tz, current_tz, resolve_and_bind
from app.approvals_service import UnifiedApprovalCard, _human_time, describe_card

_MARK = f"test-tz-{uuid.uuid4().hex[:8]}"


def _card(start="2026-07-05T17:00:00Z"):
    return UnifiedApprovalCard(
        approval_id="x", kind="tool", thread_id="web:t", tool_name="calendar_update",
        tool_args={"event_id": "e", "title": "Lunch with friends", "start_iso": start},
        description="d", status="pending", created_at="2026-07-04T00:00:00+00:00")


@pytest.fixture
def _tz_set():
    tok = _master_tz.set(("America/New_York", False))
    yield
    _master_tz.reset(tok)


@pytest.fixture
def _tz_unset():
    tok = _master_tz.set(None)
    yield
    _master_tz.reset(tok)


# ---------------- the issue-2 class ---------------- #
def test_one_pm_renders_one_pm_when_tz_set(_tz_set):
    out = _human_time("2026-07-05T17:00:00Z")
    assert "1:00 pm" in out, f"the 5:00-pm class lives: {out!r}"
    assert "UTC" not in out                                     # no marker once set


def test_describe_card_choices_path_shows_wall_clock(_tz_set):
    d = describe_card(_card())
    assert "1:00 pm" in d and "5:00 pm" not in d, f"{d!r}"


def test_unset_tz_is_visible_never_silent(_tz_unset):
    out = _human_time("2026-07-05T17:00:00Z")
    assert "5:00 pm" in out and "UTC" in out, f"a silently-wrong time: {out!r}"


# ---------------- DST correctness ---------------- #
def test_dst_winter_and_summer(_tz_set):
    assert "12:00 pm" in _human_time("2026-01-10T17:00:00Z")    # EST −5
    assert "1:00 pm" in _human_time("2026-07-10T17:00:00Z")     # EDT −4


def test_naive_datetime_renders_as_is(_tz_set):
    out = _human_time("2026-07-05T13:00:00")                    # already wall-clock
    assert "1:00 pm" in out


# ---------------- the binder + the profile chain ---------------- #
@pytest.mark.asyncio
async def test_resolve_and_bind_sets_the_var(monkeypatch):
    import app.agent.master_tz as mtz
    monkeypatch.setattr(mtz, "_resolve_timezone", AsyncMock(return_value=("America/Chicago", False)))
    tok = _master_tz.set(None)
    try:
        name, fb = await resolve_and_bind()
        assert (name, fb) == ("America/Chicago", False)
        assert current_tz() == ("America/Chicago", False)
    finally:
        _master_tz.reset(tok)


@pytest.mark.asyncio
async def test_profile_column_wins_over_always_on(monkeypatch):
    """The first-class column is the primary source; always_on stays the legacy fallback."""
    from app.agent.tools.calendar_tool import _resolve_timezone
    import app.agent.tools.calendar_tool as ct
    monkeypatch.setattr(ct, "_profile_timezone_column",
                        AsyncMock(return_value="America/Denver"), raising=False)
    name, fb = await _resolve_timezone("")
    assert name == "America/Denver" and fb is False


# ---------------- the capture tool ---------------- #
@pytest.mark.asyncio
async def test_set_timezone_tool_validates_and_persists(monkeypatch):
    from app.agent.tools import profile_tool
    saved = {}

    async def fake_save(tz):
        saved["tz"] = tz
    monkeypatch.setattr(profile_tool, "_persist_timezone", fake_save)
    out = await profile_tool.set_timezone("America/New_York")
    assert saved.get("tz") == "America/New_York"
    assert "New_York" in out
    bad = await profile_tool.set_timezone("Not/AZone")
    assert saved.get("tz") == "America/New_York"                # unchanged
    assert "didn't recognize" in bad.lower() or "not" in bad.lower()


# --------------------------------------------------------------------------- #
# B1-TZ bridge fix (master ruling (a)) — the legacy always_on read is NESTED:   #
# get_always_on() returns {'name':…, 'always_on': {'timezone':…}} and the old   #
# read looked at the OUTER dict → the master's real config rendered flagged-UTC #
# identical to fully-unset. Locks (i)–(iv) pin the whole chain.                 #
# --------------------------------------------------------------------------- #
def _fake_memory(monkeypatch, nested_tz):
    from types import SimpleNamespace

    async def fake_always_on():
        return {"name": "Master", "always_on": ({"timezone": nested_tz} if nested_tz is not None else {})}
    import app.agent.tools.calendar_tool as ct
    monkeypatch.setattr("app.memory.manager.get_memory",
                        lambda: SimpleNamespace(get_always_on=fake_always_on))


@pytest.mark.asyncio
async def test_i_nested_legacy_shape_resolves_unflagged(monkeypatch):
    """THE failing scenario (live-proven 2026-07-14): column NULL + tz in nested always_on →
    must resolve un-flagged, not ('UTC', True)."""
    import app.agent.tools.calendar_tool as ct
    monkeypatch.setattr(ct, "_profile_timezone_column", AsyncMock(return_value=""))
    _fake_memory(monkeypatch, "America/New_York")
    name, fallback = await ct._resolve_timezone("")
    assert (name, fallback) == ("America/New_York", False), f"the bridge is dead: {(name, fallback)}"


@pytest.mark.asyncio
async def test_ii_column_wins_over_legacy(monkeypatch):
    import app.agent.tools.calendar_tool as ct
    monkeypatch.setattr(ct, "_profile_timezone_column", AsyncMock(return_value="America/Denver"))
    _fake_memory(monkeypatch, "America/New_York")
    name, fallback = await ct._resolve_timezone("")
    assert (name, fallback) == ("America/Denver", False)


@pytest.mark.asyncio
async def test_iii_junk_legacy_zone_falls_through_flagged(monkeypatch):
    import app.agent.tools.calendar_tool as ct
    monkeypatch.setattr(ct, "_profile_timezone_column", AsyncMock(return_value=""))
    _fake_memory(monkeypatch, "Not/AZone")
    name, fallback = await ct._resolve_timezone("")
    assert fallback is True and name == "UTC"                   # validated, never crashes


@pytest.mark.asyncio
async def test_iv_everything_absent_stays_flagged_utc(monkeypatch):
    import app.agent.tools.calendar_tool as ct
    monkeypatch.setattr(ct, "_profile_timezone_column", AsyncMock(return_value=""))
    _fake_memory(monkeypatch, None)
    name, fallback = await ct._resolve_timezone("")
    assert (name, fallback) == ("UTC", True)
