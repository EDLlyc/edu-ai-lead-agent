"""Add strictly anonymous daily IP search funnel aggregates."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260831_0038"
down_revision: str | None = "20260827_0037"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ip_asset_search_aggregates",
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("search_version", sa.String(length=48), nullable=False),
        sa.Column("mode", sa.String(length=32), nullable=False),
        sa.Column("event_kind", sa.String(length=40), nullable=False),
        sa.Column("count", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("count >= 0", name="ck_ip_asset_search_aggregates_count"),
        sa.CheckConstraint(
            "search_version IN ('ip-asset-hybrid-v2', 'ip-asset-hybrid-v3-rrf')",
            name="ck_ip_asset_search_aggregates_version",
        ),
        sa.CheckConstraint(
            "mode IN ('semantic', 'degraded_metadata')",
            name="ck_ip_asset_search_aggregates_mode",
        ),
        sa.CheckConstraint(
            "event_kind IN ('search_results', 'zero_results', "
            "'preview_from_search', 'favorite_from_search', 'download_from_search')",
            name="ck_ip_asset_search_aggregates_event_kind",
        ),
        sa.PrimaryKeyConstraint(
            "business_date",
            "search_version",
            "mode",
            "event_kind",
            name="pk_ip_asset_search_aggregates",
        ),
    )
    op.create_index(
        "ix_ip_asset_search_aggregates_date",
        "ip_asset_search_aggregates",
        ["business_date"],
        unique=False,
    )


def downgrade() -> None:
    # This intentionally discards anonymous analytics counters only. It cannot affect assets,
    # profiles, downloads, favorites, generations, or embeddings.
    op.drop_index(
        "ix_ip_asset_search_aggregates_date",
        table_name="ip_asset_search_aggregates",
    )
    op.drop_table("ip_asset_search_aggregates")
