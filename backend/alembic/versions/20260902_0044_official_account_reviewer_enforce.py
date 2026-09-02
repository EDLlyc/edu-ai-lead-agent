"""Add one-repair Reviewer enforce lineage and durable intent."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260902_0044"
down_revision: str | None = "20260902_0043"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "official_account_article_versions",
        sa.Column("revision_no", sa.SmallInteger(), server_default="1", nullable=False),
    )
    op.add_column(
        "official_account_article_versions",
        sa.Column("repair_of_article_version_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.drop_constraint(
        "uq_official_account_article_versions_run",
        "official_account_article_versions",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_official_account_article_versions_lineage",
        "official_account_article_versions",
        ["id", "run_id", "version"],
    )
    op.create_unique_constraint(
        "uq_official_account_article_versions_run_revision",
        "official_account_article_versions",
        ["run_id", "version", "revision_no"],
    )
    op.create_check_constraint(
        "ck_official_account_article_versions_revision",
        "official_account_article_versions",
        "(revision_no = 1 AND repair_of_article_version_id IS NULL) OR "
        "(revision_no = 2 AND repair_of_article_version_id IS NOT NULL)",
    )
    op.create_foreign_key(
        "fk_official_account_article_versions_repair_of",
        "official_account_article_versions",
        "official_account_article_versions",
        ["repair_of_article_version_id", "run_id", "version"],
        ["id", "run_id", "version"],
        ondelete="RESTRICT",
    )

    op.create_unique_constraint(
        "uq_official_review_requests_lineage",
        "official_account_review_requests",
        ["id", "run_id", "article_version_id"],
    )
    op.drop_constraint(
        "fk_official_account_review_records_request_id",
        "official_account_review_records",
        type_="foreignkey",
    )
    op.add_column(
        "official_account_review_records",
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "official_account_review_records",
        sa.Column("article_version_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE official_account_review_records AS record "
            "SET run_id = request.run_id, article_version_id = request.article_version_id "
            "FROM official_account_review_requests AS request "
            "WHERE request.id = record.request_id"
        )
    )
    op.alter_column("official_account_review_records", "run_id", nullable=False)
    op.alter_column("official_account_review_records", "article_version_id", nullable=False)
    op.create_unique_constraint(
        "uq_official_review_records_lineage",
        "official_account_review_records",
        ["id", "run_id", "article_version_id"],
    )
    op.create_foreign_key(
        "fk_official_review_records_request_lineage",
        "official_account_review_records",
        "official_account_review_requests",
        ["request_id", "run_id", "article_version_id"],
        ["id", "run_id", "article_version_id"],
        ondelete="RESTRICT",
    )

    op.create_table(
        "official_account_repair_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_article_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("repaired_article_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_review_request_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("directive_fingerprint", sa.String(64), nullable=False),
        sa.Column("directive_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("provider", sa.String(40), nullable=False),
        sa.Column("model", sa.String(120), nullable=False),
        sa.Column("repair_policy_version", sa.String(80), nullable=False),
        sa.Column("execution_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("execution_task_id", sa.String(128), nullable=True),
        sa.Column("writer_agent_id", sa.String(128), nullable=True),
        sa.Column("writer_parent_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reservation_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("request_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("error_code", sa.String(80), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("calling_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_official_account_repair_requests"),
        sa.ForeignKeyConstraint(
            ["source_article_version_id", "run_id"],
            ["official_account_article_versions.id", "official_account_article_versions.run_id"],
            name="fk_official_account_repair_requests_source_article",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["repaired_article_version_id", "run_id"],
            ["official_account_article_versions.id", "official_account_article_versions.run_id"],
            name="fk_official_account_repair_requests_repaired_article",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["source_review_request_id", "run_id", "source_article_version_id"],
            [
                "official_account_review_requests.id",
                "official_account_review_requests.run_id",
                "official_account_review_requests.article_version_id",
            ],
            name="fk_official_account_repair_requests_review_lineage",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["execution_run_id", "execution_task_id", "writer_agent_id"],
            [
                "execution_agent_allocations.run_id",
                "execution_agent_allocations.task_id",
                "execution_agent_allocations.agent_id",
            ],
            name="fk_official_account_repair_requests_writer_allocation",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["writer_parent_event_id", "execution_run_id", "execution_task_id", "writer_agent_id"],
            [
                "execution_trace_events.id",
                "execution_trace_events.run_id",
                "execution_trace_events.task_id",
                "execution_trace_events.agent_id",
            ],
            name="fk_official_account_repair_requests_parent_event",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["request_event_id", "execution_run_id", "execution_task_id", "writer_agent_id"],
            [
                "execution_trace_events.id",
                "execution_trace_events.run_id",
                "execution_trace_events.task_id",
                "execution_trace_events.agent_id",
            ],
            name="fk_official_account_repair_requests_request_event",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["reservation_id", "execution_run_id", "execution_task_id", "writer_agent_id"],
            [
                "execution_budget_reservations.id",
                "execution_budget_reservations.run_id",
                "execution_budget_reservations.task_id",
                "execution_budget_reservations.agent_id",
            ],
            name="fk_official_account_repair_requests_reservation",
            ondelete="RESTRICT",
        ),
        sa.UniqueConstraint("run_id", name="uq_official_account_repair_requests_run"),
        sa.UniqueConstraint(
            "source_article_version_id", name="uq_official_account_repair_requests_source_article"
        ),
        sa.UniqueConstraint(
            "request_fingerprint", name="uq_official_account_repair_requests_request"
        ),
        sa.UniqueConstraint(
            "repaired_article_version_id", name="uq_official_account_repair_requests_repaired"
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'calling', 'completed', 'result_unknown')",
            name="ck_official_account_repair_requests_status",
        ),
        sa.CheckConstraint("attempt_number > 0", name="ck_official_account_repair_attempt"),
        sa.CheckConstraint(
            "request_fingerprint ~ '^[0-9a-f]{64}$' AND directive_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_official_account_repair_fingerprints",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(directive_snapshot) = 'array' "
            "AND jsonb_array_length(directive_snapshot) BETWEEN 1 AND 16",
            name="ck_official_account_repair_directives",
        ),
        sa.CheckConstraint(
            "(status = 'pending' AND execution_run_id IS NULL AND calling_at IS NULL "
            "AND completed_at IS NULL AND repaired_article_version_id IS NULL) OR "
            "(status = 'calling' AND execution_run_id IS NOT NULL AND calling_at IS NOT NULL "
            "AND completed_at IS NULL AND repaired_article_version_id IS NULL) OR "
            "(status = 'completed' AND execution_run_id IS NOT NULL AND calling_at IS NOT NULL "
            "AND completed_at IS NOT NULL AND repaired_article_version_id IS NOT NULL) OR "
            "(status = 'result_unknown' AND execution_run_id IS NOT NULL "
            "AND calling_at IS NOT NULL AND completed_at IS NOT NULL "
            "AND repaired_article_version_id IS NULL)",
            name="ck_official_account_repair_lifecycle",
        ),
        sa.CheckConstraint(
            "(execution_run_id IS NULL AND execution_task_id IS NULL "
            "AND writer_agent_id IS NULL AND writer_parent_event_id IS NULL "
            "AND reservation_id IS NULL AND request_event_id IS NULL) OR "
            "(execution_run_id IS NOT NULL AND execution_task_id IS NOT NULL "
            "AND writer_agent_id IS NOT NULL AND writer_parent_event_id IS NOT NULL "
            "AND reservation_id IS NOT NULL AND request_event_id IS NOT NULL)",
            name="ck_official_account_repair_execution_shape",
        ),
        sa.CheckConstraint(
            "(status = 'result_unknown' AND error_code IS NOT NULL) OR "
            "(status <> 'result_unknown' AND error_code IS NULL)",
            name="ck_official_account_repair_error_shape",
        ),
    )
    op.create_index(
        "ix_official_account_repair_requests_status",
        "official_account_repair_requests",
        ["run_id", "status"],
        unique=False,
    )

    op.add_column(
        "official_account_article_runs",
        sa.Column("active_review_record_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_check_constraint(
        "ck_official_account_article_runs_active_review_shape",
        "official_account_article_runs",
        "active_review_record_id IS NULL OR active_article_version_id IS NOT NULL",
    )
    op.create_foreign_key(
        "fk_official_account_article_runs_active_review_record",
        "official_account_article_runs",
        "official_account_review_records",
        ["active_review_record_id", "id", "active_article_version_id"],
        ["id", "run_id", "article_version_id"],
        ondelete="RESTRICT",
    )
    op.add_column(
        "official_account_render_versions",
        sa.Column("review_record_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_official_account_render_versions_review_record_id",
        "official_account_render_versions",
        "official_account_review_records",
        ["review_record_id", "run_id", "article_version_id"],
        ["id", "run_id", "article_version_id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    connection = op.get_bind()
    evidence = connection.execute(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM official_account_repair_requests) "
            "OR EXISTS (SELECT 1 FROM official_account_article_versions WHERE revision_no = 2) "
            "OR EXISTS (SELECT 1 FROM official_account_article_runs "
            "WHERE version_bundle->>'reviewer_mode' = 'enforce') "
            "OR EXISTS (SELECT 1 FROM execution_agent_allocations "
            "WHERE task_id LIKE 'official.review:%' "
            "AND ((agent_id = 'official.review.orchestrator' AND limit_children = 4) "
            "OR agent_id IN ('official.writer.repair', 'official.reviewer.r2')))"
        )
    ).scalar_one()
    if evidence:
        raise RuntimeError("cannot downgrade Reviewer enforce while durable evidence exists")

    op.drop_constraint(
        "fk_official_account_render_versions_review_record_id",
        "official_account_render_versions",
        type_="foreignkey",
    )
    op.drop_column("official_account_render_versions", "review_record_id")
    op.drop_constraint(
        "fk_official_account_article_runs_active_review_record",
        "official_account_article_runs",
        type_="foreignkey",
    )
    op.drop_constraint(
        "ck_official_account_article_runs_active_review_shape",
        "official_account_article_runs",
        type_="check",
    )
    op.drop_column("official_account_article_runs", "active_review_record_id")
    op.drop_index(
        "ix_official_account_repair_requests_status",
        table_name="official_account_repair_requests",
    )
    op.drop_table("official_account_repair_requests")
    op.drop_constraint(
        "fk_official_review_records_request_lineage",
        "official_account_review_records",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_official_review_records_lineage",
        "official_account_review_records",
        type_="unique",
    )
    op.drop_column("official_account_review_records", "article_version_id")
    op.drop_column("official_account_review_records", "run_id")
    op.create_foreign_key(
        "fk_official_account_review_records_request_id",
        "official_account_review_records",
        "official_account_review_requests",
        ["request_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.drop_constraint(
        "uq_official_review_requests_lineage",
        "official_account_review_requests",
        type_="unique",
    )
    op.drop_constraint(
        "fk_official_account_article_versions_repair_of",
        "official_account_article_versions",
        type_="foreignkey",
    )
    op.drop_constraint(
        "ck_official_account_article_versions_revision",
        "official_account_article_versions",
        type_="check",
    )
    op.drop_constraint(
        "uq_official_account_article_versions_run_revision",
        "official_account_article_versions",
        type_="unique",
    )
    op.drop_constraint(
        "uq_official_account_article_versions_lineage",
        "official_account_article_versions",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_official_account_article_versions_run",
        "official_account_article_versions",
        ["run_id", "version"],
    )
    op.drop_column("official_account_article_versions", "repair_of_article_version_id")
    op.drop_column("official_account_article_versions", "revision_no")
