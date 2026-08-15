"""Add controlled visual diversity plans and perceptual similarity audit."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260815_0021"
down_revision: str | None = "20260814_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SLOTS = "'morning', 'noon', 'evening'"


def upgrade() -> None:
    for column in (
        sa.Column("diversity_policy_version", sa.String(length=80), nullable=True),
        sa.Column("perceptual_hash_version", sa.String(length=80), nullable=True),
        sa.Column("similarity_policy_version", sa.String(length=80), nullable=True),
        sa.Column(
            "diversity_retry_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "active_plan_ordinal",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("final_plan_ordinal", sa.Integer(), nullable=True),
        sa.Column("perceptual_hash", sa.String(length=16), nullable=True),
        sa.Column("diversity_warning", sa.String(length=80), nullable=True),
        sa.Column(
            "similarity_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    ):
        op.add_column("image_artifacts", column)
    op.create_check_constraint(
        "ck_image_artifacts_diversity_retry",
        "image_artifacts",
        "diversity_retry_count BETWEEN 0 AND 1",
    )
    op.create_check_constraint(
        "ck_image_artifacts_plan_ordinals",
        "image_artifacts",
        "active_plan_ordinal BETWEEN 1 AND 2 AND "
        "(final_plan_ordinal IS NULL OR final_plan_ordinal BETWEEN 1 AND 2)",
    )
    op.create_check_constraint(
        "ck_image_artifacts_perceptual_hash",
        "image_artifacts",
        "perceptual_hash IS NULL OR perceptual_hash ~ '^[0-9a-f]{16}$'",
    )
    op.create_check_constraint(
        "ck_image_artifacts_diversity_warning",
        "image_artifacts",
        "diversity_warning IS NULL OR diversity_warning = 'near_duplicate_after_retry'",
    )
    op.create_check_constraint(
        "ck_image_artifacts_similarity_snapshot_object",
        "image_artifacts",
        "jsonb_typeof(similarity_snapshot) = 'object'",
    )

    op.drop_constraint(
        "uq_image_artifact_references_artifact_ordinal",
        "image_artifact_references",
        type_="unique",
    )
    op.add_column(
        "image_artifact_references",
        sa.Column("attempt_ordinal", sa.Integer(), server_default=sa.text("1"), nullable=False),
    )
    op.add_column(
        "image_artifact_references",
        sa.Column("plan_reservation_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_image_artifact_references_attempt_ordinal",
        "image_artifact_references",
        "attempt_ordinal BETWEEN 1 AND 2",
    )
    op.create_unique_constraint(
        "uq_image_artifact_references_attempt_ordinal",
        "image_artifact_references",
        ["image_artifact_id", "attempt_ordinal", "ordinal"],
    )

    op.create_table(
        "image_visual_plan_reservations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("image_artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_ordinal", sa.Integer(), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("timezone", sa.String(length=80), nullable=False),
        sa.Column("content_slot", sa.String(length=20), nullable=True),
        sa.Column("plan_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("plan_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("prompt_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("reference_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("history_digest", sa.String(length=64), nullable=False),
        sa.Column("policy_version", sa.String(length=80), nullable=False),
        sa.Column("selector_version", sa.String(length=80), nullable=False),
        sa.Column("reference_mode", sa.String(length=30), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_image_visual_plan_reservations"),
        sa.ForeignKeyConstraint(
            ["image_artifact_id"],
            ["image_artifacts.id"],
            name="fk_image_visual_plan_reservations_artifact_id",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "attempt_ordinal BETWEEN 1 AND 2",
            name="ck_image_visual_plan_reservations_attempt_ordinal",
        ),
        sa.CheckConstraint(
            f"content_slot IS NULL OR content_slot IN ({_SLOTS})",
            name="ck_image_visual_plan_reservations_content_slot",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(plan_snapshot) = 'object'",
            name="ck_image_visual_plan_reservations_snapshot_object",
        ),
        sa.CheckConstraint(
            "reference_mode IN ('single_reference', 'single_fallback', "
            "'budgeted_multi_reference', 'multi_reference')",
            name="ck_image_visual_plan_reservations_reference_mode",
        ),
        sa.UniqueConstraint(
            "image_artifact_id",
            "attempt_ordinal",
            name="uq_image_visual_plan_reservations_artifact_attempt",
        ),
        sa.UniqueConstraint(
            "id",
            "image_artifact_id",
            "attempt_ordinal",
            name="uq_image_visual_plan_reservations_reference_identity",
        ),
        sa.UniqueConstraint(
            "business_date",
            "timezone",
            "plan_fingerprint",
            name="uq_image_visual_plan_reservations_day_plan",
        ),
    )
    op.create_index(
        "ix_image_visual_plan_reservations_history",
        "image_visual_plan_reservations",
        ["business_date", "timezone", "content_slot"],
    )
    op.create_foreign_key(
        "fk_image_artifact_references_plan_reservation_id",
        "image_artifact_references",
        "image_visual_plan_reservations",
        ["plan_reservation_id", "image_artifact_id", "attempt_ordinal"],
        ["id", "image_artifact_id", "attempt_ordinal"],
        ondelete="CASCADE",
    )

    op.create_table(
        "image_similarity_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("image_artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_ordinal", sa.Integer(), nullable=False),
        sa.Column("output_sha256", sa.String(length=64), nullable=False),
        sa.Column("perceptual_hash", sa.String(length=16), nullable=False),
        sa.Column("nearest_artifact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("nearest_distance", sa.Integer(), nullable=True),
        sa.Column("exact_duplicate", sa.Boolean(), nullable=False),
        sa.Column("near_duplicate", sa.Boolean(), nullable=False),
        sa.Column("threshold", sa.Integer(), nullable=False),
        sa.Column("hash_version", sa.String(length=80), nullable=False),
        sa.Column("policy_version", sa.String(length=80), nullable=False),
        sa.Column("decision", sa.String(length=40), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_image_similarity_attempts"),
        sa.ForeignKeyConstraint(
            ["image_artifact_id"],
            ["image_artifacts.id"],
            name="fk_image_similarity_attempts_artifact_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["nearest_artifact_id"],
            ["image_artifacts.id"],
            name="fk_image_similarity_attempts_nearest_artifact_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["image_artifact_id", "attempt_ordinal"],
            [
                "image_visual_plan_reservations.image_artifact_id",
                "image_visual_plan_reservations.attempt_ordinal",
            ],
            name="fk_image_similarity_attempts_plan_attempt",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "attempt_ordinal BETWEEN 1 AND 2",
            name="ck_image_similarity_attempts_attempt_ordinal",
        ),
        sa.CheckConstraint(
            "perceptual_hash ~ '^[0-9a-f]{16}$'",
            name="ck_image_similarity_attempts_perceptual_hash",
        ),
        sa.CheckConstraint(
            "nearest_distance IS NULL OR nearest_distance BETWEEN 0 AND 64",
            name="ck_image_similarity_attempts_distance",
        ),
        sa.CheckConstraint(
            "threshold BETWEEN 0 AND 64",
            name="ck_image_similarity_attempts_threshold",
        ),
        sa.CheckConstraint(
            "decision IN ('accepted', 'regenerate', 'accepted_with_warning')",
            name="ck_image_similarity_attempts_decision",
        ),
        sa.UniqueConstraint(
            "image_artifact_id",
            "attempt_ordinal",
            name="uq_image_similarity_attempts_artifact_attempt",
        ),
    )
    op.create_index(
        "ix_image_similarity_attempts_hash",
        "image_similarity_attempts",
        ["perceptual_hash", "created_at"],
    )


def downgrade() -> None:
    has_diversity_artifacts = op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS ("
            "SELECT 1 FROM image_visual_plan_reservations "
            "UNION ALL SELECT 1 FROM image_similarity_attempts "
            "UNION ALL SELECT 1 FROM image_artifacts "
            "WHERE diversity_policy_version IS NOT NULL OR diversity_retry_count <> 0 "
            "OR final_plan_ordinal IS NOT NULL OR diversity_warning IS NOT NULL"
            ")"
        )
    )
    if has_diversity_artifacts:
        raise RuntimeError("cannot downgrade while visual-diversity artifacts exist")

    op.drop_index("ix_image_similarity_attempts_hash", table_name="image_similarity_attempts")
    op.drop_table("image_similarity_attempts")
    op.drop_constraint(
        "fk_image_artifact_references_plan_reservation_id",
        "image_artifact_references",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_image_visual_plan_reservations_history",
        table_name="image_visual_plan_reservations",
    )
    op.drop_table("image_visual_plan_reservations")

    op.drop_constraint(
        "uq_image_artifact_references_attempt_ordinal",
        "image_artifact_references",
        type_="unique",
    )
    op.drop_constraint(
        "ck_image_artifact_references_attempt_ordinal",
        "image_artifact_references",
        type_="check",
    )
    op.drop_column("image_artifact_references", "plan_reservation_id")
    op.drop_column("image_artifact_references", "attempt_ordinal")
    op.create_unique_constraint(
        "uq_image_artifact_references_artifact_ordinal",
        "image_artifact_references",
        ["image_artifact_id", "ordinal"],
    )

    for constraint_name in (
        "ck_image_artifacts_similarity_snapshot_object",
        "ck_image_artifacts_diversity_warning",
        "ck_image_artifacts_perceptual_hash",
        "ck_image_artifacts_plan_ordinals",
        "ck_image_artifacts_diversity_retry",
    ):
        op.drop_constraint(constraint_name, "image_artifacts", type_="check")
    for column_name in (
        "similarity_snapshot",
        "diversity_warning",
        "perceptual_hash",
        "final_plan_ordinal",
        "active_plan_ordinal",
        "diversity_retry_count",
        "similarity_policy_version",
        "perceptual_hash_version",
        "diversity_policy_version",
    ):
        op.drop_column("image_artifacts", column_name)
