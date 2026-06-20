"""Document RAG API — upload + search over the master's ingested corpus.

Mounted under the **protected** router (`app.api.router`), so every endpoint
inherits `Depends(get_current_user)` — there is no unauthenticated path to write
to the corpus. That matters: an open upload endpoint is corpus-poisoning by
anyone who can reach the host (every later search reads what was ingested).

Two production-grade guards the plan's sketch omitted:
  - **Auth** — master-only via the existing dual-path dependency (X-API-Key /
    Bearer JWT). The authenticated `user_id` is threaded into ingestion as the
    document owner (a clean multi-user seam; "master" at N=1).
  - **Streamed size cap** — the file is written to a temp path in fixed blocks
    with a running byte count, aborting at `settings.MAX_UPLOAD_SIZE_MB`. The
    plan's `await file.read()` slurps the whole upload into memory (OOM on a
    large or hostile file); this never buffers more than one block.

Ingestion idempotency is handled in `ingest_document` (content-hash dedup), so a
re-upload of the same file returns the existing document with `deduplicated=True`
rather than silently duplicating its chunks.
"""
from __future__ import annotations

import os
import tempfile

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status

from app.config import settings
from app.documents.ingestion import ingest_document
from app.documents.search import search_documents
from app.security.auth import UserContext, get_current_user
from app.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])

# Extensions the extractor pipeline understands (mirrors extractors.extract_text).
ALLOWED_EXTENSIONS = {".pdf", ".docx", ".xlsx", ".txt", ".md", ".csv"}

# Streaming read block — one of these is the most we hold in memory at once.
_READ_BLOCK = 1 << 20  # 1 MiB


@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    thread_id: str | None = Form(default=None),
    user: UserContext = Depends(get_current_user),
) -> dict:
    """Upload and ingest a document. Returns the ingestion result, including
    ``deduplicated`` / ``replaced`` so the caller knows whether a re-upload was a
    no-op. Auth required; owner is the authenticated user.

    Optional ``thread_id`` (the dashboard's canonical web thread): when given, a
    persistent '📎 Indexed …' marker is appended to that conversation so a reload
    shows the upload in place (in-chat upload, sub-phase 4.A / A3)."""
    filename = file.filename or ""
    ext = os.path.splitext(filename)[1].lower()
    if not filename or ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type: {ext or '(none)'}. Allowed: {sorted(ALLOWED_EXTENSIONS)}",
        )

    max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    written = 0
    tmp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tmp:
            tmp_path = tmp.name
            while True:
                block = await file.read(_READ_BLOCK)
                if not block:
                    break
                written += len(block)
                if written > max_bytes:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"File exceeds the {settings.MAX_UPLOAD_SIZE_MB} MB limit",
                    )
                tmp.write(block)

        if written == 0:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Empty file",
            )

        result = await ingest_document(tmp_path, filename, owner_id=user.user_id)
        logger.info(
            "document_uploaded",
            filename=filename,
            owner_id=user.user_id,
            bytes=written,
            chunks_stored=result.get("chunks_stored"),
            deduplicated=result.get("deduplicated"),
            replaced=result.get("replaced"),
        )
        if thread_id:
            from app.agent.runner import note_document_upload  # lazy — avoid cycle

            await note_document_upload(thread_id, filename, result)
        return result
    finally:
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


@router.get("/search")
async def search(
    q: str = Query(..., min_length=1, description="Search query over ingested documents"),
    top_k: int = Query(default=settings.RAG_TOP_K, ge=1, le=10, description="Max passages"),
) -> dict:
    """Hybrid search over all ingested documents. Returns kept passages with
    citation metadata + relevance scores (see ``search_documents``)."""
    results = await search_documents(q, top_k=top_k)
    return {"query": q, "count": len(results), "results": results}
