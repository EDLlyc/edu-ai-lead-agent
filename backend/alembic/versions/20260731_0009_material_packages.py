"""Add generated image artifacts and internal material packages."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260731_0009"
down_revision: str | None = "20260730_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "image_artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("draft_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("prompt_version", sa.String(length=80), nullable=False),
        sa.Column("pipeline_version", sa.String(length=80), nullable=False),
        sa.Column("reference_sha256", sa.String(length=64), nullable=True),
        sa.Column("provider_task_id", sa.String(length=200), nullable=True),
        sa.Column("provider_upload_id", sa.String(length=200), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("media_type", sa.String(length=120), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("byte_size", sa.BigInteger(), nullable=True),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("bucket", sa.String(length=120), nullable=True),
        sa.Column("object_key", sa.String(length=300), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed', 'review_required')",
            name="ck_image_artifacts_status",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_image_artifacts_attempt_count"),
        sa.CheckConstraint(
            "(status = 'succeeded' AND media_type IS NOT NULL AND width = 1024 "
            "AND height = 1024 AND byte_size IS NOT NULL AND sha256 IS NOT NULL "
            "AND bucket IS NOT NULL AND object_key IS NOT NULL) OR status <> 'succeeded'",
            name="ck_image_artifacts_success_shape",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["copy_generation_runs.id"],
            name="fk_image_artifacts_run_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["draft_version_id"],
            ["copy_draft_versions.id"],
            name="fk_image_artifacts_draft_version_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_image_artifacts"),
        sa.UniqueConstraint("request_fingerprint", name="uq_image_artifacts_request_fingerprint"),
        sa.UniqueConstraint("run_id", "draft_version_id", name="uq_image_artifacts_run_draft"),
    )
    op.create_index(
        "ix_image_artifacts_status_created", "image_artifacts", ["status", "created_at"]
    )
    op.create_table(
        "material_packages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("draft_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("image_artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("package_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("topic_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("copy_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("audit_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "review_status",
            sa.String(length=30),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("review_note", sa.String(length=500), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'ready', 'awaiting_manual_use', 'completed', "
            "'rejected', 'failed')",
            name="ck_material_packages_status",
        ),
        sa.CheckConstraint(
            "review_status IN ('pending', 'approved', 'rejected')",
            name="ck_material_packages_review_status",
        ),
        sa.CheckConstraint("package_version >= 1", name="ck_material_packages_version"),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["copy_generation_runs.id"],
            name="fk_material_packages_run_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["draft_version_id"],
            ["copy_draft_versions.id"],
            name="fk_material_packages_draft_version_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["image_artifact_id"],
            ["image_artifacts.id"],
            name="fk_material_packages_image_artifact_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_material_packages"),
        sa.UniqueConstraint("run_id", "package_version", name="uq_material_packages_run_version"),
        sa.UniqueConstraint("request_fingerprint", name="uq_material_packages_request_fingerprint"),
    )
    op.create_index(
        "ix_material_packages_status_created", "material_packages", ["status", "created_at"]
    )
    op.create_table(
        "material_reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("package_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("reviewer", sa.String(length=120), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "decision IN ('approved', 'rejected')", name="ck_material_reviews_decision"
        ),
        sa.ForeignKeyConstraint(
            ["package_id"],
            ["material_packages.id"],
            name="fk_material_reviews_package_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_material_reviews"),
        sa.UniqueConstraint("package_id", name="uq_material_reviews_package_id"),
    )


def downgrade() -> None:
    op.drop_table("material_reviews")
    op.drop_index("ix_material_packages_status_created", table_name="material_packages")
    op.drop_table("material_packages")
    op.drop_index("ix_image_artifacts_status_created", table_name="image_artifacts")
    op.drop_table("image_artifacts")
