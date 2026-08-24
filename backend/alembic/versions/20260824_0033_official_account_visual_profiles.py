"""Add block anchors and replay profiles for generated official-account visuals."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260824_0033"
down_revision: str | None = "20260824_0032"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    table = "official_account_generated_visuals"
    op.add_column(table, sa.Column("block_index", sa.Integer(), nullable=True))
    op.add_column(table, sa.Column("block_kind", sa.String(20), nullable=True))
    op.add_column(table, sa.Column("block_fingerprint", sa.String(64), nullable=True))
    op.add_column(table, sa.Column("reference_input_version", sa.String(80), nullable=True))
    op.add_column(table, sa.Column("reference_input_checksum", sa.String(64), nullable=True))
    op.add_column(table, sa.Column("output_profile_version", sa.String(80), nullable=True))
    op.create_check_constraint(
        "ck_official_generated_visuals_plan_shape",
        table,
        "(plan_version = 'official-account-generated-visual-plan-v1' "
        "AND prompt_version = 'official-account-generated-visual-prompt-v1' "
        "AND block_index IS NULL AND block_kind IS NULL AND block_fingerprint IS NULL "
        "AND reference_input_version IS NULL AND reference_input_checksum IS NULL "
        "AND output_profile_version IS NULL) OR "
        "(plan_version = 'official-account-generated-visual-plan-v2-block-anchor' "
        "AND prompt_version = 'official-account-generated-visual-prompt-v2-block-scene' "
        "AND block_index BETWEEN 0 AND 12 "
        "AND block_kind IN ('paragraph', 'bullet_list', 'quote', 'callout') "
        "AND block_fingerprint ~ '^[0-9a-f]{64}$' "
        "AND reference_input_version = "
        "'image-reference-input-v2-png-preserve-jpeg-normalize' "
        "AND reference_input_checksum ~ '^[0-9a-f]{64}$' "
        "AND output_profile_version = "
        "'official-account-generated-body-publication-v2-3x2-jpeg')",
    )
    op.create_check_constraint(
        "ck_official_generated_visuals_v2_publication",
        table,
        "plan_version <> 'official-account-generated-visual-plan-v2-block-anchor' OR "
        "status <> 'ready' OR (media_type = 'image/jpeg' AND width = 1536 "
        "AND height = 1024 AND byte_size BETWEEN 1 AND 20971520)",
    )


def downgrade() -> None:
    table = "official_account_generated_visuals"
    op.execute(
        sa.text(
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM official_account_generated_visuals "
            "WHERE plan_version = 'official-account-generated-visual-plan-v2-block-anchor') "
            "THEN RAISE EXCEPTION "
            "'cannot downgrade official-account generated visual v2 artifacts'; "
            "END IF; END $$"
        )
    )
    op.drop_constraint("ck_official_generated_visuals_v2_publication", table, type_="check")
    op.drop_constraint("ck_official_generated_visuals_plan_shape", table, type_="check")
    op.drop_column(table, "output_profile_version")
    op.drop_column(table, "reference_input_checksum")
    op.drop_column(table, "reference_input_version")
    op.drop_column(table, "block_fingerprint")
    op.drop_column(table, "block_kind")
    op.drop_column(table, "block_index")
