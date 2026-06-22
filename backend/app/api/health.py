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
import asyncio
import time
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


# --- richer subsystem probes (4.C.2 dashboard health ring) -----------------
# These back the master-facing health GROUPS surfaced on the AUTHENTICATED
# /api/system/health (system.py). The PUBLIC /health below stays minimal +
# non-leaky on purpose; these extra subsystem names live behind auth.


async def _check_ollama() -> DepStatus:
    """Ollama (BGE-M3 embeddings → Mem0 recall). Cheap local GET."""
    try:
        async with httpx.AsyncClient(timeout=2.0) as client:
            r = await client.get(f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/tags")
        return "ok" if r.status_code == 200 else "down"
    except Exception as exc:  # noqa: BLE001
        logger.warning("health_ollama_down", error=str(exc))
        return "down"


async def _check_celery() -> DepStatus:
    """Background workers — broadcast ping with a short timeout, run off the
    event loop (control.ping is sync)."""
    try:
        from app.scheduler.celery_app import celery_app

        replies = await asyncio.to_thread(lambda: celery_app.control.ping(timeout=1.0))
        return "ok" if replies else "down"
    except Exception as exc:  # noqa: BLE001
        logger.warning("health_celery_down", error=str(exc))
        return "down"


def _check_whisper() -> DepStatus:
    """Speech-to-text model resident? (warmed at startup; cheap flag read)."""
    try:
        from app.voice.transcribe import is_loaded

        return "ok" if is_loaded() else "down"
    except Exception:  # noqa: BLE001
        return "down"


def _check_brain() -> DepStatus:
    """The agent can reason only if an LLM provider key is configured. Cheap
    config-presence — NOT a live provider-reachability probe (that would cost
    tokens/latency every poll); it catches misconfig, not a provider outage."""
    if settings.GROQ_API_KEY or settings.OPENAI_API_KEY or settings.GOOGLE_GEMINI_API_KEY:
        return "ok"
    return "down"


GroupStatus = Literal["ok", "degraded", "down"]


def _group(members: list[tuple[str, DepStatus]]) -> dict:
    """Worst-of aggregation over a group's members (skipped probes excluded)."""
    live = [(n, s) for n, s in members if s != "skipped"]
    statuses = [s for _, s in live]
    if not statuses or all(s == "ok" for s in statuses):
        status: GroupStatus = "ok"
    elif all(s == "down" for s in statuses):
        status = "down"
    else:
        status = "degraded"
    return {"status": status, "members": [{"name": n, "status": s} for n, s in live]}


_groups_cache: tuple[float, dict] | None = None
_GROUPS_CACHE_TTL = 4.0  # cheap probes, but cap re-probing under multi-widget polling


async def health_groups() -> dict:
    """Probe every subsystem in parallel and fold into the 5 master-facing
    groups for the dashboard health ring. Cached briefly so the status pill +
    the ring polling the same source don't double-probe. Fail-graceful: every
    probe returns a status, never raises — so health stays fast."""
    global _groups_cache
    now = time.monotonic()
    if _groups_cache is not None and now - _groups_cache[0] < _GROUPS_CACHE_TTL:
        return _groups_cache[1]

    db, ckpt, redis_s, ollama, celery = await asyncio.gather(
        _check_db(),
        _check_checkpointer(),
        _check_redis(),
        _check_ollama(),
        _check_celery(),
    )
    whisper = _check_whisper()  # sync — module flag
    brain = _check_brain()  # sync — config presence

    groups = {
        "Core": _group([("Database", db), ("Cache", redis_s), ("Checkpointer", ckpt)]),
        "Brain": _group([("Language model", brain)]),
        "Memory": _group([("Embeddings", ollama)]),
        "Voice": _group([("Speech-to-text", whisper)]),
        "Background jobs": _group([("Task workers", celery)]),
    }
    overall: Literal["ok", "degraded"] = (
        "ok" if all(g["status"] == "ok" for g in groups.values()) else "degraded"
    )
    result = {"status": overall, "groups": groups}
    _groups_cache = (now, result)
    return result


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
