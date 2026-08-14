import pytest
from sqlalchemy import inspect, text

from .conftest import IntegrationContext


def _has_named(values: set[str | None], expected: str) -> bool:
    return any(value is not None and value.endswith(expected) for value in values)


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
                    "image_artifacts",
                    "material_packages",
                    "copy_generation_runs",
                    "wecom_delivery_jobs",
                    "wecom_delivery_windows",
                    "content_slot_runs",
                    "content_slot_scores",
                    "content_slot_selections",
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
        slot_checks = await connection.run_sync(
            lambda sync: {
                table: {item["name"] for item in inspect(sync).get_check_constraints(table)}
                for table in (
                    "acquisition_runs",
                    "content_slot_runs",
                    "content_slot_scores",
                    "content_slot_selections",
                    "copy_generation_runs",
                    "wecom_delivery_windows",
                    "wecom_delivery_jobs",
                )
            }
        )
        slot_foreign_keys = await connection.run_sync(
            lambda sync: {
                table: {item["name"] for item in inspect(sync).get_foreign_keys(table)}
                for table in (
                    "acquisition_runs",
                    "governance_runs",
                    "content_slot_runs",
                    "content_slot_scores",
                    "content_slot_selections",
                    "copy_generation_runs",
                    "wecom_delivery_jobs",
                )
            }
        )
        slot_uniques = await connection.run_sync(
            lambda sync: {
                table: {item["name"] for item in inspect(sync).get_unique_constraints(table)}
                for table in (
                    "acquisition_runs",
                    "governance_runs",
                    "content_slot_runs",
                    "content_slot_scores",
                    "content_slot_selections",
                    "copy_generation_runs",
                    "wecom_delivery_windows",
                    "wecom_delivery_jobs",
                )
            }
        )
        acquisition_indexes = await connection.run_sync(
            lambda sync: {
                item["name"]: item for item in inspect(sync).get_indexes("acquisition_runs")
            }
        )

    assert revision == "20260814_0020"
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
        "image_artifacts",
        "material_packages",
        "material_reviews",
        "content_slot_runs",
        "content_slot_jobs",
        "content_slot_scores",
        "content_slot_selections",
        "wecom_delivery_windows",
        "wecom_delivery_jobs",
        "wecom_delivery_attempts",
    }.issubset(tables)
    assert columns["acquisition_runs"]["content_slot"]["nullable"] is True
    assert columns["copy_generation_runs"]["daily_topic_selection_id"]["nullable"] is True
    assert columns["copy_generation_runs"]["topic_selection_run_id"]["nullable"] is True
    assert columns["copy_generation_runs"]["content_slot_selection_id"]["nullable"] is True
    for column_name in (
        "delivery_window_id",
        "content_slot_selection_id",
        "sequence_ordinal",
        "not_before",
        "expires_at",
    ):
        assert columns["wecom_delivery_jobs"][column_name]["nullable"] is True
    assert columns["wecom_delivery_windows"]["next_allowed_at"]["nullable"] is False
    assert columns["source_versions"]["relevance_rule_version"]["nullable"] is True
    assert columns["source_versions"]["allow_http_fallback"]["nullable"] is False
    assert str(columns["source_versions"]["allow_http_fallback"]["default"]) == "false"
    assert columns["source_versions"]["topic_priority_policy"]["nullable"] is True
    assert columns["evidence_candidates"]["relevance_rule_version"]["nullable"] is True
    for table in ("acquisition_runs", "acquisition_jobs"):
        assert columns[table]["filtered_count"]["nullable"] is False
        assert str(columns[table]["filtered_count"]["default"]) == "0"
    assert columns["brand_document_versions"]["metadata_fingerprint"]["nullable"] is False
    assert columns["brand_document_versions"]["embedding_provider"]["nullable"] is False
    for column_name in (
        "extraction_method",
        "ocr_provider",
        "ocr_model",
        "ocr_request_fingerprint",
        "ocr_provider_request_id",
        "ocr_page_count",
        "ocr_prompt_tokens",
        "ocr_completion_tokens",
        "ocr_latency_ms",
    ):
        assert columns["brand_document_versions"][column_name]["nullable"] is True
    assert columns["image_artifacts"]["pipeline_version"]["nullable"] is False
    assert columns["image_artifacts"]["available_at"]["nullable"] is False
    assert columns["image_artifacts"]["storage_metadata"]["nullable"] is False
    assert columns["image_artifacts"]["repair_count"]["nullable"] is False
    assert columns["image_artifacts"]["provider_rejection_retry_count"]["nullable"] is False
    assert columns["image_artifacts"]["validation_snapshot"]["nullable"] is False
    assert columns["image_artifacts"]["audit_snapshot"]["nullable"] is False
    for column_name in (
        "lease_owner",
        "lease_token",
        "lease_expires_at",
        "heartbeat_at",
    ):
        assert columns["image_artifacts"][column_name]["nullable"] is True
    for column_name in ("brand_snapshot", "validation_snapshot", "version_snapshot"):
        assert columns["material_packages"][column_name]["nullable"] is False
    assert "fk_copy_draft_versions_repair_same_run" in foreign_keys["copy_draft_versions"]
    assert (
        "fk_copy_claim_evidence_bindings_provenance" in foreign_keys["copy_claim_evidence_bindings"]
    )
    assert any(name.endswith("ck_copy_issues_stage_audit_shape") for name in checks)
    for table, expected in (
        ("acquisition_runs", "ck_acquisition_runs_content_slot"),
        ("content_slot_runs", "ck_content_slot_runs_window"),
        ("content_slot_scores", "ck_content_slot_scores_exclusion"),
        ("content_slot_selections", "ck_content_slot_selections_ordinal"),
        ("copy_generation_runs", "ck_copy_generation_runs_origin_xor"),
        ("wecom_delivery_windows", "ck_wecom_delivery_windows_gap"),
        ("wecom_delivery_jobs", "ck_wecom_delivery_jobs_slot_shape"),
    ):
        assert _has_named(slot_checks[table], expected)
    for table, expected in (
        ("content_slot_runs", "fk_content_slot_runs_acquisition_run_id"),
        ("content_slot_runs", "fk_content_slot_runs_acquisition_identity"),
        ("content_slot_runs", "fk_content_slot_runs_governance_run_id"),
        ("content_slot_runs", "fk_content_slot_runs_governance_lineage"),
        ("content_slot_runs", "fk_content_slot_runs_config_id"),
        ("content_slot_scores", "fk_content_slot_scores_event_version_event"),
        (
            "content_slot_selections",
            "fk_content_slot_selections_event_version_event",
        ),
        ("content_slot_selections", "fk_content_slot_selections_run_identity"),
        ("content_slot_selections", "fk_content_slot_selections_score_identity"),
        (
            "copy_generation_runs",
            "fk_copy_generation_runs_content_slot_selection_id",
        ),
        ("copy_generation_runs", "fk_copy_generation_runs_slot_origin_identity"),
        ("wecom_delivery_jobs", "fk_wecom_delivery_jobs_delivery_window_id"),
        (
            "wecom_delivery_jobs",
            "fk_wecom_delivery_jobs_content_slot_selection_id",
        ),
        ("wecom_delivery_jobs", "fk_wecom_delivery_jobs_slot_ordinal"),
        ("wecom_delivery_jobs", "fk_wecom_delivery_jobs_window_identity"),
    ):
        assert _has_named(slot_foreign_keys[table], expected)
    for table, expected in (
        ("acquisition_runs", "uq_acquisition_runs_id_slot_identity"),
        ("governance_runs", "uq_governance_runs_id_acquisition"),
        ("content_slot_runs", "uq_content_slot_runs_id_slot_identity"),
        ("content_slot_scores", "uq_content_slot_scores_selection_identity"),
        ("content_slot_selections", "uq_content_slot_selections_daily_event"),
        ("content_slot_selections", "uq_content_slot_selections_copy_origin_identity"),
        ("content_slot_selections", "uq_content_slot_selections_delivery_ordinal"),
        ("copy_generation_runs", "uq_copy_generation_runs_slot_version"),
        ("wecom_delivery_windows", "uq_wecom_delivery_windows_lane"),
        ("wecom_delivery_windows", "uq_wecom_delivery_windows_job_identity"),
        ("wecom_delivery_jobs", "uq_wecom_delivery_jobs_window_package"),
    ):
        assert _has_named(slot_uniques[table], expected)
    assert {
        "uq_acquisition_runs_scheduled_business_key",
        "uq_acquisition_runs_scheduled_slot_business_key",
    }.issubset(acquisition_indexes)
    assert "content_slot IS NULL" in str(
        acquisition_indexes["uq_acquisition_runs_scheduled_business_key"]["dialect_options"]
    )
    assert "content_slot IS NOT NULL" in str(
        acquisition_indexes["uq_acquisition_runs_scheduled_slot_business_key"]["dialect_options"]
    )
