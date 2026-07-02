"""D22 regression — the trpv0ek1t thread-brick, reproduced and sealed.

The original failure (web:master, 2026-07-02): llama streamed a malformed
`approvals_pending(arguments="null")` call → parsed into `invalid_tool_calls`
(+ the raw `additional_kwargs["tool_calls"]` mirror) with `.tool_calls` EMPTY →
persisted as a "clean" answer → ChatLiteLLM's serializer resurrected the mirror
on every later request → OpenAI 400 → every turn failed ("I hit an internal
error"), permanently (compaction sits downstream of the 400 → no self-heal).

Sealed by three layers, each tested here:
  1. mint-time  — FallbackChatLLM shape-3 detect → ONE bounded re-issue → real answer
                  (also D23: the blank reply WAS this shape passing as clean);
  2. load-time  — memory_load durably strips divergent residue (same-id replace);
                  agent_node's outbound repair keeps the wire valid regardless;
  3. recovery   — scripts/repair_poisoned_thread.py heals a committed thread
                  (raw-SQL dump first, idempotent, history intact).

The two *_serves tests drive the REAL model path (pinned gpt-4o-mini) — the 400
lived in the outbound conversion, so a mocked LLM cannot prove the fix.
"""
import contextlib
import uuid
from unittest.mock import AsyncMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage

import app.agent.runner as runner
from app.agent.graph import init_checkpointer
from app.llm.fallback_llm import FallbackChatLLM

_MARK = f"test-d22-{uuid.uuid4().hex[:8]}"


def _poisoned_ai(tc_id: str = "trpv0ek1t") -> AIMessage:
    """The exact committed web:master [26] shape."""
    return AIMessage(
        content="",
        tool_calls=[],
        invalid_tool_calls=[{"name": "approvals_pending", "args": "null", "id": tc_id,
                             "error": None, "type": "invalid_tool_call"}],
        additional_kwargs={"tool_calls": [{
            "id": tc_id, "function": {"arguments": "null", "name": "approvals_pending"},
            "type": "function", "index": 0,
        }]},
    )


def _residue(messages) -> list:
    from app.agent.message_repair import strip_divergent_tool_call_residue
    return [m for m in messages if strip_divergent_tool_call_residue(m) is not None]


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


async def _seed_poisoned_thread(thread_id: str):
    g = runner.graph()
    cfg = {"configurable": {"thread_id": thread_id}}
    await g.aupdate_state(cfg, {"messages": [
        HumanMessage(content="Do I have any email that needs approval?"),
        _poisoned_ai(),
    ]}, as_node="agent")
    snap = await g.aget_state(cfg)
    assert _residue(snap.values["messages"]), "seed failed — no residue found"
    return cfg


# =========================================================================== #
# 1. THE regression: a poisoned thread SERVES (pre-fix this 400'd every turn)  #
# =========================================================================== #
@pytest.mark.asyncio
async def test_poisoned_thread_serves_and_heals_durably(real_checkpointer):
    thread_id = f"web:{_MARK}-brick"
    cfg = await _seed_poisoned_thread(thread_id)

    env = await runner.run_turn(
        "Recovery check — one short sentence please.", thread_id, "web", "u")
    assert env["status"] == "complete", f"turn failed: {env.get('stop_reason')}"
    assert (env["response"] or "").strip(), "blank reply (D23)"
    assert "internal error" not in env["response"].lower()

    # durable heal: the CHECKPOINT no longer carries the residue (memory_load same-id replace)
    snap = await runner.graph().aget_state(cfg)
    msgs = snap.values["messages"]
    assert not _residue(msgs), "divergent residue survived in the checkpoint"
    # history intact: the poisoned message still EXISTS (sanitized), nothing deleted
    assert any(isinstance(m, HumanMessage) and "needs approval" in str(m.content) for m in msgs)


# =========================================================================== #
# 2. Mint-time: shape-3 → ONE bounded re-issue → real answer persisted         #
# =========================================================================== #
class _FakeLLM:
    def __init__(self, result):
        self.result, self.calls = result, 0

    async def ainvoke(self, _input, config=None, **kwargs):
        self.calls += 1
        return self.result


@pytest.mark.asyncio
async def test_fallback_reissues_invalid_tool_response_once():
    primary = _FakeLLM(_poisoned_ai())
    fallback = _FakeLLM(AIMessage(content="A real answer, Sir."))
    out = await FallbackChatLLM(primary, fallback).ainvoke([HumanMessage(content="q")])
    assert out.content == "A real answer, Sir."
    assert primary.calls == 1 and fallback.calls == 1     # ONE re-issue — the bound


@pytest.mark.asyncio
async def test_fallback_bound_holds_when_fallback_also_invalid():
    """Both models malformed → the wrapper returns the fallback result AS-IS (no loop —
    _reissue_ainvoke calls the fallback exactly once); agent_node's strip then owns it."""
    primary = _FakeLLM(_poisoned_ai("bad1"))
    fallback = _FakeLLM(_poisoned_ai("bad2"))
    out = await FallbackChatLLM(primary, fallback).ainvoke([HumanMessage(content="q")])
    assert primary.calls == 1 and fallback.calls == 1     # no retry loop
    assert out.invalid_tool_calls                          # handed to agent_node's strip


@pytest.mark.asyncio
async def test_double_malformed_persists_clean_with_floor_reply(real_checkpointer):
    """BOTH models return the mint shape → agent_node strips before persist (no poison
    ever committed) and the D23 floor replaces the silent blank reply."""
    thread_id = f"web:{_MARK}-floor"
    with patch("app.agent.nodes._build_chat_model", lambda *a, **k: _FakeLLM(_poisoned_ai())), \
         patch("app.messaging.failure_alerter.send_approval_request_to_master", AsyncMock()):
        env = await runner.run_turn("hello", thread_id, "web", "u")
    assert env["status"] == "complete"
    assert (env["response"] or "").strip(), "D23: blank reply persisted"
    snap = await runner.graph().aget_state({"configurable": {"thread_id": thread_id}})
    assert not _residue(snap.values["messages"]), "mint shape reached the checkpoint"


# =========================================================================== #
# 3. Recovery tool: dump-first, heal, idempotent, thread serves                #
# =========================================================================== #
@pytest.mark.asyncio
async def test_recovery_tool_heals_committed_thread(real_checkpointer, tmp_path):
    from scripts.repair_poisoned_thread import repair_thread

    thread_id = f"web:{_MARK}-tool"
    await _seed_poisoned_thread(thread_id)

    r1 = await repair_thread(thread_id, dump_dir=tmp_path)
    assert r1["healed"] == 1 and r1["n_before"] == r1["n_after"] == 2   # same-id replace, no loss
    dumps = list(tmp_path.glob("thread_dump_*.json"))
    assert len(dumps) == 1 and dumps[0].stat().st_size > 0             # raw-SQL dump BEFORE write

    r2 = await repair_thread(thread_id, dump_dir=tmp_path)             # idempotent no-op
    assert r2["healed"] == 0 and r2["synthesized"] == 0
    assert len(list(tmp_path.glob("thread_dump_*.json"))) == 1         # no second dump (no write)

    env = await runner.run_turn(
        "Recovery check — one short sentence please.", thread_id, "web", "u")
    assert env["status"] == "complete" and (env["response"] or "").strip()
