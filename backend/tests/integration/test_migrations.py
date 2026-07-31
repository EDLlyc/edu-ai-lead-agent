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
                    "brand_document_versions",
                )
            }
        )
        foreign_keys = await connection.run_sync(
            lambda sync: {
                table: {item["name"] for item in inspect(sync).get_foreign_keys(table)}
                for table in ("copy_draft_versions", "copy_claim_evidence_bindings")
            }
        )
        checks = await connection.run_sync(
            lambda sync: {
                item["name"] for item in inspect(sync).get_check_constraints("copy_issues")
            }
        )

    assert revision == "20260730_0008"
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
        "brand_documents",
        "brand_document_versions",
        "brand_ingestion_jobs",
        "brand_ingestion_attempts",
        "brand_chunks",
        "brand_chunk_embeddings",
        "copy_generation_runs",
        "copy_generation_jobs",
        "copy_generation_attempts",
        "copy_draft_versions",
        "copy_draft_claims",
        "copy_claim_evidence_bindings",
        "copy_claim_brand_bindings",
        "copy_validation_results",
        "copy_audits",
        "copy_issues",
        "copy_generation_checkpoints",
    }.issubset(tables)
    assert columns["source_versions"]["relevance_rule_version"]["nullable"] is True
    assert columns["evidence_candidates"]["relevance_rule_version"]["nullable"] is True
    for table in ("acquisition_runs", "acquisition_jobs"):
        assert columns[table]["filtered_count"]["nullable"] is False
        assert str(columns[table]["filtered_count"]["default"]) == "0"
    assert columns["brand_document_versions"]["metadata_fingerprint"]["nullable"] is False
    assert columns["brand_document_versions"]["embedding_provider"]["nullable"] is False
    assert "fk_copy_draft_versions_repair_same_run" in foreign_keys["copy_draft_versions"]
    assert (
        "fk_copy_claim_evidence_bindings_provenance" in foreign_keys["copy_claim_evidence_bindings"]
    )
    assert any(name.endswith("ck_copy_issues_stage_audit_shape") for name in checks)
