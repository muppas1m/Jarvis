"""Document ingestion pipeline — extract → chunk → contextualize → embed → store.

Consumes Turn 18's structured ``Chunk.meta`` so page / section_heading /
paragraph_index round-trip into ``DocumentChunk.meta`` for citation-ready
retrieval (Turn 19.4 search will surface these fields).

**Five-stage always-fire telemetry.** Each stage emits a ``*_complete``
structlog event with ``status=success|failure``, so debugging "why is
this large PDF stuck?" doesn't require re-running with debug
instrumentation. Per-stage ``duration_ms`` enables eval-framework
latency analysis (Turn 20.5).

**Per-chunk failure isolation.** Embedding errors and dimension mismatches
don't abort the document — the chunk persists with ``embedding=None``
(not searchable, but visible for repair via the dropped-candidate audit
trail). Contextualization failures (handled in 19.1) degrade to raw-chunk
embedding without contextual preface. Stage-level failures (extract
raises, commit fails) DO propagate after logging.

**INGESTER_VERSION** is a hybrid component+hash dict, auto-derived from
behavior-affecting inputs (CONTEXT_PROMPT, chunker defaults, embedder
model + dims). Stored verbatim in ``chunk.meta`` for "which chunks came
from which pipeline version" queries. Bumps when behavior changes;
doesn't bump on unrelated commits. Supports selective re-processing on
prompt tweaks or embedder swaps.

**Caller-side excerpt truncation.** Ingestion knows the prompt budget;
contextualizer's contract is "I take what I'm given." Memory cost bounded
to ``EXCERPT_CHARS`` regardless of document size.

Deferred lifts (memory-noted, see ``project_ingestion_idempotency_deferral.md``
and friends):

- Idempotency on re-ingest: **SHIPPED Turn 20** — a content-hash dedup gate
  skips identical content+pipeline and atomically replaces stale chunks when the
  pipeline version changed (see the Stage-0 gate in ``ingest_document``).
- Concurrent embedding via ``asyncio.gather`` + semaphore (symmetric to
  contextualizer's deferred concurrent dispatch)
- Embedding via gateway for cost-cap tracking
  (``project_embedding_cost_attribution_gap.md``)
- Document-level parent row (Phase 4 dashboard concern)
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import time
import uuid

from litellm import aembedding
from sqlalchemy import delete, select

from app.config import settings
from app.db.engine import async_session
from app.db.models import DocumentChunk
from app.documents.chunker import (
    Chunk,
    _DEFAULT_MAX_TOKENS,
    _DEFAULT_OVERLAP_TOKENS,
    chunk_blocks,
)
from app.documents.contextualizer import CONTEXT_PROMPT, contextualize_chunks
from app.documents.extractors import extract_blocks
from app.utils.logging import get_logger

logger = get_logger(__name__)


# Bytes of document text to assemble as the "whole document" context for
# the contextualizer's prompt. Frontier-clean: caller assembles only what's
# needed; contextualizer takes what it's given and doesn't truncate.
EXCERPT_CHARS = 8000

# Single-master owner today. Threaded into ``chunk.meta["owner_id"]`` as a clean
# multi-user seam: the HTTP layer passes the authenticated ``user_id`` (Phase-4
# dashboard sessions resolve a real id; Phase-1/2 api-key callers resolve
# "master"). Search does not filter on it yet — promote meta->owner_id to a real
# indexed column when multi-user (Phase 1.5b / Phase 4) lands. Nothing here
# cements "master" beyond this default.
_DEFAULT_OWNER = "master"


def _compute_ingester_version() -> dict:
    """Hybrid component+hash version dict, auto-derived from behavior inputs.

    Bumps when CONTEXT_PROMPT wording, chunker defaults, or embedder
    model/dims change. Doesn't bump on unrelated commits.

    Stored verbatim in ``chunk.meta["ingester_version"]`` for queries:

    - exact match across versions:
      ``meta->'ingester_version'->>'combined_sha256' = '<hash>'``
    - by individual component:
      ``meta->'ingester_version'->>'embedder_model' = 'ollama/bge-m3'``
      ``meta->'ingester_version'->>'context_prompt_sha256' = '<hash>'``

    The combined hash makes "did anything behavior-affecting change between
    these two runs?" a single equality check. The components make
    "which axis changed?" answerable without re-deriving from source.
    """
    components: dict = {
        "context_prompt_sha256": hashlib.sha256(CONTEXT_PROMPT.encode()).hexdigest()[:12],
        "chunker_max_tokens": _DEFAULT_MAX_TOKENS,
        "chunker_overlap_tokens": _DEFAULT_OVERLAP_TOKENS,
        "embedder_model": settings.EMBEDDING_MODEL,
        "embedder_dims": settings.EMBEDDING_DIMS,
    }
    components["combined_sha256"] = hashlib.sha256(
        json.dumps(components, sort_keys=True).encode()
    ).hexdigest()[:12]
    return components


INGESTER_VERSION: dict = _compute_ingester_version()


# --------------------------------------------------------------------------- #
# Internal helpers                                                            #
# --------------------------------------------------------------------------- #
def _assemble_excerpt(blocks: list, char_budget: int) -> str:
    """Concatenate block.text from the head of the document up to the byte
    budget. Memory-bounded regardless of document size."""
    parts: list[str] = []
    current_len = 0
    for block in blocks:
        if current_len >= char_budget:
            break
        parts.append(block.text)
        current_len += len(block.text) + 2  # +2 for "\n\n" separator
    return "\n\n".join(parts)[:char_budget]


def _hash_file(file_path: str, chunk_size: int = 1 << 20) -> str:
    """SHA-256 of the raw file bytes — the content-identity key for dedup.
    Streamed in 1 MiB blocks so a large file never lands in memory whole."""
    digest = hashlib.sha256()
    with open(file_path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk_size), b""):
            digest.update(block)
    return digest.hexdigest()


async def _existing_versions_for_hash(
    content_hash: str,
) -> list[tuple[uuid.UUID, str | None]]:
    """Distinct ``(document_id, ingester_version.combined_sha256)`` already stored
    for this content hash. Empty list → never ingested. Drives the Stage-0 gate:
    a match on the current version is an exact duplicate (skip); a match on a
    different version is the same content under a stale pipeline (replace)."""
    async with async_session() as session:
        result = await session.execute(
            select(
                DocumentChunk.document_id,
                DocumentChunk.meta["ingester_version"]["combined_sha256"].astext,
            )
            .where(DocumentChunk.meta["content_hash"].astext == content_hash)
            .distinct()
        )
    return [(row[0], row[1]) for row in result.all()]


# --------------------------------------------------------------------------- #
# Public API                                                                  #
# --------------------------------------------------------------------------- #
async def ingest_document(
    file_path: str,
    filename: str,
    owner_id: str = _DEFAULT_OWNER,
) -> dict:
    """End-to-end ingestion: extract → chunk → contextualize → embed → store.

    **Idempotent on content.** The file bytes are SHA-256'd into a ``content_hash``;
    re-ingesting the same bytes under the same pipeline version is a no-op that
    returns the existing ``document_id`` (``deduplicated=True``, no new chunks).
    If the content matches but the pipeline (``INGESTER_VERSION``) changed, the
    stale chunks are atomically replaced (``replaced=True``) — the selective
    re-processing the version hash was built for. Different content → fresh ingest.

    ``owner_id`` is stored in each ``chunk.meta`` as a multi-user seam (default
    single-master "master"); search does not filter on it yet (Phase 4).

    Returns ``{document_id, filename, chunks_stored, total_tokens, content_hash,
    deduplicated, replaced, owner_id, ingester_version}``.

    Raises ``ValueError`` if no text extracted from the file. Per-chunk failures
    isolated (embedding=None on failure or dimension mismatch; contextual_summary=""
    on contextualization failure per 19.1). Emits five ``*_complete`` structlog
    events with ``status=success|failure``: extract, chunk, contextualize, embed, commit.
    """
    document_id = uuid.uuid4()

    # --- Stage 0: content-hash dedup gate ---
    content_hash = _hash_file(file_path)
    existing = await _existing_versions_for_hash(content_hash)
    current_version = INGESTER_VERSION["combined_sha256"]
    exact = [doc_id for doc_id, ver in existing if ver == current_version]
    if exact:
        logger.info(
            "ingest_deduplicated",
            filename=filename,
            content_hash=content_hash,
            existing_document_id=str(exact[0]),
            ingester_version=current_version,
        )
        return {
            "document_id": str(exact[0]),
            "filename": filename,
            "chunks_stored": 0,
            "total_tokens": 0,
            "content_hash": content_hash,
            "deduplicated": True,
            "replaced": False,
            "owner_id": owner_id,
            "ingester_version": INGESTER_VERSION,
        }
    # Same content under a stale pipeline version → replace its chunks (atomic in Stage 5).
    is_replace = bool(existing)

    # --- Stage 1: extract ---
    start = time.monotonic()
    try:
        # extract_blocks is sync CPU (PDF parsing) — off-thread so it never
        # blocks the event loop / Telegram poller, even inside a background task.
        blocks = await asyncio.to_thread(extract_blocks, file_path)
        if not blocks:
            raise ValueError(f"No text extracted from {filename}")
        logger.info(
            "extract_complete",
            status="success",
            filename=filename,
            document_id=str(document_id),
            block_count=len(blocks),
            duration_ms=int((time.monotonic() - start) * 1000),
        )
    except Exception as exc:
        logger.error(
            "extract_complete",
            status="failure",
            filename=filename,
            document_id=str(document_id),
            error=str(exc),
            error_type=type(exc).__name__,
            duration_ms=int((time.monotonic() - start) * 1000),
        )
        raise

    # --- Stage 2: chunk ---
    start = time.monotonic()
    try:
        # chunk_blocks is sync CPU (tokenization) — off-thread, same reason.
        chunks: list[Chunk] = await asyncio.to_thread(
            chunk_blocks, blocks, source_file=filename
        )
        fallback_count = sum(1 for c in chunks if c.meta.get("fallback"))
        logger.info(
            "chunk_complete",
            status="success",
            filename=filename,
            document_id=str(document_id),
            chunk_count=len(chunks),
            fallback_count=fallback_count,
            duration_ms=int((time.monotonic() - start) * 1000),
        )
    except Exception as exc:
        logger.error(
            "chunk_complete",
            status="failure",
            filename=filename,
            document_id=str(document_id),
            error=str(exc),
            error_type=type(exc).__name__,
            duration_ms=int((time.monotonic() - start) * 1000),
        )
        raise

    # --- Stage 3: contextualize ---
    # Caller-side excerpt assembly: bounded memory, clean contextualizer contract.
    full_doc_excerpt = _assemble_excerpt(blocks, EXCERPT_CHARS)

    start = time.monotonic()
    try:
        context_summaries: list[str] = await contextualize_chunks(chunks, full_doc_excerpt)
        successful = sum(1 for s in context_summaries if s)
        empty_or_failed = len(context_summaries) - successful
        logger.info(
            "contextualize_complete",
            status="success",
            filename=filename,
            document_id=str(document_id),
            chunk_count=len(chunks),
            successful_count=successful,
            empty_or_failed_count=empty_or_failed,
            duration_ms=int((time.monotonic() - start) * 1000),
        )
    except Exception as exc:
        logger.error(
            "contextualize_complete",
            status="failure",
            filename=filename,
            document_id=str(document_id),
            error=str(exc),
            error_type=type(exc).__name__,
            duration_ms=int((time.monotonic() - start) * 1000),
        )
        raise

    # --- Stage 4: embed + build rows ---
    start = time.monotonic()
    embed_successful = 0
    embed_failed = 0
    rows: list[DocumentChunk] = []
    try:
        for chunk, summary in zip(chunks, context_summaries):
            content_with_context = (
                f"{summary}\n\n{chunk.content}" if summary else chunk.content
            )

            embedding: list[float] | None = None
            try:
                # Timeout so a hung Ollama degrades this chunk (embedding=None)
                # instead of freezing the whole ingest with no error/recovery.
                embed_response = await asyncio.wait_for(
                    aembedding(
                        model=settings.EMBEDDING_MODEL,
                        input=[content_with_context],
                    ),
                    timeout=settings.EMBED_TIMEOUT_S,
                )
                candidate = embed_response.data[0]["embedding"]
                if len(candidate) != settings.EMBEDDING_DIMS:
                    logger.error(
                        "embedding_dim_mismatch",
                        chunk_index=chunk.chunk_index,
                        expected=settings.EMBEDDING_DIMS,
                        got=len(candidate),
                        model=settings.EMBEDDING_MODEL,
                    )
                    embed_failed += 1
                else:
                    embedding = candidate
                    embed_successful += 1
            except Exception as exc:
                logger.warning(
                    "ingest_embedding_failed",
                    chunk_index=chunk.chunk_index,
                    error=str(exc),
                    error_type=type(exc).__name__,
                )
                embed_failed += 1

            chunk_meta = dict(chunk.meta)
            chunk_meta["ingester_version"] = INGESTER_VERSION
            chunk_meta["content_hash"] = content_hash
            chunk_meta["owner_id"] = owner_id

            rows.append(DocumentChunk(
                document_id=document_id,
                filename=filename,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                contextual_summary=summary,
                content_with_context=content_with_context,
                embedding=embedding,
                embedding_model=settings.EMBEDDING_MODEL,
                token_count=chunk.token_count,
                meta=chunk_meta,
            ))

        logger.info(
            "embed_complete",
            status="success",
            filename=filename,
            document_id=str(document_id),
            successful_count=embed_successful,
            failed_count=embed_failed,
            duration_ms=int((time.monotonic() - start) * 1000),
        )
    except Exception as exc:
        logger.error(
            "embed_complete",
            status="failure",
            filename=filename,
            document_id=str(document_id),
            error=str(exc),
            error_type=type(exc).__name__,
            duration_ms=int((time.monotonic() - start) * 1000),
        )
        raise

    # --- Stage 5: commit ---
    start = time.monotonic()
    try:
        async with async_session() as session:
            if is_replace:
                # Atomic swap: drop the stale-pipeline chunks for this content in
                # the SAME transaction as the new insert, so a mid-ingest failure
                # never leaves the document with zero searchable chunks.
                await session.execute(
                    delete(DocumentChunk).where(
                        DocumentChunk.meta["content_hash"].astext == content_hash
                    )
                )
            session.add_all(rows)
            await session.commit()
        logger.info(
            "commit_complete",
            status="success",
            filename=filename,
            document_id=str(document_id),
            chunks_stored=len(rows),
            replaced=is_replace,
            duration_ms=int((time.monotonic() - start) * 1000),
        )
    except Exception as exc:
        logger.error(
            "commit_complete",
            status="failure",
            filename=filename,
            document_id=str(document_id),
            error=str(exc),
            error_type=type(exc).__name__,
            duration_ms=int((time.monotonic() - start) * 1000),
        )
        raise

    return {
        "document_id": str(document_id),
        "filename": filename,
        "chunks_stored": len(rows),
        "total_tokens": sum(c.token_count for c in chunks),
        "content_hash": content_hash,
        "deduplicated": False,
        "replaced": is_replace,
        "owner_id": owner_id,
        "ingester_version": INGESTER_VERSION,
    }
