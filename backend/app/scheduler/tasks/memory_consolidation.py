"""Nightly memory consolidation (beat: 2am UTC).

Wraps `app.memory.consolidation.run_consolidation` (4.B.2). SAFETY DEFAULT: this
scheduled run is DRY-RUN until `MEM0_CONSOLIDATION_AUTO_APPLY` is flipped on — it
logs the plan it WOULD apply and mutates nothing, so the beat can't quietly start
deleting the master's memories before a human has reviewed a dry-run. Once the
master is satisfied with a dry-run, flipping the setting on hands periodic
auto-apply to this beat (run_consolidation is idempotent + conservative).
"""
import asyncio

from app.config import settings
from app.scheduler.celery_app import celery_app
from app.scheduler.task_helpers import reset_async_state_for_task
from app.utils.logging import get_logger

logger = get_logger(__name__)


@celery_app.task(name="app.scheduler.tasks.memory_consolidation.consolidate_memory")
def consolidate_memory():
    asyncio.run(_run())


async def _run() -> None:
    await reset_async_state_for_task()
    from app.memory.consolidation import run_consolidation

    apply = settings.MEM0_CONSOLIDATION_AUTO_APPLY
    report = await run_consolidation(dry_run=not apply)
    logger.info(
        "memory_consolidation_ran",
        mode="apply" if apply else "dry_run",
        **report.summary(),
    )
