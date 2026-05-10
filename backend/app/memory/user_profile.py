"""
Tier 5 — Master's profile.

Split into two slices:

  always_on   — small dict joined into every system prompt. Stuff that affects
                tone or routing on every turn: timezone, language,
                communication_style.
  on_demand   — bigger sections retrieved only when the current message
                seems relevant: relationships, routines, news_topics, long
                preference lists. The MemoryManager indexes these into Mem0
                so semantic search surfaces them naturally.

The single-row design (`limit(1)`) is intentional — Jarvis has exactly one
master. Multi-tenant comes later, if ever.
"""
from typing import Any

from sqlalchemy import select

from app.db.engine import async_session
from app.db.models import UserProfile


class UserProfileManager:
    """CRUD over the single UserProfile row."""

    async def get_always_on(self) -> dict[str, Any]:
        """Return the always-on slice. Never returns None — falls back to a
        minimal default so prompt builders don't need to handle missing data."""
        async with async_session() as session:
            result = await session.execute(select(UserProfile).limit(1))
            profile = result.scalar_one_or_none()
            if profile is None:
                return {"name": "Master", "always_on": {}}
            return {
                "name": profile.name,
                "always_on": dict(profile.always_on or {}),
            }

    async def get_on_demand(self, key: str) -> Any:
        """Read one on-demand section by key (e.g. 'news_topics')."""
        async with async_session() as session:
            result = await session.execute(select(UserProfile).limit(1))
            profile = result.scalar_one_or_none()
            if profile is None:
                return None
            return (profile.on_demand or {}).get(key)

    async def get_full(self) -> dict[str, Any]:
        """Whole profile. Used by consolidation jobs and the dashboard, NOT by
        the agent prompt path."""
        async with async_session() as session:
            result = await session.execute(select(UserProfile).limit(1))
            profile = result.scalar_one_or_none()
            if profile is None:
                return {"name": "Master", "always_on": {}, "on_demand": {}}
            return {
                "name": profile.name,
                "always_on": dict(profile.always_on or {}),
                "on_demand": dict(profile.on_demand or {}),
            }

    async def update_always_on(self, updates: dict[str, Any]) -> None:
        """Merge updates into always_on. Use sparingly — these go in every prompt."""
        async with async_session() as session:
            result = await session.execute(select(UserProfile).limit(1))
            profile = result.scalar_one_or_none()
            if profile is None:
                profile = UserProfile(name="Master", always_on={}, on_demand={})
                session.add(profile)
                await session.flush()   # ensure profile.always_on is bound before we mutate
            current = dict(profile.always_on or {})
            current.update(updates)
            profile.always_on = current
            await session.commit()

    async def update_on_demand(self, key: str, value: Any) -> None:
        """Set a single on-demand section by key."""
        async with async_session() as session:
            result = await session.execute(select(UserProfile).limit(1))
            profile = result.scalar_one_or_none()
            if profile is None:
                profile = UserProfile(name="Master", always_on={}, on_demand={})
                session.add(profile)
                await session.flush()
            current = dict(profile.on_demand or {})
            current[key] = value
            profile.on_demand = current
            await session.commit()

    async def set_name(self, name: str) -> None:
        """Update the master's display name."""
        async with async_session() as session:
            result = await session.execute(select(UserProfile).limit(1))
            profile = result.scalar_one_or_none()
            if profile is None:
                profile = UserProfile(name=name, always_on={}, on_demand={})
                session.add(profile)
            else:
                profile.name = name
            await session.commit()
