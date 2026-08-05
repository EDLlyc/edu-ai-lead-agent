"""Persist deterministic image validation, audit, and bounded repair state."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260804_0016"
down_revision: str | None = "20260804_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "image_artifacts",
        sa.Column("repair_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "image_artifacts",
        sa.Column(
            "validation_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "image_artifacts",
        sa.Column(
            "audit_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_image_artifacts_repair_count",
        "image_artifacts",
        "repair_count >= 0 AND repair_count <= 1",
    )
    op.create_check_constraint(
        "ck_image_artifacts_validation_snapshot_object",
        "image_artifacts",
        "jsonb_typeof(validation_snapshot) = 'object'",
    )
    op.create_check_constraint(
        "ck_image_artifacts_audit_snapshot_object",
        "image_artifacts",
        "jsonb_typeof(audit_snapshot) = 'object'",
    )


def downgrade() -> None:
    op.drop_constraint("ck_image_artifacts_audit_snapshot_object", "image_artifacts", type_="check")
    op.drop_constraint(
        "ck_image_artifacts_validation_snapshot_object", "image_artifacts", type_="check"
    )
    op.drop_constraint("ck_image_artifacts_repair_count", "image_artifacts", type_="check")
    op.drop_column("image_artifacts", "audit_snapshot")
    op.drop_column("image_artifacts", "validation_snapshot")
    op.drop_column("image_artifacts", "repair_count")
