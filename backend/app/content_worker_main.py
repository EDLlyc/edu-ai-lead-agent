from __future__ import annotations

import asyncio
import os
import signal
import socket
from contextlib import AsyncExitStack
from uuid import uuid4

import httpx
import structlog
from pydantic import SecretStr

from app.application.ports.copy_generation import MaterialDraftAuditor, MaterialDraftGenerator
from app.application.services.brand_knowledge import BrandIngestionExecutor
from app.application.services.copy_generation import (
    BrandRagContextRetriever,
    CopyGenerationExecutor,
    build_copy_version_bundle,
)
from app.application.services.topic_selection import TopicSelectionExecutor
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.infrastructure.ai.brand import GovernanceEmbeddingBrandAdapter
from app.infrastructure.ai.copy_generation import (
    DeterministicFakeMaterialDraftAuditor,
    DeterministicFakeMaterialDraftGenerator,
    create_zhipu_copy_models,
)
from app.infrastructure.ai.factory import create_embedding_model
from app.infrastructure.brand.parser import BoundedBrandDocumentParser
from app.infrastructure.db.brand_knowledge import PostgresBrandKnowledgeRepository
from app.infrastructure.db.copy_generation import PostgresCopyGenerationRepository
from app.infrastructure.db.governance_checkpointer import PostgresGovernanceCheckpointer
from app.infrastructure.db.session import create_engine, create_session_factory
from app.infrastructure.db.topic_selection import PostgresTopicSelectionRepository
from app.infrastructure.storage.minio_brand_store import MinioBrandOriginalStore

logger = structlog.get_logger()


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
    exit_stack = AsyncExitStack()
    workers: list[asyncio.Task[None]] = []
    stop_task: asyncio.Task[bool] | None = None
    try:
        await exit_stack.__aenter__()
        session_factory = create_session_factory(engine)
        copy_checkpointer = PostgresGovernanceCheckpointer(
            settings.governance_checkpoint_database_url
        )
        copy_saver = await exit_stack.enter_async_context(copy_checkpointer.saver())
        repository = PostgresTopicSelectionRepository(session_factory)
        executor = TopicSelectionExecutor(repository, settings)
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
        if settings.ai_provider_mode != "disabled":
            if settings.ai_provider_mode == "zhipu":
                embedding_client = httpx.AsyncClient(follow_redirects=False)
            brand_repository = PostgresBrandKnowledgeRepository(session_factory)
            brand_embeddings = GovernanceEmbeddingBrandAdapter(
                create_embedding_model(settings, client=embedding_client)
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
                    chunk_version=settings.brand_chunk_version,
                ),
                embeddings=brand_embeddings,
                settings=settings,
            )
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
                    brand_executor=brand_executor,
                    copy_executor=copy_executor,
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
        await exit_stack.aclose()
        await engine.dispose()
        logger.info("content_worker_stopped")


async def _worker_loop(
    *,
    worker_id: str,
    stop: asyncio.Event,
    executor: TopicSelectionExecutor,
    brand_executor: BrandIngestionExecutor | None,
    copy_executor: CopyGenerationExecutor,
    copy_repository: PostgresCopyGenerationRepository,
    settings: Settings,
    poll_seconds: float,
) -> None:
    cursor = 0
    while not stop.is_set():
        await copy_repository.reconcile_ready_topics(
            timezone=settings.business_timezone,
            scoring_profile=settings.content_scoring_profile,
            version_bundle=build_copy_version_bundle(settings),
        )
        work = [executor.execute_next, copy_executor.execute_next]
        if brand_executor is not None:
            work.insert(1, brand_executor.execute_next)
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
