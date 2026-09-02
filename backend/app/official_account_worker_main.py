from __future__ import annotations

import asyncio
import os
import signal
import socket
from typing import Literal, cast
from uuid import uuid4

import httpx
import structlog
from pydantic import SecretStr

from app.application.ports.image_generation import (
    ImageGenerationRequest,
    ImageGenerationResult,
    ImageGenerator,
)
from app.application.ports.official_account_local import (
    OfficialAccountArticleAuditor,
    OfficialAccountArticleGenerator,
)
from app.application.ports.official_account_reviewer import OfficialAccountReviewer
from app.application.ports.visual_retrieval import VisualEmbeddingModel
from app.application.services.official_account_local import OfficialAccountLocalExecutor
from app.application.services.official_account_media_semantic import (
    HybridOfficialAccountMediaSemanticRanker,
)
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.domain.visual_retrieval import VisualEmbeddingRequest, VisualEmbeddingResult
from app.infrastructure.ai.factory import (
    create_image_generator,
    create_official_account_image_quality_auditor,
)
from app.infrastructure.ai.official_account_local import create_zhipu_official_account_models
from app.infrastructure.ai.official_account_reviewer import (
    create_zhipu_official_account_reviewer,
)
from app.infrastructure.ai.visual_embedding import (
    AlibabaVisualEmbeddingAdapter,
    DeterministicFakeVisualEmbedding,
)
from app.infrastructure.db.execution_governance import PostgresExecutionGovernanceRepository
from app.infrastructure.db.official_account_local import PostgresOfficialAccountRepository
from app.infrastructure.db.official_account_reviewer import (
    PostgresOfficialAccountReviewRepository,
)
from app.infrastructure.db.session import create_engine, create_session_factory
from app.infrastructure.db.visual_retrieval import PostgresVisualIndexRepository
from app.infrastructure.official_account_catalog import (
    LocalOfficialAccountCatalogMediaProvider,
)
from app.infrastructure.official_account_local import (
    DeterministicFakeOfficialAccountArticleAuditor,
    DeterministicFakeOfficialAccountArticleGenerator,
    LocalOfficialAccountDraftAdapter,
    LocalOfficialAccountMediaAdapter,
)
from app.infrastructure.official_account_reviewer import (
    DeterministicFakeOfficialAccountReviewer,
)
from app.infrastructure.official_account_reviewer_governance import (
    PostgresOfficialAccountReviewerGovernance,
)
from app.infrastructure.storage.minio_image_store import MinioImageStore

logger = structlog.get_logger()


class _LazyVisualEmbeddingModel(VisualEmbeddingModel):
    """Construct the real visual HTTP client only after preflight and a live multi-candidate run."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: httpx.AsyncClient | None = None
        self._adapter: VisualEmbeddingModel | None = None

    async def embed_visual(self, request: VisualEmbeddingRequest) -> VisualEmbeddingResult:
        if self._adapter is None:
            mode = self._settings.visual_embedding_provider_mode
            if mode == "fake":
                self._adapter = DeterministicFakeVisualEmbedding()
            elif mode == "alibaba":
                if (
                    self._settings.visual_embedding_endpoint is None
                    or self._settings.visual_embedding_api_key is None
                ):
                    raise RuntimeError(
                        "official-account visual embedding credentials are unavailable"
                    )
                self._client = httpx.AsyncClient(follow_redirects=False)
                self._adapter = AlibabaVisualEmbeddingAdapter(
                    client=self._client,
                    endpoint=self._settings.visual_embedding_endpoint,
                    api_key=self._settings.visual_embedding_api_key,
                    timeout_seconds=self._settings.visual_embedding_timeout_seconds,
                    concurrency=self._settings.visual_embedding_concurrency,
                )
            else:
                raise RuntimeError("official-account visual embedding provider is disabled")
        return await self._adapter.embed_visual(request)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()


class _LazyOfficialAccountImageGenerator(ImageGenerator):
    """Build the image provider only after a persisted live visual intent exists."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client: httpx.AsyncClient | None = None
        self._adapter: ImageGenerator | None = None

    async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        if self._adapter is None:
            if self._settings.image_provider_mode == "disabled":
                raise RuntimeError("official-account image provider is disabled")
            if self._settings.image_provider_mode != "fake":
                self._client = httpx.AsyncClient(follow_redirects=False)
            self._adapter = create_image_generator(self._settings, client=self._client)
        return await self._adapter.generate(request)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()


async def run_worker() -> None:
    settings = get_settings()
    configure_logging(json_output=settings.app_env != "development")
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)
    if (
        not settings.official_account_local_enabled
        or not settings.official_account_local_worker_enabled
    ):
        logger.info("official_account_local_worker_disabled")
        await stop.wait()
        return

    engine = create_engine(settings)
    provider_client: httpx.AsyncClient | None = None
    lazy_visual_model: _LazyVisualEmbeddingModel | None = None
    lazy_image_generator: _LazyOfficialAccountImageGenerator | None = None
    workers: list[asyncio.Task[None]] = []
    try:
        live_generator: OfficialAccountArticleGenerator | None = None
        live_auditor: OfficialAccountArticleAuditor | None = None
        live_reviewer: OfficialAccountReviewer | None = None
        if settings.ai_provider_mode == "zhipu":
            if (
                settings.ai_platform_base_url is not None
                and settings.ai_platform_api_key is not None
                and settings.ai_platform_api_key.get_secret_value().strip()
            ):
                provider_client = httpx.AsyncClient(follow_redirects=False)
                live_generator, live_auditor = create_zhipu_official_account_models(
                    client=provider_client,
                    base_url=settings.ai_platform_base_url,
                    api_key=SecretStr(settings.ai_platform_api_key.get_secret_value()),
                    model=settings.ai_chat_model,
                    connect_timeout_seconds=settings.ai_connect_timeout_seconds,
                    read_timeout_seconds=settings.ai_read_timeout_seconds,
                    total_timeout_seconds=settings.ai_total_timeout_seconds,
                    concurrency=settings.ai_provider_concurrency,
                    max_attempts=settings.ai_max_attempts,
                    max_input_characters=settings.ai_max_input_characters,
                    max_output_tokens=settings.official_account_local_max_output_tokens,
                    max_validation_corrections=settings.ai_max_validation_corrections,
                )
                live_reviewer = create_zhipu_official_account_reviewer(
                    client=provider_client,
                    base_url=settings.ai_platform_base_url,
                    api_key=SecretStr(settings.ai_platform_api_key.get_secret_value()),
                    model=settings.ai_chat_model,
                    connect_timeout_seconds=settings.ai_connect_timeout_seconds,
                    read_timeout_seconds=settings.ai_read_timeout_seconds,
                    total_timeout_seconds=settings.ai_total_timeout_seconds,
                    concurrency=settings.ai_provider_concurrency,
                    max_attempts=settings.ai_max_attempts,
                    max_input_characters=settings.ai_max_input_characters,
                    max_output_tokens=settings.official_account_reviewer_max_output_tokens,
                    max_validation_corrections=settings.ai_max_validation_corrections,
                )
        session_factory = create_session_factory(engine)
        catalog_media_provider = LocalOfficialAccountCatalogMediaProvider(
            settings.image_asset_manifest
        )
        lazy_visual_model = _LazyVisualEmbeddingModel(settings)
        semantic_ranker = HybridOfficialAccountMediaSemanticRanker(
            repository=PostgresVisualIndexRepository(session_factory),
            embeddings_factory=lambda: lazy_visual_model,
            catalog_provider=catalog_media_provider,
            identity=settings.visual_embedding_identity,
        )
        generated_visual_store = None
        if settings.official_account_local_generated_visuals_enabled:
            lazy_image_generator = _LazyOfficialAccountImageGenerator(settings)
            generated_visual_store = MinioImageStore(settings)
        image_quality_auditor = create_official_account_image_quality_auditor(
            settings,
            client=provider_client,
        )
        execution_repository = PostgresExecutionGovernanceRepository(session_factory)
        review_governance = PostgresOfficialAccountReviewerGovernance(
            execution_repository=execution_repository,
            review_repository=PostgresOfficialAccountReviewRepository(session_factory),
        )
        fixture_reviewer = DeterministicFakeOfficialAccountReviewer()
        executor = OfficialAccountLocalExecutor(
            repository=PostgresOfficialAccountRepository(session_factory),
            fixture_generator=DeterministicFakeOfficialAccountArticleGenerator(),
            fixture_auditor=DeterministicFakeOfficialAccountArticleAuditor(),
            live_generator=live_generator,
            live_auditor=live_auditor,
            media_adapter=LocalOfficialAccountMediaAdapter(catalog_media_provider),
            draft_adapter=LocalOfficialAccountDraftAdapter(),
            lease_seconds=settings.official_account_local_lease_seconds,
            heartbeat_seconds=settings.official_account_local_heartbeat_seconds,
            max_attempts=settings.official_account_local_max_attempts,
            retry_base_seconds=settings.official_account_local_retry_base_seconds,
            generation_max_output_tokens=settings.official_account_local_max_output_tokens,
            audit_max_output_tokens=settings.official_account_local_audit_max_output_tokens,
            catalog_media_provider=catalog_media_provider,
            media_semantic_ranker=semantic_ranker,
            visual_semantic_enabled=settings.official_account_local_visual_semantic_enabled,
            generated_visuals_enabled=settings.official_account_local_generated_visuals_enabled,
            image_generator=lazy_image_generator,
            generated_visual_store=generated_visual_store,
            generated_visual_max_bytes=settings.image_max_download_bytes,
            generated_visual_provider=(
                cast(
                    Literal["fake", "toapis", "comfly"],
                    settings.image_provider_mode,
                )
                if settings.official_account_local_generated_visuals_enabled
                else None
            ),
            generated_visual_model=(
                settings.image_model
                if settings.official_account_local_generated_visuals_enabled
                else None
            ),
            image_quality_eval_mode=settings.image_quality_eval_mode,
            image_quality_auditor=image_quality_auditor,
            review_governance=review_governance,
            fixture_reviewer=fixture_reviewer,
            live_reviewer=live_reviewer,
        )
        worker_prefix = f"{socket.gethostname()}:{os.getpid()}:{uuid4()}"
        logger.info(
            "official_account_local_worker_started",
            concurrency=settings.official_account_local_worker_concurrency,
            live_provider_available=live_generator is not None,
            image_quality_eval_mode=settings.image_quality_eval_mode,
            image_quality_evaluator_available=image_quality_auditor is not None,
            reviewer_mode=settings.official_account_reviewer_mode,
            reviewer_available=(
                fixture_reviewer is not None
                and (live_reviewer is not None or settings.ai_provider_mode != "zhipu")
            ),
        )
        workers = [
            asyncio.create_task(
                _worker_loop(
                    worker_id=f"{worker_prefix}:{index + 1}",
                    stop=stop,
                    executor=executor,
                    poll_seconds=settings.official_account_local_poll_seconds,
                )
            )
            for index in range(settings.official_account_local_worker_concurrency)
        ]
        stop_task = asyncio.create_task(stop.wait())
        done, _ = await asyncio.wait(
            [stop_task, *workers],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in done:
            if task is not stop_task:
                task.result()
        stop_task.cancel()
        await asyncio.gather(stop_task, return_exceptions=True)
    finally:
        stop.set()
        if workers:
            await asyncio.gather(*workers, return_exceptions=True)
        if provider_client is not None:
            await provider_client.aclose()
        if lazy_visual_model is not None:
            await lazy_visual_model.close()
        if lazy_image_generator is not None:
            await lazy_image_generator.close()
        await engine.dispose()
        logger.info("official_account_local_worker_stopped")


async def _worker_loop(
    *,
    worker_id: str,
    stop: asyncio.Event,
    executor: OfficialAccountLocalExecutor,
    poll_seconds: float,
) -> None:
    while not stop.is_set():
        worked = await executor.execute_next(worker_id)
        if worked:
            continue
        try:
            await asyncio.wait_for(stop.wait(), timeout=poll_seconds)
        except TimeoutError:
            pass


if __name__ == "__main__":
    asyncio.run(run_worker())
