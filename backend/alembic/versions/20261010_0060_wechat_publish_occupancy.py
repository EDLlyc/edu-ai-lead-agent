"""Keep uncertain and successful publications from being submitted a second time."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261010_0060"
down_revision: str | None = "20261009_0059"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OCCUPIED = "status IN ('scheduled', 'submitting', 'publishing', 'outcome_unknown', 'succeeded')"


def upgrade() -> None:
    # Lock out concurrent inserts during preflight/index replacement. Never discard history to
    # make the unique index fit; operators must reconcile any existing conflicts explicitly.
    op.execute("LOCK TABLE wechat_publish_jobs IN SHARE ROW EXCLUSIVE MODE")
    op.execute(
        f"""DO $$ BEGIN
        IF EXISTS (
            SELECT 1 FROM wechat_publish_jobs WHERE {_OCCUPIED}
            GROUP BY account_id, media_id HAVING count(*) > 1
        ) THEN
            RAISE EXCEPTION 'Conflicting occupied WeChat drafts; reconcile history before 0060';
        END IF;
        END $$"""
    )
    op.add_column("wechat_publish_jobs", sa.Column("reconciled_by", sa.String(40), nullable=True))
    op.add_column(
        "wechat_publish_jobs", sa.Column("reconciliation_note", sa.String(500), nullable=True)
    )
    op.drop_index("uq_wechat_publish_jobs_open_draft", table_name="wechat_publish_jobs")
    op.create_index(
        "uq_wechat_publish_jobs_open_draft",
        "wechat_publish_jobs",
        ["account_id", "media_id"],
        unique=True,
        postgresql_where=sa.text(_OCCUPIED),
    )
    op.drop_constraint("ck_wechat_publish_jobs_publish_id", "wechat_publish_jobs", type_="check")
    # An owner can verify publication in WeChat after the submit response (and its ID) was lost.
    op.create_check_constraint(
        "ck_wechat_publish_jobs_publish_id",
        "wechat_publish_jobs",
        "status != 'publishing' OR publish_id IS NOT NULL",
    )


def downgrade() -> None:
    op.execute("LOCK TABLE wechat_publish_jobs IN SHARE ROW EXCLUSIVE MODE")
    op.execute("""DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM wechat_publish_jobs
                   WHERE reconciled_by IS NOT NULL OR status = 'outcome_unknown'
                      OR (status = 'succeeded' AND publish_id IS NULL)) THEN
            RAISE EXCEPTION 'Cannot downgrade unresolved or manually verified publications';
        END IF;
        END $$""")
    op.drop_constraint("ck_wechat_publish_jobs_publish_id", "wechat_publish_jobs", type_="check")
    op.create_check_constraint(
        "ck_wechat_publish_jobs_publish_id",
        "wechat_publish_jobs",
        "status NOT IN ('publishing', 'succeeded') OR publish_id IS NOT NULL",
    )
    op.drop_index("uq_wechat_publish_jobs_open_draft", table_name="wechat_publish_jobs")
    op.create_index(
        "uq_wechat_publish_jobs_open_draft",
        "wechat_publish_jobs",
        ["account_id", "media_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('scheduled', 'submitting', 'publishing')"),
    )

    op.drop_column("wechat_publish_jobs", "reconciliation_note")
    op.drop_column("wechat_publish_jobs", "reconciled_by")
