"""Turn 19.6 smoke — RAG retrieval pipeline correctness (NOT retrieval quality).

What it proves (pipeline runs end-to-end + the policy contract holds):
  - ingest_document works end-to-end (extract → chunk → contextualize → embed →
    store) for real files, returning stored chunks.
  - search_documents retrieves the on-topic passage and the relevance threshold
    DROPS the off-topic passages (the turn's deliverable).
  - The dropped-candidate audit is captured in the ``rag_search_complete``
    structured log event — a score and a reason on every drop.
  - The document_search agent tool renders citations (``[file, §section]``) and a
    relevance score the agent can cite.
  - _apply_threshold / _dropped_audit partition + shape are correct (a pure,
    DB-free structural check of the policy stage).

What it explicitly does NOT measure: retrieval *quality* (precision/recall on a
golden set) — that is Turn 20.5's eval-framework job. This smoke answers "does
the pipeline run and does the threshold drop+log correctly?", deterministically.

Run inside the backend container (FlagEmbedding + rank_bm25 + Ollama + pgvector
live there)::

    docker compose exec -T backend python scripts/smoke_rag.py

First run downloads the ~1.1GB bge-reranker-v2-m3 weights (one-time, can exceed
60s); steady-state runs are well under 60s. The script inserts a few chunks and
deletes them in a finally block, so the corpus is left untouched.
"""
from __future__ import annotations

import asyncio
import sys
import tempfile
import uuid
from pathlib import Path

# Allow running this script directly without installing the backend package.
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import structlog  # noqa: E402
from sqlalchemy import delete  # noqa: E402

from app.agent.tools.document_search import _render_results, document_search  # noqa: E402
from app.config import settings  # noqa: E402
from app.db.engine import async_session  # noqa: E402
from app.db.models import DocumentChunk  # noqa: E402
from app.documents.ingestion import ingest_document  # noqa: E402
from app.documents.search import (  # noqa: E402
    _apply_threshold,
    _dropped_audit,
    search_documents,
)
from app.utils.logging import configure_logging  # noqa: E402


# Three disjoint single-topic documents. Separate documents (not one multi-topic
# file) so each lands as its own chunk regardless of the chunker's packing —
# that lets the query discriminate one topic and threshold-drop the other two.
DOCS = {
    "espresso.md": (
        "# Espresso Brewing\n\n"
        "A well-pulled double shot of espresso uses about eighteen grams of "
        "finely ground coffee and extracts in roughly twenty-five to thirty "
        "seconds. The water temperature should hover near ninety-three degrees "
        "Celsius, and the finished shot weighs about thirty-six grams with a "
        "thick golden crema on top."
    ),
    "taxes.md": (
        "# Tax Filing Deadlines\n\n"
        "Individual federal income tax returns are generally due on April "
        "fifteenth each year. Requesting an extension pushes the filing deadline "
        "to October fifteenth, but it does not extend the time to pay any balance "
        "owed, so interest accrues on unpaid amounts from the original April date."
    ),
    "plants.md": (
        "# Houseplant Care\n\n"
        "Most tropical houseplants such as pothos and monstera prefer bright "
        "indirect light and should only be watered once the top inch of soil has "
        "dried out. Overwatering is the single most common cause of root rot, so "
        "well-draining soil and a pot with drainage holes matter a great deal."
    ),
}

QUERY = "How many grams of coffee and how many seconds for an espresso shot?"
ON_TOPIC = "espresso.md"
OFF_TOPIC = {"taxes.md", "plants.md"}


async def _ingest_all(tmpdir: Path) -> list[str]:
    """Write + ingest the three docs; return their document_ids."""
    doc_ids: list[str] = []
    for name, body in DOCS.items():
        path = tmpdir / name
        path.write_text(body, encoding="utf-8")
        result = await ingest_document(str(path), name)
        print(f"  ingested {name}: {result['chunks_stored']} chunk(s), doc={result['document_id'][:8]}")
        doc_ids.append(result["document_id"])
    return doc_ids


async def _cleanup(doc_ids: list[str]) -> None:
    uuids = [uuid.UUID(d) for d in doc_ids]
    async with async_session() as session:
        await session.execute(delete(DocumentChunk).where(DocumentChunk.document_id.in_(uuids)))
        await session.commit()


def _check_structural(failures: list[str]) -> None:
    """DB-free proof of the policy stage: partition + audit-record shape."""
    print("=== policy-stage structural check ===")
    synthetic = [
        {"chunk_id": "a", "filename": "a.md", "chunk_index": 0, "rerank_score": 0.95, "rrf_score": 0.03, "vector_score": 0.8},
        {"chunk_id": "b", "filename": "b.md", "chunk_index": 0, "rerank_score": 0.50, "rrf_score": 0.02, "vector_score": 0.6},
        {"chunk_id": "c", "filename": "c.md", "chunk_index": 0, "rerank_score": 0.10, "rrf_score": 0.01, "vector_score": None},
    ]
    kept, dropped = _apply_threshold(synthetic, threshold=0.3, top_k=1)
    if [c["chunk_id"] for c in kept] != ["a"]:
        failures.append(f"structural: expected kept=[a] (top_k=1), got {[c['chunk_id'] for c in kept]}")
    reasons = {d["chunk_id"]: d["drop_reason"] for d in dropped}
    if reasons.get("b") != "beyond_top_k":
        failures.append(f"structural: 'b' (≥threshold, over top_k) should be beyond_top_k, got {reasons.get('b')}")
    if reasons.get("c") != "below_threshold":
        failures.append(f"structural: 'c' (<threshold) should be below_threshold, got {reasons.get('c')}")

    audit = _dropped_audit(dropped)
    for rec in audit:
        if not isinstance(rec.get("rerank_score"), float):
            failures.append(f"structural: audit record missing numeric rerank_score: {rec}")
        if rec.get("drop_reason") not in {"below_threshold", "beyond_top_k"}:
            failures.append(f"structural: audit record bad drop_reason: {rec}")
    print(f"  kept={[c['chunk_id'] for c in kept]} dropped={reasons} audit_records={len(audit)}")


def _check_render_budget(failures: list[str]) -> None:
    """DB-free proof that document_search output stays under the archival cap for
    any top_k in 1-10 — worst-case long content + long citations."""
    print("=== render-budget invariant (1-10 passages) ===")
    long_content = "lorem ipsum dolor sit amet " * 200  # ~5400 chars, forces truncation
    for n in (1, 3, 5, 10):
        results = [
            {
                "filename": f"a-rather-long-document-filename-{i}.pdf",
                "meta": {
                    "source_file": f"a-rather-long-document-filename-{i}.pdf",
                    "page_start": 12,
                    "page_end": 13,
                    "section_heading": f"A Verbose Section Heading Number {i} For Citation Width",
                },
                "rerank_score": 0.9 - i * 0.01,
                "content": long_content,
            }
            for i in range(n)
        ]
        out = _render_results(results)
        if len(out) > settings.TOOL_RESULT_MAX_CHARS:
            failures.append(
                f"render-budget: n={n} produced {len(out)} chars > cap {settings.TOOL_RESULT_MAX_CHARS}"
            )
        # Provenance must survive: every citation present even under tight budget.
        missing = [i for i in range(n) if f"a-rather-long-document-filename-{i}.pdf" not in out]
        if missing:
            failures.append(f"render-budget: n={n} dropped citations for passages {missing}")
        print(f"  n={n}: {len(out)} chars (cap {settings.TOOL_RESULT_MAX_CHARS}), all {n} citation(s) present")


async def _check_retrieval(failures: list[str]) -> None:
    """End-to-end retrieval + threshold-drop + audit-log capture."""
    print("=== retrieval + threshold + drop-audit ===")
    # capture_logs reconfigures structlog before search's logger is first used,
    # so the rag_search_complete event is captured despite cache_logger_on_first_use.
    with structlog.testing.capture_logs() as captured:
        results = await search_documents(query=QUERY)

    kept_files = [r["filename"] for r in results]
    print(f"  kept files: {kept_files}")
    if ON_TOPIC not in kept_files:
        failures.append(f"retrieval: on-topic {ON_TOPIC} not in kept results {kept_files}")
    leaked = OFF_TOPIC & set(kept_files)
    if leaked:
        failures.append(f"retrieval: off-topic docs leaked past threshold: {leaked}")
    for r in results:
        if not isinstance(r.get("rerank_score"), float):
            failures.append(f"retrieval: kept result missing numeric rerank_score: {r.get('filename')}")

    events = [e for e in captured if e.get("event") == "rag_search_complete"]
    if not events:
        failures.append("retrieval: no rag_search_complete log event captured")
        return
    ev = events[-1]
    print(
        f"  audit: kept={ev.get('kept')} below_threshold={ev.get('dropped_below_threshold')} "
        f"beyond_top_k={ev.get('dropped_beyond_top_k')} corpus={ev.get('corpus_size')}"
    )
    dropped = ev.get("dropped_candidates") or []
    if ev.get("dropped_below_threshold", 0) < 1:
        failures.append("retrieval: expected ≥1 below-threshold drop (off-topic docs); audit shows none")
    if not dropped:
        failures.append("retrieval: dropped_candidates audit array is empty")
    for rec in dropped:
        if not isinstance(rec.get("rerank_score"), (int, float)):
            failures.append(f"retrieval: dropped audit record lacks a score: {rec}")
        if rec.get("drop_reason") not in {"below_threshold", "beyond_top_k"}:
            failures.append(f"retrieval: dropped audit record bad reason: {rec}")

    # Symmetric kept-side audit (leak-through analysis reads the kept scores).
    kept_audit = ev.get("kept_candidates") or []
    if len(kept_audit) != ev.get("kept"):
        failures.append(
            f"retrieval: kept_candidates array ({len(kept_audit)}) != kept count ({ev.get('kept')})"
        )
    for rec in kept_audit:
        if not isinstance(rec.get("rerank_score"), (int, float)):
            failures.append(f"retrieval: kept audit record lacks a score: {rec}")


async def _check_tool_citations(failures: list[str]) -> None:
    """The agent tool renders a citation bracket + relevance score."""
    print("=== document_search tool citations ===")
    out = await document_search(query=QUERY)
    print("  --- tool output ---")
    for line in out.splitlines():
        print(f"    {line}")
    if f"[{ON_TOPIC}" not in out:
        failures.append(f"tool: citation '[{ON_TOPIC} ...]' missing from output")
    if "§Espresso Brewing" not in out:
        failures.append("tool: section-heading citation '§Espresso Brewing' missing from output")
    if "relevance" not in out:
        failures.append("tool: relevance score missing from output")


async def main() -> int:
    configure_logging()
    failures: list[str] = []

    # Structural checks first — DB-free, fast, prove the policy + render
    # contracts even if the live stack misbehaves.
    _check_structural(failures)
    _check_render_budget(failures)

    doc_ids: list[str] = []
    with tempfile.TemporaryDirectory(prefix="jarvis-smoke-rag-") as tmpdir:
        td = Path(tmpdir)
        try:
            print("=== ingest ===")
            doc_ids = await _ingest_all(td)
            if not doc_ids:
                failures.append("ingest: no documents ingested")
            else:
                await _check_retrieval(failures)
                await _check_tool_citations(failures)
        finally:
            if doc_ids:
                await _cleanup(doc_ids)
                print(f"=== cleanup === removed chunks for {len(doc_ids)} test doc(s)")

    print()
    if failures:
        print(f"FAIL: {len(failures)} assertion(s) failed")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("PASS: RAG pipeline ingests, retrieves, threshold-drops+logs, and cites")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
