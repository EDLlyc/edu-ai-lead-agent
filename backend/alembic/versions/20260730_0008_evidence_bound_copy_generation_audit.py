"""Add evidence-bound copy generation, validation, audit, and one repair.

Revision ID: 20260730_0008
Revises: 20260730_0007
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260730_0008"
down_revision: str | None = "20260730_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_evidence_bindings_copy_provenance",
        "evidence_bindings",
        ["id", "candidate_id", "passage_id", "occurrence_id", "snapshot_id"],
    )
    op.create_table(
        "copy_generation_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("daily_topic_selection_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("topic_selection_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("timezone", sa.String(length=80), nullable=False),
        sa.Column("scoring_profile", sa.String(length=40), nullable=False),
        sa.Column("decision_kind", sa.String(length=20), nullable=False),
        sa.Column("selected_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("selected_event_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("no_topic_code", sa.String(length=40), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("pipeline_version", sa.String(length=80), nullable=False),
        sa.Column("version_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("version_bundle", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("active_draft_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("repair_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
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
            "decision_kind IN ('selected', 'no_topic')", name="ck_copy_generation_runs_decision"
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'no_topic', 'accepted', 'review_required', 'failed')",
            name="ck_copy_generation_runs_status",
        ),
        sa.CheckConstraint("repair_count BETWEEN 0 AND 1", name="ck_copy_generation_runs_repair"),
        sa.CheckConstraint(
            "(decision_kind = 'selected' AND selected_event_id IS NOT NULL "
            "AND selected_event_version_id IS NOT NULL AND no_topic_code IS NULL) OR "
            "(decision_kind = 'no_topic' AND selected_event_id IS NULL "
            "AND selected_event_version_id IS NULL AND no_topic_code IS NOT NULL)",
            name="ck_copy_generation_runs_topic_shape",
        ),
        sa.ForeignKeyConstraint(
            ["daily_topic_selection_id"],
            ["daily_topic_selections.id"],
            name="fk_copy_generation_runs_daily_topic_selection_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["topic_selection_run_id"],
            ["topic_selection_runs.id"],
            name="fk_copy_generation_runs_topic_selection_run_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["selected_event_version_id", "selected_event_id"],
            ["event_cluster_versions.id", "event_cluster_versions.event_id"],
            name="fk_copy_generation_runs_event_version_event",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_copy_generation_runs"),
        sa.UniqueConstraint(
            "daily_topic_selection_id",
            "version_fingerprint",
            name="uq_copy_generation_runs_topic_version",
        ),
    )
    op.create_index(
        "ix_copy_generation_runs_status_created",
        "copy_generation_runs",
        ["status", "created_at"],
    )
    op.create_table(
        "copy_generation_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
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
            name="ck_copy_generation_jobs_status",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_copy_generation_jobs_attempt_count"),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["copy_generation_runs.id"],
            name="fk_copy_generation_jobs_run_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_copy_generation_jobs"),
        sa.UniqueConstraint("run_id", name="uq_copy_generation_jobs_run_id"),
    )
    op.create_index(
        "ix_copy_generation_jobs_claim",
        "copy_generation_jobs",
        ["status", "available_at", "lease_expires_at"],
    )
    op.create_table(
        "copy_draft_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("repair_of_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("copywriting", sa.Text(), nullable=False),
        sa.Column("parent_takeaway", sa.Text(), nullable=False),
        sa.Column("interaction", sa.Text(), nullable=False),
        sa.Column("source_note", sa.Text(), nullable=False),
        sa.Column("image_prompt", sa.Text(), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("provider_request_id", sa.String(length=200), nullable=True),
        sa.Column("prompt_version", sa.String(length=80), nullable=False),
        sa.Column("schema_version", sa.String(length=80), nullable=False),
        sa.Column("rule_version", sa.String(length=80), nullable=False),
        sa.Column("validation_passed", sa.Boolean(), nullable=False),
        sa.Column("audit_accepted", sa.Boolean(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("version IN (1, 2)", name="ck_copy_draft_versions_version"),
        sa.CheckConstraint(
            "(version = 1 AND repair_of_version_id IS NULL) OR "
            "(version = 2 AND repair_of_version_id IS NOT NULL)",
            name="ck_copy_draft_versions_repair_lineage",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["copy_generation_runs.id"],
            name="fk_copy_draft_versions_run_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["repair_of_version_id", "run_id"],
            ["copy_draft_versions.id", "copy_draft_versions.run_id"],
            name="fk_copy_draft_versions_repair_same_run",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_copy_draft_versions"),
        sa.UniqueConstraint("id", "run_id", name="uq_copy_draft_versions_id_run"),
        sa.UniqueConstraint("run_id", "version", name="uq_copy_draft_versions_run_version"),
        sa.UniqueConstraint(
            "provider", "request_fingerprint", name="uq_copy_draft_versions_request"
        ),
    )
    op.create_index("ix_copy_draft_versions_run_id", "copy_draft_versions", ["run_id"])
    op.create_foreign_key(
        "fk_copy_generation_runs_active_draft_run",
        "copy_generation_runs",
        "copy_draft_versions",
        ["active_draft_version_id", "id"],
        ["id", "run_id"],
        ondelete="RESTRICT",
    )
    op.create_table(
        "copy_generation_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("draft_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("capability", sa.String(length=40), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("provider_request_id", sa.String(length=200), nullable=True),
        sa.Column("prompt_version", sa.String(length=80), nullable=False),
        sa.Column("schema_version", sa.String(length=80), nullable=False),
        sa.Column("rule_version", sa.String(length=80), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("reasoning_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("latency_ms", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column(
            "safe_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "capability IN ('generation', 'audit', 'workflow')",
            name="ck_copy_generation_attempts_capability",
        ),
        sa.CheckConstraint(
            "status IN ('succeeded', 'failed')", name="ck_copy_generation_attempts_status"
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["copy_generation_jobs.id"],
            name="fk_copy_generation_attempts_job_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["draft_version_id"],
            ["copy_draft_versions.id"],
            name="fk_copy_generation_attempts_draft_version_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_copy_generation_attempts"),
        sa.UniqueConstraint(
            "capability", "request_fingerprint", name="uq_copy_generation_attempts_request"
        ),
    )
    op.create_index("ix_copy_generation_attempts_job_id", "copy_generation_attempts", ["job_id"])
    op.create_table(
        "copy_draft_claims",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("draft_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_key", sa.String(length=80), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.CheckConstraint(
            "kind IN ('external_fact', 'brand_statement', 'opinion')",
            name="ck_copy_draft_claims_kind",
        ),
        sa.CheckConstraint("ordinal >= 0", name="ck_copy_draft_claims_ordinal"),
        sa.ForeignKeyConstraint(
            ["draft_version_id"],
            ["copy_draft_versions.id"],
            name="fk_copy_draft_claims_draft_version_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_copy_draft_claims"),
        sa.UniqueConstraint("draft_version_id", "claim_key", name="uq_copy_draft_claims_draft_key"),
        sa.UniqueConstraint(
            "draft_version_id", "ordinal", name="uq_copy_draft_claims_draft_ordinal"
        ),
    )
    op.create_table(
        "copy_claim_evidence_bindings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("evidence_binding_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("candidate_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("passage_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("occurrence_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_tier", sa.String(length=1), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exact_quote", sa.Text(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("source_tier IN ('A', 'B')", name="ck_copy_evidence_source_tier"),
        sa.ForeignKeyConstraint(
            ["claim_id"],
            ["copy_draft_claims.id"],
            name="fk_copy_claim_evidence_bindings_claim_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            [
                "evidence_binding_id",
                "candidate_id",
                "passage_id",
                "occurrence_id",
                "snapshot_id",
            ],
            [
                "evidence_bindings.id",
                "evidence_bindings.candidate_id",
                "evidence_bindings.passage_id",
                "evidence_bindings.occurrence_id",
                "evidence_bindings.snapshot_id",
            ],
            name="fk_copy_claim_evidence_bindings_provenance",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_copy_claim_evidence_bindings"),
        sa.UniqueConstraint(
            "claim_id", "evidence_binding_id", name="uq_copy_claim_evidence_binding"
        ),
    )
    op.create_table(
        "copy_claim_brand_bindings",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("claim_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("brand_chunk_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["claim_id"],
            ["copy_draft_claims.id"],
            name="fk_copy_claim_brand_bindings_claim_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["brand_chunk_id"],
            ["brand_chunks.id"],
            name="fk_copy_claim_brand_bindings_brand_chunk_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_copy_claim_brand_bindings"),
        sa.UniqueConstraint("claim_id", "brand_chunk_id", name="uq_copy_claim_brand_binding"),
    )
    op.create_table(
        "copy_validation_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("draft_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("rule_version", sa.String(length=80), nullable=False),
        sa.Column("result_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["draft_version_id"],
            ["copy_draft_versions.id"],
            name="fk_copy_validation_results_draft_version_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_copy_validation_results"),
        sa.UniqueConstraint("draft_version_id", name="uq_copy_validation_results_draft"),
        sa.UniqueConstraint("result_fingerprint", name="uq_copy_validation_results_fingerprint"),
    )
    op.create_table(
        "copy_audits",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("draft_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("accepted", sa.Boolean(), nullable=False),
        sa.Column("prompt_version", sa.String(length=80), nullable=False),
        sa.Column("schema_version", sa.String(length=80), nullable=False),
        sa.Column("rule_version", sa.String(length=80), nullable=False),
        sa.Column("result_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["draft_version_id"],
            ["copy_draft_versions.id"],
            name="fk_copy_audits_draft_version_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["copy_generation_attempts.id"],
            name="fk_copy_audits_attempt_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_copy_audits"),
        sa.UniqueConstraint("draft_version_id", name="uq_copy_audits_draft"),
        sa.UniqueConstraint("result_fingerprint", name="uq_copy_audits_fingerprint"),
    )
    op.create_table(
        "copy_issues",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("draft_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stage", sa.String(length=30), nullable=False),
        sa.Column("audit_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=80), nullable=False),
        sa.Column("severity", sa.String(length=20), nullable=False),
        sa.Column("field_name", sa.String(length=80), nullable=True),
        sa.Column("claim_key", sa.String(length=80), nullable=True),
        sa.Column("safe_message", sa.String(length=240), nullable=False),
        sa.CheckConstraint("stage IN ('deterministic', 'audit')", name="ck_copy_issues_stage"),
        sa.CheckConstraint(
            "(stage = 'deterministic' AND audit_id IS NULL) OR "
            "(stage = 'audit' AND audit_id IS NOT NULL)",
            name="ck_copy_issues_stage_audit_shape",
        ),
        sa.CheckConstraint("severity IN ('warning', 'error')", name="ck_copy_issues_severity"),
        sa.CheckConstraint("ordinal >= 0", name="ck_copy_issues_ordinal"),
        sa.ForeignKeyConstraint(
            ["draft_version_id"],
            ["copy_draft_versions.id"],
            name="fk_copy_issues_draft_version_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["audit_id"],
            ["copy_audits.id"],
            name="fk_copy_issues_audit_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_copy_issues"),
        sa.UniqueConstraint(
            "draft_version_id", "stage", "ordinal", name="uq_copy_issues_draft_stage_ordinal"
        ),
    )
    op.create_table(
        "copy_generation_checkpoints",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("stage", sa.String(length=40), nullable=False),
        sa.Column("draft_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "issue_codes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "jsonb_typeof(issue_codes) = 'array'",
            name="ck_copy_checkpoints_issue_codes_array",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["copy_generation_runs.id"],
            name="fk_copy_generation_checkpoints_run_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("run_id", name="pk_copy_generation_checkpoints"),
    )


def downgrade() -> None:
    op.drop_table("copy_generation_checkpoints")
    op.drop_table("copy_issues")
    op.drop_table("copy_audits")
    op.drop_table("copy_validation_results")
    op.drop_table("copy_claim_brand_bindings")
    op.drop_table("copy_claim_evidence_bindings")
    op.drop_table("copy_draft_claims")
    op.drop_table("copy_generation_attempts")
    op.drop_constraint(
        "fk_copy_generation_runs_active_draft_run",
        "copy_generation_runs",
        type_="foreignkey",
    )
    op.drop_index("ix_copy_draft_versions_run_id", table_name="copy_draft_versions")
    op.drop_table("copy_draft_versions")
    op.drop_index("ix_copy_generation_jobs_claim", table_name="copy_generation_jobs")
    op.drop_table("copy_generation_jobs")
    op.drop_index("ix_copy_generation_runs_status_created", table_name="copy_generation_runs")
    op.drop_table("copy_generation_runs")
    op.drop_constraint(
        "uq_evidence_bindings_copy_provenance",
        "evidence_bindings",
        type_="unique",
    )
