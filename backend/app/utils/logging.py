"""
Structured logging helper — single import point for the rest of the codebase.

Output format:
  - dev (`ENVIRONMENT=development`): pretty console with colors, easy to scan
  - prod: JSON, one log object per line, ingestible by Loki/CloudWatch/etc.

Both forms include ISO timestamps and the log level. Context vars (set via
structlog.contextvars.bind_contextvars) flow through automatically — request
IDs and thread IDs surface in every line of a turn.

Idempotent: configure_logging() can be called multiple times safely.
"""
import logging

import structlog

from app.config import settings


def configure_logging() -> None:
    """Call once at app startup (FastAPI lifespan, Celery worker init, scripts)."""
    logging.basicConfig(
        level=settings.LOG_LEVEL,
        format="%(message)s",   # structlog renders the actual content
    )

    # Quiet the chattiest third-party loggers so the real signal isn't drowned
    # (they flood especially at LOG_LEVEL=DEBUG):
    #   - httpx / httpcore: one line per request (every provider call).
    #   - telegram / apscheduler: python-telegram-bot's long-poll logs
    #     "getUpdates" + "No new updates found" every ~10s.
    #   - LiteLLM: its verbose_logger dumps the full param dict
    #     ("Params passed to completion()") on EVERY call (worst offender).
    # Pinned to WARNING so only real failures surface.
    for noisy in ("httpx", "httpcore", "telegram", "apscheduler", "LiteLLM"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    is_prod = settings.ENVIRONMENT == "production"

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.TimeStamper(fmt="iso"),
            (
                structlog.processors.JSONRenderer()
                if is_prod
                else structlog.dev.ConsoleRenderer(colors=True)
            ),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO)
        ),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    """Returns a structlog logger. Pass `__name__` from the calling module."""
    return structlog.get_logger(name)
