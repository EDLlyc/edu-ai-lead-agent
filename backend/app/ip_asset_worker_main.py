from __future__ import annotations

import asyncio
import os
import signal
import socket
from uuid import uuid4

import httpx
import structlog

from app.application.ports.image_generation import ImageGenerator
from app.application.ports.visual_retrieval import VisualEmbeddingModel
from app.application.services.ip_assets import IpAssetWorkerService
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.infrastructure.ai.factory import create_image_generator
from app.infrastructure.ai.visual_embedding import (
    AlibabaVisualEmbeddingAdapter,
    DeterministicFakeVisualEmbedding,
)
from app.infrastructure.db.ip_assets import PostgresIpAssetRepository
from app.infrastructure.db.session import create_engine, create_session_factory
from app.infrastructure.storage.minio_ip_asset_store import MinioIpAssetStore

logger = structlog.get_logger()


async def run_worker() -> None:
    settings = get_settings()
    configure_logging(json_output=settings.app_env != "development")
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)
    if not settings.ip_asset_hub_enabled or not settings.ip_asset_worker_enabled:
        logger.info("ip_asset_worker_disabled")
        await stop.wait()
        return

    engine = create_engine(settings)
    visual_client: httpx.AsyncClient | None = None
    image_client: httpx.AsyncClient | None = None
    tasks: list[asyncio.Task[None]] = []
    try:
        embeddings: VisualEmbeddingModel | None = None
        if settings.visual_semantic_enabled:
            if settings.visual_embedding_provider_mode == "fake":
                embeddings = DeterministicFakeVisualEmbedding()
            elif settings.visual_embedding_provider_mode == "alibaba":
                if (
                    settings.visual_embedding_endpoint is None
                    or settings.visual_embedding_api_key is None
                ):
                    raise RuntimeError("IP asset visual embedding credentials are unavailable")
                visual_client = httpx.AsyncClient(follow_redirects=False)
                embeddings = AlibabaVisualEmbeddingAdapter(
                    client=visual_client,
                    endpoint=settings.visual_embedding_endpoint,
                    api_key=settings.visual_embedding_api_key,
                    timeout_seconds=settings.visual_embedding_timeout_seconds,
                    concurrency=settings.visual_embedding_concurrency,
                )
        image_generator: ImageGenerator | None = None
        if settings.ip_asset_generation_enabled:
            if settings.image_provider_mode in {"toapis", "comfly"}:
                image_client = httpx.AsyncClient(follow_redirects=False)
            image_generator = create_image_generator(settings, client=image_client)
        service = IpAssetWorkerService(
            repository=PostgresIpAssetRepository(create_session_factory(engine)),
            store=MinioIpAssetStore(settings),
            embeddings=embeddings,
            identity=settings.visual_embedding_identity,
            image_generator=image_generator,
        )
        embedding_backfill_count = await service.enqueue_unavailable_embeddings()
        if embedding_backfill_count:
            logger.info(
                "ip_asset_embedding_backfill_enqueued",
                asset_count=embedding_backfill_count,
            )
        prefix = f"{socket.gethostname()}:{os.getpid()}:{uuid4()}"
        tasks = [
            asyncio.create_task(
                _worker_loop(
                    worker_id=f"{prefix}:{index + 1}",
                    stop=stop,
                    service=service,
                    poll_seconds=settings.ip_asset_poll_seconds,
                    lease_seconds=settings.ip_asset_lease_seconds,
                    heartbeat_seconds=settings.ip_asset_heartbeat_seconds,
                    max_attempts=settings.ip_asset_max_attempts,
                )
            )
            for index in range(settings.ip_asset_worker_concurrency)
        ]
        logger.info(
            "ip_asset_worker_started",
            concurrency=settings.ip_asset_worker_concurrency,
            semantic_enabled=embeddings is not None,
            generation_enabled=image_generator is not None,
        )
        await stop.wait()
    finally:
        stop.set()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if visual_client is not None:
            await visual_client.aclose()
        if image_client is not None:
            await image_client.aclose()
        await engine.dispose()
        logger.info("ip_asset_worker_stopped")


async def _worker_loop(
    *,
    worker_id: str,
    stop: asyncio.Event,
    service: IpAssetWorkerService,
    poll_seconds: float,
    lease_seconds: int,
    heartbeat_seconds: int,
    max_attempts: int,
) -> None:
    while not stop.is_set():
        try:
            worked = await service.process_one_generation(
                worker_id=worker_id,
                lease_seconds=lease_seconds,
                max_attempts=max_attempts,
                heartbeat_seconds=heartbeat_seconds,
            )
            worked = (
                await service.process_one_embedding(
                    worker_id=worker_id,
                    lease_seconds=lease_seconds,
                    heartbeat_seconds=heartbeat_seconds,
                    max_attempts=max_attempts,
                )
                or worked
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            # The durable lease/fencing token leaves the claim retryable after expiry. Keep one
            # unexpected infrastructure failure from permanently killing this worker lane.
            logger.exception("ip_asset_worker_iteration_failed", worker_id=worker_id)
            worked = False
        if worked:
            continue
        try:
            await asyncio.wait_for(stop.wait(), timeout=poll_seconds)
        except TimeoutError:
            pass


if __name__ == "__main__":
    asyncio.run(run_worker())
