"""Persist ordered visual references for generated image artifacts."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260804_0015"
down_revision: str | None = "20260803_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "image_artifacts",
        sa.Column(
            "reference_mode",
            sa.String(length=30),
            server_default=sa.text("'legacy_single'"),
            nullable=False,
        ),
    )
    op.add_column(
        "image_artifacts",
        sa.Column(
            "visual_brief_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_image_artifacts_reference_mode",
        "image_artifacts",
        "reference_mode IN ("
        "'legacy_single', 'single_reference', 'single_fallback', "
        "'budgeted_multi_reference', 'multi_reference'"
        ")",
    )
    op.create_check_constraint(
        "ck_image_artifacts_visual_brief_snapshot_object",
        "image_artifacts",
        "jsonb_typeof(visual_brief_snapshot) = 'object'",
    )
    op.create_table(
        "image_artifact_references",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "image_artifact_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("image_artifacts.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("asset_id", sa.String(length=64), nullable=False),
        sa.Column("reference_role", sa.String(length=40), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("asset_sha256", sa.String(length=64), nullable=False),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("catalog_version", sa.String(length=80), nullable=False),
        sa.Column("selector_version", sa.String(length=80), nullable=False),
        sa.Column("selection_reason", sa.String(length=500), nullable=False),
        sa.Column("fallback_used", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("ordinal >= 0", name="ck_image_artifact_references_ordinal"),
        sa.CheckConstraint("asset_id <> ''", name="ck_image_artifact_references_asset_id"),
        sa.CheckConstraint("reference_role <> ''", name="ck_image_artifact_references_role"),
        sa.UniqueConstraint(
            "image_artifact_id", "ordinal", name="uq_image_artifact_references_artifact_ordinal"
        ),
    )
    op.create_index(
        "ix_image_artifact_references_asset_id",
        "image_artifact_references",
        ["asset_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_image_artifact_references_asset_id", table_name="image_artifact_references")
    op.drop_table("image_artifact_references")
    op.drop_constraint(
        "ck_image_artifacts_visual_brief_snapshot_object", "image_artifacts", type_="check"
    )
    op.drop_constraint("ck_image_artifacts_reference_mode", "image_artifacts", type_="check")
    op.drop_column("image_artifacts", "visual_brief_snapshot")
    op.drop_column("image_artifacts", "reference_mode")
