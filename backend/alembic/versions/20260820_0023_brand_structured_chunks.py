"""Add structured brand sections and contextual chunk search input.

Downgrade intentionally discards section and chunk-classification metadata while preserving
the original chunk text and vectors.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260820_0023"
down_revision: str | None = "20260818_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "brand_sections",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("section_key", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("title", sa.String(length=240), nullable=False),
        sa.Column("text_hash", sa.String(length=64), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("source_page", sa.Integer(), nullable=True),
        sa.Column("question_number", sa.Integer(), nullable=True),
        sa.Column("question_text", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_brand_sections"),
        sa.ForeignKeyConstraint(
            ["version_id"],
            ["brand_document_versions.id"],
            name="fk_brand_sections_version_id",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("ordinal >= 0", name="ck_brand_sections_ordinal"),
        sa.CheckConstraint(
            "kind IN ('page', 'interview_qa', 'heading', 'generic')",
            name="ck_brand_sections_kind",
        ),
        sa.CheckConstraint(
            "char_start >= 0 AND char_end > char_start",
            name="ck_brand_sections_offsets",
        ),
        sa.CheckConstraint(
            "source_page IS NULL OR source_page >= 1",
            name="ck_brand_sections_source_page",
        ),
        sa.CheckConstraint(
            "question_number IS NULL OR question_number >= 1",
            name="ck_brand_sections_question_number",
        ),
        sa.CheckConstraint(
            "(kind = 'page') = (source_page IS NOT NULL)",
            name="ck_brand_sections_page_locator",
        ),
        sa.CheckConstraint(
            "(kind = 'interview_qa') = (question_number IS NOT NULL AND question_text IS NOT NULL)",
            name="ck_brand_sections_question_locator",
        ),
        sa.UniqueConstraint("section_key", name="uq_brand_sections_section_key"),
        sa.UniqueConstraint("version_id", "ordinal", name="uq_brand_sections_version_ordinal"),
        sa.UniqueConstraint("id", "version_id", name="uq_brand_sections_id_version"),
    )
    op.create_index(
        "ix_brand_sections_version_id",
        "brand_sections",
        ["version_id"],
        unique=False,
    )

    op.add_column(
        "brand_chunks",
        sa.Column("section_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column("brand_chunks", sa.Column("section_ordinal", sa.Integer(), nullable=True))
    op.add_column("brand_chunks", sa.Column("embedding_text", sa.Text(), nullable=True))
    op.add_column(
        "brand_chunks", sa.Column("embedding_input_hash", sa.String(length=64), nullable=True)
    )
    op.add_column(
        "brand_chunks",
        sa.Column(
            "content_type",
            sa.String(length=40),
            server_default=sa.text("'other'"),
            nullable=False,
        ),
    )
    op.add_column(
        "brand_chunks",
        sa.Column(
            "claim_scope",
            sa.String(length=40),
            server_default=sa.text("'brand_statement'"),
            nullable=False,
        ),
    )
    op.add_column(
        "brand_chunks",
        sa.Column(
            "verification_required",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )
    op.execute("UPDATE brand_chunks SET embedding_text = text, embedding_input_hash = text_hash")
    op.alter_column("brand_chunks", "embedding_text", nullable=False)
    op.alter_column("brand_chunks", "embedding_input_hash", nullable=False)
    op.create_check_constraint(
        "ck_brand_chunks_section_ordinal",
        "brand_chunks",
        "section_ordinal IS NULL OR section_ordinal >= 0",
    )
    op.create_check_constraint(
        "ck_brand_chunks_section_binding",
        "brand_chunks",
        "(section_id IS NULL) = (section_ordinal IS NULL)",
    )
    op.create_check_constraint(
        "ck_brand_chunks_content_type",
        "brand_chunks",
        "content_type IN ('positioning', 'product_profile', 'audience_insight', "
        "'safety_capability', 'digital_ip_values', 'tone_example', 'external_claim', "
        "'visual_guidance', 'other')",
    )
    op.create_check_constraint(
        "ck_brand_chunks_claim_scope",
        "brand_chunks",
        "claim_scope IN ('brand_statement', 'external_claim', 'normative_rule')",
    )
    op.create_check_constraint(
        "ck_brand_chunks_external_claim_verification",
        "brand_chunks",
        "claim_scope <> 'external_claim' OR verification_required = true",
    )
    op.create_unique_constraint(
        "uq_brand_chunks_section_ordinal",
        "brand_chunks",
        ["section_id", "section_ordinal"],
    )
    op.create_foreign_key(
        "fk_brand_chunks_section_version",
        "brand_chunks",
        "brand_sections",
        ["section_id", "version_id"],
        ["id", "version_id"],
        ondelete="CASCADE",
    )
    op.drop_index("ix_brand_chunks_search_vector", table_name="brand_chunks")
    op.drop_column("brand_chunks", "search_vector")
    op.add_column(
        "brand_chunks",
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('simple', embedding_text)", persisted=True),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_brand_chunks_search_vector",
        "brand_chunks",
        ["search_vector"],
        unique=False,
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_brand_chunks_search_vector", table_name="brand_chunks")
    op.drop_column("brand_chunks", "search_vector")
    op.add_column(
        "brand_chunks",
        sa.Column(
            "search_vector",
            postgresql.TSVECTOR(),
            sa.Computed("to_tsvector('simple', text)", persisted=True),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_brand_chunks_search_vector",
        "brand_chunks",
        ["search_vector"],
        unique=False,
        postgresql_using="gin",
    )
    op.drop_constraint("fk_brand_chunks_section_version", "brand_chunks", type_="foreignkey")
    op.drop_constraint("uq_brand_chunks_section_ordinal", "brand_chunks", type_="unique")
    for constraint_name in (
        "ck_brand_chunks_external_claim_verification",
        "ck_brand_chunks_claim_scope",
        "ck_brand_chunks_content_type",
        "ck_brand_chunks_section_binding",
        "ck_brand_chunks_section_ordinal",
    ):
        op.drop_constraint(constraint_name, "brand_chunks", type_="check")
    for column_name in (
        "verification_required",
        "claim_scope",
        "content_type",
        "embedding_input_hash",
        "embedding_text",
        "section_ordinal",
        "section_id",
    ):
        op.drop_column("brand_chunks", column_name)
    op.drop_index("ix_brand_sections_version_id", table_name="brand_sections")
    op.drop_table("brand_sections")
