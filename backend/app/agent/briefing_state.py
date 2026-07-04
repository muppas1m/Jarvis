"""Proactive-briefing check-in intelligence (Phase 5.4) — decides WHEN to brief.

The briefing DATA layer (app/briefing.py: HWM, scopes, latest-delta, multi-day) is
untouched. This module adds the cheap, DETERMINISTIC state + decision that rides the
agent's existing turn (memory_load_node computes it once; no new node, no new LLM call):

  - load_live_state(now): ONE cheap read — the profile scalars (last_briefed_at,
    last_seen_at, briefing_hwm) + the unheard count (an indexed COUNT over briefing_items
    above the watermark). The efficiency lever: precise FACTS so the agent decides on
    facts, not by guessing from history.
  - proactive_mode(state): PURE — the deterministic mode (suppress / surface_single /
    surface_multiday). The cooldown + caught-up gates are decided HERE in code, never asked
    of the model. The runner renders the OUTPUT post-turn from this mode, so the brief/offer
    is code-GUARANTEED (the model only writes the wrapper + the deliver_briefing() signal).
  - briefing_directive(state): PURE — the per-turn guidance. The model's only job: respond
    naturally, and on a single-day surface SIGNAL a clear check-in via deliver_briefing().
  - render_offer(state) / render_attach(mode, offer, messages): the code-rendered output —
    the offer line (the safe floor), or the actual brief when the model signalled deliver
    (fetched via briefing('latest'), which fires the mark_briefed seam). No double if a brief
    already went out this turn.
  - touch_last_seen(now): advance the per-turn sighting (monotonic) AFTER the gap was read.
  - mark_briefed(now): THE single 'brief was delivered' seam — advance the HWM AND stamp
    last_briefed_at together (the briefing tool calls this in place of a bare advance_hwm).
"""
from dataclasses import dataclass
from datetime import datetime, timedelta

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


# ---- the deterministic mode (the engine decides; the OUTPUT is code-rendered) ----
SUPPRESS = "suppress"              # cooldown active OR caught-up → no proactive attach
SURFACE_SINGLE = "surface_single" # unheard waiting, a same-day check-in window → deliver-or-offer
SURFACE_MULTIDAY = "surface_multiday"  # away ≥ BRIEFING_AWAY_DAYS → always OFFER the catch-up


def _assess(state: BriefingLiveState) -> tuple[str, int, bool]:
    """PURE: (mode, away_days, cooldown_active). The cooldown + caught-up gates are decided
    HERE in code, never asked of the model. 'surface_single' deliberately covers BOTH the
    first-interaction-of-the-day case AND a later re-greet with FRESH items since the last
    brief (unheard>0, past the cooldown) — a fresh delta surfaces, it doesn't go silent."""
    now = state.now
    lb, ls, unheard = state.last_briefed_at, state.last_seen_at, state.unheard
    cooldown = lb is not None and (now - lb) < timedelta(minutes=settings.BRIEFING_COOLDOWN_MINUTES)
    away_days = (now - ls).days if ls is not None else 0
    if cooldown or unheard == 0:
        mode = SUPPRESS
    elif away_days >= settings.BRIEFING_AWAY_DAYS:
        mode = SURFACE_MULTIDAY
    else:
        mode = SURFACE_SINGLE
    return mode, away_days, cooldown


def proactive_mode(state: BriefingLiveState) -> str:
    """The deterministic proactive mode the runner code renders post-turn."""
    return _assess(state)[0]


def render_offer(state: BriefingLiveState) -> str:
    """The code-owned OFFER line (the safe floor) — attached IN-GRAPH (persist_node) when the
    turn is a proactive moment but the model didn't signal a clear check-in (or it's multi-day).
    D21 (A2 s1b): composed, in-persona — never an "Oh —" opener; names the count so the master
    knows the weight of the offer. (Offering a BRIEFING is not an approval solicitation — the
    D24/D26 contract governs consent on actions, not this.)"""
    mode, away_days, _ = _assess(state)
    h = settings.MASTER_HONORIFIC
    n = state.unheard
    items = "One item awaits" if n == 1 else f"{n} items await"
    if mode == SURFACE_MULTIDAY:
        return (f"Welcome back, {h} — you've been away {away_days} days and "
                f"{items.lower()} your attention. Shall I catch you up?")
    return f"{items} your attention when you're ready, {h}. Shall I brief you?"


def briefing_directive(state: BriefingLiveState) -> str:
    """PURE: the per-turn `<check_in>` guidance. The model's ONLY job is to (a) respond
    naturally to the master's message and (b) on a single-day surface, SIGNAL a clear
    check-in by calling deliver_briefing() — the system renders the brief/offer itself, so
    the model never writes (or hallucinates) the briefing content. Suppress/caught-up/
    multi-day are decided in code; the model just answers normally there."""
    h = settings.MASTER_HONORIFIC
    mode, away_days, cooldown = _assess(state)
    facts = (
        f"PROACTIVE-BRIEFING STATE (deterministic): last briefed {_ago(state.last_briefed_at, state.now)}; "
        f"{state.unheard} unheard item(s); mode={mode}."
    )
    if mode == SUPPRESS:
        why = (
            f"you briefed {h} {_ago(state.last_briefed_at, state.now)} (cooldown)" if cooldown
            else "nothing new is waiting"
        )
        d = (
            f"Do NOT proactively brief or offer — {why}. Answer the master's message normally. ONLY if {h} "
            f"EXPLICITLY asks ('what's the latest', 'anything new') call briefing('latest') and relay it "
            f"(it may simply confirm they're all caught up — keep that to one line)."
        )
    elif mode == SURFACE_MULTIDAY:
        d = (
            f"{h} has been away {away_days} days with {state.unheard} unheard. Just respond NATURALLY to their "
            f"message — do NOT write a briefing or an offer yourself, and do NOT call any briefing tool; the "
            f"system attaches a catch-up offer for you (we never dump a multi-day catch-up unprompted)."
        )
    else:  # SURFACE_SINGLE
        d = (
            f"{state.unheard} item(s) are new since {h} last heard. Respond NATURALLY to their message — but do "
            f"NOT write the briefing or an offer yourself; the system attaches it. The ONE thing to decide: is "
            f"this message a CHECK-IN (read broadly — 'good morning', 'hey', 'what's up', 'what's new', 'how are "
            f"things')? If YES, call deliver_briefing() — the system then presents the brief (you don't write it). "
            f"If it's a SPECIFIC request (e.g. 'cancel my 3pm'), handle THAT and do NOT call deliver_briefing — the "
            f"system offers the briefing as a tail. Never narrate a briefing; deliver_briefing() is the only way to "
            f"brief. After calling it, your reply is JUST the natural greeting (e.g. 'Good morning, {h}!') — do NOT add "
            f"a lead-in like 'here's your briefing' or list any items; the system appends the brief right after."
        )
    return facts + " " + d


# --------------------------------------------------------------------------- #
# Post-turn render — CODE guarantees the output (text + voice); the model only  #
# wrote the wrapper. Reads the turn-start mode (stored in state) + the model's  #
# deliver signal (a tool call in the final messages).                           #
# --------------------------------------------------------------------------- #
def _called_tool(messages, name: str) -> bool:
    """TURN-BOUNDED (A2 s1b — fixes the whole-history scan the docstrings always claimed):
    walk backwards and STOP at this turn's HumanMessage, so a deliver_briefing() call from a
    PRIOR turn can never re-trigger today's attach."""
    from langchain_core.messages import AIMessage, HumanMessage
    for m in reversed(list(messages or [])):
        if isinstance(m, HumanMessage):
            break
        if isinstance(m, AIMessage):
            for tc in getattr(m, "tool_calls", None) or []:
                tc_name = tc.get("name") if isinstance(tc, dict) else getattr(tc, "name", "")
                if tc_name == name:
                    return True
    return False


def deliver_requested(messages) -> bool:
    """The model SIGNALLED a clear check-in by calling deliver_briefing() THIS turn."""
    return _called_tool(messages, "deliver_briefing")


def brief_already_delivered(messages) -> bool:
    """A brief already went out THIS turn via the explicit briefing() tool — don't double."""
    return _called_tool(messages, "briefing")


async def render_attach(mode: str, offer: str, messages) -> tuple[str, bool]:
    """The post-turn attach: (text, delivered). SUPPRESS or an already-delivered brief → no
    attach. A single-day surface WHERE the model signalled a check-in → fetch + attach the
    real brief (briefing('latest') advances the HWM + stamps last_briefed — the existing
    seam). Otherwise (multi-day, or single-day with no signal) → the code-owned OFFER floor."""
    if mode == SUPPRESS or brief_already_delivered(messages):
        return "", False
    if mode == SURFACE_SINGLE and deliver_requested(messages):
        from app.agent.tools.briefing_tool import briefing as _briefing
        return await _briefing("latest"), True   # fetch + advance (mark_briefed)
    return offer, False


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
    await mark_offered(now)  # the delivery is also a proactive surface — stamp the throttle
    return hwm


async def mark_offered(now: datetime) -> None:
    """Stamp the proactive-surface throttle (last_briefed_at) on an OFFER too — WITHOUT
    advancing the HWM, so the items stay unheard and re-surface AFTER the cooldown window.
    This is what stops the nag: once an offer (or delivery) goes out, the cooldown gate
    suppresses re-surfacing on every subsequent message (incl. plain tasks) until the window
    passes; an EXPLICIT 'what's the latest' still bypasses (it calls the briefing tool).
    Monotonic. (So last_briefed_at is really 'last proactively surfaced', offered or heard.)"""
    async with async_session() as session:
        await session.execute(
            update(UserProfile)
            .where((UserProfile.last_briefed_at.is_(None)) | (UserProfile.last_briefed_at < now))
            .values(last_briefed_at=now)
        )
        await session.commit()
