import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from app.infrastructure.db.governance_checkpointer import PostgresGovernanceCheckpointer
from app.infrastructure.db.models import Base
from pydantic import SecretStr
from sqlalchemy import inspect, text
from sqlalchemy.engine import make_url

from .conftest import IntegrationContext


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_governance_schema_and_checkpoint_contract(
    integration_context: IntegrationContext,
) -> None:
    async with integration_context.engine.connect() as connection:
        revision = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        vector_enabled = await connection.scalar(
            text("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'vector')")
        )
        checkpoint_version = await connection.scalar(
            text("SELECT max(v) FROM checkpoint_migrations")
        )
        tables = await connection.run_sync(lambda sync: set(inspect(sync).get_table_names()))
        vector_type = await connection.scalar(
            text(
                """
                SELECT format_type(attribute.atttypid, attribute.atttypmod)
                FROM pg_attribute AS attribute
                JOIN pg_class AS relation ON relation.oid = attribute.attrelid
                WHERE relation.relname = 'article_embeddings'
                  AND attribute.attname = 'vector'
                  AND NOT attribute.attisdropped
                """
            )
        )
        event_version_columns = await connection.run_sync(
            lambda sync: {
                column["name"] for column in inspect(sync).get_columns("event_cluster_versions")
            }
        )

    assert revision == "20260827_0037"
    assert vector_enabled is True
    assert checkpoint_version == 9
    assert vector_type == "vector(2048)"
    assert "representative_article_id" in event_version_columns
    assert {
        "governance_runs",
        "governance_jobs",
        "governance_attempts",
        "article_occurrences",
        "normalized_articles",
        "normalized_passages",
        "candidate_analyses",
        "analysis_facts",
        "evidence_bindings",
        "analysis_entities",
        "analysis_categories",
        "article_embeddings",
        "duplicate_relations",
        "event_clusters",
        "event_cluster_versions",
        "event_memberships",
        "event_assignment_decisions",
        "model_invocations",
        "checkpoint_migrations",
        "checkpoints",
        "checkpoint_blobs",
        "checkpoint_writes",
        "topic_scoring_configs",
        "topic_selection_runs",
        "topic_selection_jobs",
        "topic_scores",
        "daily_topic_selections",
        "content_slot_runs",
        "content_slot_jobs",
        "content_slot_scores",
        "content_slot_selections",
        "topic_rerank_records",
    }.issubset(tables)

    psycopg_url = make_url(integration_context.settings.database_url.get_secret_value()).set(
        drivername="postgresql"
    )
    checkpointer = PostgresGovernanceCheckpointer(
        SecretStr(psycopg_url.render_as_string(hide_password=False))
    )
    assert await checkpointer.checkpoint_exists(thread_id="missing-governance-job") is False

    def compare_application_metadata(sync_connection):  # type: ignore[no-untyped-def]
        context = MigrationContext.configure(
            sync_connection,
            opts={
                "compare_type": True,
                "include_name": lambda name, type_, _parent_names: (
                    not (type_ == "table" and name is not None and name.startswith("checkpoint"))
                ),
            },
        )
        return compare_metadata(context, Base.metadata)

    async with integration_context.engine.connect() as connection:
        metadata_diffs = await connection.run_sync(compare_application_metadata)
    assert metadata_diffs == []
