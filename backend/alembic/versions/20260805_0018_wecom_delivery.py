"""Add durable Enterprise WeChat delivery jobs and attempts."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260805_0018"
down_revision: str | None = "20260804_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "wecom_delivery_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "material_package_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("recipient_id", sa.String(length=80), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("package_version", sa.Integer(), nullable=False),
        sa.Column("content_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("include_copy", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("include_image", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("text_status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("image_status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "next_attempt_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("lease_owner", sa.String(length=200), nullable=True),
        sa.Column("lease_token", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=80), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["material_package_id"],
            ["material_packages.id"],
            name="fk_wecom_delivery_jobs_material_package_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_wecom_delivery_jobs"),
        sa.UniqueConstraint("request_fingerprint", name="uq_wecom_delivery_jobs_request"),
        sa.CheckConstraint("mode IN ('test', 'formal')", name="ck_wecom_delivery_jobs_mode"),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'partial', 'delivery_unknown', 'delivered', "
            "'failed', 'cancelled')",
            name="ck_wecom_delivery_jobs_status",
        ),
        sa.CheckConstraint(
            "text_status IN ('pending', 'running', 'delivered', 'failed', 'unknown', 'skipped')",
            name="ck_wecom_delivery_jobs_text_status",
        ),
        sa.CheckConstraint(
            "image_status IN ('pending', 'running', 'delivered', 'failed', 'unknown', 'skipped')",
            name="ck_wecom_delivery_jobs_image_status",
        ),
        sa.CheckConstraint("package_version >= 1", name="ck_wecom_delivery_jobs_package_version"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_wecom_delivery_jobs_attempt_count"),
        sa.CheckConstraint(
            "include_copy OR include_image", name="ck_wecom_delivery_jobs_message_kind"
        ),
    )
    op.create_index(
        "ix_wecom_delivery_jobs_claim",
        "wecom_delivery_jobs",
        ["status", "next_attempt_at", "lease_expires_at"],
    )
    op.create_index(
        "ix_wecom_delivery_jobs_package",
        "wecom_delivery_jobs",
        ["material_package_id"],
    )

    op.create_table(
        "wecom_delivery_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_kind", sa.String(length=20), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("provider_request_id", sa.String(length=200), nullable=True),
        sa.Column("safe_response_code", sa.String(length=80), nullable=True),
        sa.Column("result_state", sa.String(length=20), nullable=False),
        sa.Column("latency_ms", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["wecom_delivery_jobs.id"],
            name="fk_wecom_delivery_attempts_job_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_wecom_delivery_attempts"),
        sa.CheckConstraint(
            "message_kind IN ('text', 'image')", name="ck_wecom_delivery_attempts_kind"
        ),
        sa.CheckConstraint(
            "result_state IN ('succeeded', 'failed', 'unknown')",
            name="ck_wecom_delivery_attempts_result",
        ),
        sa.CheckConstraint("attempt_number >= 1", name="ck_wecom_delivery_attempts_number"),
        sa.CheckConstraint("latency_ms >= 0", name="ck_wecom_delivery_attempts_latency"),
    )
    op.create_index(
        "ix_wecom_delivery_attempts_job",
        "wecom_delivery_attempts",
        ["job_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_wecom_delivery_attempts_job", table_name="wecom_delivery_attempts")
    op.drop_table("wecom_delivery_attempts")
    op.drop_index("ix_wecom_delivery_jobs_package", table_name="wecom_delivery_jobs")
    op.drop_index("ix_wecom_delivery_jobs_claim", table_name="wecom_delivery_jobs")
    op.drop_table("wecom_delivery_jobs")
