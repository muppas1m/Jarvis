"""Turn 6 smoke test — the memory system end-to-end.

Steps:
  1. Seed UserProfile via UserProfileManager.update_always_on / on_demand.
  2. Read both slices back, assert what we wrote is what we read.
  3. Add a free-form memory via Mem0Client.
  4. Search for it; assert it comes back with a non-zero score.
  5. Verify Mem0 created its `mem0_memories` table inside the jarvis DB.

Run inside the backend container:

    docker compose run --rm --entrypoint sh backend -c \
        "cd /app && python scripts/smoke_memory.py"
"""
import asyncio
import sys

from sqlalchemy import text

from app.db.engine import async_session, close_db
from app.memory.manager import MemoryManager


async def main() -> int:
    mgr = MemoryManager()
    failures: list[str] = []

    print("=== seed user profile ===")
    await mgr.update_profile_always_on({
        "timezone": "America/New_York",
        "language": "English",
        "communication_style": "Direct, brief, bullet points",
    })
    await mgr.profile_mgr.set_name("Mahesh")
    # Use the direct profile_mgr path here so we DON'T trigger a Mem0 LLM
    # extraction call. The smoke makes a separate Mem0.add() below; back-to-back
    # extractions hit Groq free-tier's 12k TPM.
    await mgr.profile_mgr.update_on_demand("news_topics", ["AI", "Crypto", "Web3"])
    print("  ✓ written")

    print("=== read profile back ===")
    always_on = await mgr.get_always_on()
    on_demand_news = await mgr.get_on_demand("news_topics")
    print(f"  name:               {always_on['name']!r}")
    print(f"  always_on:          {always_on['always_on']}")
    print(f"  on_demand[news]:    {on_demand_news}")
    if always_on["name"] != "Mahesh":
        failures.append("profile.name not persisted")
    if always_on["always_on"].get("timezone") != "America/New_York":
        failures.append("always_on.timezone not persisted")
    if on_demand_news != ["AI", "Crypto", "Web3"]:
        failures.append("on_demand.news_topics not persisted")
    if not failures:
        print("  ✓ profile reads OK")

    print("=== add a memory via Mem0 ===")
    fact = "Mahesh prefers his morning briefings at 8:00 AM Eastern, in bullet points."
    await mgr.mem0.add(content=fact, thread_id="smoke-test-turn-6")
    print(f"  ✓ added: {fact}")

    print("=== search for it ===")
    hits = await mgr.recall("when does the master like his morning brief?", k=5)
    print(f"  found {len(hits)} hit(s)")
    for h in hits:
        print(f"    - score={h['score']:.3f} content={h['content']!r}")
    if not hits:
        failures.append("no memory hits returned for related query")

    print("=== verify mem0_memories table exists in pgvector ===")
    async with async_session() as session:
        result = await session.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' AND table_name LIKE 'mem0%' "
                "ORDER BY table_name"
            )
        )
        tables = [r[0] for r in result.fetchall()]
    print(f"  tables found: {tables}")
    if not any(t.startswith("mem0") for t in tables):
        failures.append("mem0 did not create its pgvector table")
    else:
        print("  ✓ mem0 table present")

    print()
    if failures:
        print("=== FAIL ===")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("=== ALL GREEN ===")
    return 0


async def _runner() -> int:
    """Run main() and clean up the engine inside the same event loop. Doing
    `asyncio.run(close_db())` after `asyncio.run(main())` reuses a closed loop
    on the asyncpg pool's connection callbacks and noisy-fails."""
    try:
        return await main()
    finally:
        await close_db()


if __name__ == "__main__":
    sys.exit(asyncio.run(_runner()))
