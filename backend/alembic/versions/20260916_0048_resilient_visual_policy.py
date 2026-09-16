"""Allow V3 advisory duplicate body bytes while preserving V1/V2 application gates."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260916_0048"
down_revision: str | None = "20260914_0047"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BODY_CHECKSUM_INDEX = "uq_official_account_local_media_body_checksum"


def upgrade() -> None:
    # V1/V2 uniqueness remains an application/repository invariant. PostgreSQL cannot express
    # the policy-dependent condition in a partial index without denormalizing the frozen run.
    op.drop_index(_BODY_CHECKSUM_INDEX, table_name="official_account_local_media")


def downgrade() -> None:
    has_resilient_data = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT EXISTS (SELECT 1 FROM official_account_article_runs "
                "WHERE version_bundle ->> 'visual_pipeline_version' = "
                "'official-account-visual-pipeline-v3-resilient-advisory')"
            )
        )
        .scalar_one()
    )
    if has_resilient_data:
        raise RuntimeError("cannot downgrade resilient visual policy data")
    op.create_index(
        _BODY_CHECKSUM_INDEX,
        "official_account_local_media",
        ["run_id", "sha256"],
        unique=True,
        postgresql_where=sa.text("role = 'body'"),
    )
