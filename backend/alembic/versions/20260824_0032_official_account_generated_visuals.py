"""Add immutable generated local body-visual intents for official-account runs."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260824_0032"
down_revision: str | None = "20260824_0031"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "official_account_generated_visuals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("article_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("render_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("section_index", sa.Integer(), nullable=False),
        sa.Column("reference_asset_ref", sa.String(16), nullable=False),
        sa.Column("reference_catalog_version", sa.String(80), nullable=False),
        sa.Column("reference_source_checksum", sa.String(64), nullable=False),
        sa.Column("reference_publication_checksum", sa.String(64), nullable=False),
        sa.Column("selection_method", sa.String(40), nullable=False),
        sa.Column("similarity_band", sa.String(20), nullable=True),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("plan_version", sa.String(80), nullable=False),
        sa.Column("prompt_version", sa.String(80), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("media_type", sa.String(120), nullable=True),
        sa.Column("byte_size", sa.BigInteger(), nullable=True),
        sa.Column("sha256", sa.String(64), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_official_account_generated_visuals"),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["official_account_article_runs.id"],
            name="fk_official_account_generated_visuals_run_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["article_version_id"],
            ["official_account_article_versions.id"],
            name="fk_official_account_generated_visuals_article_version_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["render_version_id"],
            ["official_account_render_versions.id"],
            name="fk_official_account_generated_visuals_render_version_id",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("ordinal BETWEEN 0 AND 4", name="ck_official_generated_visuals_ordinal"),
        sa.CheckConstraint(
            "section_index BETWEEN 0 AND 6", name="ck_official_generated_visuals_section"
        ),
        sa.CheckConstraint(
            "reference_asset_ref ~ '^[0-9a-f]{16}$'",
            name="ck_official_generated_visuals_reference_ref",
        ),
        sa.CheckConstraint(
            "reference_source_checksum ~ '^[0-9a-f]{64}$' AND "
            "reference_publication_checksum ~ '^[0-9a-f]{64}$'",
            name="ck_official_generated_visuals_reference_checksums",
        ),
        sa.CheckConstraint(
            "selection_method IN ('deterministic_tag', 'multimodal_embedding')",
            name="ck_official_generated_visuals_selection_method",
        ),
        sa.CheckConstraint(
            "(selection_method = 'multimodal_embedding' AND "
            "similarity_band IN ('very_high', 'high', 'medium', 'low')) OR "
            "(selection_method = 'deterministic_tag' AND similarity_band IS NULL)",
            name="ck_official_generated_visuals_similarity_shape",
        ),
        sa.CheckConstraint(
            "provider IN ('fake', 'toapis', 'comfly')",
            name="ck_official_generated_visuals_provider",
        ),
        sa.CheckConstraint(
            "status IN ('generating', 'ready', 'failed', 'result_unknown')",
            name="ck_official_generated_visuals_status",
        ),
        sa.CheckConstraint(
            "(status = 'ready' AND media_type IN ('image/png', 'image/jpeg', 'image/webp') "
            "AND byte_size > 0 AND sha256 ~ '^[0-9a-f]{64}$' AND width BETWEEN 1 AND 8192 "
            "AND height BETWEEN 1 AND 8192 AND width::bigint * height::bigint <= 32000000 "
            "AND error_code IS NULL AND completed_at IS NOT NULL) OR "
            "(status = 'generating' AND media_type IS NULL AND byte_size IS NULL "
            "AND sha256 IS NULL AND width IS NULL AND height IS NULL AND error_code IS NULL "
            "AND completed_at IS NULL) OR "
            "(status IN ('failed', 'result_unknown') AND media_type IS NULL "
            "AND byte_size IS NULL AND sha256 IS NULL AND width IS NULL AND height IS NULL "
            "AND error_code IS NOT NULL AND completed_at IS NOT NULL)",
            name="ck_official_generated_visuals_result_shape",
        ),
        sa.UniqueConstraint(
            "render_version_id", "ordinal", name="uq_official_generated_visuals_render_ordinal"
        ),
        sa.UniqueConstraint("request_fingerprint", name="uq_official_generated_visuals_request"),
    )
    op.create_index(
        "ix_official_generated_visuals_run",
        "official_account_generated_visuals",
        ["run_id", "ordinal"],
    )
    op.add_column(
        "official_account_local_media",
        sa.Column("generated_visual_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_official_account_local_media_generated_visual_id",
        "official_account_local_media",
        "official_account_generated_visuals",
        ["generated_visual_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        "ck_official_account_local_media_source_xor",
        "official_account_local_media",
        type_="check",
    )
    op.create_check_constraint(
        "ck_official_account_local_media_source_xor",
        "official_account_local_media",
        "(source_image_artifact_id IS NOT NULL AND fixture_id IS NULL "
        "AND generated_visual_id IS NULL) OR "
        "(source_image_artifact_id IS NULL AND fixture_id IS NOT NULL "
        "AND generated_visual_id IS NULL) OR "
        "(source_image_artifact_id IS NULL AND fixture_id IS NULL "
        "AND generated_visual_id IS NOT NULL)",
    )
    op.drop_constraint(
        "ck_official_account_article_runs_stage",
        "official_account_article_runs",
        type_="check",
    )
    op.create_check_constraint(
        "ck_official_account_article_runs_stage",
        "official_account_article_runs",
        "current_stage IN ('queued', 'generating', 'validating', 'auditing', 'rendering', "
        "'generating_body_visuals', 'staging_body_media', 'staging_cover', "
        "'creating_local_draft', 'ready', 'review_required', 'failed', 'result_unknown')",
    )
    op.drop_constraint(
        "ck_official_account_article_attempts_capability",
        "official_account_article_attempts",
        type_="check",
    )
    op.create_check_constraint(
        "ck_official_account_article_attempts_capability",
        "official_account_article_attempts",
        "capability IN ('generation', 'audit', 'visual_generation', 'workflow')",
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM official_account_generated_visuals) "
            "THEN RAISE EXCEPTION 'cannot downgrade official-account generated visual artifacts'; "
            "END IF; END $$"
        )
    )
    op.drop_constraint(
        "ck_official_account_article_attempts_capability",
        "official_account_article_attempts",
        type_="check",
    )
    op.create_check_constraint(
        "ck_official_account_article_attempts_capability",
        "official_account_article_attempts",
        "capability IN ('generation', 'audit', 'workflow')",
    )
    op.drop_constraint(
        "ck_official_account_article_runs_stage",
        "official_account_article_runs",
        type_="check",
    )
    op.create_check_constraint(
        "ck_official_account_article_runs_stage",
        "official_account_article_runs",
        "current_stage IN ('queued', 'generating', 'validating', 'auditing', 'rendering', "
        "'staging_body_media', 'staging_cover', 'creating_local_draft', 'ready', "
        "'review_required', 'failed', 'result_unknown')",
    )
    op.drop_constraint(
        "ck_official_account_local_media_source_xor",
        "official_account_local_media",
        type_="check",
    )
    op.create_check_constraint(
        "ck_official_account_local_media_source_xor",
        "official_account_local_media",
        "(source_image_artifact_id IS NOT NULL AND fixture_id IS NULL) OR "
        "(source_image_artifact_id IS NULL AND fixture_id IS NOT NULL)",
    )
    op.drop_constraint(
        "fk_official_account_local_media_generated_visual_id",
        "official_account_local_media",
        type_="foreignkey",
    )
    op.drop_column("official_account_local_media", "generated_visual_id")
    op.drop_index(
        "ix_official_generated_visuals_run", table_name="official_account_generated_visuals"
    )
    op.drop_table("official_account_generated_visuals")
