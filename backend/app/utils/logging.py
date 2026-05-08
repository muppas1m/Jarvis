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
