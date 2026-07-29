"""Add title relevance provenance and filtered counters.

Revision ID: 20260729_0003
Revises: 20260728_0002
Create Date: 2026-07-29
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260729_0003"
down_revision: str | None = "20260728_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "source_versions",
        sa.Column("relevance_rule_version", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "evidence_candidates",
        sa.Column("relevance_rule_version", sa.String(length=40), nullable=True),
    )
    op.add_column(
        "acquisition_runs",
        sa.Column("filtered_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "acquisition_jobs",
        sa.Column("filtered_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )


def downgrade() -> None:
    # Never leave a relevance-enabled source version active after removing the
    # column that tells the old worker to apply its title gate. Prefer the most
    # recent legacy version; a source with no legacy version becomes inactive
    # until the previous application seed command creates one.
    op.execute(
        sa.text(
            """
            UPDATE sources AS source
            SET active_version_id = (
                SELECT legacy.id
                FROM source_versions AS legacy
                WHERE legacy.source_id = source.id
                  AND legacy.relevance_rule_version IS NULL
                ORDER BY legacy.version DESC
                LIMIT 1
            )
            WHERE EXISTS (
                SELECT 1
                FROM source_versions AS active
                WHERE active.id = source.active_version_id
                  AND active.relevance_rule_version IS NOT NULL
            )
            """
        )
    )
    op.drop_column("acquisition_jobs", "filtered_count")
    op.drop_column("acquisition_runs", "filtered_count")
    op.drop_column("evidence_candidates", "relevance_rule_version")
    op.drop_column("source_versions", "relevance_rule_version")
