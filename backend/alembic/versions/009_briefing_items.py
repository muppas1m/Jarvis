"""briefing_items — the durable, windowable briefing store (Phase 5.1)

Revision ID: 009_briefing_items
Revises: 008_briefing_hwm
Create Date: 2026-06-25

A NEW table (not in the 001 monolithic schema — verified absent via the app DB
before writing this). The read-state briefing's backing store, windowed by
``occurred_at`` against UserProfile.briefing_hwm. ``kind`` (email | news) is the
news-on-subscribed-topics seam; the window engine is kind-agnostic. Chosen over
windowing EmailLog (which DOES have created_at, but is email-only, has no preview,
and leaves the locked news seam homeless).

**Numbered 009 from disk** (001-008 present; 008_briefing_hwm is the prior head).
Hand-written. The (kind, occurred_at) composite index serves the window query.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "009_briefing_items"
down_revision: str | Sequence[str] | None = "008_briefing_hwm"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "briefing_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("title", sa.String(length=500), nullable=True),
        sa.Column("source", sa.String(length=255), nullable=True),
        sa.Column("preview", sa.Text(), nullable=True),
        sa.Column("urgency", sa.String(length=20), nullable=True),
        sa.Column("meta", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_briefing_items_occurred_at", "briefing_items", ["occurred_at"])
    op.create_index("ix_briefing_items_kind_occurred", "briefing_items", ["kind", "occurred_at"])


def downgrade() -> None:
    op.drop_table("briefing_items")
