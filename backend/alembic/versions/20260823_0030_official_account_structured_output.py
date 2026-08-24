"""Allow immutable v5 article artifacts for structured-output v8 packages."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260823_0030"
down_revision: str | None = "20260823_0029"
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
        "version IN (1, 2, 3, 4, 5)",
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM official_account_article_versions WHERE version = 5) "
            "THEN RAISE EXCEPTION "
            "'cannot downgrade official-account structured-output article artifacts'; "
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
        "version IN (1, 2, 3, 4)",
    )
