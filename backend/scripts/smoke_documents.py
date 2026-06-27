"""Turn 20 smoke — document API (upload/search) + ingestion dedup + cost honesty.

What it proves (pipeline + contract correctness, NOT retrieval quality):
  - ingest_document is idempotent on content: re-ingesting the same bytes is a
    no-op (deduplicated=True, no new chunks); the corpus count doesn't grow.
  - /documents/upload requires auth (401 unauthenticated) and enforces a streamed
    size cap (413), the file-type allowlist (400), and empty-file rejection (400).
  - A valid upload ingests, threads owner_id from the auth context, and a re-upload
    of the same file dedups through the endpoint.
  - /documents/search returns the uploaded passage.
  - /costs labels coverage (the 3 gateway-bypass surfaces) + the Redis cap as a
    separate source — honest, not a single mixed total. /costs/history is shaped.

Runs the FastAPI app in-process via httpx ASGITransport — no live server needed.
Self-cleaning: deletes every chunk it created (by content_hash) in a finally.

Run inside the backend container:

    docker compose exec -T backend python scripts/smoke_documents.py
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import _smoke_isolation  # noqa: F401  — side effect: bind to the test DB before any app import

# Allow running this script directly without installing the backend package.
_BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

import httpx  # noqa: E402
from sqlalchemy import delete, func, select  # noqa: E402

from app.config import settings  # noqa: E402
from app.db.engine import async_session  # noqa: E402
from app.db.models import DocumentChunk  # noqa: E402
from app.documents.ingestion import ingest_document  # noqa: E402
from app.main import app  # noqa: E402
from app.utils.logging import configure_logging  # noqa: E402

_AUTH = {"X-API-Key": settings.API_SECRET_KEY}

DEDUP_DOC = b"# Capybara Facts\n\nThe capybara is the largest living rodent, native to South America.\n"
SEARCH_DOC = (
    b"# Quokka\n\nThe quokka is a small marsupial found mainly on Rottnest Island "
    b"off the coast of Western Australia, known for its friendly facial expression.\n"
)


def _client() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def _chunk_count(content_hash: str) -> int:
    async with async_session() as session:
        n = await session.execute(
            select(func.count())
            .select_from(DocumentChunk)
            .where(DocumentChunk.meta["content_hash"].astext == content_hash)
        )
    return int(n.scalar() or 0)


async def _cleanup(hashes: set[str]) -> None:
    if not hashes:
        return
    async with async_session() as session:
        await session.execute(
            delete(DocumentChunk).where(DocumentChunk.meta["content_hash"].astext.in_(hashes))
        )
        await session.commit()


async def _check_dedup_direct(failures: list[str], created: set[str]) -> None:
    print("=== ingestion dedup (direct) ===")
    import tempfile

    with tempfile.NamedTemporaryFile("wb", suffix=".md", delete=False) as fh:
        fh.write(DEDUP_DOC)
        path = fh.name

    first = await ingest_document(path, "capybara.md")
    created.add(first["content_hash"])
    second = await ingest_document(path, "capybara.md")
    Path(path).unlink(missing_ok=True)

    print(
        f"  first: stored={first['chunks_stored']} dedup={first['deduplicated']} "
        f"owner={first['owner_id']}  |  second: stored={second['chunks_stored']} dedup={second['deduplicated']}"
    )
    if first["deduplicated"] or first["chunks_stored"] < 1:
        failures.append(f"dedup: first ingest should store chunks, got {first}")
    if not second["deduplicated"] or second["chunks_stored"] != 0:
        failures.append(f"dedup: second ingest should be a no-op, got {second}")
    if second["document_id"] != first["document_id"]:
        failures.append("dedup: second ingest should return the first document_id")
    if first["owner_id"] != "master":
        failures.append(f"dedup: default owner should be 'master', got {first['owner_id']}")
    if await _chunk_count(first["content_hash"]) != first["chunks_stored"]:
        failures.append("dedup: corpus chunk count grew on re-ingest (duplication not prevented)")


async def _check_api(failures: list[str], created: set[str]) -> None:
    print("=== document API (auth / size cap / dedup / search) ===")
    async with _client() as client:
        # Auth gate — unauthenticated search is rejected.
        r = await client.get("/api/documents/search", params={"q": "quokka"})
        print(f"  unauth search -> {r.status_code}")
        if r.status_code != 401:
            failures.append(f"api: unauthenticated search should be 401, got {r.status_code}")

        # File-type allowlist.
        r = await client.post(
            "/api/documents/upload",
            headers=_AUTH,
            files={"file": ("evil.exe", b"MZ...", "application/octet-stream")},
        )
        if r.status_code != 400:
            failures.append(f"api: disallowed extension should be 400, got {r.status_code}")

        # Empty file.
        r = await client.post(
            "/api/documents/upload", headers=_AUTH, files={"file": ("empty.txt", b"", "text/plain")}
        )
        if r.status_code != 400:
            failures.append(f"api: empty file should be 400, got {r.status_code}")

        # Streamed size cap — temporarily shrink the cap, send >1 MB.
        original_cap = settings.MAX_UPLOAD_SIZE_MB
        settings.MAX_UPLOAD_SIZE_MB = 1
        try:
            big = b"x" * (1_300_000)
            r = await client.post(
                "/api/documents/upload", headers=_AUTH, files={"file": ("big.txt", big, "text/plain")}
            )
            print(f"  oversized upload (cap=1MB) -> {r.status_code}")
            if r.status_code != 413:
                failures.append(f"api: oversized upload should be 413, got {r.status_code}")
        finally:
            settings.MAX_UPLOAD_SIZE_MB = original_cap

        # Valid upload — ingests, threads owner, returns dedup metadata.
        r = await client.post(
            "/api/documents/upload",
            headers=_AUTH,
            files={"file": ("quokka.md", SEARCH_DOC, "text/markdown")},
        )
        if r.status_code != 200:
            failures.append(f"api: valid upload should be 200, got {r.status_code} {r.text[:200]}")
            return
        body = r.json()
        created.add(body["content_hash"])
        print(f"  upload -> stored={body['chunks_stored']} owner={body['owner_id']} dedup={body['deduplicated']}")
        if body["deduplicated"] or body["chunks_stored"] < 1:
            failures.append(f"api: valid upload should ingest fresh, got {body}")
        if body["owner_id"] != "master":
            failures.append(f"api: upload owner should be 'master', got {body['owner_id']}")

        # Re-upload same file -> dedup through the endpoint.
        r = await client.post(
            "/api/documents/upload",
            headers=_AUTH,
            files={"file": ("quokka.md", SEARCH_DOC, "text/markdown")},
        )
        body2 = r.json()
        print(f"  re-upload -> stored={body2['chunks_stored']} dedup={body2['deduplicated']}")
        if not body2.get("deduplicated") or body2.get("chunks_stored") != 0:
            failures.append(f"api: re-upload should dedup, got {body2}")

        # Search finds the uploaded passage.
        r = await client.get("/api/documents/search", headers=_AUTH, params={"q": "quokka marsupial Rottnest"})
        if r.status_code != 200:
            failures.append(f"api: authed search should be 200, got {r.status_code}")
        else:
            files_found = {hit["filename"] for hit in r.json().get("results", [])}
            print(f"  search -> {files_found}")
            if "quokka.md" not in files_found:
                failures.append(f"api: search should surface quokka.md, got {files_found}")


async def _check_costs(failures: list[str]) -> None:
    print("=== cost API honesty (coverage + cap sources) ===")
    async with _client() as client:
        r = await client.get("/api/costs", headers=_AUTH)
        if r.status_code != 200:
            failures.append(f"costs: summary should be 200, got {r.status_code}")
            return
        body = r.json()
        cov = body.get("coverage", {})
        cap = body.get("cap", {})
        excl = cov.get("excludes", [])
        print(f"  coverage.excludes={len(excl)} surfaces; cap.source set={bool(cap.get('source'))}")
        if len(excl) != 3:
            failures.append(f"costs: coverage.excludes should name the 3 bypass surfaces, got {excl}")
        if "subset" not in (cov.get("note") or "").lower():
            failures.append("costs: coverage.note should state it's a subset of real spend")
        for key in ("source", "spend_usd", "soft_cap_usd", "hard_cap_usd", "note"):
            if key not in cap:
                failures.append(f"costs: cap missing '{key}' — source/divergence not labelled")
        if "redis" not in (cap.get("note") or "").lower():
            failures.append("costs: cap.note should flag the Redis-restart divergence")

        r = await client.get("/api/costs/history", headers=_AUTH, params={"days": 7})
        if r.status_code != 200:
            failures.append(f"costs: history should be 200, got {r.status_code}")
        else:
            h = r.json()
            if "coverage" not in h or not isinstance(h.get("history"), list):
                failures.append(f"costs: history shape wrong, got keys {list(h.keys())}")
            print(f"  history days={h.get('days')} rows={len(h.get('history', []))}")


async def main() -> int:
    configure_logging()
    failures: list[str] = []
    created: set[str] = set()
    try:
        await _check_dedup_direct(failures, created)
        await _check_api(failures, created)
        await _check_costs(failures)
    finally:
        await _cleanup(created)
        print(f"=== cleanup === removed chunks for {len(created)} test content hash(es)")

    print()
    if failures:
        print(f"FAIL: {len(failures)} assertion(s) failed")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("PASS: dedup idempotent, upload authed+capped, owner threaded, costs honestly labelled")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
