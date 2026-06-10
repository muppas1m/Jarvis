"""Google Calendar tool — read events + create new events.

Follows the registry pattern from Task 1.11: Pydantic args schema, async handler,
register() function called by `register_all_tools()`.
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


# ---------- Credentials helper ----------
def _build_credentials() -> Credentials:
    return Credentials(
        token=None,
        refresh_token=settings.GOOGLE_REFRESH_TOKEN,
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=["https://www.googleapis.com/auth/calendar"],
    )


# ---------- Handlers ----------
async def calendar_read(days_ahead: int = 7, max_results: int = 20) -> str:
    """Fetch upcoming events from the master's primary calendar."""
    creds = _build_credentials()
    service = build("calendar", "v3", credentials=creds, cache_discovery=False)

    now = datetime.now(timezone.utc)
    time_min = now.isoformat()
    time_max = (now + timedelta(days=days_ahead)).isoformat()

    events_result = service.events().list(
        calendarId="primary",
        timeMin=time_min,
        timeMax=time_max,
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

    Note: this tool's safety level is APPROVE (see Task 1.9 / safety.py),
    so the agent must request approval before execution.
    """
    creds = _build_credentials()
    service = build("calendar", "v3", credentials=creds, cache_discovery=False)

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

    return f"Created event '{title}'. View: {event.get('htmlLink', '(no link)')}"


# ---------- Registration ----------
def register():
    tool_registry.register(
        name="calendar_read",
        handler=calendar_read,
        description=(
            "Read upcoming events from the master's Google Calendar — what's "
            "scheduled, meetings, what's coming up. "
            "Does NOT detect conflicts or compute free/busy availability, does NOT "
            "normalize timezones (event times come back as Google stores them), and "
            "does NOT modify anything — to add an event use calendar_create. If asked "
            "about availability, read the events and reason over the times yourself; "
            "don't claim you 'checked for conflicts' — the tool doesn't. "
            "Use for: 'what's on my calendar', 'what meetings this week', 'am I free "
            "Thursday afternoon', 'what's coming up'. "
            "Returns a flat list (title, start→end, location, attendees)."
        ),
        args_schema=CalendarReadArgs,
    )
    tool_registry.register(
        name="calendar_create",
        handler=calendar_create,
        description=(
            "Create a new event on the master's Google Calendar. Requires master "
            "approval before it executes. "
            "Does NOT add a Google Meet / video link, does NOT detect conflicts with "
            "existing events (browse first with calendar_read), and returns only a "
            "view link — NOT a reusable event_id for later edits. Provide start/end "
            "as ISO-8601 with a timezone offset; the tool does not infer or normalize "
            "timezones. "
            "Use for: 'schedule a 30-min sync with alice@example.com tomorrow at 2pm', "
            "'book a dentist appointment Friday morning', 'set up a team standup with "
            "the team'. "
            "To browse or check existing events first, use calendar_read."
        ),
        args_schema=CalendarCreateArgs,
    )
