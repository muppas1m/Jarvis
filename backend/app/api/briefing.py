"""HUD briefing surface — the latest proactive morning brief, for the dashboard.

The 7am morning brief is Celery-driven (no active stream), so the HUD surfaces it via
persist-then-poll: the task persists the structured digest to ``morning_briefs``; this
endpoint returns the most recent brief within a freshness window (else ``null``). The
HUD BriefingCard renders ``payload`` structurally — day sections, urgency chips, and
untrusted email fields (title/source/preview) as ESCAPED text — so there's no raw-HTML
or markdown injection surface. Telegram delivery is unchanged + independent.

Instant push (the moment the brief is built) is a separately-tracked future feature —
this is the persist-then-poll surface only.
"""
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select

from app.config import settings
from app.db.engine import async_session
from app.db.models import MorningBrief
from app.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["briefing"])


class BriefItem(BaseModel):
    title: str = ""
    source: str = ""
    preview: str = ""
    urgency: str = "none"
    kind: str = "email"
    occurred_at: str = ""


class BriefDay(BaseModel):
    day: str
    items: list[BriefItem] = []


class Brief(BaseModel):
    created_at: str
    empty: bool = True
    total: int = 0
    timezone: str = ""
    error: bool = False
    days: list[BriefDay] = []


class BriefingLatestResponse(BaseModel):
    """`brief` is null when there's no brief within the freshness window — the HUD
    renders nothing (no stale brief lingers)."""
    brief: Brief | None = None


@router.get("/briefing/latest", response_model=BriefingLatestResponse)
async def briefing_latest() -> BriefingLatestResponse:
    """The most recent morning brief created within BRIEFING_HUD_TTL_HOURS, or null.

    Fail-graceful: a read error returns ``brief=null`` (the HUD shows nothing) rather
    than 500-ing the dashboard. ``payload`` is rendered structurally client-side."""
    cutoff = datetime.now(UTC) - timedelta(hours=settings.BRIEFING_HUD_TTL_HOURS)
    try:
        async with async_session() as session:
            row = (await session.execute(
                select(MorningBrief)
                .where(MorningBrief.created_at > cutoff)
                .order_by(MorningBrief.created_at.desc())
                .limit(1)
            )).scalar_one_or_none()
    except Exception as exc:  # noqa: BLE001 — dashboard read; degrade to "no brief"
        logger.warning("briefing_latest_read_failed", error=str(exc))
        return BriefingLatestResponse(brief=None)

    if row is None:
        return BriefingLatestResponse(brief=None)

    payload = dict(row.payload or {})
    return BriefingLatestResponse(
        brief=Brief(
            created_at=row.created_at.isoformat(),
            empty=bool(payload.get("empty", True)),
            total=int(payload.get("total", 0) or 0),
            timezone=str(payload.get("timezone", "") or ""),
            error=bool(payload.get("error", False)),
            days=[
                BriefDay(
                    day=str(d.get("day", "")),
                    items=[
                        BriefItem(**{k: v for k, v in it.items() if k in BriefItem.model_fields})
                        for it in (d.get("items") or [])
                    ],
                )
                for d in (payload.get("days") or [])
            ],
        )
    )
