import pytest
from sqlalchemy import Text, inspect, text

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
                    "brand_chunks",
                    "brand_visual_index_jobs",
                    "brand_visual_asset_embeddings",
                    "image_artifacts",
                    "image_artifact_references",
                    "image_visual_plan_reservations",
                    "image_similarity_attempts",
                    "material_packages",
                    "copy_generation_runs",
                    "wecom_delivery_jobs",
                    "wecom_delivery_windows",
                    "topic_selection_runs",
                    "topic_scores",
                    "content_slot_runs",
                    "content_slot_scores",
                    "content_slot_selections",
                    "topic_rerank_records",
                    "ip_assets",
                    "ip_asset_embedding_jobs",
                    "ip_asset_embeddings",
                    "ip_asset_generation_jobs",
                    "ip_asset_profiles",
                    "ip_asset_profile_memberships",
                    "ip_asset_favorites",
                    "ip_asset_generation_references",
                    "ip_asset_download_daily",
                    "official_account_generated_visuals",
                )
            }
        )
        foreign_keys = await connection.run_sync(
            lambda sync: {
                table: {item["name"] for item in inspect(sync).get_foreign_keys(table)}
                for table in (
                    "copy_draft_versions",
                    "copy_claim_evidence_bindings",
                    "image_artifact_references",
                    "image_similarity_attempts",
                )
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
                    "topic_rerank_records",
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
        diversity_uniques = await connection.run_sync(
            lambda sync: {
                table: {item["name"] for item in inspect(sync).get_unique_constraints(table)}
                for table in (
                    "image_artifact_references",
                    "image_visual_plan_reservations",
                    "image_similarity_attempts",
                )
            }
        )
        official_account_foreign_keys = await connection.run_sync(
            lambda sync: {
                item["name"]: item
                for item in inspect(sync).get_foreign_keys(
                    "official_account_local_draft_body_media"
                )
            }
        )
        official_account_media_uniques = await connection.run_sync(
            lambda sync: {
                item["name"]: item
                for item in inspect(sync).get_unique_constraints("official_account_local_media")
            }
        )
        official_account_media_indexes = await connection.run_sync(
            lambda sync: {
                item["name"]: item
                for item in inspect(sync).get_indexes("official_account_local_media")
            }
        )
        official_account_body_columns = await connection.run_sync(
            lambda sync: {
                item["name"]: item
                for item in inspect(sync).get_columns("official_account_local_draft_body_media")
            }
        )
        official_account_body_checks = await connection.run_sync(
            lambda sync: {
                item["name"]: item
                for item in inspect(sync).get_check_constraints(
                    "official_account_local_draft_body_media"
                )
            }
        )
        official_account_review_foreign_keys = await connection.run_sync(
            lambda sync: {
                item["name"]: item
                for item in inspect(sync).get_foreign_keys("official_account_manual_reviews")
            }
        )
        official_account_review_uniques = await connection.run_sync(
            lambda sync: {
                item["name"]: item
                for item in inspect(sync).get_unique_constraints("official_account_manual_reviews")
            }
        )
        official_account_review_checks = await connection.run_sync(
            lambda sync: {
                item["name"]: item
                for item in inspect(sync).get_check_constraints("official_account_manual_reviews")
            }
        )
        official_account_generated_visual_columns = await connection.run_sync(
            lambda sync: {
                item["name"]: item
                for item in inspect(sync).get_columns("official_account_generated_visuals")
            }
        )
        official_account_generated_visual_foreign_keys = await connection.run_sync(
            lambda sync: {
                item["name"]: item
                for item in inspect(sync).get_foreign_keys("official_account_generated_visuals")
            }
        )
        official_account_generated_visual_checks = await connection.run_sync(
            lambda sync: {
                item["name"]: item
                for item in inspect(sync).get_check_constraints(
                    "official_account_generated_visuals"
                )
            }
        )
        official_account_generated_visual_uniques = await connection.run_sync(
            lambda sync: {
                item["name"]: item
                for item in inspect(sync).get_unique_constraints(
                    "official_account_generated_visuals"
                )
            }
        )
        official_account_generated_visual_indexes = await connection.run_sync(
            lambda sync: {
                item["name"]: item
                for item in inspect(sync).get_indexes("official_account_generated_visuals")
            }
        )
        official_account_media_columns = await connection.run_sync(
            lambda sync: {
                item["name"]: item
                for item in inspect(sync).get_columns("official_account_local_media")
            }
        )
        official_account_media_foreign_keys = await connection.run_sync(
            lambda sync: {
                item["name"]: item
                for item in inspect(sync).get_foreign_keys("official_account_local_media")
            }
        )
        official_account_run_checks = await connection.run_sync(
            lambda sync: {
                item["name"]: item
                for item in inspect(sync).get_check_constraints("official_account_article_runs")
            }
        )
        official_account_attempt_checks = await connection.run_sync(
            lambda sync: {
                item["name"]: item
                for item in inspect(sync).get_check_constraints("official_account_article_attempts")
            }
        )

    assert revision == "20260831_0039"
    assert isinstance(columns["ip_asset_generation_jobs"]["prompt"]["type"], Text)
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
        "brand_sections",
        "brand_chunks",
        "brand_chunk_embeddings",
        "brand_visual_index_jobs",
        "brand_visual_asset_embeddings",
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
        "image_artifact_references",
        "image_visual_plan_reservations",
        "image_similarity_attempts",
        "material_packages",
        "material_reviews",
        "official_account_article_runs",
        "official_account_article_versions",
        "official_account_article_attempts",
        "official_account_render_versions",
        "official_account_local_media",
        "official_account_local_drafts",
        "official_account_local_draft_body_media",
        "official_account_manual_reviews",
        "official_account_generated_visuals",
        "content_slot_runs",
        "content_slot_jobs",
        "content_slot_scores",
        "content_slot_selections",
        "topic_rerank_records",
        "wecom_delivery_windows",
        "wecom_delivery_jobs",
        "wecom_delivery_attempts",
        "ip_assets",
        "ip_asset_tags",
        "ip_asset_derivatives",
        "ip_asset_embedding_jobs",
        "ip_asset_embeddings",
        "ip_asset_generation_jobs",
        "ip_asset_profiles",
        "ip_asset_profile_memberships",
        "ip_asset_favorites",
        "ip_asset_generation_references",
        "ip_asset_download_daily",
    }.issubset(tables)
    assert columns["ip_assets"]["object_key"]["nullable"] is False
    assert columns["ip_assets"]["shared_at"]["nullable"] is True
    assert columns["ip_assets"]["blob_sha256"]["nullable"] is False
    assert columns["ip_asset_embedding_jobs"]["lease_token"]["nullable"] is True
    assert columns["ip_asset_embeddings"]["vector"]["nullable"] is False
    assert columns["ip_asset_generation_jobs"]["idempotency_key"]["nullable"] is False
    assert columns["ip_asset_generation_jobs"]["profile_id"]["nullable"] is True
    assert columns["ip_asset_profiles"]["token_digest"]["nullable"] is False
    assert columns["ip_asset_profile_memberships"]["generation_job_id"]["nullable"] is True
    assert columns["ip_asset_favorites"]["asset_id"]["nullable"] is False
    assert columns["ip_asset_generation_references"]["ordinal"]["nullable"] is False
    assert columns["ip_asset_download_daily"]["download_count"]["nullable"] is False
    for table in ("topic_selection_runs", "content_slot_runs"):
        assert columns[table]["rerank_config_snapshot"]["nullable"] is False
        assert columns[table]["rerank_config_fingerprint"]["nullable"] is False
    for table in ("topic_scores", "content_slot_scores"):
        assert columns[table]["deterministic_rank"]["nullable"] is False
    assert columns["topic_rerank_records"]["candidate_count"]["nullable"] is False
    assert columns["topic_rerank_records"]["reasons"]["nullable"] is False
    assert columns["brand_chunks"]["section_id"]["nullable"] is True
    assert columns["brand_chunks"]["embedding_text"]["nullable"] is False
    assert columns["brand_chunks"]["embedding_input_hash"]["nullable"] is False
    assert columns["brand_chunks"]["verification_required"]["nullable"] is False
    for table in ("brand_visual_index_jobs", "brand_visual_asset_embeddings"):
        assert columns[table]["embedding_input_sha256"]["nullable"] is False
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
        "diversity_policy_version",
        "perceptual_hash_version",
        "similarity_policy_version",
        "final_plan_ordinal",
        "perceptual_hash",
        "diversity_warning",
    ):
        assert columns["image_artifacts"][column_name]["nullable"] is True
    for column_name in (
        "diversity_retry_count",
        "active_plan_ordinal",
        "similarity_snapshot",
    ):
        assert columns["image_artifacts"][column_name]["nullable"] is False
    assert str(columns["image_artifacts"]["diversity_retry_count"]["default"]) == "0"
    assert str(columns["image_artifacts"]["active_plan_ordinal"]["default"]) == "1"
    assert columns["image_artifact_references"]["attempt_ordinal"]["nullable"] is False
    assert columns["image_artifact_references"]["plan_reservation_id"]["nullable"] is True
    assert columns["image_visual_plan_reservations"]["plan_snapshot"]["nullable"] is False
    assert columns["image_similarity_attempts"]["perceptual_hash"]["nullable"] is False
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
    assert (
        "fk_image_artifact_references_plan_reservation_id"
        in foreign_keys["image_artifact_references"]
    )
    assert "fk_image_similarity_attempts_plan_attempt" in foreign_keys["image_similarity_attempts"]
    assert (
        "uq_image_artifact_references_attempt_ordinal"
        in diversity_uniques["image_artifact_references"]
    )
    assert (
        "uq_image_visual_plan_reservations_reference_identity"
        in diversity_uniques["image_visual_plan_reservations"]
    )
    assert (
        "uq_image_visual_plan_reservations_day_plan"
        in diversity_uniques["image_visual_plan_reservations"]
    )
    assert (
        "uq_image_similarity_attempts_artifact_attempt"
        in diversity_uniques["image_similarity_attempts"]
    )
    assert any(name.endswith("ck_copy_issues_stage_audit_shape") for name in checks)
    for table, expected in (
        ("acquisition_runs", "ck_acquisition_runs_content_slot"),
        ("content_slot_runs", "ck_content_slot_runs_window"),
        ("content_slot_scores", "ck_content_slot_scores_exclusion"),
        ("content_slot_selections", "ck_content_slot_selections_ordinal"),
        ("topic_rerank_records", "ck_topic_rerank_records_origin_xor"),
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
    typed_media_fk = official_account_foreign_keys["fk_official_draft_body_media_typed"]
    assert typed_media_fk["constrained_columns"] == [
        "body_media_id",
        "run_id",
        "media_role",
        "ordinal",
    ]
    assert typed_media_fk["referred_columns"] == ["id", "run_id", "role", "ordinal"]
    assert official_account_media_uniques["uq_official_media_typed_identity"]["column_names"] == [
        "id",
        "run_id",
        "role",
        "ordinal",
    ]
    assert official_account_body_columns["media_role"]["nullable"] is False
    assert "body" in str(official_account_body_columns["media_role"]["default"])
    assert any(
        "media_role" in str(item["sqltext"]) and "body" in str(item["sqltext"])
        for item in official_account_body_checks.values()
    )
    body_checksum_index = official_account_media_indexes[
        "uq_official_account_local_media_body_checksum"
    ]
    assert body_checksum_index["unique"] is True
    assert body_checksum_index["column_names"] == ["run_id", "sha256"]
    body_checksum_predicate = str(body_checksum_index["dialect_options"]["postgresql_where"])
    assert "role" in body_checksum_predicate
    assert "body" in body_checksum_predicate
    assert (
        official_account_review_foreign_keys["fk_official_account_manual_reviews_run_id"][
            "referred_table"
        ]
        == "official_account_article_runs"
    )
    assert (
        official_account_review_foreign_keys["fk_official_account_manual_reviews_run_id"][
            "options"
        ]["ondelete"]
        == "CASCADE"
    )
    assert official_account_review_uniques["uq_official_account_manual_reviews_run"][
        "column_names"
    ] == ["run_id"]
    assert official_account_review_uniques["uq_official_account_manual_reviews_request"][
        "column_names"
    ] == ["request_fingerprint"]
    for expected in (
        "ck_official_account_manual_reviews_decision",
        "ck_official_account_manual_reviews_reviewer",
        "ck_official_account_manual_reviews_note",
        "ck_official_account_manual_reviews_fingerprint",
    ):
        assert _has_named(set(official_account_review_checks), expected)
    for column_name in (
        "run_id",
        "article_version_id",
        "render_version_id",
        "ordinal",
        "section_index",
        "reference_asset_ref",
        "request_fingerprint",
        "status",
        "provider",
        "model",
    ):
        assert official_account_generated_visual_columns[column_name]["nullable"] is False
    for column_name in (
        "block_index",
        "block_kind",
        "block_fingerprint",
        "reference_input_version",
        "reference_input_checksum",
        "output_profile_version",
    ):
        assert official_account_generated_visual_columns[column_name]["nullable"] is True
    assert official_account_media_columns["generated_visual_id"]["nullable"] is True
    assert (
        official_account_media_foreign_keys["fk_official_account_local_media_generated_visual_id"][
            "referred_table"
        ]
        == "official_account_generated_visuals"
    )
    for expected in (
        "fk_official_account_generated_visuals_run_id",
        "fk_official_account_generated_visuals_article_version_id",
        "fk_official_account_generated_visuals_render_version_id",
    ):
        assert expected in official_account_generated_visual_foreign_keys
    # PostgreSQL's naming convention prepends the table name and can hash-truncate a long
    # explicit check name; assert the executable SQL instead of its introspected display name.
    generated_visual_check_sql = "\n".join(
        str(item["sqltext"]) for item in official_account_generated_visual_checks.values()
    )
    for expected in (
        "ordinal",
        "section_index",
        "reference_asset_ref",
        "reference_source_checksum",
        "selection_method",
        "similarity_band",
        "provider",
        "status",
        "media_type",
        "error_code IS NOT NULL",
        "completed_at IS NULL",
        "block_index",
        "block_kind",
        "block_fingerprint",
        "prompt_version",
        "official-account-generated-visual-prompt-v1",
        "official-account-generated-visual-prompt-v2-block-scene",
        "official-account-generated-visual-prompt-v3-visible-ip-block-scene",
        "reference_input_version",
        "reference_input_checksum",
        "output_profile_version",
        "width = 1536",
        "height = 1024",
    ):
        assert expected in generated_visual_check_sql
    assert official_account_generated_visual_uniques[
        "uq_official_generated_visuals_render_ordinal"
    ]["column_names"] == ["render_version_id", "ordinal"]
    assert official_account_generated_visual_uniques["uq_official_generated_visuals_request"][
        "column_names"
    ] == ["request_fingerprint"]
    assert official_account_generated_visual_indexes["ix_official_generated_visuals_run"][
        "column_names"
    ] == ["run_id", "ordinal"]
    assert "generating_body_visuals" in "\n".join(
        str(item["sqltext"]) for item in official_account_run_checks.values()
    )
    assert "visual_generation" in "\n".join(
        str(item["sqltext"]) for item in official_account_attempt_checks.values()
    )
