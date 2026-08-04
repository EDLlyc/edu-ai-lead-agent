"""Allow retrying failed brand derivations without weakening idempotency.

Revision ID: 20260803_0013
Revises: 20260803_0012
Create Date: 2026-08-03
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260803_0013"
down_revision: str | None = "20260803_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DERIVATION_COLUMNS = [
    "document_id",
    "sha256",
    "metadata_fingerprint",
    "parser_version",
    "chunk_version",
    "embedding_input_version",
    "embedding_provider",
    "embedding_model",
]


def upgrade() -> None:
    op.drop_constraint(
        "uq_brand_document_versions_derivation",
        "brand_document_versions",
        type_="unique",
    )
    op.create_index(
        "uq_brand_document_versions_derivation",
        "brand_document_versions",
        _DERIVATION_COLUMNS,
        unique=True,
        postgresql_where=sa.text("status <> 'failed'"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_brand_document_versions_derivation",
        table_name="brand_document_versions",
    )
    op.create_unique_constraint(
        "uq_brand_document_versions_derivation",
        "brand_document_versions",
        _DERIVATION_COLUMNS,
    )
