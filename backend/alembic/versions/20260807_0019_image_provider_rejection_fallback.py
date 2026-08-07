"""Add bounded image-provider rejection recovery state."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260807_0019"
down_revision: str | None = "20260805_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "image_artifacts",
        sa.Column(
            "provider_rejection_retry_count",
            sa.Integer(),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )
    op.create_check_constraint(
        "ck_image_artifacts_provider_rejection_retry",
        "image_artifacts",
        "provider_rejection_retry_count >= 0 AND provider_rejection_retry_count <= 1",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_image_artifacts_provider_rejection_retry",
        "image_artifacts",
        type_="check",
    )
    op.drop_column("image_artifacts", "provider_rejection_retry_count")
