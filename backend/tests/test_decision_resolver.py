"""resolve_decision parsing/validation + the APPROVE verification gate.

The new skip / show_others intents validate through; off-vocabulary, an empty-change
edit, or an LLM failure degrade to the SAFE 'unrelated'. And the defence-in-depth on
the highest-harm path: an approve from the multi-class judge is downgraded to
'unrelated' unless the STRICT verify gate also confirms an explicit command — and the
gate fails CLOSED (a verify error → not approved). An ambiguous ack NEVER reaches
approve.
"""
import json

import pytest

import app.agent.decision_resolver as dr
from app.agent.decision_resolver import resolve_decision


def _wire_gateway(monkeypatch, payload, *, verify=True):
    """Mock the gateway. resolve_decision makes TWO calls on the approve path: the
    multi-class classify, then the strict verify gate (its prompt contains
    'explicit_go'). `verify` controls the gate's answer so approve is exercisable both
    ways; non-approve intents make only the one classify call."""
    async def fake_complete(messages, **kwargs):
        content = messages[0]["content"]
        if "explicit_go" in content:  # the verify gate
            return {"choices": [{"message": {"content": json.dumps({"explicit_go": verify})}}]}
        return {"choices": [{"message": {"content": json.dumps(payload)}}]}

    monkeypatch.setattr(dr.llm_gateway, "complete", fake_complete)


@pytest.mark.parametrize("intent", ["approve", "reject", "skip", "show_others", "unrelated"])
async def test_resolve_parses_valid_intents(monkeypatch, intent):
    _wire_gateway(monkeypatch, {"intent": intent, "change": ""})  # verify confirms by default
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


# --- the approve verification gate (defence-in-depth) ------------------------
async def test_approve_downgraded_when_verify_says_no(monkeypatch):
    """The judge says approve but the STRICT gate says NO (a topic echo / soft yes
    that slipped the first pass) → downgraded to unrelated. The whole point."""
    _wire_gateway(monkeypatch, {"intent": "approve", "change": ""}, verify=False)
    res = await resolve_decision("email_reply", {}, "d", "right, the Q3 numbers")
    assert res.intent == "unrelated"


async def test_approve_passes_only_when_verify_confirms(monkeypatch):
    _wire_gateway(monkeypatch, {"intent": "approve", "change": ""}, verify=True)
    res = await resolve_decision("email_reply", {}, "d", "send it")
    assert res.intent == "approve"


async def test_verify_gate_fails_closed_on_error(monkeypatch):
    """The classify says approve; the verify CALL raises → fail closed → unrelated.
    A gateway hiccup on the gate must never let an approve through."""
    async def fake_complete(messages, **kwargs):
        if "explicit_go" in messages[0]["content"]:
            raise RuntimeError("verify gateway down")
        return {"choices": [{"message": {"content": json.dumps({"intent": "approve"})}}]}

    monkeypatch.setattr(dr.llm_gateway, "complete", fake_complete)
    res = await resolve_decision("email_reply", {}, "d", "send it")
    assert res.intent == "unrelated"  # verify failed closed → never approve


async def test_non_approve_intents_skip_the_verify_gate(monkeypatch):
    """The verify gate runs ONLY on approve — a reject/skip never triggers a second
    call (asserted by raising if the verify prompt is ever sent)."""
    async def fake_complete(messages, **kwargs):
        if "explicit_go" in messages[0]["content"]:
            raise AssertionError("verify gate must NOT run for non-approve intents")
        return {"choices": [{"message": {"content": json.dumps({"intent": "reject"})}}]}

    monkeypatch.setattr(dr.llm_gateway, "complete", fake_complete)
    res = await resolve_decision("email_reply", {}, "d", "no, cancel that")
    assert res.intent == "reject"
