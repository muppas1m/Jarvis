"""
Public liveness/readiness endpoint.

Public on purpose: Cloudflare's tunnel health check, UptimeRobot, and any
external probe must be able to hit it without credentials. The tradeoff
is that it MUST NOT leak operational detail — connection strings,
hostnames, error stacktraces, version banners. An attacker who can probe
/health learns "service is up" or "service is down", nothing more. Full
error context goes to logs.

The four dependencies we probe — Postgres, the LangGraph checkpointer
pool, Redis, and Langfuse — are the ones whose absence makes the service
non-functional. Anything else (Mem0, Ollama embeddings, LLM providers)
fails per-request and is surfaced via the cost/observability dashboards.
"""
from typing import Literal

import httpx
import redis.asyncio as redis_aio
from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import text

from app.agent import graph as graph_module
from app.config import settings
from app.db.engine import async_session
from app.utils.logging import get_logger

logger = get_logger(__name__)

router = APIRouter(tags=["health"])


DepStatus = Literal["ok", "down", "skipped"]


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    deps: dict[str, DepStatus]


async def _check_db() -> DepStatus:
    try:
        async with async_session() as session:
            await session.execute(text("SELECT 1"))
        return "ok"
    except Exception as exc:  # noqa: BLE001 — health probe must not raise
        logger.warning("health_db_down", error=str(exc))
        return "down"


async def _check_checkpointer() -> DepStatus:
    # The checkpointer is process-local state established at lifespan
    # startup. If it's None the agent can't run a turn, which is
    # functionally "down" even though the underlying Postgres might be up.
    try:
        graph_module.get_checkpointer()
        return "ok"
    except Exception as exc:  # noqa: BLE001
        logger.warning("health_checkpointer_down", error=str(exc))
        return "down"


async def _check_redis() -> DepStatus:
    client = None
    try:
        client = redis_aio.from_url(settings.REDIS_URL, socket_timeout=2.0)
        pong = await client.ping()
        return "ok" if pong else "down"
    except Exception as exc:  # noqa: BLE001
        logger.warning("health_redis_down", error=str(exc))
        return "down"
    finally:
        if client is not None:
            try:
                await client.aclose()
            except Exception:  # noqa: BLE001
                pass


async def _check_langfuse() -> DepStatus:
    if not settings.LANGFUSE_ENABLED:
        return "skipped"
    if not settings.LANGFUSE_HOST:
        return "skipped"
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            # Langfuse exposes /api/public/health which returns 200 when
            # the web app is up. No auth required for the health endpoint.
            r = await client.get(f"{settings.LANGFUSE_HOST.rstrip('/')}/api/public/health")
        return "ok" if r.status_code == 200 else "down"
    except Exception as exc:  # noqa: BLE001
        logger.warning("health_langfuse_down", error=str(exc))
        return "down"


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    deps: dict[str, DepStatus] = {
        "db": await _check_db(),
        "checkpointer": await _check_checkpointer(),
        "redis": await _check_redis(),
        "langfuse": await _check_langfuse(),
    }
    # "down" anywhere → degraded. "skipped" doesn't degrade — it just
    # means we didn't probe (e.g., Langfuse disabled).
    overall: Literal["ok", "degraded"] = (
        "degraded" if any(s == "down" for s in deps.values()) else "ok"
    )
    return HealthResponse(status=overall, deps=deps)
