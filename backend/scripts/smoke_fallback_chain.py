"""Turn 11a Smoke 3 — fallback chain fires when PRIMARY provider returns an error.

Sets PRIMARY_MODEL to a deliberately bogus Groq model name so LiteLLM's first
dispatch raises BadRequestError on every retry attempt. The gateway should
then fall back to FALLBACK_MODEL (openai/gpt-4o-mini) and succeed.

What this proves end-to-end:
  - Gateway catches the primary's exception after the tenacity retries.
  - The fallback path actually fires (logged as `falling_back`).
  - The OpenAI key works and returns a real response.
  - The fallback path also writes an LLMUsageLog row tagged with the fallback model.

Run inside the backend container:

    docker compose run --rm --entrypoint sh backend -c \
        "cd /app && python scripts/smoke_fallback_chain.py"
"""

import asyncio
import sys

import _smoke_isolation  # noqa: F401  — side effect: bind to the test DB before any app import
from sqlalchemy import select

from app.config import settings
from app.db.engine import async_session, close_db
from app.db.models import LLMUsageLog


async def main() -> int:
    if not settings.OPENAI_API_KEY:
        print("FAIL: OPENAI_API_KEY is empty — fallback chain test needs it.")
        return 1

    # Sabotage PRIMARY_MODEL before we import the gateway so the gateway's
    # cached model registry picks up the bogus value.
    settings.PRIMARY_MODEL = "groq/this-model-does-not-exist-on-purpose"
    # Force the cached models() to rebuild — get_models is @cache'd so we have
    # to clear it.
    from app.llm import models as model_registry
    model_registry.get_models.cache_clear()

    print(f"=== PRIMARY: {settings.PRIMARY_MODEL!r} (sabotaged)")
    print(f"=== FAST:    {settings.FAST_MODEL!r}")
    print(f"=== FALLBACK:{settings.FALLBACK_MODEL!r}")

    # Import gateway AFTER sabotaging — its singleton picks up the new models.
    from app.llm.gateway import LLMGateway
    gateway = LLMGateway()

    print("=== call gateway.complete (should hit primary, retry, then fall back) ===")
    response = await gateway.complete(
        messages=[
            {"role": "user", "content": "Reply with exactly the three words: hello world friend."},
        ],
        task_type="reasoning",
        thread_id="smoke-fallback",
    )

    msg = response["choices"][0]["message"]["content"]
    model_used = response.get("model", "")
    print(f"  response: {msg!r}")
    print(f"  model returned by litellm: {model_used!r}")

    print()
    print("=== verify the response came from the FALLBACK provider, not the (sabotaged) primary ===")
    # The model field on the response is what LiteLLM tagged after the call
    # actually executed. If primary really did fall back, this will be a
    # gpt-4o-mini variant, not anything Groq.
    if "gpt-4o-mini" not in (model_used or "").lower():
        print(
            f"FAIL: response model was {model_used!r}; expected something containing 'gpt-4o-mini'. "
            "Either fallback didn't fire or primary somehow succeeded against a bogus model name."
        )
        return 1
    print("  ✓ response came from openai/gpt-4o-mini (fallback path proven)")

    print()
    print("=== verify llm_usage_logs row ===")
    async with async_session() as session:
        result = await session.execute(
            select(LLMUsageLog)
            .where(LLMUsageLog.thread_id == "smoke-fallback")
            .order_by(LLMUsageLog.created_at.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
    if row is None:
        print("FAIL: no LLMUsageLog row for this turn.")
        return 1
    print(f"  row.model:   {row.model!r}")
    print(f"  row.tokens:  {row.prompt_tokens} in / {row.completion_tokens} out")
    if row.model != settings.FALLBACK_MODEL:
        print(
            f"FAIL: usage row model is {row.model!r}, expected fallback {settings.FALLBACK_MODEL!r}"
        )
        return 1
    print("  ✓ usage row tagged with fallback model")

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
