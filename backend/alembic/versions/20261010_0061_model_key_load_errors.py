"""Distinguish successfully applied model key versions from failed loads."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261010_0061"
down_revision: str | None = "20261010_0060"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Do not backfill {}: legacy versions may have been reported before decryption succeeded.
    op.add_column(
        "model_key_consumers", sa.Column("load_errors", postgresql.JSONB(), nullable=True)
    )


def downgrade() -> None:
    # Ephemeral diagnostics only; consumers recreate their heartbeat every minute.
    op.drop_column("model_key_consumers", "load_errors")
