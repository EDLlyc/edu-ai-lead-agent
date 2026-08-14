#!/usr/bin/env python3
from __future__ import annotations

import argparse
import base64
import fcntl
import json
import os
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from functools import partial
from pathlib import Path
from typing import Protocol

from contract import (
    SAFE_ID_RE,
    ContractError,
    ReleaseManifest,
    load_release_manifest,
    sha256_file,
    verify_release_bundle,
)

APPLICATION_SERVICES = (
    "backend-migrate",
    "acquisition-api",
    "acquisition-scheduler",
    "acquisition-worker",
    "governance-scheduler",
    "governance-worker",
    "content-scheduler",
    "content-worker",
    "wecom-dispatcher",
)
LONG_RUNNING_SERVICES = tuple(
    service for service in APPLICATION_SERVICES if service != "backend-migrate"
)
START_PHASES = (
    (
        "api-acquisition",
        ("acquisition-api", "acquisition-scheduler", "acquisition-worker"),
    ),
    ("governance", ("governance-scheduler", "governance-worker")),
    ("content", ("content-scheduler", "content-worker")),
    ("wecom", ("wecom-dispatcher",)),
)
SECRET_RE = re.compile(
    r"(?i)(?:password|passwd|secret|token|authorization|api[_-]?key)\s*[=:]\s*[^\s,;]+"
)
AUTHENTICATED_URL_RE = re.compile(r"https?://[^\s/:@]+:[^\s/@]+@")


class Phase(StrEnum):
    PREFLIGHT = "preflight"
    IMAGE = "image-verification"
    QUIESCE = "quiesce"
    BACKUP = "backup"
    SNAPSHOT = "snapshot"
    ACTIVATE = "activate"
    MIGRATE = "migrate"
    START_API = "start-api-acquisition"
    START_GOVERNANCE = "start-governance"
    START_CONTENT = "start-content"
    START_WECOM = "start-wecom"
    EVIDENCE = "evidence"
    PERSIST = "persist-success"
    ROLLBACK = "rollback"


class PhaseFailure(RuntimeError):
    def __init__(self, phase: Phase, code: str) -> None:
        super().__init__(f"{phase.value}:{code}")
        self.phase = phase
        self.code = code


class RollbackFailure(PhaseFailure):
    pass


def redact_text(value: str) -> str:
    value = AUTHENTICATED_URL_RE.sub("https://[redacted]@", value)
    return SECRET_RE.sub("[redacted]", value)


def emit(event: str, phase: Phase | None = None, **fields: object) -> None:
    safe_fields = {
        key: redact_text(item) if isinstance(item, str) else item
        for key, item in fields.items()
    }
    payload: dict[str, object] = {"event": event, **safe_fields}
    if phase is not None:
        payload["phase"] = phase.value
    print(json.dumps(payload, ensure_ascii=True, sort_keys=True), flush=True)


@dataclass(frozen=True)
class CommandResult:
    stdout: str


class Runner(Protocol):
    def run(
        self,
        arguments: Sequence[str],
        *,
        cwd: Path | None = None,
        timeout: int = 300,
    ) -> CommandResult: ...


class SubprocessRunner:
    def run(
        self,
        arguments: Sequence[str],
        *,
        cwd: Path | None = None,
        timeout: int = 300,
    ) -> CommandResult:
        try:
            completed = subprocess.run(
                list(arguments),
                cwd=cwd,
                check=True,
                capture_output=True,
                text=True,
                timeout=timeout,
                env=os.environ.copy(),
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("command_timeout") from exc
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(f"command_failed_exit_{exc.returncode}") from exc
        return CommandResult(stdout=completed.stdout)


@contextmanager
def exclusive_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, mode=0o755, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise PhaseFailure(Phase.PREFLIGHT, "deployment_lock_busy") from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def rollback_eligible(
    *,
    migration_attempted: bool,
    migration_completed: bool,
    previous_head: str,
    target_head: str,
    compatibility_reviewed: bool,
    previous_application_compatible: bool,
) -> bool:
    if not migration_attempted:
        return True
    if not migration_completed:
        return False
    return previous_head == target_head or (
        compatibility_reviewed and previous_application_compatible
    )


class Actions(Protocol):
    def preflight(self) -> str: ...

    def pull_and_verify_image(self) -> None: ...

    def quiesce(self) -> None: ...

    def backup(self) -> str: ...

    def snapshot_previous(self) -> None: ...

    def activate(self) -> None: ...

    def migrate(self) -> str: ...

    def start_phase(self, name: str, services: Sequence[str]) -> None: ...

    def collect_evidence(self) -> None: ...

    def mark_success(self) -> None: ...

    def restart_previous(self) -> None: ...

    def rollback(self) -> None: ...

    def stop_writers(self) -> None: ...


class DeploymentEngine:
    def __init__(self, manifest: ReleaseManifest, actions: Actions) -> None:
        self.manifest = manifest
        self.actions = actions
        self.phase_order: list[str] = []

    def _step(self, phase: Phase, operation: Callable[[], object]) -> object:
        self.phase_order.append(phase.value)
        emit("deployment_phase_started", phase, commit=self.manifest.source.commit)
        try:
            result = operation()
        except PhaseFailure:
            raise
        except Exception as exc:
            raise PhaseFailure(phase, str(exc)) from exc
        emit("deployment_phase_completed", phase, commit=self.manifest.source.commit)
        return result

    def run(self) -> None:
        quiesced = False
        activated = False
        migration_attempted = False
        migration_completed = False
        previous_head = ""
        try:
            previous_head = str(self._step(Phase.PREFLIGHT, self.actions.preflight))
            self._step(Phase.IMAGE, self.actions.pull_and_verify_image)
            # Quiesce is itself mutating: a failure after the first successful stop must
            # restart the complete previous service set instead of leaving a partial outage.
            quiesced = True
            self._step(Phase.QUIESCE, self.actions.quiesce)
            self._step(Phase.BACKUP, self.actions.backup)
            self._step(Phase.SNAPSHOT, self.actions.snapshot_previous)
            activated = True
            self._step(Phase.ACTIVATE, self.actions.activate)
            migration_attempted = True
            migrated_head = str(self._step(Phase.MIGRATE, self.actions.migrate))
            if migrated_head != self.manifest.database.alembic_head:
                raise PhaseFailure(Phase.MIGRATE, "unexpected_alembic_head")
            migration_completed = True
            for index, (name, services) in enumerate(START_PHASES):
                phase = (
                    Phase.START_API,
                    Phase.START_GOVERNANCE,
                    Phase.START_CONTENT,
                    Phase.START_WECOM,
                )[index]
                self._step(
                    phase,
                    partial(self.actions.start_phase, name, services),
                )
            self._step(Phase.EVIDENCE, self.actions.collect_evidence)
            self._step(Phase.PERSIST, self.actions.mark_success)
            emit(
                "deployment_completed",
                commit=self.manifest.source.commit,
                digest=self.manifest.image.digest,
            )
        except PhaseFailure as failure:
            emit(
                "deployment_failed",
                failure.phase,
                code=failure.code,
                commit=self.manifest.source.commit,
            )
            if quiesced and not activated:
                try:
                    self.actions.restart_previous()
                    emit("previous_release_restarted", Phase.ROLLBACK)
                except Exception as exc:
                    self.actions.stop_writers()
                    raise RollbackFailure(
                        Phase.ROLLBACK, "previous_restart_failed"
                    ) from exc
            elif activated:
                eligible = rollback_eligible(
                    migration_attempted=migration_attempted,
                    migration_completed=migration_completed,
                    previous_head=previous_head,
                    target_head=self.manifest.database.alembic_head,
                    compatibility_reviewed=self.manifest.database.compatibility_reviewed,
                    previous_application_compatible=(
                        self.manifest.database.previous_application_compatible
                    ),
                )
                emit("rollback_evaluated", Phase.ROLLBACK, eligible=eligible)
                if eligible:
                    try:
                        self.actions.rollback()
                        emit("rollback_completed", Phase.ROLLBACK)
                    except Exception as exc:
                        self.actions.stop_writers()
                        raise RollbackFailure(
                            Phase.ROLLBACK, "automatic_rollback_failed"
                        ) from exc
                else:
                    self.actions.stop_writers()
                    emit("rollback_requires_incident_response", Phase.ROLLBACK)
            raise


@dataclass(frozen=True)
class DeploymentPaths:
    active: Path
    releases: Path
    state: Path
    backups: Path
    lock: Path


class ProductionActions:
    def __init__(
        self,
        manifest: ReleaseManifest,
        manifest_path: Path,
        bundle_path: Path,
        staging: Path,
        paths: DeploymentPaths,
        runner_id: str,
        runner: Runner,
    ) -> None:
        self.manifest = manifest
        self.manifest_path = manifest_path
        self.bundle_path = bundle_path
        self.staging = staging
        self.paths = paths
        self.runner_id = runner_id
        self.runner = runner
        self.previous_manifest: ReleaseManifest | None = None
        self.previous_head = ""
        self.previous_snapshot: Path | None = None
        self.backup_id = ""
        self.env_sha256 = ""
        self.previous_restart_counts: dict[str, int] = {}

    def _compose(
        self,
        *arguments: str,
        cwd: Path | None = None,
        release_env: Path | None = None,
        timeout: int = 300,
    ) -> CommandResult:
        workdir = cwd or self.paths.active
        env_path = release_env or (self.paths.active / ".release.env")
        command = [
            "docker",
            "compose",
            "--env-file",
            str(self.paths.active / ".env"),
            "--env-file",
            str(env_path),
            "--profile",
            "governance",
            "--profile",
            "content",
            "--profile",
            "wecom",
            *arguments,
        ]
        return self.runner.run(command, cwd=workdir, timeout=timeout)

    def _psql_scalar(self, query: str) -> str:
        encoded_query = base64.b64encode(query.encode()).decode("ascii")
        result = self._compose(
            "exec",
            "-T",
            "postgres",
            "sh",
            "-c",
            'printf %s "$1" | base64 -d | '
            'psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At',
            "sh",
            encoded_query,
        )
        return result.stdout.strip()

    def _write_release_env(self, destination: Path) -> None:
        content = (
            f"APP_IMAGE={self.manifest.image.reference}\n"
            f"RELEASE_COMMIT={self.manifest.source.commit}\n"
            f"RELEASE_MARKER={self.manifest.source.release_marker}\n"
            f"RELEASE_MANIFEST_SHA256={sha256_file(self.manifest_path)}\n"
            f"RELEASE_BUNDLE_SHA256={self.manifest.bundle.sha256}\n"
        )
        destination.write_text(content, encoding="utf-8")
        destination.chmod(0o600)

    @staticmethod
    def _write_private_marker(destination: Path, content: str) -> None:
        temporary = destination.with_name(f".{destination.name}.release-tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.chmod(0o600)
        os.replace(temporary, destination)

    @staticmethod
    def _require_private_root_file(path: Path) -> None:
        if not path.is_file() or path.is_symlink():
            raise RuntimeError("release_state_file_is_not_regular")
        details = path.stat()
        if details.st_uid != 0 or stat.S_IMODE(details.st_mode) & 0o077:
            raise RuntimeError("release_state_file_permissions_are_too_broad")

    def _load_previous_manifest(self) -> ReleaseManifest:
        current = self.paths.state / "current.json"
        if not current.is_file():
            raise RuntimeError("previous_release_manifest_missing")
        previous = load_release_manifest(current)
        if previous.source.commit == self.manifest.source.commit:
            raise RuntimeError("duplicate_release_commit")
        if previous.build.created >= self.manifest.build.created:
            raise RuntimeError("release_is_not_newer_than_current")
        return previous

    def _verify_previous_runtime_markers(self, previous: ReleaseManifest) -> None:
        active_manifest_path = self.paths.active / ".release-manifest.json"
        active_manifest = load_release_manifest(active_manifest_path)
        if active_manifest != previous:
            raise RuntimeError("active_and_current_release_manifests_differ")
        if (self.paths.active / ".release-commit").read_text(
            encoding="utf-8"
        ).strip() != previous.source.commit:
            raise RuntimeError("previous_release_commit_marker_mismatch")
        runner_id = (
            (self.paths.active / ".release-runner").read_text(encoding="utf-8").strip()
        )
        if SAFE_ID_RE.fullmatch(runner_id) is None:
            raise RuntimeError("previous_release_runner_marker_invalid")
        release_env_path = self.paths.active / ".release.env"
        values: dict[str, str] = {}
        for line in release_env_path.read_text(encoding="utf-8").splitlines():
            if not line or "=" not in line:
                raise RuntimeError("previous_release_environment_invalid")
            key, value = line.split("=", 1)
            if key in values or not key or not value:
                raise RuntimeError("previous_release_environment_invalid")
            values[key] = value
        expected = {
            "APP_IMAGE": previous.image.reference,
            "RELEASE_COMMIT": previous.source.commit,
            "RELEASE_MARKER": previous.source.release_marker,
            "RELEASE_MANIFEST_SHA256": sha256_file(active_manifest_path),
            "RELEASE_BUNDLE_SHA256": previous.bundle.sha256,
        }
        if values != expected:
            raise RuntimeError("previous_release_environment_mismatch")

    def _queue_running_count(self) -> int:
        query = """
SELECT
  (SELECT count(*) FROM acquisition_jobs WHERE status = 'running') +
  (SELECT count(*) FROM governance_jobs WHERE status = 'running') +
  (SELECT count(*) FROM topic_selection_jobs WHERE status = 'running') +
  (SELECT count(*) FROM content_slot_jobs WHERE status = 'running') +
  (SELECT count(*) FROM brand_ingestion_jobs WHERE status = 'running') +
  (SELECT count(*) FROM copy_generation_jobs WHERE status = 'running') +
  (SELECT count(*) FROM image_artifacts WHERE status = 'running') +
  (SELECT count(*) FROM wecom_delivery_jobs WHERE status IN ('running', 'partial', 'delivery_unknown'))
""".strip()
        value = self._psql_scalar(query)
        if not value.isdigit():
            raise RuntimeError("queue_preflight_not_numeric")
        return int(value)

    def preflight(self) -> str:
        if os.geteuid() != 0:
            raise RuntimeError("deployment_requires_root")
        if SAFE_ID_RE.fullmatch(self.runner_id) is None:
            raise RuntimeError("runner_identity_is_invalid")
        required = (
            self.paths.active / ".env",
            self.paths.active / ".release.env",
            self.paths.active / ".release-commit",
            self.paths.active / ".release-manifest.json",
            self.paths.active / ".release-runner",
            self.paths.active / "compose.yaml",
            self.paths.active / "private" / "brand-materials",
        )
        if any(not path.exists() for path in required):
            raise RuntimeError("active_runtime_prerequisite_missing")
        for private_file in (
            self.paths.active / ".env",
            self.paths.active / ".release.env",
            self.paths.active / ".release-commit",
            self.paths.active / ".release-manifest.json",
            self.paths.active / ".release-runner",
            self.paths.state / "current.json",
        ):
            self._require_private_root_file(private_file)
        self.env_sha256 = sha256_file(self.paths.active / ".env")
        if shutil.disk_usage(self.paths.active).free < 5 * 1024 * 1024 * 1024:
            raise RuntimeError("insufficient_free_disk")
        self.runner.run(["systemctl", "is-enabled", "edu-ai-backup.timer"])
        self.runner.run(["systemctl", "is-active", "edu-ai-backup.timer"])
        self.previous_manifest = self._load_previous_manifest()
        self._verify_previous_runtime_markers(self.previous_manifest)
        self.previous_restart_counts = self._verify_services(
            LONG_RUNNING_SERVICES,
            expected_image=self.previous_manifest.image.reference,
            require_zero_restarts=False,
        )
        emit(
            "previous_release_services_verified",
            service_count=len(self.previous_restart_counts),
            restart_count=sum(self.previous_restart_counts.values()),
        )
        self.previous_head = self._psql_scalar(
            "SELECT version_num FROM alembic_version"
        )
        if not self.previous_head:
            raise RuntimeError("previous_alembic_head_missing")
        if self._queue_running_count() != 0:
            raise RuntimeError("running_or_ambiguous_durable_jobs")
        return self.previous_head

    def pull_and_verify_image(self) -> None:
        image = self.manifest.image.reference
        self.runner.run(["docker", "pull", image], timeout=900)
        result = self.runner.run(["docker", "image", "inspect", image])
        try:
            details = json.loads(result.stdout)[0]
            config = details["Config"]
            labels = config["Labels"]
        except (IndexError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError("image_inspection_is_invalid") from exc
        if image not in details.get("RepoDigests", []):
            raise RuntimeError("pulled_image_digest_does_not_match")
        if (
            labels.get("org.opencontainers.image.revision")
            != self.manifest.source.commit
        ):
            raise RuntimeError("image_revision_label_mismatch")
        if labels.get("org.opencontainers.image.source") != self.manifest.source.url:
            raise RuntimeError("image_source_label_mismatch")
        if (
            labels.get("org.opencontainers.image.created")
            != self.manifest.build.created
        ):
            raise RuntimeError("image_created_label_mismatch")
        if (
            labels.get("org.opencontainers.image.base.name")
            != self.manifest.build.python_base
        ):
            raise RuntimeError("image_base_label_mismatch")
        if config.get("User") != "app" or config.get("WorkingDir") != "/app":
            raise RuntimeError("image_runtime_identity_mismatch")
        probe_prefix = [
            "docker",
            "run",
            "--rm",
            "--network",
            "none",
            "--read-only",
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=16m",
            "--user",
            "app",
            image,
        ]
        self.runner.run(
            [
                *probe_prefix,
                "python",
                "-c",
                "import alembic, fastapi, minio, sqlalchemy; import app.api_main",
            ]
        )
        self.runner.run([*probe_prefix, "python", "-m", "pip", "check"])

    def quiesce(self) -> None:
        for services in (
            ("wecom-dispatcher",),
            ("content-scheduler", "content-worker"),
            ("governance-scheduler", "governance-worker"),
            ("acquisition-scheduler", "acquisition-worker"),
            ("acquisition-api",),
        ):
            self._compose("stop", "--timeout", "60", *services, timeout=180)
        if self._queue_running_count() != 0:
            raise RuntimeError("durable_jobs_remain_after_quiesce")

    def backup(self) -> str:
        assert self.previous_manifest is not None
        result = self.runner.run(
            [str(self.staging / "scripts" / "edu-ai-backup.sh")],
            cwd=self.paths.active,
            timeout=3600,
        )
        match = re.search(r"\bbackup_id=([0-9]{8}T[0-9]{6}Z)\b", result.stdout)
        if match is None:
            raise RuntimeError("backup_evidence_identifier_missing")
        self.backup_id = match.group(1)
        evidence = (
            Path("/var/backups/edu-ai/releases")
            / self.backup_id
            / "backup-evidence.txt"
        )
        if not evidence.is_file():
            raise RuntimeError("backup_evidence_file_missing")
        self._require_private_root_file(evidence)
        values: dict[str, str] = {}
        for line in evidence.read_text(encoding="utf-8").splitlines():
            if not line or "=" not in line:
                raise RuntimeError("backup_evidence_invalid")
            key, value = line.split("=", 1)
            if key in values or not key or not value:
                raise RuntimeError("backup_evidence_invalid")
            values[key] = value
        expected_keys = {
            "schema_version",
            "backup_id",
            "release_commit",
            "release_image",
            "postgres_file",
            "postgres_sha256",
            "minio_file_count",
            "minio_manifest_sha256",
            "brand_file",
            "brand_sha256",
        }
        if set(values) != expected_keys:
            raise RuntimeError("backup_evidence_keys_mismatch")
        if (
            values["schema_version"] != "1"
            or values["backup_id"] != self.backup_id
            or values["release_commit"] != self.previous_manifest.source.commit
            or values["release_image"] != self.previous_manifest.image.reference
        ):
            raise RuntimeError("backup_evidence_release_mismatch")
        expected_postgres_file = f"edu-ai-{self.backup_id}.dump"
        expected_brand_file = f"brand-materials-{self.backup_id}.tar.gz"
        if (
            values["postgres_file"] != expected_postgres_file
            or values["brand_file"] != expected_brand_file
            or re.fullmatch(r"[0-9a-f]{64}", values["postgres_sha256"]) is None
            or re.fullmatch(r"[0-9a-f]{64}", values["minio_manifest_sha256"]) is None
            or re.fullmatch(r"[0-9a-f]{64}", values["brand_sha256"]) is None
            or not values["minio_file_count"].isdigit()
        ):
            raise RuntimeError("backup_evidence_value_invalid")
        postgres_file = Path("/var/backups/edu-ai/postgres") / expected_postgres_file
        brand_file = Path("/var/backups/edu-ai/brand-materials") / expected_brand_file
        minio_dir = Path("/var/backups/edu-ai/minio") / self.backup_id
        minio_manifest = minio_dir / "SHA256SUMS"
        if any(
            not path.is_file() or path.is_symlink()
            for path in (postgres_file, brand_file, minio_manifest)
        ):
            raise RuntimeError("backup_artifact_missing_or_unsafe")
        minio_files = [
            path
            for path in minio_dir.rglob("*")
            if path.is_file() and path.name != "SHA256SUMS"
        ]
        if any(path.is_symlink() for path in minio_dir.rglob("*")):
            raise RuntimeError("backup_artifact_contains_symlink")
        if (
            sha256_file(postgres_file) != values["postgres_sha256"]
            or sha256_file(brand_file) != values["brand_sha256"]
            or sha256_file(minio_manifest) != values["minio_manifest_sha256"]
            or len(minio_files) != int(values["minio_file_count"])
        ):
            raise RuntimeError("backup_artifact_checksum_or_count_mismatch")
        self.runner.run(["sha256sum", "-c", "SHA256SUMS"], cwd=minio_dir, timeout=900)
        return self.backup_id

    def snapshot_previous(self) -> None:
        assert self.previous_manifest is not None
        timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        snapshot = (
            self.paths.backups
            / f"{timestamp}-{self.previous_manifest.source.release_marker}"
        )
        snapshot.mkdir(parents=True, mode=0o700)
        paths = (
            "compose.yaml",
            "scripts",
            "deploy/release",
            "backend/alembic.ini",
            "backend/alembic/versions",
            ".release.env",
            ".release-commit",
            ".release-manifest.json",
            ".release-runner",
        )
        for relative in paths:
            source = self.paths.active / relative
            if not source.exists():
                continue
            destination = snapshot / relative
            destination.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
            if source.is_symlink():
                raise RuntimeError("previous_runtime_contains_symlink")
            if source.is_dir():
                if any(path.is_symlink() for path in source.rglob("*")):
                    raise RuntimeError("previous_runtime_contains_symlink")
                shutil.copytree(source, destination)
            else:
                shutil.copy2(source, destination)
        (snapshot / "protected-inputs.txt").write_text(
            (
                f"env_sha256={self.env_sha256}\n"
                f"previous_commit={self.previous_manifest.source.commit}\n"
                "restart_counts="
                + ",".join(
                    f"{name}:{count}"
                    for name, count in sorted(self.previous_restart_counts.items())
                )
                + "\n"
            ),
            encoding="utf-8",
        )
        (snapshot / "protected-inputs.txt").chmod(0o600)
        self.previous_snapshot = snapshot

    def activate(self) -> None:
        for directory in (
            self.paths.active / "deploy" / "release",
            self.paths.active / "backend" / "alembic" / "versions",
        ):
            if directory.exists():
                shutil.rmtree(directory)
        for source in sorted(self.staging.rglob("*")):
            if not source.is_file():
                continue
            relative = source.relative_to(self.staging)
            destination = self.paths.active / relative
            destination.parent.mkdir(parents=True, mode=0o755, exist_ok=True)
            temporary = destination.with_name(f".{destination.name}.release-tmp")
            shutil.copy2(source, temporary)
            os.replace(temporary, destination)
        release_env_tmp = self.paths.active / ".release.env.tmp"
        self._write_release_env(release_env_tmp)
        os.replace(release_env_tmp, self.paths.active / ".release.env")
        self._write_private_marker(
            self.paths.active / ".release-commit",
            f"{self.manifest.source.commit}\n",
        )
        self._write_private_marker(
            self.paths.active / ".release-runner", f"{self.runner_id}\n"
        )
        shutil.copy2(self.manifest_path, self.paths.active / ".release-manifest.json")
        (self.paths.active / ".release-manifest.json").chmod(0o600)
        if sha256_file(self.paths.active / ".env") != self.env_sha256:
            raise RuntimeError("production_env_changed_during_activation")

    def _verify_compose_images(
        self, cwd: Path | None = None, release_env: Path | None = None
    ) -> None:
        rendered = self._compose(
            "config", "--format", "json", cwd=cwd, release_env=release_env
        ).stdout
        try:
            services = json.loads(rendered)["services"]
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise RuntimeError("compose_render_output_is_invalid") from exc
        images = {
            name: services.get(name, {}).get("image") for name in APPLICATION_SERVICES
        }
        if any(value != self.manifest.image.reference for value in images.values()):
            raise RuntimeError("compose_application_images_are_not_one_digest")

    def migrate(self) -> str:
        self._compose("config", "--quiet")
        self._verify_compose_images()
        self._compose("up", "-d", "--no-build", "minio-init", timeout=300)
        self._compose("wait", "minio-init", timeout=300)
        self._compose("run", "--rm", "--no-deps", "backend-migrate", timeout=1800)
        return self._psql_scalar("SELECT version_num FROM alembic_version")

    def _verify_services(
        self,
        services: Sequence[str],
        *,
        expected_image: str | None = None,
        require_zero_restarts: bool = True,
    ) -> dict[str, int]:
        wanted_image = expected_image or self.manifest.image.reference
        deadline = time.monotonic() + 180
        while True:
            waiting: list[str] = []
            restart_counts: dict[str, int] = {}
            for service in services:
                container_id = self._compose("ps", "-q", service).stdout.strip()
                if not container_id:
                    waiting.append(service)
                    continue
                result = self.runner.run(["docker", "inspect", container_id])
                try:
                    details = json.loads(result.stdout)[0]
                    state = details["State"]
                    configured_image = details["Config"]["Image"]
                    restart_count = int(details.get("RestartCount", 0))
                except (
                    IndexError,
                    KeyError,
                    TypeError,
                    ValueError,
                    json.JSONDecodeError,
                ) as exc:
                    raise RuntimeError(f"service_inspection_invalid_{service}") from exc
                if configured_image != wanted_image:
                    raise RuntimeError(f"service_image_mismatch_{service}")
                if require_zero_restarts and restart_count != 0:
                    raise RuntimeError(f"service_restart_count_nonzero_{service}")
                restart_counts[service] = restart_count
                if state.get("Status") != "running":
                    waiting.append(service)
                    continue
                health = state.get("Health", {}).get("Status")
                if health not in {None, "healthy"}:
                    waiting.append(service)
            if not waiting:
                return restart_counts
            if time.monotonic() >= deadline:
                raise RuntimeError("services_not_ready_" + "_".join(sorted(waiting)))
            time.sleep(2)

    def start_phase(self, name: str, services: Sequence[str]) -> None:
        del name
        self._compose(
            "up", "-d", "--no-build", "--force-recreate", *services, timeout=600
        )
        self._verify_services(services)

    def collect_evidence(self) -> None:
        if sha256_file(self.paths.active / ".env") != self.env_sha256:
            raise RuntimeError("production_env_checksum_changed")
        ambiguous = self._psql_scalar(
            "SELECT count(*) FROM wecom_delivery_jobs "
            "WHERE status IN ('partial', 'delivery_unknown')"
        )
        if ambiguous != "0":
            raise RuntimeError("ambiguous_delivery_state_detected")
        self._verify_services(LONG_RUNNING_SERVICES)
        self.runner.run(
            [str(self.paths.active / "scripts" / "edu-ai-production-evidence.sh")],
            cwd=self.paths.active,
            timeout=600,
        )
        time.sleep(10)
        self._verify_services(LONG_RUNNING_SERVICES)

    def mark_success(self) -> None:
        self.paths.state.mkdir(parents=True, mode=0o700, exist_ok=True)
        release_manifest = self.paths.state / f"{self.manifest.source.commit}.json"
        shutil.copy2(self.manifest_path, release_manifest)
        release_manifest.chmod(0o600)
        current_tmp = self.paths.state / ".current.json.tmp"
        shutil.copy2(self.manifest_path, current_tmp)
        current_tmp.chmod(0o600)
        os.replace(current_tmp, self.paths.state / "current.json")
        evidence = {
            "schema_version": 1,
            "commit": self.manifest.source.commit,
            "image_digest": self.manifest.image.digest,
            "bundle_sha256": self.manifest.bundle.sha256,
            "backup_id": self.backup_id,
            "runner_id": self.runner_id,
            "completed_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        evidence_path = (
            self.paths.state / f"{self.manifest.source.commit}.evidence.json"
        )
        evidence_path.write_text(
            json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        evidence_path.chmod(0o600)

    def restart_previous(self) -> None:
        self._compose(
            "up",
            "-d",
            "--no-build",
            "--force-recreate",
            *LONG_RUNNING_SERVICES,
            timeout=900,
        )
        self._verify_services(LONG_RUNNING_SERVICES)

    def rollback(self) -> None:
        if self.previous_snapshot is None or self.previous_manifest is None:
            raise RuntimeError("previous_runtime_snapshot_missing")
        self.stop_writers()
        for directory in (
            self.paths.active / "deploy" / "release",
            self.paths.active / "backend" / "alembic" / "versions",
        ):
            if directory.exists():
                shutil.rmtree(directory)
        for source in sorted(self.previous_snapshot.rglob("*")):
            if not source.is_file() or source.name == "protected-inputs.txt":
                continue
            relative = source.relative_to(self.previous_snapshot)
            destination = self.paths.active / relative
            destination.parent.mkdir(parents=True, mode=0o755, exist_ok=True)
            shutil.copy2(source, destination)
        self.restart_previous()
        if sha256_file(self.paths.active / ".env") != self.env_sha256:
            raise RuntimeError("production_env_changed_during_rollback")
        self.runner.run(
            [str(self.paths.active / "scripts" / "edu-ai-production-evidence.sh")],
            cwd=self.paths.active,
            timeout=600,
        )
        rollback_evidence = {
            "schema_version": 1,
            "failed_commit": self.manifest.source.commit,
            "failed_image_digest": self.manifest.image.digest,
            "previous_commit": self.previous_manifest.source.commit,
            "previous_image_digest": self.previous_manifest.image.digest,
            "result": "application_rollback_succeeded",
            "completed_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        rollback_path = (
            self.paths.state / f"{self.manifest.source.commit}.rollback.json"
        )
        rollback_path.write_text(
            json.dumps(rollback_evidence, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        rollback_path.chmod(0o600)

    def stop_writers(self) -> None:
        for services in (
            ("wecom-dispatcher",),
            ("content-scheduler", "content-worker"),
            ("governance-scheduler", "governance-worker"),
            ("acquisition-scheduler", "acquisition-worker"),
            ("acquisition-api",),
        ):
            try:
                self._compose("stop", "--timeout", "30", *services, timeout=120)
            except RuntimeError:
                emit(
                    "writer_stop_degraded", Phase.ROLLBACK, service_count=len(services)
                )

    def dry_run(self, release_env: Path) -> None:
        previous_head = self.preflight()
        self.pull_and_verify_image()
        self._verify_compose_images(cwd=self.staging, release_env=release_env)
        emit(
            "deployment_dry_run_completed",
            commit=self.manifest.source.commit,
            digest=self.manifest.image.digest,
            previous_alembic_head=previous_head,
            predicted_phases=[
                phase.value for phase in Phase if phase != Phase.ROLLBACK
            ],
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Deploy one verified digest release")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--runner-id", required=True)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--active-dir", type=Path, default=Path("/opt/edu-ai-lead-agent")
    )
    parser.add_argument(
        "--releases-dir", type=Path, default=Path("/opt/edu-ai-releases")
    )
    parser.add_argument(
        "--state-dir", type=Path, default=Path("/var/lib/edu-ai/releases")
    )
    parser.add_argument(
        "--backup-dir", type=Path, default=Path("/var/backups/edu-ai/releases")
    )
    parser.add_argument(
        "--lock-file", type=Path, default=Path("/var/lock/edu-ai-deploy.lock")
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest = load_release_manifest(args.manifest.resolve())
        if manifest.source.commit != args.expected_commit:
            raise ContractError(
                "release manifest commit does not match the Flow commit"
            )
        paths = DeploymentPaths(
            active=args.active_dir.resolve(),
            releases=args.releases_dir.resolve(),
            state=args.state_dir.resolve(),
            backups=args.backup_dir.resolve(),
            lock=args.lock_file.resolve(),
        )
        with exclusive_lock(paths.lock):
            if args.dry_run:
                with tempfile.TemporaryDirectory(
                    prefix="edu-ai-release-dry-run-"
                ) as temporary:
                    staging = Path(temporary) / manifest.source.commit
                    verify_release_bundle(args.bundle.resolve(), manifest, staging)
                    release_env = Path(temporary) / "release.env"
                    actions = ProductionActions(
                        manifest,
                        args.manifest.resolve(),
                        args.bundle.resolve(),
                        staging,
                        paths,
                        args.runner_id,
                        SubprocessRunner(),
                    )
                    actions._write_release_env(release_env)
                    actions.dry_run(release_env)
            else:
                if os.geteuid() != 0:
                    raise ContractError("deployment requires root")
                staging = paths.releases / manifest.source.commit
                if staging.exists():
                    raise ContractError(
                        "immutable release staging directory already exists"
                    )
                verify_release_bundle(args.bundle.resolve(), manifest, staging)
                actions = ProductionActions(
                    manifest,
                    args.manifest.resolve(),
                    args.bundle.resolve(),
                    staging,
                    paths,
                    args.runner_id,
                    SubprocessRunner(),
                )
                DeploymentEngine(manifest, actions).run()
    except (ContractError, PhaseFailure) as exc:
        emit("deployment_entrypoint_failed", code=str(exc))
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
