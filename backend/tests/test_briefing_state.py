"""Proactive-briefing check-in intelligence (5.4).

The DETERMINISTIC decision that rides the turn: briefing_directive (pure) — deliver /
offer / suppress per the facts, with the cooldown gate decided IN CODE; the cheap reads
(count_unheard, load_live_state); and the single delivery seam (mark_briefed advances the
HWM AND stamps last_briefed_at). Single-row profile state is saved/restored like the HWM
tests. Far-future item dates avoid colliding with any real data.
"""
from datetime import UTC, datetime, timedelta

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
# briefing_directive — the deterministic deliver / offer / suppress decision.  #
# --------------------------------------------------------------------------- #
def test_first_of_day_delivers():
    # First interaction today + unheard items → DELIVER on a check-in (call the tool, not a
    # bare one-liner). Offer only if the message is genuinely ambiguous.
    d = bs.briefing_directive(_state(last_seen=_NOW - timedelta(days=1), unheard=2))
    assert "first interaction today" in d                 # the facts line
    assert "DELIVER the briefing" in d and "briefing('latest')" in d
    assert "NOT a trivial" in d                            # overrides the one-liner steering
    assert "2 unheard" in d


def test_cooldown_suppresses_proactive_but_allows_explicit():
    # Briefed 9 min ago → do NOT proactively brief; an explicit ask still answers.
    d = bs.briefing_directive(_state(last_briefed=_NOW - timedelta(minutes=9),
                                     last_seen=_NOW - timedelta(minutes=9), unheard=3))
    assert "do NOT proactively brief" in d
    assert "EXPLICITLY asks" in d
    assert "9 minutes ago" in d


def test_cooldown_takes_precedence_over_unheard():
    # Even with unheard items, within the cooldown the decision is SUPPRESS (not deliver).
    d = bs.briefing_directive(_state(last_briefed=_NOW - timedelta(minutes=1),
                                     last_seen=_NOW - timedelta(days=1), unheard=9))
    assert "do NOT proactively brief" in d
    assert "deliver it now" not in d


def test_multi_day_gap_offers_catchup_not_dump():
    d = bs.briefing_directive(_state(last_seen=_NOW - timedelta(days=3), unheard=5))
    assert "away 3 days" in d
    assert "catch-up OFFER" in d and "do NOT dump" in d
    assert "after Sir says yes" in d  # never call the tool / dump unprompted


def test_caught_up_says_nothing_new():
    d = bs.briefing_directive(_state(last_briefed=_NOW - timedelta(hours=5),
                                     last_seen=_NOW - timedelta(hours=5), unheard=0))
    assert "Nothing new" in d and "do NOT proactively brief" in d
    assert "all caught up" in d


def test_unheard_but_seen_today_stays_quiet():
    # Seen earlier today (not first-of-day), not in cooldown, unheard waiting → the morning
    # check-in window has passed, so do NOT re-offer (anti-spam); explicit asks still answer.
    d = bs.briefing_directive(_state(last_briefed=_NOW - timedelta(hours=3),
                                     last_seen=_NOW - timedelta(hours=2), unheard=1))
    assert "already interacted today" in d
    assert "do NOT proactively brief or offer" in d and "EXPLICITLY asks" in d


def test_cooldown_boundary_is_deterministic():
    cd = settings.BRIEFING_COOLDOWN_MINUTES
    inside = bs.briefing_directive(_state(last_briefed=_NOW - timedelta(minutes=cd - 1),
                                          last_seen=_NOW - timedelta(days=1), unheard=2))
    outside = bs.briefing_directive(_state(last_briefed=_NOW - timedelta(minutes=cd + 1),
                                           last_seen=_NOW - timedelta(days=1), unheard=2))
    assert "do NOT proactively brief" in inside        # just inside → suppressed
    assert "do NOT proactively brief" not in outside    # just outside → free to deliver/offer


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
