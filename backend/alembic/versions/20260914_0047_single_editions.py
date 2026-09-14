"""Add date-scoped single editions and shared draft ownership, without history rewrites."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260914_0047"
down_revision: str | None = "20260914_0046"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "official_account_single_editions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("account_fingerprint", sa.String(64), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("timezone", sa.String(40), nullable=False),
        sa.Column("version", sa.String(80), nullable=False),
        *(
            sa.Column(name, sa.DateTime(timezone=True), nullable=False)
            for name in (
                "prepare_at",
                "deliver_at",
                "expires_at",
                "available_at",
                "created_at",
                "updated_at",
            )
        ),
        *(
            sa.Column(name, postgresql.JSONB(), nullable=False)
            for name in ("article_identity", "retry_policy", "stage_attempts")
        ),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("lease_token", postgresql.UUID(as_uuid=True)),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True)),
        sa.Column("selection_artifact", postgresql.JSONB()),
        sa.Column("prepared_artifact", postgresql.JSONB()),
        sa.Column(
            "material_package_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("material_packages.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("event_clusters.id", ondelete="RESTRICT"),
        ),
        sa.Column(
            "article_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("official_account_article_runs.id", ondelete="RESTRICT"),
        ),
        sa.Column("role", sa.String(32)),
        *(
            sa.Column(name, sa.String(64))
            for name in ("article_fingerprint", "content_fingerprint", "receipt_fingerprint")
        ),
        sa.Column("error_code", sa.String(80)),
        sa.UniqueConstraint(
            "account_fingerprint", "business_date", name="uq_single_edition_account_date"
        ),
        sa.CheckConstraint("account_fingerprint ~ '^[0-9a-f]{64}$'", name="single_edition_account"),
        sa.CheckConstraint(
            "timezone = 'Asia/Shanghai' AND EXTRACT(ISODOW FROM business_date) IN (1,3,5) "
            "AND prepare_at < deliver_at AND deliver_at < expires_at "
            "AND (deliver_at AT TIME ZONE 'Asia/Shanghai')::date = business_date "
            "AND (deliver_at AT TIME ZONE 'Asia/Shanghai')::time = '10:00'::time "
            "AND (expires_at AT TIME ZONE 'Asia/Shanghai')::date = business_date",
            name="single_edition_window",
        ),
        sa.CheckConstraint(
            "status IN ('admitted','generating','preparing','ready','delivering','delivered',"
            "'no_topic','failed','outcome_unknown','expired')",
            name="single_edition_status",
        ),
        sa.CheckConstraint(
            "(lease_token IS NULL) = (lease_expires_at IS NULL)", name="single_edition_lease"
        ),
        sa.CheckConstraint(
            "status NOT IN ('ready','delivering','delivered') OR "
            "(prepared_artifact IS NOT NULL AND article_fingerprint IS NOT NULL "
            "AND content_fingerprint IS NOT NULL AND article_run_id IS NOT NULL)",
            name="single_edition_prepared",
        ),
        sa.CheckConstraint(
            "status <> 'delivered' OR receipt_fingerprint IS NOT NULL",
            name="single_edition_receipt",
        ),
    )
    op.create_index(
        "ix_single_edition_ready", "official_account_single_editions", ["status", "available_at"]
    )
    op.create_table(
        "official_account_draft_owners",
        sa.Column("account_fingerprint", sa.String(64), primary_key=True),
        sa.Column("key_kind", sa.String(16), primary_key=True),
        sa.Column("key_value", sa.String(64), primary_key=True),
        sa.Column("owner", sa.String(120), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("provenance_fingerprint", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("key_kind IN ('event','article','history')", name="draft_owner_kind"),
        sa.CheckConstraint(
            "account_fingerprint ~ '^[0-9a-f]{64}$' AND provenance_fingerprint ~ '^[0-9a-f]{64}$'",
            name="draft_owner_fingerprints",
        ),
        sa.CheckConstraint(
            "status IN ('reserved','acknowledged','outcome_unknown','ready','conflict')",
            name="draft_owner_status",
        ),
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DO $$ BEGIN IF EXISTS (SELECT 1 FROM official_account_single_editions) OR "
            "EXISTS (SELECT 1 FROM official_account_draft_owners) THEN "
            "RAISE EXCEPTION 'cannot downgrade populated single edition ownership'; END IF; END $$"
        )
    )
    op.drop_table("official_account_draft_owners")
    op.drop_index("ix_single_edition_ready", table_name="official_account_single_editions")
    op.drop_table("official_account_single_editions")
