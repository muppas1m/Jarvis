"""email_logs.meta JSONB — multi-dimensional triage persistence

Revision ID: 003_email_logs_meta
Revises: 002_langgraph_checkpoints
Create Date: 2026-06-08

Turn 17.8. Adds a single ``meta JSONB`` column to ``email_logs`` to persist the
full ``EmailTriageResult`` (classification + urgency + intent + confidence +
suggested_action) without a column-per-dimension sprawl — the same shape the
``document_chunks.meta`` column uses. ``server_default '{}'::jsonb`` so existing
pre-enrichment rows read as an empty object rather than NULL.

**NOT a no-op** (unlike Task 2.16b's already-present HNSW index): verified on the
live DB that ``email_logs`` had no ``meta`` column before writing this. Numbered
**003** from disk state (001 + 002 present), not the plan's stale "004" — disk is
canonical (project_phase1_monolithic_migration.md).
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "003_email_logs_meta"
down_revision: str | Sequence[str] | None = "002_langgraph_checkpoints"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "email_logs",
        sa.Column(
            "meta",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("email_logs", "meta")
