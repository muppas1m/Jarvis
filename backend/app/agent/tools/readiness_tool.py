"""
Readiness intelligence (Phase 4.3) — "am I all set for [period]?"

Synthesizes THREE sources over a period RESOLVED SERVER-SIDE in the master's
timezone (never LLM date-math):
  - tasks (4.1 actionable_items): open tasks due in-period OR overdue,
  - approvals (the pending queue): outstanding, flagging in-period expiries,
  - calendar (4.2 calendar_period): events in the period,
plus a priority-scaled LOOK-AHEAD (important items just beyond the period) and a
VERDICT (not-all-set iff any overdue task OR any in-period approval expiry).

The scrutinized logic is PURE + injectable-now: `resolve_period(keyword, tz, now)`
and `select_lookahead(tasks, end, horizons)`. Each source is FAIL-SOFT — a failure
degrades to a partial answer with a note, never an error (and the verdict goes
"uncertain" rather than falsely "all set" when a verdict-source couldn't be read).

`readiness_check(period)` is SAFE (pure read); `period` is a plain str validated in
the handler (open-weights convention — no Literal).
"""
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agent.tools.calendar_tool import _resolve_timezone, calendar_period
from app.agent.tools.registry import tool_registry
from app.config import settings
from app.db.engine import async_session
from app.db.models import ActionableItem, PendingApproval
from app.utils.logging import get_logger

logger = get_logger(__name__)

PERIOD_KEYWORDS = ("today", "tomorrow", "this_week", "this_weekend", "next_week", "this_month")


@dataclass(frozen=True)
class PeriodRange:
    keyword: str
    label: str
    start: date
    end: date


# --------------------------------------------------------------------------- #
# Pure logic — heavily unit-tested, `now` injected (no wall-clock).            #
# --------------------------------------------------------------------------- #
def resolve_period(keyword: str, tz: str, now: datetime) -> PeriodRange | None:
    """[start, end] local-date range for a period keyword, in `tz`, relative to the
    INJECTED `now`. None for an unknown keyword. ISO weeks (Mon=0 … Sun=6)."""
    today = now.astimezone(ZoneInfo(tz)).date()
    wd = today.weekday()
    if keyword == "today":
        return PeriodRange(keyword, "today", today, today)
    if keyword == "tomorrow":
        d = today + timedelta(days=1)
        return PeriodRange(keyword, "tomorrow", d, d)
    if keyword == "this_week":  # today → coming Sunday
        return PeriodRange(keyword, "this week", today, today + timedelta(days=6 - wd))
    if keyword == "this_weekend":
        if wd == 6:  # Sunday — the weekend is just today
            return PeriodRange(keyword, "this weekend", today, today)
        sat = today + timedelta(days=(5 - wd) % 7)  # coming Saturday (today if Sat)
        return PeriodRange(keyword, "this weekend", sat, sat + timedelta(days=1))
    if keyword == "next_week":  # next Monday → next Sunday
        nm = today + timedelta(days=7 - wd)
        return PeriodRange(keyword, "next week", nm, nm + timedelta(days=6))
    if keyword == "this_month":  # today → last day of this month
        first_next = (
            date(today.year + 1, 1, 1) if today.month == 12
            else date(today.year, today.month + 1, 1)
        )
        return PeriodRange(keyword, "this month", today, first_next - timedelta(days=1))
    return None


def lookahead_horizons() -> dict[str, int]:
    return {
        "high": settings.READINESS_LOOKAHEAD_HIGH_DAYS,
        "medium": settings.READINESS_LOOKAHEAD_MEDIUM_DAYS,
        "low": settings.READINESS_LOOKAHEAD_LOW_DAYS,
    }


def select_lookahead(tasks: list, period_end: date, horizons: dict[str, int]) -> list:
    """Open tasks due AFTER `period_end`, surfaced only within the priority-scaled
    horizon (high:30 / medium:7 / low:0 days by default). Pure."""
    out = []
    for t in tasks:
        if t.due_date is None or t.due_date <= period_end:
            continue
        if (t.due_date - period_end).days <= horizons.get(t.priority, 0):
            out.append(t)
    return out


def categorize_tasks(tasks: list, period: PeriodRange, today: date, horizons: dict[str, int]):
    """Split open tasks into (overdue, in-period, no-due-high, look-ahead). Pure.
    Overdue = due before today (surfaced for ANY period). A no-due task surfaces
    ONLY if high priority (capped)."""
    overdue = [t for t in tasks if t.due_date and t.due_date < today]
    in_period = [t for t in tasks if t.due_date and period.start <= t.due_date <= period.end]
    no_due_high = [t for t in tasks if t.due_date is None and t.priority == "high"]
    ahead = select_lookahead(tasks, period.end, horizons)
    return overdue, in_period, no_due_high, ahead


def compute_verdict(*, overdue: list, expiring: list, tasks_ok: bool, approvals_ok: bool) -> str:
    """'not all set' iff any overdue task OR any in-period approval expiry; else
    'uncertain' if a verdict-source couldn't be read (honest fail-soft); else
    'all set'. (In-period tasks are reported but don't alone flip the verdict.)"""
    if overdue or expiring:
        return "not all set"
    if not tasks_ok or not approvals_ok:
        return "uncertain"
    return "all set"


# --------------------------------------------------------------------------- #
# Sources (fail-soft) + orchestration.                                        #
# --------------------------------------------------------------------------- #
@dataclass
class ReadinessReport:
    period: PeriodRange
    timezone: str
    timezone_fallback: bool
    verdict: str = "all set"
    overdue: list = field(default_factory=list)
    in_period_tasks: list = field(default_factory=list)
    no_due_high: list = field(default_factory=list)
    ahead: list = field(default_factory=list)
    approvals_total: int = 0
    approvals_expiring: list = field(default_factory=list)
    calendar_events: list = field(default_factory=list)
    notes: list = field(default_factory=list)  # fail-soft degradations


async def _open_tasks() -> list[ActionableItem]:
    async with async_session() as s:
        return list((await s.execute(
            select(ActionableItem).where(ActionableItem.status == "open")
        )).scalars().all())


async def _pending_approvals(now: datetime) -> list[PendingApproval]:
    async with async_session() as s:
        return list((await s.execute(
            select(PendingApproval)
            .where(PendingApproval.status == "pending")
            .where(PendingApproval.expires_at > now)
        )).scalars().all())


async def gather_readiness(keyword: str, now: datetime) -> ReadinessReport | None:
    """Orchestrate the three sources over the resolved period, fail-soft per source.
    None only for an unknown keyword (the handler validates first)."""
    tz_name, tz_fallback = await _resolve_timezone("")
    period = resolve_period(keyword, tz_name, now)
    if period is None:
        return None
    zone = ZoneInfo(tz_name)
    today = now.astimezone(zone).date()
    horizons = lookahead_horizons()
    report = ReadinessReport(period=period, timezone=tz_name, timezone_fallback=tz_fallback)

    tasks_ok, approvals_ok = True, True

    try:
        overdue, in_period, no_due_high, ahead = categorize_tasks(
            await _open_tasks(), period, today, horizons
        )
        report.overdue, report.in_period_tasks = overdue, in_period
        report.no_due_high, report.ahead = no_due_high, ahead
    except Exception as exc:  # noqa: BLE001 — fail-soft
        logger.warning("readiness_tasks_failed", error=str(exc))
        report.notes.append("couldn't reach your task list")
        tasks_ok = False

    try:
        approvals = await _pending_approvals(now)
        report.approvals_total = len(approvals)
        report.approvals_expiring = [
            a for a in approvals
            if period.start <= a.expires_at.astimezone(zone).date() <= period.end
        ]
    except Exception as exc:  # noqa: BLE001 — fail-soft
        logger.warning("readiness_approvals_failed", error=str(exc))
        report.notes.append("couldn't check your approvals")
        approvals_ok = False

    cal = await calendar_period(period.start.isoformat(), period.end.isoformat(), tz=tz_name)
    if cal.ok:
        report.calendar_events = cal.events
    else:
        report.notes.append("couldn't reach your calendar")

    report.verdict = compute_verdict(
        overdue=report.overdue, expiring=report.approvals_expiring,
        tasks_ok=tasks_ok, approvals_ok=approvals_ok,
    )
    return report


# --------------------------------------------------------------------------- #
# Narration.                                                                  #
# --------------------------------------------------------------------------- #
def _tasks_line(tasks: list) -> str:
    parts = []
    for t in tasks:
        due = f", due {t.due_date.isoformat()}" if t.due_date else ""
        parts.append(f"{t.content} ({t.priority}{due})")
    return "; ".join(parts)


def _events_line(events: list) -> str:
    return "; ".join(f"{e.title} ({e.start})" for e in events[:8])


def format_report(report: ReadinessReport) -> str:
    h = settings.MASTER_HONORIFIC
    p = report.period
    verdict = {
        "all set": "✅ All set.",
        "not all set": "⚠️ Not all set.",
        "uncertain": "⚠️ Can't fully confirm — see below.",
    }[report.verdict]
    lines = [
        f"Readiness for {p.label} ({p.start.isoformat()} → {p.end.isoformat()}), {h}:",
        f"Verdict: {verdict}",
    ]
    if report.overdue:
        lines.append("• Overdue: " + _tasks_line(report.overdue))
    if report.in_period_tasks:
        lines.append(f"• Tasks {p.label}: " + _tasks_line(report.in_period_tasks))
    if report.no_due_high:
        lines.append("• High-priority (no date): " + _tasks_line(report.no_due_high))
    if "couldn't reach your calendar" not in report.notes:
        if report.calendar_events:
            lines.append(f"• Calendar: {len(report.calendar_events)} — " + _events_line(report.calendar_events))
        else:
            lines.append(f"• Calendar: nothing scheduled {p.label}.")
    if report.approvals_total:
        extra = f" ({len(report.approvals_expiring)} expiring {p.label})" if report.approvals_expiring else ""
        lines.append(f"• Approvals: {report.approvals_total} awaiting your decision{extra}.")
    if report.ahead:
        lines.append("• Worth knowing ahead: " + _tasks_line(report.ahead))
    if report.timezone_fallback:
        lines.append(f"(Using {report.timezone}, {h} — set your timezone for accurate periods.)")
    for note in report.notes:
        lines.append(f"(Heads up — {note}.)")
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# The tool.                                                                    #
# --------------------------------------------------------------------------- #
async def readiness_check(period: str = "today") -> str:
    """Assess readiness for a period keyword — unifies tasks, approvals, calendar."""
    period = (period or "").strip().lower()
    if period not in PERIOD_KEYWORDS:
        return (
            "I can check: today, tomorrow, this_week, this_weekend, next_week, or "
            "this_month — which would you like, Sir?"
        )
    report = await gather_readiness(period, datetime.now(UTC))
    if report is None:  # unreachable post-validation, but never raise
        return "I couldn't resolve that period, Sir."
    return format_report(report)


class _ReadinessArgs(BaseModel):
    period: str = Field(
        default="today",
        description=(
            "The time window to assess — one of: today, tomorrow, this_week, "
            "this_weekend, next_week, this_month."
        ),
    )


def register() -> None:
    tool_registry.register(
        name="readiness_check",
        handler=readiness_check,
        description=(
            "Assess whether the master is 'all set' for a time PERIOD — unifies their "
            "open tasks (overdue + due in-period), pending approvals, and calendar over "
            "the period, plus a heads-up on important items just ahead, and a verdict. "
            "period is one of: today, tomorrow, this_week, this_weekend, next_week, "
            "this_month. "
            "Use for: 'am I all set for this week', 'what have I got on tomorrow', "
            "'anything I'm forgetting', 'am I ready for the weekend', 'how's next week "
            "looking'. Does NOT add tasks (use task_add) or read raw calendar (calendar_read)."
        ),
        args_schema=_ReadinessArgs,
        capability="Tell you whether you're all set — the tasks, emails, and events needing your attention.",
    )
