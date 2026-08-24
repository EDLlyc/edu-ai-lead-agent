"""Add the no-auth intranet IP digital asset hub."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "20260824_0031"
down_revision: str | None = "20260823_0030"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ip_assets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_ref", sa.String(24), nullable=False),
        sa.Column("blob_sha256", sa.String(64), nullable=False),
        sa.Column("perceptual_hash", sa.String(16), nullable=False),
        sa.Column("safe_original_filename", sa.String(200), nullable=False),
        sa.Column("media_type", sa.String(40), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("has_alpha", sa.Boolean(), nullable=False),
        sa.Column("orientation", sa.String(20), nullable=False),
        sa.Column("bucket", sa.String(120), nullable=False),
        sa.Column("object_key", sa.String(300), nullable=False),
        sa.Column("naming_key", sa.String(64), nullable=False),
        sa.Column("canonical_name", sa.String(260), nullable=False),
        sa.Column("canonical_slug", sa.String(260), nullable=False),
        sa.Column("name_version", sa.Integer(), nullable=False),
        sa.Column("character", sa.String(30), nullable=False),
        sa.Column("asset_type", sa.String(40), nullable=False),
        sa.Column("source_kind", sa.String(20), nullable=False),
        sa.Column("department", sa.String(80), server_default=sa.text("''"), nullable=False),
        sa.Column("contributor", sa.String(80), server_default=sa.text("''"), nullable=False),
        sa.Column("emotion", sa.String(40), server_default=sa.text("''"), nullable=False),
        sa.Column("action", sa.String(40), server_default=sa.text("''"), nullable=False),
        sa.Column("scene", sa.String(60), server_default=sa.text("''"), nullable=False),
        sa.Column("intended_use", sa.String(60), server_default=sa.text("''"), nullable=False),
        sa.Column("style", sa.String(40), server_default=sa.text("''"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("semantic_status", sa.String(20), nullable=False),
        sa.Column("failure_code", sa.String(80), nullable=True),
        sa.Column("parent_asset_id", postgresql.UUID(as_uuid=True), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name="pk_ip_assets"),
        sa.ForeignKeyConstraint(
            ["parent_asset_id"],
            ["ip_assets.id"],
            name="fk_ip_assets_parent_asset_id",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("asset_ref ~ '^ipa_[a-f0-9]{20}$'", name="ck_ip_assets_ref"),
        sa.CheckConstraint("blob_sha256 ~ '^[0-9a-f]{64}$'", name="ck_ip_assets_sha256"),
        sa.CheckConstraint("perceptual_hash ~ '^[0-9a-f]{16}$'", name="ck_ip_assets_phash"),
        sa.CheckConstraint("byte_size BETWEEN 1 AND 26214400", name="ck_ip_assets_byte_size"),
        sa.CheckConstraint(
            "width BETWEEN 1 AND 8192 AND height BETWEEN 1 AND 8192 "
            "AND width::bigint * height::bigint <= 32000000",
            name="ck_ip_assets_dimensions",
        ),
        sa.CheckConstraint(
            "media_type IN ('image/png', 'image/jpeg', 'image/webp')",
            name="ck_ip_assets_media_type",
        ),
        sa.CheckConstraint(
            "orientation IN ('square', 'portrait', 'landscape')", name="ck_ip_assets_orientation"
        ),
        sa.CheckConstraint(
            "character IN ('sai_xiansheng', 'xiao_sai', 'duo', 'other')",
            name="ck_ip_assets_character",
        ),
        sa.CheckConstraint(
            "asset_type IN ('identity_reference', 'portrait_avatar', 'full_body_action', "
            "'expression', 'meme_sticker', 'transparent_cutout', 'scene_illustration', "
            "'poster_element', 'other')",
            name="ck_ip_assets_type",
        ),
        sa.CheckConstraint(
            "source_kind IN ('uploaded', 'generated', 'seed_import')", name="ck_ip_assets_source"
        ),
        sa.CheckConstraint(
            "status IN ('processing', 'ready', 'failed')", name="ck_ip_assets_status"
        ),
        sa.CheckConstraint(
            "semantic_status IN ('queued', 'running', 'ready', 'unavailable', 'failed')",
            name="ck_ip_assets_semantic_status",
        ),
        sa.UniqueConstraint("asset_ref", name="uq_ip_assets_ref"),
        sa.UniqueConstraint("blob_sha256", name="uq_ip_assets_blob_sha256"),
        sa.UniqueConstraint("naming_key", "name_version", name="uq_ip_assets_name_version"),
    )
    op.create_index("ix_ip_assets_gallery", "ip_assets", ["created_at", "id"])
    op.create_index(
        "ix_ip_assets_filters",
        "ip_assets",
        ["character", "asset_type", "source_kind", "orientation"],
    )
    op.create_index("ix_ip_assets_department", "ip_assets", ["department"])
    op.create_index("ix_ip_assets_phash", "ip_assets", ["perceptual_hash"])

    op.create_table(
        "ip_asset_tags",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("dimension", sa.String(30), nullable=False),
        sa.Column("value", sa.String(80), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ip_asset_tags"),
        sa.ForeignKeyConstraint(
            ["asset_id"], ["ip_assets.id"], name="fk_ip_asset_tags_asset_id", ondelete="CASCADE"
        ),
        sa.CheckConstraint(
            "dimension IN ('emotion', 'action', 'scene', 'intended_use', 'style', 'free')",
            name="ck_ip_asset_tags_dimension",
        ),
        sa.UniqueConstraint("asset_id", "dimension", "value", name="uq_ip_asset_tags_value"),
    )
    op.create_index("ix_ip_asset_tags_lookup", "ip_asset_tags", ["dimension", "value", "asset_id"])

    op.create_table(
        "ip_asset_derivatives",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("policy_version", sa.String(80), nullable=False),
        sa.Column("kind", sa.String(30), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("media_type", sa.String(40), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("bucket", sa.String(120), nullable=False),
        sa.Column("object_key", sa.String(300), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ip_asset_derivatives"),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["ip_assets.id"],
            name="fk_ip_asset_derivatives_asset_id",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("kind = 'thumbnail'", name="ck_ip_asset_derivatives_kind"),
        sa.UniqueConstraint("asset_id", "policy_version", "kind", name="uq_ip_asset_derivatives"),
    )

    op.create_table(
        "ip_asset_embedding_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("lease_owner", sa.String(200), nullable=True),
        sa.Column("lease_token", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_ip_asset_embedding_jobs"),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["ip_assets.id"],
            name="fk_ip_asset_embedding_jobs_asset_id",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_ip_asset_embedding_jobs_status",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_ip_asset_embedding_jobs_attempts"),
        sa.UniqueConstraint("asset_id", name="uq_ip_asset_embedding_jobs_asset"),
    )
    op.create_index(
        "ix_ip_asset_embedding_jobs_claim",
        "ip_asset_embedding_jobs",
        ["status", "available_at", "lease_expires_at"],
    )

    op.create_table(
        "ip_asset_embeddings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("embedding_input_sha256", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("input_policy_version", sa.String(80), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("vector", Vector(2048), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ip_asset_embeddings"),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["ip_assets.id"],
            name="fk_ip_asset_embeddings_asset_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["ip_asset_embedding_jobs.id"],
            name="fk_ip_asset_embeddings_job_id",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("dimensions = 2048", name="ck_ip_asset_embeddings_dimensions"),
        sa.UniqueConstraint("job_id", name="uq_ip_asset_embeddings_job"),
        sa.UniqueConstraint(
            "asset_id",
            "provider",
            "model",
            "input_policy_version",
            "source_sha256",
            name="uq_ip_asset_embeddings_identity",
        ),
    )
    op.create_index(
        "ix_ip_asset_embeddings_scope",
        "ip_asset_embeddings",
        ["provider", "model", "input_policy_version"],
    )

    op.create_table(
        "ip_asset_generation_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_ref", sa.String(24), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("prompt", sa.String(2000), nullable=False),
        sa.Column("character", sa.String(30), nullable=False),
        sa.Column("asset_type", sa.String(40), nullable=False),
        sa.Column("department", sa.String(80), server_default=sa.text("''"), nullable=False),
        sa.Column("contributor", sa.String(80), server_default=sa.text("''"), nullable=False),
        sa.Column("ratio", sa.String(20), nullable=False),
        sa.Column("reference_asset_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("lease_owner", sa.String(200), nullable=True),
        sa.Column("lease_token", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("output_asset_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_ip_asset_generation_jobs"),
        sa.ForeignKeyConstraint(
            ["reference_asset_id"],
            ["ip_assets.id"],
            name="fk_ip_asset_generation_jobs_reference",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["output_asset_id"],
            ["ip_assets.id"],
            name="fk_ip_asset_generation_jobs_output",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "job_ref ~ '^ipg_[a-f0-9]{20}$'", name="ck_ip_asset_generation_jobs_ref"
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_ip_asset_generation_jobs_status",
        ),
        sa.CheckConstraint("ratio = '1:1'", name="ck_ip_asset_generation_jobs_ratio"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_ip_asset_generation_jobs_attempts"),
        sa.UniqueConstraint("job_ref", name="uq_ip_asset_generation_jobs_ref"),
        sa.UniqueConstraint("idempotency_key", name="uq_ip_asset_generation_jobs_idempotency"),
        sa.UniqueConstraint("request_fingerprint", name="uq_ip_asset_generation_jobs_fingerprint"),
    )
    op.create_index(
        "ix_ip_asset_generation_jobs_claim",
        "ip_asset_generation_jobs",
        ["status", "available_at", "lease_expires_at"],
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DO $$ BEGIN IF EXISTS (SELECT 1 FROM ip_assets) OR "
            "EXISTS (SELECT 1 FROM ip_asset_generation_jobs) THEN "
            "RAISE EXCEPTION 'cannot downgrade IP asset hub while durable data exists'; "
            "END IF; END $$"
        )
    )
    op.drop_index("ix_ip_asset_generation_jobs_claim", table_name="ip_asset_generation_jobs")
    op.drop_table("ip_asset_generation_jobs")
    op.drop_index("ix_ip_asset_embeddings_scope", table_name="ip_asset_embeddings")
    op.drop_table("ip_asset_embeddings")
    op.drop_index("ix_ip_asset_embedding_jobs_claim", table_name="ip_asset_embedding_jobs")
    op.drop_table("ip_asset_embedding_jobs")
    op.drop_table("ip_asset_derivatives")
    op.drop_index("ix_ip_asset_tags_lookup", table_name="ip_asset_tags")
    op.drop_table("ip_asset_tags")
    op.drop_index("ix_ip_assets_phash", table_name="ip_assets")
    op.drop_index("ix_ip_assets_department", table_name="ip_assets")
    op.drop_index("ix_ip_assets_filters", table_name="ip_assets")
    op.drop_index("ix_ip_assets_gallery", table_name="ip_assets")
    op.drop_table("ip_assets")
