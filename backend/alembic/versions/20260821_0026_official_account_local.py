"""Add the durable official-account local article and simulation draft slice."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260821_0026"
down_revision: str | None = "20260821_0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "official_account_article_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("material_package_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fixture_id", sa.String(length=120), nullable=True),
        sa.Column("generation_mode", sa.String(length=20), nullable=False),
        sa.Column("source_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("version_bundle", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("current_stage", sa.String(length=40), nullable=False),
        sa.Column("active_article_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("active_render_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("active_body_media_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("active_cover_media_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("active_draft_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "available_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("attempt_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("lease_owner", sa.String(length=200), nullable=True),
        sa.Column("lease_token", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("error_retryable", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "(generation_mode = 'live' AND material_package_id IS NOT NULL "
            "AND fixture_id IS NULL) OR "
            "(generation_mode = 'fixture' AND material_package_id IS NULL "
            "AND fixture_id IS NOT NULL)",
            name="ck_official_account_article_runs_source_xor",
        ),
        sa.CheckConstraint(
            "provider IN ('fake', 'zhipu')",
            name="ck_official_account_article_runs_provider",
        ),
        sa.CheckConstraint(
            "(generation_mode = 'fixture' AND provider = 'fake') OR "
            "(generation_mode = 'live' AND provider = 'zhipu')",
            name="ck_official_account_article_runs_mode_provider",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'review_required', 'ready', 'failed', "
            "'result_unknown')",
            name="ck_official_account_article_runs_status",
        ),
        sa.CheckConstraint(
            "current_stage IN ('queued', 'generating', 'validating', 'auditing', "
            "'rendering', 'staging_body_media', 'staging_cover', "
            "'creating_local_draft', 'ready', 'review_required', 'failed', "
            "'result_unknown')",
            name="ck_official_account_article_runs_stage",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_official_account_article_runs_attempt"),
        sa.CheckConstraint(
            "jsonb_typeof(version_bundle) = 'object'",
            name="ck_official_account_article_runs_version_bundle_object",
        ),
        sa.ForeignKeyConstraint(
            ["material_package_id"],
            ["material_packages.id"],
            name="fk_official_account_article_runs_material_package_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_official_account_article_runs"),
        sa.UniqueConstraint("request_fingerprint", name="uq_official_account_article_runs_request"),
    )
    op.create_index(
        "ix_official_account_article_runs_claim",
        "official_account_article_runs",
        ["status", "available_at", "lease_expires_at", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_official_account_article_runs_material",
        "official_account_article_runs",
        ["material_package_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "official_account_article_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("article_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("content_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("generator_request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("generator_provider_request_id", sa.String(length=200), nullable=True),
        sa.Column("audit_request_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("audit_provider_request_id", sa.String(length=200), nullable=True),
        sa.Column("prompt_version", sa.String(length=80), nullable=False),
        sa.Column("schema_version", sa.String(length=80), nullable=False),
        sa.Column("audit_prompt_version", sa.String(length=80), nullable=False),
        sa.Column("audit_schema_version", sa.String(length=80), nullable=False),
        sa.Column("rule_version", sa.String(length=80), nullable=False),
        sa.Column("validation_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("audit_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("reasoning_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("latency_ms", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("audited_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("version = 1", name="ck_official_account_article_versions_version"),
        sa.CheckConstraint(
            "jsonb_typeof(article_payload) = 'object'",
            name="ck_official_account_article_versions_payload_object",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(validation_snapshot) = 'object' "
            "AND jsonb_typeof(audit_snapshot) = 'object'",
            name="ck_official_account_article_versions_quality_objects",
        ),
        sa.CheckConstraint(
            "prompt_tokens >= 0 AND completion_tokens >= 0 "
            "AND reasoning_tokens >= 0 AND latency_ms >= 0",
            name="ck_official_account_article_versions_usage",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["official_account_article_runs.id"],
            name="fk_official_account_article_versions_run_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_official_account_article_versions"),
        sa.UniqueConstraint("id", "run_id", name="uq_official_account_article_versions_id_run"),
        sa.UniqueConstraint("run_id", "version", name="uq_official_account_article_versions_run"),
        sa.UniqueConstraint(
            "generator_request_fingerprint",
            name="uq_official_account_article_versions_generation_request",
        ),
    )
    op.create_index(
        "ix_official_account_article_versions_run_id",
        "official_account_article_versions",
        ["run_id"],
        unique=False,
    )

    op.create_table(
        "official_account_article_attempts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("article_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("stage", sa.String(length=40), nullable=False),
        sa.Column("capability", sa.String(length=30), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=True),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column("provider_request_id", sa.String(length=200), nullable=True),
        sa.Column("prompt_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("reasoning_tokens", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("latency_ms", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "validation_corrections", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column(
            "safe_metadata",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "capability IN ('generation', 'audit', 'workflow')",
            name="ck_official_account_article_attempts_capability",
        ),
        sa.CheckConstraint(
            "status IN ('succeeded', 'failed')",
            name="ck_official_account_article_attempts_status",
        ),
        sa.CheckConstraint(
            "ordinal >= 1 AND prompt_tokens >= 0 AND completion_tokens >= 0 "
            "AND reasoning_tokens >= 0 AND latency_ms >= 0 "
            "AND validation_corrections BETWEEN 0 AND 1",
            name="ck_official_account_article_attempts_metrics",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(safe_metadata) = 'object'",
            name="ck_official_account_article_attempts_metadata_object",
        ),
        sa.ForeignKeyConstraint(
            ["article_version_id"],
            ["official_account_article_versions.id"],
            name="fk_official_account_article_attempts_article_version_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["official_account_article_runs.id"],
            name="fk_official_account_article_attempts_run_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_official_account_article_attempts"),
        sa.UniqueConstraint(
            "run_id",
            "stage",
            "ordinal",
            name="uq_official_account_article_attempts_stage_ordinal",
        ),
    )
    op.create_index(
        "ix_official_account_article_attempts_run",
        "official_account_article_attempts",
        ["run_id", "created_at"],
        unique=False,
    )
    op.create_index(
        "ix_official_account_article_attempts_request",
        "official_account_article_attempts",
        ["capability", "request_fingerprint"],
        unique=False,
    )

    op.create_table(
        "official_account_render_versions",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("article_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("canonical_html", sa.Text(), nullable=False),
        sa.Column("render_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("renderer_version", sa.String(length=80), nullable=False),
        sa.Column("style_version", sa.String(length=80), nullable=False),
        sa.Column("template_version", sa.String(length=80), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("byte_size > 0", name="ck_official_account_render_versions_bytes"),
        sa.ForeignKeyConstraint(
            ["article_version_id"],
            ["official_account_article_versions.id"],
            name="fk_official_account_render_versions_article_version_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["official_account_article_runs.id"],
            name="fk_official_account_render_versions_run_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_official_account_render_versions"),
        sa.UniqueConstraint("id", "run_id", name="uq_official_account_render_versions_id_run"),
        sa.UniqueConstraint(
            "article_version_id",
            "renderer_version",
            "style_version",
            "template_version",
            name="uq_official_account_render_versions_derivation",
        ),
        sa.UniqueConstraint(
            "render_fingerprint", name="uq_official_account_render_versions_fingerprint"
        ),
    )
    op.create_index(
        "ix_official_account_render_versions_run",
        "official_account_render_versions",
        ["run_id"],
        unique=False,
    )

    op.create_table(
        "official_account_local_media",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("render_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_image_artifact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("fixture_id", sa.String(length=120), nullable=True),
        sa.Column("role", sa.String(length=20), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("local_media_id", sa.String(length=80), nullable=False),
        sa.Column("media_type", sa.String(length=120), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("descriptor", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role IN ('body', 'cover')", name="ck_official_account_local_media_role"
        ),
        sa.CheckConstraint("ordinal = 0", name="ck_official_account_local_media_ordinal"),
        sa.CheckConstraint(
            "(source_image_artifact_id IS NOT NULL AND fixture_id IS NULL) OR "
            "(source_image_artifact_id IS NULL AND fixture_id IS NOT NULL)",
            name="ck_official_account_local_media_source_xor",
        ),
        sa.CheckConstraint(
            "status IN ('ready', 'failed')",
            name="ck_official_account_local_media_status",
        ),
        sa.CheckConstraint(
            "byte_size > 0 AND jsonb_typeof(descriptor) = 'object'",
            name="ck_official_account_local_media_descriptor",
        ),
        sa.ForeignKeyConstraint(
            ["render_version_id"],
            ["official_account_render_versions.id"],
            name="fk_official_account_local_media_render_version_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["official_account_article_runs.id"],
            name="fk_official_account_local_media_run_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_image_artifact_id"],
            ["image_artifacts.id"],
            name="fk_official_account_local_media_source_image_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_official_account_local_media"),
        sa.UniqueConstraint("id", "run_id", name="uq_official_account_local_media_id_run"),
        sa.UniqueConstraint(
            "render_version_id",
            "role",
            "ordinal",
            name="uq_official_account_local_media_render_role",
        ),
        sa.UniqueConstraint("request_fingerprint", name="uq_official_account_local_media_request"),
        sa.UniqueConstraint("local_media_id", name="uq_official_account_local_media_local_id"),
    )
    op.create_index(
        "ix_official_account_local_media_run",
        "official_account_local_media",
        ["run_id", "role"],
        unique=False,
    )

    op.create_table(
        "official_account_local_drafts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("render_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("body_media_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cover_media_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("local_draft_id", sa.String(length=80), nullable=False),
        sa.Column("resolved_html", sa.Text(), nullable=False),
        sa.Column("resolved_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("simulation", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("state", sa.String(length=30), nullable=False),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("simulation = true", name="ck_official_account_local_drafts_simulation"),
        sa.CheckConstraint(
            "state IN ('ready', 'failed', 'result_unknown')",
            name="ck_official_account_local_drafts_state",
        ),
        sa.CheckConstraint(
            "body_media_id <> cover_media_id",
            name="ck_official_account_local_drafts_media_distinct",
        ),
        sa.ForeignKeyConstraint(
            ["body_media_id"],
            ["official_account_local_media.id"],
            name="fk_official_account_local_drafts_body_media_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["cover_media_id"],
            ["official_account_local_media.id"],
            name="fk_official_account_local_drafts_cover_media_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["render_version_id"],
            ["official_account_render_versions.id"],
            name="fk_official_account_local_drafts_render_version_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["official_account_article_runs.id"],
            name="fk_official_account_local_drafts_run_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_official_account_local_drafts"),
        sa.UniqueConstraint("id", "run_id", name="uq_official_account_local_drafts_id_run"),
        sa.UniqueConstraint("run_id", name="uq_official_account_local_drafts_run"),
        sa.UniqueConstraint("request_fingerprint", name="uq_official_account_local_drafts_request"),
        sa.UniqueConstraint("local_draft_id", name="uq_official_account_local_drafts_local_id"),
    )
    op.create_index(
        "ix_official_account_local_drafts_created",
        "official_account_local_drafts",
        ["created_at"],
        unique=False,
    )

    op.create_foreign_key(
        "fk_official_account_article_runs_active_article",
        "official_account_article_runs",
        "official_account_article_versions",
        ["active_article_version_id", "id"],
        ["id", "run_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_official_account_article_runs_active_render",
        "official_account_article_runs",
        "official_account_render_versions",
        ["active_render_version_id", "id"],
        ["id", "run_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_official_account_article_runs_active_body_media",
        "official_account_article_runs",
        "official_account_local_media",
        ["active_body_media_id", "id"],
        ["id", "run_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_official_account_article_runs_active_cover_media",
        "official_account_article_runs",
        "official_account_local_media",
        ["active_cover_media_id", "id"],
        ["id", "run_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_official_account_article_runs_active_draft",
        "official_account_article_runs",
        "official_account_local_drafts",
        ["active_draft_id", "id"],
        ["id", "run_id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_official_account_article_runs_active_draft",
        "official_account_article_runs",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_official_account_article_runs_active_cover_media",
        "official_account_article_runs",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_official_account_article_runs_active_body_media",
        "official_account_article_runs",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_official_account_article_runs_active_render",
        "official_account_article_runs",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_official_account_article_runs_active_article",
        "official_account_article_runs",
        type_="foreignkey",
    )
    op.drop_index(
        "ix_official_account_local_drafts_created",
        table_name="official_account_local_drafts",
    )
    op.drop_table("official_account_local_drafts")
    op.drop_index("ix_official_account_local_media_run", table_name="official_account_local_media")
    op.drop_table("official_account_local_media")
    op.drop_index(
        "ix_official_account_render_versions_run",
        table_name="official_account_render_versions",
    )
    op.drop_table("official_account_render_versions")
    op.drop_index(
        "ix_official_account_article_attempts_request",
        table_name="official_account_article_attempts",
    )
    op.drop_index(
        "ix_official_account_article_attempts_run",
        table_name="official_account_article_attempts",
    )
    op.drop_table("official_account_article_attempts")
    op.drop_index(
        "ix_official_account_article_versions_run_id",
        table_name="official_account_article_versions",
    )
    op.drop_table("official_account_article_versions")
    op.drop_index(
        "ix_official_account_article_runs_material",
        table_name="official_account_article_runs",
    )
    op.drop_index(
        "ix_official_account_article_runs_claim",
        table_name="official_account_article_runs",
    )
    op.drop_table("official_account_article_runs")
