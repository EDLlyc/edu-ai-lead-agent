"""Add selected-news source images and local context-media lineage."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260825_0036"
down_revision: str | None = "20260824_0035"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("ck_source_snapshots_kind", "source_snapshots", type_="check")
    op.create_check_constraint(
        "ck_source_snapshots_kind",
        "source_snapshots",
        "kind IN ('list', 'detail', 'image')",
    )
    op.create_table(
        "source_article_images",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("candidate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("detail_snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("image_snapshot_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("discovery_fingerprint", sa.String(64), nullable=False),
        sa.Column("source_page_url", sa.Text(), nullable=False),
        sa.Column("image_url", sa.Text(), nullable=False),
        sa.Column("final_image_url", sa.Text(), nullable=True),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("alt_text", sa.String(200), nullable=True),
        sa.Column("caption", sa.String(300), nullable=True),
        sa.Column("credit", sa.String(200), nullable=True),
        sa.Column("extraction_version", sa.String(80), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("failure_code", sa.String(80), nullable=True),
        sa.Column(
            "rights_status",
            sa.String(50),
            server_default=sa.text("'publish_permission_unverified'"),
            nullable=False,
        ),
        sa.Column("media_type", sa.String(120), nullable=True),
        sa.Column("byte_size", sa.BigInteger(), nullable=True),
        sa.Column("sha256", sa.String(64), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_source_article_images"),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["evidence_candidates.id"],
            name="fk_source_article_images_candidate_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["detail_snapshot_id"],
            ["source_snapshots.id"],
            name="fk_source_article_images_detail_snapshot_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_version_id"],
            ["source_versions.id"],
            name="fk_source_article_images_source_version_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["image_snapshot_id"],
            ["source_snapshots.id"],
            name="fk_source_article_images_image_snapshot_id",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("ordinal BETWEEN 0 AND 4", name="ck_source_article_images_ordinal"),
        sa.CheckConstraint("role IN ('lead', 'body')", name="ck_source_article_images_role"),
        sa.CheckConstraint(
            "status IN ('discovered', 'ready', 'failed', 'rejected')",
            name="ck_source_article_images_status",
        ),
        sa.CheckConstraint(
            "rights_status = 'publish_permission_unverified'",
            name="ck_source_article_images_rights",
        ),
        sa.CheckConstraint(
            "(status = 'ready' AND image_snapshot_id IS NOT NULL AND final_image_url IS NOT NULL "
            "AND media_type IN ('image/jpeg', 'image/png', 'image/webp') AND byte_size > 0 "
            "AND sha256 ~ '^[0-9a-f]{64}$' AND width BETWEEN 320 AND 8192 "
            "AND height BETWEEN 180 AND 8192 AND width::bigint * height::bigint <= 40000000 "
            "AND failure_code IS NULL AND retrieved_at IS NOT NULL) OR "
            "(status = 'discovered' AND image_snapshot_id IS NULL AND final_image_url IS NULL "
            "AND media_type IS NULL AND byte_size IS NULL AND sha256 IS NULL "
            "AND width IS NULL AND height IS NULL AND failure_code IS NULL "
            "AND retrieved_at IS NULL) OR "
            "(status IN ('failed', 'rejected') AND image_snapshot_id IS NULL "
            "AND final_image_url IS NULL AND retrieved_at IS NULL "
            "AND media_type IS NULL AND byte_size IS NULL AND sha256 IS NULL "
            "AND width IS NULL AND height IS NULL AND failure_code IS NOT NULL)",
            name="ck_source_article_images_result_shape",
        ),
        sa.UniqueConstraint(
            "detail_snapshot_id", "ordinal", name="uq_source_article_images_detail_ordinal"
        ),
        sa.UniqueConstraint(
            "discovery_fingerprint", name="uq_source_article_images_discovery_fingerprint"
        ),
    )
    op.create_index(
        "ix_source_article_images_candidate",
        "source_article_images",
        ["candidate_id", "status", "ordinal"],
    )
    op.create_index(
        "ix_source_article_images_detail",
        "source_article_images",
        ["detail_snapshot_id", "status", "ordinal"],
    )

    op.create_table(
        "material_package_source_images",
        sa.Column("package_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("source_article_image_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("selection_reason", sa.String(80), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("package_id", "ordinal", name="pk_material_package_source_images"),
        sa.ForeignKeyConstraint(
            ["package_id"],
            ["material_packages.id"],
            name="fk_material_package_source_images_package_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_article_image_id"],
            ["source_article_images.id"],
            name="fk_material_package_source_images_source_image_id",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "ordinal BETWEEN 0 AND 1", name="ck_material_package_source_images_ordinal"
        ),
        sa.CheckConstraint(
            "selection_reason = 'evidence_snapshot_lineage_v1'",
            name="ck_material_package_source_images_reason",
        ),
        sa.UniqueConstraint(
            "package_id",
            "source_article_image_id",
            name="uq_material_package_source_images_identity",
        ),
    )
    op.create_index(
        "ix_material_package_source_images_source",
        "material_package_source_images",
        ["source_article_image_id"],
    )

    op.drop_constraint(
        "ck_official_account_article_versions_version",
        "official_account_article_versions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_official_account_article_versions_version",
        "official_account_article_versions",
        "version IN (1, 2, 3, 4, 5, 6)",
    )
    op.create_unique_constraint(
        "uq_official_account_article_runs_id_material",
        "official_account_article_runs",
        ["id", "material_package_id"],
    )
    op.create_table(
        "official_account_article_context_images",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("material_package_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("article_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_article_image_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("section_index", sa.Integer(), nullable=False),
        sa.Column("selection_version", sa.String(80), nullable=False),
        sa.Column("alt_text", sa.String(200), nullable=False),
        sa.Column("caption", sa.String(300), nullable=True),
        sa.Column("credit", sa.String(200), nullable=True),
        sa.Column("source_page_url", sa.Text(), nullable=False),
        sa.Column("rights_status", sa.String(50), nullable=False),
        sa.Column(
            "context_only_not_evidence",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_official_account_article_context_images"),
        sa.ForeignKeyConstraint(
            ["article_version_id", "run_id"],
            ["official_account_article_versions.id", "official_account_article_versions.run_id"],
            name="fk_official_context_images_article_run",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "material_package_id"],
            [
                "official_account_article_runs.id",
                "official_account_article_runs.material_package_id",
            ],
            name="fk_official_context_images_run_material",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["material_package_id", "source_article_image_id"],
            [
                "material_package_source_images.package_id",
                "material_package_source_images.source_article_image_id",
            ],
            name="fk_official_context_images_package_source",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("ordinal BETWEEN 0 AND 1", name="ck_official_context_images_ordinal"),
        sa.CheckConstraint(
            "section_index BETWEEN 0 AND 6", name="ck_official_context_images_section"
        ),
        sa.CheckConstraint(
            "selection_version = 'official-account-news-context-selection-v1'",
            name="ck_official_context_images_selection_version",
        ),
        sa.CheckConstraint(
            "rights_status = 'publish_permission_unverified' AND context_only_not_evidence = true",
            name="ck_official_context_images_rights_boundary",
        ),
        sa.CheckConstraint("sha256 ~ '^[0-9a-f]{64}$'", name="ck_official_context_images_sha256"),
        sa.UniqueConstraint(
            "article_version_id", "ordinal", name="uq_official_context_images_article_ordinal"
        ),
        sa.UniqueConstraint(
            "article_version_id",
            "source_article_image_id",
            name="uq_official_context_images_article_source",
        ),
    )
    op.create_index(
        "ix_official_context_images_run",
        "official_account_article_context_images",
        ["run_id", "ordinal"],
    )

    op.add_column(
        "official_account_local_media",
        sa.Column("source_article_image_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_official_account_local_media_source_article_image_id",
        "official_account_local_media",
        "source_article_images",
        ["source_article_image_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        "ck_official_account_local_media_role", "official_account_local_media", type_="check"
    )
    op.drop_constraint(
        "ck_official_account_local_media_ordinal", "official_account_local_media", type_="check"
    )
    op.drop_constraint(
        "ck_official_account_local_media_source_xor", "official_account_local_media", type_="check"
    )
    op.create_check_constraint(
        "ck_official_account_local_media_role",
        "official_account_local_media",
        "role IN ('body', 'cover', 'context')",
    )
    op.create_check_constraint(
        "ck_official_account_local_media_ordinal",
        "official_account_local_media",
        "(role = 'body' AND ordinal BETWEEN 0 AND 4) OR "
        "(role = 'cover' AND ordinal = 0) OR (role = 'context' AND ordinal BETWEEN 0 AND 1)",
    )
    op.create_check_constraint(
        "ck_official_account_local_media_source_xor",
        "official_account_local_media",
        "(source_image_artifact_id IS NOT NULL AND fixture_id IS NULL "
        "AND generated_visual_id IS NULL AND source_article_image_id IS NULL) OR "
        "(source_image_artifact_id IS NULL AND fixture_id IS NOT NULL "
        "AND generated_visual_id IS NULL AND source_article_image_id IS NULL) OR "
        "(source_image_artifact_id IS NULL AND fixture_id IS NULL "
        "AND generated_visual_id IS NOT NULL AND source_article_image_id IS NULL) OR "
        "(source_image_artifact_id IS NULL AND fixture_id IS NULL "
        "AND generated_visual_id IS NULL AND source_article_image_id IS NOT NULL "
        "AND role = 'context')",
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DO $$ BEGIN IF EXISTS (SELECT 1 FROM source_article_images) "
            "OR EXISTS (SELECT 1 FROM material_package_source_images) "
            "OR EXISTS (SELECT 1 FROM official_account_article_context_images) "
            "OR EXISTS (SELECT 1 FROM official_account_local_media "
            "WHERE source_article_image_id IS NOT NULL) "
            "OR EXISTS (SELECT 1 FROM official_account_article_versions WHERE version = 6) "
            "THEN RAISE EXCEPTION 'cannot downgrade selected-news source-image artifacts'; "
            "END IF; END $$"
        )
    )
    op.drop_constraint(
        "ck_official_account_local_media_source_xor", "official_account_local_media", type_="check"
    )
    op.drop_constraint(
        "ck_official_account_local_media_ordinal", "official_account_local_media", type_="check"
    )
    op.drop_constraint(
        "ck_official_account_local_media_role", "official_account_local_media", type_="check"
    )
    op.create_check_constraint(
        "ck_official_account_local_media_role",
        "official_account_local_media",
        "role IN ('body', 'cover')",
    )
    op.create_check_constraint(
        "ck_official_account_local_media_ordinal",
        "official_account_local_media",
        "(role = 'body' AND ordinal BETWEEN 0 AND 4) OR (role = 'cover' AND ordinal = 0)",
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
        "fk_official_account_local_media_source_article_image_id",
        "official_account_local_media",
        type_="foreignkey",
    )
    op.drop_column("official_account_local_media", "source_article_image_id")
    op.drop_index(
        "ix_official_context_images_run", table_name="official_account_article_context_images"
    )
    op.drop_table("official_account_article_context_images")
    op.drop_constraint(
        "uq_official_account_article_runs_id_material",
        "official_account_article_runs",
        type_="unique",
    )
    op.drop_constraint(
        "ck_official_account_article_versions_version",
        "official_account_article_versions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_official_account_article_versions_version",
        "official_account_article_versions",
        "version IN (1, 2, 3, 4, 5)",
    )
    op.drop_index(
        "ix_material_package_source_images_source", table_name="material_package_source_images"
    )
    op.drop_table("material_package_source_images")
    op.drop_index("ix_source_article_images_detail", table_name="source_article_images")
    op.drop_index("ix_source_article_images_candidate", table_name="source_article_images")
    op.drop_table("source_article_images")
    op.drop_constraint("ck_source_snapshots_kind", "source_snapshots", type_="check")
    op.create_check_constraint(
        "ck_source_snapshots_kind", "source_snapshots", "kind IN ('list', 'detail')"
    )
