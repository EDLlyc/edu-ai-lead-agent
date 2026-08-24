"""Allow immutable v4 article packages with persisted multimodal media selection."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260823_0029"
down_revision: str | None = "20260823_0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_official_account_article_versions_version",
        "official_account_article_versions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_official_account_article_versions_version",
        "official_account_article_versions",
        "version IN (1, 2, 3, 4)",
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM official_account_article_versions WHERE version = 4) "
            "THEN RAISE EXCEPTION "
            "'cannot downgrade official-account multimodal article artifacts'; "
            "END IF; END $$"
        )
    )
    op.drop_constraint(
        "ck_official_account_article_versions_version",
        "official_account_article_versions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_official_account_article_versions_version",
        "official_account_article_versions",
        "version IN (1, 2, 3)",
    )
