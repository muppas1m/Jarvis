"""audit_trail.latency_ms — per-tool execution latency

Revision ID: 004_audit_trail_latency
Revises: 003_email_logs_meta
Create Date: 2026-06-09

Turn 17.9 (task r). Adds a nullable ``latency_ms`` column to ``audit_trail`` so
tool-execution time — the single most valuable tool-performance signal — is
captured alongside every audit row. Nullable because pre-instrumentation rows
(and the approval-lifecycle rows that have no dispatched execution) carry no
latency.

**Numbered 004 from disk** (001+002+003 present; ``alembic current`` was 003),
NOT the plan's stale "005" — the plan's migration numbers ran ahead of disk
because the Task 2.16b documents migration was a verified no-op that never
consumed a number on disk. Disk is canonical (``project_phase1_monolithic_migration.md``).
Verified live that ``audit_trail`` had no ``latency_ms`` column before writing this.
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


revision: str = "004_audit_trail_latency"
down_revision: str | Sequence[str] | None = "003_email_logs_meta"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("audit_trail", sa.Column("latency_ms", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("audit_trail", "latency_ms")
