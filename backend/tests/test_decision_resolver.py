"""resolve_decision parsing/validation — the context-aware judge (no runtime gate).

skip / show_others / unclear validate through; off-vocabulary or an LLM failure
degrade to the SAFE 'unrelated'; an empty-change edit → 'unclear' (ambiguous about the
card). The recent conversation is passed into the prompt. There is NO second 'verify'
call — the strong model + negatives + context hold the approve boundary on their own
(locked by the live regression test_decision_judge_live)."""
import json

import pytest

import app.agent.decision_resolver as dr
from app.agent.decision_resolver import resolve_decision


def _wire_gateway(monkeypatch, payload):
    """Mock the single gateway call + record the prompt sent (to assert context flows in
    and that only ONE call is made — the verify gate is gone)."""
    rec = {"calls": 0, "prompt": ""}

    async def fake_complete(messages, **kwargs):
        rec["calls"] += 1
        rec["prompt"] = messages[0]["content"]
        return {"choices": [{"message": {"content": json.dumps(payload)}}]}

    monkeypatch.setattr(dr.llm_gateway, "complete", fake_complete)
    return rec


@pytest.mark.parametrize("intent", ["approve", "reject", "skip", "show_others", "unclear", "unrelated"])
async def test_resolve_parses_valid_intents(monkeypatch, intent):
    rec = _wire_gateway(monkeypatch, {"intent": intent, "change": ""})
    res = await resolve_decision("email_reply", {}, "d", "msg")
    assert res.intent == intent
    assert rec["calls"] == 1  # ONE call — no verify gate


async def test_resolve_edit_with_change(monkeypatch):
    _wire_gateway(monkeypatch, {"intent": "edit", "change": "make it shorter"})
    res = await resolve_decision("email_reply", {}, "d", "shorter please")
    assert res.intent == "edit" and res.change == "make it shorter"


async def test_resolve_edit_without_change_degrades_to_unclear(monkeypatch):
    # An edit with no concrete change isn't actionable → ambiguous about the card → re-ask.
    _wire_gateway(monkeypatch, {"intent": "edit", "change": ""})
    res = await resolve_decision("email_reply", {}, "d", "hmm change it")
    assert res.intent == "unclear"


async def test_resolve_offvocab_degrades_to_unrelated(monkeypatch):
    _wire_gateway(monkeypatch, {"intent": "frobnicate"})
    res = await resolve_decision("email_reply", {}, "d", "??")
    assert res.intent == "unrelated"


async def test_resolve_llm_failure_degrades_to_unrelated(monkeypatch):
    async def boom(**k):
        raise RuntimeError("gateway down")

    monkeypatch.setattr(dr.llm_gateway, "complete", boom)
    res = await resolve_decision("email_reply", {}, "d", "send it")
    assert res.intent == "unrelated"  # NEVER auto-approve on a resolver failure


async def test_recent_context_is_passed_into_the_prompt(monkeypatch):
    rec = _wire_gateway(monkeypatch, {"intent": "unclear", "change": ""})
    await resolve_decision(
        "email_reply", {}, "d", "right, the Q3 numbers",
        "Assistant: Shall I send the Priya reply about Q3, Sir?",
    )
    assert "Shall I send the Priya reply" in rec["prompt"]  # context reached the judge
    assert "RECENT CONVERSATION" in rec["prompt"]


async def test_empty_context_renders_a_placeholder(monkeypatch):
    rec = _wire_gateway(monkeypatch, {"intent": "approve", "change": ""})
    await resolve_decision("email_reply", {}, "d", "send it")  # no context
    assert "(no recent conversation)" in rec["prompt"]
