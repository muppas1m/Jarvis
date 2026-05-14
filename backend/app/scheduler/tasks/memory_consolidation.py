"""Memory consolidation — Turn 17 stub.

Real implementation lands in Turn 26.5 (see jarvis-implementation-plan.md
"Close-out Turns" section). The stub keeps the beat schedule honest — beat
fires this task nightly at 2am UTC, the worker logs that it ran, no work
happens. When Turn 26.5 lands the real `run_consolidation()` from
`app/memory/consolidation.py`, this file gets the import-and-call body
swapped in. Beat schedule stays the same.

Reason for stub-not-real: consolidation strategy + conflict-detection
integration is a multi-day design problem, and by Phase 3 close the agent
has accumulated enough real conversation history to make consolidation
meaningfully evaluable. Rushing it during Phase 2 build-out would have
shipped half-baked logic.
"""
import asyncio

from app.scheduler.celery_app import celery_app
from app.utils.logging import get_logger

logger = get_logger(__name__)


@celery_app.task(name="app.scheduler.tasks.memory_consolidation.consolidate_memory")
def consolidate_memory():
    """Stub. Real consolidation lands in Turn 26.5."""
    asyncio.run(_run())


async def _run() -> None:
    logger.info(
        "memory_consolidation_stub_ran",
        message="real consolidation deferred to Turn 26.5 per plan close-out section",
    )
