"""
Authenticated 24h activity feed (4.C.3) — a dignified, master-facing view of
Jarvis's real work, NOT a debug log. Aggregates real records — tool actions
(audit_trail), inbox triage (email_logs), and things remembered (mem0_memories)
— into a 24h summary (friendly counts) + a chronological feed (recent, newest
first). Master-facing phrasing is the point: "Remembered that…", "Sent an email
to…" — never "wrote to Mem0", a table name, or a raw tool id. Real entries only.

Each source is queried fail-graceful: one source erroring drops only its rows,
never the whole feed.
"""
import re
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select, text

from app.db.engine import async_session
from app.db.models import AuditTrail, EmailLog, SystemAlert
from app.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["activity"])

_FEED_LIMIT = 30
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

# tool_name → (glyph, friendly phrase). None = internal noise, omit from the feed
# (memory_search fires every turn; it's not something the master cares to see).
_TOOL_MAP: dict[str, tuple[str, str] | None] = {
    "email_send": ("✉", "Sent an email"),
    "gmail_send": ("✉", "Sent an email"),  # legacy audit rows (pre-provider-rename)
    "calendar_create": ("📅", "Added an event to your calendar"),
    "calendar_update": ("📅", "Updated a calendar event"),
    "calendar_delete": ("📅", "Removed a calendar event"),
    "calendar_read": ("📅", "Checked your calendar"),
    "document_search": ("📄", "Searched your documents"),
    "email_history_search": ("✉", "Reviewed your inbox"),
    "memory_search": None,
}


def _friendly_tool(tool_name: str, input_summary: str | None) -> tuple[str, str] | None:
    """Map one tool execution to (glyph, phrase), or None to omit."""
    entry = _TOOL_MAP.get(tool_name)
    if entry is None:
        # Unknown tool OR an explicitly-omitted one. Omit silently (never leak
        # the raw tool name into a master-facing feed).
        return None
    glyph, phrase = entry
    if tool_name in ("email_send", "gmail_send") and input_summary:
        m = _EMAIL_RE.search(input_summary)
        if m:
            phrase = f"Sent an email to {m.group(0)}"
    return glyph, phrase


def _friendly_email(sender: str | None) -> str:
    if sender:
        m = _EMAIL_RE.search(sender)
        who = m.group(0) if m else sender.strip()
        return f"New email from {who}"
    return "A new email arrived"


def _friendly_memory(data: str) -> str:
    """Mem0 stores facts in the third person ("User's name is…"); render them
    back to the master in the second person, dignified."""
    s = data.strip()
    s = re.sub(r"^(the )?user's ", "your ", s, flags=re.IGNORECASE)
    s = re.sub(r"^(the )?user is ", "you're ", s, flags=re.IGNORECASE)
    s = re.sub(r"^(the )?user has ", "you have ", s, flags=re.IGNORECASE)
    s = re.sub(r"^(the )?user ", "you ", s, flags=re.IGNORECASE)
    return f"Remembered: {s}"


def _friendly_alert(text: str) -> str:
    """A '🚨 SYSTEM' alert, lightly cleaned — these are WARNINGS the master should
    grasp at a glance, so we keep the substance and only strip markdown noise +
    collapse whitespace (don't over-sanitize a warning into meaninglessness)."""
    s = re.sub(r"[`*_]+", "", text or "")
    return re.sub(r"\s+", " ", s).strip()


class ActivityItem(BaseModel):
    glyph: str
    text: str
    when: str  # ISO-8601
    kind: str  # action | email | memory | alert


class ActivitySummaryRow(BaseModel):
    glyph: str
    label: str
    count: int


class ActivityResponse(BaseModel):
    summary: list[ActivitySummaryRow]
    feed: list[ActivityItem]


def _parse(ts: str | None) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


@router.get("/activity", response_model=ActivityResponse)
async def activity() -> ActivityResponse:
    since = datetime.now(UTC) - timedelta(hours=24)
    collected: list[tuple[datetime, ActivityItem]] = []
    counts = {"action": 0, "email": 0, "memory": 0, "alert": 0}

    async with async_session() as session:
        # 1) tool actions — the richest source (audit_trail), successes only.
        try:
            rows = (
                await session.execute(
                    select(AuditTrail)
                    .where(AuditTrail.executed_at > since, AuditTrail.success.is_(True))
                    .order_by(AuditTrail.executed_at.desc())
                    .limit(100)
                )
            ).scalars().all()
            for r in rows:
                m = _friendly_tool(r.tool_name, r.input_summary)
                if not m:
                    continue
                counts["action"] += 1
                collected.append(
                    (r.executed_at, ActivityItem(glyph=m[0], text=m[1], when=r.executed_at.isoformat(), kind="action"))
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("activity_audit_failed", error=str(exc))

        # 2) inbox triage (email_logs).
        try:
            rows = (
                await session.execute(
                    select(EmailLog)
                    .where(EmailLog.created_at > since)
                    .order_by(EmailLog.created_at.desc())
                    .limit(100)
                )
            ).scalars().all()
            for r in rows:
                counts["email"] += 1
                collected.append(
                    (r.created_at, ActivityItem(glyph="✉", text=_friendly_email(r.sender), when=r.created_at.isoformat(), kind="email"))
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("activity_email_failed", error=str(exc))

        # 3) things remembered (Mem0's pgvector table — timestamp lives in payload).
        try:
            res = await session.execute(
                text(
                    "SELECT payload->>'data' AS data, payload->>'created_at' AS created_at "
                    "FROM mem0_memories "
                    "WHERE (payload->>'created_at') IS NOT NULL "
                    "AND (payload->>'created_at')::timestamptz > :since "
                    "ORDER BY (payload->>'created_at')::timestamptz DESC LIMIT 100"
                ),
                {"since": since},
            )
            for data, created in res:
                dt = _parse(created)
                if not data or dt is None:
                    continue
                counts["memory"] += 1
                collected.append(
                    (dt, ActivityItem(glyph="◆", text=_friendly_memory(data), when=dt.isoformat(), kind="memory"))
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("activity_memory_failed", error=str(exc))

        # 4) system alerts (warnings) — the only source that's a WARNING, not a
        #    calm "did X". Rendered to stand out (kind="alert" → amber treatment).
        try:
            rows = (
                await session.execute(
                    select(SystemAlert)
                    .where(SystemAlert.created_at > since)
                    .order_by(SystemAlert.created_at.desc())
                    .limit(100)
                )
            ).scalars().all()
            for r in rows:
                counts["alert"] += 1
                collected.append(
                    (r.created_at, ActivityItem(glyph="⚠", text=_friendly_alert(r.text), when=r.created_at.isoformat(), kind="alert"))
                )
        except Exception as exc:  # noqa: BLE001
            logger.warning("activity_alerts_failed", error=str(exc))

    collected.sort(key=lambda pair: pair[0], reverse=True)
    feed = [item for _, item in collected[:_FEED_LIMIT]]

    summary: list[ActivitySummaryRow] = []
    if counts["alert"]:
        summary.append(ActivitySummaryRow(glyph="⚠", label="System alerts", count=counts["alert"]))
    if counts["email"]:
        summary.append(ActivitySummaryRow(glyph="✉", label="Emails triaged", count=counts["email"]))
    if counts["memory"]:
        summary.append(ActivitySummaryRow(glyph="◆", label="Things remembered", count=counts["memory"]))
    if counts["action"]:
        summary.append(ActivitySummaryRow(glyph="⚡", label="Actions taken", count=counts["action"]))

    return ActivityResponse(summary=summary, feed=feed)
