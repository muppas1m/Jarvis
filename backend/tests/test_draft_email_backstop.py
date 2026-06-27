"""#3 — "draft an email" reliably produces a CARD, not prose.

The structural backstop in agent_node catches the describe-instead-of-call drop post-response.
Primary signal: an email-SHAPED reply (a Subject: line, or salutation + formal sign-off — which
whatsapp/SMS lack). Gated by: NOT see-only/meta on the latest turn (prose is right there), AND a
recent email-COMPOSE context (email-native verbs reply/respond/get-back on their own; ambiguous
verbs draft/write/send only with an email token or @-address). Response-shape-first catches reply
phrasing AND the multi-turn follow-up drop in one move, and won't fire on a non-email channel.
"""
import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from app.agent.nodes import (
    _append_queue_offer,
    _draft_email_backstop,
    _is_draft_email_drop,
    _is_email_compose_intent,
    _is_email_shaped,
)

_DRAFT = "Subject: Project delay\n\nHi Bob,\n\nThe project will slip a week.\n\nBest,\nM"


def _state(user_message, *prior_user_messages):
    """A turn state: prior user turns (oldest→newest) + the current user message in `messages`."""
    msgs = [HumanMessage(content=m) for m in (*prior_user_messages, user_message)]
    return {"user_message": user_message, "thread_id": "web:t", "messages": msgs}


class _FakeLLM:
    """ainvoke returns scripted responses in order."""
    def __init__(self, responses):
        self._responses = list(responses)

    async def ainvoke(self, _msgs):
        return self._responses.pop(0)


def test_compose_intent_detection():
    # email-native verbs are email on their own (the most common email action); ambiguous verbs
    # need an email token or an @-address.
    for yes in ["reply to Priya", "respond to her", "draft a reply to the boss", "get back to him",
                "draft an email to Bob", "send an email to alice@x.com", "email her about the delay",
                "send a note to bob@example.com"]:
        assert _is_email_compose_intent(yes), yes
    for no in ["what is the capital of France", "summarize this email thread", "add a task",
               "send a message to Bob", "compose a message to the team", "leave a note for Alice"]:
        assert not _is_email_compose_intent(no), no


def test_email_shape_detection():
    assert _is_email_shaped(_DRAFT)                                    # has a Subject: line
    assert _is_email_shaped("Subject: Lunch?\n\nAre you free?")        # Subject alone
    assert _is_email_shaped("Hi Bob,\n\nThanks for the update.\n\nRegards,\nM")  # salutation + sign-off
    assert not _is_email_shaped("Hi Sir, the capital of France is Paris.")  # salutation only
    assert not _is_email_shaped("Here are three options to consider.")  # neither


def test_drop_fires_on_reply_phrasing_with_no_email_word():
    # The over-correction this fixes: "reply to Priya" (no literal "email") must fire.
    prose = AIMessage(content=_DRAFT)
    for msg in ["reply to Priya", "respond to her", "draft a reply to the boss", "get back to him",
                "draft an email to Bob"]:
        assert _is_draft_email_drop(_state(msg), prose), msg


def test_drop_fires_on_multiturn_followup():
    # The master's #4 follow-up: compose intent is in a PRIOR turn; the follow-up isn't an imperative.
    prose = AIMessage(content=_DRAFT)
    for followup in ["okay send it", "go ahead", "you know the context right", "bob@example.com"]:
        st = _state(followup, "send an email to my manager about the Q3 slip")
        assert _is_draft_email_drop(st, prose), followup


def test_no_drop_when_reply_is_not_email_shaped():
    # a normal (non-email-shaped) reply is never a drop, even in a compose context
    assert not _is_draft_email_drop(_state("draft an email to Bob"), AIMessage(content="Queued it, Sir."))


def test_no_drop_for_see_only_meta_or_non_email():
    prose = AIMessage(content=_DRAFT)  # email-shaped → only the gates can stop a fire
    for see_only in ["just show me a draft email to Bob, don't send it",
                     "draft an email to her without sending"]:
        assert not _is_draft_email_drop(_state(see_only), prose), see_only
    for meta in ["how do I write a formal email to my boss?",
                 "what's a good way to write an email to a client?"]:
        assert not _is_draft_email_drop(_state(meta), prose), meta
    # non-email channel → no compose context (a real whatsapp reply would also lack a sign-off)
    assert not _is_draft_email_drop(_state("send a message to Bob saying I'll be late"), prose)
    # summarizing an email thread is not compose intent
    assert not _is_draft_email_drop(_state("summarize this email thread"), prose)


@pytest.mark.asyncio
async def test_backstop_forces_the_call_on_retry():
    # 1st response = prose drop; retry = an email_send tool_call → the tool_call REPLACES the prose.
    prose = AIMessage(content=_DRAFT)
    tool_call = AIMessage(content="", tool_calls=[
        {"name": "email_send", "args": {"to": "bob@x.com", "subject": "Project delay", "body": "…"}, "id": "c1"},
    ])
    out = await _draft_email_backstop(
        _state("draft an email to Bob about the delay"), prose, _FakeLLM([tool_call]),
        [SystemMessage(content="sys")],
    )
    assert getattr(out, "tool_calls", None) and out.tool_calls[0]["name"] == "email_send"
    assert out.content == ""  # the prose draft is dropped; the card is the review surface


@pytest.mark.asyncio
async def test_backstop_appends_offer_when_retry_still_drops():
    prose = AIMessage(content=_DRAFT)
    llm = _FakeLLM([AIMessage(content="Hi Bob,\n\nStill prose.\n\nBest,\nM")])
    out = await _draft_email_backstop(_state("write an email to Bob"), prose, llm, [SystemMessage(content="sys")])
    assert not getattr(out, "tool_calls", None)
    assert _DRAFT in out.content and "say the word" in out.content.lower()


@pytest.mark.asyncio
async def test_backstop_noop_when_not_a_drop():
    called = _FakeLLM([])  # ainvoke must NOT be called → empty would IndexError if it were
    # a normal answer (not email-shaped) → no retry, response unchanged
    normal = AIMessage(content="Paris, Sir.")
    assert await _draft_email_backstop(_state("what's the capital of France?"), normal, called, []) is normal
    # already called email_send → backstop must not fire
    already = AIMessage(content="", tool_calls=[{"name": "email_send", "args": {}, "id": "x"}])
    assert await _draft_email_backstop(_state("send an email to Bob"), already, called, []) is already


def test_append_queue_offer():
    out = _append_queue_offer(AIMessage(content="the draft"))
    assert out.content.startswith("the draft") and "haven't queued" in out.content
