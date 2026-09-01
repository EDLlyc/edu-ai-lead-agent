"""Add durable WeChat Official Account draft jobs."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260901_0042"
down_revision: str | None = "20260901_0041"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "wechat_mp_draft_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("account_fingerprint", sa.String(64), nullable=False),
        sa.Column("aggregate_fingerprint", sa.String(64), nullable=False),
        sa.Column("batch_fingerprint", sa.String(64), nullable=False),
        sa.Column("policy_version", sa.String(80), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.String(128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fencing_token", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_wechat_mp_draft_jobs"),
        sa.UniqueConstraint(
            "request_fingerprint",
            name="uq_wechat_mp_draft_jobs_request",
        ),
        sa.CheckConstraint(
            "request_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND account_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND aggregate_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND batch_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_wechat_mp_draft_jobs_fingerprints",
        ),
        sa.CheckConstraint(
            "policy_version = 'wechat-mp-draft-job-v1'",
            name="ck_wechat_mp_draft_jobs_policy",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'retryable_failed', 'ready', "
            "'terminal_failed', 'outcome_unknown')",
            name="ck_wechat_mp_draft_jobs_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND max_attempts BETWEEN 1 AND 10 "
            "AND attempt_count <= max_attempts * 3 AND fencing_token >= 0",
            name="ck_wechat_mp_draft_jobs_attempts",
        ),
        sa.CheckConstraint(
            "(status = 'running' AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL "
            "AND heartbeat_at IS NOT NULL) OR "
            "(status <> 'running' AND lease_owner IS NULL AND lease_expires_at IS NULL "
            "AND heartbeat_at IS NULL)",
            name="ck_wechat_mp_draft_jobs_lease_shape",
        ),
        sa.CheckConstraint(
            "status NOT IN ('ready', 'terminal_failed', 'outcome_unknown') "
            "OR completed_at IS NOT NULL",
            name="ck_wechat_mp_draft_jobs_completion",
        ),
        sa.CheckConstraint(
            "error_code IS NULL OR error_code ~ '^[a-z][a-z0-9_.:-]{0,79}$'",
            name="ck_wechat_mp_draft_jobs_error_code",
        ),
        sa.CheckConstraint(
            "lease_owner IS NULL OR lease_owner ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$'",
            name="ck_wechat_mp_draft_jobs_lease_owner",
        ),
    )
    op.create_index(
        "ix_wechat_mp_draft_jobs_claim",
        "wechat_mp_draft_jobs",
        ["status", "available_at", "lease_expires_at", "created_at"],
        unique=False,
    )

    op.create_table(
        "wechat_mp_draft_items",
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ordinal", sa.SmallInteger(), nullable=False),
        sa.Column("role", sa.String(32), nullable=False),
        sa.Column("source_ref", sa.String(128), nullable=False),
        sa.Column("source_fingerprint", sa.String(64), nullable=False),
        sa.Column("article_fingerprint", sa.String(64), nullable=False),
        sa.Column("content_fingerprint", sa.String(64), nullable=False),
        sa.Column("policy_fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("side_effect_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("endpoint", sa.String(80), nullable=True),
        sa.Column("uploaded_image_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("draft_media_fingerprint", sa.String(64), nullable=True),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("job_id", "ordinal", name="pk_wechat_mp_draft_items"),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["wechat_mp_draft_jobs.id"],
            name="fk_wechat_mp_draft_items_job",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("job_id", "role", name="uq_wechat_mp_draft_items_role"),
        sa.CheckConstraint(
            "(ordinal = 1 AND role = 'official_anchor') OR "
            "(ordinal = 2 AND role = 'industry_trend') OR "
            "(ordinal = 3 AND role = 'application_case')",
            name="ck_wechat_mp_draft_items_role_ordinal",
        ),
        sa.CheckConstraint(
            "source_ref ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$'",
            name="ck_wechat_mp_draft_items_source_ref",
        ),
        sa.CheckConstraint(
            "source_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND article_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND content_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND policy_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_wechat_mp_draft_items_fingerprints",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'retryable_failed', 'succeeded', "
            "'terminal_failed', 'outcome_unknown')",
            name="ck_wechat_mp_draft_items_status",
        ),
        sa.CheckConstraint(
            "attempt_count >= 0 AND uploaded_image_count >= 0",
            name="ck_wechat_mp_draft_items_counters",
        ),
        sa.CheckConstraint(
            "endpoint IS NULL OR endpoint ~ '^[a-z][a-z0-9_.:-]{0,79}$'",
            name="ck_wechat_mp_draft_items_endpoint",
        ),
        sa.CheckConstraint(
            "draft_media_fingerprint IS NULL OR draft_media_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_wechat_mp_draft_items_media_fingerprint",
        ),
        sa.CheckConstraint(
            "status <> 'succeeded' OR (side_effect_started_at IS NOT NULL "
            "AND draft_media_fingerprint IS NOT NULL AND completed_at IS NOT NULL)",
            name="ck_wechat_mp_draft_items_success_shape",
        ),
        sa.CheckConstraint(
            "status NOT IN ('terminal_failed', 'outcome_unknown') OR completed_at IS NOT NULL",
            name="ck_wechat_mp_draft_items_terminal_shape",
        ),
        sa.CheckConstraint(
            "status <> 'outcome_unknown' OR side_effect_started_at IS NOT NULL",
            name="ck_wechat_mp_draft_items_unknown_shape",
        ),
        sa.CheckConstraint(
            "error_code IS NULL OR error_code ~ '^[a-z][a-z0-9_.:-]{0,79}$'",
            name="ck_wechat_mp_draft_items_error_code",
        ),
    )
    op.create_index(
        "ix_wechat_mp_draft_items_job_status",
        "wechat_mp_draft_items",
        ["job_id", "status", "ordinal"],
        unique=False,
    )

    op.create_table(
        "wechat_mp_draft_attempts",
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("item_ordinal", sa.SmallInteger(), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("fencing_token", sa.BigInteger(), nullable=False),
        sa.Column("worker_id", sa.String(128), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("endpoint", sa.String(80), nullable=True),
        sa.Column("side_effect_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("uploaded_image_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("draft_media_fingerprint", sa.String(64), nullable=True),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint(
            "job_id",
            "item_ordinal",
            "attempt_no",
            name="pk_wechat_mp_draft_attempts",
        ),
        sa.ForeignKeyConstraint(
            ["job_id", "item_ordinal"],
            ["wechat_mp_draft_items.job_id", "wechat_mp_draft_items.ordinal"],
            name="fk_wechat_mp_draft_attempts_item",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "attempt_no > 0 AND fencing_token > 0 AND uploaded_image_count >= 0",
            name="ck_wechat_mp_draft_attempts_counters",
        ),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'retryable_failed', 'terminal_failed', "
            "'outcome_unknown', 'lease_expired')",
            name="ck_wechat_mp_draft_attempts_status",
        ),
        sa.CheckConstraint(
            "endpoint IS NULL OR endpoint ~ '^[a-z][a-z0-9_.:-]{0,79}$'",
            name="ck_wechat_mp_draft_attempts_endpoint",
        ),
        sa.CheckConstraint(
            "draft_media_fingerprint IS NULL OR draft_media_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_wechat_mp_draft_attempts_media_fingerprint",
        ),
        sa.CheckConstraint(
            "status = 'running' OR completed_at IS NOT NULL",
            name="ck_wechat_mp_draft_attempts_completion",
        ),
        sa.CheckConstraint(
            "worker_id ~ '^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$'",
            name="ck_wechat_mp_draft_attempts_worker_id",
        ),
        sa.CheckConstraint(
            "error_code IS NULL OR error_code ~ '^[a-z][a-z0-9_.:-]{0,79}$'",
            name="ck_wechat_mp_draft_attempts_error_code",
        ),
        sa.CheckConstraint(
            "status <> 'succeeded' OR (side_effect_started_at IS NOT NULL "
            "AND draft_media_fingerprint IS NOT NULL AND completed_at IS NOT NULL)",
            name="ck_wechat_mp_draft_attempts_success_shape",
        ),
        sa.CheckConstraint(
            "status <> 'outcome_unknown' OR side_effect_started_at IS NOT NULL",
            name="ck_wechat_mp_draft_attempts_unknown_shape",
        ),
    )
    op.create_index(
        "ix_wechat_mp_draft_attempts_job_started",
        "wechat_mp_draft_attempts",
        ["job_id", "started_at"],
        unique=False,
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM wechat_mp_draft_jobs) "
            "OR EXISTS (SELECT 1 FROM wechat_mp_draft_items) "
            "OR EXISTS (SELECT 1 FROM wechat_mp_draft_attempts) THEN "
            "RAISE EXCEPTION "
            "'cannot downgrade WeChat Official Account draft jobs while durable data exists'; "
            "END IF; END $$"
        )
    )
    op.drop_index(
        "ix_wechat_mp_draft_attempts_job_started",
        table_name="wechat_mp_draft_attempts",
    )
    op.drop_table("wechat_mp_draft_attempts")
    op.drop_index(
        "ix_wechat_mp_draft_items_job_status",
        table_name="wechat_mp_draft_items",
    )
    op.drop_table("wechat_mp_draft_items")
    op.drop_index(
        "ix_wechat_mp_draft_jobs_claim",
        table_name="wechat_mp_draft_jobs",
    )
    op.drop_table("wechat_mp_draft_jobs")
