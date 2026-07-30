from __future__ import annotations

import asyncio
import os
import signal
import socket
from uuid import uuid4

import httpx
import structlog

from app.application.services.brand_knowledge import BrandIngestionExecutor
from app.application.services.topic_selection import TopicSelectionExecutor
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.infrastructure.ai.brand import GovernanceEmbeddingBrandAdapter
from app.infrastructure.ai.factory import create_embedding_model
from app.infrastructure.brand.parser import BoundedBrandDocumentParser
from app.infrastructure.db.brand_knowledge import PostgresBrandKnowledgeRepository
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
    workers: list[asyncio.Task[None]] = []
    stop_task: asyncio.Task[bool] | None = None
    try:
        session_factory = create_session_factory(engine)
        repository = PostgresTopicSelectionRepository(session_factory)
        executor = TopicSelectionExecutor(repository, settings)
        brand_executor: BrandIngestionExecutor | None = None
        if settings.ai_provider_mode != "disabled":
            if settings.ai_provider_mode == "zhipu":
                embedding_client = httpx.AsyncClient(follow_redirects=False)
            brand_executor = BrandIngestionExecutor(
                repository=PostgresBrandKnowledgeRepository(session_factory),
                originals=MinioBrandOriginalStore(settings),
                parser=BoundedBrandDocumentParser(
                    max_pages=settings.brand_parse_max_pages,
                    max_characters=settings.brand_parse_max_characters,
                    max_chunks=settings.brand_parse_max_chunks,
                    chunk_characters=settings.brand_chunk_characters,
                    overlap_characters=settings.brand_chunk_overlap_characters,
                    chunk_version=settings.brand_chunk_version,
                ),
                embeddings=GovernanceEmbeddingBrandAdapter(
                    create_embedding_model(settings, client=embedding_client)
                ),
                settings=settings,
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
        await engine.dispose()
        logger.info("content_worker_stopped")


async def _worker_loop(
    *,
    worker_id: str,
    stop: asyncio.Event,
    executor: TopicSelectionExecutor,
    brand_executor: BrandIngestionExecutor | None,
    poll_seconds: float,
) -> None:
    prefer_brand = True
    while not stop.is_set():
        if prefer_brand and brand_executor is not None:
            worked = await brand_executor.execute_next(worker_id)
            if not worked:
                worked = await executor.execute_next(worker_id)
        else:
            worked = await executor.execute_next(worker_id)
            if not worked and brand_executor is not None:
                worked = await brand_executor.execute_next(worker_id)
        if worked:
            prefer_brand = not prefer_brand
            continue
        try:
            await asyncio.wait_for(stop.wait(), timeout=poll_seconds)
        except TimeoutError:
            pass


if __name__ == "__main__":
    asyncio.run(run_content_worker())
