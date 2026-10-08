"""Operator keyword lists (关注词 / 屏蔽词 / 文案禁用词) and the version each slot run used."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261008_0054"
down_revision: str | None = "20261008_0053"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "operator_keyword_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("focus_terms", postgresql.JSONB(), nullable=False),
        sa.Column("block_terms", postgresql.JSONB(), nullable=False),
        sa.Column("copy_banned_terms", postgresql.JSONB(), nullable=False),
        sa.Column("note", sa.String(200), nullable=True),
        sa.Column("created_by", sa.String(40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("version", name="uq_operator_keyword_versions_version"),
        sa.CheckConstraint("version > 0", name="ck_operator_keyword_versions_version"),
        sa.CheckConstraint(
            "jsonb_typeof(focus_terms) = 'array' AND jsonb_typeof(block_terms) = 'array' "
            "AND jsonb_typeof(copy_banned_terms) = 'array'",
            name="ck_operator_keyword_versions_arrays",
        ),
        sa.CheckConstraint(
            "jsonb_array_length(focus_terms) <= 200 AND jsonb_array_length(block_terms) <= 200 "
            "AND jsonb_array_length(copy_banned_terms) <= 200",
            name="ck_operator_keyword_versions_sizes",
        ),
    )
    op.add_column(
        "content_slot_runs",
        sa.Column("operator_keyword_version_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_content_slot_runs_operator_keyword_version_id",
        "content_slot_runs",
        "operator_keyword_versions",
        ["operator_keyword_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    # Slot decisions record the keyword version they used; never drop that lineage silently.
    op.execute(
        sa.text(
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM operator_keyword_versions) THEN "
            "RAISE EXCEPTION 'refusing to discard operator keyword versions'; "
            "END IF; END $$"
        )
    )
    op.drop_constraint(
        "fk_content_slot_runs_operator_keyword_version_id", "content_slot_runs", type_="foreignkey"
    )
    op.drop_column("content_slot_runs", "operator_keyword_version_id")
    op.drop_table("operator_keyword_versions")
