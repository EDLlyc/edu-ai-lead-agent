"""Separate approved source hashes from normalized visual embedding inputs."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260821_0025"
down_revision: str | None = "20260821_0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_V1_POLICY = "brand-visual-embedding-input-v1"


def upgrade() -> None:
    connection = op.get_bind()
    non_v1_rows = connection.execute(
        sa.text(
            "SELECT "
            "(SELECT count(*) FROM brand_visual_index_jobs "
            " WHERE input_policy_version <> :v1_policy) + "
            "(SELECT count(*) FROM brand_visual_asset_embeddings "
            " WHERE input_policy_version <> :v1_policy)"
        ),
        {"v1_policy": _V1_POLICY},
    ).scalar_one()
    if int(non_v1_rows) != 0:
        raise RuntimeError("only historical visual v1 rows can be normalized during upgrade")

    for table_name in ("brand_visual_index_jobs", "brand_visual_asset_embeddings"):
        op.add_column(
            table_name,
            sa.Column("embedding_input_sha256", sa.String(length=64), nullable=True),
        )
        op.execute(
            sa.text(
                f"UPDATE {table_name} "
                "SET embedding_input_sha256 = asset_checksum "
                "WHERE embedding_input_sha256 IS NULL "
                "AND input_policy_version = :v1_policy"
            ).bindparams(v1_policy=_V1_POLICY)
        )
        op.alter_column(
            table_name,
            "embedding_input_sha256",
            existing_type=sa.String(length=64),
            nullable=False,
        )

    op.drop_index("ix_brand_visual_index_jobs_scope", table_name="brand_visual_index_jobs")
    op.create_index(
        "ix_brand_visual_index_jobs_scope",
        "brand_visual_index_jobs",
        [
            "catalog_version",
            "provider",
            "model",
            "input_policy_version",
            "embedding_input_sha256",
        ],
    )
    op.drop_index(
        "ix_brand_visual_asset_embeddings_scope",
        table_name="brand_visual_asset_embeddings",
    )
    op.create_index(
        "ix_brand_visual_asset_embeddings_scope",
        "brand_visual_asset_embeddings",
        [
            "catalog_version",
            "provider",
            "model",
            "input_policy_version",
            "embedding_input_sha256",
        ],
    )


def downgrade() -> None:
    connection = op.get_bind()
    v2_rows = connection.execute(
        sa.text(
            "SELECT "
            "(SELECT count(*) FROM brand_visual_index_jobs "
            " WHERE input_policy_version <> :v1_policy) + "
            "(SELECT count(*) FROM brand_visual_asset_embeddings "
            " WHERE input_policy_version <> :v1_policy)"
        ),
        {"v1_policy": _V1_POLICY},
    ).scalar_one()
    if int(v2_rows) != 0:
        raise RuntimeError("normalized visual embedding rows must be removed before downgrade")

    op.drop_index(
        "ix_brand_visual_asset_embeddings_scope",
        table_name="brand_visual_asset_embeddings",
    )
    op.create_index(
        "ix_brand_visual_asset_embeddings_scope",
        "brand_visual_asset_embeddings",
        ["catalog_version", "provider", "model", "input_policy_version"],
    )
    op.drop_index("ix_brand_visual_index_jobs_scope", table_name="brand_visual_index_jobs")
    op.create_index(
        "ix_brand_visual_index_jobs_scope",
        "brand_visual_index_jobs",
        ["catalog_version", "provider", "model", "input_policy_version"],
    )
    op.drop_column("brand_visual_asset_embeddings", "embedding_input_sha256")
    op.drop_column("brand_visual_index_jobs", "embedding_input_sha256")
