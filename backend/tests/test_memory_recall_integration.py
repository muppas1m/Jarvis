"""
Memory-recall integration test — real Mem0, real Postgres + pgvector,
extraction LLM bypassed.

What this proves end-to-end:
  - Mem0Client.add → AsyncMemory.add stores rows in pgvector with the
    metadata we passed (thread_id round-trip).
  - MemoryManager.recall semantic search returns the row.
  - The thread_id post-filter in MemoryManager.recall correctly drops
    rows from other threads.

Why infer=False:
  Mem0's default add path runs extracted content through Gemini Flash
  Lite to decide what facts to extract. On Gemini's free-tier RPM cap
  (which we share across tests + production traffic), bursty test runs
  hit the limit and `add()` silently returns `{'results': []}` — the
  extraction calls get queued and flush in opportunistic batches, so
  the test's awaited `add()` returns "success" with no actual rows
  written by the time the assertions run. See
  `project_mem0_extraction_gemini_swap.md`.

  `infer=False` skips the extraction LLM entirely and stores the
  message content verbatim as a memory row. That removes the Gemini
  dependency from the test path and gives us a deterministic write
  whose metadata + recall behavior is exactly what we want to lock
  down. The extraction-path is exercised by smoke_memory.py manually.

Isolation:
  Mem0Client.USER_ID is hardcoded "master" — no user-namespaced axis.
  Namespace via UUID-suffixed thread_id like "test-memrecall-<8 hex>";
  cleanup walks get_all() and deletes any memory whose
  metadata.thread_id matches the test thread.
"""
import uuid

import pytest

from app.config import settings
from app.memory.manager import MemoryManager


@pytest.fixture
async def mem_manager():
    return MemoryManager()


@pytest.fixture
async def test_thread_id():
    return f"test-memrecall-{uuid.uuid4().hex[:8]}"


async def _wipe_thread(thread_id: str) -> None:
    """RELIABLE Mem0 teardown: direct SQL on the marker thread_id.

    The prior pattern (get_all → filter by metadata.thread_id → mem0.delete)
    silently failed and accumulated residue: Mem0 v2's get_all PAGES (so a test's
    entries may not be in the returned page) and its delete() API is flaky. Hitting
    the pgvector backing table by thread_id is deterministic. (Residue cleaned +
    teardown fixed in Turn 20.5b.)"""
    from sqlalchemy import text

    from app.db.engine import async_session

    async with async_session() as session:
        await session.execute(
            text("DELETE FROM mem0_memories WHERE payload->>'thread_id' = :t"),
            {"t": thread_id},
        )
        await session.commit()


@pytest.fixture
async def memory_cleanup(test_thread_id):
    """Yield, then reliably delete any Mem0 entries tagged with the test thread_id."""
    yield
    await _wipe_thread(test_thread_id)


async def _add_no_infer(
    mem_manager: MemoryManager, content: str, thread_id: str
) -> None:
    """Bypass the Mem0 extraction LLM and write the content verbatim as
    a memory row tagged with thread_id. Same vector-store + metadata
    shape as the inference path, just deterministic."""
    await mem_manager.mem0.client.add(
        messages=[{"role": "user", "content": content}],
        user_id=mem_manager.mem0.USER_ID,
        metadata={"thread_id": thread_id},
        infer=False,
    )


@pytest.mark.asyncio
async def test_recall_filters_by_thread_id_and_excludes_other_threads(
    mem_manager: MemoryManager,
    test_thread_id: str,
    memory_cleanup,
) -> None:
    """Two distinct thread_ids, content with overlapping vocabulary.
    recall(query, thread_id=X) must return only memories tagged X."""
    other_thread = f"test-memrecall-other-{uuid.uuid4().hex[:8]}"

    # Same distinctive token in both — they'll both match the embedding
    # search if the post-filter weren't doing its job.
    distinctive = f"Zorblax-{test_thread_id[-6:]}"
    await _add_no_infer(
        mem_manager,
        content=f"User's favorite imaginary creature is the {distinctive}.",
        thread_id=test_thread_id,
    )
    await _add_no_infer(
        mem_manager,
        content=f"User mentioned the {distinctive} in a different conversation.",
        thread_id=other_thread,
    )

    try:
        hits = await mem_manager.recall(
            query=distinctive, thread_id=test_thread_id, k=20
        )
        assert len(hits) >= 1, (
            f"recall(query='{distinctive}', thread_id={test_thread_id!r}) "
            f"returned 0 hits. The memory was added with infer=False so it "
            f"should be findable by exact-token similarity."
        )
        for hit in hits:
            meta = hit.get("metadata") or {}
            assert meta.get("thread_id") == test_thread_id, (
                f"recall returned a memory tagged with "
                f"thread_id={meta.get('thread_id')!r}, expected "
                f"{test_thread_id!r}. Cross-thread leakage."
            )
    finally:
        # Clean up the second thread's memory too — the memory_cleanup fixture
        # only handles test_thread_id. Reliable SQL teardown (see _wipe_thread).
        await _wipe_thread(other_thread)


@pytest.mark.asyncio
async def test_recall_with_unknown_thread_id_returns_empty(
    mem_manager: MemoryManager,
) -> None:
    """A thread_id we never wrote to should produce zero hits. Sanity
    check that the filter actually filters (not no-op'd)."""
    bogus_thread = f"test-never-written-{uuid.uuid4().hex[:8]}"
    hits = await mem_manager.recall(
        query="anything at all",
        thread_id=bogus_thread,
        k=10,
    )
    assert hits == [], (
        f"recall on a bogus thread_id returned {len(hits)} hits — "
        f"the thread_id filter isn't working."
    )


@pytest.mark.asyncio
async def test_search_discriminates_relevant_from_unrelated(
    mem_manager: MemoryManager,
    test_thread_id: str,
    memory_cleanup,
) -> None:
    """The core 4.B.1 proof: a query's genuinely-relevant memory out-scores
    unrelated ones with a CLEAR gap, and is top-ranked.

    Root cause (project_mem0_search_quality_root): Mem0 v2's high-level search
    does HYBRID retrieval and fuses scores `combined = (semantic + bm25) / 2`,
    which halves + compresses the cosine into an indistinguishable ~0.29-0.48
    band — the relevant fact was NOT reliably top-ranked and unrelated noise
    scored the same. `mem0.search` now bypasses that fusion and returns the TRUE
    cosine, so discrimination is restored.

    A rare namespace token isolates these three rows above the live corpus so
    they're retrievable in top-k regardless of corpus size (mirrors the Zorblax
    isolation above; corpus is ~1.4k rows). The assertion is RELATIVE — relevant
    strictly above unrelated, with a gap the old fused path (gaps < ~0.05) could
    not produce."""
    ns = f"Qmark{test_thread_id[-6:]}"  # rare token → ranks our rows above corpus
    relevant = f"{ns}. I am allergic to shellfish - shrimp and crab give me hives."
    unrelated_1 = f"{ns}. My favorite programming language is Rust."
    unrelated_2 = f"{ns}. I usually go hiking in the hills on Sunday mornings."
    for content in (relevant, unrelated_1, unrelated_2):
        await _add_no_infer(mem_manager, content=content, thread_id=test_thread_id)

    query = f"{ns} which foods am I allergic to"
    hits = await mem_manager.mem0.search(query=query, top_k=50)
    ours = {
        h["content"]: h["score"]
        for h in hits
        if (h.get("metadata") or {}).get("thread_id") == test_thread_id
    }

    assert set(ours) == {relevant, unrelated_1, unrelated_2}, (
        f"expected all 3 test rows in top-50, got {sorted(k[:40] for k in ours)}. "
        f"(With the namespace token they should out-rank the live corpus.)"
    )
    rel = ours[relevant]
    top_unrelated = max(ours[unrelated_1], ours[unrelated_2])

    assert rel > top_unrelated, (
        f"relevant fact (cosine={rel:.4f}) did not out-score the best unrelated "
        f"fact (cosine={top_unrelated:.4f}) — search is not discriminating."
    )
    assert rel - top_unrelated >= 0.10, (
        f"score separation {rel - top_unrelated:.4f} < 0.10 — too compressed. "
        f"This is exactly the failure the hybrid-fusion bypass fixes "
        f"(measured ~0.27 post-fix; old fused gaps were < ~0.05)."
    )
    assert rel >= settings.MEM0_RECALL_THRESHOLD, (
        f"relevant fact cosine {rel:.4f} fell below the recall gate "
        f"({settings.MEM0_RECALL_THRESHOLD}) — it would be wrongly dropped."
    )


@pytest.mark.asyncio
async def test_build_context_relevance_gate(
    mem_manager: MemoryManager,
    test_thread_id: str,
    memory_cleanup,
) -> None:
    """build_context injects ONLY memories at/above MEM0_RECALL_THRESHOLD — it no
    longer force-injects the top-10 regardless of score. Proves the recall gate
    added in 4.B.1.

    Robust against the live corpus (no dependence on any single score straddling
    the gate): asserts the gate INVARIANT (everything injected clears the
    threshold) and gate EQUIVALENCE (the injected set is exactly the
    threshold-filtered, non-profile search hits — deterministic embeddings make
    build_context's internal search match a raw search), plus that the
    genuinely-relevant row (cosine ~0.74) still passes the gate."""
    ns = f"Qmark{test_thread_id[-6:]}"
    relevant = f"{ns}. I am allergic to shellfish - shrimp and crab give me hives."
    await _add_no_infer(mem_manager, content=relevant, thread_id=test_thread_id)

    query = f"{ns} which foods am I allergic to"
    raw = await mem_manager.mem0.search(query=query, top_k=10)
    ctx = await mem_manager.build_context(user_message=query)
    injected = ctx["relevant_memories"]
    threshold = settings.MEM0_RECALL_THRESHOLD

    # (1) Invariant: nothing sub-threshold reaches <memories>.
    below = [(round(m["score"], 3), (m.get("content") or "")[:40]) for m in injected if m["score"] < threshold]
    assert not below, f"sub-threshold memories injected into <memories>: {below}"

    # (2) Equivalence: the gate is exactly a threshold filter on the non-profile hits.
    expected_ids = {
        r["id"] for r in raw
        if r["score"] >= threshold and (r["metadata"] or {}).get("kind") != "profile"
    }
    assert {m["id"] for m in injected} == expected_ids, (
        "build_context's injected set is not the threshold-filtered search result "
        "— the recall gate isn't applied consistently."
    )

    # (3) The genuinely-relevant row passed the gate (cosine ~0.74 >> 0.5).
    assert any(m.get("content") == relevant for m in injected), (
        "the relevant memory was wrongly dropped by the recall gate."
    )
