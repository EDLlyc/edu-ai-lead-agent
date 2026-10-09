"""Per-account 排版模板 (layout colour scheme) for drafts the pipeline uploads."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261009_0057"
down_revision: str | None = "20261009_0056"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "wechat_accounts",
        sa.Column(
            "layout_template_id",
            sa.String(40),
            nullable=False,
            server_default="xiaosai-blue",
        ),
    )
    op.create_check_constraint(
        "ck_wechat_accounts_layout_template",
        "wechat_accounts",
        "layout_template_id ~ '^[a-z0-9-]{1,40}$'",
    )


def downgrade() -> None:
    # Dropping the choice only returns every account to the default blue scheme.
    op.drop_constraint("ck_wechat_accounts_layout_template", "wechat_accounts", type_="check")
    op.drop_column("wechat_accounts", "layout_template_id")
