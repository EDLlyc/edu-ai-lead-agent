from __future__ import annotations

import asyncio
import os
import signal
import socket
from uuid import uuid4

import structlog

from app.application.services.topic_selection import TopicSelectionExecutor
from app.core.config import get_settings
from app.core.logging import configure_logging
from app.infrastructure.db.session import create_engine, create_session_factory
from app.infrastructure.db.topic_selection import PostgresTopicSelectionRepository

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
    repository = PostgresTopicSelectionRepository(create_session_factory(engine))
    executor = TopicSelectionExecutor(repository, settings)
    worker_prefix = f"{socket.gethostname()}:{os.getpid()}:{uuid4()}"
    logger.info(
        "content_worker_started",
        concurrency=settings.content_worker_concurrency,
        scoring_version=settings.content_scoring_version,
    )
    workers: list[asyncio.Task[None]] = []
    stop_task: asyncio.Task[bool] | None = None
    try:
        workers = [
            asyncio.create_task(
                _worker_loop(
                    worker_id=f"{worker_prefix}:{index + 1}",
                    stop=stop,
                    executor=executor,
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
        await engine.dispose()
        logger.info("content_worker_stopped")


async def _worker_loop(
    *,
    worker_id: str,
    stop: asyncio.Event,
    executor: TopicSelectionExecutor,
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
    asyncio.run(run_content_worker())
