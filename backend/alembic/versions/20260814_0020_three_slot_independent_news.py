"""Add independent morning, noon, and evening content production."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260814_0020"
down_revision: str | None = "20260807_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SLOTS = "'morning', 'noon', 'evening'"


def upgrade() -> None:
    op.add_column(
        "acquisition_runs",
        sa.Column("content_slot", sa.String(length=20), nullable=True),
    )
    op.create_check_constraint(
        "ck_acquisition_runs_content_slot",
        "acquisition_runs",
        f"content_slot IS NULL OR content_slot IN ({_SLOTS})",
    )
    op.create_unique_constraint(
        "uq_acquisition_runs_id_slot_identity",
        "acquisition_runs",
        ["id", "business_date", "timezone", "content_slot"],
    )
    op.create_unique_constraint(
        "uq_governance_runs_id_acquisition",
        "governance_runs",
        ["id", "acquisition_run_id"],
    )
    op.drop_index(
        "uq_acquisition_runs_scheduled_business_key",
        table_name="acquisition_runs",
    )
    op.create_index(
        "uq_acquisition_runs_scheduled_business_key",
        "acquisition_runs",
        ["business_date", "timezone", "acquisition_version"],
        unique=True,
        postgresql_where=sa.text("trigger = 'scheduled' AND content_slot IS NULL"),
    )
    op.create_index(
        "uq_acquisition_runs_scheduled_slot_business_key",
        "acquisition_runs",
        ["business_date", "timezone", "acquisition_version", "content_slot"],
        unique=True,
        postgresql_where=sa.text("trigger = 'scheduled' AND content_slot IS NOT NULL"),
    )

    op.create_table(
        "content_slot_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("trigger", sa.String(length=20), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("timezone", sa.String(length=80), nullable=False),
        sa.Column("content_slot", sa.String(length=20), nullable=False),
        sa.Column("scoring_profile", sa.String(length=40), nullable=False),
        sa.Column("acquisition_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("governance_run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("governed_event_cutoff", sa.DateTime(timezone=True), nullable=False),
        sa.Column("config_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("config_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("config_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("slot_policy_version", sa.String(length=80), nullable=False),
        sa.Column("slot_policy_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("slot_policy_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("preparation_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("target_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("item_limit", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("total_scores", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("eligible_scores", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("selected_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("unfilled_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "unfilled_reason_codes",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_content_slot_runs"),
        sa.ForeignKeyConstraint(
            ["acquisition_run_id"],
            ["acquisition_runs.id"],
            name="fk_content_slot_runs_acquisition_run_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["governance_run_id"],
            ["governance_runs.id"],
            name="fk_content_slot_runs_governance_run_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["config_id"],
            ["topic_scoring_configs.id"],
            name="fk_content_slot_runs_config_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["acquisition_run_id", "business_date", "timezone", "content_slot"],
            [
                "acquisition_runs.id",
                "acquisition_runs.business_date",
                "acquisition_runs.timezone",
                "acquisition_runs.content_slot",
            ],
            name="fk_content_slot_runs_acquisition_identity",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["governance_run_id", "acquisition_run_id"],
            ["governance_runs.id", "governance_runs.acquisition_run_id"],
            name="fk_content_slot_runs_governance_lineage",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            "trigger IN ('manual', 'scheduled')", name="ck_content_slot_runs_trigger"
        ),
        sa.CheckConstraint(f"content_slot IN ({_SLOTS})", name="ck_content_slot_runs_content_slot"),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_content_slot_runs_status",
        ),
        sa.CheckConstraint(
            "preparation_at < target_at AND target_at <= expires_at",
            name="ck_content_slot_runs_window",
        ),
        sa.CheckConstraint("item_limit BETWEEN 1 AND 3", name="ck_content_slot_runs_item_limit"),
        sa.CheckConstraint(
            "total_scores >= 0 AND eligible_scores >= 0 AND selected_count >= 0 "
            "AND unfilled_count >= 0 AND selected_count <= item_limit "
            "AND unfilled_count = item_limit - selected_count",
            name="ck_content_slot_runs_counts",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(unfilled_reason_codes) = 'array'",
            name="ck_content_slot_runs_unfilled_reasons_array",
        ),
        sa.UniqueConstraint(
            "business_date",
            "timezone",
            "content_slot",
            "scoring_profile",
            "slot_policy_fingerprint",
            name="uq_content_slot_runs_business_policy",
        ),
        sa.UniqueConstraint(
            "acquisition_run_id",
            "governance_run_id",
            "scoring_profile",
            "slot_policy_fingerprint",
            name="uq_content_slot_runs_lineage_policy",
        ),
        sa.UniqueConstraint(
            "id",
            "business_date",
            "timezone",
            "content_slot",
            name="uq_content_slot_runs_id_slot_identity",
        ),
    )
    op.create_index(
        "ix_content_slot_runs_status_created", "content_slot_runs", ["status", "created_at"]
    )
    op.create_index(
        "ix_content_slot_runs_business_slot",
        "content_slot_runs",
        ["business_date", "content_slot"],
    )

    op.create_table(
        "content_slot_jobs",
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
        sa.PrimaryKeyConstraint("id", name="pk_content_slot_jobs"),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["content_slot_runs.id"],
            name="fk_content_slot_jobs_run_id",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'failed')",
            name="ck_content_slot_jobs_status",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_content_slot_jobs_attempt_count"),
        sa.UniqueConstraint("run_id", name="uq_content_slot_jobs_run_id"),
    )
    op.create_index(
        "ix_content_slot_jobs_claim",
        "content_slot_jobs",
        ["status", "available_at", "lease_expires_at"],
    )

    op.create_table(
        "content_slot_scores",
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
        sa.Column("explanation", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("slot_affinity", sa.Float(), nullable=False),
        sa.Column("slot_affinity_reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("same_day_excluded", sa.Boolean(), nullable=False),
        sa.Column("same_day_exclusion_reason", sa.String(length=80), nullable=True),
        sa.Column("final_ordering_value", sa.Float(), nullable=False),
        sa.Column("final_ordering_key", sa.String(length=300), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("selected_ordinal", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_content_slot_scores"),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["content_slot_runs.id"],
            name="fk_content_slot_scores_run_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["event_clusters.id"],
            name="fk_content_slot_scores_event_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["event_version_id"],
            ["event_cluster_versions.id"],
            name="fk_content_slot_scores_event_version_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["event_version_id", "event_id"],
            ["event_cluster_versions.id", "event_cluster_versions.event_id"],
            name="fk_content_slot_scores_event_version_event",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint("rank >= 1", name="ck_content_slot_scores_rank"),
        sa.CheckConstraint(
            "selected_ordinal IS NULL OR selected_ordinal BETWEEN 1 AND 3",
            name="ck_content_slot_scores_selected_ordinal",
        ),
        sa.CheckConstraint(
            "slot_affinity >= 0 AND slot_affinity <= 0.25",
            name="ck_content_slot_scores_affinity",
        ),
        sa.CheckConstraint(
            "same_day_excluded = (same_day_exclusion_reason IS NOT NULL)",
            name="ck_content_slot_scores_exclusion",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(veto_codes) = 'array' AND jsonb_typeof(slot_affinity_reasons) = 'array'",
            name="ck_content_slot_scores_arrays",
        ),
        sa.UniqueConstraint("run_id", "event_id", name="uq_content_slot_scores_run_event"),
        sa.UniqueConstraint("run_id", "rank", name="uq_content_slot_scores_run_rank"),
        sa.UniqueConstraint(
            "run_id", "selected_ordinal", name="uq_content_slot_scores_run_selected_ordinal"
        ),
        sa.UniqueConstraint(
            "id",
            "run_id",
            "event_id",
            "event_version_id",
            "selected_ordinal",
            name="uq_content_slot_scores_selection_identity",
        ),
    )
    op.create_index("ix_content_slot_scores_run_order", "content_slot_scores", ["run_id", "rank"])

    op.create_table(
        "content_slot_selections",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("score_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("timezone", sa.String(length=80), nullable=False),
        sa.Column("content_slot", sa.String(length=20), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("selected_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("selected_event_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_content_slot_selections"),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["content_slot_runs.id"],
            name="fk_content_slot_selections_run_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["score_id"],
            ["content_slot_scores.id"],
            name="fk_content_slot_selections_score_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["selected_event_id"],
            ["event_clusters.id"],
            name="fk_content_slot_selections_selected_event_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["selected_event_version_id"],
            ["event_cluster_versions.id"],
            name="fk_content_slot_selections_selected_event_version_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["selected_event_version_id", "selected_event_id"],
            ["event_cluster_versions.id", "event_cluster_versions.event_id"],
            name="fk_content_slot_selections_event_version_event",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "business_date", "timezone", "content_slot"],
            [
                "content_slot_runs.id",
                "content_slot_runs.business_date",
                "content_slot_runs.timezone",
                "content_slot_runs.content_slot",
            ],
            name="fk_content_slot_selections_run_identity",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "score_id",
                "run_id",
                "selected_event_id",
                "selected_event_version_id",
                "ordinal",
            ],
            [
                "content_slot_scores.id",
                "content_slot_scores.run_id",
                "content_slot_scores.event_id",
                "content_slot_scores.event_version_id",
                "content_slot_scores.selected_ordinal",
            ],
            name="fk_content_slot_selections_score_identity",
            ondelete="RESTRICT",
        ),
        sa.CheckConstraint(
            f"content_slot IN ({_SLOTS})", name="ck_content_slot_selections_content_slot"
        ),
        sa.CheckConstraint("ordinal BETWEEN 1 AND 3", name="ck_content_slot_selections_ordinal"),
        sa.UniqueConstraint("run_id", "ordinal", name="uq_content_slot_selections_run_ordinal"),
        sa.UniqueConstraint(
            "run_id", "selected_event_id", name="uq_content_slot_selections_run_event"
        ),
        sa.UniqueConstraint("score_id", name="uq_content_slot_selections_score_id"),
        sa.UniqueConstraint(
            "id",
            "business_date",
            "timezone",
            "selected_event_id",
            "selected_event_version_id",
            name="uq_content_slot_selections_copy_origin_identity",
        ),
        sa.UniqueConstraint("id", "ordinal", name="uq_content_slot_selections_delivery_ordinal"),
        sa.UniqueConstraint(
            "business_date",
            "timezone",
            "selected_event_id",
            name="uq_content_slot_selections_daily_event",
        ),
    )
    op.create_index(
        "ix_content_slot_selections_business_slot",
        "content_slot_selections",
        ["business_date", "content_slot"],
    )

    op.alter_column("copy_generation_runs", "daily_topic_selection_id", nullable=True)
    op.alter_column("copy_generation_runs", "topic_selection_run_id", nullable=True)
    op.add_column(
        "copy_generation_runs",
        sa.Column("content_slot_selection_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_copy_generation_runs_content_slot_selection_id",
        "copy_generation_runs",
        "content_slot_selections",
        ["content_slot_selection_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_copy_generation_runs_slot_origin_identity",
        "copy_generation_runs",
        "content_slot_selections",
        [
            "content_slot_selection_id",
            "business_date",
            "timezone",
            "selected_event_id",
            "selected_event_version_id",
        ],
        ["id", "business_date", "timezone", "selected_event_id", "selected_event_version_id"],
        ondelete="RESTRICT",
    )
    op.create_check_constraint(
        "ck_copy_generation_runs_origin_xor",
        "copy_generation_runs",
        "(daily_topic_selection_id IS NOT NULL AND content_slot_selection_id IS NULL "
        "AND topic_selection_run_id IS NOT NULL) OR "
        "(daily_topic_selection_id IS NULL AND content_slot_selection_id IS NOT NULL "
        "AND topic_selection_run_id IS NULL AND decision_kind = 'selected')",
    )
    op.create_unique_constraint(
        "uq_copy_generation_runs_slot_version",
        "copy_generation_runs",
        ["content_slot_selection_id", "version_fingerprint"],
    )

    op.create_table(
        "wecom_delivery_windows",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("business_date", sa.Date(), nullable=False),
        sa.Column("timezone", sa.String(length=80), nullable=False),
        sa.Column("content_slot", sa.String(length=20), nullable=False),
        sa.Column("recipient_id", sa.String(length=80), nullable=False),
        sa.Column("provider", sa.String(length=30), nullable=False),
        sa.Column("mode", sa.String(length=20), nullable=False),
        sa.Column("target_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("package_gap_seconds", sa.Integer(), nullable=False),
        sa.Column("next_allowed_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.PrimaryKeyConstraint("id", name="pk_wecom_delivery_windows"),
        sa.CheckConstraint(
            f"content_slot IN ({_SLOTS})", name="ck_wecom_delivery_windows_content_slot"
        ),
        sa.CheckConstraint(
            "provider IN ('self_built_app', 'group_webhook')",
            name="ck_wecom_delivery_windows_provider",
        ),
        sa.CheckConstraint("mode = 'formal'", name="ck_wecom_delivery_windows_mode"),
        sa.CheckConstraint("target_at <= expires_at", name="ck_wecom_delivery_windows_interval"),
        sa.CheckConstraint(
            "package_gap_seconds BETWEEN 1 AND 600", name="ck_wecom_delivery_windows_gap"
        ),
        sa.UniqueConstraint(
            "business_date",
            "timezone",
            "content_slot",
            "recipient_id",
            "provider",
            "mode",
            name="uq_wecom_delivery_windows_lane",
        ),
        sa.UniqueConstraint(
            "id",
            "recipient_id",
            "mode",
            "target_at",
            "expires_at",
            name="uq_wecom_delivery_windows_job_identity",
        ),
    )
    op.create_index(
        "ix_wecom_delivery_windows_next_allowed",
        "wecom_delivery_windows",
        ["next_allowed_at", "expires_at"],
    )

    for column in (
        sa.Column("delivery_window_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("content_slot_selection_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("sequence_ordinal", sa.Integer(), nullable=True),
        sa.Column("not_before", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    ):
        op.add_column("wecom_delivery_jobs", column)
    op.create_foreign_key(
        "fk_wecom_delivery_jobs_delivery_window_id",
        "wecom_delivery_jobs",
        "wecom_delivery_windows",
        ["delivery_window_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_wecom_delivery_jobs_content_slot_selection_id",
        "wecom_delivery_jobs",
        "content_slot_selections",
        ["content_slot_selection_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_wecom_delivery_jobs_slot_ordinal",
        "wecom_delivery_jobs",
        "content_slot_selections",
        ["content_slot_selection_id", "sequence_ordinal"],
        ["id", "ordinal"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_wecom_delivery_jobs_window_identity",
        "wecom_delivery_jobs",
        "wecom_delivery_windows",
        ["delivery_window_id", "recipient_id", "mode", "not_before", "expires_at"],
        ["id", "recipient_id", "mode", "target_at", "expires_at"],
        ondelete="RESTRICT",
    )
    op.drop_constraint("ck_wecom_delivery_jobs_status", "wecom_delivery_jobs", type_="check")
    op.create_check_constraint(
        "ck_wecom_delivery_jobs_status",
        "wecom_delivery_jobs",
        "status IN ('queued', 'running', 'partial', 'delivery_unknown', 'delivered', "
        "'failed', 'cancelled', 'delivery_window_expired')",
    )
    op.create_check_constraint(
        "ck_wecom_delivery_jobs_slot_shape",
        "wecom_delivery_jobs",
        "(delivery_window_id IS NULL AND content_slot_selection_id IS NULL "
        "AND sequence_ordinal IS NULL AND not_before IS NULL AND expires_at IS NULL) OR "
        "(delivery_window_id IS NOT NULL AND content_slot_selection_id IS NOT NULL "
        "AND sequence_ordinal BETWEEN 1 AND 3 AND not_before IS NOT NULL "
        "AND expires_at IS NOT NULL AND not_before <= expires_at)",
    )
    op.create_unique_constraint(
        "uq_wecom_delivery_jobs_window_package",
        "wecom_delivery_jobs",
        ["delivery_window_id", "sequence_ordinal", "material_package_id"],
    )
    op.create_index(
        "ix_wecom_delivery_jobs_slot_claim",
        "wecom_delivery_jobs",
        ["delivery_window_id", "sequence_ordinal", "not_before", "expires_at"],
    )


def downgrade() -> None:
    has_slot_artifacts = op.get_bind().scalar(
        sa.text(
            "SELECT EXISTS ("
            "SELECT 1 FROM acquisition_runs WHERE content_slot IS NOT NULL "
            "UNION ALL SELECT 1 FROM content_slot_runs "
            "UNION ALL SELECT 1 FROM copy_generation_runs "
            "WHERE content_slot_selection_id IS NOT NULL "
            "UNION ALL SELECT 1 FROM wecom_delivery_windows "
            "UNION ALL SELECT 1 FROM wecom_delivery_jobs WHERE delivery_window_id IS NOT NULL"
            ")"
        )
    )
    if has_slot_artifacts:
        raise RuntimeError("cannot downgrade while content-slot artifacts exist")
    op.drop_index("ix_wecom_delivery_jobs_slot_claim", table_name="wecom_delivery_jobs")
    op.drop_constraint(
        "uq_wecom_delivery_jobs_window_package", "wecom_delivery_jobs", type_="unique"
    )
    op.drop_constraint("ck_wecom_delivery_jobs_slot_shape", "wecom_delivery_jobs", type_="check")
    op.drop_constraint("ck_wecom_delivery_jobs_status", "wecom_delivery_jobs", type_="check")
    op.create_check_constraint(
        "ck_wecom_delivery_jobs_status",
        "wecom_delivery_jobs",
        "status IN ('queued', 'running', 'partial', 'delivery_unknown', 'delivered', "
        "'failed', 'cancelled')",
    )
    op.drop_constraint(
        "fk_wecom_delivery_jobs_content_slot_selection_id",
        "wecom_delivery_jobs",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_wecom_delivery_jobs_slot_ordinal", "wecom_delivery_jobs", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_wecom_delivery_jobs_window_identity", "wecom_delivery_jobs", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_wecom_delivery_jobs_delivery_window_id", "wecom_delivery_jobs", type_="foreignkey"
    )
    for column_name in (
        "expires_at",
        "not_before",
        "sequence_ordinal",
        "content_slot_selection_id",
        "delivery_window_id",
    ):
        op.drop_column("wecom_delivery_jobs", column_name)
    op.drop_index("ix_wecom_delivery_windows_next_allowed", table_name="wecom_delivery_windows")
    op.drop_table("wecom_delivery_windows")

    op.drop_constraint(
        "uq_copy_generation_runs_slot_version", "copy_generation_runs", type_="unique"
    )
    op.drop_constraint("ck_copy_generation_runs_origin_xor", "copy_generation_runs", type_="check")
    op.drop_constraint(
        "fk_copy_generation_runs_content_slot_selection_id",
        "copy_generation_runs",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_copy_generation_runs_slot_origin_identity",
        "copy_generation_runs",
        type_="foreignkey",
    )
    op.drop_column("copy_generation_runs", "content_slot_selection_id")
    op.alter_column("copy_generation_runs", "topic_selection_run_id", nullable=False)
    op.alter_column("copy_generation_runs", "daily_topic_selection_id", nullable=False)

    op.drop_index("ix_content_slot_selections_business_slot", table_name="content_slot_selections")
    op.drop_table("content_slot_selections")
    op.drop_index("ix_content_slot_scores_run_order", table_name="content_slot_scores")
    op.drop_table("content_slot_scores")
    op.drop_index("ix_content_slot_jobs_claim", table_name="content_slot_jobs")
    op.drop_table("content_slot_jobs")
    op.drop_index("ix_content_slot_runs_business_slot", table_name="content_slot_runs")
    op.drop_index("ix_content_slot_runs_status_created", table_name="content_slot_runs")
    op.drop_table("content_slot_runs")

    op.drop_constraint("uq_governance_runs_id_acquisition", "governance_runs", type_="unique")

    op.drop_index("uq_acquisition_runs_scheduled_slot_business_key", table_name="acquisition_runs")
    op.drop_index("uq_acquisition_runs_scheduled_business_key", table_name="acquisition_runs")
    op.create_index(
        "uq_acquisition_runs_scheduled_business_key",
        "acquisition_runs",
        ["business_date", "timezone", "acquisition_version"],
        unique=True,
        postgresql_where=sa.text("trigger = 'scheduled'"),
    )
    op.drop_constraint("ck_acquisition_runs_content_slot", "acquisition_runs", type_="check")
    op.drop_constraint("uq_acquisition_runs_id_slot_identity", "acquisition_runs", type_="unique")
    op.drop_column("acquisition_runs", "content_slot")
