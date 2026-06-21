"""
Mem0 STORE-quality integration tests (4.B.2 — the write side) — real Mem0, real
Postgres + pgvector, extraction LLM bypassed.

Companion to test_memory_recall_integration.py (the read side). What this locks:
  - get_all() returns the FULL corpus, not Mem0's default top_k=20 truncation.
  - dedup-on-write skips a near-identical fact and keeps a distinct one.

infer=False everywhere for the same reason as the recall suite: deterministic
verbatim writes, no Gemini-extraction RPM dependency. Cleanup is reliable
direct-SQL by the marker thread_id (Mem0 v2's delete()/get_all() can't be trusted
for teardown — see test_memory_recall_integration._wipe_thread).
"""
import uuid

import numpy as np
import pytest
from sqlalchemy import text

from app.config import settings
from app.db.engine import async_session
from app.memory.consolidation import _auto_decision, _cluster, _norm, _Row
from app.memory.manager import MemoryManager


@pytest.fixture
async def mem_manager():
    return MemoryManager()


@pytest.fixture
async def test_thread_id():
    return f"test-storeq-{uuid.uuid4().hex[:8]}"


async def _wipe_thread(thread_id: str) -> None:
    """Reliable Mem0 teardown: direct SQL on the marker thread_id."""
    async with async_session() as session:
        await session.execute(
            text("DELETE FROM mem0_memories WHERE payload->>'thread_id' = :t"),
            {"t": thread_id},
        )
        await session.commit()


@pytest.fixture
async def memory_cleanup(test_thread_id):
    yield
    await _wipe_thread(test_thread_id)


async def _add_no_infer(mem_manager: MemoryManager, content: str, thread_id: str) -> None:
    """Write content verbatim as a memory row tagged with thread_id (skips the
    extraction LLM). Goes through the raw Mem0 client so dedup-on-write is NOT
    exercised here — tests that want dedup call mem_manager.mem0.add directly."""
    await mem_manager.mem0.client.add(
        messages=[{"role": "user", "content": content}],
        user_id=mem_manager.mem0.USER_ID,
        metadata={"thread_id": thread_id},
        infer=False,
    )


@pytest.mark.asyncio
async def test_get_all_returns_full_corpus_not_capped(
    mem_manager: MemoryManager,
    test_thread_id: str,
    memory_cleanup,
) -> None:
    """get_all() must return the ENTIRE corpus, not Mem0's silent default
    top_k=20. Write >20 rows under one marker thread; every one must come back.

    Pre-fix (4.B.2): get_all() passed no top_k → Mem0 returned 20 of ~1.4k, so
    consolidation/conflict-detection would have processed a 20-row subset and
    corrupted the store."""
    n = 25  # deliberately above the old default-20 cap
    for i in range(n):
        await _add_no_infer(
            mem_manager,
            content=f"Store-quality probe fact #{i} for thread {test_thread_id}.",
            thread_id=test_thread_id,
        )

    rows = await mem_manager.mem0.get_all()
    mine = [r for r in rows if (r.get("metadata") or {}).get("thread_id") == test_thread_id]

    assert len(mine) == n, (
        f"get_all returned {len(mine)} of {n} rows for the marker thread "
        f"(total returned={len(rows)}). The default top_k=20 truncation is not fixed."
    )
    # The whole corpus is well past the old cap — a direct guard against a 20-cap.
    assert len(rows) > 20, f"get_all returned only {len(rows)} rows total — still capped."
    assert len(rows) <= settings.MEM0_GET_ALL_LIMIT, "corpus reached the configured bound"


def test_extraction_custom_instructions_wired() -> None:
    """Auto-save scoping (4.B.2) depends on Mem0 receiving our durable-facts
    extraction rules. Lock the WIRING so a config refactor can't silently drop
    them. (Extraction behavior itself is LLM-measured — 7→3 facts/turn on a
    representative mix — not unit-tested, since the extraction LLM is
    non-deterministic.)"""
    from app.memory.mem0_client import JARVIS_EXTRACTION_INSTRUCTIONS, _mem0_config

    cfg = _mem0_config()
    assert cfg.get("custom_instructions") == JARVIS_EXTRACTION_INSTRUCTIONS, (
        "Mem0 config no longer carries the durable-facts extraction rules — "
        "auto-save would fall back to the noisy default prompt."
    )
    ci = JARVIS_EXTRACTION_INSTRUCTIONS.lower()
    # the load-bearing guards must survive any future edit to the rules
    assert "durable" in ci
    assert "assistant" in ci          # "Assistant line is context only" guard
    assert "do not extract" in ci


@pytest.mark.asyncio
async def test_dedup_skips_true_duplicate_keeps_distinct(
    mem_manager: MemoryManager,
    test_thread_id: str,
    memory_cleanup,
    monkeypatch,
) -> None:
    """Dedup-on-write (4.B.2) skips a near-identical re-write but lets a genuinely
    distinct fact through. Hermetic — forces the calibrated gate on regardless of
    the deployment default, so the test pins the LOGIC, not the env.

    Calibration (true post-4.B.1 cosines): duplicates 0.972-1.0; contradictions
    up to 0.958; distinct facts <= 0.93. 0.97 skips dups, keeps the rest."""
    monkeypatch.setattr(settings, "MEM0_DEDUP_ENABLED", True)
    monkeypatch.setattr(settings, "MEM0_DEDUP_THRESHOLD", 0.97)

    ns = f"Qmark{test_thread_id[-6:]}"  # unique token → these rows isolate from the corpus
    seed = f"{ns}. The user's lucky number is forty-two."
    await _add_no_infer(mem_manager, seed, test_thread_id)  # verbatim seed in the store

    # (1) exact re-write → dedup search finds the seed (~1.0) → SKIPPED before any
    #     extraction (returns early, no LLM call).
    r_dup = await mem_manager.mem0.add(content=seed, thread_id=test_thread_id)
    assert r_dup.get("skipped_duplicate") is True, f"true duplicate not skipped: {r_dup}"

    # (2) a genuinely distinct fact (its own unique token → no near neighbor) stays
    #     BELOW the gate, so it would be stored, not skipped. Checked via the same
    #     search the gate uses — no extraction-LLM call, fully deterministic.
    distinct = f"Zflux{test_thread_id[-6:]}. The user collects vintage typewriters."
    hits = await mem_manager.mem0.search(query=distinct, top_k=1)
    nearest = hits[0]["score"] if hits else 0.0
    assert nearest < settings.MEM0_DEDUP_THRESHOLD, (
        f"a distinct fact's nearest neighbor scored {nearest:.4f} >= the dedup gate "
        f"({settings.MEM0_DEDUP_THRESHOLD}) — it would be wrongly skipped."
    )


# --------------------------------------------------------------------------- #
# Consolidation engine — deterministic core (clustering + auto-merge). The LLM
# adjudication path is non-deterministic and exercised by the dry-run, not here.
# --------------------------------------------------------------------------- #
def _row(mem_id: str, content: str, created_at: str, vec: np.ndarray) -> _Row:
    return _Row(mem_id=mem_id, content=content, created_at=created_at, vector=vec)


def test_consolidation_clusters_similar_excludes_distinct() -> None:
    """_cluster groups near-identical vectors and leaves a distinct one out
    (singletons are nothing to consolidate)."""
    near = np.array([1.0, 0.0, 0.0, 0.02], dtype=np.float32)
    rows = [
        _row("a", "x", "2026-01-01", np.array([1.0, 0.0, 0.0, 0.00], dtype=np.float32)),
        _row("b", "x", "2026-01-02", near),
        _row("c", "x", "2026-01-03", np.array([1.0, 0.0, 0.0, 0.04], dtype=np.float32)),
        _row("d", "y", "2026-01-04", np.array([0.0, 1.0, 0.0, 0.00], dtype=np.float32)),  # orthogonal
    ]
    clusters = _cluster(rows, threshold=0.99)
    assert len(clusters) == 1, f"expected one cluster, got {clusters}"
    assert set(clusters[0]) == {0, 1, 2}, "the orthogonal 'd' must not be clustered"


def test_consolidation_auto_merge_keeps_newest_drops_rest() -> None:
    """A cluster whose rows are the SAME normalized text is pure re-extraction:
    auto-merge keeps the newest and drops the rest, confidence 1.0, no LLM."""
    v = np.ones(4, dtype=np.float32)
    cluster = [
        _row("old", "User's name is Mahesh", "2026-01-01T00:00:00", v),
        _row("mid", "User's name is Mahesh.", "2026-01-02T00:00:00", v),   # same after _norm
        _row("new", "user's name is mahesh", "2026-01-03T00:00:00", v),    # same after _norm
    ]
    decision = _auto_decision(cluster)
    assert decision is not None, "identical-text cluster should auto-merge"
    assert decision.confidence == 1.0
    assert {d.drop_id for d in decision.drops} == {"old", "mid"}, "must keep the newest ('new')"
    assert all(d.folds_into_id == "new" for d in decision.drops)
    assert all(d.reason == "duplicate" for d in decision.drops)


def test_consolidation_auto_merge_refuses_varying_text() -> None:
    """A cluster with DIFFERENT facts must NOT auto-merge — it returns None so the
    decision goes to the (conservative) LLM, never an unsupervised drop. This is
    the guard against silently dropping a distinct fact."""
    v = np.ones(4, dtype=np.float32)
    cluster = [
        _row("a", "User likes coffee", "2026-01-01T00:00:00", v),
        _row("b", "User likes tea", "2026-01-02T00:00:00", v),
    ]
    assert _auto_decision(cluster) is None
    assert _norm("User's name is Mahesh.") == _norm("user's name is  mahesh")
