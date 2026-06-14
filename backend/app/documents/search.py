"""Hybrid document retrieval — vector + BM25 → RRF fusion → cross-encoder rerank.

This module owns retrieval **policy**. The cheap recall stages (pgvector cosine
+ in-process BM25) over-fetch a candidate pool; Reciprocal Rank Fusion unions
the two ranked lists; the cross-encoder (:mod:`app.documents.reranker`, a pure
scorer) re-scores the pool; and *this module* applies the relevance threshold,
the final ``top_k`` cut, and the dropped-candidate audit log.

Pipeline::

    query
      ├─ vector:  embed(query) → pgvector cosine top RAG_CANDIDATE_POOL
      ├─ bm25:    BM25Okapi over the corpus → top RAG_CANDIDATE_POOL
      ├─ fuse:    Reciprocal Rank Fusion (rank-based union) → top RAG_CANDIDATE_POOL
      ├─ rerank:  bge-reranker-v2-m3 scores every fused candidate (pure scorer)
      └─ policy:  keep rerank_score ≥ threshold, cap to top_k, LOG every drop

**Why RRF, not weighted score fusion.** Cosine similarity is bounded ``[0, 1]``
while BM25 is unbounded and corpus-frequency-dependent; the two live on
incompatible scales. Weighted fusion (``α·norm(cos) + (1-α)·norm(bm25)``)
forces a brittle per-query normalization *and* a magic ``α`` that can only be
tuned against an eval harness we don't have yet (Turn 20.5). RRF is rank-based
and scale-invariant — its only knob (``RAG_RRF_K``, default 60) is a smoothing
constant the literature shows is insensitive. Critically, the cross-encoder is
the precision stage; fusion only needs to maximize *recall into the rerank
pool*, which rank-based union does directly. RRF is the 2026 default for exactly
this two-retriever-into-reranker shape (Elasticsearch ``rrf``, Weaviate hybrid,
LlamaIndex ``QueryFusionRetriever``).

**The threshold logging is the deliverable, not plumbing.** Every candidate the
reranker scores is recorded with its score in the ``rag_search_complete``
structured event — BOTH sides of the cut: ``kept_candidates`` (passed the
threshold) and ``dropped_candidates`` (below threshold or beyond ``top_k``, each
with a ``drop_reason``). Both sides matter because the deferred lifts probe
different sides: the LLM-relevance-grading deferral (see
``project_llm_relevance_grading_deferral.md``) triggers on "reranker
leak-through shows up in eval data" — leak-through being a *kept* chunk that
shouldn't be — while threshold tuning and recall-ceiling analysis read the
*dropped* scores. Logging the kept set as a count only would force any
leak-through analysis to string-parse the agent-facing tool output; the
symmetric arrays keep the whole measurement floor mineable from one event.

**BM25 full-corpus scan — small-corpus assumption (deferred lift).** BM25Okapi
is in-process, so each search loads the entire ``document_chunks`` table to
build the index. That's acceptable for a single-master personal corpus and is
the plan-chosen approach (Task 2.16), but it is O(corpus) per query. ``corpus_size``
is logged on every search and a warning fires past ``_BM25_FULL_SCAN_WARN`` so
the scale cliff is observable rather than silent; the swap to Postgres
``tsvector`` full-text search is the trigger-gated lift when the corpus grows.
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

import litellm
from rank_bm25 import BM25Okapi
from sqlalchemy import select

from app.config import settings
from app.db.engine import async_session
from app.db.models import DocumentChunk
from app.documents.reranker import rerank
from app.utils.logging import get_logger

logger = get_logger(__name__)


# Past this corpus size the BM25 full-table load is a real cost; warn so the
# tsvector-swap trigger is observable instead of a silent latency creep.
_BM25_FULL_SCAN_WARN = 5000


# --------------------------------------------------------------------------- #
# Public API                                                                  #
# --------------------------------------------------------------------------- #
async def search_documents(
    query: str,
    top_k: int | None = None,
    candidate_pool: int | None = None,
    threshold: float | None = None,
) -> list[dict[str, Any]]:
    """Hybrid retrieve → RRF fuse → rerank → threshold + top_k.

    Returns the kept passages as dicts, best (highest ``rerank_score``) first.
    Each dict carries ``chunk_id``, ``document_id``, ``filename``,
    ``chunk_index``, ``content`` (full chunk text), ``meta`` (citation fields:
    ``source_file`` / ``page_start`` / ``page_end`` / ``section_heading``), and
    the per-stage scores (``vector_score``, ``bm25_score``, ``rrf_score``,
    ``rerank_score``). Presentation/truncation is the caller's job — this
    function returns full data.

    Dropped candidates (below threshold or beyond ``top_k``) are NOT returned;
    they are recorded with their scores in the ``rag_search_complete`` log event.
    Empty corpus → ``[]``.
    """
    top_k = settings.RAG_TOP_K if top_k is None else top_k
    candidate_pool = settings.RAG_CANDIDATE_POOL if candidate_pool is None else candidate_pool
    threshold = settings.RAG_RERANK_THRESHOLD if threshold is None else threshold

    start = time.monotonic()

    # --- recall stage 1: vector ---
    query_embedding = await _embed_query(query)

    async with async_session() as session:
        vector_hits = await _vector_candidates(session, query_embedding, candidate_pool)
        # --- recall stage 2: BM25 (full-corpus, in-process) ---
        bm25_hits, corpus_size = await _bm25_candidates(session, query, candidate_pool)

    if corpus_size == 0:
        logger.info("rag_search_empty_corpus", query_len=len(query))
        return []
    if corpus_size > _BM25_FULL_SCAN_WARN:
        logger.warning(
            "rag_bm25_full_scan_large_corpus",
            corpus_size=corpus_size,
            note="in-process BM25 loads the whole corpus per query; consider tsvector swap",
        )

    # --- fusion stage: Reciprocal Rank Fusion ---
    fused_pool = _rrf_fuse(vector_hits, bm25_hits, settings.RAG_RRF_K, candidate_pool)

    # --- precision stage: cross-encoder scores every fused candidate ---
    # Off the event loop: rerank() is sync CPU (CrossEncoder.predict) and the
    # first call lazy-loads the ~30s model — running it inline froze the agent
    # loop / webhook. asyncio.to_thread keeps it off the loop.
    reranked = await asyncio.to_thread(
        rerank, query=query, candidates=fused_pool, content_key="content"
    )

    # --- policy stage: threshold + top_k + dropped-candidate audit ---
    kept, dropped = _apply_threshold(reranked, threshold, top_k)

    logger.info(
        "rag_search_complete",
        query_len=len(query),
        corpus_size=corpus_size,
        vector_candidates=len(vector_hits),
        bm25_candidates=len(bm25_hits),
        fused_pool=len(fused_pool),
        reranked=len(reranked),
        kept=len(kept),
        dropped_below_threshold=sum(1 for d in dropped if d["drop_reason"] == "below_threshold"),
        dropped_beyond_top_k=sum(1 for d in dropped if d["drop_reason"] == "beyond_top_k"),
        threshold=threshold,
        top_k=top_k,
        kept_candidates=_kept_audit(kept),
        dropped_candidates=_dropped_audit(dropped),
        duration_ms=int((time.monotonic() - start) * 1000),
    )
    return kept


# --------------------------------------------------------------------------- #
# Recall stages                                                               #
# --------------------------------------------------------------------------- #
async def _embed_query(query: str) -> list[float]:
    """Embed the query with the same model the chunks were embedded with.

    Defensive on the LiteLLM response shape — versions differ on whether
    ``response.data[0]`` is a dict or an object exposing ``.embedding`` (same
    handling as the tool registry's ``_embed_text``).
    """
    response = await litellm.aembedding(model=settings.EMBEDDING_MODEL, input=[query])
    item = response.data[0]
    if hasattr(item, "embedding"):
        return list(item.embedding)
    return list(item["embedding"])


async def _vector_candidates(
    session: Any,
    query_embedding: list[float],
    limit: int,
) -> list[dict[str, Any]]:
    """pgvector cosine top-``limit`` chunks (only rows that actually embedded).

    ``vector_score`` is cosine *similarity* (``1 - distance``), best first.
    """
    distance = DocumentChunk.embedding.cosine_distance(query_embedding)
    stmt = (
        select(
            DocumentChunk.id,
            DocumentChunk.document_id,
            DocumentChunk.filename,
            DocumentChunk.chunk_index,
            DocumentChunk.content,
            DocumentChunk.meta,
            (1 - distance).label("vector_score"),
        )
        .where(DocumentChunk.embedding.isnot(None))
        .order_by(distance)
        .limit(limit)
    )
    result = await session.execute(stmt)
    return [
        _base_candidate(r, vector_score=float(r.vector_score), bm25_score=None)
        for r in result.all()
    ]


async def _bm25_candidates(
    session: Any,
    query: str,
    limit: int,
) -> tuple[list[dict[str, Any]], int]:
    """In-process BM25 over the full corpus → top-``limit`` lexical matches.

    Returns ``(candidates, corpus_size)``. ``corpus_size`` is surfaced so the
    caller can log the full-scan cost and fire the scale-cliff warning.
    """
    stmt = select(
        DocumentChunk.id,
        DocumentChunk.document_id,
        DocumentChunk.filename,
        DocumentChunk.chunk_index,
        DocumentChunk.content,
        DocumentChunk.meta,
    )
    result = await session.execute(stmt)
    rows = result.all()
    corpus_size = len(rows)
    if corpus_size == 0:
        return [], 0

    tokenized = [(r.content or "").lower().split() for r in rows]
    bm25 = BM25Okapi(tokenized)
    scores = bm25.get_scores(query.lower().split())

    ranked_idx = sorted(range(corpus_size), key=lambda i: scores[i], reverse=True)[:limit]
    candidates = [
        _base_candidate(rows[i], vector_score=None, bm25_score=float(scores[i]))
        for i in ranked_idx
    ]
    return candidates, corpus_size


def _base_candidate(
    row: Any,
    vector_score: float | None,
    bm25_score: float | None,
) -> dict[str, Any]:
    """Normalize a DB row into the canonical candidate dict carried end-to-end.

    Both score keys always exist (the irrelevant one is ``None``) so the fusion
    merge can fill whichever side is present without key juggling.
    """
    return {
        "chunk_id": str(row.id),
        "document_id": str(row.document_id),
        "filename": row.filename,
        "chunk_index": row.chunk_index,
        "content": row.content,
        "meta": row.meta or {},
        "vector_score": vector_score,
        "bm25_score": bm25_score,
    }


# --------------------------------------------------------------------------- #
# Fusion + policy                                                             #
# --------------------------------------------------------------------------- #
def _rrf_fuse(
    vector_hits: list[dict[str, Any]],
    bm25_hits: list[dict[str, Any]],
    k: int,
    pool: int,
) -> list[dict[str, Any]]:
    """Reciprocal Rank Fusion of the two ranked candidate lists.

    ``rrf_score(d) = Σ_lists 1 / (k + rank_list(d))`` over the lists ``d``
    appears in (1-based rank). Scale-invariant — it never compares a cosine
    similarity to a BM25 score. Returns the top-``pool`` fused candidates, each
    carrying ``rrf_score``, ``vector_rank``/``bm25_rank`` (None if absent), and
    both raw recall scores for debugging.
    """
    fused: dict[str, dict[str, Any]] = {}

    for source, hits in (("vector", vector_hits), ("bm25", bm25_hits)):
        for rank, hit in enumerate(hits, start=1):
            cid = hit["chunk_id"]
            entry = fused.get(cid)
            if entry is None:
                entry = {**hit, "rrf_score": 0.0, "vector_rank": None, "bm25_rank": None}
                fused[cid] = entry
            if source == "vector":
                entry["vector_rank"] = rank
                entry["vector_score"] = hit["vector_score"]
            else:
                entry["bm25_rank"] = rank
                entry["bm25_score"] = hit["bm25_score"]
            entry["rrf_score"] += 1.0 / (k + rank)

    ranked = sorted(fused.values(), key=lambda c: c["rrf_score"], reverse=True)
    return ranked[:pool]


def _apply_threshold(
    reranked: list[dict[str, Any]],
    threshold: float,
    top_k: int,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split reranked (sorted desc) candidates into kept vs dropped.

    A candidate is dropped ``below_threshold`` if its ``rerank_score`` is under
    the threshold, or ``beyond_top_k`` if it cleared the threshold but the
    ``top_k`` budget is already full. Returns ``(kept, dropped)``; dropped dicts
    carry a ``drop_reason``.
    """
    kept: list[dict[str, Any]] = []
    dropped: list[dict[str, Any]] = []
    for cand in reranked:
        if cand["rerank_score"] < threshold:
            dropped.append({**cand, "drop_reason": "below_threshold"})
        elif len(kept) >= top_k:
            dropped.append({**cand, "drop_reason": "beyond_top_k"})
        else:
            kept.append(cand)
    return kept, dropped


def _audit_record(c: dict[str, Any]) -> dict[str, Any]:
    """Compact, queryable score record for one candidate (kept or dropped)."""
    return {
        "chunk_id": c["chunk_id"],
        "filename": c["filename"],
        "chunk_index": c["chunk_index"],
        "rerank_score": round(c["rerank_score"], 4),
        "rrf_score": round(c["rrf_score"], 6),
        "vector_score": round(c["vector_score"], 4) if c.get("vector_score") is not None else None,
    }


def _kept_audit(kept: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per-kept audit records — the score on every chunk that PASSED the
    threshold. This is the side reranker-leak-through analysis actually needs
    (a chunk kept that shouldn't be); logged symmetrically with the drops so
    both sides of the cut are mineable from the one ``rag_search_complete``
    event without parsing the agent-facing tool output."""
    return [_audit_record(c) for c in kept]


def _dropped_audit(dropped: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Per-drop audit records — a score and a reason on every dropped candidate,
    so the eval framework can mine threshold tuning (below_threshold) and
    recall ceiling (beyond_top_k)."""
    return [{**_audit_record(d), "drop_reason": d["drop_reason"]} for d in dropped]
