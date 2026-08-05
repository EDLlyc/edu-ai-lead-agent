"""Add source-scoped HTTP fallback and topic priority policy metadata."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260804_0017"
down_revision: str | None = "20260804_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "source_versions",
        sa.Column(
            "allow_http_fallback",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.add_column(
        "source_versions",
        sa.Column("topic_priority_policy", sa.String(length=80), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("source_versions", "topic_priority_policy")
    op.drop_column("source_versions", "allow_http_fallback")
