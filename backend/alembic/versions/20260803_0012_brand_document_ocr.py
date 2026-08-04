"""Add bounded extraction and OCR metadata to brand document versions.

Revision ID: 20260803_0012
Revises: 20260803_0011
Create Date: 2026-08-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260803_0012"
down_revision: str | None = "20260803_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "brand_document_versions",
        sa.Column("extraction_method", sa.String(length=20), nullable=True),
    )
    op.add_column(
        "brand_document_versions",
        sa.Column("ocr_provider", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "brand_document_versions",
        sa.Column("ocr_model", sa.String(length=120), nullable=True),
    )
    op.add_column(
        "brand_document_versions",
        sa.Column("ocr_request_fingerprint", sa.String(length=64), nullable=True),
    )
    op.add_column(
        "brand_document_versions",
        sa.Column("ocr_provider_request_id", sa.String(length=200), nullable=True),
    )
    op.add_column(
        "brand_document_versions",
        sa.Column("ocr_page_count", sa.Integer(), nullable=True),
    )
    op.add_column(
        "brand_document_versions",
        sa.Column("ocr_prompt_tokens", sa.Integer(), nullable=True),
    )
    op.add_column(
        "brand_document_versions",
        sa.Column("ocr_completion_tokens", sa.Integer(), nullable=True),
    )
    op.add_column(
        "brand_document_versions",
        sa.Column("ocr_latency_ms", sa.Integer(), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE brand_document_versions "
            "SET extraction_method = 'local' WHERE extraction_method IS NULL"
        )
    )
    op.create_check_constraint(
        "ck_brand_document_versions_extraction_method",
        "brand_document_versions",
        "extraction_method IS NULL OR extraction_method IN ('local', 'ocr')",
    )
    op.create_check_constraint(
        "ck_brand_document_versions_ocr_page_count",
        "brand_document_versions",
        "ocr_page_count IS NULL OR ocr_page_count BETWEEN 1 AND 100",
    )
    op.create_check_constraint(
        "ck_brand_document_versions_ocr_prompt_tokens",
        "brand_document_versions",
        "ocr_prompt_tokens IS NULL OR ocr_prompt_tokens BETWEEN 0 AND 10000000",
    )
    op.create_check_constraint(
        "ck_brand_document_versions_ocr_completion_tokens",
        "brand_document_versions",
        "ocr_completion_tokens IS NULL OR ocr_completion_tokens BETWEEN 0 AND 10000000",
    )
    op.create_check_constraint(
        "ck_brand_document_versions_ocr_latency_ms",
        "brand_document_versions",
        "ocr_latency_ms IS NULL OR ocr_latency_ms BETWEEN 0 AND 3600000",
    )
    op.create_check_constraint(
        "ck_brand_document_versions_ocr_metadata",
        "brand_document_versions",
        "extraction_method IS NULL OR extraction_method = 'local' OR "
        "(ocr_provider IS NOT NULL AND ocr_model IS NOT NULL AND "
        "ocr_request_fingerprint IS NOT NULL AND ocr_page_count IS NOT NULL)",
    )
    op.create_index(
        "ix_brand_document_versions_extraction",
        "brand_document_versions",
        ["extraction_method", "ocr_provider", "ocr_model"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_brand_document_versions_extraction", table_name="brand_document_versions")
    op.drop_constraint(
        "ck_brand_document_versions_ocr_metadata",
        "brand_document_versions",
        type_="check",
    )
    op.drop_constraint(
        "ck_brand_document_versions_ocr_latency_ms",
        "brand_document_versions",
        type_="check",
    )
    op.drop_constraint(
        "ck_brand_document_versions_ocr_completion_tokens",
        "brand_document_versions",
        type_="check",
    )
    op.drop_constraint(
        "ck_brand_document_versions_ocr_prompt_tokens",
        "brand_document_versions",
        type_="check",
    )
    op.drop_constraint(
        "ck_brand_document_versions_ocr_page_count",
        "brand_document_versions",
        type_="check",
    )
    op.drop_constraint(
        "ck_brand_document_versions_extraction_method",
        "brand_document_versions",
        type_="check",
    )
    for name in (
        "ocr_latency_ms",
        "ocr_completion_tokens",
        "ocr_prompt_tokens",
        "ocr_page_count",
        "ocr_provider_request_id",
        "ocr_request_fingerprint",
        "ocr_model",
        "ocr_provider",
        "extraction_method",
    ):
        op.drop_column("brand_document_versions", name)
