"""Session-wide test fixtures.

The async-state-rebind footgun (project_async_state_rebind_pattern): the
module-level SQLAlchemy engine binds its pooled connections to whichever event
loop first touched them. pytest-asyncio gives each test its own loop, so a test
that reuses the engine on a fresh loop hits "Future attached to a different loop"
/ connection-termination errors — which made the FULL suite fail for
resume_dedup + tool_selector when run together (they pass in isolation).

Disposing the engine pool before each test forces a clean rebind to the current
test's loop. Added in Turn 20.5b so the whole suite (and the coverage baseline)
runs green end-to-end, not just in subsets.
"""
import pytest

from app.db.engine import engine


@pytest.fixture(autouse=True)
async def _rebind_engine():
    """Dispose the engine pool before each test so connections rebind to THIS
    test's event loop. Dispose is best-effort — closing connections owned by a
    now-dead loop can raise; that's noise, not a failure."""
    try:
        await engine.dispose()
    except Exception:
        pass
    yield
