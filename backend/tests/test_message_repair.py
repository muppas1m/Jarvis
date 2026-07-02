"""P1 — orphaned-tool_call repair + the run_turn legacy-checkpoint backstop.

Two layers protect against the Jun-11 terminal error (a free-text turn landing
on a pending approval interrupt → an AIMessage tool_call with no ToolMessage →
the OpenAI fallback 400s the whole history):

  1. repair_orphaned_tool_calls — defense-in-depth: stub any orphan before the
     LLM call so the fallback can't choke. (pure function, exhaustively tested)
  2. run_turn's _is_awaiting_approval backstop — Phase 3 retired interrupt() so
     nothing NEW pauses; the deploy-time drain clears any pre-cutover paused
     checkpoint. This backstop covers the deploy window: a free-text turn on a
     legacy paused checkpoint NUDGES to the buttons (which resolve through the
     claim-gated dispatcher) and NEVER resumes the graph — resuming would flip the
     row to approved without dispatching the tool (a silent action-drop).
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
    strip_divergent_tool_call_residue,
)
from app.agent.runner import run_turn


def _poisoned_ai(tc_id: str = "trpv0ek1t", name: str = "approvals_pending") -> AIMessage:
    """The EXACT web:master [26] shape (D22 5th capture): parse-failed llama call —
    .tool_calls EMPTY, the call in invalid_tool_calls + the raw additional_kwargs mirror."""
    return AIMessage(
        content="",
        tool_calls=[],
        invalid_tool_calls=[{"name": name, "args": "null", "id": tc_id,
                             "error": None, "type": "invalid_tool_call"}],
        additional_kwargs={"tool_calls": [{
            "id": tc_id, "function": {"arguments": "null", "name": name},
            "type": "function", "index": 0,
        }]},
    )


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


# --------------------------------------------------------------------------- #
# D22 — divergent-residue strip (the trpv0ek1t shape) + wire round-trip         #
# --------------------------------------------------------------------------- #
def test_strip_divergent_residue_exact_web_master_shape():
    """The web:master [26] message: strip returns a same-id copy with NO residue;
    the original is untouched (pure function)."""
    m = _poisoned_ai()
    fixed = strip_divergent_tool_call_residue(m)
    assert fixed is not None
    assert fixed.id == m.id                                   # same-id → add_messages REPLACES
    assert fixed.invalid_tool_calls == []
    assert "tool_calls" not in fixed.additional_kwargs
    assert m.invalid_tool_calls                               # original untouched
    assert "tool_calls" in m.additional_kwargs


def test_strip_returns_none_for_clean_and_for_healthy_ak_mirror():
    """The head-probe constraint: healthy messages ([9]/[13]/[17]/[21]) carry ak-mirrors
    of their REAL parsed tool_calls — those must NEVER be stripped."""
    healthy = AIMessage(
        content="",
        tool_calls=[{"name": "email_send", "args": {"to": "x@y.com"}, "id": "call_1"}],
        additional_kwargs={"tool_calls": [{
            "id": "call_1", "function": {"arguments": '{"to":"x@y.com"}', "name": "email_send"},
            "type": "function"}]},
    )
    assert strip_divergent_tool_call_residue(healthy) is None
    assert strip_divergent_tool_call_residue(AIMessage(content="plain")) is None
    assert strip_divergent_tool_call_residue(HumanMessage(content="hi")) is None


def test_strip_partial_divergent_keeps_only_mirrored_ids():
    """ak carries a real call's mirror + a divergent id → only the divergent entry drops."""
    m = AIMessage(
        content="",
        tool_calls=[{"name": "a", "args": {}, "id": "call_a"}],
        additional_kwargs={"tool_calls": [
            {"id": "call_a", "function": {"arguments": "{}", "name": "a"}, "type": "function"},
            {"id": "zzz9bad", "function": {"arguments": "null", "name": "b"}, "type": "function"},
        ]},
    )
    fixed = strip_divergent_tool_call_residue(m)
    assert fixed is not None
    kept = fixed.additional_kwargs["tool_calls"]
    assert [c["id"] for c in kept] == ["call_a"]


def test_repair_strips_divergent_residue_in_copies():
    msgs = [HumanMessage(content="q"), _poisoned_ai(), HumanMessage(content="next")]
    out = repair_orphaned_tool_calls(msgs)
    assert len(out) == 3                                       # nothing inserted — nothing to answer
    ai = out[1]
    assert ai.invalid_tool_calls == [] and "tool_calls" not in ai.additional_kwargs
    assert not any(isinstance(m, ToolMessage) for m in out)    # STRIP, never synthesize for invalid


def test_displaced_answer_moved_adjacent():
    """Answered-somewhere-but-not-adjacent (a HumanMessage landed in between) —
    OpenAI validates POSITION; the repair moves the answer back next to its call."""
    msgs = [
        _ai_with_tool_call("call_x"),
        HumanMessage(content="interleaved"),
        ToolMessage(content="late answer", tool_call_id="call_x"),
    ]
    out = repair_orphaned_tool_calls(msgs)
    assert isinstance(out[0], AIMessage)
    assert isinstance(out[1], ToolMessage) and out[1].tool_call_id == "call_x"
    assert out[1].content == "late answer"                     # the REAL answer moved, not a stub
    assert isinstance(out[2], HumanMessage)
    assert len(out) == 3


def test_dangling_tool_message_dropped():
    """A ToolMessage answering a call no in-list AIMessage carries (the mirror 400:
    role 'tool' must respond to a preceding 'tool_calls') → dropped from the copy."""
    msgs = [HumanMessage(content="q"),
            ToolMessage(content="ghost", tool_call_id="call_gone"),
            AIMessage(content="answer")]
    out = repair_orphaned_tool_calls(msgs)
    assert not any(isinstance(m, ToolMessage) for m in out)
    assert len(out) == 2


def test_normalize_idempotent_on_poisoned_history():
    msgs = [_poisoned_ai(), HumanMessage(content="next"), _ai_with_tool_call("call_1")]
    once = repair_orphaned_tool_calls(msgs)
    twice = repair_orphaned_tool_calls(once)
    assert [(type(m).__name__, getattr(m, "tool_call_id", None)) for m in once] == \
           [(type(m).__name__, getattr(m, "tool_call_id", None)) for m in twice]


def test_wire_roundtrip_no_unanswered_tool_calls_under_both_elif_branches():
    """The master's round-trip proof: serialize normalized history through ChatLiteLLM's
    ACTUAL outbound converter; assert no unanswered tool_call under EITHER branch of the
    elif — branch A (parsed .tool_calls) and branch B (the additional_kwargs fallback)."""
    litellm_mod = pytest.importorskip("langchain_litellm.chat_models.litellm")
    convert = litellm_mod._convert_message_to_dict

    history = [
        HumanMessage(content="q1"),
        _poisoned_ai(),                                        # branch-B shape → must strip
        HumanMessage(content="q2"),
        _ai_with_tool_call("call_ok"),                         # branch-A orphan → synthesized
        HumanMessage(content="q3"),
    ]
    wire = [convert(m) for m in repair_orphaned_tool_calls(history)]
    for i, d in enumerate(wire):
        if d.get("role") == "assistant" and d.get("tool_calls"):
            ids = {c.get("id") for c in d["tool_calls"]}
            j = i + 1
            while j < len(wire) and wire[j].get("role") == "tool":
                ids.discard(wire[j].get("tool_call_id"))
                j += 1
            assert not ids, f"unanswered on the wire at [{i}]: {ids}"
    # the poisoned message emitted with NO tool_calls key at all (branch B defused)
    poisoned_wire = wire[1]
    assert poisoned_wire["role"] == "assistant" and "tool_calls" not in poisoned_wire


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
# run_turn legacy-checkpoint backstop — nudge, never resume                    #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_run_turn_nudges_on_legacy_paused_checkpoint():
    """A free-text turn on a LEGACY paused-at-interrupt checkpoint (pre-Phase-3)
    must NOT invoke OR resume the graph — either would either orphan the pending
    tool_call (Jun-11 error) or flip the row to approved without dispatching (a
    silent drop). It nudges to the buttons and leaves the checkpoint intact for
    the drain / a button-decide."""

    class _Task:
        interrupts = ({"value": "Approve calendar_create?"},)  # a REAL interrupt

    class _PausedState:
        next = ("tool_executor",)
        tasks = (_Task(),)  # task.interrupts populated → genuinely paused
        values: dict = {}

    async def fake_aget_state(_config):
        return _PausedState()

    async def fake_ainvoke(*args, **kwargs):  # noqa: ARG001
        raise AssertionError("run_turn must not invoke/resume the graph while paused")

    with patch("app.agent.runner.graph") as mock_graph_factory:
        mock_graph = mock_graph_factory.return_value
        mock_graph.aget_state.side_effect = fake_aget_state
        mock_graph.ainvoke.side_effect = fake_ainvoke

        envelope = await run_turn(
            user_message="yes send it",
            thread_id="legacy-paused-thread",
            platform="telegram",
            channel_user_id="master",
        )

    assert envelope["status"] == "complete"
    assert envelope["stop_reason"] == "pending_approval"
    assert "decision waiting" in envelope["response"]
    assert "approve" in envelope["response"].lower()  # nudge to the buttons
    assert envelope["interrupt"] is None  # we don't re-send the buttons (no dup row)
    mock_graph.ainvoke.assert_not_called()  # neither a fresh turn NOR a resume


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
