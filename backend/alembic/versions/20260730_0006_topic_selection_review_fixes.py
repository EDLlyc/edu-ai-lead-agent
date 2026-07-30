"""Tighten topic-selection business and event-version constraints.

Revision ID: 20260730_0006
Revises: 20260730_0005
Create Date: 2026-07-30
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20260730_0006"
down_revision: str | None = "20260730_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint(
        "uq_topic_selection_runs_business_config",
        "topic_selection_runs",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_topic_selection_runs_business_key",
        "topic_selection_runs",
        ["business_date", "timezone", "scoring_profile"],
    )
    op.create_unique_constraint(
        "uq_event_cluster_versions_id_event",
        "event_cluster_versions",
        ["id", "event_id"],
    )
    op.create_foreign_key(
        "fk_topic_selection_runs_selected_event_version_event",
        "topic_selection_runs",
        "event_cluster_versions",
        ["selected_event_version_id", "selected_event_id"],
        ["id", "event_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_topic_scores_event_version_event",
        "topic_scores",
        "event_cluster_versions",
        ["event_version_id", "event_id"],
        ["id", "event_id"],
        ondelete="RESTRICT",
    )
    op.create_foreign_key(
        "fk_daily_topic_selections_selected_event_version_event",
        "daily_topic_selections",
        "event_cluster_versions",
        ["selected_event_version_id", "selected_event_id"],
        ["id", "event_id"],
        ondelete="RESTRICT",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_daily_topic_selections_selected_event_version_event",
        "daily_topic_selections",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_topic_scores_event_version_event",
        "topic_scores",
        type_="foreignkey",
    )
    op.drop_constraint(
        "fk_topic_selection_runs_selected_event_version_event",
        "topic_selection_runs",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_event_cluster_versions_id_event",
        "event_cluster_versions",
        type_="unique",
    )
    op.drop_constraint(
        "uq_topic_selection_runs_business_key",
        "topic_selection_runs",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_topic_selection_runs_business_config",
        "topic_selection_runs",
        ["business_date", "timezone", "scoring_profile", "config_fingerprint"],
    )
