"""Proactive-briefing check-in intelligence (5.4).

The DETERMINISTIC engine: proactive_mode (suppress / surface_single / surface_multiday,
cooldown + caught-up decided IN CODE) and — the key BEHAVIOR-level seam — render_attach,
which returns the actual text the runner appends to the reply: the real brief when the
model SIGNALLED a check-in (deliver_briefing tool call), else the code-owned OFFER floor.
Asserting render_attach (not just the directive string) is what catches an offer that
under-fires. Plus the cheap reads and the mark_briefed delivery seam. Single-row profile
state is saved/restored like the HWM tests; far-future item dates avoid real-data collision.
"""
from datetime import UTC, datetime, timedelta

from langchain_core.messages import AIMessage
from sqlalchemy import delete, select, update

import app.agent.briefing_state as bs
from app.agent.prompts import build_system_prompt
from app.config import settings
from app.db.engine import async_session
from app.db.models import BriefingItem, UserProfile

_NOW = datetime(2026, 6, 26, 14, 0, tzinfo=UTC)  # a fixed "now" (10:00 EDT)
_TZ = "America/New_York"


def _state(last_briefed=None, last_seen=None, unheard=0, now=_NOW):
    return bs.BriefingLiveState(
        now=now, timezone=_TZ, last_briefed_at=last_briefed, last_seen_at=last_seen, unheard=unheard,
    )


# --------------------------------------------------------------------------- #
# proactive_mode — the deterministic deliver-window / suppress decision.       #
# --------------------------------------------------------------------------- #
def test_mode_first_of_day_surfaces():
    assert bs.proactive_mode(_state(last_seen=_NOW - timedelta(days=1), unheard=2)) == bs.SURFACE_SINGLE


def test_mode_regreet_with_fresh_delta_surfaces():
    # Item 2: seen earlier today, PAST the cooldown, with fresh items → SURFACE (not silent).
    m = bs.proactive_mode(_state(last_briefed=_NOW - timedelta(hours=3),
                                 last_seen=_NOW - timedelta(hours=2), unheard=2))
    assert m == bs.SURFACE_SINGLE


def test_mode_cooldown_suppresses_even_with_unheard():
    m = bs.proactive_mode(_state(last_briefed=_NOW - timedelta(minutes=9),
                                 last_seen=_NOW - timedelta(days=1), unheard=9))
    assert m == bs.SUPPRESS


def test_mode_caught_up_suppresses():
    assert bs.proactive_mode(_state(last_briefed=_NOW - timedelta(hours=5),
                                    last_seen=_NOW - timedelta(hours=5), unheard=0)) == bs.SUPPRESS


def test_mode_multiday():
    assert bs.proactive_mode(_state(last_seen=_NOW - timedelta(days=3), unheard=5)) == bs.SURFACE_MULTIDAY


def test_mode_cooldown_boundary_is_deterministic():
    cd = settings.BRIEFING_COOLDOWN_MINUTES
    inside = _state(last_briefed=_NOW - timedelta(minutes=cd - 1), last_seen=_NOW - timedelta(days=1), unheard=2)
    outside = _state(last_briefed=_NOW - timedelta(minutes=cd + 1), last_seen=_NOW - timedelta(days=1), unheard=2)
    assert bs.proactive_mode(inside) == bs.SUPPRESS
    assert bs.proactive_mode(outside) == bs.SURFACE_SINGLE


def test_render_offer_per_mode():
    assert "latest" in bs.render_offer(_state(last_seen=_NOW - timedelta(days=1), unheard=2)).lower()
    multi = bs.render_offer(_state(last_seen=_NOW - timedelta(days=3), unheard=5))
    assert "away 3 days" in multi and "catch you up" in multi


def test_directive_surface_single_tells_model_to_signal():
    d = bs.briefing_directive(_state(last_seen=_NOW - timedelta(days=1), unheard=2))
    assert "deliver_briefing()" in d and "do NOT write the briefing" in d
    assert "mode=surface_single" in d


def test_directive_suppress_only_on_explicit():
    d = bs.briefing_directive(_state(last_briefed=_NOW - timedelta(minutes=9),
                                     last_seen=_NOW - timedelta(minutes=9), unheard=3))
    assert "Do NOT proactively brief or offer" in d and "cooldown" in d


# --------------------------------------------------------------------------- #
# render_attach — BEHAVIOR-LEVEL: the actual text the runner appends (the brief #
# on a deliver SIGNAL, the offer line otherwise). This is what reaches the     #
# master — asserting it, not just the directive string (the gap last time).    #
# --------------------------------------------------------------------------- #
def _ai_calling(tool_name):
    return AIMessage(content="Good morning, Sir.", tool_calls=[{"name": tool_name, "args": {}, "id": "x"}])


async def test_render_attach_delivers_the_brief_on_signal(monkeypatch):
    async def fake_briefing(scope="latest"):
        return "Here's the latest, Sir — 2 new: ..."
    monkeypatch.setattr("app.agent.tools.briefing_tool.briefing", fake_briefing)
    text, delivered = await bs.render_attach(bs.SURFACE_SINGLE, "OFFER LINE", [_ai_calling("deliver_briefing")])
    assert delivered and "the latest" in text and "OFFER LINE" not in text


async def test_render_attach_offers_the_floor_without_signal():
    # No deliver_briefing signal (a task turn) → the code-owned OFFER floor, NOT silence.
    text, delivered = await bs.render_attach(bs.SURFACE_SINGLE, "OFFER FLOOR", [_ai_calling("calendar_read")])
    assert not delivered and text == "OFFER FLOOR"


async def test_render_attach_multiday_always_offers_never_dumps():
    # Even if the model erroneously signalled deliver, multi-day NEVER auto-delivers.
    text, delivered = await bs.render_attach(bs.SURFACE_MULTIDAY, "CATCHUP OFFER", [_ai_calling("deliver_briefing")])
    assert not delivered and text == "CATCHUP OFFER"


async def test_render_attach_suppress_is_silent():
    text, delivered = await bs.render_attach(bs.SUPPRESS, "OFFER", [_ai_calling("deliver_briefing")])
    assert text == "" and not delivered


async def test_render_attach_no_double_when_explicit_briefing_ran(monkeypatch):
    # The master explicitly asked → the briefing() tool already delivered this turn. The
    # proactive attach must NOT fire again (no double-brief).
    async def fake_briefing(scope="latest"):
        return "should not be called"
    monkeypatch.setattr("app.agent.tools.briefing_tool.briefing", fake_briefing)
    msgs = [_ai_calling("briefing"), _ai_calling("deliver_briefing")]
    text, delivered = await bs.render_attach(bs.SURFACE_SINGLE, "OFFER", msgs)
    assert text == "" and not delivered


def test_ago_phrasing():
    assert bs._ago(None, _NOW) == "not yet"
    assert bs._ago(_NOW - timedelta(seconds=30), _NOW) == "just now"
    assert "minutes ago" in bs._ago(_NOW - timedelta(minutes=9), _NOW)
    assert "hours ago" in bs._ago(_NOW - timedelta(hours=5), _NOW)
    assert "days ago" in bs._ago(_NOW - timedelta(days=3), _NOW)


# --------------------------------------------------------------------------- #
# Prompt injection — volatile <check_in> block (empty → no block).             #
# --------------------------------------------------------------------------- #
def _profile():
    return {"name": "Master", "always_on": {"timezone": _TZ}}


def test_prompt_injects_check_in_block():
    out = build_system_prompt(_profile(), [], [], "web", _NOW.isoformat(),
                              briefing_directive="DELIVER TODAY'S BRIEFING")
    assert "<check_in>" in out and "DELIVER TODAY'S BRIEFING" in out


def test_prompt_no_block_when_empty():
    out = build_system_prompt(_profile(), [], [], "web", _NOW.isoformat(), briefing_directive="")
    assert "<check_in>" not in out


# --------------------------------------------------------------------------- #
# Cheap reads + the delivery seam (DB; single-row state saved/restored).       #
# --------------------------------------------------------------------------- #
_FUT = datetime(2090, 3, 1, 12, 0, tzinfo=UTC)  # far-future → no real-data collision


async def _seed(tag, occurred_ats):
    async with async_session() as s:
        for i, oa in enumerate(occurred_ats):
            s.add(BriefingItem(kind="email", occurred_at=oa, title=f"{tag}-{i}", source="x", preview="p"))
        await s.commit()


async def _cleanup(tag):
    async with async_session() as s:
        await s.execute(delete(BriefingItem).where(BriefingItem.title.like(f"{tag}%")))
        await s.commit()


async def _save_profile():
    async with async_session() as s:
        return (await s.execute(select(
            UserProfile.briefing_hwm, UserProfile.last_briefed_at, UserProfile.last_seen_at
        ).limit(1))).first()


async def _restore_profile(saved):
    async with async_session() as s:
        await s.execute(update(UserProfile).values(
            briefing_hwm=saved[0], last_briefed_at=saved[1], last_seen_at=saved[2],
        ))
        await s.commit()


async def test_count_unheard_counts_window_above_hwm():
    tag = "cu-test"
    base = _FUT
    await _seed(tag, [base - timedelta(hours=2), base - timedelta(hours=1), base + timedelta(hours=1)])
    try:
        # HWM at base − 90min → only the two items in (hwm, base] count; the future one is > now.
        n = await bs.count_unheard(base - timedelta(minutes=90), base)
        assert n == 1  # only base−1h is in (base−90m, base]; base−2h is below, base+1h is above
        # NULL hwm floors at now−24h → both past items (within 24h) count.
        assert await bs.count_unheard(None, base) == 2
    finally:
        await _cleanup(tag)


async def test_mark_briefed_advances_hwm_and_stamps_last_briefed():
    saved = await _save_profile()
    try:
        await bs.mark_briefed(_FUT)
        async with async_session() as s:
            hwm, lb, _ = (await s.execute(select(
                UserProfile.briefing_hwm, UserProfile.last_briefed_at, UserProfile.last_seen_at
            ).limit(1))).first()
        assert hwm == _FUT and lb == _FUT  # one seam — both advanced together
    finally:
        await _restore_profile(saved)


async def test_touch_last_seen_is_monotonic():
    saved = await _save_profile()
    try:
        await bs.touch_last_seen(_FUT)
        await bs.touch_last_seen(_FUT - timedelta(days=10))  # an older sighting must NOT move it back
        async with async_session() as s:
            ls = (await s.execute(select(UserProfile.last_seen_at).limit(1))).scalar_one()
        assert ls == _FUT
    finally:
        await _restore_profile(saved)


async def test_load_live_state_reads_the_facts():
    saved = await _save_profile()
    tag = "lls-test"
    try:
        async with async_session() as s:
            await s.execute(update(UserProfile).values(
                briefing_hwm=_FUT - timedelta(hours=1),
                last_briefed_at=_FUT - timedelta(minutes=20),
                last_seen_at=_FUT - timedelta(days=1),
            ))
            await s.commit()
        await _seed(tag, [_FUT - timedelta(minutes=30)])  # one item above the HWM
        live = await bs.load_live_state(_FUT)
        assert live.last_briefed_at == _FUT - timedelta(minutes=20)
        assert live.last_seen_at == _FUT - timedelta(days=1)
        assert live.unheard == 1
    finally:
        await _cleanup(tag)
        await _restore_profile(saved)


async def test_offer_throttles_then_resurfaces_after_window():
    # Item 1: a proactive OFFER is a throttled event. Turn 1 surfaces → mark_offered stamps the
    # cooldown → Turn 2 (a plain task moments later) is SUPPRESS (no second offer); past the
    # cooldown window the SAME pending items re-surface (the offer didn't advance the HWM).
    saved = await _save_profile()
    tag = "throttle"
    try:
        async with async_session() as s:
            await s.execute(update(UserProfile).values(briefing_hwm=None, last_briefed_at=None, last_seen_at=None))
            await s.commit()
        await _seed(tag, [_FUT - timedelta(minutes=30)])  # one unheard item

        # Turn 1 → a proactive surface moment (offer eligible).
        assert bs.proactive_mode(await bs.load_live_state(_FUT)) == bs.SURFACE_SINGLE
        await bs.mark_offered(_FUT)  # the runner stamps this when it attaches the OFFER

        # Turn 2, a minute later (next message in the same stream) → SUPPRESSED, not a 2nd offer.
        assert bs.proactive_mode(await bs.load_live_state(_FUT + timedelta(minutes=1))) == bs.SUPPRESS

        # An OFFER does NOT advance the HWM → the items are still unheard, so past the cooldown
        # window the same delta re-surfaces (re-offer/deliver on a genuine later moment).
        past = _FUT + timedelta(minutes=settings.BRIEFING_COOLDOWN_MINUTES + 1)
        live = await bs.load_live_state(past)
        assert live.unheard == 1 and bs.proactive_mode(live) == bs.SURFACE_SINGLE
    finally:
        await _cleanup(tag)
        await _restore_profile(saved)
