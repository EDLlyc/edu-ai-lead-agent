"""Operator-managed news sources: ownership, sticky toggles, archive, generic connector config."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261008_0053"
down_revision: str | None = "20261008_0052"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "sources",
        sa.Column("managed_by", sa.String(16), server_default=sa.text("'seed'"), nullable=False),
    )
    op.add_column(
        "sources",
        sa.Column(
            "enabled_set_by", sa.String(16), server_default=sa.text("'seed'"), nullable=False
        ),
    )
    op.add_column("sources", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))
    op.create_check_constraint(
        "ck_sources_managed_by", "sources", "managed_by IN ('seed', 'operator')"
    )
    op.create_check_constraint(
        "ck_sources_enabled_set_by", "sources", "enabled_set_by IN ('seed', 'operator')"
    )
    op.create_check_constraint(
        "ck_sources_archive_shape",
        "sources",
        "archived_at IS NULL OR (enabled = false AND managed_by = 'operator')",
    )
    op.add_column(
        "source_versions",
        sa.Column("connector_config", postgresql.JSONB(), nullable=True),
    )
    op.create_check_constraint(
        "ck_source_versions_connector_config",
        "source_versions",
        "connector_config IS NULL OR jsonb_typeof(connector_config) = 'object'",
    )


def downgrade() -> None:
    # Operator sources own acquisition history; never drop them silently.
    op.execute(
        sa.text(
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM sources WHERE managed_by <> 'seed') "
            "OR EXISTS (SELECT 1 FROM source_versions WHERE connector_config IS NOT NULL) THEN "
            "RAISE EXCEPTION 'refusing to discard operator-managed sources'; "
            "END IF; END $$"
        )
    )
    op.drop_constraint("ck_source_versions_connector_config", "source_versions", type_="check")
    op.drop_column("source_versions", "connector_config")
    op.drop_constraint("ck_sources_archive_shape", "sources", type_="check")
    op.drop_constraint("ck_sources_enabled_set_by", "sources", type_="check")
    op.drop_constraint("ck_sources_managed_by", "sources", type_="check")
    op.drop_column("sources", "archived_at")
    op.drop_column("sources", "enabled_set_by")
    op.drop_column("sources", "managed_by")
