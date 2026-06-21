"""Conversation-compaction core (4.B.3) — deterministic token-count + trim split.

These cover the pure logic that decides WHAT gets summarized + dropped (the
risky part — never lose the recent thread, partition cleanly). The compact_node
itself calls the summarizer LLM (non-deterministic) and is exercised by the live
long-conversation test, not here.
"""
from langchain_core.messages import AIMessage, HumanMessage

from app.agent.nodes import count_message_tokens, split_for_compaction


def _msgs(n: int) -> list:
    """n alternating user/assistant messages, each with an id (RemoveMessage needs ids)."""
    out = []
    for i in range(n):
        cls = HumanMessage if i % 2 == 0 else AIMessage
        out.append(cls(content=f"This is message number {i} carrying a few words.", id=str(i)))
    return out


def test_count_message_tokens_nonzero_and_additive() -> None:
    a = [HumanMessage(content="hello there")]
    b = [HumanMessage(content="hello there"), AIMessage(content="general kenobi, a bold one")]
    na, nb = count_message_tokens(a), count_message_tokens(b)
    assert na > 0
    assert nb > na  # more content → more tokens


def test_split_partitions_and_keeps_recent_suffix() -> None:
    msgs = _msgs(10)
    # budget = exactly the last two messages' tokens → keep ~the recent tail, summarize the rest
    budget = count_message_tokens(msgs[-2:])
    to_summarize, keep = split_for_compaction(msgs, keep_recent_tokens=budget)

    # clean partition, in order
    assert to_summarize + keep == msgs
    # keep is a SUFFIX (the most-recent messages), never empty
    assert keep == msgs[len(msgs) - len(keep):]
    assert len(keep) >= 1
    # something old got peeled off to summarize, and the kept window respects the budget
    assert len(to_summarize) > 0
    assert count_message_tokens(keep) <= budget + count_message_tokens([msgs[-1]])


def test_split_summarizes_nothing_when_under_budget() -> None:
    msgs = _msgs(6)
    to_summarize, keep = split_for_compaction(msgs, keep_recent_tokens=1_000_000)
    assert to_summarize == []
    assert keep == msgs


def test_split_keeps_at_least_the_newest_even_if_it_exceeds_budget() -> None:
    msgs = _msgs(4)
    # an impossibly tight budget must still keep the newest message (never drop everything)
    to_summarize, keep = split_for_compaction(msgs, keep_recent_tokens=1)
    assert len(keep) >= 1
    assert keep[-1] is msgs[-1]
    assert to_summarize + keep == msgs
