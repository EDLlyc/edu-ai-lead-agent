"""Add independent per-news infographic generation and WeCom supplement state."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260923_0049"
down_revision: str | None = "20260916_0048"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _id(name: str, target: str) -> sa.Column[object]:
    return sa.Column(
        name,
        postgresql.UUID(as_uuid=True),
        sa.ForeignKey(target, name=f"fk_news_infographic_jobs_{name}", ondelete="RESTRICT"),
        nullable=False,
    )


def upgrade() -> None:
    op.create_table(
        "news_infographic_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        _id("base_job_id", "wecom_delivery_jobs.id"),
        _id("material_package_id", "material_packages.id"),
        _id("copy_generation_run_id", "copy_generation_runs.id"),
        _id("content_slot_selection_id", "content_slot_selections.id"),
        sa.Column("sequence_ordinal", sa.Integer(), nullable=False),
        sa.Column("selected_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("selected_event_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("content_slot", sa.String(20), nullable=False),
        sa.Column("recipient_id", sa.String(80), nullable=False),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("package_version", sa.Integer(), nullable=False),
        sa.Column("policy_fingerprint", sa.String(64), nullable=False),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("stage", sa.String(24), nullable=False),
        sa.Column("copy_request_fingerprint", sa.String(64), nullable=True),
        sa.Column("audit_request_fingerprint", sa.String(64), nullable=True),
        sa.Column("image_request_fingerprint", sa.String(64), nullable=True),
        sa.Column("ocr_request_fingerprint", sa.String(64), nullable=True),
        sa.Column("footer_ocr_request_fingerprint", sa.String(64), nullable=True),
        sa.Column("visual_request_fingerprint", sa.String(64), nullable=True),
        sa.Column("copy_intent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("audit_intent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("image_intent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ocr_intent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("footer_ocr_intent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("visual_intent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw_sha256", sa.String(64), nullable=True),
        sa.Column("raw_byte_size", sa.Integer(), nullable=True),
        sa.Column("raw_media_type", sa.String(32), nullable=True),
        sa.Column("composite_sha256", sa.String(64), nullable=True),
        sa.Column("composite_byte_size", sa.Integer(), nullable=True),
        sa.Column("footer_sha256", sa.String(64), nullable=True),
        sa.Column("footer_byte_size", sa.Integer(), nullable=True),
        sa.Column("delivery_sha256", sa.String(64), nullable=True),
        sa.Column("delivery_byte_size", sa.Integer(), nullable=True),
        sa.Column("delivery_media_type", sa.String(32), nullable=True),
        sa.Column("delivery_width", sa.Integer(), nullable=True),
        sa.Column("delivery_height", sa.Integer(), nullable=True),
        sa.Column("ocr_status", sa.String(20), nullable=False, server_default="not_checked"),
        sa.Column("footer_ocr_status", sa.String(20), nullable=False, server_default="not_checked"),
        sa.Column("visual_status", sa.String(20), nullable=False, server_default="not_checked"),
        sa.Column("safe_error_code", sa.String(80), nullable=True),
        sa.Column("lease_owner", sa.String(200), nullable=True),
        sa.Column("lease_token", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "sequence_ordinal BETWEEN 1 AND 3", name="ck_news_infographic_jobs_ordinal"
        ),
        sa.CheckConstraint("package_version >= 1", name="ck_news_infographic_jobs_package_version"),
        sa.CheckConstraint(
            "content_slot IN ('morning', 'noon', 'evening')", name="ck_news_infographic_jobs_slot"
        ),
        sa.CheckConstraint("provider = 'group_webhook'", name="ck_news_infographic_jobs_provider"),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'ready', 'failed', "
            "'result_unknown', 'expired', 'skipped')",
            name="ck_news_infographic_jobs_status",
        ),
        sa.UniqueConstraint("base_job_id", name="uq_news_infographic_jobs_base_job"),
        sa.UniqueConstraint(
            "content_slot_selection_id",
            "recipient_id",
            "provider",
            "policy_fingerprint",
            name="uq_news_infographic_jobs_slot_selection_policy",
        ),
        sa.UniqueConstraint(
            "material_package_id",
            "package_version",
            "policy_fingerprint",
            name="uq_news_infographic_jobs_package_policy",
        ),
        sa.ForeignKeyConstraint(
            ["content_slot_selection_id", "sequence_ordinal"],
            ["content_slot_selections.id", "content_slot_selections.ordinal"],
            name="fk_news_infographic_jobs_selection_ordinal",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_news_infographic_jobs_date_intent",
        "news_infographic_jobs",
        ["business_date", "image_intent_at"],
    )
    op.create_index(
        "ix_news_infographic_jobs_claim", "news_infographic_jobs", ["status", "lease_expires_at"]
    )
    op.create_table(
        "wecom_infographic_supplements",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "infographic_job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "news_infographic_jobs.id",
                name="fk_wecom_infographic_supplements_infographic_job_id",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column(
            "base_job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "wecom_delivery_jobs.id",
                name="fk_wecom_infographic_supplements_base_job_id",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.String(200), nullable=True),
        sa.Column("lease_token", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("safe_error_code", sa.String(80), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'delivered', 'failed', 'result_unknown', 'expired')",
            name="ck_wecom_infographic_supplements_status",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_wecom_infographic_supplements_attempts"),
        sa.UniqueConstraint("infographic_job_id", name="uq_wecom_infographic_supplements_artifact"),
        sa.UniqueConstraint("base_job_id", name="uq_wecom_infographic_supplements_base_job"),
        sa.UniqueConstraint("request_fingerprint", name="uq_wecom_infographic_supplements_request"),
    )
    op.create_index(
        "ix_wecom_infographic_supplements_claim",
        "wecom_infographic_supplements",
        ["status", "next_attempt_at", "expires_at"],
    )
    op.create_table(
        "wecom_infographic_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "supplement_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "wecom_infographic_supplements.id",
                name="fk_wecom_infographic_attempts_supplement_id",
                ondelete="RESTRICT",
            ),
            nullable=False,
        ),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("result_state", sa.String(20), nullable=False),
        sa.Column("safe_response_code", sa.String(80), nullable=True),
        sa.Column("provider_request_id", sa.String(200), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint("attempt_number >= 1", name="ck_wecom_infographic_attempts_number"),
        sa.CheckConstraint(
            "result_state IN ('succeeded', 'failed', 'unknown')",
            name="ck_wecom_infographic_attempts_result",
        ),
        sa.UniqueConstraint(
            "supplement_id", "attempt_number", name="uq_wecom_infographic_attempts_number"
        ),
    )
    op.create_table(
        "wecom_infographic_test_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "formal_base_job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("wecom_delivery_jobs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "infographic_job_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("news_infographic_jobs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "material_package_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("material_packages.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "content_slot_selection_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("content_slot_selections.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("sequence_ordinal", sa.Integer(), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("content_slot", sa.String(20), nullable=False),
        sa.Column("package_version", sa.Integer(), nullable=False),
        sa.Column("target_fingerprint", sa.String(64), nullable=False),
        sa.Column("formal_delivery_sha256", sa.String(64), nullable=False),
        sa.Column("test_artifact_sha256", sa.String(64), nullable=False),
        sa.Column("test_artifact_byte_size", sa.Integer(), nullable=False),
        sa.Column("text_sha256", sa.String(64), nullable=False),
        sa.Column("original_image_sha256", sa.String(64), nullable=False),
        sa.Column("original_delivery_sha256", sa.String(64), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("text_status", sa.String(20), nullable=False),
        sa.Column("original_status", sa.String(20), nullable=False),
        sa.Column("infographic_status", sa.String(20), nullable=False),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.String(200), nullable=True),
        sa.Column("lease_token", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("safe_error_code", sa.String(80), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "sequence_ordinal BETWEEN 1 AND 3", name="ck_wecom_infographic_test_runs_ordinal"
        ),
        sa.CheckConstraint(
            "content_slot IN ('morning', 'noon', 'evening')",
            name="ck_wecom_infographic_test_runs_slot",
        ),
        sa.CheckConstraint(
            "status IN ('prepared', 'queued', 'running', 'delivered', "
            "'failed', 'result_unknown', 'expired')",
            name="ck_wecom_infographic_test_runs_status",
        ),
        sa.CheckConstraint(
            "text_status IN ('pending', 'running', 'delivered', 'failed', 'unknown')",
            name="ck_wecom_infographic_test_runs_text_status",
        ),
        sa.CheckConstraint(
            "original_status IN ('pending', 'running', 'delivered', 'failed', 'unknown')",
            name="ck_wecom_infographic_test_runs_original_status",
        ),
        sa.CheckConstraint(
            "infographic_status IN ('pending', 'running', 'delivered', 'failed', 'unknown')",
            name="ck_wecom_infographic_test_runs_infographic_status",
        ),
        sa.UniqueConstraint(
            "formal_base_job_id", name="uq_wecom_infographic_test_runs_formal_base"
        ),
        sa.UniqueConstraint("infographic_job_id", name="uq_wecom_infographic_test_runs_poster"),
        sa.ForeignKeyConstraint(
            ["content_slot_selection_id", "sequence_ordinal"],
            ["content_slot_selections.id", "content_slot_selections.ordinal"],
            name="fk_wecom_infographic_test_runs_selection_ordinal",
            ondelete="RESTRICT",
        ),
    )
    op.create_index(
        "ix_wecom_infographic_test_runs_claim",
        "wecom_infographic_test_runs",
        ["status", "expires_at"],
    )
    op.create_table(
        "wecom_infographic_test_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "test_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("wecom_infographic_test_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("message_kind", sa.String(20), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("result_state", sa.String(20), nullable=False),
        sa.Column("safe_response_code", sa.String(80), nullable=True),
        sa.Column("provider_request_id", sa.String(200), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "message_kind IN ('text', 'original', 'infographic')",
            name="ck_wecom_infographic_test_attempts_kind",
        ),
        sa.CheckConstraint(
            "result_state IN ('intent', 'succeeded', 'failed', 'unknown')",
            name="ck_wecom_infographic_test_attempts_result",
        ),
        sa.UniqueConstraint(
            "test_run_id", "message_kind", name="uq_wecom_infographic_test_attempts_kind"
        ),
    )


def downgrade() -> None:
    # Preserve delivery and provider-call evidence. An explicit data-retention decision is required.
    connection = op.get_bind()
    for table in (
        "wecom_infographic_test_attempts",
        "wecom_infographic_test_runs",
        "wecom_infographic_attempts",
        "wecom_infographic_supplements",
        "news_infographic_jobs",
    ):
        if connection.execute(
            sa.text(f"SELECT EXISTS (SELECT 1 FROM {table} LIMIT 1)")
        ).scalar_one():
            raise RuntimeError("cannot downgrade while infographic evidence rows exist")
    op.drop_table("wecom_infographic_test_attempts")
    op.drop_index("ix_wecom_infographic_test_runs_claim", table_name="wecom_infographic_test_runs")
    op.drop_table("wecom_infographic_test_runs")
    op.drop_table("wecom_infographic_attempts")
    op.drop_index(
        "ix_wecom_infographic_supplements_claim", table_name="wecom_infographic_supplements"
    )
    op.drop_table("wecom_infographic_supplements")
    op.drop_index("ix_news_infographic_jobs_claim", table_name="news_infographic_jobs")
    op.drop_index("ix_news_infographic_jobs_date_intent", table_name="news_infographic_jobs")
    op.drop_table("news_infographic_jobs")
