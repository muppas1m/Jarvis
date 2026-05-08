"""Turn 5 smoke test — one round-trip through the gateway, then verify
both the DB log and the Langfuse trace landed.

Run inside the backend container:

    docker compose run --rm --entrypoint sh backend -c "cd /app && python scripts/smoke_llm.py"
"""
import asyncio
import os
from datetime import datetime, timedelta, timezone

import httpx
from sqlalchemy import select

from app.config import settings
from app.db.engine import async_session, close_db
from app.db.models import LLMUsageLog
from app.llm.gateway import llm_gateway


THREAD_ID = "smoke-test-turn-5"


async def call_gateway() -> dict:
    response = await llm_gateway.complete(
        messages=[
            {"role": "user", "content": "Reply with exactly three words: hello world friend."},
        ],
        task_type="reasoning",
        thread_id=THREAD_ID,
    )
    msg = response["choices"][0]["message"]["content"]
    usage = response.get("usage", {})
    print("=== gateway response ===")
    print(f"  message: {msg!r}")
    print(f"  model:   {response.get('model')}")
    print(f"  prompt_tokens:     {usage.get('prompt_tokens')}")
    print(f"  completion_tokens: {usage.get('completion_tokens')}")

    spend = await llm_gateway.cost_tracker.get_today_spend()
    print(f"  today_spend_usd:   {spend}")
    return response


async def verify_db_log() -> None:
    print("=== db log row ===")
    async with async_session() as session:
        result = await session.execute(
            select(LLMUsageLog)
            .where(LLMUsageLog.thread_id == THREAD_ID)
            .order_by(LLMUsageLog.created_at.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        if row is None:
            print("  ✗ no row found — DB logging failed")
            return
        print(f"  ✓ row id={row.id}")
        print(f"  model:    {row.model}")
        print(f"  task:     {row.task_type}")
        print(f"  tokens:   {row.prompt_tokens} in / {row.completion_tokens} out")
        print(f"  duration: {row.duration_ms}ms")
        print(f"  cost:     ${row.cost_usd}")


async def verify_langfuse_trace() -> None:
    """Hit Langfuse's traces API and look for any trace with our session_id.

    LiteLLM's callback fires asynchronously, so we wait briefly before querying.
    """
    print("=== langfuse trace ===")
    if not (settings.LANGFUSE_ENABLED and settings.LANGFUSE_PUBLIC_KEY):
        print("  - skipped (langfuse disabled or keys missing)")
        return

    # Map the host-side LANGFUSE_HOST into the container's network. The .env
    # value is `http://localhost:3002`, which inside the container resolves to
    # the container itself. Rewrite to the docker DNS name so we can hit it.
    host_url = settings.LANGFUSE_HOST.replace("localhost", "host.docker.internal")
    auth = (settings.LANGFUSE_PUBLIC_KEY, settings.LANGFUSE_SECRET_KEY)

    # Slight wait for LiteLLM's async callback to flush.
    for delay in (2, 4, 6):
        await asyncio.sleep(delay)
        from_iso = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(
                    f"{host_url}/api/public/traces",
                    auth=auth,
                    params={"sessionId": THREAD_ID, "fromTimestamp": from_iso, "limit": 5},
                )
            r.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            print(f"  ! langfuse query failed (will retry): {exc}")
            continue

        data = r.json()
        traces = data.get("data") or []
        if traces:
            t = traces[0]
            print(f"  ✓ found {len(traces)} trace(s)")
            print(f"  trace id:    {t.get('id')}")
            print(f"  name:        {t.get('name')}")
            print(f"  session id:  {t.get('sessionId')}")
            print(f"  ui url:      {settings.LANGFUSE_HOST}/project/jarvis/traces/{t.get('id')}")
            return
        print(f"  - no trace yet after {delay}s, waiting more...")

    print("  ✗ no trace landed within ~12s")


async def main() -> None:
    try:
        await call_gateway()
        await verify_db_log()
        await verify_langfuse_trace()
    finally:
        await close_db()


if __name__ == "__main__":
    asyncio.run(main())
