

def test_approval_linkage_exposed_on_message_items():
    """Item #8 (γ-3): an AI message carrying the persisted jarvis approval tag exposes
    approval_ids on its /history item; untagged messages don't."""
    from langchain_core.messages import AIMessage

    from app.agent.runner import _serialize_message
    tagged = AIMessage(content="queued — shall I go ahead?",
                       additional_kwargs={"jarvis": {"type": "approval",
                                                     "approval_ids": ["a1", "a2"],
                                                     "mint_class": "fresh", "solicited": True}})
    out = _serialize_message(tagged)
    assert out["approval_ids"] == ["a1", "a2"]
    plain = _serialize_message(AIMessage(content="hello"))
    assert "approval_ids" not in plain
    # a question tag is NOT an approval linkage for this surface
    q = AIMessage(content="which one?", additional_kwargs={"jarvis": {"type": "question",
                                                                      "state": "open",
                                                                      "candidate_ids": ["x"]}})
    assert "approval_ids" not in _serialize_message(q)
