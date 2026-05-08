"""
Database engine + session factory.

We expose two surfaces:
  - `engine` / `async_session` — used directly by app code that wants its own
    transaction scope (the LangGraph nodes, the memory consolidation Celery
    job, etc.)
  - `get_session()` — FastAPI dependency that yields an AsyncSession per
    request and cleans it up afterwards.

`init_db()` runs a single SELECT 1 at app startup — not a migration. Migrations
are managed by Alembic and run separately. The startup probe just confirms the
connection works before we start serving traffic.
"""
from collections.abc import AsyncIterator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings


engine = create_async_engine(
    settings.DATABASE_URL,
    echo=(settings.ENVIRONMENT == "development"),
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,   # cheap liveness check on borrow — survives postgres restarts
    pool_recycle=3600,    # recycle idle connections after 1h to avoid stale TCP
)

async_session = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,   # keep ORM objects usable after commit() without re-fetch
)


async def init_db() -> None:
    """Smoke-test the connection on startup. SQLAlchemy 2.0 requires text() for raw SQL."""
    async with engine.begin() as conn:
        await conn.execute(text("SELECT 1"))


async def close_db() -> None:
    """Drain the pool cleanly on shutdown."""
    await engine.dispose()


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency. Use as `session: AsyncSession = Depends(get_session)`."""
    async with async_session() as session:
        yield session
