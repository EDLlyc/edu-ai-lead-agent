from __future__ import annotations

import asyncio
import os
import signal
import socket
from uuid import uuid4

import httpx
import structlog

from app.application.services.wecom_delivery import WeComDeliveryExecutor
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.infrastructure.db.session import create_engine, create_session_factory
from app.infrastructure.storage.minio_image_store import MinioImageStore
from app.infrastructure.wecom.client import WeComHttpClient

logger = structlog.get_logger()


async def run_dispatcher() -> None:
    settings = get_settings()
    configure_logging(json_output=settings.app_env != "development")
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for signum in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(signum, stop.set)
    if not settings.wecom_enabled:
        logger.info("wecom_dispatcher_disabled")
        await stop.wait()
        return

    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    worker_tasks: list[asyncio.Task[None]] = []
    try:
        async with httpx.AsyncClient(follow_redirects=False) as http_client:
            client = WeComHttpClient(settings=settings, client=http_client)
            executor = WeComDeliveryExecutor(
                session_factory=session_factory,
                client=client,
                image_store=MinioImageStore(settings),
                settings=settings,
            )
            worker_prefix = f"{socket.gethostname()}:{os.getpid()}:{uuid4()}"
            logger.info(
                "wecom_dispatcher_started",
                concurrency=settings.wecom_worker_concurrency,
                auto_delivery=settings.wecom_auto_delivery_enabled,
            )
            worker_tasks = [
                asyncio.create_task(
                    _worker_loop(
                        worker_id=f"{worker_prefix}:{index + 1}",
                        stop=stop,
                        executor=executor,
                        poll_seconds=settings.wecom_poll_seconds,
                        reconcile_auto=index == 0,
                    )
                )
                for index in range(settings.wecom_worker_concurrency)
            ]
            stop_task = asyncio.create_task(stop.wait())
            done, _ = await asyncio.wait(
                [stop_task, *worker_tasks], return_when=asyncio.FIRST_COMPLETED
            )
            for task in done:
                if task is not stop_task:
                    task.result()
            stop_task.cancel()
            await asyncio.gather(stop_task, return_exceptions=True)
    finally:
        stop.set()
        if worker_tasks:
            await asyncio.gather(*worker_tasks, return_exceptions=True)
        await engine.dispose()
        logger.info("wecom_dispatcher_stopped")


async def _worker_loop(
    *,
    worker_id: str,
    stop: asyncio.Event,
    executor: WeComDeliveryExecutor,
    poll_seconds: float,
    reconcile_auto: bool,
) -> None:
    while not stop.is_set():
        if reconcile_auto:
            await executor.reconcile_auto_deliveries()
        worked = await executor.execute_next(worker_id)
        if worked:
            continue
        try:
            await asyncio.wait_for(stop.wait(), timeout=poll_seconds)
        except TimeoutError:
            pass


if __name__ == "__main__":
    asyncio.run(run_dispatcher())
