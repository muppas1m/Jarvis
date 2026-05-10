"""Turn 11a Smoke 2 — verify all four graph nodes appear as discrete spans
in Langfuse.

Without the langfuse.callback CallbackHandler wired into the graph config,
we only see LiteLLM-level traces (one span per LLM completion). With it,
the graph emits a span per node (memory_load, agent, tool_executor — empty
this turn since no tools fire — and persist), all nested under one trace
that's grouped by session_id = thread_id.

Run inside the backend container:

    docker compose run --rm --entrypoint sh backend -c \
        "cd /app && python scripts/smoke_langfuse_nodes.py"
"""
import asyncio
import sys
import uuid

import httpx

from app.agent.graph import close_checkpointer, init_checkpointer
from app.agent.runner import run_turn
from app.agent.tools import register_all_tools
from app.agent.tools.registry import tool_registry
from app.config import settings
from app.db.engine import close_db


THREAD_ID = f"smoke-langfuse-{uuid.uuid4().hex[:8]}"

# memory_load + agent + persist always run. tool_executor only runs when the
# LLM emits a tool_call, which it does on at least some prompts. We make a
# query that should trigger memory_search (the always-loaded tool) so all
# four show up.
PROMPT = (
    "What do you remember about my morning briefing preferences? "
    "Look it up in my long-term memory before answering."
)

# Nodes whose names we want to see in the trace. memory_load + agent + persist
# always fire. tool_executor depends on the LLM choosing to call memory_search.
EXPECTED_NODES_AT_MINIMUM = {"memory_load", "agent", "persist"}
EXPECTED_NODES_BONUS = {"tool_executor"}


async def main() -> int:
    if not settings.LANGFUSE_PUBLIC_KEY:
        print("FAIL: LANGFUSE_PUBLIC_KEY empty — wire it before running this smoke.")
        return 1

    print(f"=== thread_id: {THREAD_ID} ===")
    print(f"=== langfuse host: {settings.LANGFUSE_HOST} ===")

    print("=== init checkpointer + register tools ===")
    await init_checkpointer()
    register_all_tools()
    await tool_registry.index_all_tools()

    print("=== run_turn ===")
    result = await run_turn(
        user_message=PROMPT,
        thread_id=THREAD_ID,
        platform="web",
        channel_user_id="smoke-tester",
    )
    print(f"  status:    {result['status']}")
    print(f"  response:  {(result['response'] or '')[:160]!r}")

    if result["status"] != "complete":
        print(f"FAIL: turn did not complete (status={result['status']})")
        await close_checkpointer()
        return 1

    print("=== query Langfuse for the trace ===")
    # Inside the container, langfuse-web is on docker DNS; the .env points at
    # langfuse-web:3000 already, so settings.LANGFUSE_HOST works as-is.
    auth = (settings.LANGFUSE_PUBLIC_KEY, settings.LANGFUSE_SECRET_KEY)

    # Wait for the callback to flush. Langfuse buffers and flushes every few
    # seconds; we poll up to ~15s.
    found_traces: list[dict] = []
    for delay in (3, 4, 5, 5):
        await asyncio.sleep(delay)
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"{settings.LANGFUSE_HOST}/api/public/traces",
                    auth=auth,
                    params={"sessionId": THREAD_ID, "limit": 10},
                )
            r.raise_for_status()
            data = r.json()
            found_traces = data.get("data") or []
        except Exception as exc:
            print(f"  ! langfuse query failed (will retry): {exc}")
            continue

        if found_traces:
            break
        print(f"  - no traces yet, waited {delay}s")

    if not found_traces:
        print("FAIL: no Langfuse traces appeared after ~15s of polling.")
        await close_checkpointer()
        return 1

    print(f"  ✓ found {len(found_traces)} trace(s) in this session")
    trace = found_traces[0]
    trace_id = trace.get("id")
    print(f"  trace_id: {trace_id}")
    print(f"  ui:       {settings.LANGFUSE_HOST.replace('langfuse-web:3000', 'localhost:3002')}/project/jarvis/traces/{trace_id}")

    print("=== fetch full trace + observations ===")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                f"{settings.LANGFUSE_HOST}/api/public/traces/{trace_id}",
                auth=auth,
            )
        r.raise_for_status()
        full = r.json()
    except Exception as exc:
        print(f"FAIL: couldn't fetch trace detail: {exc}")
        await close_checkpointer()
        return 1

    obs = full.get("observations") or []
    obs_names = {o.get("name") for o in obs if o.get("name")}
    print(f"  observation count: {len(obs)}")
    print(f"  observation names: {sorted(obs_names)}")

    # The CallbackHandler tags spans with the node name when it walks the
    # langgraph callback tree. We assert at least the always-running nodes
    # are present. tool_executor is a bonus — depends on whether the LLM
    # actually called memory_search this turn.
    missing = EXPECTED_NODES_AT_MINIMUM - obs_names
    bonus_found = EXPECTED_NODES_BONUS & obs_names

    print()
    if missing:
        print(f"FAIL: missing required node spans: {sorted(missing)}")
        print(f"      observed: {sorted(obs_names)}")
        await close_checkpointer()
        return 1

    print(f"✓ all required node spans present ({sorted(EXPECTED_NODES_AT_MINIMUM)})")
    if bonus_found:
        print(f"✓ bonus node span(s) present: {sorted(bonus_found)}")

    await close_checkpointer()
    print()
    print("=== ALL GREEN ===")
    return 0


async def _runner() -> int:
    try:
        return await main()
    finally:
        await close_db()


if __name__ == "__main__":
    sys.exit(asyncio.run(_runner()))
