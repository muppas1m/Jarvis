"""Per-task async state reset.

Every Celery task wraps its body in `asyncio.run(...)`, which creates a new
event loop. SQLAlchemy's async engine pool and LangGraph's AsyncPostgresSaver
bind to whatever loop is active when they first acquire a connection. Across
multiple sequential tasks in the same worker process, those bindings go stale
— the second task's asyncio.run sees pool state from the first task's now-
dead loop and fails with "Future attached to a different loop".

`reset_async_state_for_task()` is called at the top of each task's async body.
It disposes the engine (which closes the dead-loop-bound connections; the
next connection acquisition creates fresh ones in the CURRENT loop) and
resets the checkpointer singleton so its next call re-opens against the
current loop.

Cost: ~50ms per task (engine dispose + checkpointer reopen). Negligible for
scheduled tasks that run hourly or daily.

Pattern reused from Phase 1's test_resume_dedup fixture, which faced the
same issue with pytest-asyncio's per-test loop scoping."""
from app.utils.logging import get_logger

logger = get_logger(__name__)


async def reset_async_state_for_task() -> None:
    """Dispose engine + checkpointer so they rebind to the current event loop.

    Idempotent: safe to call from any task body, multiple times if needed.
    Errors during cleanup are swallowed (the previous loop is dead anyway;
    we just want the next acquisition to be fresh)."""
    from app.agent import graph as graph_module
    from app.db.engine import engine

    try:
        await engine.dispose()
    except Exception as exc:  # noqa: BLE001
        logger.debug("engine_dispose_failed_swallowed", error=str(exc))

    # redis.asyncio pools bind to the loop that first touched them, same as the
    # engine. The Celery email path (gmail_check → classifier/responder →
    # gateway → cost_tracker) touches both pools below, so a second task on a
    # fresh asyncio.run loop would hit "Event loop is closed" without this
    # rebind. aclose disconnects; the next command reconnects on the current
    # loop. Best-effort — a dead-loop pool can raise on close.
    try:
        from app.agent.rate_limits import rate_limiter
        await rate_limiter.redis.aclose()
    except Exception:  # noqa: BLE001
        pass
    try:
        from app.llm.gateway import llm_gateway
        await llm_gateway.cost_tracker.redis.aclose()
    except Exception:  # noqa: BLE001
        pass

    if graph_module._checkpointer_cm is not None:
        try:
            await graph_module._checkpointer_cm.__aexit__(None, None, None)
        except Exception:  # noqa: BLE001
            pass
        graph_module._checkpointer = None
        graph_module._checkpointer_cm = None

    # Eagerly re-open the checkpointer in the current loop so tasks that
    # call into the graph (approval_expiry's expired-resume path) don't
    # hit a "checkpointer not initialized" error.
    await graph_module.init_checkpointer()
