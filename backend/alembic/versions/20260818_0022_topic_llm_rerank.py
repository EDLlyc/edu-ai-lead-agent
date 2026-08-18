"""Add immutable topic rerank config, ranks, and typed audit records."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260818_0022"
down_revision: str | None = "20260815_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DISABLED_SNAPSHOT = (
    '{"candidate_limit":8,"enabled":false,'
    '"fallback_policy":"deterministic_base_order",'
    '"max_output_tokens":1024,"model":"none",'
    '"policy_version":"topic-rerank-v1","provider":"disabled","temperature":0.0}'
)
_DISABLED_FINGERPRINT = "919acf47899b5068d71f050e3ef0afe1c1ac3877680ce9803994024a3ef2773e"


def upgrade() -> None:
    for table_name in ("topic_selection_runs", "content_slot_runs"):
        op.add_column(
            table_name,
            sa.Column(
                "rerank_config_snapshot",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=True,
            ),
        )
        op.add_column(
            table_name,
            sa.Column(
                "rerank_config_fingerprint",
                sa.String(length=64),
                nullable=True,
            ),
        )
        op.execute(
            sa.text(
                f"UPDATE {table_name} "
                "SET rerank_config_snapshot = CAST(:snapshot AS jsonb), "
                "rerank_config_fingerprint = :fingerprint"
            ).bindparams(
                snapshot=_DISABLED_SNAPSHOT,
                fingerprint=_DISABLED_FINGERPRINT,
            )
        )
        op.alter_column(table_name, "rerank_config_snapshot", nullable=False)
        op.alter_column(table_name, "rerank_config_fingerprint", nullable=False)

    for table_name in ("topic_scores", "content_slot_scores"):
        op.add_column(table_name, sa.Column("deterministic_rank", sa.Integer(), nullable=True))
        op.execute(sa.text(f"UPDATE {table_name} SET deterministic_rank = rank"))
        op.alter_column(table_name, "deterministic_rank", nullable=False)
        op.create_check_constraint(
            f"ck_{table_name}_deterministic_rank",
            table_name,
            "deterministic_rank >= 1",
        )

    op.create_table(
        "topic_rerank_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("topic_selection_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("content_slot_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("policy_version", sa.String(length=80), nullable=False),
        sa.Column("provider", sa.String(length=40), nullable=False),
        sa.Column("model", sa.String(length=120), nullable=False),
        sa.Column("outcome", sa.String(length=20), nullable=False),
        sa.Column("failure_code", sa.String(length=80), nullable=True),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("base_order", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("final_order", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("reasons", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("prompt_fingerprint", sa.String(length=64), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name="pk_topic_rerank_records"),
        sa.ForeignKeyConstraint(
            ["topic_selection_run_id"],
            ["topic_selection_runs.id"],
            name="fk_topic_rerank_records_topic_selection_run_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["content_slot_run_id"],
            ["content_slot_runs.id"],
            name="fk_topic_rerank_records_content_slot_run_id",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "(topic_selection_run_id IS NULL) <> (content_slot_run_id IS NULL)",
            name="ck_topic_rerank_records_origin_xor",
        ),
        sa.CheckConstraint(
            "outcome IN ('applied', 'skipped', 'fallback')",
            name="ck_topic_rerank_records_outcome",
        ),
        sa.CheckConstraint(
            "(outcome = 'fallback') = (failure_code IS NOT NULL)",
            name="ck_topic_rerank_records_failure_state",
        ),
        sa.CheckConstraint(
            "candidate_count BETWEEN 0 AND 8",
            name="ck_topic_rerank_records_candidate_count",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(base_order) = 'array' AND "
            "jsonb_typeof(final_order) = 'array' AND jsonb_typeof(reasons) = 'object'",
            name="ck_topic_rerank_records_json_shapes",
        ),
        sa.CheckConstraint(
            "prompt_tokens >= 0 AND completion_tokens >= 0 "
            "AND reasoning_tokens >= 0 AND latency_ms >= 0",
            name="ck_topic_rerank_records_usage",
        ),
    )
    op.create_index(
        "uq_topic_rerank_records_daily_run",
        "topic_rerank_records",
        ["topic_selection_run_id"],
        unique=True,
        postgresql_where=sa.text("topic_selection_run_id IS NOT NULL"),
    )
    op.create_index(
        "uq_topic_rerank_records_slot_run",
        "topic_rerank_records",
        ["content_slot_run_id"],
        unique=True,
        postgresql_where=sa.text("content_slot_run_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_topic_rerank_records_slot_run", table_name="topic_rerank_records")
    op.drop_index("uq_topic_rerank_records_daily_run", table_name="topic_rerank_records")
    op.drop_table("topic_rerank_records")
    for table_name in ("content_slot_scores", "topic_scores"):
        op.drop_constraint(f"ck_{table_name}_deterministic_rank", table_name, type_="check")
        op.drop_column(table_name, "deterministic_rank")
    for table_name in ("content_slot_runs", "topic_selection_runs"):
        op.drop_column(table_name, "rerank_config_fingerprint")
        op.drop_column(table_name, "rerank_config_snapshot")
