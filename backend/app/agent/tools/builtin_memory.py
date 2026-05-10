"""
memory_search — built-in tool, always loaded.

The only tool registered in Phase 1. Lets the agent fetch facts from Mem0
when a question references something previously discussed (preferences,
past decisions, named relationships, etc.).

`always_loaded=True` skips the embedding-based ranking — memory_search is
relevant on so many turns that paying the dynamic-selection cost would
just add latency without changing the outcome.
"""
from pydantic import BaseModel, Field

from app.agent.tools.registry import tool_registry
from app.memory.manager import MemoryManager

# Singleton — MemoryManager wraps a Mem0 client + DB-backed UserProfileManager
# and isn't cheap to construct.
_memory = MemoryManager()


class MemorySearchArgs(BaseModel):
    query: str = Field(
        ..., description="What to search for in long-term memory"
    )
    top_k: int = Field(
        default=5, description="Maximum number of relevant memories to return"
    )


async def memory_search(query: str, top_k: int = 5) -> str:
    """Look up the master's memories that semantically match `query`."""
    results = await _memory.mem0.search(query=query, top_k=top_k)
    if not results:
        return "No relevant memories found."

    lines = [
        f"- ({r.get('score', 0):.2f}) {r['content']}"
        for r in results
        if r.get("content")
    ]
    if not lines:
        return "No relevant memories found."
    return "Relevant memories:\n" + "\n".join(lines)


def register() -> None:
    tool_registry.register(
        name="memory_search",
        handler=memory_search,
        description=(
            "Search the master's long-term memory for facts, past decisions, "
            "preferences, or past conversations. Use when the user references "
            "something previously discussed or when context from past turns "
            "may help answer."
        ),
        args_schema=MemorySearchArgs,
        always_loaded=True,
    )
