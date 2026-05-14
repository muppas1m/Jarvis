"""@critical_task decorator — alerts master after 3 consecutive failures.

Usage:
    @critical_task(name="...", max_retries=3)
    def some_celery_task(): ...

Failure tracking is in Redis (counter per task name, TTL 24h). After 3 failures,
sends a Telegram alert via the channel abstraction.
"""
import asyncio
import functools
import redis
from celery.exceptions import Retry

from app.config import settings
from app.scheduler.celery_app import celery_app
import structlog

logger = structlog.get_logger()
_redis = redis.from_url(settings.REDIS_URL.replace("/0", "/1"))  # different DB to keep clean


CONSECUTIVE_FAILURE_THRESHOLD = 3
FAILURE_KEY_TTL = 86400  # 24h


def critical_task(name: str, max_retries: int = 3, retry_backoff: int = 60):
    """Decorator combining Celery's retry + a Telegram alert on persistent failure."""

    def decorator(fn):
        @celery_app.task(
            name=name,
            bind=True,
            max_retries=max_retries,
            default_retry_delay=retry_backoff,
            acks_late=True,
        )
        @functools.wraps(fn)
        def wrapper(self, *args, **kwargs):
            failure_key = f"jarvis:critical_task_failures:{name}"
            try:
                result = fn(*args, **kwargs)
                # On success, reset the failure counter
                _redis.delete(failure_key)
                return result
            except Retry:
                raise
            except Exception as exc:
                count = _redis.incr(failure_key)
                _redis.expire(failure_key, FAILURE_KEY_TTL)
                logger.error(
                    "critical_task_failed",
                    task=name, attempt=count, error=str(exc),
                )

                if count >= CONSECUTIVE_FAILURE_THRESHOLD:
                    # Send a system alert via the master's primary channel
                    asyncio.run(_alert_master(name, str(exc), count))
                    # Reset so we don't spam — alert again only if it keeps failing
                    _redis.delete(failure_key)

                # Defer to Celery's retry mechanism
                raise self.retry(exc=exc, countdown=retry_backoff)

        return wrapper

    return decorator


async def _alert_master(task_name: str, error: str, failure_count: int):
    try:
        from app.messaging.failure_alerter import send_system_alert
        await send_system_alert(
            f"Scheduled task `{task_name}` has failed {failure_count} consecutive times.\n\n"
            f"Last error:\n```\n{error[:500]}\n```\n\n"
            f"Investigate via Langfuse traces or the audit log."
        )
    except Exception as e:
        logger.error("master_alert_failed", error=str(e))
