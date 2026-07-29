"""Preserve per-response provenance for shared snapshot objects.

Revision ID: 20260728_0002
Revises: 20260728_0001
Create Date: 2026-07-28
"""

import hashlib
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260728_0002"
down_revision: str | None = "20260728_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _provenance_key(
    source_version_id: object,
    kind: object,
    original_url: object,
    final_url: object,
    sha256: object,
) -> str:
    normalized = "\x1f".join(
        str(part) for part in (source_version_id, kind, original_url, final_url, sha256)
    )
    return hashlib.sha256(normalized.encode()).hexdigest()


def upgrade() -> None:
    op.add_column(
        "source_snapshots", sa.Column("provenance_key", sa.String(length=64), nullable=True)
    )
    snapshots = sa.table(
        "source_snapshots",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("source_version_id", postgresql.UUID(as_uuid=True)),
        sa.column("kind", sa.String()),
        sa.column("original_url", sa.Text()),
        sa.column("final_url", sa.Text()),
        sa.column("sha256", sa.String()),
        sa.column("provenance_key", sa.String()),
    )
    connection = op.get_bind()
    rows = connection.execute(
        sa.select(
            snapshots.c.id,
            snapshots.c.source_version_id,
            snapshots.c.kind,
            snapshots.c.original_url,
            snapshots.c.final_url,
            snapshots.c.sha256,
        )
    ).mappings()
    for row in rows:
        connection.execute(
            snapshots.update()
            .where(snapshots.c.id == row["id"])
            .values(
                provenance_key=_provenance_key(
                    row["source_version_id"],
                    row["kind"],
                    row["original_url"],
                    row["final_url"],
                    row["sha256"],
                )
            )
        )
    op.alter_column("source_snapshots", "provenance_key", nullable=False)
    op.drop_constraint("uq_source_snapshots_object", "source_snapshots", type_="unique")
    op.drop_constraint("uq_source_snapshots_content_identity", "source_snapshots", type_="unique")
    op.create_unique_constraint(
        "uq_source_snapshots_provenance_key", "source_snapshots", ["provenance_key"]
    )
    op.create_index("ix_source_snapshots_object", "source_snapshots", ["bucket", "object_key"])


def downgrade() -> None:
    connection = op.get_bind()
    duplicates = connection.scalar(
        sa.text(
            "SELECT 1 FROM source_snapshots GROUP BY bucket, object_key HAVING count(*) > 1 LIMIT 1"
        )
    )
    if duplicates is not None:
        raise RuntimeError(
            "cannot downgrade snapshot provenance while multiple metadata rows share an object"
        )
    op.drop_index("ix_source_snapshots_object", table_name="source_snapshots")
    op.drop_constraint("uq_source_snapshots_provenance_key", "source_snapshots", type_="unique")
    op.create_unique_constraint(
        "uq_source_snapshots_object", "source_snapshots", ["bucket", "object_key"]
    )
    op.create_unique_constraint(
        "uq_source_snapshots_content_identity",
        "source_snapshots",
        ["source_version_id", "sha256", "kind"],
    )
    op.drop_column("source_snapshots", "provenance_key")
