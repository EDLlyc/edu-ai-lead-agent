"""Operator accounts, login sessions and the audit log of the 运营后台."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261008_0052"
down_revision: str | None = "20260928_0051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "admin_users",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("username", sa.String(40), nullable=False),
        sa.Column("display_name", sa.String(40), nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.Column("password_hash", sa.String(200), nullable=False),
        sa.Column("active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("failed_login_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("username", name="uq_admin_users_username"),
        sa.CheckConstraint("username ~ '^[a-z][a-z0-9_.-]{1,39}$'", name="ck_admin_users_username"),
        sa.CheckConstraint("role IN ('owner', 'editor')", name="ck_admin_users_role"),
        sa.CheckConstraint("failed_login_count >= 0", name="ck_admin_users_failed_login_count"),
        sa.CheckConstraint("password_hash LIKE 'scrypt$%'", name="ck_admin_users_password_hash"),
    )
    op.create_table(
        "admin_sessions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["admin_users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("token_hash", name="uq_admin_sessions_token_hash"),
        sa.CheckConstraint("token_hash ~ '^[0-9a-f]{64}$'", name="ck_admin_sessions_token_hash"),
        sa.CheckConstraint("expires_at > created_at", name="ck_admin_sessions_expiry"),
    )
    op.create_index("ix_admin_sessions_user_id", "admin_sessions", ["user_id"])
    op.create_table(
        "admin_audit_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("username", sa.String(40), nullable=False),
        sa.Column("action", sa.String(60), nullable=False),
        sa.Column("target_type", sa.String(40), nullable=True),
        sa.Column("target_id", sa.String(80), nullable=True),
        sa.Column(
            "detail",
            postgresql.JSONB(),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["admin_users.id"], ondelete="SET NULL"),
        sa.CheckConstraint(
            "action ~ '^[a-z][a-z0-9_.]{0,59}$'", name="ck_admin_audit_events_action"
        ),
        sa.CheckConstraint(
            "jsonb_typeof(detail) = 'object'", name="ck_admin_audit_events_detail_object"
        ),
    )
    op.create_index("ix_admin_audit_events_occurred_at", "admin_audit_events", ["occurred_at"])


def downgrade() -> None:
    # The audit log is the record of operator changes; never drop it silently.
    op.execute(
        sa.text(
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM admin_audit_events) THEN "
            "RAISE EXCEPTION 'refusing to discard the admin audit log'; "
            "END IF; END $$"
        )
    )
    op.drop_index("ix_admin_audit_events_occurred_at", table_name="admin_audit_events")
    op.drop_table("admin_audit_events")
    op.drop_index("ix_admin_sessions_user_id", table_name="admin_sessions")
    op.drop_table("admin_sessions")
    op.drop_table("admin_users")
