"""Add safe execution governance identity, budget, capability and trace ledger."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260831_0039"
down_revision: str | None = "20260831_0038"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = (
    "execution_budget_reservations",
    "execution_artifacts",
    "execution_trace_events",
    "execution_agent_allocations",
    "execution_governed_runs",
)


def upgrade() -> None:
    op.create_table(
        "execution_governed_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", sa.String(length=128), nullable=False),
        sa.Column("root_agent_id", sa.String(length=128), nullable=False),
        sa.Column("policy_version", sa.String(length=80), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("limit_elapsed_ms", sa.BigInteger(), nullable=False),
        sa.Column("limit_model_turns", sa.Integer(), nullable=False),
        sa.Column("limit_input_tokens", sa.BigInteger(), nullable=False),
        sa.Column("limit_output_tokens", sa.BigInteger(), nullable=False),
        sa.Column("limit_tool_calls", sa.Integer(), nullable=False),
        sa.Column("limit_tool_result_bytes", sa.BigInteger(), nullable=False),
        sa.Column("limit_artifact_bytes", sa.BigInteger(), nullable=False),
        sa.Column("limit_children", sa.Integer(), nullable=False),
        sa.Column("max_depth", sa.SmallInteger(), nullable=False),
        sa.Column("allow_child_agents", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed', 'cancelled')",
            name="ck_execution_runs_status",
        ),
        sa.CheckConstraint("limit_elapsed_ms > 0", name="ck_execution_runs_elapsed"),
        sa.CheckConstraint(
            "limit_model_turns >= 0 AND limit_input_tokens >= 0 "
            "AND limit_output_tokens >= 0 AND limit_tool_calls >= 0 "
            "AND limit_tool_result_bytes >= 0 AND limit_artifact_bytes >= 0 "
            "AND limit_children >= 0",
            name="ck_execution_runs_limits",
        ),
        sa.CheckConstraint("max_depth BETWEEN 0 AND 2", name="ck_execution_runs_depth"),
        sa.CheckConstraint(
            "(allow_child_agents AND limit_children > 0 AND max_depth > 0) OR "
            "(NOT allow_child_agents AND limit_children = 0)",
            name="ck_execution_runs_children",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_execution_governed_runs"),
        sa.UniqueConstraint("id", "task_id", name="uq_execution_runs_task"),
        sa.UniqueConstraint("request_fingerprint", name="uq_execution_runs_request"),
    )
    op.create_index(
        "ix_execution_runs_task_created",
        "execution_governed_runs",
        ["task_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "execution_agent_allocations",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", sa.String(length=128), nullable=False),
        sa.Column("agent_id", sa.String(length=128), nullable=False),
        sa.Column("role", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("parent_agent_id", sa.String(length=128), nullable=True),
        sa.Column("parent_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("depth", sa.SmallInteger(), nullable=False),
        sa.Column("allow_child_agents", sa.Boolean(), nullable=False),
        sa.Column("max_depth", sa.SmallInteger(), nullable=False),
        sa.Column("limit_elapsed_ms", sa.BigInteger(), nullable=False),
        sa.Column("limit_model_turns", sa.Integer(), nullable=False),
        sa.Column("limit_input_tokens", sa.BigInteger(), nullable=False),
        sa.Column("limit_output_tokens", sa.BigInteger(), nullable=False),
        sa.Column("limit_tool_calls", sa.Integer(), nullable=False),
        sa.Column("limit_tool_result_bytes", sa.BigInteger(), nullable=False),
        sa.Column("limit_artifact_bytes", sa.BigInteger(), nullable=False),
        sa.Column("limit_children", sa.Integer(), nullable=False),
        sa.Column("used_elapsed_ms", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("used_model_turns", sa.Integer(), server_default="0", nullable=False),
        sa.Column("used_input_tokens", sa.BigInteger(), server_default="0", nullable=True),
        sa.Column("used_output_tokens", sa.BigInteger(), server_default="0", nullable=True),
        sa.Column("used_tool_calls", sa.Integer(), server_default="0", nullable=False),
        sa.Column("used_tool_result_bytes", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("used_artifact_bytes", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("used_child_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("reserved_elapsed_ms", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("reserved_model_turns", sa.Integer(), server_default="0", nullable=False),
        sa.Column("reserved_input_tokens", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("reserved_output_tokens", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("reserved_tool_calls", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "reserved_tool_result_bytes", sa.BigInteger(), server_default="0", nullable=False
        ),
        sa.Column("reserved_artifact_bytes", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("reserved_child_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("next_seq_no", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "role IN ('orchestrator', 'planner', 'worker', 'reviewer')",
            name="ck_execution_allocations_role",
        ),
        sa.CheckConstraint(
            "status IN ('running', 'succeeded', 'failed', 'cancelled')",
            name="ck_execution_allocations_status",
        ),
        sa.CheckConstraint("depth BETWEEN 0 AND 2", name="ck_execution_allocations_depth"),
        sa.CheckConstraint("max_depth BETWEEN 0 AND 2", name="ck_execution_allocations_max_depth"),
        sa.CheckConstraint(
            "limit_elapsed_ms > 0 AND limit_model_turns >= 0 "
            "AND limit_input_tokens >= 0 AND limit_output_tokens >= 0 "
            "AND limit_tool_calls >= 0 AND limit_tool_result_bytes >= 0 "
            "AND limit_artifact_bytes >= 0 AND limit_children >= 0",
            name="ck_execution_allocations_limits",
        ),
        sa.CheckConstraint(
            "used_elapsed_ms >= 0 AND used_model_turns >= 0 "
            "AND (used_input_tokens IS NULL OR used_input_tokens >= 0) "
            "AND (used_output_tokens IS NULL OR used_output_tokens >= 0) "
            "AND used_tool_calls >= 0 AND used_tool_result_bytes >= 0 "
            "AND used_artifact_bytes >= 0 AND used_child_count >= 0",
            name="ck_execution_allocations_usage",
        ),
        sa.CheckConstraint(
            "reserved_elapsed_ms >= 0 AND reserved_model_turns >= 0 "
            "AND reserved_input_tokens >= 0 AND reserved_output_tokens >= 0 "
            "AND reserved_tool_calls >= 0 AND reserved_tool_result_bytes >= 0 "
            "AND reserved_artifact_bytes >= 0 AND reserved_child_count >= 0",
            name="ck_execution_allocations_reserved",
        ),
        sa.CheckConstraint("next_seq_no >= 0", name="ck_execution_allocations_seq"),
        sa.CheckConstraint(
            "(depth = 0 AND parent_agent_id IS NULL AND parent_event_id IS NULL) OR "
            "(depth > 0 AND parent_agent_id IS NOT NULL AND parent_event_id IS NOT NULL)",
            name="ck_execution_allocations_parent_shape",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "task_id"],
            ["execution_governed_runs.id", "execution_governed_runs.task_id"],
            name="fk_execution_allocations_run_task",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "task_id", "parent_agent_id"],
            [
                "execution_agent_allocations.run_id",
                "execution_agent_allocations.task_id",
                "execution_agent_allocations.agent_id",
            ],
            name="fk_execution_allocations_parent",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint(
            "run_id", "task_id", "agent_id", name="pk_execution_agent_allocations"
        ),
    )
    op.create_index(
        "ix_execution_allocations_run_status",
        "execution_agent_allocations",
        ["run_id", "status"],
        unique=False,
    )

    op.create_table(
        "execution_trace_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", sa.String(length=128), nullable=False),
        sa.Column("agent_id", sa.String(length=128), nullable=False),
        sa.Column("seq_no", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("parent_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("artifact_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("target_name", sa.String(length=80), nullable=True),
        sa.Column("provider_name", sa.String(length=80), nullable=True),
        sa.Column("model_name", sa.String(length=80), nullable=True),
        sa.Column("error_code", sa.String(length=80), nullable=True),
        sa.Column("duration_ms", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("model_turns", sa.Integer(), server_default="0", nullable=False),
        sa.Column("input_tokens", sa.BigInteger(), server_default="0", nullable=True),
        sa.Column("output_tokens", sa.BigInteger(), server_default="0", nullable=True),
        sa.Column("tool_calls", sa.Integer(), server_default="0", nullable=False),
        sa.Column("result_bytes", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("seq_no >= 0", name="ck_execution_events_seq"),
        sa.CheckConstraint(
            "kind IN ('run_started', 'run_finished', 'run_failed', 'node_started', "
            "'node_finished', 'node_failed', 'model_requested', 'model_result', "
            "'tool_requested', 'tool_result', 'artifact_produced', 'budget_denied', "
            "'permission_denied')",
            name="ck_execution_events_kind",
        ),
        sa.CheckConstraint(
            "status IN ('started', 'succeeded', 'failed', 'denied')",
            name="ck_execution_events_status",
        ),
        sa.CheckConstraint(
            "duration_ms >= 0 AND model_turns >= 0 AND tool_calls >= 0 "
            "AND result_bytes >= 0 AND (input_tokens IS NULL OR input_tokens >= 0) "
            "AND (output_tokens IS NULL OR output_tokens >= 0)",
            name="ck_execution_events_usage",
        ),
        sa.CheckConstraint(
            "(kind = 'run_started' AND seq_no = 0 AND parent_event_id IS NULL) OR "
            "(kind <> 'run_started' AND parent_event_id IS NOT NULL)",
            name="ck_execution_events_parent_shape",
        ),
        sa.CheckConstraint(
            "(kind = 'artifact_produced' AND artifact_id IS NOT NULL) OR "
            "(kind <> 'artifact_produced' AND artifact_id IS NULL)",
            name="ck_execution_events_artifact_shape",
        ),
        sa.CheckConstraint(
            "status <> 'denied' OR error_code IS NOT NULL",
            name="ck_execution_events_denial",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "task_id", "agent_id"],
            [
                "execution_agent_allocations.run_id",
                "execution_agent_allocations.task_id",
                "execution_agent_allocations.agent_id",
            ],
            name="fk_execution_events_allocation",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["parent_event_id", "run_id", "task_id"],
            [
                "execution_trace_events.id",
                "execution_trace_events.run_id",
                "execution_trace_events.task_id",
            ],
            name="fk_execution_events_parent",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_execution_trace_events"),
        sa.UniqueConstraint("id", "run_id", "task_id", name="uq_execution_events_run_task"),
        sa.UniqueConstraint(
            "id",
            "run_id",
            "task_id",
            "agent_id",
            name="uq_execution_events_agent",
        ),
        sa.UniqueConstraint("run_id", "agent_id", "seq_no", name="uq_execution_events_seq"),
    )
    op.create_index(
        "ix_execution_events_timeline",
        "execution_trace_events",
        ["run_id", "created_at", "id"],
        unique=False,
    )
    op.create_table(
        "execution_artifacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", sa.String(length=128), nullable=False),
        sa.Column("agent_id", sa.String(length=128), nullable=False),
        sa.Column("producer_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("media_type", sa.String(length=128), nullable=False),
        sa.Column("byte_size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("lifecycle_status", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.CheckConstraint("byte_size >= 0", name="ck_execution_artifacts_size"),
        sa.CheckConstraint(
            "kind IN ('article', 'markdown', 'html', 'image', 'report', 'checkpoint', 'other')",
            name="ck_execution_artifacts_kind",
        ),
        sa.CheckConstraint(
            "lifecycle_status IN ('active', 'superseded', 'deleted')",
            name="ck_execution_artifacts_status",
        ),
        sa.ForeignKeyConstraint(
            ["producer_event_id", "run_id", "task_id", "agent_id"],
            [
                "execution_trace_events.id",
                "execution_trace_events.run_id",
                "execution_trace_events.task_id",
                "execution_trace_events.agent_id",
            ],
            name="fk_execution_artifacts_event",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_execution_artifacts"),
        sa.UniqueConstraint("id", "run_id", "task_id", name="uq_execution_artifacts_run_task"),
    )
    op.create_index(
        "ix_execution_artifacts_run_created",
        "execution_artifacts",
        ["run_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "execution_budget_reservations",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_id", sa.String(length=128), nullable=False),
        sa.Column("agent_id", sa.String(length=128), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("reserved_elapsed_ms", sa.BigInteger(), nullable=False),
        sa.Column("reserved_model_turns", sa.Integer(), nullable=False),
        sa.Column("reserved_input_tokens", sa.BigInteger(), nullable=False),
        sa.Column("reserved_output_tokens", sa.BigInteger(), nullable=False),
        sa.Column("reserved_tool_calls", sa.Integer(), nullable=False),
        sa.Column("reserved_tool_result_bytes", sa.BigInteger(), nullable=False),
        sa.Column("reserved_artifact_bytes", sa.BigInteger(), nullable=False),
        sa.Column("actual_elapsed_ms", sa.BigInteger(), nullable=True),
        sa.Column("actual_model_turns", sa.Integer(), nullable=True),
        sa.Column("actual_input_tokens", sa.BigInteger(), nullable=True),
        sa.Column("actual_output_tokens", sa.BigInteger(), nullable=True),
        sa.Column("actual_tool_calls", sa.Integer(), nullable=True),
        sa.Column("actual_tool_result_bytes", sa.BigInteger(), nullable=True),
        sa.Column("actual_artifact_bytes", sa.BigInteger(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("reconciled_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('reserved', 'reconciled')",
            name="ck_execution_reservations_status",
        ),
        sa.CheckConstraint(
            "reserved_elapsed_ms >= 0 AND reserved_model_turns >= 0 "
            "AND reserved_input_tokens >= 0 AND reserved_output_tokens >= 0 "
            "AND reserved_tool_calls >= 0 AND reserved_tool_result_bytes >= 0 "
            "AND reserved_artifact_bytes >= 0",
            name="ck_execution_reservations_reserved",
        ),
        sa.ForeignKeyConstraint(
            ["run_id", "task_id", "agent_id"],
            [
                "execution_agent_allocations.run_id",
                "execution_agent_allocations.task_id",
                "execution_agent_allocations.agent_id",
            ],
            name="fk_execution_reservations_allocation",
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_execution_budget_reservations"),
    )
    op.create_index(
        "ix_execution_reservations_allocation",
        "execution_budget_reservations",
        ["run_id", "agent_id", "status"],
        unique=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    populated = any(
        bind.execute(sa.text(f"SELECT EXISTS (SELECT 1 FROM {table_name} LIMIT 1)")).scalar_one()
        for table_name in _TABLES
    )
    if populated:
        raise RuntimeError(
            "execution governance tables contain rows; destructive downgrade is disabled"
        )

    op.drop_index(
        "ix_execution_reservations_allocation",
        table_name="execution_budget_reservations",
    )
    op.drop_table("execution_budget_reservations")
    op.drop_index("ix_execution_artifacts_run_created", table_name="execution_artifacts")
    op.drop_table("execution_artifacts")
    op.drop_index("ix_execution_events_timeline", table_name="execution_trace_events")
    op.drop_table("execution_trace_events")
    op.drop_index(
        "ix_execution_allocations_run_status",
        table_name="execution_agent_allocations",
    )
    op.drop_table("execution_agent_allocations")
    op.drop_index("ix_execution_runs_task_created", table_name="execution_governed_runs")
    op.drop_table("execution_governed_runs")
