"""
FastAPI app factory + lifespan.

Starts the engine pool, mounts the API router, leaves shutdown clean.

Heads up: `app.api.router` does not exist yet — it lands in a later commit
(api/router.py + the chat/webhooks/approvals modules underneath). Importing
this module before then will fail. The container's CMD points at this file,
which is why the backend service can't `up` cleanly until the router is in.
"""
import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agent.graph import close_checkpointer, init_checkpointer
from app.agent.tools import register_all_tools
from app.agent.tools.registry import tool_registry
from app.api.router import api_router
from app.config import settings
from app.db.engine import close_db, init_db
from app.messaging.channels.telegram import get_telegram_channel
from app.messaging.normalizer import channel_registry
from app.utils.logging import configure_logging, get_logger


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Bring up resources before serving traffic, drain them on shutdown.

    Order matters:
      - DB engine first (cheap; needed by everything else).
      - Checkpointer second (depends on DB pool; opens its own pg connection
        for AsyncPostgresSaver and is what the agent graph builds against).
      - Tool registration third (needs the registry module imported and the
        memory layer reachable; index_all_tools writes to pgvector).
      - Channel registration + polling start last — channels deliver INTO
        the agent stack so everything they call needs to be ready first.
    Shutdown reverses that order, except the registry has no resources to close.
    """
    configure_logging()
    logger = get_logger(__name__)
    logger.info("startup_begin", environment=settings.ENVIRONMENT)

    await init_db()
    logger.info("db_engine_ready")

    await init_checkpointer()
    logger.info("checkpointer_ready")

    register_all_tools()
    await tool_registry.index_all_tools()
    logger.info("tools_indexed", count=len(tool_registry))

    # --- channels -----------------------------------------------------------
    # Telegram is the Phase 1 primary. Construct lazily so a missing token
    # raises here (in lifespan, where logs are visible) rather than at
    # module import.
    if settings.TELEGRAM_BOT_TOKEN:
        tg = get_telegram_channel()
        channel_registry.register(tg)
        logger.info("telegram_channel_registered")

        if settings.TELEGRAM_USE_POLLING:
            polling_app = tg.build_polling_application()
            await polling_app.initialize()
            await polling_app.start()
            # The updater is what actually long-polls Telegram. Run it in
            # a background task so this lifespan call returns and FastAPI
            # can start serving HTTP.
            asyncio.create_task(polling_app.updater.start_polling())
            app.state.telegram_polling_app = polling_app
            logger.info("telegram_long_polling_started")
        else:
            logger.info(
                "telegram_polling_disabled",
                hint="webhook mode active — incoming updates land via /api/webhooks/telegram",
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


def create_app() -> FastAPI:
    app = FastAPI(
        title="Jarvis AI Agent",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.BASE_URL],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router, prefix="/api")
    return app


app = create_app()
