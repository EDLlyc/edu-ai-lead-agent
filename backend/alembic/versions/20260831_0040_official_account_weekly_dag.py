"""Add durable deterministic weekly three-article DAG checkpoints."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260831_0040"
down_revision: str | None = "20260831_0039"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "official_account_weekly_dag_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", sa.String(length=128), nullable=False),
        sa.Column("week_start", sa.Date(), nullable=False),
        sa.Column("timezone", sa.String(length=80), nullable=False),
        sa.Column("schedule_version", sa.String(length=80), nullable=False),
        sa.Column("selection_version", sa.String(length=80), nullable=False),
        sa.Column("dag_version", sa.String(length=80), nullable=False),
        sa.Column("graph_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("aggregate_artifact_ref", sa.String(length=128), nullable=True),
        sa.Column("aggregate_artifact_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("aggregate_media_type", sa.String(length=128), nullable=True),
        sa.Column("aggregate_byte_size", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'partial', 'retryable_failed', "
            "'terminal_failed', 'ready')",
            name="ck_weekly_dag_runs_status",
        ),
        sa.CheckConstraint(
            "(aggregate_artifact_ref IS NULL AND aggregate_artifact_fingerprint IS NULL "
            "AND aggregate_media_type IS NULL AND aggregate_byte_size IS NULL) OR "
            "(aggregate_artifact_ref IS NOT NULL AND aggregate_artifact_fingerprint IS NOT NULL "
            "AND aggregate_media_type IS NOT NULL AND aggregate_byte_size >= 0)",
            name="ck_weekly_dag_runs_aggregate_shape",
        ),
        sa.ForeignKeyConstraint(
            ["id", "task_id"],
            ["execution_governed_runs.id", "execution_governed_runs.task_id"],
            name="fk_weekly_dag_runs_execution_run",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_official_account_weekly_dag_runs"),
        sa.UniqueConstraint("id", "task_id", name="uq_weekly_dag_runs_task"),
        sa.UniqueConstraint(
            "week_start",
            "schedule_version",
            "selection_version",
            "dag_version",
            name="uq_weekly_dag_runs_business_key",
        ),
        sa.UniqueConstraint("request_fingerprint", name="uq_weekly_dag_runs_request"),
    )
    op.create_index(
        "ix_weekly_dag_runs_status_week",
        "official_account_weekly_dag_runs",
        ["status", "week_start"],
        unique=False,
    )

    op.create_table(
        "official_account_weekly_dag_nodes",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", sa.String(length=128), nullable=False),
        sa.Column("node_key", sa.String(length=128), nullable=False),
        sa.Column("ordinal", sa.SmallInteger(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("role", sa.String(length=32), nullable=True),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_owner", sa.String(length=128), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fencing_token", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("output_artifact_ref", sa.String(length=128), nullable=True),
        sa.Column("output_artifact_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("output_media_type", sa.String(length=128), nullable=True),
        sa.Column("output_byte_size", sa.BigInteger(), nullable=True),
        sa.Column("execution_artifact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("trace_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint(
            "kind IN ('schedule', 'select_roles', 'build_article', 'plan_media', "
            "'render_handoff', 'validate_child', 'aggregate', 'finalize')",
            name="ck_weekly_dag_nodes_kind",
        ),
        sa.CheckConstraint(
            "role IS NULL OR role IN ('official_anchor', 'industry_trend', 'application_case')",
            name="ck_weekly_dag_nodes_role",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'running', 'succeeded', 'retryable_failed', 'terminal_failed')",
            name="ck_weekly_dag_nodes_status",
        ),
        sa.CheckConstraint(
            "ordinal >= 0 AND attempt_count >= 0 AND max_attempts > 0 "
            "AND attempt_count <= max_attempts AND fencing_token >= 0",
            name="ck_weekly_dag_nodes_attempts",
        ),
        sa.CheckConstraint(
            "(status = 'running' AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL) OR "
            "(status <> 'running' AND lease_owner IS NULL AND lease_expires_at IS NULL)",
            name="ck_weekly_dag_nodes_lease_shape",
        ),
        sa.CheckConstraint(
            "(output_artifact_ref IS NULL AND output_artifact_fingerprint IS NULL "
            "AND output_media_type IS NULL AND output_byte_size IS NULL "
            "AND execution_artifact_id IS NULL) OR "
            "(output_artifact_ref IS NOT NULL AND output_artifact_fingerprint IS NOT NULL "
            "AND output_media_type IS NOT NULL AND output_byte_size >= 0 "
            "AND execution_artifact_id IS NOT NULL)",
            name="ck_weekly_dag_nodes_artifact_shape",
        ),
        sa.CheckConstraint(
            "status <> 'succeeded' OR (output_artifact_ref IS NOT NULL "
            "AND trace_event_id IS NOT NULL AND completed_at IS NOT NULL)",
            name="ck_weekly_dag_nodes_success_shape",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "task_id"],
            ["official_account_weekly_dag_runs.id", "official_account_weekly_dag_runs.task_id"],
            name="fk_weekly_dag_nodes_run",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["execution_artifact_id", "run_id", "task_id"],
            ["execution_artifacts.id", "execution_artifacts.run_id", "execution_artifacts.task_id"],
            name="fk_weekly_dag_nodes_execution_artifact",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["trace_event_id", "run_id", "task_id"],
            [
                "execution_trace_events.id",
                "execution_trace_events.run_id",
                "execution_trace_events.task_id",
            ],
            name="fk_weekly_dag_nodes_trace_event",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "run_id", "task_id", "node_key", name="pk_official_account_weekly_dag_nodes"
        ),
        sa.UniqueConstraint("run_id", "ordinal", name="uq_weekly_dag_nodes_ordinal"),
    )
    op.create_index(
        "ix_weekly_dag_nodes_claim",
        "official_account_weekly_dag_nodes",
        ["status", "available_at", "lease_expires_at", "ordinal"],
        unique=False,
    )
    op.create_index(
        "ix_weekly_dag_nodes_run_status",
        "official_account_weekly_dag_nodes",
        ["run_id", "status"],
        unique=False,
    )

    op.create_table(
        "official_account_weekly_dag_attempts",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", sa.String(length=128), nullable=False),
        sa.Column("node_key", sa.String(length=128), nullable=False),
        sa.Column("attempt_no", sa.Integer(), nullable=False),
        sa.Column("fencing_token", sa.BigInteger(), nullable=False),
        sa.Column("worker_id", sa.String(length=128), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("output_artifact_ref", sa.String(length=128), nullable=True),
        sa.Column("output_artifact_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "attempt_no > 0 AND fencing_token > 0", name="ck_weekly_dag_attempts_no"
        ),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'retryable_failed', 'terminal_failed', "
            "'lease_expired')",
            name="ck_weekly_dag_attempts_status",
        ),
        sa.CheckConstraint(
            "status = 'running' OR completed_at IS NOT NULL",
            name="ck_weekly_dag_attempts_completion",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "task_id", "node_key"],
            [
                "official_account_weekly_dag_nodes.run_id",
                "official_account_weekly_dag_nodes.task_id",
                "official_account_weekly_dag_nodes.node_key",
            ],
            name="fk_weekly_dag_attempts_node",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "run_id",
            "task_id",
            "node_key",
            "attempt_no",
            name="pk_official_account_weekly_dag_attempts",
        ),
    )
    op.create_index(
        "ix_weekly_dag_attempts_run_started",
        "official_account_weekly_dag_attempts",
        ["run_id", "started_at"],
        unique=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    populated = bind.execute(
        sa.text("SELECT EXISTS (SELECT 1 FROM official_account_weekly_dag_runs LIMIT 1)")
    ).scalar_one()
    if populated:
        raise RuntimeError("weekly DAG tables contain rows; destructive downgrade is disabled")
    op.drop_index(
        "ix_weekly_dag_attempts_run_started",
        table_name="official_account_weekly_dag_attempts",
    )
    op.drop_table("official_account_weekly_dag_attempts")
    op.drop_index(
        "ix_weekly_dag_nodes_run_status",
        table_name="official_account_weekly_dag_nodes",
    )
    op.drop_index("ix_weekly_dag_nodes_claim", table_name="official_account_weekly_dag_nodes")
    op.drop_table("official_account_weekly_dag_nodes")
    op.drop_index(
        "ix_weekly_dag_runs_status_week",
        table_name="official_account_weekly_dag_runs",
    )
    op.drop_table("official_account_weekly_dag_runs")
