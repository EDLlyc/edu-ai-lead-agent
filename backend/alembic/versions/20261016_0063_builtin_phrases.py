"""Maintainable built-in phrase lists (营销承诺 and 焦虑话术)."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261016_0063"
down_revision: str | None = "20261015_0062"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "builtin_phrase_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("marketing_terms", postgresql.JSONB(), nullable=False),
        sa.Column("anxiety_terms", postgresql.JSONB(), nullable=False),
        sa.Column("note", sa.String(length=200), nullable=True),
        sa.Column("created_by", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_builtin_phrase_versions"),
        sa.UniqueConstraint("version", name="uq_builtin_phrase_versions_version"),
        sa.CheckConstraint("version > 0", name="ck_builtin_phrase_versions_version"),
        sa.CheckConstraint(
            "jsonb_typeof(marketing_terms) = 'array' AND jsonb_typeof(anxiety_terms) = 'array'",
            name="ck_builtin_phrase_versions_arrays",
        ),
        sa.CheckConstraint(
            "jsonb_array_length(marketing_terms) <= 200 "
            "AND jsonb_array_length(anxiety_terms) <= 200",
            name="ck_builtin_phrase_versions_sizes",
        ),
    )
    op.add_column(
        "content_slot_runs",
        sa.Column("builtin_phrase_version_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_content_slot_runs_builtin_phrase_version_id",
        "content_slot_runs",
        "builtin_phrase_versions",
        ["builtin_phrase_version_id"],
        ["id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_content_slot_runs_builtin_phrase_version_id", "content_slot_runs", type_="foreignkey"
    )
    op.drop_column("content_slot_runs", "builtin_phrase_version_id")
    op.drop_table("builtin_phrase_versions")
