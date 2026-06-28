"""Side bug: the per-turn hourly rate check ran on EVERY agent pass, not once.

`tool_calls_this_turn` (AgentState) gates `check_turn_rate` to the FIRST agent pass of a turn, but
the field was read and never written → always falsy → the hourly cap was decremented once per agent
pass (over-counting). Fix: agent_node writes it (incremented); each turn's initial_state resets it.
"""
from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage

import app.agent.nodes as nodes


class _Scripted:
    def __init__(self, responses):
        self._responses = list(responses)

    async def ainvoke(self, _msgs):
        return self._responses.pop(0)


@pytest.mark.asyncio
async def test_hourly_rate_check_runs_once_per_turn(monkeypatch):
    check = AsyncMock(return_value=True)
    monkeypatch.setattr(nodes.rate_limiter, "check_turn_rate", check)
    monkeypatch.setattr(nodes, "_build_chat_model",
                        lambda *a, **k: _Scripted([AIMessage(content="one"), AIMessage(content="two")]))
    base = {"messages": [HumanMessage(content="hi")], "thread_id": "web:rate", "platform": "web",
            "user_message": "hi", "user_profile_always_on": {}, "tool_calls_this_turn": 0}

    # FIRST agent pass of the turn: the hourly check runs, and the counter is written.
    upd1 = await nodes.agent_node(base)
    assert check.await_count == 1
    assert upd1.get("tool_calls_this_turn") == 1

    # SECOND pass (a tool loop-back within the SAME turn): counter is truthy → check NOT re-run.
    upd2 = await nodes.agent_node({**base, "tool_calls_this_turn": upd1["tool_calls_this_turn"]})
    assert check.await_count == 1, "hourly rate check must run once per turn, not per agent pass"
    assert upd2.get("tool_calls_this_turn") == 2
