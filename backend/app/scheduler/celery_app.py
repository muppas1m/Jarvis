"""Celery app instance + per-worker-process initialization.

The Celery worker is a separate process from the FastAPI backend. State that
FastAPI's lifespan establishes (DB engine pool, AsyncPostgresSaver checkpointer,
channel registry) does NOT carry over — every Celery worker process must
initialize its own copies.

Plan-gap fill: Task 2.7's verbatim celery_app.py only creates the Celery
instance and autodiscovers tasks. Without explicit per-worker initialization,
half the scheduled tasks fail at runtime — approval_expiry needs the DB engine
for async_session, @critical_task's failure alerts need the channel registry,
gmail_renew + gmail_check need the Gmail service which is fine but anything
calling resume_turn needs the checkpointer.

The `worker_process_init` Celery signal fires once per worker process at
startup (each `--concurrency=N` spawns N processes). Initialize everything
the tasks need here.
"""
from celery import Celery
from celery.signals import worker_process_init

from app.config import settings
from app.utils.logging import get_logger


celery_app = Celery(
    "jarvis",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
    # Explicit include of task modules. autodiscover_tasks(["app.scheduler.tasks"])
    # would look for `app.scheduler.tasks.tasks` submodules per Celery's convention,
    # which isn't our layout. Listing each task module here is unambiguous.
    include=[
        "app.scheduler.task_wrapper",   # @critical_task uses celery_app.task at import time
        "app.scheduler.tasks.gmail_renew",
        "app.scheduler.tasks.gmail_check",
        "app.scheduler.tasks.inbound_health",
        "app.scheduler.tasks.morning_brief",
        "app.scheduler.tasks.memory_consolidation",
        "app.scheduler.tasks.approval_expiry",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_acks_late=True,
    worker_prefetch_multiplier=1,
)

# Pull in the beat schedule definitions at app build time (importing the
# module attaches conf.beat_schedule). Safe to import here; the file has no
# side effects beyond the schedule mutation.
from app.scheduler import beat_schedule  # noqa: E402, F401

# Task modules are explicitly listed in the Celery() include= above —
# autodiscover_tasks call removed (its convention didn't match our layout).


@worker_process_init.connect
def init_worker_process(**kwargs):
    """Per-worker-process synchronous bootstrap.

    DB engine + checkpointer cannot be pre-initialized here. Each Celery
    task wraps its body in `asyncio.run(...)`, which creates a fresh event
    loop. SQLAlchemy's async engine pool + LangGraph's AsyncPostgresSaver
    bind to whatever loop is active when they first acquire a connection
    — if we initialized them in a worker_process_init's asyncio.run, they
    would bind to THAT loop, which dies when worker_process_init returns.
    Subsequent task asyncio.runs would inherit dead-loop-bound state and
    fail with "Future attached to a different loop" errors.

    Instead: keep this hook synchronous (no asyncio.run), do only loop-
    independent setup (channel registry, which is just a dict mutation).
    DB engine + checkpointer rebind per-task via `reset_async_state_for_task`
    in app.scheduler.task_helpers, called at the top of each task's
    async body."""
    logger = get_logger("celery.worker.init")

    if settings.TELEGRAM_BOT_TOKEN:
        try:
            from app.messaging.channels.telegram import get_telegram_channel
            from app.messaging.channel_registry import channel_registry

            tg = get_telegram_channel()
            channel_registry.register(tg)
            logger.info("worker_telegram_channel_registered")
        except Exception as exc:  # noqa: BLE001
            logger.error("worker_channel_init_failed", error=str(exc))

    logger.info("worker_process_init_done")
