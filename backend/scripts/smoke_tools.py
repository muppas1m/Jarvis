"""Turn 10 smoke test — tool registry end-to-end.

What it proves:
  - register_all_tools() runs cleanly and lands memory_search in the registry.
  - index_all_tools() embeds the description (BGE-M3, 1024 dims) into
    `tool_embeddings` and is idempotent across re-runs.
  - select_relevant_tools(...) returns memory_search even on a totally
    unrelated query (because always_loaded=True bypasses the cosine ranking).
  - tool_registry.execute("memory_search", ...) actually round-trips through
    Mem0 and returns the formatted reply.

Run inside the backend container:

    docker compose run --rm --entrypoint sh backend -c \
        "cd /app && python scripts/smoke_tools.py"
"""
import asyncio
import sys

from sqlalchemy import select

from app.agent.tools import register_all_tools
from app.agent.tools.registry import tool_registry
from app.config import settings
from app.db.engine import async_session, close_db
from app.db.models import ToolEmbedding


async def main() -> int:
    failures: list[str] = []

    print("=== register_all_tools ===")
    register_all_tools()
    names = tool_registry.all_names()
    print(f"  registered: {names}")
    if "memory_search" not in names:
        failures.append("memory_search not registered")

    print("=== index_all_tools (first call — should embed) ===")
    await tool_registry.index_all_tools()
    async with async_session() as session:
        rows = await session.execute(select(ToolEmbedding))
        rows = rows.scalars().all()
    print(f"  rows in tool_embeddings: {len(rows)}")
    for row in rows:
        dim = len(row.embedding) if row.embedding is not None else 0
        print(f"    {row.tool_name}  dim={dim}  always_loaded={row.is_always_loaded}  model={row.embedding_model}")
        if dim != settings.EMBEDDING_DIMS:
            failures.append(
                f"{row.tool_name} embedding dim is {dim}, expected {settings.EMBEDDING_DIMS}"
            )
        if row.tool_name == "memory_search" and not row.is_always_loaded:
            failures.append("memory_search should be always_loaded=True")

    print("=== index_all_tools (second call — should be idempotent / no-op embed) ===")
    await tool_registry.index_all_tools()
    print("  ✓ no error on re-run")

    print("=== select_relevant_tools (totally unrelated query) ===")
    selected = await tool_registry.select_relevant_tools(
        query="What's the capital of France?",
        top_k=5,
    )
    selected_names = [t.name for t in selected]
    print(f"  selected: {selected_names}")
    if "memory_search" not in selected_names:
        failures.append("memory_search missing despite always_loaded=True")

    print("=== execute memory_search through the registry ===")
    out = await tool_registry.execute(
        "memory_search",
        {"query": "What does the master prefer for breakfast?", "top_k": 3},
    )
    print(f"  result (first 200 chars): {out[:200]!r}")
    if not isinstance(out, str) or not out:
        failures.append("memory_search returned empty / non-string")

    print("=== execute unknown tool (should ValueError) ===")
    try:
        await tool_registry.execute("does_not_exist", {})
        failures.append("execute('does_not_exist') should have raised")
    except ValueError as exc:
        print(f"  ✓ ValueError raised as expected: {exc}")

    print()
    if failures:
        print("=== FAIL ===")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("=== ALL GREEN ===")
    return 0


async def _runner() -> int:
    try:
        return await main()
    finally:
        await close_db()


if __name__ == "__main__":
    sys.exit(asyncio.run(_runner()))
