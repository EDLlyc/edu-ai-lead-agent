from __future__ import annotations

import asyncio
import os
import signal
import socket
from contextlib import AsyncExitStack
from datetime import UTC, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

import httpx
import structlog
from pydantic import SecretStr

from app.application.ports.copy_generation import MaterialDraftAuditor, MaterialDraftGenerator
from app.application.ports.topic_rerank import TopicReranker
from app.application.ports.visual_retrieval import VisualEmbeddingModel
from app.application.services.brand_knowledge import BrandIngestionExecutor
from app.application.services.content_slots import ContentSlotExecutor
from app.application.services.copy_generation import (
    BrandRagContextRetriever,
    CopyGenerationExecutor,
    build_copy_version_bundle,
)
from app.application.services.material_package import MaterialPackageExecutor
from app.application.services.topic_selection import TopicSelectionExecutor
from app.application.services.visual_retrieval import VisualRetrievalService
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.infrastructure.ai.copy_generation import (
    DeterministicFakeMaterialDraftAuditor,
    DeterministicFakeMaterialDraftGenerator,
    create_zhipu_copy_models,
)
from app.infrastructure.ai.factory import (
    create_brand_embedding_model,
    create_brand_ocr_model,
    create_image_generator,
    create_image_quality_auditor,
    create_image_text_recognizer,
)
from app.infrastructure.ai.topic_rerank import (
    DeterministicFakeTopicReranker,
    ZhipuTopicReranker,
)
from app.infrastructure.ai.visual_embedding import (
    AlibabaVisualEmbeddingAdapter,
    DeterministicFakeVisualEmbedding,
)
from app.infrastructure.brand.parser import BoundedBrandDocumentParser
from app.infrastructure.db.brand_knowledge import PostgresBrandKnowledgeRepository
from app.infrastructure.db.content_slots import PostgresContentSlotRepository
from app.infrastructure.db.copy_generation import PostgresCopyGenerationRepository
from app.infrastructure.db.governance_checkpointer import PostgresGovernanceCheckpointer
from app.infrastructure.db.session import create_engine, create_session_factory
from app.infrastructure.db.topic_selection import PostgresTopicSelectionRepository
from app.infrastructure.db.visual_retrieval import PostgresVisualIndexRepository
from app.infrastructure.storage.minio_brand_store import MinioBrandOriginalStore
from app.infrastructure.storage.minio_image_store import MinioImageStore

logger = structlog.get_logger()


def _brand_ingestion_provider_enabled(settings: Settings) -> bool:
    """Keep brand ingestion availability independent from governance AI mode."""

    return settings.resolved_brand_embedding_provider_mode != "disabled"


async def run_content_worker() -> None:
    settings = get_settings()
    configure_logging(json_output=settings.app_env != "development")
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)
    if not settings.content_enabled or not settings.content_worker_enabled:
        logger.info("content_worker_disabled")
        await stop.wait()
        return

    engine = create_engine(settings)
    embedding_client: httpx.AsyncClient | None = None
    image_client: httpx.AsyncClient | None = None
    visual_embedding_client: httpx.AsyncClient | None = None
    exit_stack = AsyncExitStack()
    workers: list[asyncio.Task[None]] = []
    material_executor: MaterialPackageExecutor | None = None
    stop_task: asyncio.Task[bool] | None = None
    try:
        await exit_stack.__aenter__()
        session_factory = create_session_factory(engine)
        copy_checkpointer = PostgresGovernanceCheckpointer(
            settings.governance_checkpoint_database_url
        )
        copy_saver = await exit_stack.enter_async_context(copy_checkpointer.saver())
        repository = PostgresTopicSelectionRepository(session_factory)
        brand_executor: BrandIngestionExecutor | None = None
        copy_repository = PostgresCopyGenerationRepository(session_factory)
        copy_executor = CopyGenerationExecutor(
            repository=copy_repository,
            brand_retriever=None,
            generator=None,
            auditor=None,
            settings=settings,
            checkpointer=copy_saver,
        )
        if settings.ai_provider_mode == "zhipu":
            embedding_client = httpx.AsyncClient(follow_redirects=False)
        if settings.resolved_brand_embedding_provider_mode == "alibaba" or (
            settings.visual_semantic_enabled
            and settings.visual_embedding_provider_mode == "alibaba"
        ):
            visual_embedding_client = httpx.AsyncClient(follow_redirects=False)
        reranker: TopicReranker | None = None
        if settings.content_enabled and settings.content_llm_rerank_enabled:
            if settings.ai_provider_mode == "fake":
                reranker = DeterministicFakeTopicReranker(model=settings.ai_chat_model)
            else:
                if (
                    embedding_client is None
                    or settings.ai_platform_base_url is None
                    or settings.ai_platform_api_key is None
                ):
                    raise RuntimeError("validated Zhipu topic rerank settings are unavailable")
                reranker = ZhipuTopicReranker(
                    client=embedding_client,
                    base_url=settings.ai_platform_base_url,
                    api_key=SecretStr(settings.ai_platform_api_key.get_secret_value()),
                    model=settings.ai_chat_model,
                    connect_timeout_seconds=settings.ai_connect_timeout_seconds,
                    read_timeout_seconds=settings.ai_read_timeout_seconds,
                    total_timeout_seconds=settings.ai_total_timeout_seconds,
                    concurrency=settings.ai_provider_concurrency,
                    max_attempts=settings.ai_max_attempts,
                    max_input_characters=settings.ai_max_input_characters,
                    max_output_tokens=settings.content_llm_rerank_max_output_tokens,
                )
        executor = TopicSelectionExecutor(repository, settings, reranker=reranker)
        slot_executor = ContentSlotExecutor(
            PostgresContentSlotRepository(session_factory),
            settings,
            reranker=reranker,
        )
        visual_retrieval_service: VisualRetrievalService | None = None
        if settings.visual_semantic_enabled:
            if settings.visual_embedding_provider_mode == "fake":
                visual_embeddings: VisualEmbeddingModel = DeterministicFakeVisualEmbedding()
            else:
                if (
                    settings.visual_embedding_endpoint is None
                    or settings.visual_embedding_api_key is None
                ):
                    raise RuntimeError("validated visual embedding secrets are unavailable")
                if visual_embedding_client is None:
                    visual_embedding_client = httpx.AsyncClient(follow_redirects=False)
                visual_embeddings = AlibabaVisualEmbeddingAdapter(
                    client=visual_embedding_client,
                    endpoint=settings.visual_embedding_endpoint,
                    api_key=settings.visual_embedding_api_key,
                    timeout_seconds=settings.visual_embedding_timeout_seconds,
                    concurrency=settings.visual_embedding_concurrency,
                )
            visual_retrieval_service = VisualRetrievalService(
                embeddings=visual_embeddings,
                repository=PostgresVisualIndexRepository(session_factory),
                identity=settings.visual_embedding_identity,
            )
        if settings.image_enabled and settings.image_provider_mode != "disabled":
            if settings.image_provider_mode in {"toapis", "comfly"}:
                image_client = httpx.AsyncClient(follow_redirects=False)
            image_text_recognizer = (
                create_image_text_recognizer(settings, client=embedding_client)
                if settings.image_ocr_enabled
                else None
            )
            image_quality_auditor = (
                create_image_quality_auditor(settings, client=embedding_client)
                if settings.image_quality_audit_enabled
                else None
            )
            material_executor = MaterialPackageExecutor(
                session_factory=session_factory,
                image_generator=create_image_generator(settings, client=image_client),
                image_store=MinioImageStore(settings),
                settings=settings,
                reference_asset=settings.image_reference_asset,
                image_text_recognizer=image_text_recognizer,
                image_quality_auditor=image_quality_auditor,
                visual_retrieval_service=visual_retrieval_service,
            )
        brand_repository: PostgresBrandKnowledgeRepository | None = None
        brand_embeddings = None
        if _brand_ingestion_provider_enabled(settings):
            brand_repository = PostgresBrandKnowledgeRepository(session_factory)
            brand_embeddings = create_brand_embedding_model(
                settings,
                client=visual_embedding_client,
            )
            brand_ocr = (
                create_brand_ocr_model(settings, client=embedding_client)
                if settings.ai_provider_mode == "zhipu"
                else None
            )
            brand_executor = BrandIngestionExecutor(
                repository=brand_repository,
                originals=MinioBrandOriginalStore(settings),
                parser=BoundedBrandDocumentParser(
                    max_pages=settings.brand_parse_max_pages,
                    max_characters=settings.brand_parse_max_characters,
                    max_chunks=settings.brand_parse_max_chunks,
                    chunk_characters=settings.brand_chunk_characters,
                    overlap_characters=settings.brand_chunk_overlap_characters,
                    parser_version=settings.brand_parser_version,
                    chunk_version=settings.brand_chunk_version,
                    embedding_input_version=settings.brand_embedding_input_version,
                    sparse_text_threshold=settings.brand_ocr_sparse_text_threshold,
                ),
                embeddings=brand_embeddings,
                ocr=brand_ocr,
                settings=settings,
            )
        if (
            settings.ai_provider_mode != "disabled"
            and brand_repository is not None
            and brand_embeddings is not None
        ):
            generator: MaterialDraftGenerator
            auditor: MaterialDraftAuditor
            if settings.ai_provider_mode == "fake":
                generator = DeterministicFakeMaterialDraftGenerator(model=settings.ai_chat_model)
                auditor = DeterministicFakeMaterialDraftAuditor(model=settings.ai_chat_model)
            else:
                if (
                    embedding_client is None
                    or settings.ai_platform_base_url is None
                    or settings.ai_platform_api_key is None
                ):
                    raise RuntimeError("validated Zhipu copy settings are unavailable")
                generator, auditor = create_zhipu_copy_models(
                    client=embedding_client,
                    base_url=settings.ai_platform_base_url,
                    api_key=SecretStr(settings.ai_platform_api_key.get_secret_value()),
                    model=settings.ai_chat_model,
                    connect_timeout_seconds=settings.ai_connect_timeout_seconds,
                    read_timeout_seconds=settings.ai_read_timeout_seconds,
                    total_timeout_seconds=settings.ai_total_timeout_seconds,
                    concurrency=settings.ai_provider_concurrency,
                    max_attempts=settings.ai_max_attempts,
                    max_input_characters=settings.ai_max_input_characters,
                    max_output_tokens=settings.copy_max_output_tokens,
                    max_validation_corrections=settings.ai_max_validation_corrections,
                )
            copy_executor = CopyGenerationExecutor(
                repository=copy_repository,
                brand_retriever=BrandRagContextRetriever(
                    repository=brand_repository,
                    embeddings=brand_embeddings,
                    limit=settings.copy_brand_context_limit,
                    retrieval_version=settings.brand_retrieval_version,
                ),
                generator=generator,
                auditor=auditor,
                settings=settings,
                checkpointer=copy_saver,
            )
        worker_prefix = f"{socket.gethostname()}:{os.getpid()}:{uuid4()}"
        logger.info(
            "content_worker_started",
            concurrency=settings.content_worker_concurrency,
            scoring_version=settings.content_scoring_version,
        )
        workers = [
            asyncio.create_task(
                _worker_loop(
                    worker_id=f"{worker_prefix}:{index + 1}",
                    stop=stop,
                    executor=executor,
                    slot_executor=slot_executor,
                    brand_executor=brand_executor,
                    copy_executor=copy_executor,
                    material_executor=material_executor,
                    copy_repository=copy_repository,
                    settings=settings,
                    poll_seconds=settings.content_poll_seconds,
                )
            )
            for index in range(settings.content_worker_concurrency)
        ]
        stop_task = asyncio.create_task(stop.wait())
        done, _ = await asyncio.wait(
            [stop_task, *workers],
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in done:
            if task is not stop_task:
                task.result()
    finally:
        stop.set()
        if stop_task is not None:
            await stop_task
        if workers:
            await asyncio.gather(*workers, return_exceptions=True)
        if embedding_client is not None:
            await embedding_client.aclose()
        if image_client is not None:
            await image_client.aclose()
        if visual_embedding_client is not None:
            await visual_embedding_client.aclose()
        await exit_stack.aclose()
        await engine.dispose()
        logger.info("content_worker_stopped")


async def _worker_loop(
    *,
    worker_id: str,
    stop: asyncio.Event,
    executor: TopicSelectionExecutor,
    slot_executor: ContentSlotExecutor,
    brand_executor: BrandIngestionExecutor | None,
    copy_executor: CopyGenerationExecutor,
    material_executor: MaterialPackageExecutor | None,
    copy_repository: PostgresCopyGenerationRepository,
    settings: Settings,
    poll_seconds: float,
) -> None:
    cursor = 0
    while not stop.is_set():
        business_date = datetime.now(UTC).astimezone(ZoneInfo(settings.business_timezone)).date()
        reconciliation = (
            copy_repository.reconcile_ready_slot_topics
            if settings.content_slot_mode_enabled
            else copy_repository.reconcile_ready_topics
        )
        await reconciliation(
            business_date=business_date,
            timezone=settings.business_timezone,
            scoring_profile=settings.content_scoring_profile,
            version_bundle=build_copy_version_bundle(settings),
            max_attempts=settings.content_max_attempts,
        )
        if material_executor is not None:
            created = await material_executor.reconcile_ready_packages()
            if created:
                logger.info("material_packages_reconciled", created_count=created)
        topic_work = (
            slot_executor.execute_next
            if settings.content_slot_mode_enabled
            else executor.execute_next
        )
        work = [topic_work, copy_executor.execute_next]
        if brand_executor is not None:
            work.insert(1, brand_executor.execute_next)
        if material_executor is not None:
            work.append(material_executor.execute_next)
        worked = False
        for offset in range(len(work)):
            candidate = work[(cursor + offset) % len(work)]
            if await candidate(worker_id):
                cursor = (cursor + offset + 1) % len(work)
                worked = True
                break
        if worked:
            continue
        try:
            await asyncio.wait_for(stop.wait(), timeout=poll_seconds)
        except TimeoutError:
            pass


if __name__ == "__main__":
    asyncio.run(run_content_worker())
