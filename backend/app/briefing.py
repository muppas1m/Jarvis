"""
Read-state briefing engine (Phase 5.1) — the foundation.

The per-master "heard-up-to" high-water mark (UserProfile.briefing_hwm) + the
durable, windowable store (briefing_items). The behaviors (latest / today /
yesterday / tomorrow + advance-vs-not) and the conversational tool are 5.2; the
ingestion rewire + 7am push are 5.3. This module is the primitive both build on:

  - read_hwm() / advance_hwm(now): the watermark. advance is ATOMIC + MONOTONIC
    (UPDATE … WHERE hwm IS NULL OR hwm < now) — a concurrent double-advance can
    never move it backward (mirrors the approval claim).
  - digest_window(start, end): briefing_items with occurred_at ∈ (start, end],
    DAY-SEGMENTED in the master's TZ (so a missed-days catch-up renders per day).
    segment_by_day is the pure, unit-tested core.

TZ resolution reuses 4.2's resolver (app/agent/tools/calendar_tool._resolve_timezone)
— the same arg → profile → flagged-default path; no duplicated TZ logic.
"""
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select, update

from app.agent.tools.calendar_tool import _resolve_timezone
from app.config import settings
from app.db.engine import async_session
from app.db.models import BriefingItem, MorningBrief, UserProfile
from app.utils.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class BriefingDay:
    day: date
    items: list


@dataclass(frozen=True)
class DigestWindow:
    start: datetime
    end: datetime
    timezone: str
    timezone_fallback: bool
    days: list = field(default_factory=list)  # BriefingDay[], chronological
    total: int = 0


# --------------------------------------------------------------------------- #
# Pure: day segmentation (the unit-tested core).                              #
# --------------------------------------------------------------------------- #
def segment_by_day(items: list, tz: str) -> list[BriefingDay]:
    """Group items by their LOCAL day (occurred_at in `tz`), chronological within
    and across days. Pure — a single-day window yields one BriefingDay; a multi-day
    window yields one per day (the missed-days catch-up segmentation)."""
    zone = ZoneInfo(tz)
    buckets: dict[date, list] = {}
    for it in sorted(items, key=lambda x: x.occurred_at):
        buckets.setdefault(it.occurred_at.astimezone(zone).date(), []).append(it)
    return [BriefingDay(d, buckets[d]) for d in sorted(buckets)]


# --------------------------------------------------------------------------- #
# Windowed read.                                                              #
# --------------------------------------------------------------------------- #
async def digest_window(start: datetime, end: datetime, tz: str = "") -> DigestWindow:
    """Briefing items with occurred_at ∈ (start, end], segmented by local day.
    `tz` resolves arg → profile → flagged default (reuses 4.2's resolver), so the
    caller can pass an explicit TZ or let it resolve. The (start, end] bounds are
    instants (UTC); the day segmentation is in the resolved TZ."""
    tz_name, fallback = await _resolve_timezone(tz)
    async with async_session() as session:
        items = list((await session.execute(
            select(BriefingItem)
            .where(BriefingItem.occurred_at > start)
            .where(BriefingItem.occurred_at <= end)
            .order_by(BriefingItem.occurred_at.asc())
        )).scalars().all())
    return DigestWindow(
        start=start, end=end, timezone=tz_name, timezone_fallback=fallback,
        days=segment_by_day(items, tz_name), total=len(items),
    )


# --------------------------------------------------------------------------- #
# The HWM — atomic + monotonic.                                               #
# --------------------------------------------------------------------------- #
async def read_hwm() -> datetime | None:
    """The master's current heard-up-to mark, or None if never set (single-row)."""
    async with async_session() as session:
        row = (await session.execute(
            select(UserProfile.briefing_hwm).limit(1)
        )).first()
    return row[0] if row else None


async def advance_hwm(now: datetime) -> datetime | None:
    """Advance the HWM to `now` — ATOMIC + MONOTONIC. The single conditional UPDATE
    (WHERE hwm IS NULL OR hwm < now) is the gate: under row locking, a concurrent
    double-advance serializes and the mark NEVER moves backward (an earlier `now`
    that loses the race matches zero rows). Returns the resulting HWM."""
    async with async_session() as session:
        await session.execute(
            update(UserProfile)
            .where((UserProfile.briefing_hwm.is_(None)) | (UserProfile.briefing_hwm < now))
            .values(briefing_hwm=now)
        )
        await session.commit()
    return await read_hwm()


# --------------------------------------------------------------------------- #
# Ingestion + the proactive 7am push (5.3).                                   #
# --------------------------------------------------------------------------- #
async def record_briefing_item(
    *, kind: str, title: str, source: str, preview: str, urgency: str,
    occurred_at: datetime, meta: dict | None = None,
) -> None:
    """Durably record one briefing item — the FYI-mail ingestion (replacing the
    clear-on-build Redis digest) and the future news seam (kind='news'). The caller
    owns fail-soft (it raises on a real DB error)."""
    async with async_session() as session:
        session.add(BriefingItem(
            kind=kind, title=title, source=source, preview=preview,
            urgency=urgency, occurred_at=occurred_at, meta=meta or {},
        ))
        await session.commit()


async def build_push_digest(now: datetime, *, cap_days: int) -> DigestWindow:
    """The proactive 7am push window: (max(HWM-or-24h-floor, now − cap_days), now].
    NO advance — the push must NOT consume (a missed push must still surface under
    'latest'; the caller never advances on this path). The cap stops an unread HWM
    from growing the window unbounded; the NULL-HWM 24h floor holds here too."""
    hwm = await read_hwm()
    floor = now - timedelta(hours=24)                        # NULL-HWM first-run floor
    effective = hwm if hwm is not None else floor
    start = max(effective, now - timedelta(days=cap_days))   # cap on an unread HWM
    return await digest_window(start, now)                   # tz resolves from profile


def render_push(win: DigestWindow) -> str:
    """The 7am push text — day-segmented, urgency-tagged. Returns a 'nothing new'
    line when empty (the morning brief still greets the master). Chronological with
    inline urgency tags supersedes the old digest's urgency-first sort — the
    time-windowed model carries the date context the sort used to compensate for."""
    if win.total == 0:
        return "📬 *Email Digest:* nothing new."
    lines = [f"📬 *Email Digest* — {win.total} new:"]
    multi = len(win.days) > 1
    for d in win.days:
        if multi:
            lines.append(f"_{d.day.strftime('%A %Y-%m-%d')}_:")
        for it in d.items:
            tag = f"[{it.urgency}] " if it.urgency and it.urgency != "none" else ""
            src = f" — {it.source}" if it.source else ""
            lines.append(f"  • {tag}{it.title or '(no subject)'}{src}")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# HUD surface — persist the SAME digest the Telegram push sends, so the HUD can  #
# poll it (persist-then-poll; the brief is Celery-driven with no active stream). #
# --------------------------------------------------------------------------- #
def digest_to_payload(win: DigestWindow) -> dict:
    """Serialize a DigestWindow into the HUD briefing payload (pure, JSON-safe).

    The HUD BriefingCard renders this STRUCTURALLY — day sections, urgency chips,
    and untrusted fields (title/source/preview, which carry attacker-influenceable
    email content) as escaped React text, never markdown — so it shows the SAME
    content the Telegram render_push does, plus per-item previews, with no raw-HTML/
    markdown injection surface. ``occurred_at``/``window_*`` are ISO-8601 instants;
    ``day`` is the local-day label the segmentation already computed."""
    return {
        "empty": win.total == 0,
        "total": win.total,
        "timezone": win.timezone,
        "window_start": win.start.isoformat(),
        "window_end": win.end.isoformat(),
        "days": [
            {
                "day": d.day.isoformat(),
                "items": [
                    {
                        "title": it.title or "",
                        "source": it.source or "",
                        "preview": it.preview or "",
                        "urgency": it.urgency or "none",
                        "kind": it.kind,
                        "occurred_at": it.occurred_at.isoformat(),
                    }
                    for it in d.items
                ],
            }
            for d in win.days
        ],
    }


async def record_morning_brief(payload: dict) -> None:
    """Best-effort persist of one morning brief so the HUD can surface it, then prune
    so the table self-limits to ~one row. FULLY wrapped + INDEPENDENT of the Telegram
    send (mirrors failure_alerter._persist_alert): a DB failure here logs but never
    raises, so neither a persist nor a prune problem can break the proactive Telegram
    brief.

    Prune = DELETE briefs older than the freshness window (the SAME TTL the endpoint
    filters on) — so a stale brief is both un-shown AND removed, not just hidden. It
    runs AFTER the insert commits, in a separate statement, so a prune failure can
    never roll back the just-persisted brief (and the outer wrapper keeps it off the
    brief/Telegram path entirely)."""
    try:
        async with async_session() as session:
            session.add(MorningBrief(payload=payload))
            await session.commit()
            cutoff = datetime.now(UTC) - timedelta(hours=settings.BRIEFING_HUD_TTL_HOURS)
            await session.execute(delete(MorningBrief).where(MorningBrief.created_at < cutoff))
            await session.commit()
    except Exception as exc:  # noqa: BLE001 — best-effort HUD surface; never raise
        logger.error("morning_brief_persist_failed", error=str(exc))
