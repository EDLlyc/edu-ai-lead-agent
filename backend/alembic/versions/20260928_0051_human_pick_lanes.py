"""Allow operator human picks as one-item slot runs with their own delivery lane."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260928_0051"
down_revision: str | None = "20260926_0050"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LANE_COLUMNS = ["business_date", "timezone", "content_slot", "recipient_id", "provider", "mode"]


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_content_slot_runs_ck_content_slot_runs_trigger"),
        "content_slot_runs",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_content_slot_runs_ck_content_slot_runs_trigger"),
        "content_slot_runs",
        "trigger IN ('manual', 'scheduled', 'human')",
    )
    # Every existing window is the shared scheduled lane of its slot. A human pick gets its own
    # lane so it can start immediately without changing the immutable scheduled window times.
    op.add_column(
        "wecom_delivery_windows",
        sa.Column("lane_key", sa.String(40), nullable=False, server_default="slot"),
    )
    op.create_check_constraint(
        op.f("ck_wecom_delivery_windows_ck_wecom_delivery_windows_lane_key"),
        "wecom_delivery_windows",
        "lane_key = 'slot' OR lane_key ~ '^human-[0-9a-f]{32}$'",
    )
    op.drop_constraint(
        op.f("uq_wecom_delivery_windows_lane"), "wecom_delivery_windows", type_="unique"
    )
    op.create_unique_constraint(
        op.f("uq_wecom_delivery_windows_lane"),
        "wecom_delivery_windows",
        [*_LANE_COLUMNS, "lane_key"],
    )


def downgrade() -> None:
    # Human picks own formal delivery history; never drop it silently.
    op.execute(
        sa.text(
            "DO $$ BEGIN "
            "IF EXISTS (SELECT 1 FROM content_slot_runs WHERE trigger = 'human') "
            "OR EXISTS (SELECT 1 FROM wecom_delivery_windows WHERE lane_key <> 'slot') THEN "
            "RAISE EXCEPTION 'refusing to discard human pick lineage'; "
            "END IF; END $$"
        )
    )
    op.drop_constraint(
        op.f("uq_wecom_delivery_windows_lane"), "wecom_delivery_windows", type_="unique"
    )
    op.create_unique_constraint(
        op.f("uq_wecom_delivery_windows_lane"), "wecom_delivery_windows", _LANE_COLUMNS
    )
    op.drop_constraint(
        op.f("ck_wecom_delivery_windows_ck_wecom_delivery_windows_lane_key"),
        "wecom_delivery_windows",
        type_="check",
    )
    op.drop_column("wecom_delivery_windows", "lane_key")
    op.drop_constraint(
        op.f("ck_content_slot_runs_ck_content_slot_runs_trigger"),
        "content_slot_runs",
        type_="check",
    )
    op.create_check_constraint(
        op.f("ck_content_slot_runs_ck_content_slot_runs_trigger"),
        "content_slot_runs",
        "trigger IN ('manual', 'scheduled')",
    )
