"""Create authoritative-source acquisition schema.

Revision ID: 20260728_0001
Revises:
Create Date: 2026-07-28
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260728_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slug", sa.String(length=80), nullable=False),
        sa.Column("display_name", sa.String(length=200), nullable=False),
        sa.Column("organization_type", sa.String(length=80), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("owner", sa.String(length=120), nullable=False),
        sa.Column("active_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sources"),
        sa.UniqueConstraint("slug", name="uq_sources_slug"),
    )
    op.create_index("ix_sources_enabled", "sources", ["enabled"])

    op.create_table(
        "source_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("trust_tier", sa.String(length=1), nullable=False),
        sa.Column("connector_key", sa.String(length=80), nullable=False),
        sa.Column("entry_url", sa.Text(), nullable=False),
        sa.Column("allowed_hosts", postgresql.JSONB(), nullable=False),
        sa.Column("allowed_path_prefixes", postgresql.JSONB(), nullable=False),
        sa.Column("cadence", sa.String(length=40), nullable=False),
        sa.Column("timezone", sa.String(length=80), nullable=False),
        sa.Column("language", sa.String(length=20), nullable=False),
        sa.Column("robots_status", sa.String(length=40), nullable=False),
        sa.Column("terms_reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("rate_limit_seconds", sa.Float(), nullable=False),
        sa.Column("connector_version", sa.String(length=40), nullable=False),
        sa.Column("parser_version", sa.String(length=40), nullable=False),
        sa.Column("config_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("trust_tier IN ('A', 'B')", name="ck_source_versions_trust_tier"),
        sa.CheckConstraint("rate_limit_seconds >= 0", name="ck_source_versions_rate_limit"),
        sa.ForeignKeyConstraint(
            ["source_id"], ["sources.id"], name="fk_source_versions_source_id", ondelete="RESTRICT"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_source_versions"),
        sa.UniqueConstraint("source_id", "version", name="uq_source_versions_source_version"),
        sa.UniqueConstraint(
            "source_id", "config_fingerprint", name="uq_source_versions_source_fingerprint"
        ),
    )
    op.create_index("ix_source_versions_connector_key", "source_versions", ["connector_key"])
    op.create_foreign_key(
        "fk_sources_active_version_id",
        "sources",
        "source_versions",
        ["active_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )

    op.create_table(
        "source_cursors",
        sa.Column("source_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("etag", sa.String(length=500), nullable=True),
        sa.Column("last_modified", sa.String(length=200), nullable=True),
        sa.Column("last_item_id", sa.String(length=500), nullable=True),
        sa.Column("last_published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "cursor_data", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False
        ),
        sa.Column("lock_version", sa.Integer(), server_default=sa.text("1"), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["source_version_id"],
            ["source_versions.id"],
            name="fk_source_cursors_source_version_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("source_version_id", name="pk_source_cursors"),
    )

    op.create_table(
        "acquisition_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trigger", sa.String(length=20), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=True),
        sa.Column("timezone", sa.String(length=80), nullable=False),
        sa.Column("acquisition_version", sa.String(length=40), nullable=False),
        sa.Column("manual_idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("total_jobs", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("succeeded_jobs", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("failed_jobs", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("new_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("unchanged_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("duplicate_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "trigger IN ('scheduled', 'manual')", name="ck_acquisition_runs_trigger"
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', "
            "'partially_succeeded', 'failed', 'cancelled')",
            name="ck_acquisition_runs_status",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_acquisition_runs"),
    )
    op.create_index("ix_acquisition_runs_created_at", "acquisition_runs", ["created_at"])
    op.create_index(
        "uq_acquisition_runs_scheduled_business_key",
        "acquisition_runs",
        ["business_date", "timezone", "acquisition_version"],
        unique=True,
        postgresql_where=sa.text("trigger = 'scheduled'"),
    )
    op.create_index(
        "uq_acquisition_runs_manual_idempotency",
        "acquisition_runs",
        ["manual_idempotency_key"],
        unique=True,
        postgresql_where=sa.text("manual_idempotency_key IS NOT NULL"),
    )

    op.create_table(
        "acquisition_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column(
            "available_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("lease_owner", sa.String(length=200), nullable=True),
        sa.Column("lease_token", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(length=40), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("new_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("unchanged_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("duplicate_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("byte_count", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'retry_scheduled', "
            "'succeeded', 'failed', 'cancelled')",
            name="ck_acquisition_jobs_status",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["acquisition_runs.id"],
            name="fk_acquisition_jobs_run_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["sources.id"], name="fk_acquisition_jobs_source_id", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["source_version_id"],
            ["source_versions.id"],
            name="fk_acquisition_jobs_source_version_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_acquisition_jobs"),
        sa.UniqueConstraint("run_id", "source_id", name="uq_acquisition_jobs_run_source"),
    )
    op.create_index(
        "ix_acquisition_jobs_claim",
        "acquisition_jobs",
        ["status", "available_at", "lease_expires_at"],
    )
    op.create_index("ix_acquisition_jobs_run_id", "acquisition_jobs", ["run_id"])
    op.create_index("ix_acquisition_jobs_source_id", "acquisition_jobs", ["source_id"])

    op.create_table(
        "acquisition_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result", sa.String(length=40), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("byte_count", sa.BigInteger(), server_default=sa.text("0"), nullable=False),
        sa.Column("item_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["acquisition_jobs.id"],
            name="fk_acquisition_attempts_job_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_acquisition_attempts"),
        sa.UniqueConstraint("job_id", "attempt_number", name="uq_acquisition_attempts_job_number"),
    )
    op.create_index("ix_acquisition_attempts_job_id", "acquisition_attempts", ["job_id"])

    op.create_table(
        "source_fetch_leases",
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("lease_owner", sa.String(length=200), nullable=False),
        sa.Column("lease_token", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name="fk_source_fetch_leases_source_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("source_id", name="pk_source_fetch_leases"),
    )
    op.create_index("ix_source_fetch_leases_expires_at", "source_fetch_leases", ["expires_at"])

    op.create_table(
        "source_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=20), nullable=False),
        sa.Column("original_url", sa.Text(), nullable=False),
        sa.Column("final_url", sa.Text(), nullable=False),
        sa.Column("bucket", sa.String(length=120), nullable=False),
        sa.Column("object_key", sa.String(length=300), nullable=False),
        sa.Column("media_type", sa.String(length=120), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("response_metadata", postgresql.JSONB(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("connector_version", sa.String(length=40), nullable=False),
        sa.Column("parser_version", sa.String(length=40), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("kind IN ('list', 'detail')", name="ck_source_snapshots_kind"),
        sa.CheckConstraint("byte_size >= 0", name="ck_source_snapshots_byte_size"),
        sa.ForeignKeyConstraint(
            ["source_version_id"],
            ["source_versions.id"],
            name="fk_source_snapshots_source_version_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_source_snapshots"),
        sa.UniqueConstraint("bucket", "object_key", name="uq_source_snapshots_object"),
        sa.UniqueConstraint(
            "source_version_id", "sha256", "kind", name="uq_source_snapshots_content_identity"
        ),
    )
    op.create_index(
        "ix_source_snapshots_source_version_id", "source_snapshots", ["source_version_id"]
    )

    op.create_table(
        "evidence_candidates",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_item_id", sa.String(length=500), nullable=False),
        sa.Column("original_url", sa.Text(), nullable=False),
        sa.Column("canonical_url", sa.Text(), nullable=False),
        sa.Column("trust_tier", sa.String(length=1), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("clean_text", sa.Text(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("language", sa.String(length=20), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("parser_version", sa.String(length=40), nullable=False),
        sa.Column("extraction_metadata", postgresql.JSONB(), nullable=False),
        sa.Column("primary_snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("trust_tier IN ('A', 'B')", name="ck_evidence_candidates_trust_tier"),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            name="fk_evidence_candidates_source_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_version_id"],
            ["source_versions.id"],
            name="fk_evidence_candidates_source_version_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["primary_snapshot_id"],
            ["source_snapshots.id"],
            name="fk_evidence_candidates_primary_snapshot_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_evidence_candidates"),
        sa.UniqueConstraint(
            "source_version_id",
            "source_item_id",
            "content_hash",
            name="uq_evidence_candidates_item_content",
        ),
    )
    op.create_index(
        "ix_evidence_candidates_published_at", "evidence_candidates", ["published_at", "id"]
    )
    op.create_index(
        "ix_evidence_candidates_source_id", "evidence_candidates", ["source_id", "created_at"]
    )

    op.create_table(
        "source_observations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("idempotency_key", sa.String(length=64), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_item_id", sa.String(length=500), nullable=True),
        sa.Column("outcome", sa.String(length=40), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("candidate_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("metadata", postgresql.JSONB(), nullable=False),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["acquisition_runs.id"],
            name="fk_source_observations_run_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["acquisition_jobs.id"],
            name="fk_source_observations_job_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_version_id"],
            ["source_versions.id"],
            name="fk_source_observations_source_version_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["source_snapshots.id"],
            name="fk_source_observations_snapshot_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_id"],
            ["evidence_candidates.id"],
            name="fk_source_observations_candidate_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_source_observations"),
        sa.UniqueConstraint("idempotency_key", name="uq_source_observations_idempotency_key"),
    )
    op.create_index("ix_source_observations_run_id", "source_observations", ["run_id"])
    op.create_index("ix_source_observations_candidate_id", "source_observations", ["candidate_id"])


def downgrade() -> None:
    op.drop_table("source_observations")
    op.drop_table("evidence_candidates")
    op.drop_table("source_snapshots")
    op.drop_table("source_fetch_leases")
    op.drop_table("acquisition_attempts")
    op.drop_table("acquisition_jobs")
    op.drop_table("acquisition_runs")
    op.drop_table("source_cursors")
    op.drop_constraint("fk_sources_active_version_id", "sources", type_="foreignkey")
    op.drop_table("source_versions")
    op.drop_table("sources")
