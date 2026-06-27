"""Google Calendar tool — read, create, update, delete events (+ conflict check).

Follows the registry pattern from Task 1.11: Pydantic args schema, async handler,
register() function called by `register_all_tools()`.

P5b additions:
  - `calendar_read` / `calendar_create` now surface the Google ``event_id`` so the
    agent can target an event for update/delete (previously read returned times
    only and create returned just an htmlLink).
  - `calendar_update` / `calendar_delete` (APPROVE-tier) — edit/remove an existing
    event by id. Partial update: empty-string fields are left unchanged (flat
    types + empty-string sentinels for open-weights tool-call compatibility).
  - `calendar_conflict_warning` — names existing events overlapping a requested
    slot (reuses events.list, not the raw free/busy endpoint, so the warning says
    *what* it overlaps). The tool_executor APPROVE branch appends this to the
    Approve/Reject prompt for calendar_create — a soft warning, not a hard block;
    the master decides per-event.
"""
import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import structlog
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from pydantic import BaseModel, Field

from app.agent.tools.registry import tool_registry
from app.config import settings

logger = structlog.get_logger()

_PERIOD_MAX_RESULTS = 250  # Google's page max; a readiness window wants them all


# ---------- Args schemas ----------
class CalendarReadArgs(BaseModel):
    days_ahead: int = Field(
        default=7,
        description="Number of days into the future to fetch events for. Default 7.",
    )
    max_results: int = Field(default=20, description="Max events to return.")


class CalendarCreateArgs(BaseModel):
    title: str = Field(description="Event title")
    start_iso: str = Field(description="Start time as ISO-8601 string (with timezone offset)")
    end_iso: str = Field(description="End time as ISO-8601 string (with timezone offset)")
    description: str = Field(default="", description="Event description / notes")
    location: str = Field(default="", description="Physical or virtual location")
    attendees: list[str] = Field(
        default_factory=list,
        description="Email addresses of attendees (Calendar will send invites)",
    )


class CalendarUpdateArgs(BaseModel):
    event_id: str = Field(description="The event_id from calendar_read or calendar_create.")
    title: str = Field(default="", description="New title, or empty to leave unchanged.")
    start_iso: str = Field(default="", description="New start (ISO-8601 with offset), or empty to leave unchanged.")
    end_iso: str = Field(default="", description="New end (ISO-8601 with offset), or empty to leave unchanged.")
    description: str = Field(default="", description="New description, or empty to leave unchanged.")
    location: str = Field(default="", description="New location, or empty to leave unchanged.")


class CalendarDeleteArgs(BaseModel):
    event_id: str = Field(description="The event_id of the event to delete (from calendar_read).")


# ---------- Credentials / service helpers ----------
def _build_credentials() -> Credentials:
    return Credentials(
        token=None,
        refresh_token=settings.GOOGLE_REFRESH_TOKEN,
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/calendar"],
    )


def _service():
    return build("calendar", "v3", credentials=_build_credentials(), cache_discovery=False)


async def _blocking[T](fn: Callable[[], T], *, timeout: float | None = None) -> T:
    """Run a SYNCHRONOUS google-api-python-client call OFF the event loop AND
    bounded. The SDK is sync — a bare ``…execute()`` blocks the whole backend for
    the round-trip and a hung call would wedge it. Mirrors the Gmail adapter's
    ``_blocking`` idiom (to_thread + wait_for); ``fn`` builds the service AND
    executes inside the worker thread, so the OAuth ``build`` (discovery I/O) is
    off-loop too. BOTH the read paths (calendar_read + calendar_period) AND the
    APPROVE-tier write handlers (create/update/delete/conflict) route through here, so
    a hung Google call raises TimeoutError to the normal [ERROR] path instead of
    wedging the backend. The two fail-open paths — the conflict check and delete's
    cosmetic title fetch — catch that timeout and degrade gracefully (no warning /
    "(unknown)" title); the mutations themselves let it propagate."""
    return await asyncio.wait_for(
        asyncio.to_thread(fn),
        timeout=timeout if timeout is not None else settings.CALENDAR_TIMEOUT_S,
    )


def _fmt_time(iso: str, with_day: bool = True) -> str:
    """Compact local time for a warning line; falls back to the raw value.

    ``with_day`` carries the weekday on the range START only — the END drops it
    so a same-day slot reads "Sat 12:00–12:30", not "Sat 12:00–Sat 12:30"."""
    try:
        return datetime.fromisoformat(iso).strftime("%a %H:%M" if with_day else "%H:%M")
    except Exception:  # noqa: BLE001 — all-day events carry a date, not a datetime
        return iso


# ---------- Handlers ----------
async def calendar_read(days_ahead: int = 7, max_results: int = 20) -> str:
    """Fetch upcoming events from the master's primary calendar."""
    now = datetime.now(UTC)

    def _list():
        return _service().events().list(
            calendarId="primary",
            timeMin=now.isoformat(),
            timeMax=(now + timedelta(days=days_ahead)).isoformat(),
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        ).execute()

    events_result = await _blocking(_list)  # off-loop + bounded
    events = events_result.get("items", [])
    if not events:
        return f"No events scheduled in the next {days_ahead} days."

    lines = []
    for ev in events:
        start = ev["start"].get("dateTime", ev["start"].get("date"))
        end = ev["end"].get("dateTime", ev["end"].get("date"))
        title = ev.get("summary", "(no title)")
        location = ev.get("location", "")
        attendees = [a.get("email", "") for a in ev.get("attendees", [])]
        line = f"- [{start} → {end}] {title}"
        if location:
            line += f" @ {location}"
        if attendees:
            line += f" (attendees: {', '.join(attendees)})"
        # event_id is load-bearing for update/delete — surface it so the agent
        # can target this event later.
        line += f" (event_id: {ev['id']})"
        lines.append(line)
    return "Upcoming events:\n" + "\n".join(lines)


async def calendar_create(
    title: str,
    start_iso: str,
    end_iso: str,
    description: str = "",
    location: str = "",
    attendees: list[str] | None = None,
) -> str:
    """Create a new event on the master's primary calendar.

    Safety level APPROVE (safety.py), so the agent must request approval first.
    The approval prompt is enriched with a conflict warning by the tool_executor
    (see calendar_conflict_warning)."""
    body = {
        "summary": title,
        "description": description,
        "location": location,
        "start": {"dateTime": start_iso},
        "end": {"dateTime": end_iso},
    }
    if attendees:
        body["attendees"] = [{"email": a} for a in attendees]

    def _insert():
        return _service().events().insert(
            calendarId="primary",
            body=body,
            sendUpdates="all" if attendees else "none",
        ).execute()

    event = await _blocking(_insert)  # off-loop + bounded — a hung write → TimeoutError

    return (
        f"Created event '{title}' (event_id: {event['id']}). "
        f"View: {event.get('htmlLink', '(no link)')}"
    )


async def calendar_update(
    event_id: str,
    title: str = "",
    start_iso: str = "",
    end_iso: str = "",
    description: str = "",
    location: str = "",
) -> str:
    """Patch an existing event. Only non-empty fields change (partial update).

    Safety level APPROVE. Use the event_id from calendar_read/calendar_create."""
    body: dict = {}
    if title:
        body["summary"] = title
    if start_iso:
        body["start"] = {"dateTime": start_iso}
    if end_iso:
        body["end"] = {"dateTime": end_iso}
    if description:
        body["description"] = description
    if location:
        body["location"] = location
    if not body:
        return "No changes specified — nothing to update."

    def _patch():
        return _service().events().patch(
            calendarId="primary", eventId=event_id, body=body,
        ).execute()

    event = await _blocking(_patch)  # off-loop + bounded — a hung write → TimeoutError
    return (
        f"Updated event '{event.get('summary', '(untitled)')}' "
        f"(event_id: {event['id']}). View: {event.get('htmlLink', '(no link)')}"
    )


async def calendar_delete(event_id: str) -> str:
    """Delete an event by id. Safety level APPROVE.

    Fetches the title first so the confirmation names what was removed."""
    def _get():
        return _service().events().get(calendarId="primary", eventId=event_id).execute()

    try:
        ev = await _blocking(_get)  # bounded; a hung/failed get is cosmetic → fall back
        title = ev.get("summary", "(untitled)")
    except Exception:  # noqa: BLE001 — title is cosmetic; proceed to delete
        title = "(unknown)"

    def _delete():
        return _service().events().delete(calendarId="primary", eventId=event_id).execute()

    await _blocking(_delete)  # off-loop + bounded — a hung delete → TimeoutError, not a wedge
    return f"Deleted event '{title}' (event_id: {event_id})."


async def calendar_conflict_warning(start_iso: str, end_iso: str) -> str | None:
    """Return a named warning if existing events overlap ``[start_iso, end_iso]``.

    Reuses ``events.list`` (NOT the free/busy endpoint) so the warning can name
    *what* it overlaps. ``events.list(timeMin, timeMax)`` already returns exactly
    the intersecting events (end > timeMin AND start < timeMax), so no extra
    overlap math is needed.

    Fail-open: an unparseable slot or an API error returns None (no warning) —
    a check failure must never block the approval. The prompt separately forbids
    the agent from CLAIMING a conflict check it didn't run."""
    if not start_iso or not end_iso:
        return None
    def _list():
        return _service().events().list(
            calendarId="primary",
            timeMin=start_iso,
            timeMax=end_iso,
            singleEvents=True,
            orderBy="startTime",
            maxResults=10,
        ).execute()

    try:
        res = await _blocking(_list)  # off-loop + bounded; a timeout fails open (no warning)
        items = res.get("items", [])
    except Exception as exc:  # noqa: BLE001 — incl. TimeoutError; a check failure never blocks approval
        logger.warning("calendar_conflict_check_failed", error=str(exc))
        return None

    overlaps = []
    for ev in items:
        title = ev.get("summary", "(untitled)")
        es = ev["start"].get("dateTime", ev["start"].get("date"))
        ee = ev["end"].get("dateTime", ev["end"].get("date"))
        overlaps.append(f"{title} ({_fmt_time(es)}–{_fmt_time(ee, with_day=False)})")

    if not overlaps:
        return None
    if len(overlaps) == 1:
        return f"⚠️ Heads up — this overlaps an existing event: {overlaps[0]}."
    return "⚠️ Heads up — this overlaps existing events:\n" + "\n".join(
        f"  • {o}" for o in overlaps
    )


# ---------- Readiness: internal period read (4.2) — NOT an LLM tool ----------
@dataclass
class CalendarEvent:
    """One normalized calendar event for the readiness aggregator."""
    title: str
    start: str                  # ISO in the master's TZ (timed) or YYYY-MM-DD (all-day)
    end: str
    all_day: bool
    location: str
    attendees: list[str]
    event_id: str


@dataclass
class CalendarPeriodResult:
    """Events in a date range + the TZ they were resolved in. ``timezone_fallback``
    is True when the profile TZ was unset and the configured default was used — so
    the aggregator can SAY 'using UTC' rather than silently misplace events. ``ok``
    is False on a calendar failure (fail-soft; events empty, error set)."""
    events: list[CalendarEvent]
    timezone: str
    timezone_fallback: bool
    ok: bool = True
    error: str = ""


async def _resolve_timezone(tz: str) -> tuple[str, bool]:
    """Resolve the master's TZ — explicit arg → profile always_on['timezone'] →
    configured default (FLAGGED). Never silently UTC. Returns (tz_name, fallback)."""
    candidate = (tz or "").strip()
    if not candidate:
        try:
            from app.memory.manager import get_memory
            always_on = await get_memory().get_always_on()
            candidate = (always_on.get("timezone") or "").strip()
        except Exception as exc:  # noqa: BLE001 — TZ resolution must never raise
            logger.warning("calendar_tz_profile_read_failed", error=str(exc))
            candidate = ""
    fallback = False
    if not candidate:
        candidate, fallback = settings.DEFAULT_TIMEZONE, True
    try:
        ZoneInfo(candidate)
    except Exception:  # noqa: BLE001 — an invalid name falls back to the default
        logger.warning("calendar_tz_invalid", tz=candidate, default=settings.DEFAULT_TIMEZONE)
        candidate, fallback = settings.DEFAULT_TIMEZONE, True
        ZoneInfo(candidate)  # the configured default must be valid
    return candidate, fallback


def _to_tz(dt_iso: str, zone: ZoneInfo) -> str:
    try:
        return datetime.fromisoformat(dt_iso).astimezone(zone).isoformat()
    except Exception:  # noqa: BLE001 — leave an unparseable value raw
        return dt_iso


def _normalize_event(ev: dict, zone: ZoneInfo) -> CalendarEvent:
    s, e = ev.get("start", {}), ev.get("end", {})
    all_day = "dateTime" not in s  # Google: all-day → "date", timed → "dateTime"
    if all_day:
        start, end = s.get("date", ""), e.get("date", "")
    else:
        start, end = _to_tz(s.get("dateTime", ""), zone), _to_tz(e.get("dateTime", ""), zone)
    return CalendarEvent(
        title=ev.get("summary", "(no title)"),
        start=start, end=end, all_day=all_day,
        location=ev.get("location", ""),
        attendees=[a.get("email", "") for a in ev.get("attendees", [])],
        event_id=ev.get("id", ""),
    )


async def calendar_period(start: str, end: str, tz: str = "") -> CalendarPeriodResult:
    """INTERNAL (not an LLM tool) — the calendar input for readiness (4.3). Fetch
    events in the INCLUSIVE local-date range [start, end] (YYYY-MM-DD), normalized
    to the master's timezone.

    TZ correctness is the headline: the range boundaries are LOCAL midnight in the
    master's TZ converted to UTC (DST-safe via ZoneInfo), NOT UTC midnight — so an
    event late on the last local day lands in the right period. ``tz`` is resolved
    (arg → profile → flagged default) and returned, so the caller never assumes UTC."""
    tz_name, fallback = await _resolve_timezone(tz)
    zone = ZoneInfo(tz_name)
    try:
        start_d, end_d = date.fromisoformat(start), date.fromisoformat(end)
    except ValueError as exc:
        return CalendarPeriodResult([], tz_name, fallback, ok=False, error=f"bad date range: {exc}")

    # Local-midnight boundaries → UTC. timeMax is EXCLUSIVE, so use local midnight
    # of the day AFTER end → the whole end day is included.
    time_min = datetime.combine(start_d, time.min, zone).astimezone(UTC)
    time_max = datetime.combine(end_d + timedelta(days=1), time.min, zone).astimezone(UTC)

    def _list():
        return _service().events().list(
            calendarId="primary",
            timeMin=time_min.isoformat(),
            timeMax=time_max.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=_PERIOD_MAX_RESULTS,
        ).execute()

    try:
        raw = await _blocking(_list)
    except Exception as exc:  # noqa: BLE001 — fail-soft: readiness degrades, never errors
        logger.warning("calendar_period_failed", start=start, end=end, tz=tz_name, error=str(exc))
        return CalendarPeriodResult([], tz_name, fallback, ok=False, error=str(exc)[:200])

    events = [_normalize_event(ev, zone) for ev in raw.get("items", [])]
    return CalendarPeriodResult(events, tz_name, fallback, ok=True)


# ---------- Registration ----------
def register():
    tool_registry.register(
        name="calendar_read",
        handler=calendar_read,
        description=(
            "Read upcoming events from the master's Google Calendar — what's "
            "scheduled, meetings, what's coming up. "
            "Does NOT normalize timezones (event times come back as Google stores "
            "them). Each event includes its event_id — pass that to calendar_update "
            "or calendar_delete to change or remove it. The event_id is for YOUR "
            "internal use only: NEVER show raw event_ids in your reply to the "
            "master — summarize events cleanly (title, time, location). "
            "Use for: 'what's on my calendar', 'what meetings this week', 'am I free "
            "Thursday afternoon', 'what's coming up'. "
            "Returns a flat list (title, start→end, location, attendees, event_id)."
        ),
        args_schema=CalendarReadArgs,
        capability="Check your calendar and schedule.",
    )
    tool_registry.register(
        name="calendar_create",
        handler=calendar_create,
        description=(
            "Create a new event on the master's Google Calendar. Requires master "
            "approval before it executes — and the approval prompt automatically "
            "shows any existing events that overlap the requested slot, so DON'T "
            "claim you personally checked for conflicts; the master sees them. "
            "Does NOT add a Google Meet / video link. Provide start/end as ISO-8601 "
            "with a timezone offset; the tool does not infer or normalize timezones. "
            "Returns the new event_id (usable with calendar_update/delete). "
            "Use for: 'schedule a 30-min sync with alice@example.com tomorrow at 2pm', "
            "'book a dentist appointment Friday morning'."
        ),
        args_schema=CalendarCreateArgs,
        capability="Add a calendar event (pauses for your approval).",
    )
    tool_registry.register(
        name="calendar_update",
        handler=calendar_update,
        description=(
            "Update / reschedule an existing calendar event — change its title, "
            "time, description, or location. Requires master approval. You MUST have "
            "the event_id (from calendar_read or a prior calendar_create); if you "
            "don't, call calendar_read first to find it. Only the fields you provide "
            "change; leave the rest empty. This is how you 'rename', 'move', or "
            "'reschedule' an event — do NOT create a new event for that (it leaves a "
            "duplicate). Times are ISO-8601 with a timezone offset."
        ),
        args_schema=CalendarUpdateArgs,
        capability="Reschedule or rename a calendar event (pauses for your approval).",
    )
    tool_registry.register(
        name="calendar_delete",
        handler=calendar_delete,
        description=(
            "Delete / cancel an existing calendar event by event_id. Requires master "
            "approval. You MUST have the event_id (from calendar_read); if you don't, "
            "call calendar_read first to find the event. Use for 'cancel my dentist "
            "appointment', 'delete the duplicate Gym event'."
        ),
        args_schema=CalendarDeleteArgs,
        capability="Delete a calendar event (pauses for your approval).",
    )
