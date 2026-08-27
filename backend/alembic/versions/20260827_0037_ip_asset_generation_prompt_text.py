"""Allow non-blank IP asset generation prompts of any product-level length."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260827_0037"
down_revision: str | None = "20260825_0036"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "ip_asset_generation_jobs",
        "prompt",
        existing_type=sa.String(length=2_000),
        type_=sa.Text(),
        existing_nullable=False,
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DO $$
            BEGIN
                IF EXISTS (
                    SELECT 1
                    FROM ip_asset_generation_jobs
                    WHERE char_length(prompt) > 2000
                ) THEN
                    RAISE EXCEPTION
                        'cannot downgrade: IP asset generation prompts exceed 2000 characters';
                END IF;
            END
            $$;
            """
        )
    )
    op.alter_column(
        "ip_asset_generation_jobs",
        "prompt",
        existing_type=sa.Text(),
        type_=sa.String(length=2_000),
        existing_nullable=False,
    )
