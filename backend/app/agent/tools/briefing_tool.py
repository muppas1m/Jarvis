"""
Briefing scope behaviors + the conversational tool (Phase 5.2).

Maps a scope keyword to a window over the 5.1 primitive + an advance rule:

  scope       window (UTC instants)              advances HWM?
  ----------  ---------------------------------  -------------
  latest      (HWM, now]   (NULL HWM → now−24h)   YES → now
  today       [today-start, now]   (local)        no   (+ earlier-catch-up offer)
  yesterday   [yesterday-start, yesterday-end]    no
  tomorrow    — nothing —                          no   ("I'll watch, Sir.")

The window/advance logic is PURE with `now` injected (`resolve_scope`), heavily
unit-tested per scope. Two boundary notes:
  - The 5.1 primitive is (start, end]; for the INCLUSIVE day-scopes (today/yesterday)
    the passed `start` is `local_midnight − 1µs` so a midnight-exact item isn't dropped.
  - NULL HWM (first run) floors the `latest` window at `now − 24h` (don't brief
    "everything ever"), then advances.

ADVANCE-ON-RETURN (see the step report): `latest` advances the HWM inside the tool,
before the agent narrates. The residual: if the turn fails after this returns but
before narration, the (old-HWM, now] items won't re-appear under "latest" — but they
remain in briefing_items and are recallable by date ("today's"/"yesterday's", which
don't advance). Acceptable for informational FYIs; the no-loss alternative needs a
turn-completion hook the tool can't observe.

briefing(scope) is SAFE (a read + an internal HWM advance — no external side effect);
`scope` is a plain str validated in the handler (open-weights convention — no Literal).
"""
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from app.agent.briefing_state import mark_briefed
from app.agent.tools.calendar_tool import _resolve_timezone
from app.agent.tools.registry import tool_registry
from app.briefing import DigestWindow, digest_window, read_hwm
from app.config import settings

_SCOPES = ("latest", "today", "yesterday", "tomorrow")
_LATEST_ALIASES = {"catch_up", "catch up", "catchup", "new", "whats_new", "what's new"}
_NULL_HWM_FLOOR_HOURS = 24


@dataclass(frozen=True)
class ScopeWindow:
    scope: str
    start: datetime              # the (start, end] lower bound to pass (epsilon-adjusted for day scopes)
    end: datetime
    advances: bool
    earlier_start: datetime | None = None  # "today": earlier-catch-up window lower bound
    earlier_end: datetime | None = None     # = today-start


def _local_midnight_utc(d, zone: ZoneInfo) -> datetime:
    return datetime.combine(d, time.min, zone).astimezone(UTC)


def resolve_scope(scope: str, hwm: datetime | None, now: datetime, tz: str) -> ScopeWindow | None:
    """Pure: scope → window + advance rule, in `tz`, relative to INJECTED `now` and
    the current `hwm`. None for tomorrow/unknown (the caller handles those)."""
    zone = ZoneInfo(tz)
    today = now.astimezone(zone).date()
    eps = timedelta(microseconds=1)
    if scope == "latest":
        start = hwm if hwm is not None else (now - timedelta(hours=_NULL_HWM_FLOOR_HOURS))
        return ScopeWindow("latest", start, now, advances=True)  # (HWM, now] is naturally exclusive at HWM
    if scope == "today":
        today_start = _local_midnight_utc(today, zone)
        effective_hwm = hwm if hwm is not None else (now - timedelta(hours=_NULL_HWM_FLOOR_HOURS))
        earlier = effective_hwm if effective_hwm < today_start else None
        return ScopeWindow(
            "today", today_start - eps, now, advances=False,
            earlier_start=earlier, earlier_end=(today_start if earlier is not None else None),
        )
    if scope == "yesterday":
        today_start = _local_midnight_utc(today, zone)
        y_start = _local_midnight_utc(today - timedelta(days=1), zone)
        # End at today_start − eps so a today-midnight-exact item belongs to TODAY
        # only — the (start, end] primitive is inclusive at end, so a plain today_start
        # would double-attribute it to both yesterday and today.
        return ScopeWindow("yesterday", y_start - eps, today_start - eps, advances=False)
    return None


# --------------------------------------------------------------------------- #
# Narration (pure).                                                           #
# --------------------------------------------------------------------------- #
_PRESENT = {
    "latest": "Here's the latest, {h} — {n} new:",
    "today": "Here's today, {h} — {n}:",
    "yesterday": "Yesterday, {h} — {n}:",
}
_EMPTY = {
    "latest": "You're all caught up, {h} — nothing new since you last heard.",
    "today": "Nothing's come in today, {h}.",
    "yesterday": "Nothing came in yesterday, {h}.",
}


def _render_item(it) -> str:
    tag = f"[{it.urgency}] " if getattr(it, "urgency", None) and it.urgency != "none" else ""
    src = f" — {it.source}" if getattr(it, "source", None) else ""
    return f"  • {tag}{it.title or '(no subject)'}{src}"


def format_digest(sw: ScopeWindow, win: DigestWindow, *, fallback: bool, earlier_count: int) -> str:
    h = settings.MASTER_HONORIFIC
    if win.total == 0:
        body = _EMPTY[sw.scope].format(h=h)
    else:
        parts = [_PRESENT[sw.scope].format(h=h, n=win.total)]
        multi = len(win.days) > 1  # day headers only for a multi-day (missed-days) catch-up
        for d in win.days:
            if multi:
                parts.append(d.day.strftime("%A %Y-%m-%d:"))
            parts.extend(_render_item(it) for it in d.items)
        body = "\n".join(parts)
    extras = []
    if earlier_count > 0:
        extras.append(
            f"You've also got {earlier_count} from before today you haven't heard — "
            f"shall I catch you up, {h}?"
        )
    if fallback:
        extras.append(f"(Using {win.timezone}, {h} — set your timezone for accurate day boundaries.)")
    return body + ("\n" + "\n".join(extras) if extras else "")


# --------------------------------------------------------------------------- #
# The tool.                                                                    #
# --------------------------------------------------------------------------- #
async def _earlier_unheard(start: datetime, end: datetime, tz: str) -> int:
    """Count of pre-today unheard items — the earlier-catch-up offer fires iff > 0."""
    return (await digest_window(start, end, tz=tz)).total


def _normalize(scope: str) -> str:
    scope = (scope or "").strip().lower()
    return "latest" if scope in _LATEST_ALIASES else scope


async def briefing(scope: str = "latest") -> str:
    """The read-state briefing — 'what's the latest' and scoped recalls."""
    h = settings.MASTER_HONORIFIC
    scope = _normalize(scope)
    if scope == "tomorrow":
        return f"Nothing yet, {h} — I'll keep watch and bring it to you when it lands."
    if scope not in _SCOPES:
        return (
            "I can give you: latest (what's new), today, yesterday, or tomorrow — "
            "which would you like, Sir?"
        )

    now = datetime.now(UTC)
    tz_name, fallback = await _resolve_timezone("")
    sw = resolve_scope(scope, await read_hwm(), now, tz_name)
    win = await digest_window(sw.start, sw.end, tz=tz_name)
    earlier = (
        await _earlier_unheard(sw.earlier_start, sw.earlier_end, tz_name)
        if sw.earlier_start is not None else 0
    )
    text = format_digest(sw, win, fallback=fallback, earlier_count=earlier)
    if sw.advances:
        # The single 'brief was delivered' seam — advance the HWM AND stamp last_briefed_at
        # together (briefing_state.mark_briefed). Advance-on-return (see module docstring for
        # the residual); the cooldown reads the stamp set here.
        await mark_briefed(now)
    return text


class _BriefingArgs(BaseModel):
    scope: str = Field(
        default="latest",
        description=(
            "What to brief — one of: latest (what's new since the master last heard), "
            "today, yesterday, tomorrow."
        ),
    )


async def deliver_briefing() -> str:
    """SIGNAL ONLY (Phase 5.4) — the agent calls this to tell the SYSTEM the master is
    checking in and a pending briefing should be presented. The system fetches and attaches
    the actual brief to the reply (text + voice); the agent NEVER writes the briefing itself.
    Returns a confirmation so the agent simply finishes its natural greeting."""
    return "Acknowledged — presenting the master's briefing now."


class _DeliverBriefingArgs(BaseModel):
    pass  # signal only — no arguments


def register() -> None:
    tool_registry.register(
        name="briefing",
        handler=briefing,
        description=(
            "Brief the master on incoming items (FYI emails today; news later) for a "
            "scope. 'latest' = everything new since they last heard, and marks it heard; "
            "'today' / 'yesterday' = a scoped recall by day (does NOT mark heard); "
            "'tomorrow' = nothing yet. "
            "Use for: 'what's the latest', 'what's new', 'catch me up', 'anything I "
            "missed', 'what came in today', 'what did I get yesterday'. "
            "Does NOT check tasks/calendar/approvals (use readiness_check for 'am I all set')."
        ),
        args_schema=_BriefingArgs,
        capability="Brief you on what's new (FYI emails today; news later).",
    )
    tool_registry.register(
        name="deliver_briefing",
        handler=deliver_briefing,
        description=(
            "Signal that the master is CHECKING IN and their pending briefing should be "
            "presented. Call this (no arguments) ONLY when the <check_in> context says a "
            "briefing is pending AND the master's message is a check-in/greeting ('good "
            "morning', 'hey', 'what's up', 'what's new', 'how are things'). The SYSTEM then "
            "attaches the briefing to your reply — you do NOT write the briefing yourself. "
            "Do NOT call it for a specific request (the system offers the briefing as a tail), "
            "and never to deliver a scoped recall (use 'briefing' for 'what came in today')."
        ),
        args_schema=_DeliverBriefingArgs,
    )
