"""
AgentState — the dict that flows through every graph node.

Two design notes:
  - `messages` uses LangGraph's `add_messages` reducer, which appends new
    messages and replaces existing ones by message ID. Without this reducer,
    each node would clobber the message list.
  - The other fields use the default "replace" reducer, which is what we
    want for per-turn metadata (memory context, counters). Each node
    returns a partial-state dict and only the keys it touches get updated.

Adding a field here? Default reducer is replace. If you need accumulate-on-
update (a list that grows across node calls), wrap with `Annotated[..., reducer]`
the way `messages` does.
"""
from typing import Annotated, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    # --- conversation history (checkpointer-managed across turns) -----------
    messages: Annotated[list[BaseMessage], add_messages]

    # --- memory context (set by memory_load_node, read by agent_node) -------
    user_profile_always_on: dict
    user_profile_on_demand: list[dict]
    relevant_memories: list[dict]

    # --- per-turn metadata --------------------------------------------------
    thread_id: str
    platform: str            # "telegram", "whatsapp", "web"
    channel_user_id: str     # platform's user/chat ID
    user_message: str        # the original master message that started this turn
    turn_started_at: str     # ISO timestamp — also used as a turn_id for rate limit keys

    # --- tool-call accounting ------------------------------------------------
    tool_calls_this_turn: int

    # --- final assistant text (set when agent emits a non-tool message) -----
    final_response: str
