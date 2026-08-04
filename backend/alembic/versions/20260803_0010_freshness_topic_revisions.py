"""Add freshness policy metadata support and immutable same-day topic revisions.

Revision ID: 20260803_0010
Revises: 20260731_0009
Create Date: 2026-08-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260803_0010"
down_revision: str | None = "20260731_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "topic_selection_runs",
        sa.Column("revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
    )
    op.add_column(
        "topic_selection_runs",
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "topic_selection_runs",
        sa.Column("superseded_by_run_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "daily_topic_selections",
        sa.Column("revision", sa.Integer(), server_default=sa.text("1"), nullable=False),
    )
    op.add_column(
        "daily_topic_selections",
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "daily_topic_selections",
        sa.Column("superseded_by_run_id", postgresql.UUID(as_uuid=True), nullable=True),
    )

    op.drop_constraint(
        "uq_topic_selection_runs_business_key", "topic_selection_runs", type_="unique"
    )
    op.drop_constraint(
        "uq_daily_topic_selections_business_key", "daily_topic_selections", type_="unique"
    )
    op.create_unique_constraint(
        "uq_topic_selection_runs_business_revision",
        "topic_selection_runs",
        ["business_date", "timezone", "scoring_profile", "revision"],
    )
    op.create_check_constraint(
        "ck_topic_selection_runs_revision",
        "topic_selection_runs",
        "revision >= 1",
    )
    op.create_foreign_key(
        "fk_topic_selection_runs_superseded_by_run_id",
        "topic_selection_runs",
        "topic_selection_runs",
        ["superseded_by_run_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_daily_topic_selections_superseded_by_run_id",
        "daily_topic_selections",
        "topic_selection_runs",
        ["superseded_by_run_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "uq_daily_topic_selections_current_business_key",
        "daily_topic_selections",
        ["business_date", "timezone", "scoring_profile"],
        unique=True,
        postgresql_where=sa.text("superseded_at IS NULL"),
    )


def downgrade() -> None:
    bind = op.get_bind()
    revised_runs = bind.execute(
        sa.text("SELECT count(*) FROM topic_selection_runs WHERE revision > 1")
    ).scalar_one()
    if revised_runs:
        raise RuntimeError("cannot downgrade while same-day topic revisions exist")

    op.drop_index(
        "uq_daily_topic_selections_current_business_key",
        table_name="daily_topic_selections",
    )
    op.drop_constraint(
        "fk_daily_topic_selections_superseded_by_run_id",
        "daily_topic_selections",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_topic_selection_runs_superseded_by_run_id",
        "topic_selection_runs",
        type_="foreignkey",
    )
    op.drop_constraint("ck_topic_selection_runs_revision", "topic_selection_runs", type_="check")
    op.drop_constraint(
        "uq_topic_selection_runs_business_revision", "topic_selection_runs", type_="unique"
    )
    op.create_unique_constraint(
        "uq_topic_selection_runs_business_key",
        "topic_selection_runs",
        ["business_date", "timezone", "scoring_profile"],
    )
    op.create_unique_constraint(
        "uq_daily_topic_selections_business_key",
        "daily_topic_selections",
        ["business_date", "timezone", "scoring_profile"],
    )
    op.drop_column("daily_topic_selections", "superseded_by_run_id")
    op.drop_column("daily_topic_selections", "superseded_at")
    op.drop_column("daily_topic_selections", "revision")
    op.drop_column("topic_selection_runs", "superseded_by_run_id")
    op.drop_column("topic_selection_runs", "superseded_at")
    op.drop_column("topic_selection_runs", "revision")
