"""
MemoryManager — the single entry point the rest of the codebase uses to read
and write any tier of memory.

Tier breakdown:
  Tier 1 (working memory) — bounded by the LLM context window; shaped by the
                            agent graph nodes, not by this class.
  Tier 2 (session messages) — owned by LangGraph's AsyncPostgresSaver
                              checkpointer. We never duplicate that storage.
                              `app.memory.session.SessionManager` exposes a
                              read-only analytics view for the dashboard.
  Tier 3 (episodic) — Mem0, surfaced via `recall()` and written by `persist_turn`.
  Tier 4 (semantic facts) — same Mem0 store, distinguished by metadata.kind.
  Tier 5 (user profile) — UserProfileManager (split always_on / on_demand).
                          On-demand sections are also indexed into Mem0 with
                          `kind="profile"` so they surface during recall.
"""
from typing import Any

from app.memory.mem0_client import Mem0Client
from app.memory.user_profile import UserProfileManager


class MemoryManager:
    def __init__(self) -> None:
        self.mem0 = Mem0Client()
        self.profile_mgr = UserProfileManager()

    # ------------------------------------------------------------------
    # Per-turn API — used by the agent graph's memory_load node.
    # ------------------------------------------------------------------
    async def build_context(self, user_message: str) -> dict[str, Any]:
        """Pull everything the system prompt needs for this turn.

        Returns the always-on profile slice, any on-demand sections that
        Mem0 thinks are relevant to the message, and free-form recall hits
        (memories whose `kind` is not 'profile')."""
        always_on = await self.profile_mgr.get_always_on()
        relevant = await self.mem0.search(query=user_message, top_k=10)

        on_demand_profile = [
            r for r in relevant if r["metadata"].get("kind") == "profile"
        ]
        recall = [
            r for r in relevant if r["metadata"].get("kind") != "profile"
        ]

        return {
            "user_profile_always_on": always_on,
            "user_profile_on_demand": on_demand_profile,
            "relevant_memories": recall,
        }

    async def persist_turn(
        self,
        thread_id: str,
        user_message: str,
        assistant_response: str,
    ) -> None:
        """After a turn closes, hand the (user, assistant) pair to Mem0 so it
        can extract durable memories. Raw messages stay with LangGraph; only
        Mem0 extractions land in our memory store."""
        combined = f"User: {user_message}\nAssistant: {assistant_response}"
        await self.mem0.add(content=combined, thread_id=thread_id)

    # ------------------------------------------------------------------
    # Profile mutators — kept here so callers don't need a separate
    # UserProfileManager handle. The on-demand path also indexes into Mem0
    # so semantic search picks up profile changes immediately.
    # ------------------------------------------------------------------
    async def update_profile_always_on(self, updates: dict[str, Any]) -> None:
        await self.profile_mgr.update_always_on(updates)

    async def update_profile_on_demand(self, key: str, value: Any) -> None:
        await self.profile_mgr.update_on_demand(key, value)
        await self.mem0.add(
            content=f"Profile section [{key}]: {value}",
            metadata={"kind": "profile", "key": key},
        )

    # ------------------------------------------------------------------
    # Convenience facades — used by api/memory.py and agent/context.py.
    # ------------------------------------------------------------------
    async def get_always_on(self) -> dict[str, Any]:
        return await self.profile_mgr.get_always_on()

    async def get_on_demand(self, key: str) -> Any:
        return await self.profile_mgr.get_on_demand(key)

    async def list_on_demand_keys(self) -> list[str]:
        full = await self.profile_mgr.get_full()
        return list((full.get("on_demand") or {}).keys())

    async def recall(
        self,
        query: str,
        thread_id: str | None = None,
        k: int = 5,
    ) -> list[dict[str, Any]]:
        """Semantic recall over Mem0. If a thread_id is given, filter to
        memories that came from that thread."""
        # Over-fetch when filtering so we still have k results after the filter.
        raw = await self.mem0.search(query=query, top_k=k * 4 if thread_id else k)
        if thread_id:
            raw = [
                m for m in raw
                if m["metadata"].get("thread_id") == thread_id
            ][:k]
        return raw

    async def thread_summary(self, thread_id: str) -> str:
        """One-paragraph rollup of a thread's extracted memories. Used by the
        prompt builder's volatile suffix. Empty string when the thread has no
        Mem0 entries yet (early in a conversation)."""
        all_mems = await self.mem0.search(query=f"thread:{thread_id}", top_k=20)
        relevant = [
            m["content"] for m in all_mems
            if m["metadata"].get("thread_id") == thread_id
        ]
        if not relevant:
            return ""
        joined = " | ".join(relevant)
        return joined[:1500]   # token-bound; the prompt builder may trim more
