"""Add native visual intents and independently fenced final-image audits.

Rollback to pre-strict workers is forbidden once strict run identities exist.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260907_0043"
down_revision: str | None = "20260901_0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _legacy_shape() -> str:
    common = (
        " AND block_index BETWEEN 0 AND 12"
        " AND block_kind IN ('paragraph','bullet_list','quote','callout')"
        " AND block_fingerprint ~ '^[0-9a-f]{64}$'"
        " AND reference_input_version = 'image-reference-input-v2-png-preserve-jpeg-normalize'"
        " AND reference_input_checksum ~ '^[0-9a-f]{64}$'"
        " AND output_profile_version = 'official-account-generated-body-publication-v2-3x2-jpeg')"
    )
    return (
        "(plan_version = 'official-account-generated-visual-plan-v1'"
        " AND prompt_version = 'official-account-generated-visual-prompt-v1'"
        " AND block_index IS NULL AND block_kind IS NULL AND block_fingerprint IS NULL"
        " AND reference_input_version IS NULL AND reference_input_checksum IS NULL"
        " AND output_profile_version IS NULL) OR "
        "(plan_version = 'official-account-generated-visual-plan-v2-block-anchor'"
        " AND prompt_version = 'official-account-generated-visual-prompt-v2-block-scene'"
        + common
        + " OR (plan_version = 'official-account-generated-visual-plan-v3-visible-ip'"
        " AND prompt_version = 'official-account-generated-visual-prompt-v3-visible-ip-block-scene'"
        + common
    )


def upgrade() -> None:
    table = "official_account_generated_visuals"
    op.add_column(table, sa.Column("output_size", sa.String(20), nullable=True))
    op.add_column(
        table, sa.Column("intent_lease_token", postgresql.UUID(as_uuid=True), nullable=True)
    )
    op.add_column(table, sa.Column("intent_attempt_number", sa.Integer(), nullable=True))
    op.drop_constraint("ck_official_generated_visuals_plan_shape", table, type_="check")
    op.create_check_constraint(
        "ck_official_generated_visuals_plan_shape",
        table,
        _legacy_shape()
        + " OR (plan_version = 'official-account-generated-visual-plan-v4-native-strict'"
        " AND prompt_version = 'official-account-generated-visual-prompt-v4-native-strict'"
        " AND block_index BETWEEN 0 AND 12"
        " AND block_kind IN ('paragraph','bullet_list','quote','callout')"
        " AND block_fingerprint ~ '^[0-9a-f]{64}$'"
        " AND reference_input_version = 'image-reference-input-v2-png-preserve-jpeg-normalize'"
        " AND reference_input_checksum ~ '^[0-9a-f]{64}$'"
        " AND output_profile_version = 'official-account-generated-body-jpeg-v2-native-strict')",
    )
    op.create_check_constraint(
        "ck_official_generated_visuals_native_intent",
        table,
        "(plan_version = 'official-account-generated-visual-plan-v4-native-strict' "
        "AND output_size IS NOT NULL AND output_size = '1536x1024' "
        "AND intent_lease_token IS NOT NULL AND intent_attempt_number IS NOT NULL "
        "AND intent_attempt_number > 0 AND provider = 'comfly' AND model = 'gpt-image-2' "
        "AND block_index IS NOT NULL AND block_kind IS NOT NULL AND block_fingerprint IS NOT NULL "
        "AND reference_input_version IS NOT NULL AND reference_input_checksum IS NOT NULL "
        "AND output_profile_version IS NOT NULL "
        "AND (status <> 'ready' OR (width IS NOT NULL AND height IS NOT NULL "
        "AND media_type IS NOT NULL AND width = 1536 AND height = 1024 "
        "AND media_type = 'image/jpeg'))) OR "
        "(plan_version <> 'official-account-generated-visual-plan-v4-native-strict' "
        "AND output_size IS NULL AND intent_lease_token IS NULL AND intent_attempt_number IS NULL)",
    )
    op.create_table(
        "official_account_strict_visual_audits",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("official_account_article_runs.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "article_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("official_account_article_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "render_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("official_account_render_versions.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "generated_visual_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("official_account_generated_visuals.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("role", sa.String(10), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("upload_sha256", sa.String(64), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("subject", postgresql.JSONB(), nullable=False),
        sa.Column("lease_token", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("issue_codes", postgresql.JSONB(), nullable=False),
        sa.Column("record_fingerprint", sa.String(64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("run_id", "role", "ordinal", name="uq_official_strict_audit_slot"),
        sa.UniqueConstraint("request_fingerprint", name="uq_official_strict_audit_request"),
        sa.CheckConstraint(
            "(role = 'body' AND ordinal BETWEEN 0 AND 4) OR (role = 'cover' AND ordinal = 0)",
            name="ck_official_strict_audit_slot",
        ),
        sa.CheckConstraint("attempt_number > 0", name="ck_official_strict_audit_attempt"),
        sa.CheckConstraint(
            "request_fingerprint ~ '^[0-9a-f]{64}$' AND upload_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_official_strict_audit_hash",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(subject) = 'object' AND jsonb_typeof(issue_codes) = 'array' "
            "AND jsonb_array_length(issue_codes) <= 16",
            name="ck_official_strict_audit_json",
        ),
        sa.CheckConstraint(
            "(status = 'calling' AND completed_at IS NULL AND record_fingerprint IS NULL "
            "AND issue_codes = '[]'::jsonb) OR "
            "(status IN ('accepted','rejected','unavailable','result_unknown') "
            "AND completed_at IS NOT NULL AND record_fingerprint IS NOT NULL "
            "AND record_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND (status <> 'accepted' OR issue_codes = '[]'::jsonb))",
            name="ck_official_strict_audit_result",
        ),
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DO $$ BEGIN IF EXISTS (SELECT 1 FROM official_account_strict_visual_audits) "
            "OR EXISTS (SELECT 1 FROM official_account_generated_visuals "
            "WHERE output_size IS NOT NULL) "
            "OR EXISTS (SELECT 1 FROM official_account_article_runs "
            "WHERE version_bundle->>'visual_pipeline_version' IS NOT NULL) "
            "THEN RAISE EXCEPTION 'cannot downgrade populated strict visual pipeline'; "
            "END IF; END $$"
        )
    )
    op.drop_table("official_account_strict_visual_audits")
    table = "official_account_generated_visuals"
    op.drop_constraint("ck_official_generated_visuals_native_intent", table, type_="check")
    op.drop_constraint("ck_official_generated_visuals_plan_shape", table, type_="check")
    op.create_check_constraint("ck_official_generated_visuals_plan_shape", table, _legacy_shape())
    for column in ("intent_attempt_number", "intent_lease_token", "output_size"):
        op.drop_column(table, column)
