"""Memory-extraction quality gate (2026-06-25 cut).

The owned extractor (app.memory.extraction) replaced Mem0's ADDITIVE infer=True
path, which measured ~6 facts/turn at ~90% junk on live turns. This is the
repeatable gate that pins the new behaviour: over a replay set of archetypal turns
the extractor must stay precision-first (<= 2 facts/turn), emit ZERO forbidden-
category facts, retain durable facts (fact-bearing turns non-empty + recalled above
the 0.5 gate), suppress junk (command / Q&A / outcome / pleasantry turns -> empty),
and fact-level dedup must fire on an identical re-write.

The gate calls the real extractor (Gemini via the gateway) — non-deterministic, but
the archetypes are unambiguous and the call runs at temperature=0 with a fallback.
Cleanup is reliable direct-SQL by the marker thread_id (Mem0 v2 delete()/get_all()
can't be trusted for teardown — see test_memory_recall_integration._wipe_thread).
"""
import uuid

import pytest
from sqlalchemy import text

from app.config import settings
from app.db.engine import async_session
from app.memory.extraction import extract_facts, is_forbidden_fact
from app.memory.manager import MemoryManager


# (label, user, assistant, expects_fact). expects_fact True = a durable USER fact
# must be extracted; False = nothing durable (command / Q&A / outcome / pleasantry).
REPLAY_SET = [
    ("fact_health", "I'm allergic to shellfish, please keep that in mind.",
     "Noted, Sir — I'll remember you're allergic to shellfish.", True),
    ("fact_pref", "I really love reading science fiction, especially space operas.",
     "Noted, Sir.", True),
    ("relationship", "My wife Sarah's birthday is March 3rd.",
     "I'll remember Sarah's birthday is March 3rd, Sir.", True),
    ("mixed", "I'm vegetarian, so order me lunch from the usual place.",
     "Done, Sir — I've placed a vegetarian lunch order.", True),
    ("command", "Send an email to John about the meeting.",
     "I've queued that email for your approval, Sir.", False),
    ("qa", "What's the distance from here to Orlando?",
     "It is about 85 miles, Sir.", False),
    ("task_outcome", "Did the email go out?",
     "Yes Sir, the email to John was sent successfully.", False),
    ("calendar_debug", "Check if my calendar works — create a test event.",
     "I've created a test event titled 'Test Event', Sir.", False),
    ("assistant_heavy", "What do you recommend for dinner?",
     "I'd recommend the Italian place on Main St, Sir — great pasta.", False),
    ("pleasantry_nontrivial", "Haha that's a good one, tell me another.",
     "Glad you enjoyed it, Sir.", False),
]


# --- pure + fast: the deterministic post-filter backstop ---------------------
@pytest.mark.parametrize("fact,forbidden", [
    # observed live junk → MUST be caught
    ("Assistant created a test calendar event titled 'Test Event'.", True),
    ("Assistant deleted the test calendar event.", True),
    ("User asked the assistant if it was working.", True),
    ("User inquired about weekend plans.", True),
    ("User approved the test email.", True),
    ("User requested to send a test email, which was successfully delivered.", True),
    ("User's weekend has no scheduled events or plans.", True),
    ("User wants to send an email.", True),
    # real durable facts → MUST NOT be caught (precision)
    ("User is allergic to shellfish.", False),
    ("User is vegetarian.", False),
    ("User's wife is named Sarah.", False),
    ("User wants to lose weight this year.", False),         # a goal, not a tool-command
    ("User is scheduled for surgery on March 3rd.", False),  # 'is scheduled' must not trip the outcome rule
    ("User loves science fiction.", False),
])
def test_post_filter_classifies_forbidden_vs_durable(fact, forbidden):
    assert is_forbidden_fact(fact) is forbidden


# --- the quality gate: the real extractor over the replay set ----------------
@pytest.mark.asyncio
async def test_extraction_quality_gate():
    results = []
    for label, user, asst, expects in REPLAY_SET:
        facts = await extract_facts(user, asst)
        results.append((label, expects, facts))

    facts_per_turn = sum(len(f) for _, _, f in results) / len(results)
    forbidden = [f for _, _, fs in results for f in fs if is_forbidden_fact(f)]

    # (1) volume — owned extraction is precision-first (the old path was ~6/turn)
    assert facts_per_turn <= 2.0, f"facts/turn={facts_per_turn:.2f} (>2); detail={results}"
    # (2) zero forbidden-category facts survive (LLM + post-filter)
    assert not forbidden, f"forbidden facts leaked: {forbidden}"
    # (3) durable retention + junk suppression, per archetype
    for label, expects, facts in results:
        if expects:
            assert facts, f"[{label}] expected a durable fact, got none"
        else:
            assert not facts, f"[{label}] expected NO fact, got {facts}"


# --- retention end-to-end: an extracted fact recalls above the 0.5 gate -------
@pytest.mark.asyncio
async def test_extracted_fact_recalls_above_gate():
    mgr = MemoryManager()
    thread = f"test-extract-{uuid.uuid4().hex[:8]}"
    try:
        facts = await extract_facts(
            "I'm allergic to shellfish, please keep that in mind.", "Noted, Sir."
        )
        assert facts, "expected an allergy fact from a clear fact-stating turn"
        for f in facts:
            await mgr.mem0.add_fact(f, thread_id=thread)
        hits = await mgr.mem0.search(query="what am I allergic to?", top_k=5)
        best = max((h["score"] for h in hits), default=0.0)
        assert best >= settings.MEM0_RECALL_THRESHOLD, (
            f"extracted allergy fact recalled at {best:.3f} < gate "
            f"{settings.MEM0_RECALL_THRESHOLD}"
        )
    finally:
        await _wipe_thread(thread)


# --- fact-level dedup fires (the granularity fix; was 0 skips/48h) ------------
@pytest.mark.asyncio
async def test_fact_level_dedup_fires():
    mgr = MemoryManager()
    thread = f"test-dedup-{uuid.uuid4().hex[:8]}"
    try:
        fact = f"User's lucky token for thread {thread} is forty-two."
        r1 = await mgr.mem0.add_fact(fact, thread_id=thread)
        assert not (isinstance(r1, dict) and r1.get("skipped_duplicate")), "first write skipped"
        # identical re-write → fact-level dedup must skip (the old turn-blob path never did)
        r2 = await mgr.mem0.add_fact(fact, thread_id=thread)
        assert isinstance(r2, dict) and r2.get("skipped_duplicate") is True, (
            f"identical fact re-write was not deduped: {r2}"
        )
    finally:
        await _wipe_thread(thread)


async def _wipe_thread(thread_id: str) -> None:
    async with async_session() as session:
        await session.execute(
            text("DELETE FROM mem0_memories WHERE payload->>'thread_id' = :t"),
            {"t": thread_id},
        )
        await session.commit()
