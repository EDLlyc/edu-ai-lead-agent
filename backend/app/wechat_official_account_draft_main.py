"""Default-off CLI for durable WeChat Official Account draft-only automation."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import signal
from collections.abc import Callable
from pathlib import Path
from uuid import UUID, uuid4

from app.application.ports.wechat_official_account import WeChatOfficialAccountError
from app.application.ports.wechat_official_account_draft_artifacts import (
    WeChatDraftArtifactError,
)
from app.application.services.official_account_weekly_edition import (
    WeeklyEditionLiveProvenanceError,
)
from app.application.services.wechat_official_account_draft_jobs import (
    WeChatOfficialAccountDraftJobExecutor,
    WeChatOfficialAccountDraftJobService,
)
from app.core.config import Settings, get_settings
from app.core.logging import configure_logging
from app.domain.wechat_official_account_draft_jobs import (
    WeChatDraftJobFailure,
    wechat_draft_account_fingerprint,
)
from app.infrastructure.db.session import create_engine, create_session_factory
from app.infrastructure.db.wechat_official_account_draft_jobs import (
    PostgresWeChatOfficialAccountDraftJobRepository,
)
from app.infrastructure.wechat_official_account.artifacts import (
    LocalWeChatDraftArtifactStore,
)
from app.infrastructure.wechat_official_account.client import (
    WeChatOfficialAccountHttpClient,
)

_DISABLED = "wechat_mp_draft_automation_disabled"
_AUTO_DISABLED = "wechat_mp_draft_auto_enqueue_disabled"
_INVALID_WEEKLY = "weekly_edition_invalid"
_JOB_NOT_FOUND = "wechat_mp_draft_job_not_found"
_INTERNAL_ERROR = "wechat_mp_draft_internal"


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    enqueue = subparsers.add_parser("enqueue-weekly")
    enqueue.add_argument("weekly_aggregate_dir", type=Path)

    reconcile = subparsers.add_parser("reconcile")
    reconcile.add_argument("--once", action="store_true")
    reconcile.add_argument("--maximum", type=int, default=100)

    status = subparsers.add_parser("status")
    status.add_argument("job_id", type=UUID)

    worker = subparsers.add_parser("worker")
    mode = worker.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true")
    mode.add_argument("--drain", action="store_true")
    worker.add_argument(
        "--worker-id",
        default=f"wechat.worker.{os.getpid()}.{uuid4().hex}",
    )
    return parser


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    configure_logging(json_output=settings.app_env != "development")
    gate_error = _command_gate(args.command, settings)
    if gate_error is not None:
        _print_json({"ok": False, "error_code": gate_error})
        return 3

    engine = create_engine(settings)
    client: WeChatOfficialAccountHttpClient | None = None
    try:
        repository = PostgresWeChatOfficialAccountDraftJobRepository(create_session_factory(engine))
        if args.command == "status":
            status = await repository.get_status(args.job_id)
            _print_json({"ok": True, **status.as_dict()})
            return 0

        artifact_store = LocalWeChatDraftArtifactStore(
            staging_root=Path(settings.wechat_mp_draft_artifact_root),
            inbox_root=Path(settings.wechat_mp_draft_weekly_inbox_root),
        )
        job_service = _job_service(
            settings=settings,
            repository=repository,
            artifact_store=artifact_store,
        )
        if args.command == "enqueue-weekly":
            result = await job_service.enqueue_weekly(args.weekly_aggregate_dir)
            _print_json({"ok": True, **result.as_dict()})
            return 0
        if args.command == "reconcile":
            return await _reconcile_loop(
                job_service,
                once=args.once,
                maximum=args.maximum,
                poll_seconds=settings.wechat_mp_draft_poll_seconds,
            )
        if args.command == "worker":
            client = WeChatOfficialAccountHttpClient(settings)
            executor = WeChatOfficialAccountDraftJobExecutor(
                repository=repository,
                artifact_store=artifact_store,
                client=client,
                lease_seconds=settings.wechat_mp_draft_lease_seconds,
                heartbeat_seconds=settings.wechat_mp_draft_heartbeat_seconds,
                retry_base_seconds=settings.wechat_mp_draft_retry_base_seconds,
                max_image_bytes=settings.wechat_mp_max_image_bytes,
            )
            return await _worker_loop(
                executor=executor,
                job_service=(
                    job_service if settings.wechat_mp_draft_auto_enqueue_enabled else None
                ),
                worker_id=args.worker_id,
                once=args.once,
                drain=args.drain,
                poll_seconds=settings.wechat_mp_draft_poll_seconds,
            )
        raise AssertionError("WeChat draft command routing is incomplete")
    except WeeklyEditionLiveProvenanceError as exc:
        _print_json({"ok": False, "error_code": exc.code})
        return 4
    except WeChatDraftArtifactError as exc:
        _print_json({"ok": False, "error_code": exc.code})
        return 4
    except WeChatOfficialAccountError as exc:
        _print_json({"ok": False, "error_code": exc.code})
        return 5
    except WeChatDraftJobFailure as exc:
        _print_json({"ok": False, "error_code": exc.error_code})
        return 5
    except LookupError:
        _print_json({"ok": False, "error_code": _JOB_NOT_FOUND})
        return 4
    except (OSError, ValueError):
        _print_json({"ok": False, "error_code": _INVALID_WEEKLY})
        return 4
    except Exception:
        _print_json({"ok": False, "error_code": _INTERNAL_ERROR})
        return 1
    finally:
        if client is not None:
            await client.aclose()
        await engine.dispose()


def _job_service(
    *,
    settings: Settings,
    repository: PostgresWeChatOfficialAccountDraftJobRepository,
    artifact_store: LocalWeChatDraftArtifactStore,
) -> WeChatOfficialAccountDraftJobService:
    app_id = settings.wechat_mp_app_id
    if app_id is None:
        raise ValueError("WeChat AppID is unavailable")
    return WeChatOfficialAccountDraftJobService(
        repository=repository,
        artifact_store=artifact_store,
        account_fingerprint=wechat_draft_account_fingerprint(app_id.get_secret_value()),
        max_attempts=settings.wechat_mp_draft_max_attempts,
        max_image_bytes=settings.wechat_mp_max_image_bytes,
    )


def _command_gate(command: str, settings: Settings) -> str | None:
    if command == "status":
        return None
    if not settings.wechat_mp_draft_worker_enabled:
        return _DISABLED
    if command == "reconcile" and not settings.wechat_mp_draft_auto_enqueue_enabled:
        return _AUTO_DISABLED
    return None


async def _reconcile_loop(
    service: WeChatOfficialAccountDraftJobService,
    *,
    once: bool,
    maximum: int,
    poll_seconds: float,
) -> int:
    stop, cleanup = _signal_stop()
    try:
        while not stop.is_set():
            result = await service.reconcile(maximum=maximum)
            _print_json({"ok": True, **result.as_dict()})
            if once:
                return 0
            await _wait_for_stop(stop, poll_seconds)
        return 0
    finally:
        cleanup()


async def _worker_loop(
    *,
    executor: WeChatOfficialAccountDraftJobExecutor,
    job_service: WeChatOfficialAccountDraftJobService | None,
    worker_id: str,
    once: bool,
    drain: bool,
    poll_seconds: float,
) -> int:
    stop, cleanup = _signal_stop()
    try:
        while not stop.is_set():
            if job_service is not None:
                reconciled = await job_service.reconcile()
                _print_json({"ok": True, "event": "reconciled", **reconciled.as_dict()})
            status = await executor.execute_next(worker_id)
            if status is not None:
                _print_json({"ok": True, "event": "processed", **status.as_dict()})
            if once or (drain and status is None):
                return 0
            if status is None:
                await _wait_for_stop(stop, poll_seconds)
        return 0
    finally:
        cleanup()


def _signal_stop() -> tuple[asyncio.Event, Callable[[], None]]:
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    registered: list[signal.Signals] = []
    for signum in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signum, stop.set)
        except NotImplementedError:  # pragma: no cover - Unix is the production runtime.
            continue
        registered.append(signum)

    def cleanup() -> None:
        for signum in registered:
            loop.remove_signal_handler(signum)

    return stop, cleanup


async def _wait_for_stop(stop: asyncio.Event, interval_seconds: float) -> None:
    try:
        async with asyncio.timeout(interval_seconds):
            await stop.wait()
    except TimeoutError:
        return


def _print_json(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def main() -> None:
    try:
        raise SystemExit(asyncio.run(_run(_parser().parse_args())))
    except KeyboardInterrupt:
        raise SystemExit(130) from None


if __name__ == "__main__":
    main()
