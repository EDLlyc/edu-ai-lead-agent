import pytest
from sqlalchemy import inspect, text

from .conftest import IntegrationContext


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_clean_database_is_at_alembic_head(
    integration_context: IntegrationContext,
) -> None:
    async with integration_context.engine.connect() as connection:
        revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        tables = await connection.run_sync(lambda sync: set(inspect(sync).get_table_names()))
        columns = await connection.run_sync(
            lambda sync: {
                table: {column["name"]: column for column in inspect(sync).get_columns(table)}
                for table in (
                    "source_versions",
                    "evidence_candidates",
                    "acquisition_runs",
                    "acquisition_jobs",
                )
            }
        )

    assert revision == "20260730_0006"
    assert {
        "sources",
        "source_versions",
        "source_cursors",
        "acquisition_runs",
        "acquisition_jobs",
        "acquisition_attempts",
        "source_fetch_leases",
        "source_snapshots",
        "evidence_candidates",
        "source_observations",
        "topic_scoring_configs",
        "topic_selection_runs",
        "topic_selection_jobs",
        "topic_scores",
        "daily_topic_selections",
    }.issubset(tables)
    assert columns["source_versions"]["relevance_rule_version"]["nullable"] is True
    assert columns["evidence_candidates"]["relevance_rule_version"]["nullable"] is True
    for table in ("acquisition_runs", "acquisition_jobs"):
        assert columns[table]["filtered_count"]["nullable"] is False
        assert str(columns[table]["filtered_count"]["default"]) == "0"
