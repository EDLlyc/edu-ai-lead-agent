"""Add deterministic daily topic-selection persistence.

Revision ID: 20260730_0005
Revises: 20260729_0004
Create Date: 2026-07-30
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260730_0005"
down_revision: str | None = "20260729_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "topic_scoring_configs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version", sa.String(length=80), nullable=False),
        sa.Column("profile", sa.String(length=40), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("config_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_topic_scoring_configs"),
        sa.UniqueConstraint("profile", "version", name="uq_topic_scoring_configs_profile_version"),
        sa.UniqueConstraint("fingerprint", name="uq_topic_scoring_configs_fingerprint"),
    )
    op.create_table(
        "topic_selection_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trigger", sa.String(length=20), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("timezone", sa.String(length=80), nullable=False),
        sa.Column("scoring_profile", sa.String(length=40), nullable=False),
        sa.Column("config_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("config_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("config_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("governed_event_cutoff", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("selected_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("selected_event_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("no_topic_code", sa.String(length=40), nullable=True),
        sa.Column("total_scores", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("eligible_scores", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "trigger IN ('manual', 'scheduled')",
            name="ck_topic_selection_runs_trigger",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_topic_selection_runs_status",
        ),
        sa.CheckConstraint(
            "no_topic_code IS NULL OR no_topic_code IN "
            "('no_candidates', 'all_vetoed', 'below_threshold')",
            name="ck_topic_selection_runs_no_topic_code",
        ),
        sa.CheckConstraint("total_scores >= 0", name="ck_topic_selection_runs_total_scores"),
        sa.CheckConstraint("eligible_scores >= 0", name="ck_topic_selection_runs_eligible_scores"),
        sa.CheckConstraint(
            "(selected_event_id IS NULL) = (selected_event_version_id IS NULL)",
            name="ck_topic_selection_runs_selected_pair",
        ),
        sa.CheckConstraint(
            "status <> 'succeeded' OR "
            "((selected_event_id IS NOT NULL AND no_topic_code IS NULL) OR "
            "(selected_event_id IS NULL AND no_topic_code IS NOT NULL))",
            name="ck_topic_selection_runs_terminal_decision",
        ),
        sa.ForeignKeyConstraint(
            ["config_id"],
            ["topic_scoring_configs.id"],
            name="fk_topic_selection_runs_config_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["selected_event_id"],
            ["event_clusters.id"],
            name="fk_topic_selection_runs_selected_event_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["selected_event_version_id"],
            ["event_cluster_versions.id"],
            name="fk_topic_selection_runs_selected_event_version_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_topic_selection_runs"),
        sa.UniqueConstraint(
            "business_date",
            "timezone",
            "scoring_profile",
            "config_fingerprint",
            name="uq_topic_selection_runs_business_config",
        ),
    )
    op.create_index(
        "ix_topic_selection_runs_status_created",
        "topic_selection_runs",
        ["status", "created_at"],
        unique=False,
    )
    op.create_table(
        "topic_selection_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
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
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_topic_selection_jobs_status",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_topic_selection_jobs_attempt_count"),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["topic_selection_runs.id"],
            name="fk_topic_selection_jobs_run_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_topic_selection_jobs"),
        sa.UniqueConstraint("run_id", name="uq_topic_selection_jobs_run_id"),
    )
    op.create_index(
        "ix_topic_selection_jobs_claim",
        "topic_selection_jobs",
        ["status", "available_at", "lease_expires_at"],
        unique=False,
    )
    op.create_table(
        "topic_scores",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("raw_features", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("normalized_features", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("weights", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("penalty_weights", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("positive_components", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("penalty_components", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("total", sa.Float(), nullable=False),
        sa.Column("threshold", sa.Float(), nullable=False),
        sa.Column("passes_threshold", sa.Boolean(), nullable=False),
        sa.Column("eligible", sa.Boolean(), nullable=False),
        sa.Column("veto_codes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("explanation", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("rank >= 1", name="ck_topic_scores_rank"),
        sa.CheckConstraint(
            "jsonb_typeof(veto_codes) = 'array'", name="ck_topic_scores_veto_codes_array"
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["event_clusters.id"],
            name="fk_topic_scores_event_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["event_version_id"],
            ["event_cluster_versions.id"],
            name="fk_topic_scores_event_version_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["topic_selection_runs.id"],
            name="fk_topic_scores_run_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_topic_scores"),
        sa.UniqueConstraint("run_id", "event_id", name="uq_topic_scores_run_event"),
        sa.UniqueConstraint("run_id", "rank", name="uq_topic_scores_run_rank"),
    )
    op.create_index("ix_topic_scores_run_total", "topic_scores", ["run_id", "total"], unique=False)
    op.create_table(
        "daily_topic_selections",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("timezone", sa.String(length=80), nullable=False),
        sa.Column("scoring_profile", sa.String(length=40), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("config_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("config_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("decision_kind", sa.String(length=20), nullable=False),
        sa.Column("selected_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("selected_event_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("no_topic_code", sa.String(length=40), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "decision_kind IN ('selected', 'no_topic')",
            name="ck_daily_topic_selections_decision_kind",
        ),
        sa.CheckConstraint(
            "no_topic_code IS NULL OR no_topic_code IN "
            "('no_candidates', 'all_vetoed', 'below_threshold')",
            name="ck_daily_topic_selections_no_topic_code",
        ),
        sa.CheckConstraint(
            "(decision_kind = 'selected' AND selected_event_id IS NOT NULL "
            "AND selected_event_version_id IS NOT NULL AND no_topic_code IS NULL) OR "
            "(decision_kind = 'no_topic' AND selected_event_id IS NULL "
            "AND selected_event_version_id IS NULL AND no_topic_code IS NOT NULL)",
            name="ck_daily_topic_selections_decision",
        ),
        sa.ForeignKeyConstraint(
            ["config_id"],
            ["topic_scoring_configs.id"],
            name="fk_daily_topic_selections_config_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["topic_selection_runs.id"],
            name="fk_daily_topic_selections_run_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["selected_event_id"],
            ["event_clusters.id"],
            name="fk_daily_topic_selections_selected_event_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["selected_event_version_id"],
            ["event_cluster_versions.id"],
            name="fk_daily_topic_selections_selected_event_version_id",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_daily_topic_selections"),
        sa.UniqueConstraint(
            "business_date",
            "timezone",
            "scoring_profile",
            name="uq_daily_topic_selections_business_key",
        ),
        sa.UniqueConstraint("run_id", name="uq_daily_topic_selections_run_id"),
    )
    op.create_index(
        "ix_daily_topic_selections_selected_event",
        "daily_topic_selections",
        ["selected_event_id", "business_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_daily_topic_selections_selected_event", table_name="daily_topic_selections")
    op.drop_table("daily_topic_selections")
    op.drop_index("ix_topic_scores_run_total", table_name="topic_scores")
    op.drop_table("topic_scores")
    op.drop_index("ix_topic_selection_jobs_claim", table_name="topic_selection_jobs")
    op.drop_table("topic_selection_jobs")
    op.drop_index("ix_topic_selection_runs_status_created", table_name="topic_selection_runs")
    op.drop_table("topic_selection_runs")
    op.drop_table("topic_scoring_configs")
