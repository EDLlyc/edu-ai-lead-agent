"""Add durable image-package worker reservations and safe package snapshots."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260803_0014"
down_revision: str | None = "20260803_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_PRIVATE_STORAGE_DEFAULT = sa.text(
    '\'{"access": "private", "immutable": true, "content_addressed": true}\'::jsonb'
)


def upgrade() -> None:
    op.add_column(
        "image_artifacts",
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.add_column("image_artifacts", sa.Column("lease_owner", sa.String(length=200), nullable=True))
    op.add_column(
        "image_artifacts",
        sa.Column("lease_token", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "image_artifacts",
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "image_artifacts",
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "image_artifacts",
        sa.Column(
            "storage_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=_PRIVATE_STORAGE_DEFAULT,
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_image_artifacts_storage_metadata_object",
        "image_artifacts",
        "jsonb_typeof(storage_metadata) = 'object'",
    )
    op.create_index(
        "ix_image_artifacts_claim",
        "image_artifacts",
        ["status", "available_at", "lease_expires_at"],
    )

    op.add_column(
        "material_packages",
        sa.Column(
            "brand_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "material_packages",
        sa.Column(
            "validation_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "material_packages",
        sa.Column(
            "version_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
    )
    op.create_check_constraint(
        "ck_material_packages_brand_snapshot_array",
        "material_packages",
        "jsonb_typeof(brand_snapshot) = 'array'",
    )
    op.create_check_constraint(
        "ck_material_packages_validation_snapshot_object",
        "material_packages",
        "jsonb_typeof(validation_snapshot) = 'object'",
    )
    op.create_check_constraint(
        "ck_material_packages_version_snapshot_object",
        "material_packages",
        "jsonb_typeof(version_snapshot) = 'object'",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_material_packages_version_snapshot_object", "material_packages", type_="check"
    )
    op.drop_constraint(
        "ck_material_packages_validation_snapshot_object", "material_packages", type_="check"
    )
    op.drop_constraint(
        "ck_material_packages_brand_snapshot_array", "material_packages", type_="check"
    )
    op.drop_column("material_packages", "version_snapshot")
    op.drop_column("material_packages", "validation_snapshot")
    op.drop_column("material_packages", "brand_snapshot")
    op.drop_index("ix_image_artifacts_claim", table_name="image_artifacts")
    op.drop_constraint(
        "ck_image_artifacts_storage_metadata_object", "image_artifacts", type_="check"
    )
    op.drop_column("image_artifacts", "storage_metadata")
    op.drop_column("image_artifacts", "heartbeat_at")
    op.drop_column("image_artifacts", "lease_expires_at")
    op.drop_column("image_artifacts", "lease_token")
    op.drop_column("image_artifacts", "lease_owner")
    op.drop_column("image_artifacts", "available_at")
