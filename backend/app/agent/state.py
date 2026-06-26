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

    # --- rolling conversation summary (compaction, 4.B.3) -------------------
    # When the verbatim history grows past the threshold, the oldest messages are
    # summarized into here and dropped from `messages`. agent_node injects this as
    # a context block so the thread survives without sending the full history.
    # Checkpointer-managed (persists across turns).
    running_summary: str
    # True ONLY on the turn compaction just fired — drives the live in-chat
    # "compacted" divider. Not surfaced on history reload (the divider is live).
    compacted_last_turn: bool

    # --- memory context (set by memory_load_node, read by agent_node) -------
    user_profile_always_on: dict
    user_profile_on_demand: list[dict]
    relevant_memories: list[dict]
    # Proactive-briefing check-in (5.4) — computed once in memory_load_node. directive =
    # the model guidance (injected by agent_node); proactive = the deterministic mode
    # (suppress / surface_single / surface_multiday) + offer = the code-owned OFFER line,
    # both read by the runner post-turn to CODE-render the brief/offer into the reply.
    briefing_directive: str
    briefing_proactive: str
    briefing_offer: str

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
