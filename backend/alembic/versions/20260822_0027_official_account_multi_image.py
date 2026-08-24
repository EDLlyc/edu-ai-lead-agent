"""Add deterministic multi-image lineage to local official-account drafts."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260822_0027"
down_revision: str | None = "20260821_0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_official_account_article_versions_version",
        "official_account_article_versions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_official_account_article_versions_version",
        "official_account_article_versions",
        "version IN (1, 2)",
    )
    op.drop_constraint(
        "ck_official_account_local_media_ordinal",
        "official_account_local_media",
        type_="check",
    )
    op.create_check_constraint(
        "ck_official_account_local_media_ordinal",
        "official_account_local_media",
        "(role = 'body' AND ordinal BETWEEN 0 AND 4) OR (role = 'cover' AND ordinal = 0)",
    )
    op.create_index(
        "uq_official_account_local_media_body_checksum",
        "official_account_local_media",
        ["run_id", "sha256"],
        unique=True,
        postgresql_where=sa.text("role = 'body'"),
    )
    op.create_unique_constraint(
        "uq_official_media_typed_identity",
        "official_account_local_media",
        ["id", "run_id", "role", "ordinal"],
    )
    op.create_table(
        "official_account_local_draft_body_media",
        sa.Column("draft_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "media_role",
            sa.String(length=20),
            server_default=sa.text("'body'"),
            nullable=False,
        ),
        sa.Column("body_media_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "ordinal BETWEEN 0 AND 4",
            name="ck_official_account_local_draft_body_media_ordinal",
        ),
        sa.CheckConstraint(
            "media_role = 'body'",
            name="ck_official_draft_body_media_role",
        ),
        sa.ForeignKeyConstraint(
            ["draft_id", "run_id"],
            ["official_account_local_drafts.id", "official_account_local_drafts.run_id"],
            name="fk_official_account_local_draft_body_media_draft_run",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["body_media_id", "run_id", "media_role", "ordinal"],
            [
                "official_account_local_media.id",
                "official_account_local_media.run_id",
                "official_account_local_media.role",
                "official_account_local_media.ordinal",
            ],
            name="fk_official_draft_body_media_typed",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "draft_id",
            "ordinal",
            name="pk_official_account_local_draft_body_media",
        ),
        sa.UniqueConstraint(
            "draft_id",
            "body_media_id",
            name="uq_official_account_local_draft_body_media_identity",
        ),
    )
    op.create_index(
        "ix_official_account_local_draft_body_media_run",
        "official_account_local_draft_body_media",
        ["run_id", "draft_id", "ordinal"],
        unique=False,
    )
    op.execute(
        sa.text(
            "INSERT INTO official_account_local_draft_body_media "
            "(draft_id, ordinal, run_id, body_media_id) "
            "SELECT id, 0, run_id, body_media_id FROM official_account_local_drafts"
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM official_account_local_media "
            "WHERE role = 'body' AND ordinal > 0) "
            "OR EXISTS (SELECT 1 FROM official_account_article_versions WHERE version = 2) "
            "THEN RAISE EXCEPTION "
            "'cannot downgrade official-account multi-image artifacts'; END IF; END $$"
        )
    )
    op.drop_index(
        "ix_official_account_local_draft_body_media_run",
        table_name="official_account_local_draft_body_media",
    )
    op.drop_table("official_account_local_draft_body_media")
    op.drop_index(
        "uq_official_account_local_media_body_checksum",
        table_name="official_account_local_media",
    )
    op.drop_constraint(
        "uq_official_media_typed_identity",
        "official_account_local_media",
        type_="unique",
    )
    op.drop_constraint(
        "ck_official_account_local_media_ordinal",
        "official_account_local_media",
        type_="check",
    )
    op.create_check_constraint(
        "ck_official_account_local_media_ordinal",
        "official_account_local_media",
        "ordinal = 0",
    )
    op.drop_constraint(
        "ck_official_account_article_versions_version",
        "official_account_article_versions",
        type_="check",
    )
    op.create_check_constraint(
        "ck_official_account_article_versions_version",
        "official_account_article_versions",
        "version = 1",
    )
