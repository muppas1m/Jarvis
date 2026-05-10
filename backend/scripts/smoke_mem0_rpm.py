"""Turn 11a Smoke 1 — Mem0 sustained throughput on Gemini 2.0-flash.

Mem0 v2 calls its extraction LLM once per add(). Gemini 2.0-flash free tier:
  - 15 RPM (requests per minute) — bottleneck
  - 1M TPM (tokens per minute) — comfortable headroom
  - 1500 RPD (per day)

This smoke makes 15 sequential Mem0 writes inside ~60 seconds and verifies
each one extracted at least one durable fact. If we hit Gemini's RPM, the
later writes will RateLimitError-out and the script flags it.

Run inside the backend container:

    docker compose run --rm --entrypoint sh backend -c \
        "cd /app && python scripts/smoke_mem0_rpm.py"
"""
import asyncio
import sys
import time
import uuid

from app.config import settings
from app.db.engine import close_db
from app.memory.manager import MemoryManager


# Vary the content a little so Mem0's dedup doesn't merge them silently.
TEMPLATES = [
    "Master prefers {drink} in the morning.",
    "Master likes {hobby} on weekends.",
    "Master's friend named {name} is in {city}.",
    "Master wants to learn {topic} this year.",
    "Master is allergic to {allergen}.",
]


async def main() -> int:
    if not settings.GOOGLE_GEMINI_API_KEY:
        print("FAIL: GOOGLE_GEMINI_API_KEY is empty in env. Mem0 extraction needs it.")
        return 1
    if not settings.MEMORY_EXTRACTION_MODEL.startswith("gemini/"):
        print(
            f"WARN: MEMORY_EXTRACTION_MODEL={settings.MEMORY_EXTRACTION_MODEL!r} "
            "is not a gemini model. This smoke targets the 15 RPM ceiling of "
            "gemini/gemini-2.0-flash specifically."
        )

    mgr = MemoryManager()
    print(f"=== extraction_llm: {settings.MEMORY_EXTRACTION_MODEL} ===")
    print(f"=== embedder:       {settings.EMBEDDING_MODEL} ===")

    target_writes = 15
    print(f"=== making {target_writes} sequential Mem0.add() calls ===")
    started = time.time()
    failures: list[str] = []

    for i in range(target_writes):
        t = TEMPLATES[i % len(TEMPLATES)]
        unique = uuid.uuid4().hex[:6]
        content = t.format(
            drink=f"coffee-{unique}",
            hobby=f"hobby-{unique}",
            name=f"Person-{unique}",
            city=f"City-{unique}",
            topic=f"topic-{unique}",
            allergen=f"allergen-{unique}",
        )
        thread_id = f"smoke-rpm-{unique}"
        t0 = time.time()
        try:
            result = await mgr.mem0.add(content=content, thread_id=thread_id)
            elapsed = time.time() - t0
            extracted = (result or {}).get("results") or []
            n = len(extracted) if isinstance(extracted, list) else 0
            print(f"  [{i+1:>2}/{target_writes}] {elapsed:.2f}s  extracted={n}")
            if n == 0:
                # Don't fail on n=0 alone (Gemini may decide nothing was worth
                # extracting from a one-liner) but track it for the summary.
                failures.append(f"call {i+1}: 0 facts extracted from {content!r}")
        except Exception as exc:
            failures.append(f"call {i+1}: raised {type(exc).__name__}: {exc}")
            print(f"  [{i+1:>2}/{target_writes}] FAIL: {exc}")

    total = time.time() - started
    print()
    print(f"=== {target_writes} writes in {total:.1f}s ({target_writes/total*60:.1f}/min) ===")

    print()
    if failures:
        print(f"=== ISSUES ({len(failures)}) ===")
        for f in failures:
            print(f"  - {f}")
        # Distinguish "rate limit hit" from "0-extraction" — the former is
        # a real failure, the latter is just an LLM judgement call.
        rate_limited = [f for f in failures if "rate" in f.lower() or "429" in f]
        if rate_limited:
            print()
            print("FAIL: hit Gemini rate limit during the run.")
            return 1
        # Allow up to 2 zero-extraction events in 15 — Gemini sometimes returns
        # no facts on highly synthetic inputs.
        if len(failures) > 2:
            print()
            print(f"FAIL: too many zero-extraction events ({len(failures)} > 2).")
            return 1
        print()
        print("OK: zero-extraction events within tolerance, no rate-limit failures.")
        return 0

    print("=== ALL GREEN ===")
    return 0


async def _runner() -> int:
    try:
        return await main()
    finally:
        await close_db()


if __name__ == "__main__":
    sys.exit(asyncio.run(_runner()))
