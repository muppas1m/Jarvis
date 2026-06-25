"""resolve_decision parsing/validation — the new skip / show_others intents
validate through, and anything off-vocabulary, an empty-change edit, or an LLM
failure degrades to the SAFE 'unrelated' (NEVER an auto-approve)."""
import json

import pytest

import app.agent.decision_resolver as dr
from app.agent.decision_resolver import resolve_decision


def _wire_gateway(monkeypatch, payload):
    async def fake_complete(**kwargs):
        return {"choices": [{"message": {"content": json.dumps(payload)}}]}

    monkeypatch.setattr(dr.llm_gateway, "complete", fake_complete)


@pytest.mark.parametrize("intent", ["approve", "reject", "skip", "show_others", "unrelated"])
async def test_resolve_parses_valid_intents(monkeypatch, intent):
    _wire_gateway(monkeypatch, {"intent": intent, "change": ""})
    res = await resolve_decision("email_reply", {}, "d", "msg")
    assert res.intent == intent


async def test_resolve_edit_with_change(monkeypatch):
    _wire_gateway(monkeypatch, {"intent": "edit", "change": "make it shorter"})
    res = await resolve_decision("email_reply", {}, "d", "shorter please")
    assert res.intent == "edit" and res.change == "make it shorter"


async def test_resolve_edit_without_change_degrades_to_unrelated(monkeypatch):
    # An edit with no concrete change isn't actionable → ambiguous → unrelated.
    _wire_gateway(monkeypatch, {"intent": "edit", "change": ""})
    res = await resolve_decision("email_reply", {}, "d", "hmm")
    assert res.intent == "unrelated"


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
