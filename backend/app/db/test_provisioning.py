"""Self-bootstrapping isolated test database + the data-safety guard.

Companion to ``app.config._isolate_test_db``: that swaps the URLs to ``<db>_test``
when under test; THIS provisions that database (the app role ``jarvis_app`` has no
CREATEDB, so the ``jarvis_admin`` superuser creates it + the ``vector`` extension)
and seeds the single-row ``UserProfile`` the briefing/approval tests assume exists.

Called by ``tests/conftest.py`` (``drop_first=True`` — a pristine DB per session)
and by ``scripts/_smoke_isolation.py`` (``drop_first=False`` — ensure-exists). Both
sit behind ``assert_isolated()`` so we can NEVER provision/seed against prod.

Everything here is synchronous (psycopg) so it runs cleanly in ``pytest_configure``
and at smoke import time, before any event loop or the async engine is touched.
"""
import os
from urllib.parse import urlsplit, urlunsplit

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.config import _db_name, settings


class DBIsolationError(RuntimeError):
    """Raised when the running process is NOT safely bound to an isolated test DB."""


def assert_isolated() -> None:
    """Hard guard — refuse to proceed unless every DB surface is bound to a distinct
    ``_test`` database. The check is on the LIVE engine object, not just settings, so a
    stale import or a missed swap is caught. This is what makes "a test can never touch
    prod" structural rather than a convention."""
    if not settings.RUNTIME_DB_IS_TEST:
        raise DBIsolationError(
            "DB isolation did not engage (settings.RUNTIME_DB_IS_TEST is False). "
            "config._isolate_test_db only swaps under pytest or JARVIS_TEST_MODE=1."
        )
    bound = _db_name(settings.DATABASE_URL)
    if bound == settings.PROD_DB_NAME or not bound.endswith("_test"):
        raise DBIsolationError(
            f"Engine is bound to {bound!r}, which is not an isolated _test database "
            f"(prod is {settings.PROD_DB_NAME!r}). Refusing to run."
        )
    # Belt-and-suspenders: the actual async engine object must agree with settings.
    from app.db.engine import engine

    live = _db_name(str(engine.url))
    if live != bound:
        raise DBIsolationError(
            f"Live engine database {live!r} disagrees with settings {bound!r} — a module "
            f"imported the engine before the test-DB swap. Refusing to run."
        )


def _admin_url(maintenance_db: str = "postgres") -> str:
    """A sync superuser URL on the same server, pointed at a maintenance DB. ``jarvis_app``
    cannot CREATE DATABASE, so DB-level DDL runs as ``jarvis_admin`` (compose POSTGRES_USER)."""
    parts = urlsplit(settings.DATABASE_URL_SYNC)
    admin_user = os.getenv("POSTGRES_ADMIN_USER", "jarvis_admin")
    host = parts.hostname or "localhost"
    port = f":{parts.port}" if parts.port else ""
    netloc = f"{admin_user}:{settings.POSTGRES_ADMIN_PASSWORD}@{host}{port}"
    return urlunsplit(parts._replace(netloc=netloc, path=f"/{maintenance_db}"))


def ensure_test_database(*, drop_first: bool) -> None:
    """Provision the isolated test DB so the suite/smoke can run against it.

    drop_first=True  → DROP + CREATE (pristine, per-session for pytest).
    drop_first=False → CREATE only if missing (idempotent ensure, for smoke runs).

    Steps (admin): create the database owned by the app role + the ``vector`` extension;
    (app): create the ORM schema + seed one ``UserProfile`` row the tests rely on.
    """
    assert_isolated()  # never provision unless we are provably off prod

    test_db = _db_name(settings.DATABASE_URL)
    app_owner = urlsplit(settings.DATABASE_URL_SYNC).username or "jarvis_app"

    admin = create_engine(_admin_url(), isolation_level="AUTOCOMMIT")
    try:
        with admin.connect() as conn:
            exists = conn.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": test_db}
            ).scalar()
            if exists and drop_first:
                # Drop any leftover connections from a prior run, then the DB itself.
                conn.execute(
                    text(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname = :n AND pid <> pg_backend_pid()"
                    ),
                    {"n": test_db},
                )
                conn.execute(text(f'DROP DATABASE IF EXISTS "{test_db}"'))
                exists = False
            if not exists:
                conn.execute(text(f'CREATE DATABASE "{test_db}" OWNER "{app_owner}"'))
    finally:
        admin.dispose()

    # The vector extension is NOT trusted → must be created by the superuser, inside the
    # DB. Also (re)assert the app role's schema rights — belt-and-suspenders for PG16's
    # locked-down public schema, so create_all as the app role always succeeds.
    admin_db = create_engine(_admin_url(test_db), isolation_level="AUTOCOMMIT")
    try:
        with admin_db.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.execute(text(f'GRANT ALL ON SCHEMA public TO "{app_owner}"'))
    finally:
        admin_db.dispose()

    # ORM schema + seed, as the app role (owns the DB → has CREATE on public).
    from app.db.models import Base, UserProfile

    app_engine = create_engine(settings.DATABASE_URL_SYNC)
    try:
        Base.metadata.create_all(app_engine)
        with Session(app_engine) as s:
            has_profile = s.execute(text("SELECT 1 FROM user_profiles LIMIT 1")).scalar()
            if not has_profile:
                s.add(UserProfile(
                    name="Test Master",
                    always_on={"timezone": "America/New_York"},
                    on_demand={},
                ))
                s.commit()
    finally:
        app_engine.dispose()
