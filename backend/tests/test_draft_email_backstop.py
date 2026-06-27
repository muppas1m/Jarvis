"""#3 — "draft an email" reliably produces a CARD, not prose.

The prompt mandates the card, but the model still sometimes writes the draft as chat text with
no email_send call (the describe-instead-of-call drop, silent in voice). The structural backstop
in agent_node catches it post-response: on a clear draft/send-email imperative that returned an
email-shaped reply with no email_send call, it re-prompts ONCE to force the call; if it still
drops, it makes the offer explicit — never a silent drop.
"""
import pytest
from langchain_core.messages import AIMessage, SystemMessage

from app.agent.nodes import (
    _append_queue_offer,
    _draft_email_backstop,
    _is_draft_email_drop,
    _is_draft_email_imperative,
    _is_email_shaped,
)

_DRAFT = "Subject: Project delay\n\nHi Bob,\n\nThe project will slip a week.\n\nBest,\nM"


class _FakeLLM:
    """ainvoke returns scripted responses in order."""
    def __init__(self, responses):
        self._responses = list(responses)

    async def ainvoke(self, _msgs):
        return self._responses.pop(0)


def test_imperative_detection():
    for yes in ["draft an email to Bob", "write an email to him", "send an email to alice@x.com",
                "reply to Priya's email", "email her about the delay", "compose a message to the team"]:
        assert _is_draft_email_imperative(yes), yes
    for no in ["what is the capital of France", "what would you say to Bob?",
               "summarize the contract", "add a task to call the dentist"]:
        assert not _is_draft_email_imperative(no), no


def test_email_shape_detection():
    assert _is_email_shaped(_DRAFT)  # subject + salutation + sign-off
    assert _is_email_shaped("Hi Bob,\n\nThanks for the update.\n\nRegards,\nM")
    # a normal answer with a stray "hi" is NOT email-shaped (needs ≥2 signals)
    assert not _is_email_shaped("Hi Sir, the capital of France is Paris.")
    assert not _is_email_shaped("Here are three options to consider.")


def test_drop_detection_requires_both_imperative_and_shape():
    prose = AIMessage(content=_DRAFT)
    assert _is_draft_email_drop("draft an email to Bob", prose)
    assert not _is_draft_email_drop("what would you say to Bob?", prose)  # not an imperative
    assert not _is_draft_email_drop("draft an email to Bob", AIMessage(content="Queued it, Sir."))  # not shaped


@pytest.mark.asyncio
async def test_backstop_forces_the_call_on_retry():
    # 1st response = prose drop; retry = an email_send tool_call → the tool_call REPLACES the prose.
    state = {"user_message": "draft an email to Bob about the delay", "thread_id": "web:t"}
    prose = AIMessage(content=_DRAFT)
    tool_call = AIMessage(content="", tool_calls=[
        {"name": "email_send", "args": {"to": "bob@x.com", "subject": "Project delay", "body": "…"}, "id": "c1"},
    ])
    llm = _FakeLLM([tool_call])
    out = await _draft_email_backstop(state, prose, llm, [SystemMessage(content="sys")])
    # the tool_call (leak-stripped copy) replaces the prose; the prose draft is dropped
    assert getattr(out, "tool_calls", None) and out.tool_calls[0]["name"] == "email_send"
    assert out.content == ""


@pytest.mark.asyncio
async def test_backstop_appends_offer_when_retry_still_drops():
    # retry STILL returns prose (no tool call) → never a silent drop: the original draft + an
    # explicit "say the word" offer.
    state = {"user_message": "write an email to Bob", "thread_id": "web:t"}
    prose = AIMessage(content=_DRAFT)
    llm = _FakeLLM([AIMessage(content="Hi Bob,\n\nStill prose.\n\nBest,\nM")])
    out = await _draft_email_backstop(state, prose, llm, [SystemMessage(content="sys")])
    assert not getattr(out, "tool_calls", None)
    assert _DRAFT in out.content and "say the word" in out.content.lower()


@pytest.mark.asyncio
async def test_backstop_noop_when_not_a_drop():
    # A normal answer (no draft imperative) → no retry, response unchanged. Also: if the model
    # ALREADY called email_send, the backstop must not fire.
    state = {"user_message": "what's the capital of France?", "thread_id": "web:t"}
    normal = AIMessage(content="Paris, Sir.")
    called = _FakeLLM([])  # ainvoke must NOT be called → empty would IndexError if it were
    assert await _draft_email_backstop(state, normal, called, []) is normal

    already = AIMessage(content="", tool_calls=[{"name": "email_send", "args": {}, "id": "x"}])
    assert await _draft_email_backstop({"user_message": "send an email to Bob"}, already, called, []) is already


def test_append_queue_offer():
    out = _append_queue_offer(AIMessage(content="the draft"))
    assert out.content.startswith("the draft") and "haven't queued" in out.content
