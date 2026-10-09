"""Which service loaded which model key version, reported by each long-running process."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261009_0059"
down_revision: str | None = "20261009_0058"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_key_consumers",
        sa.Column("service", sa.String(60), nullable=False),
        sa.Column("host", sa.String(100), nullable=False),
        # Newest version per provider this process loaded at start; null if that read failed.
        sa.Column("versions", postgresql.JSONB(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("service", "host"),
    )


def downgrade() -> None:
    # Heartbeats only; every process writes its row again within a minute.
    op.drop_table("model_key_consumers")
