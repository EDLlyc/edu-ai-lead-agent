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

        executor = BrandIngestionExecutor(
            repository=PostgresBrandKnowledgeRepository(integration_context.session_factory),
            originals=original_store,
            parser=BoundedBrandDocumentParser(
                max_pages=settings.brand_parse_max_pages,
                max_characters=settings.brand_parse_max_characters,
                max_chunks=settings.brand_parse_max_chunks,
                chunk_characters=settings.brand_chunk_characters,
                overlap_characters=settings.brand_chunk_overlap_characters,
                chunk_version=settings.brand_chunk_version,
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
                    "query": "面向家长介绍人工智能时如何避免教育焦虑",
                    "audience": "parents",
                    "limit": 3,
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
    finally:
        app.state.settings = previous_settings
        app.state.session_factory = previous_factory
        app.state.brand_original_store = previous_store
        app.state.brand_embedding_model = previous_embedding
