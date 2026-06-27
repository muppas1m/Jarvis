"""pending_approvals.outcome_detail — the execution outcome of an approved action

Restores what the non-blocking cutover (88ad34d) dropped: the agent knowing what
happened to an APPROVED action. The status lifecycle gains terminal ``executed`` /
``failed`` (post-dispatch, set in code — ``status`` is a free String, no enum change),
and this column carries the short human detail of the dispatch result ("Email sent to
X (id …)" / "invalid recipient" / "Calendar event 'Standup' created").

NULLABLE — only resolved+dispatched rows carry it; pending/rejected/discarded rows leave
it NULL. The recent-outcomes read (app.approvals_service.list_recent_outcomes) filters on
status IN (executed, failed); at single-master scale that rides the existing
ix_pending_approvals_status index — no new index (promote on table growth).

**Numbered 012 from disk** (head was 011_briefing_checkin_state). Hand-written.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "012_approval_outcome"
down_revision: str | Sequence[str] | None = "011_briefing_checkin_state"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "pending_approvals",
        sa.Column("outcome_detail", sa.Text(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("pending_approvals", "outcome_detail")
