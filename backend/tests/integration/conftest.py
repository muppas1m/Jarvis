"""Shared fixtures for the real-stack integration tests (Turn 20.5b).

These tests hit real Postgres + Redis + Mem0 + the LangGraph checkpointer. The
async-state-rebind footgun (project_async_state_rebind_pattern) bites here:
pytest-asyncio gives each test its own event loop, but the module-level
SQLAlchemy engine and the cached LangGraph checkpointer bind to whichever loop
first touched them. Crossing into a new per-test loop fails with
"Future attached to a different loop". The fixtures below reuse the
dispose+rebind pattern proven in test_resume_dedup.py — don't reinvent it.
"""
import pytest


@pytest.fixture
async def real_checkpointer():
    """Open the AsyncPostgresSaver against live Postgres, scoped to this test's
    loop. Same dispose+reinit as test_resume_dedup.py."""
    from app.agent import graph as graph_module
    from app.agent.graph import init_checkpointer

    if graph_module._checkpointer_cm is not None:
        try:
            await graph_module._checkpointer_cm.__aexit__(None, None, None)
        except Exception:
            pass
        graph_module._checkpointer = None
        graph_module._checkpointer_cm = None

    await init_checkpointer()
    yield
    # Don't close — the runner's module-level cached graph holds a reference;
    # the container's shutdown cleans up at process exit.


@pytest.fixture
async def reset_runner_graph():
    """Force the runner to rebuild the graph on next use (so patches + a fresh
    checkpointer take effect)."""
    import app.agent.runner as runner

    runner._graph = None
    yield
    runner._graph = None
