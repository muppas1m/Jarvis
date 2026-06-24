"""P1 — orphaned-tool_call repair + the run_turn pending-interrupt guard.

Two layers protect against the Jun-11 terminal error (a free-text turn landing
on a pending approval interrupt → an AIMessage tool_call with no ToolMessage →
the OpenAI fallback 400s the whole history):

  1. repair_orphaned_tool_calls — defense-in-depth: stub any orphan before the
     LLM call so the fallback can't choke. (pure function, exhaustively tested)
  2. run_turn's _is_awaiting_approval guard — prevent-at-source: don't even
     start a fresh turn while an approval is pending; nudge to the buttons.
"""
from unittest.mock import patch

import pytest
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

from app.agent.message_repair import (
    ORPHAN_PLACEHOLDER,
    repair_orphaned_tool_calls,
)
from app.agent.runner import run_turn


def _ai_with_tool_call(tc_id: str, name: str = "email_send") -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[{"name": name, "args": {"to": "x@y.com"}, "id": tc_id}],
    )


# --------------------------------------------------------------------------- #
# repair_orphaned_tool_calls — pure function                                  #
# --------------------------------------------------------------------------- #
def test_noop_when_no_tool_calls():
    msgs = [SystemMessage(content="sys"), HumanMessage(content="hi"),
            AIMessage(content="hello")]
    assert repair_orphaned_tool_calls(msgs) == msgs


def test_noop_when_tool_call_already_answered():
    msgs = [
        _ai_with_tool_call("call_1"),
        ToolMessage(content="sent", tool_call_id="call_1"),
    ]
    out = repair_orphaned_tool_calls(msgs)
    assert len(out) == 2  # nothing injected
    assert out == msgs


def test_orphaned_tool_call_gets_synthetic_tool_message():
    """The exact Jun-11 shape: pending tool_call, then a free-text HumanMessage
    landed after it with no ToolMessage in between."""
    msgs = [
        HumanMessage(content="schedule a meeting"),
        _ai_with_tool_call("call_9FlaTAOC"),
        HumanMessage(content="yes send it"),  # free text hijacked the interrupt
    ]
    out = repair_orphaned_tool_calls(msgs)

    # synthetic ToolMessage inserted immediately after the AIMessage
    assert isinstance(out[2], ToolMessage)
    assert out[2].tool_call_id == "call_9FlaTAOC"
    assert out[2].content == ORPHAN_PLACEHOLDER
    # original order otherwise preserved; the trailing HumanMessage still last
    assert isinstance(out[3], HumanMessage) and out[3].content == "yes send it"
    # every tool_call now has an answering ToolMessage
    _assert_no_orphans(out)


def test_partial_answer_only_orphan_repaired():
    """AIMessage with two tool_calls, only one answered → repair the other."""
    msgs = [
        AIMessage(
            content="",
            tool_calls=[
                {"name": "a", "args": {}, "id": "call_a"},
                {"name": "b", "args": {}, "id": "call_b"},
            ],
        ),
        ToolMessage(content="ok", tool_call_id="call_b"),
    ]
    out = repair_orphaned_tool_calls(msgs)
    ids = {m.tool_call_id for m in out if isinstance(m, ToolMessage)}
    assert ids == {"call_a", "call_b"}
    # the synthetic one is for call_a and carries the placeholder
    synth = next(m for m in out if isinstance(m, ToolMessage)
                 and m.content == ORPHAN_PLACEHOLDER)
    assert synth.tool_call_id == "call_a"
    _assert_no_orphans(out)


def test_idempotent():
    msgs = [_ai_with_tool_call("call_1"), HumanMessage(content="next")]
    once = repair_orphaned_tool_calls(msgs)
    twice = repair_orphaned_tool_calls(once)
    assert [(_kind(m), getattr(m, "tool_call_id", None)) for m in once] == \
           [(_kind(m), getattr(m, "tool_call_id", None)) for m in twice]
    _assert_no_orphans(twice)


def test_multiple_orphans_across_messages():
    msgs = [
        _ai_with_tool_call("call_1"),
        HumanMessage(content="a"),
        _ai_with_tool_call("call_2"),
        HumanMessage(content="b"),
    ]
    out = repair_orphaned_tool_calls(msgs)
    _assert_no_orphans(out)
    assert {m.tool_call_id for m in out if isinstance(m, ToolMessage)} == {"call_1", "call_2"}


def _kind(m) -> str:
    return type(m).__name__


def _assert_no_orphans(messages) -> None:
    """Every AIMessage tool_call id must have a ToolMessage somewhere after."""
    answered = {m.tool_call_id for m in messages if isinstance(m, ToolMessage)}
    for m in messages:
        if isinstance(m, AIMessage) and getattr(m, "tool_calls", None):
            for tc in m.tool_calls:
                assert tc["id"] in answered, f"orphaned tool_call {tc['id']}"


# --------------------------------------------------------------------------- #
# run_turn guard — prevent-at-source                                          #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_run_turn_blocks_when_approval_pending():
    """A free-text turn while an interrupt is pending must NOT invoke the graph
    (which would orphan the pending tool_call). It returns a 'pending_approval'
    nudge envelope and leaves the interrupt intact."""

    class _PausedState:
        next = ("tool_executor",)  # non-empty → paused at interrupt
        values: dict = {}

    async def fake_aget_state(_config):
        return _PausedState()

    async def fake_ainvoke(*args, **kwargs):  # noqa: ARG001
        raise AssertionError("run_turn must not invoke the graph while paused")

    with patch("app.agent.runner.graph") as mock_graph_factory:
        mock_graph = mock_graph_factory.return_value
        mock_graph.aget_state.side_effect = fake_aget_state
        mock_graph.ainvoke.side_effect = fake_ainvoke

        envelope = await run_turn(
            user_message="yes send it",
            thread_id="poisoned-thread",
            platform="telegram",
            channel_user_id="master",
        )

    assert envelope["status"] == "complete"
    assert envelope["stop_reason"] == "pending_approval"
    assert "Approve" in envelope["response"] and "Reject" in envelope["response"]
    assert envelope["interrupt"] is None  # we don't re-send the buttons
    mock_graph.ainvoke.assert_not_called()


@pytest.mark.asyncio
async def test_run_turn_proceeds_when_no_pending_interrupt():
    """When the thread is NOT paused (state.next empty), the guard is
    transparent — run_turn proceeds to invoke the graph as normal."""

    class _IdleState:
        next = ()  # empty → not paused
        values: dict = {"messages": []}

    async def fake_aget_state(_config):
        return _IdleState()

    invoked = {"called": False}

    async def fake_ainvoke(initial_state, config=None):  # noqa: ARG001
        invoked["called"] = True
        return {"messages": [AIMessage(content="done")], "final_response": "done"}

    with patch("app.agent.runner.graph") as mock_graph_factory:
        mock_graph = mock_graph_factory.return_value
        mock_graph.aget_state.side_effect = fake_aget_state
        mock_graph.ainvoke.side_effect = fake_ainvoke

        envelope = await run_turn(
            user_message="hello",
            thread_id="clean-thread",
            platform="telegram",
            channel_user_id="master",
        )

    assert invoked["called"], "guard must be transparent when no interrupt is pending"
    assert envelope["stop_reason"] != "pending_approval"
