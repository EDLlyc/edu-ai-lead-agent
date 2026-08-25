"""Add local profiles, personal IP assets, favorites, references, and rankings."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260824_0035"
down_revision: str | None = "20260824_0034"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ip_assets",
        sa.Column("shared_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.execute(sa.text("UPDATE ip_assets SET shared_at = created_at"))
    op.create_index(
        "ix_ip_assets_shared_gallery",
        "ip_assets",
        ["shared_at", "created_at", "id"],
    )

    op.create_table(
        "ip_asset_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("profile_ref", sa.String(24), nullable=False),
        sa.Column("token_digest", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(80), nullable=False),
        sa.Column("department", sa.String(80), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ip_asset_profiles"),
        sa.CheckConstraint("profile_ref ~ '^ipp_[a-f0-9]{20}$'", name="ck_ip_asset_profiles_ref"),
        sa.CheckConstraint(
            "token_digest ~ '^[0-9a-f]{64}$'", name="ck_ip_asset_profiles_token_digest"
        ),
        sa.CheckConstraint(
            "char_length(display_name) BETWEEN 1 AND 80",
            name="ck_ip_asset_profiles_display_name",
        ),
        sa.CheckConstraint(
            "char_length(department) BETWEEN 1 AND 80",
            name="ck_ip_asset_profiles_department",
        ),
        sa.UniqueConstraint("profile_ref", name="uq_ip_asset_profiles_ref"),
        sa.UniqueConstraint("token_digest", name="uq_ip_asset_profiles_token_digest"),
    )

    op.add_column(
        "ip_asset_generation_jobs",
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_ip_asset_generation_jobs_profile_id",
        "ip_asset_generation_jobs",
        "ip_asset_profiles",
        ["profile_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        "uq_ip_asset_generation_jobs_idempotency",
        "ip_asset_generation_jobs",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_ip_asset_generation_jobs_profile_idempotency",
        "ip_asset_generation_jobs",
        ["profile_id", "idempotency_key"],
    )
    op.create_index(
        "uq_ip_asset_generation_jobs_legacy_idempotency",
        "ip_asset_generation_jobs",
        ["idempotency_key"],
        unique=True,
        postgresql_where=sa.text("profile_id IS NULL"),
    )

    op.create_table(
        "ip_asset_generation_references",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ordinal", sa.SmallInteger(), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ip_asset_generation_references"),
        sa.ForeignKeyConstraint(
            ["job_id"],
            ["ip_asset_generation_jobs.id"],
            name="fk_ip_asset_generation_references_job_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["ip_assets.id"],
            name="fk_ip_asset_generation_references_asset_id",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "ordinal BETWEEN 0 AND 2", name="ck_ip_asset_generation_references_ordinal"
        ),
        sa.CheckConstraint(
            "source_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_ip_asset_generation_references_sha256",
        ),
        sa.UniqueConstraint("job_id", "ordinal", name="uq_ip_asset_generation_references_ordinal"),
        sa.UniqueConstraint("job_id", "asset_id", name="uq_ip_asset_generation_references_asset"),
        sa.Index("ix_ip_asset_generation_references_job", "job_id", "ordinal"),
    )
    op.execute(
        sa.text(
            "INSERT INTO ip_asset_generation_references "
            "(id, job_id, ordinal, asset_id, source_sha256) "
            "SELECT md5(jobs.id::text || '|ordinal-0')::uuid, jobs.id, 0, "
            "assets.id, assets.blob_sha256 "
            "FROM ip_asset_generation_jobs AS jobs "
            "JOIN ip_assets AS assets ON assets.id = jobs.reference_asset_id "
            "WHERE jobs.reference_asset_id IS NOT NULL"
        )
    )

    op.create_table(
        "ip_asset_profile_memberships",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("generation_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ip_asset_profile_memberships"),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["ip_asset_profiles.id"],
            name="fk_ip_asset_profile_memberships_profile_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["ip_assets.id"],
            name="fk_ip_asset_profile_memberships_asset_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["generation_job_id"],
            ["ip_asset_generation_jobs.id"],
            name="fk_ip_asset_profile_memberships_generation_job_id",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "source IN ('generated', 'uploaded')",
            name="ck_ip_asset_profile_memberships_source",
        ),
        sa.CheckConstraint(
            "(source = 'generated' AND generation_job_id IS NOT NULL) OR "
            "(source = 'uploaded' AND generation_job_id IS NULL)",
            name="ck_ip_asset_profile_memberships_generation_shape",
        ),
        sa.UniqueConstraint(
            "profile_id",
            "asset_id",
            "source",
            name="uq_ip_asset_profile_memberships_source",
        ),
        sa.Index(
            "ix_ip_asset_profile_memberships_profile",
            "profile_id",
            "created_at",
            "asset_id",
        ),
    )

    op.create_table(
        "ip_asset_favorites",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ip_asset_favorites"),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["ip_asset_profiles.id"],
            name="fk_ip_asset_favorites_profile_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["ip_assets.id"],
            name="fk_ip_asset_favorites_asset_id",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("profile_id", "asset_id", name="uq_ip_asset_favorites_asset"),
        sa.Index("ix_ip_asset_favorites_profile", "profile_id", "created_at", "asset_id"),
    )

    op.create_table(
        "ip_asset_download_daily",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("asset_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("download_count", sa.BigInteger(), nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ip_asset_download_daily"),
        sa.ForeignKeyConstraint(
            ["asset_id"],
            ["ip_assets.id"],
            name="fk_ip_asset_download_daily_asset_id",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint("download_count > 0", name="ck_ip_asset_download_daily_count"),
        sa.UniqueConstraint(
            "asset_id", "business_date", name="uq_ip_asset_download_daily_asset_date"
        ),
        sa.Index("ix_ip_asset_download_daily_date", "business_date", "asset_id"),
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM ip_asset_profiles) "
            "OR EXISTS (SELECT 1 FROM ip_asset_download_daily) "
            "OR EXISTS (SELECT 1 FROM ip_assets WHERE shared_at IS NULL) "
            "OR EXISTS (SELECT 1 FROM ip_asset_generation_jobs WHERE profile_id IS NOT NULL) "
            "OR EXISTS ("
            "SELECT 1 FROM ip_asset_generation_references AS refs "
            "JOIN ip_asset_generation_jobs AS jobs ON jobs.id = refs.job_id "
            "WHERE refs.ordinal <> 0 "
            "OR jobs.reference_asset_id IS DISTINCT FROM refs.asset_id"
            ") THEN "
            "RAISE EXCEPTION 'cannot downgrade while IP asset personal-library data exists'; "
            "END IF; END $$"
        )
    )
    op.execute(
        sa.text(
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM ip_asset_generation_jobs "
            "GROUP BY idempotency_key HAVING count(*) > 1) THEN "
            "RAISE EXCEPTION 'cannot restore global generation idempotency uniqueness'; "
            "END IF; END $$"
        )
    )
    op.drop_table("ip_asset_download_daily")
    op.drop_table("ip_asset_favorites")
    op.drop_table("ip_asset_profile_memberships")
    op.drop_table("ip_asset_generation_references")
    op.drop_index(
        "uq_ip_asset_generation_jobs_legacy_idempotency",
        table_name="ip_asset_generation_jobs",
    )
    op.drop_constraint(
        "uq_ip_asset_generation_jobs_profile_idempotency",
        "ip_asset_generation_jobs",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_ip_asset_generation_jobs_idempotency",
        "ip_asset_generation_jobs",
        ["idempotency_key"],
    )
    op.drop_constraint(
        "fk_ip_asset_generation_jobs_profile_id",
        "ip_asset_generation_jobs",
        type_="foreignkey",
    )
    op.drop_column("ip_asset_generation_jobs", "profile_id")
    op.drop_table("ip_asset_profiles")
    op.drop_index("ix_ip_assets_shared_gallery", table_name="ip_assets")
    op.drop_column("ip_assets", "shared_at")
