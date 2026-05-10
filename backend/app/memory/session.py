"""
Tier 2 — Session analytics view.

LangGraph's AsyncPostgresSaver owns the actual message history. This class
maintains the parallel `conversation_analytics` row that powers dashboard
queries (last activity, message count per thread, summary text) without
duplicating the message blobs themselves.

All writes happen at the channel boundary (whenever a NormalizedMessage
arrives). `get_recent_messages()` is a read-only adapter that pulls from the
checkpointer for analytics-only callers.
"""
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from app.db.engine import async_session
from app.db.models import ConversationAnalytics


class SessionManager:
    """Read-only analytics view over LangGraph thread state."""

    async def upsert_analytics(
        self,
        thread_id: str,
        platform: str,
        channel_user_id: str | None,
    ) -> None:
        """Called by the channel layer when a new message arrives. Creates
        the row on first sight, otherwise just bumps last_message_at and
        message_count."""
        async with async_session() as session:
            existing = await session.execute(
                select(ConversationAnalytics).where(
                    ConversationAnalytics.thread_id == thread_id
                )
            )
            row = existing.scalar_one_or_none()
            now = datetime.now(timezone.utc)
            if row is None:
                row = ConversationAnalytics(
                    thread_id=thread_id,
                    platform=platform,
                    channel_user_id=channel_user_id,
                    last_message_at=now,
                    message_count=1,
                )
                session.add(row)
            else:
                row.last_message_at = now
                row.message_count = (row.message_count or 0) + 1
            await session.commit()

    async def get_recent_messages(
        self,
        thread_id: str,
        checkpointer,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Pull recent messages from the LangGraph checkpoint state.

        Analytics-only adapter — the agent doesn't call this since its
        own state arrives via the graph automatically. Keeping it on the
        SessionManager keeps the dashboard from reaching into LangGraph
        internals directly.
        """
        config = {"configurable": {"thread_id": thread_id}}
        snapshot = await checkpointer.aget_tuple(config)
        if not snapshot or not snapshot.checkpoint:
            return []
        messages = snapshot.checkpoint.get("channel_values", {}).get("messages", [])
        return [
            {
                "role": getattr(m, "type", "unknown"),
                "content": getattr(m, "content", str(m)),
            }
            for m in messages[-limit:]
        ]
