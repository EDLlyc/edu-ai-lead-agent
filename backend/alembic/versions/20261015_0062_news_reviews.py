"""Human opinions on the AI's news picks, recorded from the admin console."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20261015_0062"
down_revision: str | None = "20261010_0061"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "news_reviews",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("news_key", sa.String(length=40), nullable=False),
        sa.Column("decision", sa.String(length=10), nullable=False),
        sa.Column("note", sa.String(length=280), nullable=True),
        sa.Column("reviewer", sa.String(length=40), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("source_name", sa.String(length=120), nullable=True),
        sa.Column("ai_verdict", sa.String(length=10), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("slot", sa.String(length=10), nullable=False),
        sa.Column("source_url", sa.String(length=2048), nullable=True),
        sa.Column("snippet", sa.String(length=200), nullable=True),
        sa.Column("tier_label", sa.String(length=40), nullable=True),
        sa.Column("ai_score", sa.Float(), nullable=True),
        sa.Column("ai_threshold", sa.Float(), nullable=True),
        sa.Column("ai_rank", sa.Integer(), nullable=True),
        sa.Column("ai_reasons", postgresql.JSONB(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_news_reviews"),
        sa.CheckConstraint(
            "decision IN ('agree', 'include', 'exclude')", name="ck_news_reviews_decision"
        ),
        sa.CheckConstraint(
            "ai_verdict IN ('selected', 'rejected')", name="ck_news_reviews_verdict"
        ),
        sa.CheckConstraint("jsonb_typeof(ai_reasons) = 'array'", name="ck_news_reviews_reasons"),
    )
    op.create_index("ix_news_reviews_key", "news_reviews", ["news_key", "id"])
    op.create_index("ix_news_reviews_reviewed_at", "news_reviews", ["reviewed_at"])


def downgrade() -> None:
    # Opinions only; they are never an input to a run, score or delivery.
    op.drop_table("news_reviews")
