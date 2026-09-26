"""Prepare and explicitly queue one visible fixed-group triple test; never send here."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from collections.abc import Mapping
from pathlib import Path
from uuid import UUID

from app.application.services.wecom_infographic_test import WeComInfographicVisibleTest
from app.core.config import get_settings
from app.core.errors import AppError
from app.infrastructure.db.session import create_engine, create_session_factory
from app.infrastructure.storage.minio_image_store import MinioImageStore


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    preflight = commands.add_parser("preflight", help="read current-news identity and fixed target")
    preflight.add_argument("--formal-base-job-id", type=UUID, required=True)
    prepare = commands.add_parser("prepare", help="create a visibly marked private test JPEG")
    prepare.add_argument("--formal-base-job-id", type=UUID, required=True)
    prepare.add_argument("--expect-target-fingerprint", required=True)
    prepare.add_argument("--preview-output", type=Path, required=True)
    queue = commands.add_parser("queue", help="approve exact preview SHA and enqueue triple send")
    queue.add_argument("--test-run-id", type=UUID, required=True)
    queue.add_argument("--expect-target-fingerprint", required=True)
    queue.add_argument("--approve-artifact-sha256", required=True)
    queue.add_argument("--execute", action="store_true", required=True)
    status = commands.add_parser("status", help="read safe durable receipt and attempts")
    status.add_argument("--test-run-id", type=UUID, required=True)
    return parser


def _write_preview(path: Path, body: bytes) -> None:
    if not path.is_absolute() or ".." in path.parts or path.exists() or path.is_symlink():
        raise ValueError("preview output must be a fresh absolute path")
    if any(parent.is_symlink() for parent in path.parents):
        raise ValueError("preview output parents must not be symlinks")
    if not path.parent.is_dir():
        raise ValueError("preview output parent must already exist")
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    try:
        with os.fdopen(descriptor, "wb", closefd=False) as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
    finally:
        os.close(descriptor)


async def _run(args: argparse.Namespace) -> int:
    settings = get_settings()
    engine = create_engine(settings)
    try:
        service = WeComInfographicVisibleTest(
            session_factory=create_session_factory(engine),
            image_store=MinioImageStore(settings),
            settings=settings,
        )
        result: Mapping[str, object]
        if args.command == "preflight":
            result = await service.preflight(args.formal_base_job_id)
        elif args.command == "prepare":
            run, body = await service.prepare(
                args.formal_base_job_id,
                expected_target_fingerprint=args.expect_target_fingerprint,
            )
            _write_preview(args.preview_output, body)
            result = {
                "test_run_id": str(run.id),
                "test_artifact_sha256": run.test_artifact_sha256,
                "test_artifact_byte_size": run.test_artifact_byte_size,
                "target_fingerprint": run.target_fingerprint,
                "preview_output": str(args.preview_output),
                "status": run.status,
            }
        elif args.command == "queue":
            if not args.execute:
                raise ValueError("visible triple test requires --execute")
            run = await service.enqueue(
                args.test_run_id,
                expected_target_fingerprint=args.expect_target_fingerprint,
                approved_artifact_sha256=args.approve_artifact_sha256,
            )
            result = {"test_run_id": str(run.id), "status": run.status}
        else:
            result = await service.status(args.test_run_id)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except (AppError, ValueError) as exc:
        code = exc.code if isinstance(exc, AppError) else "invalid_visible_test_command"
        print(json.dumps({"error": code}, sort_keys=True))
        return 2
    except Exception:
        # A CLI process boundary must not print provider, database or private-object details.
        print(json.dumps({"error": "visible_test_unavailable"}, sort_keys=True))
        return 3
    finally:
        await engine.dispose()


def main() -> int:
    return asyncio.run(_run(_parser().parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
