"""WeChat Official Accounts bound in the 运营后台 (encrypted AppSecret) and publish jobs."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261009_0055"
down_revision: str | None = "20261008_0054"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "wechat_accounts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(40), nullable=False),
        sa.Column("app_id", sa.String(32), nullable=False),
        sa.Column("account_fingerprint", sa.String(64), nullable=False),
        sa.Column("app_secret_sealed", sa.Text(), nullable=False),
        sa.Column("app_secret_last4", sa.String(4), nullable=False),
        sa.Column("topics", postgresql.JSONB(), nullable=False),
        sa.Column("enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_verify_error", sa.String(200), nullable=True),
        sa.Column("created_by", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("app_id", name="uq_wechat_accounts_app_id"),
        sa.CheckConstraint("app_id ~ '^wx[0-9a-f]{16}$'", name="ck_wechat_accounts_app_id"),
        sa.CheckConstraint(
            "account_fingerprint ~ '^[0-9a-f]{64}$'", name="ck_wechat_accounts_fingerprint"
        ),
        sa.CheckConstraint("app_secret_sealed LIKE 'v1:%'", name="ck_wechat_accounts_sealed"),
        sa.CheckConstraint(
            "jsonb_typeof(topics) = 'array' AND jsonb_array_length(topics) <= 10",
            name="ck_wechat_accounts_topics",
        ),
    )
    op.create_table(
        "wechat_publish_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("media_id", sa.String(128), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("publish_id", sa.String(64), nullable=True),
        sa.Column("article_id", sa.String(128), nullable=True),
        sa.Column("article_url", sa.Text(), nullable=True),
        sa.Column("wechat_status", sa.Integer(), nullable=True),
        sa.Column("error", sa.String(200), nullable=True),
        sa.Column("lease_owner", sa.String(128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(40), nullable=False),
        sa.Column("cancelled_by", sa.String(40), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["account_id"], ["wechat_accounts.id"], ondelete="RESTRICT"),
        sa.CheckConstraint(
            "status IN ('scheduled', 'submitting', 'publishing', 'succeeded', 'failed', "
            "'outcome_unknown', 'cancelled')",
            name="ck_wechat_publish_jobs_status",
        ),
        sa.CheckConstraint(
            "status NOT IN ('publishing', 'succeeded') OR publish_id IS NOT NULL",
            name="ck_wechat_publish_jobs_publish_id",
        ),
    )
    op.create_index(
        "ix_wechat_publish_jobs_due", "wechat_publish_jobs", ["status", "scheduled_at"]
    )
    op.create_index(
        "uq_wechat_publish_jobs_open_draft",
        "wechat_publish_jobs",
        ["account_id", "media_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('scheduled', 'submitting', 'publishing')"),
    )


def downgrade() -> None:
    # Publish history and bound accounts are operator records; never drop them silently.
    op.execute(
        sa.text(
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM wechat_accounts) THEN "
            "RAISE EXCEPTION 'refusing to discard bound WeChat accounts'; "
            "END IF; END $$"
        )
    )
    op.drop_index("uq_wechat_publish_jobs_open_draft", table_name="wechat_publish_jobs")
    op.drop_index("ix_wechat_publish_jobs_due", table_name="wechat_publish_jobs")
    op.drop_table("wechat_publish_jobs")
    op.drop_table("wechat_accounts")
