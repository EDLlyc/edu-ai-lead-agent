"""Model provider keys rotated in the 运营后台 (模型配置), as an immutable version history."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261009_0058"
down_revision: str | None = "20261009_0057"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "model_api_keys",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        # Null means "use the key from the environment" (a rollback to before the console).
        sa.Column("key_sealed", sa.Text(), nullable=True),
        sa.Column("key_last4", sa.String(4), nullable=True),
        sa.Column("note", sa.String(200), nullable=True),
        sa.Column("restored_from", sa.Integer(), nullable=True),
        sa.Column("probe_latency_ms", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "version", name="uq_model_api_keys_provider_version"),
        sa.CheckConstraint(
            "provider IN ('zhipu', 'comfly', 'alibaba-visual')", name="ck_model_api_keys_provider"
        ),
        sa.CheckConstraint("version >= 1", name="ck_model_api_keys_version"),
        sa.CheckConstraint(
            "(key_sealed IS NULL AND key_last4 IS NULL) "
            "OR (key_sealed LIKE 'v1:%' AND key_last4 IS NOT NULL)",
            name="ck_model_api_keys_sealed",
        ),
    )


def downgrade() -> None:
    # Dropping the history returns every process to its environment keys on the next start.
    op.drop_table("model_api_keys")
