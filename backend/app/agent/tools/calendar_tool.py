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
from datetime import datetime, timezone, timedelta
from pydantic import BaseModel, Field
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app.config import settings
from app.agent.tools.registry import tool_registry
import structlog

logger = structlog.get_logger()


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
    service = _service()

    now = datetime.now(timezone.utc)
    events_result = service.events().list(
        calendarId="primary",
        timeMin=now.isoformat(),
        timeMax=(now + timedelta(days=days_ahead)).isoformat(),
        maxResults=max_results,
        singleEvents=True,
        orderBy="startTime",
    ).execute()

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
    service = _service()

    body = {
        "summary": title,
        "description": description,
        "location": location,
        "start": {"dateTime": start_iso},
        "end": {"dateTime": end_iso},
    }
    if attendees:
        body["attendees"] = [{"email": a} for a in attendees]

    event = service.events().insert(
        calendarId="primary",
        body=body,
        sendUpdates="all" if attendees else "none",
    ).execute()

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

    event = _service().events().patch(
        calendarId="primary", eventId=event_id, body=body,
    ).execute()
    return (
        f"Updated event '{event.get('summary', '(untitled)')}' "
        f"(event_id: {event['id']}). View: {event.get('htmlLink', '(no link)')}"
    )


async def calendar_delete(event_id: str) -> str:
    """Delete an event by id. Safety level APPROVE.

    Fetches the title first so the confirmation names what was removed."""
    service = _service()
    try:
        ev = service.events().get(calendarId="primary", eventId=event_id).execute()
        title = ev.get("summary", "(untitled)")
    except Exception:  # noqa: BLE001 — title is cosmetic; proceed to delete
        title = "(unknown)"
    service.events().delete(calendarId="primary", eventId=event_id).execute()
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
    try:
        res = _service().events().list(
            calendarId="primary",
            timeMin=start_iso,
            timeMax=end_iso,
            singleEvents=True,
            orderBy="startTime",
            maxResults=10,
        ).execute()
        items = res.get("items", [])
    except Exception as exc:  # noqa: BLE001
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
            "or calendar_delete to change or remove it. "
            "Use for: 'what's on my calendar', 'what meetings this week', 'am I free "
            "Thursday afternoon', 'what's coming up'. "
            "Returns a flat list (title, start→end, location, attendees, event_id)."
        ),
        args_schema=CalendarReadArgs,
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
    )
