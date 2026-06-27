"""Session-wide test fixtures.

The async-state-rebind footgun (project_async_state_rebind_pattern): module-level
async clients — the SQLAlchemy engine pool AND the redis.asyncio pools on
``rate_limiter`` and the gateway's ``cost_tracker`` — bind their connections to
whichever event loop first touched them. pytest-asyncio gives each test its own
loop, so a test that reuses one of these on a fresh loop hits "Future attached to
a different loop" / "Event loop is closed". That made the full suite fail for
resume_dedup + tool_selector when run together (they pass in isolation), and
resurfaces whenever a *second* full-graph (run_turn) test lands — the agent path
touches the rate-limiter pool, so two such tests in one session collide.

Disposing these pools before each test forces a clean rebind to the current
test's loop. Best-effort everywhere: closing connections owned by a now-dead
loop can raise, and that's noise, not a failure.
"""
import pytest

from app.db.engine import engine
from app.db.test_provisioning import (
    DBIsolationError,
    assert_isolated,
    ensure_test_database,
)


def pytest_configure(config):
    """Data-safety gate — runs ONCE before collection, before any test imports a
    session. (1) HARD GUARD: refuse the whole run if the engine is bound to the prod
    DB (the 2026-06-27 incident: the suite wrote to the master's live data). (2)
    Provision a pristine isolated test DB for this session. A failure here aborts the
    run loudly rather than letting a single test touch prod."""
    try:
        assert_isolated()
        ensure_test_database(drop_first=True)
    except DBIsolationError as exc:
        pytest.exit(f"\n*** DB ISOLATION GUARD TRIPPED ***\n{exc}\n", returncode=1)
    except Exception as exc:  # provisioning failure → fail loud, never fall through to prod
        pytest.exit(f"\n*** test DB provisioning failed ***\n{exc!r}\n", returncode=1)


async def _aclose(client) -> None:
    """Disconnect a redis.asyncio pool; the next command reconnects on the
    current loop. Swallow errors — a dead-loop pool can raise on close."""
    try:
        await client.aclose()
    except Exception:
        pass


@pytest.fixture(autouse=True)
async def _rebind_async_state():
    """Rebind module-level async pools (DB engine + redis) to THIS test's loop."""
    try:
        await engine.dispose()
    except Exception:
        pass

    # redis.asyncio pools on the run_turn path. Imported lazily so an import
    # error in one module can't break the whole fixture.
    try:
        from app.agent.rate_limits import rate_limiter
        await _aclose(rate_limiter.redis)
    except Exception:
        pass
    try:
        from app.llm.gateway import llm_gateway
        await _aclose(llm_gateway.cost_tracker.redis)
    except Exception:
        pass

    yield
