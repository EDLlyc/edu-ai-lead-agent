"""Add immutable editorial review for local official-account article runs."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260823_0028"
down_revision: str | None = "20260822_0027"
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
        "version IN (1, 2, 3)",
    )
    op.create_table(
        "official_account_manual_reviews",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("decision", sa.String(length=20), nullable=False),
        sa.Column("reviewer_label", sa.String(length=80), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column(
            "reviewed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "decision IN ('approved', 'rejected')",
            name=op.f("ck_official_account_manual_reviews_decision"),
        ),
        sa.CheckConstraint(
            "char_length(reviewer_label) BETWEEN 1 AND 80",
            name=op.f("ck_official_account_manual_reviews_reviewer"),
        ),
        sa.CheckConstraint(
            "note IS NULL OR char_length(note) BETWEEN 1 AND 2000",
            name=op.f("ck_official_account_manual_reviews_note"),
        ),
        sa.CheckConstraint(
            "request_fingerprint ~ '^[0-9a-f]{64}$'",
            name=op.f("ck_official_account_manual_reviews_fingerprint"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["official_account_article_runs.id"],
            name="fk_official_account_manual_reviews_run_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_official_account_manual_reviews"),
        sa.UniqueConstraint("run_id", name="uq_official_account_manual_reviews_run"),
        sa.UniqueConstraint(
            "request_fingerprint",
            name="uq_official_account_manual_reviews_request",
        ),
    )
    op.create_index(
        "ix_official_account_manual_reviews_reviewed",
        "official_account_manual_reviews",
        ["reviewed_at"],
        unique=False,
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM official_account_manual_reviews) "
            "OR EXISTS (SELECT 1 FROM official_account_article_versions WHERE version = 3) "
            "THEN RAISE EXCEPTION "
            "'cannot downgrade official-account editorial artifacts'; END IF; END $$"
        )
    )
    op.drop_index(
        "ix_official_account_manual_reviews_reviewed",
        table_name="official_account_manual_reviews",
    )
    op.drop_table("official_account_manual_reviews")
    op.drop_constraint(
        "ck_official_account_article_versions_version",
        "official_account_article_versions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_official_account_article_versions_version",
        "official_account_article_versions",
        "version IN (1, 2)",
    )
