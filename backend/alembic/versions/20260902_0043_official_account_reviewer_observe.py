"""Add durable governed official-account Reviewer observations."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260902_0043"
down_revision: str | None = "20260901_0042"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_execution_reservations_identity",
        "execution_budget_reservations",
        ["id", "run_id", "task_id", "agent_id"],
    )
    op.create_unique_constraint(
        "uq_execution_artifacts_producer",
        "execution_artifacts",
        ["id", "producer_event_id"],
    )
    op.create_table(
        "official_account_review_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("article_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("article_sha256", sa.String(64), nullable=False),
        sa.Column("source_sha256", sa.String(64), nullable=False),
        sa.Column("brand_sha256", sa.String(64), nullable=False),
        sa.Column("request_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("reviewer_version", sa.String(160), nullable=False),
        sa.Column("prompt_version", sa.String(160), nullable=False),
        sa.Column("request_schema_version", sa.String(80), nullable=False),
        sa.Column("verdict_schema_version", sa.String(80), nullable=False),
        sa.Column("rubric_version", sa.String(80), nullable=False),
        sa.Column("review_policy_version", sa.String(80), nullable=False),
        sa.Column("repair_policy_version", sa.String(80), nullable=False),
        sa.Column("article_artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("brand_artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("execution_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("execution_task_id", sa.String(128), nullable=True),
        sa.Column("reviewer_agent_id", sa.String(128), nullable=True),
        sa.Column("reviewer_parent_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reservation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("request_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("calling_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_official_account_review_requests"),
        sa.ForeignKeyConstraint(
            ["article_version_id", "run_id"],
            ["official_account_article_versions.id", "official_account_article_versions.run_id"],
            name="fk_official_review_requests_article_run",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["execution_run_id", "execution_task_id", "reviewer_agent_id"],
            [
                "execution_agent_allocations.run_id",
                "execution_agent_allocations.task_id",
                "execution_agent_allocations.agent_id",
            ],
            name="fk_official_review_requests_reviewer_allocation",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            [
                "reviewer_parent_event_id",
                "execution_run_id",
                "execution_task_id",
                "reviewer_agent_id",
            ],
            [
                "execution_trace_events.id",
                "execution_trace_events.run_id",
                "execution_trace_events.task_id",
                "execution_trace_events.agent_id",
            ],
            name="fk_official_review_requests_parent_event",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["request_event_id", "execution_run_id", "execution_task_id", "reviewer_agent_id"],
            [
                "execution_trace_events.id",
                "execution_trace_events.run_id",
                "execution_trace_events.task_id",
                "execution_trace_events.agent_id",
            ],
            name="fk_official_review_requests_request_event",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reservation_id", "execution_run_id", "execution_task_id", "reviewer_agent_id"],
            [
                "execution_budget_reservations.id",
                "execution_budget_reservations.run_id",
                "execution_budget_reservations.task_id",
                "execution_budget_reservations.agent_id",
            ],
            name="fk_official_review_requests_reservation",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["article_artifact_id"],
            ["execution_artifacts.id"],
            name="fk_official_review_requests_article_artifact",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_artifact_id"],
            ["execution_artifacts.id"],
            name="fk_official_review_requests_source_artifact",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["brand_artifact_id"],
            ["execution_artifacts.id"],
            name="fk_official_review_requests_brand_artifact",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint(
            "run_id", "article_version_id", name="uq_official_review_requests_article"
        ),
        sa.UniqueConstraint("request_fingerprint", name="uq_official_review_requests_fingerprint"),
        sa.CheckConstraint(
            "status IN ('pending', 'calling', 'completed', 'result_unknown')",
            name="ck_official_review_requests_status",
        ),
        sa.CheckConstraint(
            "attempt_number > 0",
            name="ck_official_review_requests_attempt_number",
        ),
        sa.CheckConstraint(
            "request_fingerprint ~ '^[0-9a-f]{64}$' "
            "AND article_sha256 ~ '^[0-9a-f]{64}$' "
            "AND source_sha256 ~ '^[0-9a-f]{64}$' "
            "AND brand_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_official_review_requests_fingerprints",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(request_snapshot) = 'object'",
            name="ck_official_review_requests_snapshot",
        ),
        sa.CheckConstraint(
            "(status = 'pending' AND execution_run_id IS NULL AND calling_at IS NULL "
            "AND completed_at IS NULL) OR "
            "(status = 'calling' AND execution_run_id IS NOT NULL AND calling_at IS NOT NULL "
            "AND completed_at IS NULL) OR "
            "(status IN ('completed', 'result_unknown') AND execution_run_id IS NOT NULL "
            "AND calling_at IS NOT NULL AND completed_at IS NOT NULL)",
            name="ck_official_review_requests_lifecycle",
        ),
        sa.CheckConstraint(
            "(execution_run_id IS NULL AND execution_task_id IS NULL "
            "AND reviewer_agent_id IS NULL AND reviewer_parent_event_id IS NULL "
            "AND reservation_id IS NULL AND request_event_id IS NULL) OR "
            "(execution_run_id IS NOT NULL AND execution_task_id IS NOT NULL "
            "AND reviewer_agent_id IS NOT NULL AND reviewer_parent_event_id IS NOT NULL "
            "AND reservation_id IS NOT NULL AND request_event_id IS NOT NULL)",
            name="ck_official_review_requests_execution_shape",
        ),
        sa.CheckConstraint(
            "(status = 'result_unknown' AND error_code IS NOT NULL) OR "
            "(status <> 'result_unknown' AND error_code IS NULL)",
            name="ck_official_review_requests_error_shape",
        ),
    )
    op.create_index(
        "ix_official_review_requests_run_status",
        "official_account_review_requests",
        ["run_id", "status"],
        unique=False,
    )

    op.create_table(
        "official_account_review_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("decision", sa.String(24), nullable=False),
        sa.Column("record_fingerprint", sa.String(64), nullable=False),
        sa.Column("issue_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("unavailable_reason", sa.String(40), nullable=True),
        sa.Column("provider_request_id", sa.String(200), nullable=True),
        sa.Column("prompt_tokens", sa.BigInteger(), nullable=True),
        sa.Column("completion_tokens", sa.BigInteger(), nullable=True),
        sa.Column("reasoning_tokens", sa.BigInteger(), nullable=True),
        sa.Column("latency_ms", sa.BigInteger(), nullable=False),
        sa.Column("validation_corrections", sa.Integer(), nullable=False),
        sa.Column("execution_artifact_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("execution_event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_official_account_review_records"),
        sa.ForeignKeyConstraint(
            ["request_id"],
            ["official_account_review_requests.id"],
            name="fk_official_account_review_records_request_id",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["execution_artifact_id", "execution_event_id"],
            ["execution_artifacts.id", "execution_artifacts.producer_event_id"],
            name="fk_official_account_review_records_execution_artifact_id",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("request_id", name="uq_official_review_records_request"),
        sa.UniqueConstraint("record_fingerprint", name="uq_official_review_records_fingerprint"),
        sa.UniqueConstraint(
            "execution_artifact_id", name="uq_official_review_records_execution_artifact"
        ),
        sa.CheckConstraint(
            "decision IN ('accepted', 'manual_review', 'rejected', 'unavailable')",
            name="ck_official_review_records_decision",
        ),
        sa.CheckConstraint(
            "record_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_official_review_records_fingerprint",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(issue_snapshot) = 'array'",
            name="ck_official_review_records_issues",
        ),
        sa.CheckConstraint(
            "prompt_tokens IS NULL OR prompt_tokens >= 0",
            name="ck_official_review_records_prompt_tokens",
        ),
        sa.CheckConstraint(
            "completion_tokens IS NULL OR completion_tokens >= 0",
            name="ck_official_review_records_completion_tokens",
        ),
        sa.CheckConstraint(
            "reasoning_tokens IS NULL OR reasoning_tokens >= 0",
            name="ck_official_review_records_reasoning_tokens",
        ),
        sa.CheckConstraint(
            "latency_ms >= 0 AND validation_corrections >= 0",
            name="ck_official_review_records_usage",
        ),
        sa.CheckConstraint(
            "(decision = 'unavailable' AND unavailable_reason IS NOT NULL "
            "AND jsonb_array_length(issue_snapshot) = 0) OR "
            "(decision <> 'unavailable' AND unavailable_reason IS NULL)",
            name="ck_official_review_records_unavailable",
        ),
    )


def downgrade() -> None:
    connection = op.get_bind()
    request_count = connection.execute(
        sa.text("SELECT count(*) FROM official_account_review_requests")
    ).scalar_one()
    record_count = connection.execute(
        sa.text("SELECT count(*) FROM official_account_review_records")
    ).scalar_one()
    execution_binding_count = connection.execute(
        sa.text(
            "SELECT count(*) FROM execution_governed_runs WHERE task_id LIKE 'official.review:%'"
        )
    ).scalar_one()
    if request_count or record_count or execution_binding_count:
        raise RuntimeError(
            "refusing to drop populated official-account Reviewer observations or execution "
            "bindings"
        )
    op.drop_table("official_account_review_records")
    op.drop_index(
        "ix_official_review_requests_run_status",
        table_name="official_account_review_requests",
    )
    op.drop_table("official_account_review_requests")
    op.drop_constraint(
        "uq_execution_artifacts_producer",
        "execution_artifacts",
        type_="unique",
    )
    op.drop_constraint(
        "uq_execution_reservations_identity",
        "execution_budget_reservations",
        type_="unique",
    )
