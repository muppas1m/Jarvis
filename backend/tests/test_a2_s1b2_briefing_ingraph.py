"""A2 s1b-2 — briefing IN-GRAPH (D19) + D21 persona + the ONE terminal delta (NV7) +
the turn-bounded deliver signal. The three post-graph bolt-on sites are dead; persist_node
is the single attach point; every channel consumes the same terminal_delta.
"""
import contextlib
import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

import app.agent.runner as runner
from app.agent.briefing_state import (
    BriefingLiveState,
    deliver_requested,
    render_offer,
)
from app.agent.graph import init_checkpointer
from app.agent.nodes import persist_node

_MARK = f"test-s1b2-{uuid.uuid4().hex[:8]}"


@pytest.fixture
async def real_checkpointer():
    from app.agent import graph as graph_module
    if graph_module._checkpointer_cm is not None:
        with contextlib.suppress(Exception):
            await graph_module._checkpointer_cm.__aexit__(None, None, None)
        graph_module._checkpointer = None
        graph_module._checkpointer_cm = None
    await init_checkpointer()
    runner._graph = None
    yield
    runner._graph = None


class _Scripted:
    def __init__(self, responses):
        self._responses = list(responses)

    async def ainvoke(self, _msgs):
        return self._responses.pop(0)


def _live(unheard=3, away_days=0, cooldown=False):
    now = datetime.now(UTC)
    return BriefingLiveState(
        now=now,
        timezone="UTC",
        last_briefed_at=(now - timedelta(minutes=5)) if cooldown else (now - timedelta(hours=6)),
        last_seen_at=now - timedelta(days=away_days) if away_days else now - timedelta(hours=1),
        unheard=unheard,
    )


# --------------------------------------------------------------------------- #
# D21 — the persona floors                                                     #
# --------------------------------------------------------------------------- #
def test_offer_templates_in_persona_no_oh_opener():
    single = render_offer(_live(unheard=3))
    multi = render_offer(_live(unheard=7, away_days=3))
    for text in (single, multi):
        assert not text.startswith("Oh")                    # the off-persona opener is gone
        assert "Sir" in text                                 # honorific from config
    assert "3 items await" in single                         # names the count (composed butler)
    assert "away 3 days" in multi and "Welcome back" in multi


def test_offer_singular_count():
    assert "One item awaits" in render_offer(_live(unheard=1))


# --------------------------------------------------------------------------- #
# Turn-bounded deliver signal (the §a.7 contradiction fixed)                    #
# --------------------------------------------------------------------------- #
def test_deliver_signal_from_prior_turn_does_not_leak():
    prior_call = AIMessage(content="", tool_calls=[{"name": "deliver_briefing", "args": {}, "id": "d0"}])
    msgs = [prior_call, HumanMessage(content="what's 2+2?"), AIMessage(content="4, Sir.")]
    assert deliver_requested(msgs) is False                  # bounded at this turn's HumanMessage


def test_deliver_signal_this_turn_detected():
    msgs = [HumanMessage(content="good morning"),
            AIMessage(content="", tool_calls=[{"name": "deliver_briefing", "args": {}, "id": "d1"}])]
    assert deliver_requested(msgs) is True


# --------------------------------------------------------------------------- #
# persist_node — the in-graph attach: persisted message, idempotent, delta      #
# --------------------------------------------------------------------------- #
def _persist_state(**over):
    state = {
        "user_message": "good morning", "final_response": "Good morning, Sir.",
        "thread_id": f"web:{_MARK}", "messages": [HumanMessage(content="good morning"),
                                                  AIMessage(content="Good morning, Sir.")],
        "briefing_proactive": "surface_single", "briefing_offer": "3 items await your attention when you're ready, Sir. Shall I brief you?",
        "briefing_attached": False, "terminal_delta": "",
    }
    state.update(over)
    return state


@pytest.mark.asyncio
async def test_briefing_attaches_as_persisted_message_with_kwargs():
    with patch("app.agent.nodes.get_memory") as mem, \
         patch("app.agent.briefing_state.mark_offered", new=AsyncMock()) as stamp:
        mem.return_value.persist_turn = AsyncMock()
        out = await persist_node(_persist_state())
    msg = out["messages"][0]                                 # the briefing message EXISTS in state
    assert msg.additional_kwargs["jarvis"]["type"] == "briefing"
    assert "Shall I brief you?" in msg.content
    assert out["briefing_attached"] is True
    assert "Shall I brief you?" in out["final_response"]     # rides the reply
    assert "Good morning, Sir." in out["final_response"]     # after the answer
    assert out["terminal_delta"].endswith("Shall I brief you?")   # the ONE delta
    stamp.assert_awaited_once()                              # the cooldown stamped at attach


@pytest.mark.asyncio
async def test_briefing_attach_idempotent_via_flag():
    with patch("app.agent.nodes.get_memory") as mem, \
         patch("app.agent.briefing_state.mark_offered", new=AsyncMock()) as stamp:
        mem.return_value.persist_turn = AsyncMock()
        out = await persist_node(_persist_state(briefing_attached=True))
    assert out == {}                                         # re-entry: no message, no stamp
    stamp.assert_not_awaited()


@pytest.mark.asyncio
async def test_suppress_mode_attaches_nothing():
    with patch("app.agent.nodes.get_memory") as mem:
        mem.return_value.persist_turn = AsyncMock()
        out = await persist_node(_persist_state(briefing_proactive="suppress"))
    assert out == {}


# --------------------------------------------------------------------------- #
# D19 end-to-end: the offer PERSISTS in the checkpoint                          #
# --------------------------------------------------------------------------- #
@pytest.mark.asyncio
async def test_d19_offer_persists_in_checkpoint(real_checkpointer):
    thread = f"web:{_MARK}-d19"
    answer = AIMessage(content="Good morning to you too, Sir.")
    with patch("app.agent.nodes._build_chat_model", lambda *a, **k: _Scripted([answer])), \
         patch("app.agent.nodes.get_memory") as mem, \
         patch("app.agent.briefing_state.load_live_state", new=AsyncMock(return_value=_live(unheard=2))), \
         patch("app.agent.briefing_state.touch_last_seen", new=AsyncMock()), \
         patch("app.agent.briefing_state.mark_offered", new=AsyncMock()):
        mem.return_value.build_context = AsyncMock(return_value={
            "user_profile_always_on": "", "user_profile_on_demand": "", "relevant_memories": ""})
        mem.return_value.persist_turn = AsyncMock()
        env = await runner.run_turn("good morning", thread, "web", "u")
    assert "2 items await" in env["response"]                # the offer rides the reply
    snap = await runner.graph().aget_state({"configurable": {"thread_id": thread}})
    briefing_msgs = [m for m in snap.values["messages"]
                     if isinstance(m, AIMessage)
                     and ((m.additional_kwargs or {}).get("jarvis") or {}).get("type") == "briefing"]
    assert len(briefing_msgs) == 1                           # D19: PERSISTED, refresh-safe
    assert "2 items await" in briefing_msgs[0].content
