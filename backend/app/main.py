"""
FastAPI app factory + lifespan.

Starts the engine pool, runs the first-run profile guard, brings up the
checkpointer + tools + Telegram channel, mounts the API router, drains
on shutdown.

CORS is locked to TUNNEL_PUBLIC_URL (see _allowed_cors_origins for why).
Polling vs webhook is enforced as a hard mutex at startup so we never
double-deliver Telegram updates.
"""
import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from sqlalchemy import select

from app.agent.graph import close_checkpointer, init_checkpointer
from app.agent.tools import register_all_tools
from app.agent.tools.registry import tool_registry
from app.api.router import api_router
from app.config import settings
from app.db.engine import async_session, close_db, init_db
from app.db.models import UserProfile
from app.messaging.channels.telegram import get_telegram_channel
from app.messaging.channel_registry import channel_registry
from app.utils.logging import configure_logging, get_logger


async def _startup_model_ping(logger) -> None:
    """Ping each declared LLM model slot at boot to surface deprecations early.

    LLM providers periodically deprecate models with little notice (Groq
    decommissioned `gemma2-9b-it` mid-Phase-2 — the fallback chain absorbed
    every classification call until volume revealed 100% fallback rate). The
    ping surfaces deprecation on the first restart after it happens, so the
    fix lands before a high-volume task burns quota retrying a dead model.

    Three 1-token completion calls at boot. Failures log error-level but
    don't fail boot — a transient provider outage at lifespan time shouldn't
    prevent the agent from starting (it can recover via fallback chain once
    primary comes back). The point is VISIBILITY, not enforcement.
    """
    from litellm import acompletion

    from app.llm.models import get_models

    for slot, model_info in get_models().items():
        try:
            await acompletion(
                model=model_info.model_id,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
                temperature=0.0,
                timeout=10.0,
            )
            logger.info(
                "startup_model_ping_ok",
                slot=slot,
                model=model_info.model_id,
            )
        except Exception as exc:  # noqa: BLE001 — startup probe, never fatal
            logger.error(
                "startup_model_ping_failed",
                slot=slot,
                model=model_info.model_id,
                error=str(exc)[:300],
            )


async def _ensure_master_profile_or_exit(logger) -> None:
    """Hard refuse to boot if the master profile row is missing.

    Phase 1 is a single-master system: every prompt embeds the master's
    name and always_on slice. Booting without that data means the agent
    introduces itself as "Master" and confidently fabricates context on
    the first turn — the worst possible first impression.

    Raising SystemExit propagates through uvicorn cleanly with the
    message printed; no traceback noise."""
    async with async_session() as session:
        result = await session.execute(select(UserProfile).limit(1))
        existing = result.scalar_one_or_none()
    if existing is not None:
        logger.info("master_profile_present", profile_id=str(existing.id), name=existing.name)
        return

    msg = (
        "FATAL: master profile not seeded. The agent refuses to boot without "
        "knowing who it's serving.\n\n"
        "Run the seeder:\n"
        "  docker compose run --rm backend python scripts/seed_profile.py < profile.json\n\n"
        "See `python scripts/seed_profile.py --help` for the JSON shape."
    )
    logger.error("master_profile_missing")
    raise SystemExit(msg)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Bring up resources before serving traffic, drain them on shutdown.

    Order matters:
      1. DB engine (cheap; needed by everything else).
      2. First-run profile guard — refuse to boot if the master profile
         row is missing. Must run BEFORE checkpointer/tools/channels so a
         half-initialized stack doesn't accept traffic against a misseeded DB.
      3. Checkpointer (depends on DB pool; opens its own pg connection
         for AsyncPostgresSaver and is what the agent graph builds against).
      4. Tool registration (needs the registry module imported and the
         memory layer reachable; index_all_tools writes to pgvector).
      5. Channel registration + Telegram mode (polling OR webhook, mutex
         enforced) last — channels deliver INTO the agent stack so
         everything they call needs to be ready first.
    Shutdown reverses that order, except the registry has no resources to close.
    """
    configure_logging()
    logger = get_logger(__name__)
    logger.info("startup_begin", environment=settings.ENVIRONMENT)

    await init_db()
    logger.info("db_engine_ready")

    # First-run guard. Refuse to boot if the master's profile row is
    # missing — without it the agent doesn't know who it's serving and the
    # first conversation goes sideways with "I don't have any information
    # about you" hallucinations. Single-master deployment, so we fail fast
    # rather than soft-warn.
    await _ensure_master_profile_or_exit(logger)

    await init_checkpointer()
    logger.info("checkpointer_ready")

    register_all_tools()
    await tool_registry.index_all_tools()
    logger.info("tools_indexed", count=len(tool_registry))

    await _startup_model_ping(logger)

    # --- channels -----------------------------------------------------------
    # Telegram is the Phase 1 primary. Construct lazily so a missing token
    # raises here (in lifespan, where logs are visible) rather than at
    # module import.
    #
    # Polling vs webhook is a hard mutex. If both are active you get every
    # incoming Update twice — Telegram delivers via webhook AND the polling
    # loop pulls the same update via getUpdates. Enforce one-or-the-other
    # by clearing the opposite registration at startup.
    if settings.TELEGRAM_BOT_TOKEN:
        tg = get_telegram_channel()
        channel_registry.register(tg)
        logger.info("telegram_channel_registered")

        if settings.TELEGRAM_USE_POLLING:
            # Best-effort clear any stale webhook registration so we don't
            # double-deliver. Failure is non-fatal: if no webhook was ever
            # set, deleteWebhook is still a 200.
            try:
                await tg.bot.delete_webhook(drop_pending_updates=False)
                logger.info("telegram_webhook_cleared_for_polling")
            except Exception as exc:  # noqa: BLE001
                logger.warning("telegram_webhook_clear_failed", error=str(exc))

            polling_app = tg.build_polling_application()
            await polling_app.initialize()
            await polling_app.start()
            # The updater is what actually long-polls Telegram. Run it in
            # a background task so this lifespan call returns and FastAPI
            # can start serving HTTP.
            asyncio.create_task(polling_app.updater.start_polling())
            app.state.telegram_polling_app = polling_app
            logger.info("telegram_mode_active", mode="polling")
        else:
            # Webhook mode requires a public HTTPS URL Telegram can POST
            # to AND a shared secret it'll echo back as
            # X-Telegram-Bot-Api-Secret-Token. Missing either is a config
            # error — refuse to register a half-broken webhook.
            if not settings.TUNNEL_PUBLIC_URL:
                logger.error(
                    "telegram_webhook_misconfigured",
                    reason="TUNNEL_PUBLIC_URL not set; webhook can't be registered",
                )
            elif not settings.TELEGRAM_WEBHOOK_SECRET:
                logger.error(
                    "telegram_webhook_misconfigured",
                    reason="TELEGRAM_WEBHOOK_SECRET not set; refusing to register without HMAC",
                )
            else:
                webhook_url = (
                    settings.TUNNEL_PUBLIC_URL.rstrip("/")
                    + "/api/webhooks/telegram"
                )
                try:
                    await tg.bot.set_webhook(
                        url=webhook_url,
                        secret_token=settings.TELEGRAM_WEBHOOK_SECRET,
                        drop_pending_updates=False,
                    )
                    logger.info(
                        "telegram_mode_active",
                        mode="webhook",
                        url=webhook_url,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.error(
                        "telegram_webhook_register_failed",
                        url=webhook_url,
                        error=str(exc),
                    )
    else:
        logger.warning("telegram_disabled_no_token")

    yield

    logger.info("shutdown_begin")

    if hasattr(app.state, "telegram_polling_app"):
        polling_app = app.state.telegram_polling_app
        try:
            await polling_app.updater.stop()
            await polling_app.stop()
            await polling_app.shutdown()
            logger.info("telegram_long_polling_stopped")
        except Exception as exc:  # noqa: BLE001
            logger.error("telegram_shutdown_error", error=str(exc))

    await close_checkpointer()
    await close_db()
    logger.info("shutdown_done")


def _allowed_cors_origins() -> list[str]:
    """Lock CORS to the public dashboard origin (Phase 4) and nothing else.

    Same-origin browser requests don't pass through CORS, so the backend
    serving its own dashboard from the same host doesn't need to allowlist
    itself. We allowlist *cross*-origin callers, of which there's exactly
    one in Phase 1: the dashboard at TUNNEL_PUBLIC_URL.

    Wide-open CORS plus allow_credentials=True is a safety footgun: a
    malicious page on any domain could trigger state-changing requests
    using the master's session cookie. Locking origins to a single explicit
    URL closes that. Browsers also reject `*` when credentials are involved
    — so an empty allowlist here is strictly safer than a permissive one.

    Phase 4 adds the dev origin (e.g. http://localhost:3002) to support
    `next dev` against this backend. For now the prod tunnel URL is enough
    — there's no frontend yet to need anything else."""
    origins: list[str] = []
    if settings.TUNNEL_PUBLIC_URL:
        origins.append(settings.TUNNEL_PUBLIC_URL.rstrip("/"))
    return origins


def create_app() -> FastAPI:
    app = FastAPI(
        title="Jarvis AI Agent",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_allowed_cors_origins(),
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-API-Key"],
    )
    app.include_router(api_router, prefix="/api")
    return app


app = create_app()
