"""Add private versioned brand knowledge ingestion and retrieval.

Revision ID: 20260730_0007
Revises: 20260730_0006
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "20260730_0007"
down_revision: str | None = "20260730_0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "brand_documents",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("brand_slug", sa.String(length=80), nullable=False),
        sa.Column("document_key", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("document_kind", sa.String(length=40), nullable=False),
        sa.Column("audience", sa.String(length=40), nullable=False),
        sa.Column("language", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("active_version_id", postgresql.UUID(as_uuid=True), nullable=True),
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
        sa.CheckConstraint("brand_slug = 'sai-xiansheng'", name="ck_brand_documents_single_brand"),
        sa.CheckConstraint(
            "document_kind IN ('positioning', 'tone', 'approved_example', "
            "'prohibited_language', 'safety_rule', 'visual_guidance', 'other')",
            name="ck_brand_documents_kind",
        ),
        sa.CheckConstraint(
            "audience IN ('parents', 'internal')", name="ck_brand_documents_audience"
        ),
        sa.CheckConstraint("language = 'zh-CN'", name="ck_brand_documents_language"),
        sa.CheckConstraint("status IN ('active', 'inactive')", name="ck_brand_documents_status"),
        sa.PrimaryKeyConstraint("id", name="pk_brand_documents"),
        sa.UniqueConstraint("document_key", name="uq_brand_documents_document_key"),
    )
    op.create_index(
        "ix_brand_documents_scope",
        "brand_documents",
        ["brand_slug", "audience", "document_kind", "status"],
        unique=False,
    )
    op.create_table(
        "brand_document_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("safe_filename", sa.String(length=180), nullable=False),
        sa.Column("media_type", sa.String(length=120), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("bucket", sa.String(length=120), nullable=False),
        sa.Column("object_key", sa.String(length=300), nullable=False),
        sa.Column("metadata_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("parser_version", sa.String(length=80), nullable=False),
        sa.Column("chunk_version", sa.String(length=80), nullable=False),
        sa.Column("embedding_input_version", sa.String(length=80), nullable=False),
        sa.Column("embedding_provider", sa.String(length=40), nullable=False),
        sa.Column("embedding_model", sa.String(length=120), nullable=False),
        sa.Column("embedding_dimensions", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("valid_from", sa.Date(), nullable=True),
        sa.Column("valid_until", sa.Date(), nullable=True),
        sa.Column("tone_tags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("safety_tags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("visual_tags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("character_count", sa.Integer(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("version >= 1", name="ck_brand_document_versions_version"),
        sa.CheckConstraint("byte_size > 0", name="ck_brand_document_versions_byte_size"),
        sa.CheckConstraint(
            "embedding_dimensions = 2048", name="ck_brand_document_versions_dimensions"
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'processing', 'ready', 'failed')",
            name="ck_brand_document_versions_status",
        ),
        sa.CheckConstraint(
            "valid_until IS NULL OR valid_from IS NULL OR valid_until >= valid_from",
            name="ck_brand_document_versions_validity",
        ),
        sa.CheckConstraint("jsonb_typeof(tone_tags) = 'array'", name="ck_brand_versions_tone_tags"),
        sa.CheckConstraint(
            "jsonb_typeof(safety_tags) = 'array'", name="ck_brand_versions_safety_tags"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(visual_tags) = 'array'", name="ck_brand_versions_visual_tags"
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["brand_documents.id"],
            name="fk_brand_document_versions_document_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_brand_document_versions"),
        sa.UniqueConstraint(
            "document_id", "version", name="uq_brand_document_versions_document_version"
        ),
        sa.UniqueConstraint("id", "document_id", name="uq_brand_document_versions_id_document"),
        sa.UniqueConstraint(
            "document_id",
            "sha256",
            "metadata_fingerprint",
            "parser_version",
            "chunk_version",
            "embedding_input_version",
            "embedding_provider",
            "embedding_model",
            name="uq_brand_document_versions_derivation",
        ),
    )
    op.create_index(
        "uq_brand_document_versions_one_active",
        "brand_document_versions",
        ["document_id"],
        unique=True,
        postgresql_where=sa.text("active = true"),
    )
    op.create_index(
        "ix_brand_document_versions_status",
        "brand_document_versions",
        ["status", "created_at"],
        unique=False,
    )
    op.create_foreign_key(
        "fk_brand_documents_active_version_document",
        "brand_documents",
        "brand_document_versions",
        ["active_version_id", "id"],
        ["id", "document_id"],
        ondelete="RESTRICT",
    )
    op.create_table(
        "brand_ingestion_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("lease_owner", sa.String(length=200), nullable=True),
        sa.Column("lease_token", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'retry_scheduled', "
            "'succeeded', 'failed', 'cancelled')",
            name="ck_brand_ingestion_jobs_status",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_brand_ingestion_jobs_attempt_count"),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["brand_document_versions.id"],
            name="fk_brand_ingestion_jobs_version_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_brand_ingestion_jobs"),
        sa.UniqueConstraint("version_id", name="uq_brand_ingestion_jobs_version_id"),
    )
    op.create_index(
        "ix_brand_ingestion_jobs_claim",
        "brand_ingestion_jobs",
        ["status", "available_at", "lease_expires_at"],
        unique=False,
    )
    op.create_table(
        "brand_ingestion_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column(
            "safe_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'retry_scheduled', 'succeeded', 'failed')",
            name="ck_brand_ingestion_attempts_status",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["brand_ingestion_jobs.id"],
            name="fk_brand_ingestion_attempts_job_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_brand_ingestion_attempts"),
        sa.UniqueConstraint(
            "job_id", "attempt_number", name="uq_brand_ingestion_attempts_job_number"
        ),
    )
    op.create_index(
        "ix_brand_ingestion_attempts_job_id",
        "brand_ingestion_attempts",
        ["job_id"],
        unique=False,
    )
    op.create_table(
        "brand_chunks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("chunk_key", sa.String(length=64), nullable=False),
        sa.Column("text_hash", sa.String(length=64), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('simple', text)", persisted=True),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("ordinal >= 0", name="ck_brand_chunks_ordinal"),
        sa.CheckConstraint(
            "char_start >= 0 AND char_end > char_start", name="ck_brand_chunks_offsets"
        ),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["brand_document_versions.id"],
            name="fk_brand_chunks_version_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_brand_chunks"),
        sa.UniqueConstraint("chunk_key", name="uq_brand_chunks_chunk_key"),
        sa.UniqueConstraint("version_id", "ordinal", name="uq_brand_chunks_version_ordinal"),
    )
    op.create_index(
        "ix_brand_chunks_search_vector",
        "brand_chunks",
        ["search_vector"],
        unique=False,
        postgresql_using="gin",
    )
    op.create_index("ix_brand_chunks_version_id", "brand_chunks", ["version_id"], unique=False)
    op.create_table(
        "brand_chunk_embeddings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("purpose", sa.String(length=40), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("dimensions", sa.Integer(), nullable=False),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("input_version", sa.String(length=80), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("provider_request_id", sa.String(length=200), nullable=True),
        sa.Column("vector", Vector(dim=2048), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("purpose = 'brand_retrieval'", name="ck_brand_chunk_embeddings_purpose"),
        sa.CheckConstraint("dimensions = 2048", name="ck_brand_chunk_embeddings_dimensions"),
        sa.ForeignKeyConstraint(
            ["chunk_id"],
            ["brand_chunks.id"],
            name="fk_brand_chunk_embeddings_chunk_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_brand_chunk_embeddings"),
        sa.UniqueConstraint(
            "chunk_id",
            "purpose",
            "provider",
            "model",
            "input_hash",
            "input_version",
            name="uq_brand_chunk_embeddings_derivation",
        ),
        sa.UniqueConstraint("request_fingerprint", name="uq_brand_chunk_embeddings_request"),
    )
    op.create_index(
        "ix_brand_chunk_embeddings_chunk_id",
        "brand_chunk_embeddings",
        ["chunk_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_brand_chunk_embeddings_chunk_id", table_name="brand_chunk_embeddings")
    op.drop_table("brand_chunk_embeddings")
    op.drop_index("ix_brand_chunks_version_id", table_name="brand_chunks")
    op.drop_index("ix_brand_chunks_search_vector", table_name="brand_chunks")
    op.drop_table("brand_chunks")
    op.drop_index("ix_brand_ingestion_attempts_job_id", table_name="brand_ingestion_attempts")
    op.drop_table("brand_ingestion_attempts")
    op.drop_index("ix_brand_ingestion_jobs_claim", table_name="brand_ingestion_jobs")
    op.drop_table("brand_ingestion_jobs")
    op.drop_constraint(
        "fk_brand_documents_active_version_document", "brand_documents", type_="foreignkey"
    )
    op.drop_index("ix_brand_document_versions_status", table_name="brand_document_versions")
    op.drop_index("uq_brand_document_versions_one_active", table_name="brand_document_versions")
    op.drop_table("brand_document_versions")
    op.drop_index("ix_brand_documents_scope", table_name="brand_documents")
    op.drop_table("brand_documents")
