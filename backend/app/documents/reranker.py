"""bge-reranker-v2-m3 cross-encoder reranking — a pure scoring function.

A cross-encoder scores ``(query, candidate)`` *pairs* directly rather than
comparing independently-embedded vectors, which gives a 20-30% precision lift
on real-world RAG. The standard 2026 indie pattern is: cheap recall stage
(vector + BM25) → top-N candidate pool → cross-encoder rerank → keep the best.

**Loader: sentence-transformers ``CrossEncoder``, not ``FlagEmbedding``.** The
plan sketched ``FlagReranker``, but FlagEmbedding 1.4.0's tokenizer path calls
``tokenizer.prepare_for_model(...)`` which transformers 5.x removed — and
transformers 5.8.0 is pinned in this image by ``sentence-transformers`` and
``peft``, so downgrading it to satisfy FlagEmbedding would start a resolver
fight. ``CrossEncoder`` loads the *identical* model weights
(``BAAI/bge-reranker-v2-m3``), is the more widely-maintained API, and works with
the installed transformers-5 stack. For a single-label reranker (``num_labels=1``)
it applies a sigmoid by default, so ``rerank_score`` lands in ``(0, 1)`` — the
same scale ``FlagReranker(normalize=True)`` produced, keeping the caller's
threshold (``settings.RAG_RERANK_THRESHOLD``, default 0.3) a stable cut.

**This module is deliberately a pure scorer.** It assigns a ``rerank_score`` to
every candidate it is given, sorts by that score, and returns *all* of them. It
does NOT apply the relevance threshold, does NOT cap to a final ``top_k``, and
does NOT log dropped candidates. Those are retrieval *policy* and belong to the
caller (:mod:`app.documents.search`), which owns the threshold, the final cut,
and the dropped-candidate audit trail. Keeping scoring and policy in separate
modules means the threshold/logging contract has exactly one home and the
reranker stays trivially testable in isolation.

**Lazy single-process load.** The ~568M model takes ~30s to load on CPU and
~1.1GB resident. Loading it lazily on first ``rerank()`` call (rather than at
import) means only the process that actually performs a document search pays
that cost — Celery workers and webhook handlers that never search never load
it. First-search latency is the trade; a startup warm-up hook can be added if
that ever surfaces as a complaint (lifts ship on real-usage signal).
"""
from __future__ import annotations

import threading
from typing import Any

from sentence_transformers import CrossEncoder

from app.config import settings
from app.utils.logging import get_logger

logger = get_logger(__name__)


_reranker: CrossEncoder | None = None
# Now that rerank() runs via asyncio.to_thread, concurrent first-searches could
# load the ~30s model twice. Double-checked locking loads it exactly once.
_load_lock = threading.Lock()


def _get_reranker() -> CrossEncoder:
    """Lazy-load the cross-encoder on first call. ~30s initial load on CPU."""
    global _reranker
    if _reranker is None:
        with _load_lock:
            if _reranker is None:  # re-check under the lock
                logger.info("loading_reranker", model=settings.RERANK_MODEL)
                # fp16 only helps on GPU; CrossEncoder takes it via model_kwargs.
                model_kwargs = {"torch_dtype": "float16"} if settings.RERANK_USE_FP16 else {}
                _reranker = CrossEncoder(settings.RERANK_MODEL, model_kwargs=model_kwargs)
                logger.info("reranker_loaded", model=settings.RERANK_MODEL)
    return _reranker


def rerank(
    query: str,
    candidates: list[dict[str, Any]],
    content_key: str = "content",
) -> list[dict[str, Any]]:
    """Score every candidate against ``query`` and return them sorted, best first.

    Pure scorer: returns **all** candidates (no threshold, no ``top_k`` cut) so
    the caller can own the relevance threshold and the dropped-candidate audit
    trail. Each returned dict is a shallow copy of the input with a new
    ``rerank_score`` (sigmoid-normalized to ``(0, 1)``); the original recall-stage
    ``score`` / ``rrf_score`` fields are preserved for debugging.

    Empty input → ``[]`` (no model load triggered).
    """
    if not candidates:
        return []

    reranker = _get_reranker()
    pairs = [(query, c[content_key]) for c in candidates]
    scores = reranker.predict(pairs, show_progress_bar=False)

    enriched: list[dict[str, Any]] = []
    for cand, score in zip(candidates, scores):
        scored = dict(cand)
        scored["rerank_score"] = float(score)
        enriched.append(scored)

    enriched.sort(key=lambda c: c["rerank_score"], reverse=True)
    return enriched
