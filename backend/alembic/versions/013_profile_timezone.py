"""timezone as a first-class profile field (B1-TZ / R2)

The issue-2 "5:00 pm" class closes only once the master's REAL timezone is set; UNSET is a
meaningful state (the fail-visible marker + the ask-once capture live on it) — never a silent
"UTC". Numbered 013 from disk (head was 012_approval_outcome). Hand-written.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "013_profile_timezone"
down_revision: str | Sequence[str] | None = "012_approval_outcome"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("user_profiles", sa.Column("timezone", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("user_profiles", "timezone")
