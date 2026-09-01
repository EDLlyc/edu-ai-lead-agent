"""Add immutable final-publication image-quality observations."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260901_0041"
down_revision: str | None = "20260831_0040"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_official_generated_visuals_id_run_sha",
        "official_account_generated_visuals",
        ["id", "run_id", "sha256"],
    )
    op.create_table(
        "official_account_generated_visual_evals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("generated_visual_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("publication_sha256", sa.String(64), nullable=False),
        sa.Column("decision", sa.String(24), nullable=False),
        sa.Column("hard_gate_passed", sa.Boolean(), nullable=False),
        sa.Column("manual_review_required", sa.Boolean(), nullable=False),
        sa.Column("evaluator_version", sa.String(80), nullable=False),
        sa.Column("audit_prompt_version", sa.String(80), nullable=False),
        sa.Column("rubric_version", sa.String(80), nullable=False),
        sa.Column("decision_policy_version", sa.String(80), nullable=False),
        sa.Column("request_fingerprint", sa.String(64), nullable=False),
        sa.Column("record_fingerprint", sa.String(64), nullable=False),
        sa.Column("provider", sa.String(80), nullable=True),
        sa.Column("model", sa.String(160), nullable=True),
        sa.Column("issue_codes", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "observation_snapshot",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name="pk_official_account_generated_visual_evals"),
        sa.ForeignKeyConstraint(
            ["generated_visual_id", "run_id", "publication_sha256"],
            [
                "official_account_generated_visuals.id",
                "official_account_generated_visuals.run_id",
                "official_account_generated_visuals.sha256",
            ],
            name="fk_official_generated_visual_evals_visual_run_sha",
            ondelete="CASCADE",
        ),
        sa.CheckConstraint(
            "publication_sha256 ~ '^[0-9a-f]{64}$'",
            name="ck_official_generated_visual_evals_sha",
        ),
        sa.CheckConstraint(
            "decision IN ('accepted', 'manual_review', 'rejected', 'unavailable')",
            name="ck_official_generated_visual_evals_decision",
        ),
        sa.CheckConstraint(
            "(decision = 'accepted' AND hard_gate_passed AND NOT manual_review_required) OR "
            "(decision = 'manual_review' AND hard_gate_passed AND manual_review_required) OR "
            "(decision = 'rejected' AND NOT hard_gate_passed AND NOT manual_review_required) OR "
            "(decision = 'unavailable' AND NOT hard_gate_passed AND manual_review_required)",
            name="ck_official_generated_visual_evals_decision_shape",
        ),
        sa.CheckConstraint(
            "request_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_official_generated_visual_evals_fingerprint",
        ),
        sa.CheckConstraint(
            "record_fingerprint ~ '^[0-9a-f]{64}$'",
            name="ck_official_generated_visual_evals_record_fingerprint",
        ),
        sa.CheckConstraint(
            "char_length(evaluator_version) BETWEEN 1 AND 80 "
            "AND char_length(audit_prompt_version) BETWEEN 1 AND 80 "
            "AND char_length(rubric_version) BETWEEN 1 AND 80 "
            "AND char_length(decision_policy_version) BETWEEN 1 AND 80",
            name="ck_official_generated_visual_evals_versions",
        ),
        sa.CheckConstraint(
            "(decision = 'unavailable' AND provider IS NULL AND model IS NULL) OR "
            "(decision <> 'unavailable' AND char_length(provider) BETWEEN 1 AND 80 "
            "AND char_length(model) BETWEEN 1 AND 160)",
            name="ck_official_generated_visual_evals_provider_shape",
        ),
        sa.CheckConstraint(
            "jsonb_typeof(issue_codes) = 'array' AND jsonb_array_length(issue_codes) <= 16 "
            "AND jsonb_typeof(observation_snapshot) = 'array' "
            "AND jsonb_array_length(observation_snapshot) = 5",
            name="ck_official_generated_visual_evals_snapshot_shape",
        ),
        sa.CheckConstraint(
            "decision <> 'accepted' OR jsonb_array_length(issue_codes) = 0",
            name="ck_official_generated_visual_evals_accepted_issues",
        ),
        sa.UniqueConstraint(
            "generated_visual_id",
            name="uq_official_generated_visual_evals_visual",
        ),
        sa.UniqueConstraint(
            "request_fingerprint",
            name="uq_official_generated_visual_evals_request",
        ),
        sa.UniqueConstraint(
            "record_fingerprint",
            name="uq_official_generated_visual_evals_record_fingerprint",
        ),
    )
    op.create_index(
        "ix_official_generated_visual_evals_run",
        "official_account_generated_visual_evals",
        ["run_id"],
        unique=False,
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM official_account_generated_visual_evals) "
            "THEN RAISE EXCEPTION "
            "'cannot downgrade official-account generated visual eval artifacts'; "
            "END IF; END $$"
        )
    )
    op.drop_index(
        "ix_official_generated_visual_evals_run",
        table_name="official_account_generated_visual_evals",
    )
    op.drop_table("official_account_generated_visual_evals")
    op.drop_constraint(
        "uq_official_generated_visuals_id_run_sha",
        "official_account_generated_visuals",
        type_="unique",
    )
