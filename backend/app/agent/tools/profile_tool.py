"""B1-TZ (R2) — the ask-once-then-persist timezone capture."""
from __future__ import annotations

from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field
from sqlalchemy import update

from app.agent.tools.registry import tool_registry
from app.config import settings
from app.db.engine import async_session
from app.db.models import UserProfile
from app.utils.logging import get_logger

logger = get_logger(__name__)


async def _persist_timezone(tz: str) -> None:
    async with async_session() as session:
        await session.execute(update(UserProfile).values(timezone=tz))
        await session.commit()


async def set_timezone(timezone: str) -> str:
    """Persist the master's timezone to the first-class profile column (validated)."""
    h = settings.MASTER_HONORIFIC
    candidate = (timezone or "").strip()
    try:
        ZoneInfo(candidate)
    except Exception:  # noqa: BLE001 — an invalid name is said plainly, never stored
        return (f"I didn't recognize '{candidate}' as a timezone, {h} — an IANA name like "
                f"America/New_York works.")
    await _persist_timezone(candidate)
    # rebind THIS turn so times render right immediately (the var is ours in this context)
    from app.agent.master_tz import _master_tz
    _master_tz.set((candidate, False))
    logger.info("profile_timezone_set", tz=candidate)
    return f"Done, {h} — your timezone is set to {candidate}; times will show your wall clock."


class _SetTimezoneArgs(BaseModel):
    timezone: str = Field(description="IANA timezone name, e.g. America/New_York")


def register() -> None:
    tool_registry.register(
        name="set_timezone",
        handler=set_timezone,
        description=(
            "Persist the master's timezone (IANA name, e.g. America/New_York) to the profile. "
            "Call when the master states their timezone or location for times — and if a time "
            "is being discussed while the timezone is unset (times showing 'UTC'), ask ONCE for "
            "it, then call this with the answer."
        ),
        args_schema=_SetTimezoneArgs,
    )
