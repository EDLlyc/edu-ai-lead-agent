"""Independent default-off worker for current-date, per-news WeCom infographics."""

from __future__ import annotations

import asyncio
import os
import signal
import socket
from uuid import uuid4

import structlog

from app.application.services.wecom_news_infographic import NewsInfographicProducer
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.infrastructure.ai.news_infographic import local_infographic_models
from app.infrastructure.db.session import create_engine, create_session_factory
from app.infrastructure.model_api_keys_overlay import start_model_key_watch
from app.infrastructure.storage.minio_image_store import MinioImageStore

logger = structlog.get_logger()


async def run_producer() -> None:
    settings = get_settings()
    configure_logging(json_output=settings.app_env != "development")
    # Restart (SIGTERM, then Docker) after an owner rotates a model key in the 运营后台.
    start_model_key_watch(settings)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)
    if not settings.wecom_infographic_producer_enabled:
        logger.info("wecom_infographic_producer_disabled")
        await stop.wait()
        return
    engine = create_engine(settings)
    try:
        async with local_infographic_models(settings) as models:
            producer = NewsInfographicProducer(
                session_factory=create_session_factory(engine),
                image_store=MinioImageStore(settings),
                settings=settings,
                models=models,
            )
            worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid4()}"
            logger.info("wecom_infographic_producer_started")
            while not stop.is_set():
                try:
                    await producer.reconcile()
                    worked = await producer.execute_next(worker_id)
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    logger.warning(
                        "wecom_infographic_producer_cycle_failed",
                        exception_type=type(error).__name__,
                    )
                    worked = False
                if worked:
                    continue
                try:
                    await asyncio.wait_for(stop.wait(), timeout=settings.wecom_poll_seconds)
                except TimeoutError:
                    pass
    finally:
        await engine.dispose()
        logger.info("wecom_infographic_producer_stopped")


if __name__ == "__main__":
    asyncio.run(run_producer())
