"""Operate the durable weekly article DAG in fixture or explicit production mode."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
from datetime import UTC, date, datetime
from hashlib import sha256
from pathlib import Path
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.ports.official_account_weekly_dag import WeeklyDagHandlerRegistry
from app.application.services.official_account_weekly_dag import (
    OfficialAccountWeeklyDagService,
)
from app.application.services.official_account_weekly_dag_fixture import (
    LocalWeeklyDagFixtureHandlers,
)
from app.application.services.official_account_weekly_production import (
    ProductionWeeklyDagHandlers,
)
from app.core.config import Settings, get_settings
from app.infrastructure.db.execution_governance import (
    PostgresExecutionGovernanceRepository,
)
from app.infrastructure.db.official_account_local import PostgresOfficialAccountRepository
from app.infrastructure.db.official_account_weekly_dag import (
    PostgresOfficialAccountWeeklyDagRepository,
)
from app.infrastructure.db.session import create_engine, create_session_factory
from app.infrastructure.official_account_media import OfficialAccountLocalMediaResolver
from app.infrastructure.official_account_runtime import official_account_identity_from_settings
from app.infrastructure.official_account_weekly_dag_governance import (
    PostgresOfficialAccountWeeklyDagGovernance,
)
from app.infrastructure.official_account_weekly_production import (
    LocalWeeklyProductionArtifactOwner,
)
from app.infrastructure.storage.minio_image_store import MinioImageStore
from app.infrastructure.storage.minio_snapshot_store import MinioSnapshotStore
from app.infrastructure.wechat_official_account.prepared_artifacts import (
    PreparedWeeklyDraftArtifactOwner,
)

_FIXTURE_INPUT_FINGERPRINT = sha256(b"official-account-weekly-fixture-input-v1").hexdigest()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("output/official-account-weekly-dag"),
        help="local artifact owner; paths are never persisted in DAG checkpoints",
    )
    parser.add_argument(
        "--handler-mode",
        choices=("fixture", "production"),
        default="fixture",
        help="production mode reuses persisted Zhipu article runs and prepared draft artifacts",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    enqueue = subparsers.add_parser("enqueue")
    enqueue.add_argument("--week-start", type=date.fromisoformat, required=True)
    enqueue.add_argument("--input-fingerprint", default=_FIXTURE_INPUT_FINGERPRINT)

    enqueue_due = subparsers.add_parser("enqueue-due")
    enqueue_due.add_argument("--input-fingerprint", default=_FIXTURE_INPUT_FINGERPRINT)
    enqueue_due.add_argument("--now", type=datetime.fromisoformat)

    status = subparsers.add_parser("status")
    status.add_argument("run_id", type=UUID)

    retry = subparsers.add_parser("retry")
    retry.add_argument("run_id", type=UUID)
    retry.add_argument("node_key")

    worker = subparsers.add_parser("worker")
    worker.add_argument(
        "--worker-id",
        default=f"weekly-worker-{os.getpid()}",
    )
    worker.add_argument("--concurrency", type=int, default=3)
    worker.add_argument("--lease-seconds", type=int, default=60)
    worker.add_argument("--poll-seconds", type=float, default=2.0)
    worker.add_argument("--once", action="store_true")
    worker.add_argument("--drain", action="store_true")
    return parser


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    dag_repository = PostgresOfficialAccountWeeklyDagRepository(session_factory)
    governance_repository = PostgresExecutionGovernanceRepository(session_factory)
    governance = PostgresOfficialAccountWeeklyDagGovernance(
        repository=governance_repository,
        session_factory=session_factory,
    )
    handlers = _handler_registry(
        args=args,
        settings=settings,
        session_factory=session_factory,
    )
    service = OfficialAccountWeeklyDagService(
        repository=dag_repository,
        governance=governance,
        handlers=handlers,
    )
    try:
        if args.command == "enqueue":
            _require_fixture_enqueue(args)
            run, created = await service.enqueue(
                week_start=args.week_start,
                input_fingerprint=args.input_fingerprint,
            )
            print(
                json.dumps(
                    {"run_id": str(run.run_id), "status": run.status.value, "created": created},
                    ensure_ascii=False,
                    sort_keys=True,
                )
            )
            return 0
        if args.command == "enqueue-due":
            _require_fixture_enqueue(args)
            now = args.now or datetime.now(UTC)
            if now.utcoffset() is None:
                raise ValueError("--now must include a timezone offset")
            outcome = await service.enqueue_due(
                input_fingerprint=args.input_fingerprint,
                now=now,
            )
            if outcome is None:
                print(json.dumps({"due": False}, sort_keys=True))
            else:
                run, created = outcome
                print(
                    json.dumps(
                        {
                            "due": True,
                            "run_id": str(run.run_id),
                            "status": run.status.value,
                            "created": created,
                        },
                        ensure_ascii=False,
                        sort_keys=True,
                    )
                )
            return 0
        if args.command == "status":
            status = await service.status(args.run_id)
            print(json.dumps(status.as_dict(), ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "retry":
            status = await service.retry(run_id=args.run_id, node_key=args.node_key)
            print(json.dumps(status.as_dict(), ensure_ascii=False, sort_keys=True))
            return 0
        if args.command == "worker":
            return await _worker_loop(service, args)
        raise AssertionError("weekly DAG command routing is incomplete")
    finally:
        await engine.dispose()


def _handler_registry(
    *,
    args: argparse.Namespace,
    settings: Settings,
    session_factory: async_sessionmaker[AsyncSession],
) -> WeeklyDagHandlerRegistry:
    if args.handler_mode == "fixture":
        return LocalWeeklyDagFixtureHandlers(args.output_root).registry()

    if (
        not settings.official_account_weekly_production_enabled
        or not settings.official_account_weekly_worker_enabled
    ):
        raise RuntimeError("production weekly DAG worker is not explicitly enabled")
    provider_key = (
        settings.ai_platform_api_key.get_secret_value().strip()
        if settings.ai_platform_api_key is not None
        else ""
    )
    if (
        not settings.official_account_local_enabled
        or not settings.official_account_local_worker_enabled
        or settings.ai_provider_mode != "zhipu"
        or not provider_key
    ):
        raise RuntimeError("production weekly DAG requires the persisted Zhipu article worker")
    artifact_root = Path(settings.official_account_weekly_artifact_root)
    checkpoints = LocalWeeklyProductionArtifactOwner(artifact_root)
    prepared = PreparedWeeklyDraftArtifactOwner(
        session_factory=session_factory,
        resolver=OfficialAccountLocalMediaResolver(
            image_asset_manifest=settings.image_asset_manifest,
            image_store=MinioImageStore(settings),
            snapshot_store=MinioSnapshotStore(settings),
        ),
        work_root=artifact_root / "prepared",
        inbox_root=Path(settings.wechat_mp_draft_weekly_inbox_root),
        max_image_bytes=settings.wechat_mp_max_image_bytes,
    )
    return ProductionWeeklyDagHandlers(
        checkpoints=checkpoints,
        article_repository=PostgresOfficialAccountRepository(session_factory),
        prepared_artifacts=prepared,
        article_identity=official_account_identity_from_settings(
            settings,
            provider="zhipu",
            model=settings.ai_chat_model,
        ),
        article_wait_seconds=settings.official_account_weekly_article_wait_seconds,
        article_poll_seconds=settings.official_account_weekly_worker_poll_seconds,
    ).registry()


def _require_fixture_enqueue(args: argparse.Namespace) -> None:
    if args.handler_mode != "fixture":
        raise RuntimeError("production weekly inputs are owned by the Monday scheduler")


async def _worker_loop(
    service: OfficialAccountWeeklyDagService,
    args: argparse.Namespace,
) -> int:
    if not 1 <= args.concurrency <= 3:
        raise ValueError("weekly DAG worker concurrency must be between one and three")
    if not 0.1 <= args.poll_seconds <= 60:
        raise ValueError("weekly DAG poll interval must be between 0.1 and 60 seconds")
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    registered_signals: list[signal.Signals] = []
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, stop.set)
        except NotImplementedError:  # pragma: no cover - Unix is the deployed worker runtime.
            continue
        registered_signals.append(signum)
    try:
        while not stop.is_set():
            outcomes = await asyncio.gather(
                *(
                    service.process_once(
                        worker_id=f"{args.worker_id}.{index}",
                        lease_seconds=args.lease_seconds,
                    )
                    for index in range(args.concurrency)
                )
            )
            progressed = tuple(item for item in outcomes if item is not None)
            for status in progressed:
                print(json.dumps(status.as_dict(), ensure_ascii=False, sort_keys=True))
            if args.once or (args.drain and not progressed):
                return 0
            if not progressed:
                try:
                    await asyncio.wait_for(stop.wait(), timeout=args.poll_seconds)
                except TimeoutError:
                    pass
        return 0
    finally:
        for signum in registered_signals:
            loop.remove_signal_handler(signum)


def main() -> None:
    try:
        raise SystemExit(asyncio.run(_run(_parser().parse_args())))
    except KeyboardInterrupt:
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()
