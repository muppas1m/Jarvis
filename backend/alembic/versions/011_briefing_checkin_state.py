"""user_profiles.last_briefed_at + last_seen_at — the proactive-briefing check-in state (Phase 5.4)

Two scalars on the single-row profile (like briefing_hwm) that drive the deterministic
"when to brief" decision riding each turn:
  - last_briefed_at: when the master last heard a 'latest' brief. The COOLDOWN key — a
    proactive brief won't re-fire within BRIEFING_COOLDOWN_MINUTES (an explicit ask still
    answers). Stamped at the same seam as the HWM advance (briefing_state.mark_briefed).
  - last_seen_at: the previous sighting. Drives the gap ("away N days") + first-interaction-
    of-the-day signals. Read for the gap, then advanced to now each turn (touch_last_seen).

Both NULLABLE (NULL until the first brief / first turn). Plain typed columns — NOT in
always_on/on_demand, so they never enter the prompt. The unheard count rides the existing
ix_briefing_items_occurred_at index (no new index).

**Numbered 011 from disk** (001-010 present; head is 010_morning_briefs). Hand-written.
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "011_briefing_checkin_state"
down_revision: str | Sequence[str] | None = "010_morning_briefs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_profiles",
        sa.Column("last_briefed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "user_profiles",
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_profiles", "last_seen_at")
    op.drop_column("user_profiles", "last_briefed_at")
