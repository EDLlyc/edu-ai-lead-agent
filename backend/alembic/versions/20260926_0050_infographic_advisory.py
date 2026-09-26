"""Add forward-only advisory quality evidence to infographic jobs."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260926_0050"
down_revision: str | None = "20260923_0049"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ALLOWED_CODES = (
    '["advisory_unverified","copy_deterministic_rejected",'
    '"copy_audit_rejected","copy_audit_unavailable",'
    '"copy_audit_schema_invalid","layout_unverified",'
    '"layout_overflow","body_ocr_failed","body_ocr_unavailable",'
    '"footer_ocr_unavailable","visual_failed","visual_unavailable",'
    '"brand_unverified"]'
)


def upgrade() -> None:
    op.add_column(
        "news_infographic_jobs",
        sa.Column("quality_mode", sa.String(16), nullable=False, server_default="strict"),
    )
    op.add_column(
        "news_infographic_jobs",
        sa.Column(
            "warning_codes",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )
    op.add_column(
        "news_infographic_jobs",
        sa.Column("warning_notice_version", sa.String(64), nullable=True),
    )
    op.add_column(
        "news_infographic_jobs",
        sa.Column("copy_candidate_snapshot", postgresql.JSONB(), nullable=True),
    )
    op.add_column(
        "news_infographic_jobs",
        sa.Column("copy_audit_snapshot", postgresql.JSONB(), nullable=True),
    )
    op.create_check_constraint(
        op.f("ck_news_infographic_jobs_quality_mode"),
        "news_infographic_jobs",
        "quality_mode IN ('strict', 'advisory')",
    )
    op.create_check_constraint(
        op.f("ck_news_infographic_jobs_warning_codes"),
        "news_infographic_jobs",
        "jsonb_typeof(warning_codes) = 'array' "
        "AND jsonb_array_length(warning_codes) <= 16 "
        f"AND warning_codes <@ '{_ALLOWED_CODES}'::jsonb",
    )
    op.create_check_constraint(
        op.f("ck_news_infographic_jobs_advisory_shape"),
        "news_infographic_jobs",
        "(quality_mode = 'strict' AND warning_codes = '[]'::jsonb "
        "AND warning_notice_version IS NULL) OR "
        "(quality_mode = 'advisory' AND warning_notice_version IS NOT NULL "
        "AND length(warning_notice_version) > 0 "
        "AND (status <> 'ready' OR warning_codes @> "
        '\'["advisory_unverified","layout_unverified"]\'::jsonb))',
    )


def downgrade() -> None:
    # Removing these columns with advisory rows would erase the only durable
    # explanation for why a failed/unchecked audit did not veto a send.
    op.execute(
        sa.text(
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM news_infographic_jobs "
            "WHERE quality_mode = 'advisory' OR warning_codes <> '[]'::jsonb "
            "OR warning_notice_version IS NOT NULL "
            "OR copy_candidate_snapshot IS NOT NULL OR copy_audit_snapshot IS NOT NULL) THEN "
            "RAISE EXCEPTION 'refusing to discard infographic advisory evidence'; "
            "END IF; END $$"
        )
    )
    op.drop_constraint(
        op.f("ck_news_infographic_jobs_advisory_shape"), "news_infographic_jobs", type_="check"
    )
    op.drop_constraint(
        op.f("ck_news_infographic_jobs_warning_codes"), "news_infographic_jobs", type_="check"
    )
    op.drop_constraint(
        op.f("ck_news_infographic_jobs_quality_mode"), "news_infographic_jobs", type_="check"
    )
    op.drop_column("news_infographic_jobs", "warning_notice_version")
    op.drop_column("news_infographic_jobs", "copy_audit_snapshot")
    op.drop_column("news_infographic_jobs", "copy_candidate_snapshot")
    op.drop_column("news_infographic_jobs", "warning_codes")
    op.drop_column("news_infographic_jobs", "quality_mode")
