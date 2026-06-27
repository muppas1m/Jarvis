"""Regression lock for the test-DB isolation (the 2026-06-27 data-safety fix).

If a future change removes the config swap or reintroduces an engine-bypassing write
surface, THESE fail — that's the point. The companion empirical proof that the
briefing/approval tests leave prod byte-for-byte untouched is
``scripts/verify_prod_untouched.py`` (run out-of-band; it reads prod, this suite can't).
"""
from urllib.parse import urlparse

import pytest

from app.config import _db_name, settings
from app.db.test_provisioning import DBIsolationError, assert_isolated


def test_engine_url_is_an_isolated_test_db():
    assert settings.RUNTIME_DB_IS_TEST is True
    bound = _db_name(settings.DATABASE_URL)
    assert bound.endswith("_test"), bound
    assert bound != settings.PROD_DB_NAME, "engine must NOT be on the prod database"


def test_all_three_write_surfaces_follow_the_swap():
    # Engine (async DATABASE_URL).
    from app.db.engine import engine
    assert _db_name(str(engine.url)).endswith("_test")

    # LangGraph checkpointer (derives from DATABASE_URL_SYNC).
    from app.agent.graph import _checkpointer_conn_string
    assert _db_name(_checkpointer_conn_string()).endswith("_test")

    # Mem0 (mem0_client parses settings.DATABASE_URL → dbname). Mirror its parse here
    # so the assertion stays true even if Mem0's heavy client isn't constructed.
    mem0_dbname = urlparse(settings.DATABASE_URL.replace("+asyncpg", "")).path.lstrip("/")
    assert mem0_dbname.endswith("_test")


def test_assert_isolated_passes_under_test():
    assert_isolated()  # must not raise inside the isolated suite


def test_guard_trips_if_isolation_disengages(monkeypatch):
    # Simulate a botched/removed swap: the guard must REFUSE rather than fall through to prod.
    monkeypatch.setattr(settings, "RUNTIME_DB_IS_TEST", False)
    with pytest.raises(DBIsolationError):
        assert_isolated()


def test_guard_trips_if_bound_to_prod_name(monkeypatch):
    # Even with the test flag set, a database whose name matches prod must be rejected.
    monkeypatch.setattr(settings, "PROD_DB_NAME", _db_name(settings.DATABASE_URL))
    with pytest.raises(DBIsolationError):
        assert_isolated()
