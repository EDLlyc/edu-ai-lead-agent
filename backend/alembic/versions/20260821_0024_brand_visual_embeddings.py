"""Add an isolated multimodal visual-asset embedding index."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "20260821_0024"
down_revision: str | None = "20260820_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "brand_visual_index_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("derivation_key", sa.String(length=64), nullable=False),
        sa.Column("asset_id", sa.String(length=64), nullable=False),
        sa.Column("asset_checksum", sa.String(length=64), nullable=False),
        sa.Column("catalog_version", sa.String(length=80), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("input_policy_version", sa.String(length=80), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("lease_owner", sa.String(length=200), nullable=True),
        sa.Column("lease_token", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("input_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("image_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("latency_ms", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_brand_visual_index_jobs"),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_brand_visual_index_jobs_status",
        ),
        sa.CheckConstraint("dimensions = 2048", name="ck_brand_visual_index_jobs_dimensions"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_brand_visual_index_jobs_attempt_count"),
        sa.CheckConstraint(
            "input_tokens >= 0 AND image_tokens >= 0 AND latency_ms >= 0",
            name="ck_brand_visual_index_jobs_metrics",
        ),
        sa.UniqueConstraint("derivation_key", name="uq_brand_visual_index_jobs_derivation"),
    )
    op.create_index(
        "ix_brand_visual_index_jobs_claim",
        "brand_visual_index_jobs",
        ["status", "lease_expires_at", "created_at"],
    )
    op.create_index(
        "ix_brand_visual_index_jobs_scope",
        "brand_visual_index_jobs",
        ["catalog_version", "provider", "model", "input_policy_version"],
    )

    op.create_table(
        "brand_visual_asset_embeddings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("derivation_key", sa.String(length=64), nullable=False),
        sa.Column("asset_id", sa.String(length=64), nullable=False),
        sa.Column("asset_checksum", sa.String(length=64), nullable=False),
        sa.Column("catalog_version", sa.String(length=80), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("input_policy_version", sa.String(length=80), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("vector", Vector(2048), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_brand_visual_asset_embeddings"),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["brand_visual_index_jobs.id"],
            name="fk_brand_visual_asset_embeddings_job_id",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("dimensions = 2048", name="ck_brand_visual_embeddings_dimensions"),
        sa.UniqueConstraint("job_id", name="uq_brand_visual_asset_embeddings_job"),
        sa.UniqueConstraint("derivation_key", name="uq_brand_visual_asset_embeddings_derivation"),
    )
    op.create_index(
        "ix_brand_visual_asset_embeddings_scope",
        "brand_visual_asset_embeddings",
        ["catalog_version", "provider", "model", "input_policy_version"],
    )
    op.create_index(
        "ix_brand_visual_asset_embeddings_asset",
        "brand_visual_asset_embeddings",
        ["asset_id", "asset_checksum"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_brand_visual_asset_embeddings_asset",
        table_name="brand_visual_asset_embeddings",
    )
    op.drop_index(
        "ix_brand_visual_asset_embeddings_scope",
        table_name="brand_visual_asset_embeddings",
    )
    op.drop_table("brand_visual_asset_embeddings")
    op.drop_index("ix_brand_visual_index_jobs_scope", table_name="brand_visual_index_jobs")
    op.drop_index("ix_brand_visual_index_jobs_claim", table_name="brand_visual_index_jobs")
    op.drop_table("brand_visual_index_jobs")
