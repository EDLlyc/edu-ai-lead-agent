"""R16 host adapter used only by the authenticated, one-attempt release CLI.

Real filesystem and Docker operations are never invoked by unit tests. A
green fake-runner test is not a production backup, clone or release receipt.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import tarfile
import time
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, BinaryIO, Protocol, cast
from urllib.parse import quote, urlsplit

from r16_forward_operator import (
    ALEMBIC_ONLY_COMMAND,
    APPROVED_RECIPIENT_FINGERPRINT,
    APPROVED_RECIPIENT_KEY_SHA256,
    ARCHIVE_VOLUMES,
    ATTEMPT_NAME,
    BASE_IMAGE,
    BASE_REF,
    BASE_REVISION,
    BASE_SCHEMA,
    HOST_REPLACEMENTS,
    MINIO_VOLUME,
    OFF_FLAGS,
    PROTECTED_FILES,
    SERVICES,
    TARGET_SCHEMA,
    VOLUMES,
    ReleaseBlocked,
    canonical,
    is_sha,
    quiescent_baseline,
    require,
    sha,
    valid_backup,
    valid_baseline,
    valid_production_manifest,
)

APP = Path("/opt/edu-ai-lead-agent")
# /opt is owned by the application Unix user on the production host. A sealed
# enablement receipt must be under root-owned ancestors all the way to /;
# use a separate, private root path for this one-attempt release backup.
BACKUP_ROOT = Path("/root/edu-ai-release-backups")
PROJECT = "edu-ai-lead-agent"
DEPENDENCY_REFS = {
    "postgres": "pgvector/pgvector:0.8.1-pg16",
    "minio": "minio/minio:RELEASE.2025-04-22T22-12-26Z",
}
DEPENDENCY_VOLUMES = {
    "postgres": "edu-ai-lead-agent_postgres_data",
    "minio": "edu-ai-lead-agent_minio_data",
}
SOURCE_DIRS = ("backend", "deploy", "scripts", "infra")
REPLACED_FILES = HOST_REPLACEMENTS
MAX_COMMAND_OUTPUT = 2 * 1024 * 1024
MIN_RELEASE_FREE_BYTES = 8 * 1024**3
MIN_RELEASE_FREE_INODES = 10_000
HOST_COMMAND_ENV = {
    "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
    "HOME": "/root",
    "DOCKER_CONFIG": "/root/.docker",
    "DOCKER_HOST": "unix:///var/run/docker.sock",
}
# Real paths are armed only after the authenticated operator captures its
# baseline under both existing locks. Direct imports remain unarmed.
# Computed from the independently checked R15 OCI bundle (archive SHA-256 in
# r16_gate.BASE_ARCHIVE_SHA256) loaded as BASE_IMAGE, not from a mutable tag.
# The tree contains /app/app, /app/alembic, alembic.ini and pyproject.toml.
R15_RUNTIME_FILES = 334
R15_RUNTIME_TREE_SHA256 = (
    "c5742de810955c17bb69c36be4868819c3ae73f3cd8691d9f34d96c6f818daa0"
)
# The production 0048 baseline has a specifically reviewed, inert cohort:
# seven August preview copy jobs/runs (claim requires the *current* business
# date) and five terminal September Official Account image-result unknowns.
# This fingerprint includes every relevant row's ID and safety fields. It is
# not a general age/status exemption: any added, removed or changed member
# blocks release. See the task's historical-work review research record.
HISTORICAL_WORK_COHORT_SHA256 = (
    "22fc386e051df9f0cf6509677a929ae53d35e25a4e63775a68b7b20706fa0e12"
)
HISTORICAL_WORK_COHORT_SQL = """
WITH cohort AS (
  SELECT jsonb_build_array('copy_generation_jobs', j.id::text, j.run_id::text,
    j.status, j.attempt_count, j.lease_token IS NULL, r.business_date::text,
    r.scoring_profile, r.status)::text AS line
  FROM copy_generation_jobs j
  JOIN copy_generation_runs r ON r.id=j.run_id
  WHERE j.status IN ('queued','pending','running','delivering','retryable_failed',
    'retry_scheduled','admitted','generating','preparing') OR j.lease_token IS NOT NULL
  UNION ALL
  SELECT jsonb_build_array('copy_generation_runs', r.id::text, r.status,
    r.business_date::text, r.scoring_profile, r.timezone, r.decision_kind,
    (to_jsonb(r)->>'lease_token' IS NULL))::text AS line
  FROM copy_generation_runs r
  WHERE r.status IN ('queued','pending','running','delivering','retryable_failed',
    'retry_scheduled','admitted','generating','preparing')
    OR to_jsonb(r)->>'lease_token' IS NOT NULL
  UNION ALL
  SELECT jsonb_build_array('official_account_article_runs', a.id::text, a.status,
    a.current_stage, a.error_code, a.error_retryable, a.attempt_count,
    a.lease_token IS NULL, a.generation_mode)::text AS line
  FROM official_account_article_runs a
  WHERE a.status IN ('delivery_unknown','result_unknown','outcome_unknown')
    AND (to_jsonb(a)->>'expires_at' IS NULL
      OR (to_jsonb(a)->>'expires_at')::timestamptz > now())
)
SELECT line FROM cohort ORDER BY line
"""
RUNTIME_TREE_SCRIPT = """import hashlib,json,pathlib,stat
roots=('/app/app','/app/alembic','/app/alembic.ini','/app/pyproject.toml')
files={}
for root_name in roots:
    root=pathlib.Path(root_name)
    if root.is_symlink() or not root.exists():
        raise RuntimeError('unsafe runtime root')
    paths=[root] if root.is_file() else sorted(root.rglob('*'))
    for path in paths:
        info=path.lstat()
        if stat.S_ISDIR(info.st_mode):
            continue
        if not stat.S_ISREG(info.st_mode):
            raise RuntimeError('unsafe runtime entry')
        files[str(path)]=hashlib.sha256(path.read_bytes()).hexdigest()
body=json.dumps(files,sort_keys=True,separators=(',',':')).encode()
print(json.dumps({'files':len(files),'sha256':hashlib.sha256(body).hexdigest()}))
"""
PG_CLONE_DB = "edu_ai_r16_clone"
PG_CLONE_USER = "r16_clone"
SAFE_NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*\Z")
MINIO_MC_IMAGE = "minio/mc:RELEASE.2025-04-16T18-13-26Z"
MINIO_MC_IMAGE_ID = (
    "sha256:aead63c77f9db9107f1696fb08ecb0faeda23729cde94b0f663edf4fe09728e3"
)
MAX_MINIO_OBJECTS = 10_000
MAX_MINIO_SOURCE_BYTES = 3 * 1024**3
MAX_MINIO_INVENTORY_BYTES = 64 * 1024**2
MINIO_MIRROR_TIMEOUT = 600
MINIO_INVENTORY_TIMEOUT = 180
SAFE_BUCKET = re.compile(r"[a-z0-9][a-z0-9.-]{2,62}\Z")
SAFE_OBJECT_PART = re.compile(r"[A-Za-z0-9_.-]+\Z")


class Runner(Protocol):
    def run(
        self,
        argv: tuple[str, ...],
        *,
        code: str,
        timeout: int = 60,
        input_file: Path | None = None,
        output_file: Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> bytes: ...


class SubprocessRunner:
    """Never echoes command arguments, stderr, stdout, or environment on error."""

    def run(
        self,
        argv: tuple[str, ...],
        *,
        code: str,
        timeout: int = 60,
        input_file: Path | None = None,
        output_file: Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> bytes:
        source: BinaryIO | None = None
        target: BinaryIO | None = None
        try:
            if input_file is not None:
                source = input_file.open("rb")
            if output_file is not None:
                fd = os.open(
                    output_file,
                    os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
                    0o600,
                )
                target = os.fdopen(fd, "wb")
            result = subprocess.run(
                argv,
                cwd=APP,
                env=dict(env) if env is not None else dict(HOST_COMMAND_ENV),
                stdin=source,
                stdout=target if target is not None else subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
                check=False,
            )
            require(result.returncode == 0, code)
            if target is not None:
                target.flush()
                os.fsync(target.fileno())
                return b""
            body = result.stdout
            require(isinstance(body, bytes) and len(body) <= MAX_COMMAND_OUTPUT, code)
            return body
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise ReleaseBlocked(code) from exc
        finally:
            if source is not None:
                source.close()
            if target is not None:
                target.close()


def _regular_file(path: Path, *, private: bool = False) -> os.stat_result:
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1, "unsafe_file_type")
    if private:
        require(stat.S_IMODE(info.st_mode) == 0o600, "private_file_mode")
    return info


def _metadata(path: Path) -> dict[str, int | str]:
    info = _regular_file(path)
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while part := stream.read(1024 * 1024):
            digest.update(part)
    again = _regular_file(path)
    require(
        (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
        == (again.st_dev, again.st_ino, again.st_size, again.st_mtime_ns),
        "file_changed_during_read",
    )
    return {
        "sha256": digest.hexdigest(),
        "size": info.st_size,
        "mode": stat.S_IMODE(info.st_mode),
        "uid": info.st_uid,
        "gid": info.st_gid,
    }


def _tree(root: Path) -> dict[str, dict[str, int | str]]:
    require(root.is_dir() and not root.is_symlink(), "unsafe_tree_root")
    root_info = root.lstat()
    result: dict[str, dict[str, int | str]] = {
        ".": {
            "type": "dir",
            "mode": stat.S_IMODE(root_info.st_mode),
            "uid": root_info.st_uid,
            "gid": root_info.st_gid,
        }
    }
    for folder, dirs, files in os.walk(root, followlinks=False):
        parent = Path(folder)
        for name in dirs:
            child = parent / name
            require(child.is_dir() and not child.is_symlink(), "unsafe_tree_entry")
            info = child.lstat()
            result[child.relative_to(root).as_posix()] = {
                "type": "dir",
                "mode": stat.S_IMODE(info.st_mode),
                "uid": info.st_uid,
                "gid": info.st_gid,
            }
        for name in files:
            child = parent / name
            relative = child.relative_to(root).as_posix()
            require(relative not in result, "duplicate_tree_entry")
            result[relative] = {"type": "file", **_metadata(child)}
    return dict(sorted(result.items()))


def _tree_hash(root: Path) -> str:
    return sha(canonical(_tree(root)))


def _safe_archive_name(name: str) -> None:
    relative = PurePosixPath(name)
    require(
        bool(name)
        and not relative.is_absolute()
        and ".." not in relative.parts
        and str(relative) == name
        and not any(ord(c) < 32 or ord(c) == 127 for c in name),
        "unsafe_archive_name",
    )


def _safe_object_key(key: str) -> None:
    """Reject keys that cannot be restored from an exact local path."""
    parts = key.split("/")
    require(
        bool(parts)
        and all(
            part not in ("", ".", "..") and SAFE_OBJECT_PART.fullmatch(part) is not None
            for part in parts
        ),
        "minio_object_key_unsafe",
    )


def _archive_tree(source: Path, archive_path: Path) -> tuple[str, dict[str, Any]]:
    """Create and independently read a complete regular-file archive."""
    before = _tree(source)
    fd = os.open(
        archive_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
    )
    with os.fdopen(fd, "wb") as stream:
        with tarfile.open(fileobj=stream, mode="w:gz") as archive:
            for name, meta in before.items():
                _safe_archive_name(name)
                path = source / name
                if meta["type"] == "dir":
                    info = path.lstat()
                    require(
                        path.is_dir() and not path.is_symlink(), "archive_dir_drift"
                    )
                    member = tarfile.TarInfo(name)
                    member.type = tarfile.DIRTYPE
                    member.mode = stat.S_IMODE(info.st_mode)
                    member.uid = info.st_uid
                    member.gid = info.st_gid
                    archive.addfile(member)
                    continue
                info = _regular_file(path)
                require(
                    {"type": "file", **_metadata(path)} == meta, "archive_source_drift"
                )
                member = tarfile.TarInfo(name)
                member.size = info.st_size
                member.mode = stat.S_IMODE(info.st_mode)
                member.uid = info.st_uid
                member.gid = info.st_gid
                with path.open("rb") as item:
                    archive.addfile(member, item)
        stream.flush()
        os.fsync(stream.fileno())
    observed: dict[str, dict[str, int | str]] = {}
    with tarfile.open(archive_path, "r:gz") as archive:
        for member in archive:
            _safe_archive_name(member.name)
            require(member.name not in observed, "archive_duplicate")
            if member.isdir():
                observed[member.name] = {
                    "type": "dir",
                    "mode": member.mode,
                    "uid": member.uid,
                    "gid": member.gid,
                }
                continue
            require(member.isfile(), "archive_entry_type")
            body = archive.extractfile(member)
            require(body is not None, "archive_entry_read")
            assert body is not None
            digest = hashlib.sha256()
            while part := body.read(1024 * 1024):
                digest.update(part)
            observed[member.name] = {
                "type": "file",
                "sha256": digest.hexdigest(),
                "size": member.size,
                "mode": member.mode,
                "uid": member.uid,
                "gid": member.gid,
            }
    require(observed == before == _tree(source), "archive_readback_drift")
    return str(_metadata(archive_path)["sha256"]), before


def _fsync_directories(root: Path) -> None:
    """Persist backup directory entries before a migration intent is written."""
    require(root.is_dir() and not root.is_symlink(), "backup_directory_type")
    paths = [Path(folder) for folder, _, _ in os.walk(root, followlinks=False)]
    for path in reversed(paths):
        fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def _parse_env(path: Path) -> dict[str, str]:
    _regular_file(path, private=True)
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if not line or line.lstrip().startswith("#"):
            continue
        key, sep, value = line.partition("=")
        require(
            sep == "="
            and re.fullmatch(r"[A-Z][A-Z0-9_]*", key) is not None
            and key not in values,
            "environment_syntax",
        )
        values[key] = value.strip().strip('"').strip("'")
    return values


def _json(body: bytes, code: str) -> Any:
    try:
        return json.loads(body)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ReleaseBlocked(code) from exc


def _mounts_sha256(mounts: Any) -> str:
    """Bind every Docker mount field without depending on inspect list order."""
    require(
        isinstance(mounts, list) and all(isinstance(item, dict) for item in mounts),
        "service_mounts_shape",
    )
    return sha(canonical(sorted(mounts, key=canonical)))


@dataclass(frozen=True)
class HostPaths:
    app: Path = APP
    backup_root: Path = BACKUP_ROOT


class RealHostAdapter:
    """Release host operations, armed only after a locked baseline capture.

    The authenticated CLI owns the two locks and one-attempt directory. The
    old ``r16_forward_operator.py apply`` entry remains hard-disabled.
    """

    def __init__(
        self,
        runner: Runner,
        paths: HostPaths,
        attempt_dir: Path,
        manifest: dict[str, Any],
        bundle_dir: Path,
        *,
        require_production_paths: bool = True,
        trusted_recipient_fingerprint: str | None = None,
        trusted_recipient_key_sha256: str | None = None,
    ) -> None:
        if require_production_paths:
            require(os.geteuid() == 0, "root_required")
            require(paths == HostPaths(), "host_paths")
            require(attempt_dir.parent == paths.backup_root, "attempt_root")
        else:
            require(
                paths.app.resolve() != APP
                and paths.backup_root.resolve() != BACKUP_ROOT,
                "test_paths_only",
            )
            # Docker Compose still targets the fixed production project even
            # when its YAML lives under a test path. Never pair that escape
            # hatch with the actual subprocess/Docker runner.
            require(
                not isinstance(runner, SubprocessRunner),
                "test_paths_real_runner_forbidden",
            )
        require(ATTEMPT_NAME.fullmatch(attempt_dir.name) is not None, "attempt_name")
        self.runner = runner
        self.paths = paths
        self.attempt_dir = attempt_dir
        self.manifest = manifest
        self.bundle_dir = bundle_dir
        self._baseline: dict[str, Any] | None = None
        self._service_env: dict[str, dict[str, str]] = {}
        self._volume_paths: dict[str, Path] = {}
        self._minio_preflight_size: tuple[int, int] | None = None
        self._table_identity: dict[str, dict[str, int | str]] = {}
        self._live_table_names: frozenset[str] | None = None
        self._stopped = False
        self._clone_verified = False
        self._candidate_loaded = False
        self._original_recovery_verified = False
        self._production_paths = require_production_paths
        self._mutation_armed = False
        require(
            not require_production_paths
            or (
                trusted_recipient_fingerprint == APPROVED_RECIPIENT_FINGERPRINT
                and trusted_recipient_key_sha256 == APPROVED_RECIPIENT_KEY_SHA256
            ),
            "trusted_recipient_anchor_required",
        )
        self._trusted_recipient_fingerprint = trusted_recipient_fingerprint
        self._trusted_recipient_key_sha256 = trusted_recipient_key_sha256

    def _required_baseline(self) -> dict[str, Any]:
        require(self._baseline is not None, "capture_required")
        assert self._baseline is not None
        return self._baseline

    def _bundle_file(self, relative: str) -> Path:
        """Do not follow bundle symlinks, including parent directories."""
        path = self.bundle_dir / relative
        require(path.is_relative_to(self.bundle_dir), "bundle_path")
        parent = path.parent
        while True:
            info = parent.lstat()
            require(
                stat.S_ISDIR(info.st_mode) and not parent.is_symlink(),
                "bundle_parent_type",
            )
            if parent == self.bundle_dir:
                break
            parent = parent.parent
        _regular_file(path)
        return path

    def _require_mutation_review(self) -> None:
        require(
            self._mutation_armed
            or (
                not self._production_paths
                and not isinstance(self.runner, SubprocessRunner)
            ),
            "real_host_mutation_unarmed",
        )

    def arm_production_mutation(
        self,
        manifest: dict[str, Any],
        baseline: dict[str, Any],
        manifest_sha256: str,
    ) -> None:
        """Bind host writes to a durable single-attempt intent and capture."""
        require(
            self._production_paths
            and isinstance(self.runner, SubprocessRunner)
            and not self._mutation_armed
            and not self._stopped,
            "mutation_arm_order",
        )
        valid_production_manifest(manifest)
        require(
            re.fullmatch(r"[0-9a-f]{64}", manifest_sha256) is not None,
            "mutation_manifest_hash",
        )
        attempt_info = self.attempt_dir.lstat()
        require(
            stat.S_ISDIR(attempt_info.st_mode)
            and not self.attempt_dir.is_symlink()
            and attempt_info.st_uid == 0
            and stat.S_IMODE(attempt_info.st_mode) == 0o700,
            "mutation_attempt_directory",
        )
        intent_path = self.attempt_dir / "intent.json"
        require(intent_path.exists(), "mutation_intent_missing")
        intent_info = _regular_file(intent_path, private=True)
        require(intent_info.st_uid == 0, "mutation_intent_owner")
        intent = _json(intent_path.read_bytes(), "mutation_intent_json")
        require(
            isinstance(intent, dict)
            and intent
            == {
                "version": "r16-default-off-intent-v1",
                "candidate": manifest["image"],
                "revision": manifest["revision"],
                "manifest_sha256": manifest_sha256,
                "baseline_sha256": sha(canonical(baseline)),
                "old_app_restart_forbidden_after_migration_intent": True,
                "simulation_only": False,
            },
            "mutation_intent_identity",
        )
        require(
            manifest == self.manifest
            and self._baseline == baseline
            and baseline.get("recipient_fingerprint") == APPROVED_RECIPIENT_FINGERPRINT
            and self._trusted_recipient_key_sha256 == APPROVED_RECIPIENT_KEY_SHA256,
            "mutation_arm_identity",
        )
        self._mutation_armed = True

    def _run(
        self,
        *argv: str,
        code: str,
        timeout: int = 60,
        input_file: Path | None = None,
        output_file: Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> bytes:
        return self.runner.run(
            tuple(argv),
            code=code,
            timeout=timeout,
            input_file=input_file,
            output_file=output_file,
            env=env,
        )

    def _compose(
        self,
        *args: str,
        code: str,
        timeout: int = 60,
        input_file: Path | None = None,
        output_file: Path | None = None,
        env: Mapping[str, str] | None = None,
    ) -> bytes:
        # Compose shell variables override --env-file. Never allow the
        # operator's ambient APP_IMAGE/feature flags to silently change the
        # candidate or briefly start a live delivery before postchecks run.
        require(env is None, "compose_env_override")
        app = self.paths.app
        return self._run(
            "docker",
            "compose",
            "--project-name",
            PROJECT,
            "-f",
            str(app / "compose.yaml"),
            "--env-file",
            str(app / ".env"),
            "--env-file",
            str(app / ".release.env"),
            *args,
            code=code,
            timeout=timeout,
            input_file=input_file,
            output_file=output_file,
            env=HOST_COMMAND_ENV,
        )

    def _inspect(self, *args: str) -> dict[str, Any]:
        result = _json(
            self._run("docker", "inspect", *args, code="docker_inspect"),
            "docker_inspect_json",
        )
        require(
            isinstance(result, list)
            and len(result) == 1
            and isinstance(result[0], dict),
            "docker_inspect_shape",
        )
        return cast(dict[str, Any], result[0])

    def _image(self, ref: str) -> dict[str, Any]:
        result = _json(
            self._run("docker", "image", "inspect", ref, code="image_inspect"),
            "image_inspect_json",
        )
        require(
            isinstance(result, list)
            and len(result) == 1
            and isinstance(result[0], dict),
            "image_inspect_shape",
        )
        return cast(dict[str, Any], result[0])

    def _service(self, name: str) -> dict[str, Any]:
        require(name in (*SERVICES, "postgres", "minio"), "service_name")
        ids = (
            self._compose("ps", "-a", "-q", name, code="service_lookup")
            .decode()
            .split()
        )
        require(
            len(ids) == 1 and re.fullmatch(r"[0-9a-f]{12,64}", ids[0]) is not None,
            "service_count",
        )
        return self._inspect(ids[0])

    def _runtime_tree(self, container_id: str) -> dict[str, Any]:
        require(
            re.fullmatch(r"[0-9a-f]{64}", container_id) is not None,
            "runtime_container_identity",
        )
        result = _json(
            self._run(
                "docker",
                "exec",
                container_id,
                "python",
                "-c",
                RUNTIME_TREE_SCRIPT,
                code="runtime_tree_readback",
                timeout=180,
            ),
            "runtime_tree_json",
        )
        require(
            isinstance(result, dict)
            and result.get("files") == R15_RUNTIME_FILES
            and result.get("sha256") == R15_RUNTIME_TREE_SHA256,
            "live_runtime_tree_drift",
        )
        return cast(dict[str, Any], result)

    def _sql(self, sql: str) -> str:
        require(
            (sql.startswith("SELECT ") or sql == HISTORICAL_WORK_COHORT_SQL)
            and ";" not in sql,
            "readonly_sql",
        )
        return (
            self._compose(
                "exec",
                "-T",
                "postgres",
                "sh",
                "-c",
                'exec psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "$1"',
                "sh",
                sql,
                code="postgres_readonly",
                timeout=180,
            )
            .decode()
            .strip()
        )

    def _db_identity(
        self, *, bind_if_unbound: bool = False, allow_additive_tables: bool = True
    ) -> str:
        """Measure every row; bind only the first stopped-writer measurement."""
        tables = self._sql(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"
        ).splitlines()
        require("alembic_version" in tables and len(tables) >= 10, "table_inventory")
        identity: dict[str, dict[str, int | str]] = {}
        for table in tables:
            require(re.fullmatch(r"[a-z][a-z0-9_]*", table) is not None, "table_name")
            if table == "alembic_version":
                continue
            count = self._sql(f"SELECT count(*) FROM public.{table}")
            digest = self._sql(
                "SELECT md5(COALESCE(string_agg(md5(to_jsonb(t)::text),'' "
                f"ORDER BY md5(to_jsonb(t)::text)),'')) FROM public.{table} t"
            )
            require(
                count.isdecimal() and re.fullmatch(r"[0-9a-f]{32}", digest) is not None,
                "table_identity",
            )
            identity[table] = {"count": int(count), "rows_md5": digest}
        names = frozenset(identity)
        if self._live_table_names is None:
            self._live_table_names = names
        elif bind_if_unbound or not allow_additive_tables:
            require(names == self._live_table_names, "business_table_inventory_drift")
        if not self._table_identity and bind_if_unbound:
            self._table_identity = identity
        elif self._table_identity:
            require(
                {name: identity.get(name) for name in self._table_identity}
                == self._table_identity,
                "business_identity_drift",
            )
        # New additive tables appear after 0048 -> 0050. Preserve the bound
        # original-table digest while still comparing every original table.
        return sha(canonical(self._table_identity or identity))

    def _work_counts(self) -> tuple[int, int]:
        """Refuse new work; allow only the exact reviewed, inert 0048 cohort."""
        tables = self._sql(
            "SELECT tablename FROM pg_tables WHERE schemaname='public' AND "
            "(tablename LIKE '%_jobs' OR tablename LIKE '%_runs') ORDER BY tablename"
        ).splitlines()
        require("wecom_delivery_jobs" in tables, "work_table_inventory")
        unknown_total = 0
        pending_total = 0
        for table in tables:
            require(
                re.fullmatch(r"[a-z][a-z0-9_]*", table) is not None, "work_table_name"
            )
            unknown = self._sql(
                "SELECT count(*) FROM public."
                + table
                + " t WHERE to_jsonb(t)->>'status' IN "
                "('delivery_unknown','result_unknown','outcome_unknown') "
                "AND (to_jsonb(t)->>'expires_at' IS NULL OR "
                "(to_jsonb(t)->>'expires_at')::timestamptz > now())"
            )
            pending = self._sql(
                "SELECT count(*) FROM public."
                + table
                + " t WHERE to_jsonb(t)->>'status' IN "
                "('queued','pending','running','delivering','retryable_failed',"
                "'retry_scheduled','admitted','generating','preparing') "
                "OR to_jsonb(t)->>'lease_token' IS NOT NULL"
            )
            require(unknown.isdecimal() and pending.isdecimal(), "work_count")
            unknown_total += int(unknown)
            pending_total += int(pending)
        if unknown_total == pending_total == 0:
            return 0, 0
        require(
            (unknown_total, pending_total) == (5, 14),
            "unreviewed_pending_or_unknown_work",
        )
        cohort = self._sql(HISTORICAL_WORK_COHORT_SQL)
        require(
            sha(cohort.encode()) == HISTORICAL_WORK_COHORT_SHA256,
            "historical_work_cohort_drift",
        )
        return 0, 0

    def _common_identity(
        self,
    ) -> tuple[dict[str, dict[str, int | str]], str, dict[str, str]]:
        app = self.paths.app
        protected = {name: _metadata(app / name) for name in PROTECTED_FILES}
        brand = _tree_hash(app / "private/brand-materials")
        volumes: dict[str, str] = {}
        for name in VOLUMES:
            result = _json(
                self._run("docker", "volume", "inspect", name, code="volume_inspect"),
                "volume_inspect_json",
            )
            require(
                isinstance(result, list)
                and len(result) == 1
                and result[0].get("Name") == name,
                "volume_identity",
            )
            path = Path(result[0]["Mountpoint"])
            require(path.is_absolute() and not path.is_symlink(), "volume_mountpoint")
            self._volume_paths[name] = path
            # MinIO's live .minio.sys is service control state, not a stable
            # application-object identity. It must never be raw-archived while
            # MinIO remains online.
            if name == MINIO_VOLUME:
                snapshot = self._minio_snapshot()
                entries = snapshot["objects"]
                self._minio_preflight_size = (
                    len(entries),
                    sum(item["size"] for item in entries.values()),
                )
                volumes[name] = sha(canonical(snapshot))
            else:
                volumes[name] = _tree_hash(path)
        return protected, brand, volumes

    def _mc(
        self,
        *args: str,
        code: str,
        timeout: int = 180,
        output_file: Path | None = None,
        backup_mount: Path | None = None,
    ) -> bytes:
        """Run the pinned client with credentials in process environment only."""
        settings = _parse_env(self.paths.app / ".env")
        user = settings.get("MINIO_ROOT_USER", "")
        password = settings.get("MINIO_ROOT_PASSWORD", "")
        bucket = settings.get("MINIO_BUCKET", "")
        require(
            bool(user)
            and bool(password)
            and SAFE_BUCKET.fullmatch(bucket) is not None
            and all(
                "\n" not in value and "\r" not in value for value in (user, password)
            ),
            "minio_configuration",
        )
        require(
            self._image(MINIO_MC_IMAGE).get("Id") == MINIO_MC_IMAGE_ID,
            "minio_client_image_unpinned",
        )
        command = [
            "docker",
            "run",
            "--rm",
            "--pull",
            "never",
            "--network",
            self._production_network(),
            "--user",
            "0:0",
            "--entrypoint",
            "/usr/bin/mc",
            "--env",
            "MC_HOST_r16",
        ]
        if backup_mount is not None:
            require(
                backup_mount.is_dir()
                and not backup_mount.is_symlink()
                and backup_mount.is_relative_to(self.attempt_dir),
                "minio_backup_mount",
            )
            command.extend(("-v", str(backup_mount) + ":/backup"))
        command.extend((MINIO_MC_IMAGE_ID, *args))
        # Docker's --env NAME forwards the value from the client environment;
        # neither argv nor release logs contain the secret URL.
        env = {
            **HOST_COMMAND_ENV,
            "MC_HOST_r16": "http://"
            + quote(user, safe="")
            + ":"
            + quote(password, safe="")
            + "@minio:9000",
        }
        return self._run(
            *command, code=code, timeout=timeout, output_file=output_file, env=env
        )

    def _minio_bucket(self) -> str:
        bucket = _parse_env(self.paths.app / ".env").get("MINIO_BUCKET", "")
        require(SAFE_BUCKET.fullmatch(bucket) is not None, "minio_bucket")
        return bucket

    def _require_minio_capacity(self, object_count: int, object_bytes: int) -> None:
        """Reserve both local copies at the current free-space watermark."""
        if not self._production_paths:
            return
        free = os.statvfs(self.paths.backup_root)
        require(
            free.f_bavail * free.f_frsize
            >= max(MIN_RELEASE_FREE_BYTES, 2 * object_bytes + 4 * 1024**3)
            and free.f_favail
            >= max(MIN_RELEASE_FREE_INODES, 2 * object_count + 10_000),
            "minio_logical_backup_capacity",
        )

    def _mc_json_lines(self, *args: str, code: str) -> list[dict[str, Any]]:
        """Stream a bounded inventory to a private file, never into logs/stdout."""
        # Sealed preflight intentionally has no attempt directory yet. Its
        # temporary inventory lives under the existing private backup root
        # and is unlinked before preflight returns.
        directory = (
            self.attempt_dir if self.attempt_dir.is_dir() else self.paths.backup_root
        )
        info = directory.lstat()
        require(
            stat.S_ISDIR(info.st_mode)
            and not directory.is_symlink()
            and stat.S_IMODE(info.st_mode) == 0o700
            and info.st_uid == os.geteuid(),
            "minio_inventory_directory",
        )
        path = directory / (".minio-inventory-" + secrets.token_hex(12))
        try:
            self._mc(
                *args, code=code, timeout=MINIO_INVENTORY_TIMEOUT, output_file=path
            )
            info = _regular_file(path, private=True)
            require(
                info.st_size <= MAX_MINIO_INVENTORY_BYTES, "minio_inventory_too_large"
            )
            result: list[dict[str, Any]] = []
            with path.open("rb") as stream:
                for line in stream:
                    require(len(line) <= 64 * 1024, "minio_inventory_line_too_large")
                    item = _json(line, "minio_inventory_json")
                    require(isinstance(item, dict), "minio_inventory_shape")
                    result.append(item)
            return result
        finally:
            if path.exists():
                path.unlink()

    def _minio_snapshot(self) -> dict[str, Any]:
        """Exact current-object inventory; unsupported S3 features fail closed."""
        bucket = self._minio_bucket()
        target = "r16/" + bucket
        version = _json(
            self._mc("version", "info", "--json", target, code="minio_version_info"),
            "minio_version_json",
        )
        require(
            isinstance(version, dict)
            and version.get("status") == "success"
            and isinstance(version.get("versioning"), dict)
            and version["versioning"].get("status") == ""
            and version["versioning"].get("MFADelete") == "",
            "minio_versioning_unsupported",
        )
        listing = self._mc_json_lines(
            "stat", "--recursive", "--json", target + "/", code="minio_stat_recursive"
        )
        objects: dict[str, dict[str, Any]] = {}
        total_bytes = 0
        for item in listing:
            require(
                item.get("status") == "success"
                and item.get("type") == "file"
                and isinstance(item.get("name"), str)
                and type(item.get("size")) is int
                and item["size"] >= 0
                and isinstance(item.get("etag"), str)
                and bool(item["etag"])
                and isinstance(item.get("lastModified"), str)
                and isinstance(item.get("metadata"), dict)
                and all(
                    isinstance(meta_key, str) and isinstance(meta_value, str)
                    for meta_key, meta_value in item["metadata"].items()
                )
                and any(
                    meta_key.lower() == "content-type" and bool(meta_value)
                    for meta_key, meta_value in item["metadata"].items()
                )
                and all(
                    meta_key.lower() == "content-type"
                    or meta_key.lower().startswith("x-amz-meta-")
                    for meta_key in item["metadata"]
                )
                and not any(
                    field in item
                    for field in ("versionID", "retention", "legalHold", "tags")
                )
                and not any(
                    forbidden in meta_key.lower()
                    for meta_key in item["metadata"]
                    for forbidden in (
                        "object-lock",
                        "retention",
                        "legal-hold",
                        "server-side-encryption",
                    )
                ),
                "minio_stat_shape_or_metadata",
            )
            key = item["name"]
            _safe_object_key(key)
            require(key not in objects, "minio_duplicate_object")
            objects[key] = {
                "size": item["size"],
                "etag": item["etag"],
                "last_modified": item["lastModified"],
                "metadata": item["metadata"],
            }
            total_bytes += item["size"]
            require(
                len(objects) <= MAX_MINIO_OBJECTS
                and total_bytes <= MAX_MINIO_SOURCE_BYTES,
                "minio_preflight_size_limit",
            )
        # A flat file and a child prefix cannot both map to the local mirror.
        for key in objects:
            parts = key.split("/")
            require(
                all(
                    "/".join(parts[:index]) not in objects
                    for index in range(1, len(parts))
                ),
                "minio_key_path_collision",
            )
        tags_listing = self._mc_json_lines(
            "tag",
            "list",
            "--recursive",
            "--json",
            target + "/",
            code="minio_tags_recursive",
        )
        seen_tags: set[str] = set()
        for tags in tags_listing:
            url = tags.get("url")
            require(
                tags.get("status") == "success"
                and isinstance(url, str)
                and urlsplit(url).path.startswith("/" + bucket + "/")
                and tags.get("versionID") in (None, "")
                and tags.get("tags") in (None, {}, []),
                "minio_tags_unsupported",
            )
            assert isinstance(url, str)
            key = urlsplit(url).path[len(bucket) + 2 :]
            _safe_object_key(key)
            require(key in objects and key not in seen_tags, "minio_tags_inventory")
            seen_tags.add(key)
        require(seen_tags == set(objects), "minio_tags_inventory")
        return {
            "version": "r16-minio-current-objects-v1",
            "bucket": bucket,
            "objects": dict(sorted(objects.items())),
        }

    def _backup_minio_objects(self, expected_identity: str) -> dict[str, Any]:
        before = self._minio_snapshot()
        require(sha(canonical(before)) == expected_identity, "minio_prebackup_drift")
        self._require_minio_capacity(
            len(before["objects"]),
            sum(item["size"] for item in before["objects"].values()),
        )
        bucket = before["bucket"]
        target_dir = self.attempt_dir / "minio-objects"
        target_dir.mkdir(mode=0o700)
        self._mc(
            "mirror",
            "--preserve",
            "--quiet",
            "r16/" + bucket,
            "/backup",
            code="minio_mirror",
            timeout=MINIO_MIRROR_TIMEOUT,
            backup_mount=target_dir,
        )
        local = _tree(target_dir)
        keys = set(before["objects"])
        require(
            {name for name, meta in local.items() if meta["type"] == "file"} == keys,
            "minio_mirror_inventory",
        )
        # A fresh second mirror performs an independent remote GET of every
        # current object; it is retained as readback evidence, not an archive
        # of MinIO's live internal files.
        readback_dir = self.attempt_dir / "minio-objects-readback"
        readback_dir.mkdir(mode=0o700)
        self._mc(
            "mirror",
            "--preserve",
            "--quiet",
            "r16/" + bucket,
            "/backup",
            code="minio_mirror_readback",
            timeout=MINIO_MIRROR_TIMEOUT,
            backup_mount=readback_dir,
        )
        readback_tree = _tree(readback_dir)
        require(
            {name for name, meta in readback_tree.items() if meta["type"] == "file"}
            == keys,
            "minio_readback_inventory",
        )
        manifest_objects: dict[str, dict[str, Any]] = {}
        total_bytes = 0
        for key, item in before["objects"].items():
            copied = _metadata(target_dir / key)
            require(copied["size"] == item["size"], "minio_mirror_size")
            source = _metadata(readback_dir / key)
            require(
                source["sha256"] == copied["sha256"]
                and source["size"] == copied["size"],
                "minio_object_byte_drift",
            )
            manifest_objects[key] = {
                "sha256": copied["sha256"],
                "size": copied["size"],
                "metadata": item["metadata"],
            }
            total_bytes += int(copied["size"])
        require(self._minio_snapshot() == before, "minio_postbackup_drift")
        manifest = {
            "version": "r16-minio-logical-backup-v1",
            "bucket": bucket,
            "inventory_sha256": expected_identity,
            "objects": manifest_objects,
        }
        manifest_path = self.attempt_dir / "minio-objects-manifest.json"
        self._write_private(manifest_path, canonical(manifest))
        require(
            _json(manifest_path.read_bytes(), "minio_manifest_json") == manifest,
            "minio_manifest_readback",
        )
        _fsync_directories(target_dir)
        _fsync_directories(readback_dir)
        return {
            "kind": "unversioned-current-object-logical-v1",
            "bucket": bucket,
            "inventory_sha256": expected_identity,
            "manifest_sha256": _metadata(manifest_path)["sha256"],
            "object_count": len(keys),
            "bytes": total_bytes,
            "readback_tree_sha256": sha(
                canonical({key: readback_tree[key]["sha256"] for key in sorted(keys)})
            ),
            "source_bytes_readback": True,
            "local_bytes_readback": True,
            "metadata_readback": True,
        }

    def capture(self) -> dict[str, Any]:
        app = self.paths.app
        host_files = self.manifest.get("host_files")
        require(
            isinstance(host_files, dict) and set(host_files) == set(REPLACED_FILES),
            "candidate_host_files",
        )
        assert isinstance(host_files, dict)
        require(
            _metadata(self._bundle_file("backend-image.oci.tar.gz"))["sha256"]
            == self.manifest.get("archive_sha256"),
            "candidate_archive_sha256",
        )
        for name in REPLACED_FILES:
            require(
                _metadata(self._bundle_file("host-files/" + name))["sha256"]
                == host_files[name],
                "host_file_sha256",
            )
        self._run(
            "docker",
            "compose",
            "--project-name",
            PROJECT,
            "-f",
            str(self._bundle_file("host-files/compose.yaml")),
            "--env-file",
            str(app / ".env"),
            "--env-file",
            str(app / ".release.env"),
            "config",
            "--quiet",
            code="candidate_compose_config",
            env=HOST_COMMAND_ENV,
        )
        compose_help = self._run(
            "docker", "compose", "up", "--help", code="compose_up_capabilities"
        ).decode()
        require(
            all(
                option in compose_help
                for option in (
                    "--no-build",
                    "--no-deps",
                    "--pull",
                    "--wait",
                    "--wait-timeout",
                )
            ),
            "compose_up_capabilities",
        )
        if self._production_paths:
            for directory in (self.paths.backup_root, Path("/var/lib/docker")):
                info = directory.lstat()
                require(
                    stat.S_ISDIR(info.st_mode) and not directory.is_symlink(),
                    "release_storage_directory",
                )
                free = os.statvfs(directory)
                require(
                    free.f_bavail * free.f_frsize >= MIN_RELEASE_FREE_BYTES
                    and free.f_favail >= MIN_RELEASE_FREE_INODES,
                    "release_storage_capacity",
                )
            backup_info = self.paths.backup_root.stat()
            require(
                backup_info.st_uid == 0
                and backup_info.st_gid == 0
                and stat.S_IMODE(backup_info.st_mode) == 0o700,
                "backup_root_permissions",
            )
        require(
            (app / ".release-commit").read_text().strip() == BASE_REVISION,
            "base_revision",
        )
        require(
            (app / "RELEASE_COMMIT").read_text().strip() == BASE_REVISION,
            "base_revision_secondary",
        )
        env = _parse_env(app / ".env")
        release = _parse_env(app / ".release.env")
        require(release.get("APP_IMAGE") == BASE_REF, "release_image_ref")
        require(
            env.get("WECOM_DELIVERY_PROVIDER") == "group_webhook"
            and bool(env.get("WECOM_GROUP_WEBHOOK_KEY")),
            "recipient_not_configured",
        )
        flags = {key: env.get(key, "false").lower() == "true" for key in OFF_FLAGS}
        require(
            all(
                env.get(key, "false").lower() in ("true", "false") for key in OFF_FLAGS
            ),
            "flag_syntax",
        )
        image = self._image(BASE_REF)
        require(
            image.get("Id") == BASE_IMAGE
            and image.get("Config", {})
            .get("Labels", {})
            .get("org.opencontainers.image.revision")
            == BASE_REVISION,
            "base_image_identity",
        )
        services: dict[str, Any] = {}
        dependencies: dict[str, str] = {}
        for name in SERVICES:
            item = self._service(name)
            state = item.get("State", {})
            config = item.get("Config", {})
            require(
                state.get("Status") == "running"
                and state.get("Health", {}).get("Status", "healthy") == "healthy",
                "service_unhealthy",
            )
            container_id = item.get("Id")
            require(
                isinstance(container_id, str)
                and re.fullmatch(r"[0-9a-f]{64}", container_id) is not None,
                "service_container_id",
            )
            assert isinstance(container_id, str)
            actual_env = dict(
                value.split("=", 1) for value in config.get("Env", []) if "=" in value
            )
            self._service_env[name] = actual_env
            self._runtime_tree(container_id)
            require(
                all(
                    actual_env.get(flag, "false").lower() == "false"
                    for flag in OFF_FLAGS
                ),
                "running_infographic_flag_enabled",
            )
            services[name] = {
                "image": item.get("Image"),
                "image_ref": config.get("Image"),
                "running": True,
                "healthy": True,
                "restarts": item.get("RestartCount"),
                "command_sha256": sha(canonical(config.get("Cmd"))),
                "mounts_sha256": _mounts_sha256(item.get("Mounts")),
                "env_sha256": sha(canonical(actual_env)),
                "container_id": container_id,
            }
        for name in ("postgres", "minio"):
            item = self._service(name)
            state = item.get("State", {})
            require(
                state.get("Status") == "running"
                and state.get("Health", {}).get("Status", "healthy") == "healthy"
                and item.get("RestartCount") == 0,
                "dependency_health",
            )
            container_id = item.get("Id")
            require(
                isinstance(container_id, str)
                and re.fullmatch(r"[0-9a-f]{64}", container_id) is not None
                and item.get("Config", {}).get("Image") == DEPENDENCY_REFS[name]
                and any(
                    mount.get("Type") == "volume"
                    and mount.get("Name") == DEPENDENCY_VOLUMES[name]
                    for mount in item.get("Mounts", [])
                ),
                "dependency_identity",
            )
            assert isinstance(container_id, str)
            dependencies[name] = container_id
        # There must not be an already-created optional producer, even exited.
        optional = self._run(
            "docker",
            "ps",
            "-a",
            "-q",
            "--filter",
            f"label=com.docker.compose.project={PROJECT}",
            "--filter",
            "label=com.docker.compose.service=wecom-infographic-producer",
            code="optional_producer_lookup",
        )
        # These values are used by the post-backup Alembic-only command.
        # Reject malformed URLs/networks before stopping a single writer.
        self._production_db_url()
        self._production_network()
        protected, brand, volumes = self._common_identity()
        if self._production_paths:
            require(self._minio_preflight_size is not None, "minio_preflight_size")
            assert self._minio_preflight_size is not None
            object_count, object_bytes = self._minio_preflight_size
            self._require_minio_capacity(object_count, object_bytes)
        dispatcher_env = self._service_env["wecom-dispatcher"]
        require(
            dispatcher_env.get("WECOM_DELIVERY_PROVIDER") == "group_webhook"
            and dispatcher_env.get("WECOM_GROUP_WEBHOOK_KEY")
            == env["WECOM_GROUP_WEBHOOK_KEY"],
            "live_recipient_config_drift",
        )
        recipient_fingerprint = sha(
            ("group_webhook\0" + env["WECOM_GROUP_WEBHOOK_KEY"]).encode()
        )
        if self._trusted_recipient_fingerprint is not None:
            require(
                recipient_fingerprint == self._trusted_recipient_fingerprint,
                "trusted_recipient_mismatch",
            )
        if self._trusted_recipient_key_sha256 is not None:
            require(
                sha(env["WECOM_GROUP_WEBHOOK_KEY"].encode())
                == self._trusted_recipient_key_sha256,
                "trusted_recipient_key_mismatch",
            )
        unknown, pending = self._work_counts()
        result = {
            "release_commit": BASE_REVISION,
            "release_commit_secondary": BASE_REVISION,
            "image": image["Id"],
            "release_env_image": release["APP_IMAGE"],
            "schema": self._sql("SELECT version_num FROM alembic_version"),
            "optional_producer_absent": not optional.strip(),
            "standard_manifest_absent": not (app / ".release-manifest.json").exists(),
            "backup_timer_active": self._run(
                "systemctl", "is-active", "edu-ai-backup.timer", code="backup_timer"
            ).strip()
            == b"active",
            "idle": unknown == pending == 0,
            "unknown_work_count": unknown,
            "pending_work_count": pending,
            "business_identity_sha256": self._db_identity(),
            "brand_identity_sha256": brand,
            "recipient_fingerprint": recipient_fingerprint,
            "flags": flags,
            "services": services,
            "protected_files": {
                name: {key: value for key, value in meta.items() if key != "size"}
                for name, meta in protected.items()
            },
            "volumes": volumes,
            "dependencies": dependencies,
        }
        valid_baseline(result)
        self._baseline = json.loads(canonical(result))
        return cast(dict[str, Any], json.loads(canonical(result)))

    def stop_writers(self) -> None:
        self._require_mutation_review()
        require(self._baseline is not None, "capture_required")
        self._compose("stop", *SERVICES, code="stop_writers", timeout=180)
        self._stopped = True

    def verify_writers_stopped(self) -> bool:
        if not self._stopped:
            return False
        return all(
            self._service(name).get("State", {}).get("Status") == "exited"
            for name in SERVICES
        )

    def capture_quiescent(self) -> dict[str, Any]:
        require(
            self._baseline is not None and self.verify_writers_stopped(),
            "writers_not_stopped",
        )
        baseline = self._required_baseline()
        for name in SERVICES:
            require(
                self._service(name).get("Id")
                == baseline["services"][name]["container_id"],
                "writer_recreated_during_stop",
            )
        for name, container_id in baseline["dependencies"].items():
            require(
                self._service(name).get("Id") == container_id, "dependency_recreated"
            )
        protected, brand, volumes = self._common_identity()
        unknown, pending = self._work_counts()
        require(unknown == pending == 0, "quiescent_work")
        return {
            "schema": self._sql("SELECT version_num FROM alembic_version"),
            "business_identity_sha256": self._db_identity(bind_if_unbound=True),
            "brand_identity_sha256": brand,
            "recipient_fingerprint": baseline["recipient_fingerprint"],
            "protected_files": {
                name: {key: value for key, value in meta.items() if key != "size"}
                for name, meta in protected.items()
            },
            "volumes": volumes,
            "flags": baseline["flags"],
            "stopped_services": list(SERVICES),
            "optional_producer_absent": True,
        }

    def adopt_quiescent_baseline(
        self, live_baseline: dict[str, Any], snapshot: dict[str, Any]
    ) -> None:
        """Switch backup/clone checks to the stopped-writer business identity."""
        require(
            self._mutation_armed
            and self.verify_writers_stopped()
            and self._baseline == live_baseline
            and bool(self._table_identity),
            "quiescent_adoption_order",
        )
        authoritative = quiescent_baseline(live_baseline, snapshot)
        require(
            snapshot["business_identity_sha256"]
            == sha(canonical(self._table_identity)),
            "quiescent_table_identity",
        )
        self._baseline = authoritative

    def backup(self) -> dict[str, Any]:
        self._require_mutation_review()
        baseline = self._required_baseline()
        require(
            self._baseline is not None and self.verify_writers_stopped(),
            "backup_requires_stopped_writers",
        )
        attempt_info = self.attempt_dir.lstat()
        require(
            stat.S_ISDIR(attempt_info.st_mode)
            and not self.attempt_dir.is_symlink()
            and stat.S_IMODE(attempt_info.st_mode) == 0o700
            and attempt_info.st_uid == os.geteuid(),
            "attempt_dir_mode",
        )
        dump = self.attempt_dir / "postgres.dump"
        self._compose(
            "exec",
            "-T",
            "postgres",
            "sh",
            "-c",
            'exec pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc',
            code="postgres_dump",
            timeout=900,
            output_file=dump,
        )
        with dump.open("rb") as stream:
            magic = stream.read(5)
        require(
            dump.stat().st_size > 1024 and magic == b"PGDMP", "postgres_dump_format"
        )
        toc = self._compose(
            "exec",
            "-T",
            "postgres",
            "pg_restore",
            "--list",
            code="pg_restore_toc",
            timeout=180,
            input_file=dump,
        )
        require(b"TABLE DATA" in toc and b"alembic_version" in toc, "pg_restore_toc")
        protected_dir = self.attempt_dir / "protected"
        protected_dir.mkdir(mode=0o700)
        protected_metadata: dict[str, dict[str, int | str]] = {}
        for name in PROTECTED_FILES:
            target = protected_dir / name
            target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            source = self.paths.app / name
            before = _metadata(source)
            fd = os.open(
                target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
            )
            with os.fdopen(fd, "wb") as output, source.open("rb") as item:
                while part := item.read(1024 * 1024):
                    output.write(part)
                output.flush()
                os.fsync(output.fileno())
            require(
                _metadata(source) == before
                and _metadata(target)["sha256"] == before["sha256"],
                "protected_readback",
            )
            protected_metadata[name] = before
        metadata_path = self.attempt_dir / "protected-metadata.json"
        self._write_private(metadata_path, canonical(protected_metadata))
        require(
            _json(metadata_path.read_bytes(), "protected_metadata_readback")
            == protected_metadata,
            "protected_metadata_readback",
        )
        minio_receipt = self._backup_minio_objects(baseline["volumes"][MINIO_VOLUME])
        volume_archives: dict[str, str] = {}
        for name in ARCHIVE_VOLUMES:
            digest, _ = _archive_tree(
                self._volume_paths[name], self.attempt_dir / (name + ".tar.gz")
            )
            volume_archives[name] = digest
        brand_digest, _ = _archive_tree(
            self.paths.app / "private/brand-materials",
            self.attempt_dir / "brand-materials.tar.gz",
        )
        source_root = self.attempt_dir / "source-config"
        source_root.mkdir(mode=0o700)
        source_digests: dict[str, str] = {}
        for name in SOURCE_DIRS:
            source_digests[name], _ = _archive_tree(
                self.paths.app / name, source_root / (name + ".tar.gz")
            )
        _fsync_directories(protected_dir)
        _fsync_directories(source_root)
        _fsync_directories(self.attempt_dir)
        return {
            "baseline_sha256": sha(canonical(baseline)),
            "pg_dump_sha256": _metadata(dump)["sha256"],
            "pg_dump_bytes": dump.stat().st_size,
            "pg_restore_toc_sha256": sha(toc),
            "pg_restore_toc_read": True,
            "protected_files_readback": True,
            "protected_files": baseline["protected_files"],
            "protected_metadata_sha256": _metadata(metadata_path)["sha256"],
            "brand_materials_readback": True,
            "brand_identity_sha256": baseline["brand_identity_sha256"],
            "brand_archive_sha256": brand_digest,
            "source_config_readback": len(source_digests) == len(SOURCE_DIRS),
            "source_config_archives": source_digests,
            "minio": minio_receipt,
            "volumes": volume_archives,
            "volume_readbacks": dict.fromkeys(ARCHIVE_VOLUMES, True),
        }

    def verify_backup_materials(self, backup: dict[str, Any]) -> None:
        """Rehash both retained MinIO copies immediately before migration intent.

        The receipt records the backup-time result; it cannot itself prove that
        the private on-disk recovery material still exists after clone work.
        """
        self._require_mutation_review()
        baseline = self._required_baseline()
        require(
            self._stopped
            and self.verify_writers_stopped()
            and not (self.attempt_dir / "migration-intent.json").exists(),
            "minio_materials_verification_order",
        )
        valid_backup(backup, baseline)
        minio = backup["minio"]
        manifest_path = self.attempt_dir / "minio-objects-manifest.json"
        info = _regular_file(manifest_path, private=True)
        require(info.st_uid == os.geteuid(), "minio_manifest_owner")
        body = manifest_path.read_bytes()
        require(sha(body) == minio["manifest_sha256"], "minio_manifest_drift")
        manifest = _json(body, "minio_manifest_json")
        require(
            isinstance(manifest, dict)
            and canonical(manifest) == body
            and set(manifest) == {"version", "bucket", "inventory_sha256", "objects"}
            and manifest["version"] == "r16-minio-logical-backup-v1"
            and manifest["bucket"] == minio["bucket"]
            and manifest["inventory_sha256"] == minio["inventory_sha256"]
            and isinstance(manifest["objects"], dict),
            "minio_manifest_contract",
        )
        objects = manifest["objects"]
        require(len(objects) == minio["object_count"], "minio_manifest_count")
        expected_bytes = 0
        for key, item in objects.items():
            require(isinstance(key, str), "minio_manifest_key")
            _safe_object_key(key)
            require(
                isinstance(item, dict)
                and set(item) == {"sha256", "size", "metadata"}
                and is_sha(item["sha256"])
                and type(item["size"]) is int
                and item["size"] >= 0
                and isinstance(item["metadata"], dict),
                "minio_manifest_object",
            )
            expected_bytes += item["size"]
        require(expected_bytes == minio["bytes"], "minio_manifest_bytes")
        first = _tree(self.attempt_dir / "minio-objects")
        second = _tree(self.attempt_dir / "minio-objects-readback")
        keys = set(objects)
        require(
            {key for key, item in first.items() if item["type"] == "file"} == keys
            and {key for key, item in second.items() if item["type"] == "file"} == keys,
            "minio_materials_inventory_drift",
        )
        for key, item in objects.items():
            require(
                all(
                    tree[key]["sha256"] == item["sha256"]
                    and tree[key]["size"] == item["size"]
                    for tree in (first, second)
                ),
                "minio_materials_byte_drift",
            )
        require(
            sha(canonical({key: second[key]["sha256"] for key in sorted(keys)}))
            == minio["readback_tree_sha256"],
            "minio_materials_readback_drift",
        )

    def stage_candidate_image(self, manifest: dict[str, Any]) -> str:
        self._require_mutation_review()
        require(manifest == self.manifest and self._stopped, "candidate_stage_order")
        archive = self._bundle_file("backend-image.oci.tar.gz")
        require(
            _metadata(archive)["sha256"] == manifest["archive_sha256"],
            "candidate_archive_sha256",
        )
        self._run(
            "docker",
            "load",
            "-i",
            str(archive),
            code="candidate_load",
            timeout=600,
        )
        ref = self._candidate_ref()
        image = self._image(ref)
        require(
            image.get("Id") == manifest["image"]
            and ref in image.get("RepoDigests", [])
            and image.get("Config", {})
            .get("Labels", {})
            .get("org.opencontainers.image.revision")
            == manifest["revision"],
            "candidate_loaded_identity",
        )
        self._candidate_loaded = True
        return cast(str, manifest["image"])

    def _candidate_ref(self) -> str:
        return "offline.local/edu-ai/edu-ai-lead-agent-backend@" + cast(
            str, self.manifest["image"]
        )

    def _clone_sql(self, container: str, sql: str) -> str:
        require(sql.startswith("SELECT ") and ";" not in sql, "clone_readonly_sql")
        return (
            self._run(
                "docker",
                "exec",
                container,
                "psql",
                "-X",
                "-v",
                "ON_ERROR_STOP=1",
                "-U",
                PG_CLONE_USER,
                "-d",
                PG_CLONE_DB,
                "-Atc",
                sql,
                code="clone_sql",
                timeout=180,
            )
            .decode()
            .strip()
        )

    def _clone_table_identity(self, container: str) -> dict[str, dict[str, int | str]]:
        tables = self._clone_sql(
            container,
            "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename",
        ).splitlines()
        require("alembic_version" in tables, "clone_table_inventory")
        identity: dict[str, dict[str, int | str]] = {}
        for table in self._table_identity:
            require(
                table in tables and SAFE_NAME.fullmatch(table) is not None,
                "clone_table_missing",
            )
            count = self._clone_sql(container, f"SELECT count(*) FROM public.{table}")
            digest = self._clone_sql(
                container,
                "SELECT md5(COALESCE(string_agg(md5(to_jsonb(t)::text),'' "
                f"ORDER BY md5(to_jsonb(t)::text)),'')) FROM public.{table} t",
            )
            require(
                count.isdecimal() and re.fullmatch(r"[0-9a-f]{32}", digest) is not None,
                "clone_table_identity",
            )
            identity[table] = {"count": int(count), "rows_md5": digest}
        return identity

    def _write_private(self, path: Path, body: bytes) -> None:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())

    def rehearse_clone(self, dump_sha256: str) -> dict[str, Any]:
        self._require_mutation_review()
        require(
            self._stopped and self._candidate_loaded and self._baseline is not None,
            "clone_order",
        )
        baseline = self._required_baseline()
        dump = self.attempt_dir / "postgres.dump"
        require(_metadata(dump)["sha256"] == dump_sha256, "clone_dump_bytes")
        suffix = self.attempt_dir.name.removeprefix("r16-forward-")
        require(
            SAFE_NAME.fullmatch(suffix) is not None and len(suffix) <= 32, "clone_name"
        )
        network = "r16-net-" + suffix
        volume = "r16-pg-" + suffix
        container = "r16-clone-" + suffix
        password = secrets.token_urlsafe(24)
        clone_env = self.attempt_dir / "clone-postgres.env"
        self._write_private(
            clone_env,
            (
                f"POSTGRES_USER={PG_CLONE_USER}\n"
                f"POSTGRES_PASSWORD={password}\n"
                f"POSTGRES_DB={PG_CLONE_DB}\n"
            ).encode(),
        )
        url = (
            f"postgresql+asyncpg://{PG_CLONE_USER}:{quote(password, safe='')}"
            f"@postgres:5432/{PG_CLONE_DB}"
        )
        app_env = self.attempt_dir / "clone-app.env"
        self._write_private(app_env, f"DATABASE_URL={url}\n".encode())
        postgres = self._service("postgres")
        postgres_ref = postgres.get("Config", {}).get("Image")
        require(
            isinstance(postgres_ref, str)
            and postgres_ref.startswith("pgvector/pgvector:"),
            "clone_postgres_image",
        )
        self._run(
            "docker", "network", "create", "--internal", network, code="clone_network"
        )
        self._run("docker", "volume", "create", volume, code="clone_volume")
        self._run(
            "docker",
            "run",
            "-d",
            "--pull",
            "never",
            "--name",
            container,
            "--network",
            network,
            "--network-alias",
            "postgres",
            "--env-file",
            str(clone_env),
            "--mount",
            f"type=volume,src={volume},dst=/var/lib/postgresql/data",
            postgres_ref,
            code="clone_start",
            timeout=120,
        )
        for _ in range(60):
            try:
                self._run(
                    "docker",
                    "exec",
                    container,
                    "pg_isready",
                    "-U",
                    PG_CLONE_USER,
                    "-d",
                    PG_CLONE_DB,
                    code="clone_ready",
                    timeout=5,
                )
                break
            except ReleaseBlocked:
                time.sleep(1)
        else:
            raise ReleaseBlocked("clone_ready_timeout")
        self._run(
            "docker",
            "exec",
            "-i",
            container,
            "pg_restore",
            "--exit-on-error",
            "--no-owner",
            "--no-acl",
            "-U",
            PG_CLONE_USER,
            "-d",
            PG_CLONE_DB,
            code="clone_restore",
            timeout=900,
            input_file=dump,
        )
        require(
            self._clone_sql(container, "SELECT version_num FROM alembic_version")
            == BASE_SCHEMA,
            "clone_source_schema",
        )
        require(
            self._clone_table_identity(container) == self._table_identity,
            "clone_restore_business",
        )
        self._run(
            "docker",
            "run",
            "--rm",
            "--pull",
            "never",
            "--network",
            network,
            "--env-file",
            str(app_env),
            "--entrypoint",
            "python",
            self._candidate_ref(),
            *ALEMBIC_ONLY_COMMAND[1:],
            code="clone_alembic_upgrade",
            timeout=900,
        )
        require(
            self._clone_sql(container, "SELECT version_num FROM alembic_version")
            == TARGET_SCHEMA,
            "clone_target_schema",
        )
        require(
            self._clone_table_identity(container) == self._table_identity,
            "clone_retained_business",
        )
        self._run("docker", "stop", container, code="clone_stop", timeout=60)
        receipt = {
            "chain": [BASE_SCHEMA, "20260923_0049", TARGET_SCHEMA],
            "source_dump_sha256": dump_sha256,
            "isolated_restore_readback": True,
            "isolated_target": True,
            "source_business_sha256": baseline["business_identity_sha256"],
            "retained_business_sha256": baseline["business_identity_sha256"],
            "existing_table_counts_equal": True,
            "source_schema": BASE_SCHEMA,
            "target_schema": TARGET_SCHEMA,
            "clone_network": network,
            "clone_volume": volume,
            "clone_container": container,
        }
        receipt["receipt_sha256"] = sha(canonical(receipt))
        self._clone_verified = True
        return receipt

    def _production_db_url(self) -> str:
        # Use the actual running application's resolved URL, not a second,
        # potentially divergent interpretation of Compose .env quoting.
        value = self._service_env.get("acquisition-api", {}).get("DATABASE_URL")
        require(
            isinstance(value, str) and value.startswith("postgresql+asyncpg://"),
            "production_database_url",
        )
        parsed = urlsplit(value)
        require(
            parsed.hostname == "postgres"
            and parsed.port == 5432
            and bool(parsed.username)
            and bool(parsed.password)
            and bool(parsed.path.strip("/")),
            "production_database_url",
        )
        assert isinstance(value, str)
        return value

    def _production_network(self) -> str:
        networks = (
            self._service("postgres").get("NetworkSettings", {}).get("Networks", {})
        )
        require(isinstance(networks, dict) and len(networks) == 1, "postgres_network")
        network = cast(str, next(iter(networks)))
        require(network.startswith(PROJECT + "_"), "postgres_network_identity")
        return network

    def migrate_forward(self, command: tuple[str, ...], chain: list[str]) -> None:
        self._require_mutation_review()
        baseline = self._required_baseline()
        require(
            self._clone_verified
            and self._candidate_loaded
            and self.verify_writers_stopped()
            and command == ALEMBIC_ONLY_COMMAND
            and chain == [BASE_SCHEMA, "20260923_0049", TARGET_SCHEMA]
            and self.read_schema_head() == BASE_SCHEMA,
            "production_migration_gate",
        )
        require(
            bool(self._table_identity)
            and self._work_counts() == (0, 0)
            and self._db_identity(allow_additive_tables=False)
            == baseline["business_identity_sha256"],
            "production_pre_migration_business_drift",
        )
        db_env = self.attempt_dir / "production-migration.env"
        self._write_private(
            db_env, ("DATABASE_URL=" + self._production_db_url() + "\n").encode()
        )
        self._run(
            "docker",
            "run",
            "--rm",
            "--pull",
            "never",
            "--network",
            self._production_network(),
            "--env-file",
            str(db_env),
            "--entrypoint",
            "python",
            self._candidate_ref(),
            *ALEMBIC_ONLY_COMMAND[1:],
            code="production_alembic_upgrade",
            timeout=900,
        )
        require(self.read_schema_head() == TARGET_SCHEMA, "production_target_schema")
        require(
            self._db_identity() == baseline["business_identity_sha256"],
            "migration_business_drift",
        )

    def _replace_file(self, name: str, body: bytes) -> None:
        self._require_mutation_review()
        baseline = self._required_baseline()
        require(name in PROTECTED_FILES, "replace_scope")
        path = self.paths.app / name
        parent = path.parent
        while parent != self.paths.app.parent:
            info = parent.lstat()
            require(
                stat.S_ISDIR(info.st_mode) and not parent.is_symlink(),
                "protected_parent_type",
            )
            parent = parent.parent
        before = _metadata(path)
        require(
            {key: value for key, value in before.items() if key != "size"}
            == baseline["protected_files"][name],
            "protected_before_replace",
        )
        temp = path.with_name(path.name + ".r16-new")
        fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as stream:
            stream.write(body)
            os.fchmod(stream.fileno(), int(before["mode"]))
            os.fchown(stream.fileno(), int(before["uid"]), int(before["gid"]))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
        require(_metadata(path)["sha256"] == sha(body), "protected_replace_readback")

    def install_candidate(self, manifest: dict[str, Any]) -> None:
        self._require_mutation_review()
        require(
            manifest == self.manifest
            and self._clone_verified
            and self.read_schema_head() == TARGET_SCHEMA
            and self.verify_writers_stopped(),
            "candidate_install_gate",
        )
        host_files = manifest.get("host_files")
        require(
            isinstance(host_files, dict) and set(host_files) == set(REPLACED_FILES),
            "host_files_manifest",
        )
        assert isinstance(host_files, dict)
        candidate_bodies: dict[str, bytes] = {}
        for name in REPLACED_FILES:
            body = self._bundle_file("host-files/" + name).read_bytes()
            require(sha(body) == host_files[name], "host_file_sha256")
            candidate_bodies[name] = body
        migration = _json(
            candidate_bodies["deploy/release/migration-compatibility.json"],
            "migration_declaration_json",
        )
        require(
            migration.get("previous_application_compatible") is False
            and migration.get("reviewed") is True
            and migration.get("alembic_head") == TARGET_SCHEMA,
            "migration_declaration",
        )
        release_path = self.paths.app / ".release.env"
        release_body = release_path.read_bytes()
        old_line = ("APP_IMAGE=" + BASE_REF).encode()
        require(release_body.count(old_line) == 1, "release_env_old_ref")
        new_release = release_body.replace(
            old_line, ("APP_IMAGE=" + self._candidate_ref()).encode()
        )
        for name in REPLACED_FILES:
            self._replace_file(name, candidate_bodies[name])
        self._replace_file(".release.env", new_release)
        for name in (".release-commit", "RELEASE_COMMIT"):
            self._replace_file(name, (manifest["revision"] + "\n").encode())

    def start_default_off(self, services: tuple[str, ...]) -> None:
        self._require_mutation_review()
        require(
            services == SERVICES
            and self.read_schema_head() == TARGET_SCHEMA
            and _parse_env(self.paths.app / ".release.env").get("APP_IMAGE")
            == self._candidate_ref()
            and all(
                _parse_env(self.paths.app / ".env").get(key, "false").lower() == "false"
                for key in OFF_FLAGS
            ),
            "default_off_start_gate",
        )
        self._compose(
            "up",
            "-d",
            "--no-build",
            "--no-deps",
            "--pull",
            "never",
            "--force-recreate",
            "--wait",
            "--wait-timeout",
            "300",
            *SERVICES,
            code="default_off_start",
            timeout=600,
        )

    def verify_candidate(self, manifest: dict[str, Any]) -> bool:
        baseline = self._required_baseline()
        require(
            manifest == self.manifest and self._baseline is not None,
            "candidate_verify_gate",
        )
        if self.read_schema_head() != TARGET_SCHEMA:
            return False
        env = _parse_env(self.paths.app / ".env")
        if any(env.get(key, "false").lower() != "false" for key in OFF_FLAGS):
            return False
        if (
            _tree_hash(self.paths.app / "private/brand-materials")
            != baseline["brand_identity_sha256"]
        ):
            return False
        if sha(canonical(self._minio_snapshot())) != baseline["volumes"][MINIO_VOLUME]:
            return False
        if any(
            _tree_hash(self._volume_paths[name]) != baseline["volumes"][name]
            for name in ARCHIVE_VOLUMES
        ):
            return False
        if self._db_identity() != baseline["business_identity_sha256"]:
            return False
        host_files = manifest.get("host_files")
        if not isinstance(host_files, dict) or set(host_files) != set(REPLACED_FILES):
            return False
        for name in PROTECTED_FILES:
            actual = _metadata(self.paths.app / name)
            if name in REPLACED_FILES:
                expected_sha = host_files[name]
            elif name in (".release-commit", "RELEASE_COMMIT"):
                expected_sha = sha((manifest["revision"] + "\n").encode())
            elif name == ".release.env":
                saved = (self.attempt_dir / "protected" / name).read_bytes()
                old_line = ("APP_IMAGE=" + BASE_REF).encode()
                if saved.count(old_line) != 1:
                    return False
                expected_sha = sha(
                    saved.replace(
                        old_line, ("APP_IMAGE=" + self._candidate_ref()).encode()
                    )
                )
                if (
                    _parse_env(self.paths.app / name).get("APP_IMAGE")
                    != self._candidate_ref()
                ):
                    return False
            else:
                expected_sha = baseline["protected_files"][name]["sha256"]
            if actual["sha256"] != expected_sha:
                return False
        for name, container_id in baseline["dependencies"].items():
            if self._service(name).get("Id") != container_id:
                return False
        for name in SERVICES:
            item = self._service(name)
            state = item.get("State", {})
            config = item.get("Config", {})
            if (
                item.get("Image") != manifest["image"]
                or config.get("Image") != self._candidate_ref()
                or state.get("Status") != "running"
                or state.get("Health", {}).get("Status", "healthy") != "healthy"
                or item.get("RestartCount") != 0
            ):
                return False
            new_env = dict(
                value.split("=", 1) for value in config.get("Env", []) if "=" in value
            )
            old_env = self._service_env[name]
            common = {
                key: value
                for key, value in new_env.items()
                if not key.startswith("WECOM_INFOGRAPHIC_")
            }
            if common != old_env:
                return False
            if any(new_env.get(key, "false").lower() != "false" for key in OFF_FLAGS):
                return False
            if (
                sha(canonical(config.get("Cmd")))
                != baseline["services"][name]["command_sha256"]
            ):
                return False
            if (
                _mounts_sha256(item.get("Mounts"))
                != baseline["services"][name]["mounts_sha256"]
            ):
                return False
        optional = self._run(
            "docker",
            "ps",
            "-a",
            "-q",
            "--filter",
            f"label=com.docker.compose.project={PROJECT}",
            "--filter",
            "label=com.docker.compose.service=wecom-infographic-producer",
            code="optional_producer_lookup",
        )
        if optional.strip():
            return False
        health = _json(
            self._run(
                "curl",
                "--fail",
                "--silent",
                "--max-time",
                "5",
                "--max-filesize",
                "65536",
                "http://127.0.0.1:8000/healthz",
                code="api_health",
            ),
            "api_health_json",
        )
        return isinstance(health, dict) and health.get("status") == "ok"

    def read_schema_head(self) -> str:
        return self._sql("SELECT version_num FROM alembic_version")

    def verify_original_recoverable(
        self, live_baseline: dict[str, Any]
    ) -> dict[str, Any]:
        """Prove exact R15 code/config/containers remain before any restart."""
        self._require_mutation_review()
        require(
            self._baseline is not None
            and not (self.attempt_dir / "migration-intent.json").exists()
            and self.read_schema_head() == BASE_SCHEMA
            and (self.paths.app / ".release-commit").read_text().strip()
            == BASE_REVISION
            and (self.paths.app / "RELEASE_COMMIT").read_text().strip() == BASE_REVISION
            and _parse_env(self.paths.app / ".release.env").get("APP_IMAGE")
            == BASE_REF,
            "pre_migration_original_identity",
        )
        baseline = self._required_baseline()
        require(
            all(
                baseline.get(key) == live_baseline.get(key)
                for key in live_baseline
                if key not in ("business_identity_sha256", "volumes")
            )
            and all(
                baseline["volumes"][name] == live_baseline["volumes"][name]
                for name in ARCHIVE_VOLUMES
            ),
            "pre_migration_baseline_identity",
        )
        protected, brand, volumes = self._common_identity()
        require(
            {
                name: {key: value for key, value in meta.items() if key != "size"}
                for name, meta in protected.items()
            }
            == live_baseline["protected_files"]
            and brand == live_baseline["brand_identity_sha256"]
            and volumes == baseline["volumes"]
            and self._work_counts() == (0, 0),
            "pre_migration_data_or_file_drift",
        )
        image = self._image(BASE_REF)
        require(image.get("Id") == BASE_IMAGE, "pre_migration_image_identity")
        for name, container_id in live_baseline["dependencies"].items():
            item = self._service(name)
            require(
                item.get("Id") == container_id
                and item.get("State", {}).get("Status") == "running",
                "pre_migration_dependency_identity",
            )
        for name in SERVICES:
            item = self._service(name)
            config = item.get("Config", {})
            expected = live_baseline["services"][name]
            actual_env = dict(
                value.split("=", 1) for value in config.get("Env", []) if "=" in value
            )
            require(
                item.get("Id") == expected["container_id"]
                and item.get("Image") == BASE_IMAGE
                and config.get("Image") == BASE_REF
                and item.get("State", {}).get("Status") in ("running", "exited")
                and item.get("RestartCount") == 0
                and sha(canonical(config.get("Cmd"))) == expected["command_sha256"]
                and _mounts_sha256(item.get("Mounts")) == expected["mounts_sha256"]
                and sha(canonical(actual_env)) == expected["env_sha256"],
                "pre_migration_service_identity",
            )
        optional = self._run(
            "docker",
            "ps",
            "-a",
            "-q",
            "--filter",
            f"label=com.docker.compose.project={PROJECT}",
            "--filter",
            "label=com.docker.compose.service=wecom-infographic-producer",
            code="optional_producer_lookup",
        )
        require(not optional.strip(), "pre_migration_optional_producer")
        business_sha = self._db_identity(allow_additive_tables=False)
        require(
            not self._table_identity
            or business_sha == sha(canonical(self._table_identity)),
            "pre_migration_business_drift",
        )
        self._original_recovery_verified = True
        return {
            "verified": True,
            "schema": BASE_SCHEMA,
            "image": BASE_IMAGE,
            "revision": BASE_REVISION,
            "business_identity_sha256": business_sha,
            "baseline_sha256": sha(canonical(live_baseline)),
            "services": len(SERVICES),
        }

    def start_original(self, services: tuple[str, ...]) -> None:
        self._require_mutation_review()
        require(
            services == SERVICES
            and self._original_recovery_verified
            and not (self.attempt_dir / "migration-intent.json").exists()
            and (self.attempt_dir / "pre-migration-recovery-intent.json").is_file(),
            "pre_migration_restart_gate",
        )
        # `start` uses the existing containers and cannot recreate from new code.
        self._compose("start", *SERVICES, code="start_original", timeout=180)
        self._stopped = False

    def verify_original_recovered(self, live_baseline: dict[str, Any]) -> bool:
        require(self._original_recovery_verified, "recovery_verification_order")
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            healthy = True
            for name in SERVICES:
                item = self._service(name)
                state = item.get("State", {})
                if not (
                    item.get("Id") == live_baseline["services"][name]["container_id"]
                    and state.get("Status") == "running"
                    and state.get("Health", {}).get("Status", "healthy") == "healthy"
                ):
                    healthy = False
                    break
            if healthy:
                return self.read_schema_head() == BASE_SCHEMA
            time.sleep(2)
        return False

    def stop_all(self) -> None:
        self._require_mutation_review()
        self._compose("stop", *SERVICES, code="stop_all", timeout=180)
