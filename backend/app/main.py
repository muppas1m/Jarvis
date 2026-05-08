"""
FastAPI app factory + lifespan.

Starts the engine pool, mounts the API router, leaves shutdown clean.

Heads up: `app.api.router` does not exist yet — it lands in a later commit
(api/router.py + the chat/webhooks/approvals modules underneath). Importing
this module before then will fail. The container's CMD points at this file,
which is why the backend service can't `up` cleanly until the router is in.
"""
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.config import settings
from app.db.engine import close_db, init_db
from app.utils.logging import configure_logging, get_logger


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    """Bring up resources before serving traffic, drain them on shutdown."""
    configure_logging()
    logger = get_logger(__name__)
    logger.info("startup_begin", environment=settings.ENVIRONMENT)

    await init_db()
    logger.info("db_engine_ready")

    yield

    logger.info("shutdown_begin")
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
