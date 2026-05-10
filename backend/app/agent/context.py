"""
Per-turn context builder — thin facade over MemoryManager.

The agent graph's memory_load node already does the heavy lifting via
`MemoryManager.build_context()`. This module exists so other call sites
(future: dashboard previews of "what would the agent see right now",
prompt-replay tooling, debug endpoints) can ask the same question without
having to reconstruct the per-turn payload by hand.

Keep this file thin. If the graph's loading logic ever needs to differ
from a generic context build, add the divergence in the graph node, not
here.
"""
from typing import Any

from app.memory.manager import MemoryManager


_memory = MemoryManager()


async def build_turn_context(thread_id: str, user_message: str) -> dict[str, Any]:
    """Returns the same shape MemoryManager.build_context produces, plus the
    thread-scoped recall + summary that the agent's volatile prompt suffix
    expects.

    Shape:
        {
            "profile_block":  <always_on profile dict>,
            "recall_block":   <list[MemoryHit] for this thread>,
            "summary_block":  <string, may be empty>,
        }
    """
    return {
        "profile_block": await _memory.get_always_on(),
        "recall_block": await _memory.recall(user_message, thread_id=thread_id, k=5),
        "summary_block": await _memory.thread_summary(thread_id),
    }
