"""WeChat article and account reading statistics for the 运营后台 数据 page."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261009_0056"
down_revision: str | None = "20261009_0055"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("wechat_accounts", sa.Column("stats_synced_on", sa.Date(), nullable=True))
    op.add_column("wechat_accounts", sa.Column("stats_sync_error", sa.String(200), nullable=True))
    op.create_table(
        "wechat_article_stats",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("msgid", sa.String(64), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("publish_date", sa.Date(), nullable=False),
        sa.Column("stat_date", sa.Date(), nullable=False),
        sa.Column("read_user", sa.Integer(), nullable=False),
        sa.Column("share_user", sa.Integer(), nullable=False),
        sa.Column("collection_user", sa.Integer(), nullable=False),
        sa.Column("read_subscribe_user", sa.Integer(), nullable=False),
        sa.Column("read_delivery_rate", sa.Float(), nullable=True),
        sa.Column("read_finish_rate", sa.Float(), nullable=True),
        sa.Column("read_avg_activetime", sa.Float(), nullable=True),
        sa.Column("read_sources", postgresql.JSONB(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["account_id"], ["wechat_accounts.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("account_id", "msgid", name="uq_wechat_article_stats_account_msgid"),
    )
    op.create_index(
        "ix_wechat_article_stats_account_publish",
        "wechat_article_stats",
        ["account_id", "publish_date"],
    )
    op.create_table(
        "wechat_account_daily_stats",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ref_date", sa.Date(), nullable=False),
        sa.Column("read_user", sa.Integer(), nullable=False),
        sa.Column("share_user", sa.Integer(), nullable=False),
        sa.Column("like_user", sa.Integer(), nullable=False),
        sa.Column("zaikan_user", sa.Integer(), nullable=False),
        sa.Column("comment_count", sa.Integer(), nullable=False),
        sa.Column("collection_user", sa.Integer(), nullable=False),
        sa.Column("redirect_ori_page_user", sa.Integer(), nullable=False),
        sa.Column("send_page_count", sa.Integer(), nullable=False),
        sa.Column("read_sources", postgresql.JSONB(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["account_id"], ["wechat_accounts.id"], ondelete="RESTRICT"),
        sa.UniqueConstraint("account_id", "ref_date", name="uq_wechat_account_daily_stats_day"),
    )


def downgrade() -> None:
    # Statistics can be fetched again from WeChat (30 days back), so dropping them is safe.
    op.drop_table("wechat_account_daily_stats")
    op.drop_index("ix_wechat_article_stats_account_publish", table_name="wechat_article_stats")
    op.drop_table("wechat_article_stats")
    op.drop_column("wechat_accounts", "stats_sync_error")
    op.drop_column("wechat_accounts", "stats_synced_on")
