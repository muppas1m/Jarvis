"""langgraph checkpoint tables — created via PostgresSaver.setup()

Revision ID: 002_langgraph_checkpoints
Revises: 001_initial_schema
Create Date: 2026-05-08

LangGraph's AsyncPostgresSaver owns four tables (`checkpoints`,
`checkpoint_writes`, `checkpoint_blobs`, `checkpoint_migrations`) that hold the
graph's state between turns. They have their own internal versioning baked into
the SQL that PostgresSaver.setup() emits, so we let LangGraph manage their
schema rather than re-deriving it in this file.

This migration just calls the official setup() in upgrade and drops the tables
in downgrade. It is idempotent — re-running upgrade() against an already-set-up
DB is a no-op.
"""
from collections.abc import Sequence

from alembic import op


revision: str = "002_langgraph_checkpoints"
down_revision: str | Sequence[str] | None = "001_initial_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Imports inside the function so `alembic --help` and lint tools don't pull
    # heavy LangGraph imports for unrelated commands.
    from langgraph.checkpoint.postgres import PostgresSaver

    from app.config import settings

    # PostgresSaver expects a psycopg-style URL. Strip the SQLAlchemy "+psycopg"
    # qualifier — psycopg accepts the bare postgresql:// scheme just fine.
    sync_url = settings.DATABASE_URL_SYNC.replace("+psycopg", "")

    with PostgresSaver.from_conn_string(sync_url) as saver:
        saver.setup()


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS checkpoint_writes CASCADE")
    op.execute("DROP TABLE IF EXISTS checkpoint_blobs CASCADE")
    op.execute("DROP TABLE IF EXISTS checkpoints CASCADE")
    op.execute("DROP TABLE IF EXISTS checkpoint_migrations CASCADE")
