from __future__ import annotations

import asyncio
import os
import signal
import socket
from uuid import uuid4

import structlog

from app.application.services.execute_acquisition import AcquisitionExecutor
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.infrastructure.db.repositories import PostgresAcquisitionRepository
from app.infrastructure.db.session import create_engine, create_session_factory
from app.infrastructure.ingestion.fetcher import SafeHttpFetcher
from app.infrastructure.ingestion.source_image_fetcher import SafeSourceImageFetcher
from app.infrastructure.storage.minio_snapshot_store import MinioSnapshotStore

logger = structlog.get_logger()


async def run_worker() -> None:
    settings = get_settings()
    configure_logging(json_output=settings.app_env != "development")
    engine = create_engine(settings)
    repository = PostgresAcquisitionRepository(create_session_factory(engine))
    executor = AcquisitionExecutor(
        repository,
        SafeHttpFetcher(settings),
        MinioSnapshotStore(settings),
        settings,
        source_image_fetcher=SafeSourceImageFetcher(settings),
    )
    worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid4()}"
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)
    logger.info(
        "acquisition_worker_started",
        worker_id=worker_id,
        concurrency=settings.acquisition_worker_concurrency,
    )
    try:
        while not stop.is_set():
            results = await asyncio.gather(
                *(
                    executor.execute_next(worker_id)
                    for _ in range(settings.acquisition_worker_concurrency)
                )
            )
            if not any(results):
                try:
                    await asyncio.wait_for(stop.wait(), timeout=settings.acquisition_poll_seconds)
                except TimeoutError:
                    pass
    finally:
        await engine.dispose()
        logger.info("acquisition_worker_stopped", worker_id=worker_id)


if __name__ == "__main__":
    asyncio.run(run_worker())
