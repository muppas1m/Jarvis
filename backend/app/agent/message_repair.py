"""Message-history repair — orphaned tool_call → synthetic ToolMessage.

An agent loop can end up with an assistant message whose ``tool_calls`` have no
answering ``ToolMessage``. The concrete trigger (Jun-11 manual test): a
free-text turn lands while an APPROVE-tier ``interrupt()`` is still pending, so
``run_turn`` appends a new ``HumanMessage`` *after* the pending tool_call that
never produced a result.

Some providers tolerate that history; OpenAI's chat-completions API (which
``FallbackChatLLM`` falls over to) does not — it 400s the whole request:

    "An assistant message with 'tool_calls' must be followed by tool messages
     responding to each 'tool_call_id'."

That 400 surfaced as the terminal "internal error" in the test. ``run_turn``
now blocks the orphan from forming at all (prevent-at-source); this module is
the defense-in-depth layer: ``agent_node`` repairs any orphan in the outbound
message list before EVERY LLM call, so the fallback can't choke regardless of
how an orphan arose.

Pure function (no I/O) → unit-testable in isolation.
"""
from __future__ import annotations

from langchain_core.messages import AIMessage, BaseMessage, ToolMessage


# Distinct, self-explaining content so a human reading the transcript (or a
# Langfuse trace) sees exactly why the ToolMessage is here and isn't real.
ORPHAN_PLACEHOLDER = (
    "[no result recorded — this tool call was interrupted or superseded "
    "before it produced a result]"
)


def _tool_call_id(tc: object) -> str | None:
    """tool_calls entries are dicts (``{'name', 'args', 'id'}``) on LangChain
    AIMessages; stay defensive against object-shaped variants from other SDKs."""
    if isinstance(tc, dict):
        return tc.get("id")
    return getattr(tc, "id", None)


def repair_orphaned_tool_calls(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Return a message list where every assistant ``tool_call`` is answered.

    For each ``AIMessage.tool_calls`` id with no ``ToolMessage`` anywhere in the
    list, insert a synthetic placeholder ``ToolMessage`` immediately after the
    assistant message. Order-preserving and idempotent — re-running finds
    nothing to repair, and the common case (no orphans) returns an equivalent
    list. The synthetic message goes right after the AIMessage, so it sits
    inside that message's tool-response block ahead of any real ToolMessages
    for the call's other ids — a valid ordering for the strict providers.
    """
    answered: set[str] = {
        m.tool_call_id
        for m in messages
        if isinstance(m, ToolMessage) and m.tool_call_id
    }

    repaired: list[BaseMessage] = []
    for m in messages:
        repaired.append(m)
        if not (isinstance(m, AIMessage) and getattr(m, "tool_calls", None)):
            continue
        for tc in m.tool_calls:
            tc_id = _tool_call_id(tc)
            if tc_id and tc_id not in answered:
                repaired.append(
                    ToolMessage(content=ORPHAN_PLACEHOLDER, tool_call_id=tc_id)
                )
                answered.add(tc_id)
    return repaired
