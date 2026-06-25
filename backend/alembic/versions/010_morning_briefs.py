"""morning_briefs — persisted proactive brief so the HUD can surface it (persist-then-poll)

Revision ID: 010_morning_briefs
Revises: 009_briefing_items
Create Date: 2026-06-25

A NEW table (not in the 001 monolithic schema — verified absent). The 7am morning
brief is Celery-driven with no active stream, so the HUD surfaces it via persist-then-
poll: the task persists the structured digest here, the HUD polls /api/briefing/latest.
``payload`` is the JSONB structured digest (days → items: title/source/preview/urgency
+ empty/total/timezone), rendered natively + XSS-safe in the HUD. Telegram delivery is
unchanged + independent of this persist.

**Numbered 010 from disk** (001-009 present; 009_briefing_items is the prior head).
Hand-written. created_at is indexed for the "latest within a freshness window" read.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "010_morning_briefs"
down_revision: str | Sequence[str] | None = "009_briefing_items"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "morning_briefs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("payload", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_morning_briefs_created_at", "morning_briefs", ["created_at"])


def downgrade() -> None:
    op.drop_table("morning_briefs")
