"""
memory_search — built-in tool, always loaded.

First tool registered (Phase 1); Phase 2+ tools register alongside via
__init__.py. Lets the agent fetch facts from Mem0 when a question references
something previously discussed (preferences, past decisions, named
relationships, etc.).

`always_loaded=True` skips the embedding-based ranking — memory_search is
relevant on so many turns that paying the dynamic-selection cost would
just add latency without changing the outcome.
"""
from pydantic import BaseModel, Field

from app.agent.tools.registry import tool_registry
from app.memory.manager import get_memory


class MemorySearchArgs(BaseModel):
    query: str = Field(
        ..., description="What to search for in long-term memory"
    )
    top_k: int = Field(
        default=5, description="Maximum number of relevant memories to return"
    )


async def memory_search(query: str, top_k: int = 5) -> str:
    """Look up the master's memories that semantically match `query`."""
    results = await get_memory().mem0.search(query=query, top_k=top_k)
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
            "Search the master's persistent conversation memory — facts they've "
            "told you, preferences, relationships, things mentioned in past "
            "chats with you (Jarvis). "
            "Does NOT search email content (use email_history_search) and does NOT "
            "track open tasks / to-dos (use task_list for the master's list). "
            "Use for: 'what did I tell you about X', 'do I prefer Y', 'who is Z', "
            "questions referencing prior chat context."
        ),
        args_schema=MemorySearchArgs,
        always_loaded=True,
        capability="Recall facts from your memory and past conversations.",
    )
