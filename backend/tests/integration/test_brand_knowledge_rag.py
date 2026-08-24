from __future__ import annotations

from pathlib import Path
from uuid import UUID, uuid4

import pytest
from app.api_main import app
from app.application.services.brand_knowledge import BrandIngestionExecutor
from app.infrastructure.ai.brand import GovernanceEmbeddingBrandAdapter
from app.infrastructure.ai.fake import DeterministicFakeEmbeddingModel
from app.infrastructure.brand.parser import BoundedBrandDocumentParser
from app.infrastructure.db.brand_knowledge import PostgresBrandKnowledgeRepository
from app.infrastructure.storage.minio_brand_store import MinioBrandOriginalStore
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from .conftest import IntegrationContext

FIXTURE = Path(__file__).parents[1] / "fixtures" / "brand" / "parent-tone-v1.md"


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_brand_upload_ingest_activate_and_filtered_retrieval(
    integration_context: IntegrationContext,
) -> None:
    settings = integration_context.settings.model_copy(
        update={
            "content_enabled": True,
            "content_worker_enabled": True,
            "ai_provider_mode": "fake",
        }
    )
    original_store = MinioBrandOriginalStore(settings)
    embedding_model = GovernanceEmbeddingBrandAdapter(
        DeterministicFakeEmbeddingModel(
            model=settings.ai_embedding_model,
            dimensions=settings.ai_embedding_dimensions,
        )
    )
    previous_settings = app.state.settings
    previous_factory = app.state.session_factory
    previous_store = getattr(app.state, "brand_original_store", None)
    previous_embedding = getattr(app.state, "brand_embedding_model", None)
    app.state.settings = settings
    app.state.session_factory = integration_context.session_factory
    app.state.brand_original_store = original_store
    app.state.brand_embedding_model = embedding_model
    transport = ASGITransport(app=app)
    title = f"赛先生家长沟通规范-{uuid4().hex[:8]}"
    body = FIXTURE.read_bytes()
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            app.state.brand_embedding_model = None
            provider_disabled = await client.post(
                "/api/v1/brand-documents",
                data={"title": title, "document_kind": "tone", "audience": "parents"},
                files={"file": ("parent-tone-v1.md", body, "text/markdown")},
            )
            assert provider_disabled.status_code == 409
            assert provider_disabled.json()["error"]["code"] == "conflict"
            app.state.brand_embedding_model = embedding_model

            created = await client.post(
                "/api/v1/brand-documents",
                data={
                    "title": title,
                    "document_kind": "tone",
                    "audience": "parents",
                    "tone_tags": "准确,克制,温暖",
                    "safety_tags": "不制造焦虑,不作效果承诺",
                },
                files={"file": ("parent-tone-v1.md", body, "text/markdown")},
            )
            assert created.status_code == 202, created.text
            created_payload = created.json()
            document_id = UUID(created_payload["document_id"])
            version_id = UUID(created_payload["version_id"])
            job_id = UUID(created_payload["ingestion_job_id"])
            assert created_payload["status"] == "queued"
            assert created.headers["location"].endswith(str(job_id))

            replay = await client.post(
                "/api/v1/brand-documents",
                data={
                    "title": title,
                    "document_kind": "tone",
                    "audience": "parents",
                    "tone_tags": "准确,克制,温暖",
                    "safety_tags": "不制造焦虑,不作效果承诺",
                },
                files={"file": ("parent-tone-v1.md", body, "text/markdown")},
            )
            assert replay.status_code == 202
            assert replay.json()["created"] is False
            assert UUID(replay.json()["version_id"]) == version_id

            changed_metadata = await client.post(
                "/api/v1/brand-documents",
                data={
                    "title": title,
                    "document_kind": "tone",
                    "audience": "parents",
                    "tone_tags": "准确,克制,温暖,鼓励探索",
                    "safety_tags": "不制造焦虑,不作效果承诺",
                },
                files={"file": ("parent-tone-v1.md", body, "text/markdown")},
            )
            assert changed_metadata.status_code == 202
            assert changed_metadata.json()["created"] is True
            changed_metadata_version_id = UUID(changed_metadata.json()["version_id"])
            assert changed_metadata_version_id != version_id

            app.state.settings = settings.model_copy(update={"ai_provider_mode": "zhipu"})
            changed_provider = await client.post(
                "/api/v1/brand-documents",
                data={
                    "title": title,
                    "document_kind": "tone",
                    "audience": "parents",
                    "tone_tags": "准确,克制,温暖",
                    "safety_tags": "不制造焦虑,不作效果承诺",
                },
                files={"file": ("parent-tone-v1.md", body, "text/markdown")},
            )
            app.state.settings = settings
            assert changed_provider.status_code == 202
            assert changed_provider.json()["created"] is True
            assert UUID(changed_provider.json()["version_id"]) not in {
                version_id,
                changed_metadata_version_id,
            }

            legacy_settings = settings.model_copy(
                update={
                    "brand_parser_version": "brand-parser-v2-glm-ocr",
                    "brand_chunk_version": "brand-chunk-v2-structure-aware",
                    "brand_embedding_input_version": "brand-embedding-input-v1",
                    "brand_retrieval_version": "brand-hybrid-rrf-v2-diverse",
                }
            )
            app.state.settings = legacy_settings
            legacy_upload = await client.post(
                "/api/v1/brand-documents",
                data={
                    "title": title,
                    "document_kind": "tone",
                    "audience": "parents",
                    "tone_tags": "准确,克制,温暖",
                    "safety_tags": "不制造焦虑,不作效果承诺",
                },
                files={"file": ("parent-tone-v1.md", body, "text/markdown")},
            )
            app.state.settings = settings
            assert legacy_upload.status_code == 202
            legacy_job_id = UUID(legacy_upload.json()["ingestion_job_id"])
            legacy_version_id = UUID(legacy_upload.json()["version_id"])

        async with integration_context.engine.begin() as connection:
            await connection.execute(
                text(
                    """
                    UPDATE brand_ingestion_jobs
                    SET status = 'running', attempt_count = 1,
                        lease_owner = 'synthetic-v2-worker', lease_token = :lease_token,
                        lease_expires_at = now() - interval '1 minute', heartbeat_at = now()
                    WHERE id = :job_id
                    """
                ),
                {"job_id": legacy_job_id, "lease_token": uuid4()},
            )
            await connection.execute(
                text("UPDATE brand_document_versions SET status = 'processing' WHERE id = :id"),
                {"id": legacy_version_id},
            )

        executor = BrandIngestionExecutor(
            repository=PostgresBrandKnowledgeRepository(integration_context.session_factory),
            originals=original_store,
            parser=BoundedBrandDocumentParser(
                max_pages=settings.brand_parse_max_pages,
                max_characters=settings.brand_parse_max_characters,
                max_chunks=settings.brand_parse_max_chunks,
                chunk_characters=settings.brand_chunk_characters,
                overlap_characters=settings.brand_chunk_overlap_characters,
                parser_version=settings.brand_parser_version,
                chunk_version=settings.brand_chunk_version,
                embedding_input_version=settings.brand_embedding_input_version,
            ),
            embeddings=embedding_model,
            settings=settings,
        )
        assert await executor.execute_next("brand-rag-integration-worker")

        async with AsyncClient(transport=transport, base_url="http://test") as client:
            job = await client.get(f"/api/v1/brand-ingestion-jobs/{job_id}")
            assert job.status_code == 200
            assert job.json()["status"] == "succeeded"

            replay_after_success = await client.post(
                "/api/v1/brand-documents",
                data={
                    "title": title,
                    "document_kind": "tone",
                    "audience": "parents",
                    "tone_tags": "准确,克制,温暖",
                    "safety_tags": "不制造焦虑,不作效果承诺",
                },
                files={"file": ("parent-tone-v1.md", body, "text/markdown")},
            )
            assert replay_after_success.json()["status"] == "succeeded"

            activated = await client.post(
                f"/api/v1/brand-documents/{document_id}/versions/{version_id}/activate"
            )
            assert activated.status_code == 200, activated.text
            assert activated.json()["status"] == "active"
            assert activated.json()["active_version_id"] == str(version_id)

            retrieval = await client.post(
                "/api/v1/brand-context/retrieve",
                json={
                    "query": "教育焦虑",
                    "audience": "parents",
                    "limit": 4,
                },
            )
            assert retrieval.status_code == 200, retrieval.text
            retrieval_payload = retrieval.json()
            assert retrieval_payload["evidence_eligible"] is False
            assert retrieval_payload["count"] >= 1
            assert all(
                item["document_id"] == str(document_id) for item in retrieval_payload["items"]
            )
            assert any("教育焦虑" in item["text"] for item in retrieval_payload["items"])
            assert all(item["section_id"] is not None for item in retrieval_payload["items"])
            assert all(item["section_kind"] == "generic" for item in retrieval_payload["items"])
            content_types = {item["content_type"] for item in retrieval_payload["items"]}
            assert content_types <= {
                "tone_example",
                "audience_insight",
                "safety_capability",
            }
            assert "tone_example" in content_types
            claim_scopes = {item["claim_scope"] for item in retrieval_payload["items"]}
            assert claim_scopes == {"brand_statement", "external_claim"}
            assert all(
                item["verification_required"] == (item["claim_scope"] == "external_claim")
                for item in retrieval_payload["items"]
            )

            wrong_audience = await client.post(
                "/api/v1/brand-context/retrieve",
                json={"query": "家长沟通", "audience": "internal", "limit": 3},
            )
            assert wrong_audience.status_code == 200
            assert wrong_audience.json()["items"] == []

            deactivated = await client.post(f"/api/v1/brand-documents/{document_id}/deactivate")
            assert deactivated.status_code == 200
            assert deactivated.json()["status"] == "inactive"

        assert await executor.execute_next("brand-rag-integration-worker")
        assert not await executor.execute_next("brand-rag-integration-worker")
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            legacy_job = await client.get(f"/api/v1/brand-ingestion-jobs/{legacy_job_id}")
        assert legacy_job.status_code == 200
        assert legacy_job.json()["status"] == "running"
        assert legacy_job.json()["attempt_count"] == 1

        legacy_executor = BrandIngestionExecutor(
            repository=PostgresBrandKnowledgeRepository(integration_context.session_factory),
            originals=original_store,
            parser=BoundedBrandDocumentParser(
                max_pages=legacy_settings.brand_parse_max_pages,
                max_characters=legacy_settings.brand_parse_max_characters,
                max_chunks=legacy_settings.brand_parse_max_chunks,
                chunk_characters=legacy_settings.brand_chunk_characters,
                overlap_characters=legacy_settings.brand_chunk_overlap_characters,
                parser_version=legacy_settings.brand_parser_version,
                chunk_version=legacy_settings.brand_chunk_version,
                embedding_input_version=legacy_settings.brand_embedding_input_version,
            ),
            embeddings=embedding_model,
            settings=legacy_settings,
        )
        assert not await legacy_executor.execute_next("brand-rag-v2-rollback-worker")
        assert await legacy_executor.execute_next("brand-rag-v2-rollback-worker")
        async with integration_context.engine.connect() as connection:
            legacy_shape = (
                await connection.execute(
                    text(
                        """
                        SELECT
                            (SELECT count(*) FROM brand_sections WHERE version_id = :version_id)
                                AS section_count,
                            count(*) AS chunk_count,
                            count(*) FILTER (
                                WHERE section_id IS NULL
                                  AND section_ordinal IS NULL
                                  AND embedding_text = text
                                  AND embedding_input_hash = text_hash
                            ) AS compatible_chunk_count
                        FROM brand_chunks
                        WHERE version_id = :version_id
                        """
                    ),
                    {"version_id": legacy_version_id},
                )
            ).one()
        assert legacy_shape.section_count == 0
        assert legacy_shape.chunk_count >= 1
        assert legacy_shape.compatible_chunk_count == legacy_shape.chunk_count
    finally:
        app.state.settings = previous_settings
        app.state.session_factory = previous_factory
        app.state.brand_original_store = previous_store
        app.state.brand_embedding_model = previous_embedding
