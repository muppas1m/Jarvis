"""Proactive-briefing check-in intelligence (Phase 5.4) — decides WHEN to brief.

The briefing DATA layer (app/briefing.py: HWM, scopes, latest-delta, multi-day) is
untouched. This module adds the cheap, DETERMINISTIC state + decision that rides the
agent's existing turn (memory_load_node computes it once; no new node, no new LLM call):

  - load_live_state(now): ONE cheap read — the profile scalars (last_briefed_at,
    last_seen_at, briefing_hwm) + the unheard count (an indexed COUNT over briefing_items
    above the watermark). The efficiency lever: precise FACTS so the agent decides on
    facts, not by guessing from history.
  - briefing_directive(state): PURE — the facts + the deterministic decision (deliver /
    offer / suppress) the agent follows this turn. The COOLDOWN is decided HERE in code
    (keyed on last_briefed_at), not asked of the model — when it's active the directive
    says "do not proactively brief". An EXPLICIT ask bypasses all of this (the agent calls
    the briefing tool directly, which always answers).
  - touch_last_seen(now): advance the per-turn sighting (monotonic) AFTER the gap was read.
  - mark_briefed(now): THE single 'brief was delivered' seam — advance the HWM AND stamp
    last_briefed_at together (the briefing tool calls this in place of a bare advance_hwm).
"""
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select, update

from app.agent.tools.calendar_tool import _resolve_timezone
from app.briefing import advance_hwm
from app.config import settings
from app.db.engine import async_session
from app.db.models import BriefingItem, UserProfile
from app.utils.logging import get_logger

logger = get_logger(__name__)

_NULL_HWM_FLOOR_HOURS = 24  # mirrors the briefing tool's "latest" floor (don't brief "everything ever")


@dataclass(frozen=True)
class BriefingLiveState:
    """The cheap per-turn facts the briefing decision rides on."""
    now: datetime
    timezone: str
    last_briefed_at: datetime | None
    last_seen_at: datetime | None
    unheard: int                       # items a 'latest' brief would deliver right now


# --------------------------------------------------------------------------- #
# Reads.                                                                        #
# --------------------------------------------------------------------------- #
async def count_unheard(hwm: datetime | None, now: datetime) -> int:
    """How many items a 'latest' brief would deliver NOW — count of briefing_items in
    (effective, now], where effective = HWM or (NULL → now − 24h floor). An indexed
    COUNT (ix_briefing_items_occurred_at) — no rows fetched."""
    start = hwm if hwm is not None else (now - timedelta(hours=_NULL_HWM_FLOOR_HOURS))
    async with async_session() as session:
        n = (await session.execute(
            select(func.count())
            .select_from(BriefingItem)
            .where(BriefingItem.occurred_at > start)
            .where(BriefingItem.occurred_at <= now)
        )).scalar_one()
    return int(n or 0)


async def load_live_state(now: datetime) -> BriefingLiveState:
    """One cheap read: the profile scalars + the unheard count. TZ resolves via the
    shared resolver (arg → profile → flagged default)."""
    tz_name, _ = await _resolve_timezone("")
    async with async_session() as session:
        row = (await session.execute(
            select(
                UserProfile.last_briefed_at,
                UserProfile.last_seen_at,
                UserProfile.briefing_hwm,
            ).limit(1)
        )).first()
    last_briefed = row[0] if row else None
    last_seen = row[1] if row else None
    hwm = row[2] if row else None
    return BriefingLiveState(
        now=now, timezone=tz_name,
        last_briefed_at=last_briefed, last_seen_at=last_seen,
        unheard=await count_unheard(hwm, now),
    )


# --------------------------------------------------------------------------- #
# The decision — PURE, deterministic (the cooldown gate lives here).           #
# --------------------------------------------------------------------------- #
def _ago(then: datetime | None, now: datetime) -> str:
    if then is None:
        return "not yet"
    secs = (now - then).total_seconds()
    if secs < 90:
        return "just now"
    if secs < 5400:                       # < 90 min
        return f"{round(secs / 60)} minutes ago"
    if secs < 129600:                     # < 36 h
        return f"{round(secs / 3600)} hours ago"
    return f"{round(secs / 86400)} days ago"


# How to actually brief — force the tool call, kill the describe-instead-of-call + the
# "queued for approval" hallucination (briefing is a SAFE read), and stop the agent reciting
# the surfaced count in place of delivering. Shared by every branch that may brief.
_HOW = (
    "call the briefing('latest') tool and present what it returns. It is a normal READ — NOT an "
    "approval-tier action: never say you 'queued', 'prepared', or 'will' brief it. You do NOT know "
    "the items until the tool returns, so never invent them or recite the count in place of calling it."
)


def briefing_directive(state: BriefingLiveState) -> str:
    """PURE: the per-turn `<check_in>` guidance — precise facts + the deterministic
    deliver/offer/suppress decision the agent applies WITHIN this turn. Reads 'check-in'
    is left to the model (broad — "good morning", "what's going on", "long time no see");
    WHETHER a proactive brief may fire at all is decided HERE (cooldown / caught-up)."""
    h = settings.MASTER_HONORIFIC
    now, zone = state.now, ZoneInfo(state.timezone)
    last_briefed, last_seen, unheard = state.last_briefed_at, state.last_seen_at, state.unheard

    cooldown_active = (
        last_briefed is not None
        and (now - last_briefed) < timedelta(minutes=settings.BRIEFING_COOLDOWN_MINUTES)
    )
    away_days = (now - last_seen).days if last_seen is not None else 0
    multi_day = away_days >= settings.BRIEFING_AWAY_DAYS
    first_of_day = last_seen is None or last_seen.astimezone(zone).date() < now.astimezone(zone).date()

    seen = f"away {away_days} days" if multi_day else (
        "first interaction today" if first_of_day else f"last seen {_ago(last_seen, now)}"
    )
    facts = (
        f"PROACTIVE-BRIEFING STATE (deterministic — decide within THIS turn, no extra call): "
        f"last briefed {_ago(last_briefed, now)}; {seen}; {unheard} unheard item(s)."
    )

    if cooldown_active:
        d = (
            f"You briefed {h} {_ago(last_briefed, now)} — do NOT proactively brief, offer, or even mention a "
            f"briefing. ONLY if {h} EXPLICITLY asks ('what's the latest', 'anything new'). {_HOW} "
            f"Otherwise answer their message normally, as if no briefing were pending."
        )
    elif unheard == 0:
        d = (
            f"Nothing new is waiting — do NOT proactively brief or offer. ONLY if {h} explicitly asks what's "
            f"new, {_HOW} (it will confirm they're all caught up — keep it to one line)."
        )
    elif multi_day:
        d = (
            f"{h} has been away {away_days} days — {unheard} item(s) are unheard. A greeting here is a "
            f"check-in, NOT a trivial one-liner to brush off: OPEN your reply with the catch-up OFFER (do "
            f"NOT dump it, do NOT call the tool yet) — e.g. 'Welcome back, {h} — shall I catch you up on the "
            f"last {away_days} days?' ONLY after {h} says yes, {_HOW} If the message is a specific request, "
            f"handle that first, then make the offer."
        )
    elif first_of_day:
        d = (
            f"This is {h}'s FIRST interaction today and {unheard} item(s) are unheard. Read 'check-in' BROADLY "
            f"— 'good morning' / 'hey' / 'what's up' all count, and such a greeting here is NOT a trivial "
            f"one-liner to brush off. On a check-in, DELIVER the briefing now (don't merely offer): {_HOW} "
            f"Keep it tight and offer the next action ('shall I read it?'). ONLY if the message is a SPECIFIC "
            f"request (e.g. 'morning — cancel my 3pm') do THAT first, then offer the briefing as a short tail; "
            f"ONLY if it's genuinely unclear they're checking in, OFFER ('Shall I give you today's briefing, {h}?')."
        )
    else:
        # Seen earlier today already (not first-of-day) and not in cooldown: the morning check-in window
        # has passed — stay quiet so repeated greetings don't re-offer. Explicit asks still answer.
        d = (
            f"{h} has already interacted today, so do NOT proactively brief or offer again — that would nag. "
            f"ONLY if {h} EXPLICITLY asks ('what's new', 'the latest'), {_HOW} Otherwise answer normally."
        )
    return facts + " " + d


# --------------------------------------------------------------------------- #
# Writes.                                                                       #
# --------------------------------------------------------------------------- #
async def touch_last_seen(now: datetime) -> None:
    """Advance the per-turn sighting to `now` — MONOTONIC (never moves backward), read the
    gap from the PREVIOUS value BEFORE calling this. Best-effort at the call site."""
    async with async_session() as session:
        await session.execute(
            update(UserProfile)
            .where((UserProfile.last_seen_at.is_(None)) | (UserProfile.last_seen_at < now))
            .values(last_seen_at=now)
        )
        await session.commit()


async def mark_briefed(now: datetime) -> datetime | None:
    """THE single 'brief was delivered' seam (Phase 5.4 item 5): advance the HWM AND stamp
    last_briefed_at together. Called by the briefing tool in place of a bare advance_hwm,
    AFTER the brief text is produced (advance-on-return) — never before. Both stamps are
    monotonic. This is the one place the follow-up TTS-accurate refinement will touch."""
    hwm = await advance_hwm(now)
    async with async_session() as session:
        await session.execute(
            update(UserProfile)
            .where((UserProfile.last_briefed_at.is_(None)) | (UserProfile.last_briefed_at < now))
            .values(last_briefed_at=now)
        )
        await session.commit()
    return hwm
