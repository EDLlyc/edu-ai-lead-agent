#!/usr/bin/env python3
"""Pure validation for the substantive-release incident offline release stage."""

from __future__ import annotations

import argparse
import ast
import gzip
import hashlib
import json
import os
import re
import stat
import sys
import tarfile
import tempfile
from datetime import UTC, date, datetime, timedelta
from io import BytesIO
from pathlib import Path, PurePosixPath
from typing import Any, NoReturn

SCHEMA_VERSION = 1
PRODUCTION_COMMIT = "5c560da71bcbb61b765d3fe82c742cf2d5e676e1"
PRODUCTION_IMAGE_ID = (
    "sha256:35e4405a5dfa06e70a45c360d8838021e00c05938ac7f7e818378c6454d48454"
)
PRODUCTION_PRIMARY_ENV_SHA256 = (
    "bff0015eeabd72fbcf34f48aaeb5f6a077c9752a3afd7953d0ae67b934898b84"
)
PRODUCTION_RELEASE_ENV_SHA256 = (
    "37b940c6e6df6a65ae12bc372c381e78ac0b2866cf439c3552bebfddbac57467"
)
LEGACY_PRODUCTION_COMMIT = b"5c560da71bcbb61b765d3fe82c742cf2d5e676e1"
LEGACY_PRODUCTION_COMMIT_HASHES = {
    hashlib.sha256(LEGACY_PRODUCTION_COMMIT).hexdigest(),
    hashlib.sha256(LEGACY_PRODUCTION_COMMIT + b"\n").hexdigest(),
}
RELEASE_REF = "refs/remotes/origin/release/substantive-news-scope-20260905"
ALEMBIC_HEAD = "20260901_0042"
OLD_SCORING_VERSION = "scoring-v1-preview.11-qualified-authoritative-priority"
NEW_SCORING_VERSION = "scoring-v1-preview.12-substantive-topic-scope"
PRIORITY_RULE_VERSION = "qualified-authoritative-priority-v1"
# One-shot activation boundary reviewed after the September 5 business date expired. 09:00 UTC
# is the September 6 17:00 Asia/Shanghai evening-slot preparation. The validator additionally
# derives the next producer from live runtime settings, so using these bytes before the noon
# window closes or after this boundary fails closed.
EARLIEST_PRODUCER_UTC = "2026-09-06T09:00:00Z"
FROZEN_COPY_JOB_SHA256 = (
    "657797a7d4b8d51c8355c07c62343610529fc85753ecb7b489dcd2ef3c5dc74c"
)
SHA256 = re.compile(r"[0-9a-f]{64}")
COMMIT = re.compile(r"[0-9a-f]{40}")
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")
IMAGE_REFERENCE = re.compile(
    r"[a-z0-9.-]+(?::[0-9]+)?(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*"
    r"@sha256:[0-9a-f]{64}"
)
REPOSITORY = re.compile(r"[a-z0-9.-]+(?::[0-9]+)?(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*")
TIMESTAMP = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z")
BUSINESS_DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
SAFE_SOURCE_PATH = re.compile(r"[A-Za-z0-9._/-]+")

APP_SERVICES = (
    "acquisition-api",
    "acquisition-scheduler",
    "acquisition-worker",
    "governance-scheduler",
    "governance-worker",
    "content-scheduler",
    "content-worker",
    "wecom-dispatcher",
    "official-account-weekly-dag-worker",
    "official-account-weekly-scheduler",
    "official-account-local-worker",
    "wechat-official-account-draft-worker",
)
INFRA_SERVICES = ("postgres", "minio")
SERVICE_COMMANDS: dict[str, tuple[str, ...]] = {
    "acquisition-api": (
        "python",
        "-m",
        "uvicorn",
        "app.api_main:app",
        "--host",
        "0.0.0.0",
        "--port",
        "8000",
    ),
    "acquisition-scheduler": ("python", "-m", "app.scheduler_main"),
    "acquisition-worker": ("python", "-m", "app.worker_main"),
    "governance-scheduler": ("python", "-m", "app.governance_scheduler_main"),
    "governance-worker": ("python", "-m", "app.governance_worker_main"),
    "content-scheduler": ("python", "-m", "app.content_scheduler_main"),
    "content-worker": ("python", "-m", "app.content_worker_main"),
    "wecom-dispatcher": ("python", "-m", "app.wecom_dispatcher_main"),
    "official-account-weekly-dag-worker": (
        "python",
        "-m",
        "app.official_account_weekly_dag_main",
        "--handler-mode",
        "production",
        "worker",
        "--concurrency",
        "3",
        "--lease-seconds",
        "900",
        "--poll-seconds",
        "2",
    ),
    "official-account-weekly-scheduler": (
        "python",
        "-m",
        "app.official_account_weekly_scheduler_main",
    ),
    "official-account-local-worker": (
        "python",
        "-m",
        "app.official_account_worker_main",
    ),
    "wechat-official-account-draft-worker": (
        "python",
        "-m",
        "app.wechat_official_account_draft_main",
        "worker",
    ),
}
RUNTIME_DIFF = {
    ".env.example": "M",
    "backend/app/application/services/topic_selection.py": "M",
    "backend/app/core/config.py": "M",
    "backend/app/domain/editorial_relevance.py": "M",
    "backend/app/domain/topic_selection.py": "M",
    "backend/app/infrastructure/db/topic_selection.py": "M",
    "compose.yaml": "M",
    "scripts/doctor.sh": "M",
}
AUDIT_EXACT: dict[str, str] = {
    ".trellis/spec/backend/substantive-topic-scope.md": "A",
    ".trellis/spec/backend/index.md": "M",
    ".trellis/spec/backend/topic-selection.md": "M",
    "backend/tests/unit/test_substantive_topic_scope.py": "A",
    "backend/tests/unit/test_topic_selection.py": "M",
    "backend/tests/unit/test_topic_selection_delivery.py": "M",
    "backend/tests/integration/test_topic_selection_repositories.py": "M",
}
AUDIT_TASK_PREFIX = ".trellis/tasks/09-05-production-recovery-qwen-embedding/"
EFFECT_COUNT_ORDER = (
    "copy_provider_unavailable_terminal",
    "copy_generation_attempts",
    "wecom_delivery_jobs",
    "wecom_delivery_attempts",
    "weekly_dag_runs",
    "weekly_dag_attempts",
    "official_account_article_runs",
    "official_account_article_attempts",
    "wechat_mp_draft_jobs",
    "wechat_mp_draft_items",
    "wechat_mp_draft_attempts",
    "claimable_copy_jobs",
    "running_copy_jobs",
    "current_business_date_copy_jobs",
    "future_copy_jobs",
    "pending_wecom_jobs",
    "pending_weekly_runs",
    "pending_official_account_runs",
    "pending_wechat_draft_jobs",
    "material_packages",
    "copy_generation_runs",
    "copy_generation_jobs",
    "delivered_wecom_jobs",
    "new_policy_topic_runs",
    "new_policy_topic_jobs",
    "new_policy_slot_runs",
    "new_policy_slot_jobs",
)
EFFECT_COUNT_KEYS = set(EFFECT_COUNT_ORDER)
EXACT_EFFECT_COUNTS = {
    "copy_generation_attempts": 479,
    "wecom_delivery_attempts": 191,
    "material_packages": 112,
    "copy_generation_runs": 196,
    "copy_generation_jobs": 196,
    "delivered_wecom_jobs": 95,
    **{key: 0 for key in EFFECT_COUNT_ORDER if key.startswith("new_policy_")},
}
MEMBERS = {
    "artifacts.sha256",
    "audit-diff.tsv",
    "backend-image.oci.tar.gz",
    "build-substantive-release.sh",
    "capture-substantive-production-baseline.sh",
    "image-source.sha256",
    "production-baseline.json",
    "release-metadata.json",
    "runtime-diff.tsv",
    "source-manifest.tsv",
    "source.tar.gz",
    "validate-substantive-release.py",
    "substantive-release-operator.sh",
}
CHECKSUM_TARGETS = MEMBERS - {"artifacts.sha256"}
MAX_STAGE_MEMBER = 8 * 1024 * 1024 * 1024
MAX_ARCHIVE_TOTAL = 8 * 1024 * 1024 * 1024
MAX_JSON = 16 * 1024 * 1024
MAX_ALEMBIC_REVISIONS = 256
MAX_ALEMBIC_SOURCE = 512 * 1024
MAX_ALEMBIC_AST_NODES = 20_000
OCI_LAYOUT_MEDIA_TYPE = "application/vnd.oci.image.index.v1+json"
OCI_MANIFEST_MEDIA_TYPE = "application/vnd.oci.image.manifest.v1+json"
OCI_CONFIG_MEDIA_TYPE = "application/vnd.oci.image.config.v1+json"
OCI_LAYER_MEDIA_TYPES = {
    "application/vnd.oci.image.layer.v1.tar": (
        "application/vnd.oci.image.layer.v1.tar",
        False,
    ),
    "application/vnd.oci.image.layer.v1.tar+gzip": (
        "application/vnd.oci.image.layer.v1.tar+gzip",
        True,
    ),
    "application/vnd.docker.image.rootfs.diff.tar": (
        "application/vnd.oci.image.layer.v1.tar",
        False,
    ),
    "application/vnd.docker.image.rootfs.diff.tar.gzip": (
        "application/vnd.oci.image.layer.v1.tar+gzip",
        True,
    ),
}


def fail(message: str) -> NoReturn:
    raise ValueError(message)


def digest_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def digest_file(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def strict_json(value: bytes, label: str) -> Any:
    def reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, item in pairs:
            if key in result:
                fail(f"{label} contains duplicate JSON keys")
            result[key] = item
        return result

    def reject_constant(_: str) -> NoReturn:
        fail(f"{label} contains a non-finite JSON value")

    try:
        text = value.decode("utf-8")
        parsed = json.loads(
            text,
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is not strict JSON") from exc
    if not text or text.strip() != text or "\r" in text:
        fail(f"{label} JSON encoding is non-canonical")
    return parsed


def canonical_json_bytes(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode()


def normalize_containerd_reference(transport_tag: str) -> str:
    if (
        re.fullmatch(
            r"[a-z0-9.-]+(?::[0-9]+)?(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*"
            r":[a-z0-9][a-z0-9._-]*",
            transport_tag,
        )
        is None
    ):
        fail("transport tag cannot be normalized safely")
    repository, tag = transport_tag.rsplit(":", 1)
    pieces = repository.split("/")
    first = pieces[0]
    if len(pieces) == 1:
        repository = f"docker.io/library/{repository}"
    elif "." not in first and ":" not in first and first != "localhost":
        repository = f"docker.io/{repository}"
    return f"{repository}:{tag}"


def safe_path(value: str) -> str:
    candidate = value.removeprefix("./").removesuffix("/")
    path = PurePosixPath(candidate)
    normalized = str(path)
    if (
        not normalized
        or path.is_absolute()
        or normalized != candidate
        or any(part in {"", ".", ".."} for part in path.parts)
        or SAFE_SOURCE_PATH.fullmatch(normalized) is None
    ):
        fail("unsafe archive path")
    return normalized


def has_symlink_component(path: Path) -> bool:
    current = Path(path.anchor) if path.is_absolute() else Path()
    for part in path.parts:
        if part == path.anchor:
            continue
        current /= part
        if current.is_symlink():
            return True
    return False


def stable_read_regular(
    path: Path,
    *,
    expected_mode: int | None = None,
    expected_uid: int | None = None,
    expected_gid: int | None = None,
    max_bytes: int = 2 * 1024 * 1024,
) -> tuple[bytes, os.stat_result]:
    if has_symlink_component(path.absolute()):
        fail("protected file path contains a symlink")
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        before = os.fstat(descriptor)
        if (
            not stat.S_ISREG(before.st_mode)
            or (
                expected_mode is not None
                and stat.S_IMODE(before.st_mode) != expected_mode
            )
            or (expected_uid is not None and before.st_uid != expected_uid)
            or (expected_gid is not None and before.st_gid != expected_gid)
            or before.st_size > max_bytes
        ):
            fail("protected file identity is outside the reviewed contract")
        chunks: list[bytes] = []
        size = 0
        while chunk := os.read(descriptor, min(1024 * 1024, max_bytes + 1 - size)):
            chunks.append(chunk)
            size += len(chunk)
            if size > max_bytes:
                fail("protected file exceeds its byte bound")
        after = os.fstat(descriptor)
        observed = os.lstat(path)
        fields = (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_uid",
            "st_gid",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        if any(
            getattr(before, field) != getattr(after, field) for field in fields
        ) or any(getattr(after, field) != getattr(observed, field) for field in fields):
            fail("protected file changed during its stable read")
        return b"".join(chunks), after
    finally:
        os.close(descriptor)


def derive_candidate_environment(raw: bytes) -> bytes:
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError("primary environment is not UTF-8") from exc
    if "\r" in text or "\x00" in text:
        fail("primary environment has a non-canonical encoding")
    lines = text.splitlines(keepends=True)
    scoring_assignment = re.compile(
        r"^[ \t]*(?:export[ \t]+)?CONTENT_SCORING_VERSION[ \t]*="
    )
    priority_assignment = re.compile(
        r"^[ \t]*(?:export[ \t]+)?CONTENT_SELECTION_PRIORITY_RULE_VERSION[ \t]*="
    )
    scoring_rows = [
        index for index, line in enumerate(lines) if scoring_assignment.match(line)
    ]
    priority_rows = [
        index for index, line in enumerate(lines) if priority_assignment.match(line)
    ]
    if len(scoring_rows) != 1:
        fail("primary environment must contain one scoring-version assignment")
    if len(priority_rows) != 1:
        fail("primary environment must contain one priority-rule assignment")
    scoring_index = scoring_rows[0]
    priority_index = priority_rows[0]
    scoring_line = lines[scoring_index]
    priority_line = lines[priority_index]
    scoring_ending = "\n" if scoring_line.endswith("\n") else ""
    priority_ending = "\n" if priority_line.endswith("\n") else ""
    if scoring_line.removesuffix(scoring_ending) != (
        f"CONTENT_SCORING_VERSION={OLD_SCORING_VERSION}"
    ):
        fail("primary environment scoring version differs from the reviewed value")
    if priority_line.removesuffix(priority_ending) != (
        f"CONTENT_SELECTION_PRIORITY_RULE_VERSION={PRIORITY_RULE_VERSION}"
    ):
        fail("primary environment priority rule differs from the reviewed value")
    if digest_bytes(raw) != PRODUCTION_PRIMARY_ENV_SHA256:
        fail("primary environment contains an unreviewed byte change")
    lines[scoring_index] = (
        f"CONTENT_SCORING_VERSION={NEW_SCORING_VERSION}{scoring_ending}"
    )
    candidate = "".join(lines).encode()
    if candidate == raw or candidate.count(NEW_SCORING_VERSION.encode()) != 1:
        fail("candidate environment scoring replacement is ambiguous")
    return candidate


def environment_plan(path: Path) -> tuple[str, str]:
    raw, _ = stable_read_regular(
        path, expected_mode=0o600, expected_uid=1000, expected_gid=1001
    )
    candidate = derive_candidate_environment(raw)
    return digest_bytes(raw), digest_bytes(candidate)


def _atomic_replace_environment(
    *,
    target: Path,
    value: bytes,
    accepted_current_sha256: set[str],
) -> None:
    current, identity = stable_read_regular(
        target, expected_mode=0o600, expected_uid=1000, expected_gid=1001
    )
    if digest_bytes(current) not in accepted_current_sha256:
        fail("protected environment changed before atomic replacement")
    descriptor, raw_temporary = tempfile.mkstemp(
        dir=target.parent, prefix=".env.substantive-release."
    )
    temporary = Path(raw_temporary)
    replaced = False
    try:
        with os.fdopen(descriptor, "wb", closefd=True) as stream:
            stream.write(value)
            stream.flush()
            os.fchmod(stream.fileno(), 0o600)
            os.fchown(stream.fileno(), 1000, 1001)
            os.fsync(stream.fileno())
        staged, _ = stable_read_regular(
            temporary, expected_mode=0o600, expected_uid=1000, expected_gid=1001
        )
        if staged != value:
            fail("staged protected environment changed")
        latest, observed = stable_read_regular(
            target, expected_mode=0o600, expected_uid=1000, expected_gid=1001
        )
        fields = (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_uid",
            "st_gid",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        if latest != current or any(
            getattr(observed, field) != getattr(identity, field) for field in fields
        ):
            fail("protected environment path changed before atomic replacement")
        os.replace(temporary, target)
        replaced = True
        directory = os.open(target.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
        installed, _ = stable_read_regular(
            target, expected_mode=0o600, expected_uid=1000, expected_gid=1001
        )
        if installed != value:
            fail("installed protected environment changed")
    finally:
        if not replaced:
            temporary.unlink(missing_ok=True)


def activate_candidate_environment(
    source: Path, target: Path, expected_candidate_sha256: str
) -> None:
    raw, _ = stable_read_regular(
        source, expected_mode=0o600, expected_uid=1000, expected_gid=1001
    )
    candidate = derive_candidate_environment(raw)
    if SHA256.fullmatch(expected_candidate_sha256) is None or (
        digest_bytes(candidate) != expected_candidate_sha256
    ):
        fail("candidate environment hash differs from the captured plan")
    _atomic_replace_environment(
        target=target,
        value=candidate,
        accepted_current_sha256={PRODUCTION_PRIMARY_ENV_SHA256},
    )


def restore_production_environment(
    source: Path, target: Path, expected_candidate_sha256: str
) -> None:
    raw, _ = stable_read_regular(
        source, expected_mode=0o600, expected_uid=1000, expected_gid=1001
    )
    if digest_bytes(raw) != PRODUCTION_PRIMARY_ENV_SHA256:
        fail("environment backup differs from the production baseline")
    if SHA256.fullmatch(expected_candidate_sha256) is None:
        fail("candidate environment hash is malformed")
    if digest_bytes(derive_candidate_environment(raw)) != expected_candidate_sha256:
        fail("rollback candidate hash differs from the exact single-key plan")
    _atomic_replace_environment(
        target=target,
        value=raw,
        accepted_current_sha256={
            PRODUCTION_PRIMARY_ENV_SHA256,
            expected_candidate_sha256,
        },
    )


def checksum_rows(path: Path) -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9][A-Za-z0-9._-]*)", line)
        if match is None or match.group(2) in rows:
            fail("artifact checksum manifest is malformed")
        rows[match.group(2)] = match.group(1)
    if set(rows) != CHECKSUM_TARGETS or list(rows) != sorted(rows):
        fail("artifact checksum member set changed")
    return rows


def diff_rows(path: Path, *, runtime: bool) -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        pieces = line.split("\t")
        if len(pieces) != 2 or pieces[0] not in {"A", "M"}:
            fail("diff evidence is malformed")
        name = safe_path(pieces[1])
        if name in rows:
            fail("diff evidence has duplicate paths")
        rows[name] = pieces[0]
    if list(rows) != sorted(rows):
        fail("diff evidence is unsorted")
    if runtime:
        if rows != RUNTIME_DIFF:
            fail("runtime diff is not the complete reviewed allowlist")
    elif (
        any(rows.get(name) != status for name, status in AUDIT_EXACT.items())
        or not any(name.startswith(AUDIT_TASK_PREFIX) for name in rows)
        or any(
            name not in AUDIT_EXACT
            and not (name.startswith(AUDIT_TASK_PREFIX) and status == "A")
            for name, status in rows.items()
        )
    ):
        fail(
            "non-runtime diff escaped or incompletely matched the audit/test allowlist"
        )
    return rows


def source_manifest(path: Path) -> dict[str, tuple[str, int, str]]:
    rows: dict[str, tuple[str, int, str]] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        pieces = line.split("\t")
        if len(pieces) != 4 or pieces[0] not in {"d", "f"}:
            fail("source manifest is malformed")
        kind, raw_mode, raw_hash, raw_name = pieces
        name = safe_path(raw_name)
        if name in rows or re.fullmatch(r"0[0-7]{3}", raw_mode) is None:
            fail("source manifest identity is malformed")
        mode = int(raw_mode, 8)
        if kind == "d":
            if mode != 0o755 or raw_hash != "-":
                fail("source directory mode or digest changed")
        elif mode not in {0o644, 0o755} or SHA256.fullmatch(raw_hash) is None:
            fail("source file mode or digest changed")
        rows[name] = (kind, mode, raw_hash)
    if list(rows) != sorted(rows):
        fail("source manifest is unsorted")
    required = {
        "backend",
        "deploy",
        "infra",
        "scripts",
        "compose.yaml",
        "backend/alembic.ini",
        "backend/pyproject.toml",
        *RUNTIME_DIFF,
    }
    if not required.issubset(rows) or any(
        name in {".env", ".release.env"} or name.startswith("private/") for name in rows
    ):
        fail("source manifest is incomplete or contains protected state")
    return rows


def alembic_revision(source: bytes, name: str) -> str:
    if len(source) > MAX_ALEMBIC_SOURCE:
        fail("Alembic revision source exceeds its bound")
    try:
        tree = ast.parse(source, filename=name)
    except (MemoryError, RecursionError, SyntaxError, ValueError) as exc:
        raise ValueError("Alembic revision source is malformed") from exc
    for index, _node in enumerate(ast.walk(tree), start=1):
        if index > MAX_ALEMBIC_AST_NODES:
            fail("Alembic revision AST exceeds its bound")
    declarations: list[tuple[ast.expr | None, ast.Name]] = []
    for node in tree.body:
        match node:
            case ast.Assign(targets=targets, value=value):
                declarations.extend(
                    (value, target)
                    for target in targets
                    if isinstance(target, ast.Name) and target.id == "revision"
                )
            case ast.AnnAssign(target=ast.Name(id="revision") as target, value=value):
                declarations.append((value, target))
    if len(declarations) != 1:
        fail("Alembic revision declaration is missing or duplicated")
    value, allowed_target = declarations[0]
    if not isinstance(value, ast.Constant) or not isinstance(value.value, str):
        fail("Alembic revision declaration is not a static string")
    if any(
        isinstance(node, ast.Name)
        and node.id == "revision"
        and isinstance(node.ctx, (ast.Store, ast.Del))
        and node is not allowed_target
        for node in ast.walk(tree)
    ):
        fail("Alembic revision declaration is dynamically rebound")
    return value.value


def image_source_projection(
    rows: dict[str, tuple[str, int, str]],
) -> dict[str, str]:
    projected: dict[str, str] = {}
    for name, (kind, _mode, checksum) in rows.items():
        if kind != "f" or not name.startswith("backend/"):
            continue
        relative = name.removeprefix("backend/")
        relative_path = PurePosixPath(relative)
        if relative in {"alembic.ini", "pyproject.toml"} or (
            relative_path.suffix in {".py", ".html"}
            and relative_path.parts[0] in {"app", "alembic"}
        ):
            projected[relative] = checksum
    required = {
        "alembic.ini",
        "pyproject.toml",
        "app/api_main.py",
        "app/content_worker_main.py",
        "app/core/config.py",
        "app/infrastructure/ai/factory.py",
    }
    if not required.issubset(projected):
        fail("complete image source projection is missing required runtime files")
    return projected


def validate_source_archive(stage: Path) -> dict[str, str]:
    expected = source_manifest(stage / "source-manifest.tsv")
    observed: dict[str, tuple[str, int, str]] = {}
    revisions: dict[str, str] = {}
    total = 0
    try:
        with tarfile.open(stage / "source.tar.gz", "r:gz") as archive:
            for member in archive:
                name = safe_path(member.name)
                if name in observed or member.issym() or member.islnk():
                    fail("source archive has duplicate or linked members")
                mode = stat.S_IMODE(member.mode)
                if member.isdir():
                    if mode != 0o755:
                        fail("source archive directory mode changed")
                    observed[name] = ("d", mode, "-")
                    continue
                if not member.isfile() or mode not in {0o644, 0o755}:
                    fail("source archive member type or mode changed")
                total += member.size
                if member.size < 0 or total > MAX_ARCHIVE_TOTAL:
                    fail("source archive exceeds its bound")
                stream = archive.extractfile(member)
                if stream is None:
                    fail("source archive member is unreadable")
                value = stream.read()
                observed[name] = ("f", mode, digest_bytes(value))
                if (
                    name.startswith("backend/alembic/versions/")
                    and PurePosixPath(name).suffix == ".py"
                ):
                    if len(revisions) >= MAX_ALEMBIC_REVISIONS:
                        fail("Alembic revision count exceeds its bound")
                    revision = alembic_revision(value, name)
                    if revision in revisions:
                        fail("Alembic revision declaration is duplicated")
                    revisions[revision] = name
    except (OSError, tarfile.TarError) as exc:
        raise ValueError("source archive is unreadable") from exc
    if observed != expected:
        fail("source archive differs from the complete source manifest")
    if ALEMBIC_HEAD not in revisions:
        fail("Alembic head revision declaration is missing")
    return image_source_projection(expected)


def baseline_manifest(value: object) -> list[dict[str, object]]:
    if not isinstance(value, list) or not value:
        fail("production source baseline is absent")
    result: list[dict[str, object]] = []
    previous = ""
    for row in value:
        if not isinstance(row, dict) or set(row) != {
            "kind",
            "path",
            "mode",
            "uid",
            "gid",
            "sha256",
        }:
            fail("production source baseline row changed")
        name = safe_path(row["path"] if isinstance(row["path"], str) else "")
        kind = row["kind"]
        mode = row["mode"]
        uid = row["uid"]
        gid = row["gid"]
        checksum = row["sha256"]
        if (
            name <= previous
            or kind not in {"d", "f"}
            or isinstance(mode, bool)
            or not isinstance(mode, int)
            or isinstance(uid, bool)
            or not isinstance(uid, int)
            or isinstance(gid, bool)
            or not isinstance(gid, int)
            or uid < 0
            or gid < 0
        ):
            fail("production source baseline ordering or metadata changed")
        if kind == "d":
            if mode not in {0o700, 0o755} or checksum is not None:
                fail("production directory baseline changed")
        elif (
            mode not in {0o600, 0o644, 0o700, 0o755}
            or not isinstance(checksum, str)
            or SHA256.fullmatch(checksum) is None
        ):
            fail("production file baseline changed")
        previous = name
        result.append(row)
    return result


def validate_candidate_source_compatibility(
    candidate: dict[str, tuple[str, int, str]],
    production: list[dict[str, object]],
) -> None:
    baseline = {str(row["path"]): row for row in production}
    if set(baseline) - set(candidate):
        fail("candidate source omits a captured production path")
    for name, previous in baseline.items():
        kind, mode, _checksum = candidate[name]
        if previous["kind"] != kind:
            fail("candidate source type differs from production")
        previous_mode = previous["mode"]
        if (
            kind == "f"
            and isinstance(previous_mode, int)
            and bool(previous_mode & 0o111) != bool(mode & 0o111)
        ):
            fail("candidate executable class differs from production")


def validate_baseline(path: Path) -> dict[str, object]:
    payload = strict_json(path.read_bytes(), "production baseline")
    keys = {
        "schema_version",
        "captured_at_utc",
        "business_timezone",
        "business_date",
        "content_max_attempts",
        "frozen_copy_job_count",
        "frozen_copy_job_sha256",
        "current_commit",
        "current_alembic_head",
        "current_image_id",
        "current_image_reference",
        "current_image_revision",
        "primary_env_sha256",
        "primary_env_mode",
        "primary_env_uid",
        "primary_env_gid",
        "release_env_sha256",
        "legacy_release_commit_sha256",
        "legacy_release_commit_mode",
        "legacy_release_commit_uid",
        "legacy_release_commit_gid",
        "running_services",
        "restart_counts",
        "effect_counts",
        "source_manifest",
    }
    if not isinstance(payload, dict) or set(payload) != keys:
        fail("production baseline keys changed")
    schema_version = payload["schema_version"]
    if (
        isinstance(schema_version, bool)
        or not isinstance(schema_version, int)
        or schema_version != SCHEMA_VERSION
        or payload["current_commit"] != PRODUCTION_COMMIT
        or payload["current_alembic_head"] != ALEMBIC_HEAD
        or payload["current_image_revision"] != PRODUCTION_COMMIT
        or not isinstance(payload["captured_at_utc"], str)
        or TIMESTAMP.fullmatch(payload["captured_at_utc"]) is None
        or not isinstance(payload["current_image_id"], str)
        or IMAGE_ID.fullmatch(payload["current_image_id"]) is None
        or payload["current_image_id"] != PRODUCTION_IMAGE_ID
        or not isinstance(payload["current_image_reference"], str)
        or IMAGE_REFERENCE.fullmatch(payload["current_image_reference"]) is None
        or payload["current_image_reference"]
        != f"edu-ai-lead-agent-backend@{PRODUCTION_IMAGE_ID}"
    ):
        fail("production baseline identity changed")
    business_date = payload["business_date"]
    if (
        payload["business_timezone"] != "Asia/Shanghai"
        or not isinstance(business_date, str)
        or BUSINESS_DATE.fullmatch(business_date) is None
        or isinstance(payload["content_max_attempts"], bool)
        or payload["content_max_attempts"] != 3
        or not isinstance(payload["content_max_attempts"], int)
    ):
        fail("production business-date claim identity changed")
    try:
        date.fromisoformat(business_date)
    except ValueError:
        fail("production business-date claim identity changed")
    frozen_count = payload["frozen_copy_job_count"]
    frozen_digest = payload["frozen_copy_job_sha256"]
    if (
        isinstance(frozen_count, bool)
        or not isinstance(frozen_count, int)
        or frozen_count != 7
        or not isinstance(frozen_digest, str)
        or SHA256.fullmatch(frozen_digest) is None
        or frozen_digest != FROZEN_COPY_JOB_SHA256
    ):
        fail("production frozen copy cohort identity changed")
    for key in (
        "primary_env_sha256",
        "release_env_sha256",
        "legacy_release_commit_sha256",
    ):
        if not isinstance(payload[key], str) or SHA256.fullmatch(payload[key]) is None:
            fail("production environment checksum changed")
    if (
        payload["primary_env_sha256"] != PRODUCTION_PRIMARY_ENV_SHA256
        or payload["release_env_sha256"] != PRODUCTION_RELEASE_ENV_SHA256
    ):
        fail("production environment differs from the independently reviewed identity")
    primary_identity = (
        payload["primary_env_mode"],
        payload["primary_env_uid"],
        payload["primary_env_gid"],
    )
    if any(
        isinstance(value, bool) or not isinstance(value, int)
        for value in primary_identity
    ) or primary_identity != (0o600, 1000, 1001):
        fail("primary environment baseline identity changed")
    legacy_identity = (
        payload["legacy_release_commit_mode"],
        payload["legacy_release_commit_uid"],
        payload["legacy_release_commit_gid"],
    )
    if (
        payload["legacy_release_commit_sha256"] not in LEGACY_PRODUCTION_COMMIT_HASHES
        or any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in legacy_identity
        )
        or legacy_identity != (0o600, 1000, 1001)
    ):
        fail("legacy release marker baseline identity changed")
    services = sorted((*INFRA_SERVICES, *APP_SERVICES))
    if payload["running_services"] != services:
        fail("production service topology changed")
    restart_counts = payload["restart_counts"]
    if (
        not isinstance(restart_counts, dict)
        or set(restart_counts) != set(services)
        or any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in restart_counts.values()
        )
        or any(value != 0 for value in restart_counts.values())
    ):
        fail("production restart counts changed")
    effects = payload["effect_counts"]
    if (
        not isinstance(effects, dict)
        or set(effects) != EFFECT_COUNT_KEYS
        or any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0
            for value in effects.values()
        )
        or effects["copy_provider_unavailable_terminal"] < 18
        or any(
            effects[key] != expected for key, expected in EXACT_EFFECT_COUNTS.items()
        )
        or any(
            effects[key] != 0
            for key in (
                "claimable_copy_jobs",
                "running_copy_jobs",
                "current_business_date_copy_jobs",
                "future_copy_jobs",
                "pending_wecom_jobs",
                "pending_weekly_runs",
                "pending_official_account_runs",
                "pending_wechat_draft_jobs",
            )
        )
    ):
        fail("production effect counters and claimable-work gates changed")
    baseline_manifest(payload["source_manifest"])
    return payload


def descriptor_blob(
    blobs: dict[str, tuple[str, int, bytes | None]],
    descriptor: object,
    media_type: str,
    label: str,
) -> tuple[str, bytes | None]:
    if not isinstance(descriptor, dict) or set(descriptor) - {
        "annotations",
        "digest",
        "mediaType",
        "platform",
        "size",
    }:
        fail(f"{label} descriptor keys changed")
    raw_digest = descriptor.get("digest")
    size = descriptor.get("size")
    if (
        descriptor.get("mediaType") != media_type
        or not isinstance(raw_digest, str)
        or not raw_digest.startswith("sha256:")
        or SHA256.fullmatch(raw_digest.removeprefix("sha256:")) is None
        or isinstance(size, bool)
        or not isinstance(size, int)
        or size < 0
    ):
        fail(f"{label} descriptor identity changed")
    name = f"blobs/sha256/{raw_digest.removeprefix('sha256:')}"
    record = blobs.get(name)
    if record is None or record[0] != raw_digest[7:] or record[1] != size:
        fail(f"{label} descriptor bytes changed")
    return raw_digest, record[2]


def json_record(value: bytes | None, label: str) -> Any:
    if value is None:
        fail(f"{label} exceeds the JSON size bound")
    return strict_json(value, label)


def _legacy_archive_records(
    archive_path: Path,
) -> dict[str, tuple[str, int, bytes | None]]:
    if (
        not archive_path.is_absolute()
        or archive_path.is_symlink()
        or has_symlink_component(archive_path)
        or not archive_path.is_file()
    ):
        fail("legacy OCI input must be a physical absolute file")
    records: dict[str, tuple[str, int, bytes | None]] = {}
    seen: set[str] = set()
    total = 0
    try:
        with tarfile.open(archive_path, "r:") as archive:
            for member in archive:
                name = safe_path(member.name)
                if name in seen:
                    fail("legacy OCI archive contains duplicate members")
                seen.add(name)
                if member.isdir():
                    if (
                        name not in {"blobs", "blobs/sha256"}
                        or stat.S_IMODE(member.mode) != 0o755
                        or member.uid != 0
                        or member.gid != 0
                    ):
                        fail("legacy OCI archive directory changed")
                    continue
                if (
                    not member.isfile()
                    or member.issym()
                    or member.islnk()
                    or stat.S_IMODE(member.mode) not in {0o444, 0o644}
                    or member.uid != 0
                    or member.gid != 0
                    or (
                        name not in {"oci-layout", "index.json"}
                        and re.fullmatch(r"blobs/sha256/[0-9a-f]{64}", name) is None
                    )
                ):
                    fail("legacy OCI archive member is unsafe")
                total += member.size
                if member.size < 0 or total > MAX_ARCHIVE_TOTAL:
                    fail("legacy OCI archive exceeds its bound")
                stream = archive.extractfile(member)
                if stream is None:
                    fail("legacy OCI archive member is unreadable")
                value = hashlib.sha256()
                captured = (
                    bytearray()
                    if name in {"oci-layout", "index.json"} and member.size <= MAX_JSON
                    else None
                )
                while chunk := stream.read(1024 * 1024):
                    value.update(chunk)
                    if captured is not None:
                        captured.extend(chunk)
                digest = value.hexdigest()
                if (
                    name.startswith("blobs/sha256/")
                    and name.rsplit("/", 1)[1] != digest
                ):
                    fail("legacy OCI blob filename differs from its bytes")
                records[name] = (
                    digest,
                    member.size,
                    bytes(captured) if captured is not None else None,
                )
    except (OSError, tarfile.TarError) as exc:
        raise ValueError("legacy OCI archive is unreadable") from exc
    if seen != {*records, "blobs", "blobs/sha256"}:
        fail("legacy OCI archive directory graph is incomplete")
    return records


def _read_legacy_archive_member(
    archive_path: Path, name: str, *, maximum: int = MAX_JSON
) -> bytes:
    try:
        with tarfile.open(archive_path, "r:") as archive:
            member = archive.getmember(name)
            if not member.isfile() or member.size > maximum:
                fail("legacy OCI JSON member exceeds its bound")
            stream = archive.extractfile(member)
            if stream is None:
                fail("legacy OCI JSON member is unreadable")
            value = stream.read(maximum + 1)
    except (KeyError, OSError, tarfile.TarError) as exc:
        raise ValueError("legacy OCI JSON member is missing") from exc
    if len(value) != member.size:
        fail("legacy OCI JSON member size changed")
    return value


def _write_canonical_oci_archive(
    source: Path,
    output: Path,
    values: dict[str, bytes | None],
) -> None:
    parent = output.parent.resolve(strict=True)
    if (
        not output.is_absolute()
        or output.exists()
        or output.is_symlink()
        or has_symlink_component(output.parent)
        or not parent.is_dir()
        or parent != output.parent
    ):
        fail("canonical OCI output must be an absent path in a physical directory")
    descriptor, temporary_name = tempfile.mkstemp(
        dir=parent, prefix=".substantive-release-oci.", suffix=".tmp"
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with (
            os.fdopen(descriptor, "wb") as raw_output,
            tarfile.open(source, "r:") as incoming,
            tarfile.open(
                fileobj=raw_output, mode="w|", format=tarfile.PAX_FORMAT
            ) as outgoing,
        ):
            for directory in ("blobs", "blobs/sha256"):
                info = tarfile.TarInfo(directory + "/")
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                info.uid = 0
                info.gid = 0
                info.mtime = 0
                outgoing.addfile(info)
            for name in sorted(values):
                value = values[name]
                info = tarfile.TarInfo(name)
                info.type = tarfile.REGTYPE
                info.mode = 0o644
                info.uid = 0
                info.gid = 0
                info.mtime = 0
                if value is not None:
                    info.size = len(value)
                    outgoing.addfile(info, BytesIO(value))
                    continue
                original = incoming.getmember(name)
                stream = incoming.extractfile(original)
                if stream is None:
                    fail("legacy OCI content blob is unreadable")
                info.size = original.size
                outgoing.addfile(info, stream)
            raw_output.flush()
            os.fsync(raw_output.fileno())
        os.link(temporary, output)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    temporary.unlink()


def canonicalize_legacy_oci_archive(
    source: Path, output: Path, transport_tag: str
) -> str:
    """Convert one containerd legacy-export graph into the strict release OCI shape."""

    source = source.absolute()
    output = output.absolute()
    normalized_reference = normalize_containerd_reference(transport_tag)
    short_reference = transport_tag.rsplit(":", 1)[1]
    records = _legacy_archive_records(source)
    if set(records) < {"oci-layout", "index.json"}:
        fail("legacy OCI archive root is incomplete")
    layout = json_record(records["oci-layout"][2], "legacy OCI layout")
    index = json_record(records["index.json"][2], "legacy OCI index")
    if layout != {"imageLayoutVersion": "1.0.0"}:
        fail("legacy OCI layout version changed")
    if not isinstance(index, dict) or set(index) != {
        "schemaVersion",
        "mediaType",
        "manifests",
    }:
        fail("legacy OCI index keys changed")
    manifests = index["manifests"]
    if (
        index["schemaVersion"] != 2
        or index["mediaType"] != OCI_LAYOUT_MEDIA_TYPE
        or not isinstance(manifests, list)
        or len(manifests) != 1
        or not isinstance(manifests[0], dict)
    ):
        fail("legacy OCI index must bind one manifest")
    index_descriptor = manifests[0]
    if (
        set(index_descriptor)
        not in (
            {"annotations", "digest", "mediaType", "size"},
            {"annotations", "digest", "mediaType", "platform", "size"},
        )
        or index_descriptor.get("platform") is not None
    ):
        fail("legacy OCI manifest descriptor changed")
    if index_descriptor.get("annotations") != {
        "io.containerd.image.name": normalized_reference,
        "org.opencontainers.image.ref.name": short_reference,
    }:
        fail("legacy OCI transport annotations changed")
    original_manifest_digest, _ = descriptor_blob(
        records,
        index_descriptor,
        OCI_MANIFEST_MEDIA_TYPE,
        "legacy OCI manifest",
    )
    original_manifest_name = f"blobs/sha256/{original_manifest_digest[7:]}"
    manifest = json_record(
        _read_legacy_archive_member(source, original_manifest_name),
        "legacy OCI manifest",
    )
    if not isinstance(manifest, dict) or set(manifest) != {
        "schemaVersion",
        "mediaType",
        "config",
        "layers",
    }:
        fail("legacy OCI manifest keys changed")
    layers = manifest["layers"]
    if (
        manifest["schemaVersion"] != 2
        or manifest["mediaType"] != OCI_MANIFEST_MEDIA_TYPE
        or not isinstance(layers, list)
        or not layers
    ):
        fail("legacy OCI manifest graph changed")
    config_descriptor = manifest["config"]
    if not isinstance(config_descriptor, dict) or set(config_descriptor) != {
        "digest",
        "mediaType",
        "size",
    }:
        fail("legacy OCI config descriptor changed")
    config_digest, _ = descriptor_blob(
        records,
        config_descriptor,
        OCI_CONFIG_MEDIA_TYPE,
        "legacy OCI config",
    )
    canonical_layers: list[dict[str, object]] = []
    layer_names: list[tuple[str, bool]] = []
    layer_digests: list[str] = []
    for index_value, descriptor in enumerate(layers):
        if not isinstance(descriptor, dict) or set(descriptor) != {
            "digest",
            "mediaType",
            "size",
        }:
            fail("legacy OCI layer descriptor changed")
        raw_media_type = descriptor["mediaType"]
        mapping = OCI_LAYER_MEDIA_TYPES.get(raw_media_type)
        if mapping is None:
            fail("legacy OCI layer media type changed")
        canonical_media_type, compressed = mapping
        layer_digest, _ = descriptor_blob(
            records,
            descriptor,
            raw_media_type,
            f"legacy OCI layer {index_value}",
        )
        if layer_digest in layer_digests:
            fail("legacy OCI layer descriptors contain duplicates")
        layer_digests.append(layer_digest)
        layer_names.append((f"blobs/sha256/{layer_digest[7:]}", compressed))
        canonical_layers.append(
            {
                "digest": layer_digest,
                "mediaType": canonical_media_type,
                "size": descriptor["size"],
            }
        )
    config_name = f"blobs/sha256/{config_digest[7:]}"
    config = json_record(
        _read_legacy_archive_member(source, config_name), "legacy OCI config"
    )
    diff_ids = layer_diff_ids(source, layer_names)
    rootfs = config.get("rootfs") if isinstance(config, dict) else None
    runtime = config.get("config") if isinstance(config, dict) else None
    if (
        not isinstance(config, dict)
        or config.get("architecture") != "amd64"
        or config.get("os") != "linux"
        or not isinstance(runtime, dict)
        or runtime.get("User") != "app"
        or not isinstance(rootfs, dict)
        or rootfs.get("type") != "layers"
        or rootfs.get("diff_ids") != diff_ids
    ):
        fail("legacy OCI config platform, user, or diff-ID graph changed")
    referenced = {
        "oci-layout",
        "index.json",
        original_manifest_name,
        config_name,
        *(name for name, _ in layer_names),
    }
    if set(records) != referenced:
        fail("legacy OCI archive contains dangling or missing blobs")

    canonical_manifest = canonical_json_bytes(
        {
            "config": {
                "digest": config_digest,
                "mediaType": OCI_CONFIG_MEDIA_TYPE,
                "size": config_descriptor["size"],
            },
            "layers": canonical_layers,
            "mediaType": OCI_MANIFEST_MEDIA_TYPE,
            "schemaVersion": 2,
        }
    )
    canonical_manifest_digest = f"sha256:{digest_bytes(canonical_manifest)}"
    canonical_manifest_name = f"blobs/sha256/{canonical_manifest_digest[7:]}"
    # Keep the OCI reference conventions emitted by containerd: Docker uses the
    # normalized name to create the tag, while ref.name is the short tag.  A
    # full, unnormalized value in both fields can make `docker image load`
    # return success without attaching the archive graph to the requested tag.
    canonical_index = canonical_json_bytes(
        {
            "manifests": [
                {
                    "annotations": {
                        "io.containerd.image.name": normalized_reference,
                        "org.opencontainers.image.ref.name": short_reference,
                    },
                    "digest": canonical_manifest_digest,
                    "mediaType": OCI_MANIFEST_MEDIA_TYPE,
                    "platform": {"architecture": "amd64", "os": "linux"},
                    "size": len(canonical_manifest),
                }
            ],
            "mediaType": OCI_LAYOUT_MEDIA_TYPE,
            "schemaVersion": 2,
        }
    )
    values: dict[str, bytes | None] = {
        "oci-layout": canonical_json_bytes({"imageLayoutVersion": "1.0.0"}),
        "index.json": canonical_index,
        canonical_manifest_name: canonical_manifest,
        config_name: None,
        **{name: None for name, _ in layer_names},
    }
    if len(values) != 4 + len(layer_names):
        fail("canonical OCI graph contains a digest collision")
    _write_canonical_oci_archive(source, output, values)
    return canonical_manifest_digest


def layer_diff_ids(archive_path: Path, layers: list[tuple[str, bool]]) -> list[str]:
    expected = dict(layers)
    if len(expected) != len(layers):
        fail("OCI layer descriptors contain duplicates")
    observed: dict[str, str] = {}
    try:
        with tarfile.open(archive_path, "r:*") as archive:
            for member in archive:
                name = safe_path(member.name)
                if name not in expected or not member.isfile():
                    continue
                stream = archive.extractfile(member)
                if stream is None:
                    fail("OCI layer is unreadable")
                reader = gzip.GzipFile(fileobj=stream) if expected[name] else stream
                value = hashlib.sha256()
                while chunk := reader.read(1024 * 1024):
                    value.update(chunk)
                observed[name] = f"sha256:{value.hexdigest()}"
    except (EOFError, gzip.BadGzipFile, OSError, tarfile.TarError) as exc:
        raise ValueError("OCI layer compression is invalid") from exc
    if set(observed) != set(expected):
        fail("OCI layer graph is incomplete")
    return [observed[name] for name, _ in layers]


def validate_image_archive(stage: Path, metadata: dict[str, object]) -> str:
    archive_path = stage / "backend-image.oci.tar.gz"
    blobs: dict[str, tuple[str, int, bytes | None]] = {}
    total = 0
    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            for member in archive:
                name = safe_path(member.name)
                if member.isdir():
                    if stat.S_IMODE(member.mode) not in {0o755, 0o775}:
                        fail("OCI archive directory mode changed")
                    continue
                if (
                    not member.isfile()
                    or member.issym()
                    or member.islnk()
                    or name in blobs
                ):
                    fail("OCI archive member is unsafe")
                total += member.size
                if member.size < 0 or total > MAX_ARCHIVE_TOTAL:
                    fail("OCI archive exceeds its bound")
                stream = archive.extractfile(member)
                if stream is None:
                    fail("OCI archive member is unreadable")
                value = hashlib.sha256()
                captured = bytearray() if member.size <= MAX_JSON else None
                while chunk := stream.read(1024 * 1024):
                    value.update(chunk)
                    if captured is not None:
                        captured.extend(chunk)
                blobs[name] = (
                    value.hexdigest(),
                    member.size,
                    bytes(captured) if captured is not None else None,
                )
    except (OSError, tarfile.TarError) as exc:
        raise ValueError("OCI image archive is unreadable") from exc
    if set(blobs) < {"oci-layout", "index.json"}:
        fail("OCI archive root is incomplete")
    layout = json_record(blobs["oci-layout"][2], "OCI layout")
    index = json_record(blobs["index.json"][2], "OCI index")
    if layout != {"imageLayoutVersion": "1.0.0"}:
        fail("OCI layout version changed")
    if not isinstance(index, dict) or set(index) != {
        "schemaVersion",
        "mediaType",
        "manifests",
    }:
        fail("OCI index keys changed")
    manifests = index["manifests"]
    if (
        index["schemaVersion"] != 2
        or index["mediaType"] != "application/vnd.oci.image.index.v1+json"
        or not isinstance(manifests, list)
        or len(manifests) != 1
    ):
        fail("OCI index must bind one manifest")
    index_descriptor = manifests[0]
    if not isinstance(index_descriptor, dict):
        fail("OCI index descriptor changed")
    annotations = index_descriptor.get("annotations")
    transport_tag = metadata.get("transport_tag")
    if not isinstance(transport_tag, str):
        fail("OCI transport tag identity changed")
    normalized_reference = normalize_containerd_reference(transport_tag)
    short_reference = transport_tag.rsplit(":", 1)[1]
    if annotations != {
        "io.containerd.image.name": normalized_reference,
        "org.opencontainers.image.ref.name": short_reference,
    }:
        fail("OCI transport tag annotation changed")
    if index_descriptor.get("platform") != {"architecture": "amd64", "os": "linux"}:
        fail("OCI manifest platform changed")
    manifest_digest, manifest_bytes = descriptor_blob(
        blobs,
        index_descriptor,
        "application/vnd.oci.image.manifest.v1+json",
        "OCI manifest",
    )
    manifest = json_record(manifest_bytes, "OCI manifest")
    if not isinstance(manifest, dict) or set(manifest) != {
        "schemaVersion",
        "mediaType",
        "config",
        "layers",
    }:
        fail("OCI manifest keys changed")
    if (
        manifest["schemaVersion"] != 2
        or manifest["mediaType"] != "application/vnd.oci.image.manifest.v1+json"
        or not isinstance(manifest["layers"], list)
        or not manifest["layers"]
    ):
        fail("OCI manifest graph changed")
    config_digest, config_bytes = descriptor_blob(
        blobs,
        manifest["config"],
        "application/vnd.oci.image.config.v1+json",
        "OCI config",
    )
    layer_digests: list[str] = []
    layer_names: list[tuple[str, bool]] = []
    for index_value, descriptor in enumerate(manifest["layers"]):
        media_type = descriptor.get("mediaType") if isinstance(descriptor, dict) else ""
        if media_type not in {
            "application/vnd.oci.image.layer.v1.tar",
            "application/vnd.oci.image.layer.v1.tar+gzip",
        }:
            fail("OCI layer media type changed")
        layer_digest, _ = descriptor_blob(
            blobs, descriptor, media_type, f"OCI layer {index_value}"
        )
        layer_digests.append(layer_digest)
        layer_names.append(
            (
                f"blobs/sha256/{layer_digest[7:]}",
                media_type.endswith("+gzip"),
            )
        )
    diff_ids = layer_diff_ids(archive_path, layer_names)
    config = json_record(config_bytes, "OCI config")
    runtime = config.get("config") if isinstance(config, dict) else None
    labels = runtime.get("Labels") if isinstance(runtime, dict) else None
    rootfs = config.get("rootfs") if isinstance(config, dict) else None
    if (
        not isinstance(config, dict)
        or config.get("architecture") != "amd64"
        or config.get("os") != "linux"
        or not isinstance(runtime, dict)
        or runtime.get("User") != "app"
        or not isinstance(labels, dict)
        or labels.get("org.opencontainers.image.revision") != metadata["release_commit"]
        or not isinstance(rootfs, dict)
        or rootfs.get("type") != "layers"
        or rootfs.get("diff_ids") != diff_ids
    ):
        fail("OCI config platform, identity, or diff-ID graph changed")
    referenced = {
        "oci-layout",
        "index.json",
        f"blobs/sha256/{manifest_digest[7:]}",
        f"blobs/sha256/{config_digest[7:]}",
        *(f"blobs/sha256/{value[7:]}" for value in layer_digests),
    }
    if set(blobs) != referenced:
        fail("OCI archive contains dangling or missing blobs")
    if metadata["candidate_config_digest"] != config_digest:
        fail("candidate config digest binding changed")
    expected_reference = f"{metadata['candidate_repository']}@{manifest_digest}"
    if metadata["candidate_reference"] != expected_reference:
        fail("candidate repository digest binding changed")
    return manifest_digest


def validate_image_source(path: Path, expected: dict[str, str]) -> None:
    rows: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9._/-]+)", line)
        if match is None:
            fail("image source manifest is malformed")
        name = safe_path(match.group(2))
        if name in rows:
            fail("image source manifest contains duplicates")
        rows[name] = match.group(1)
    if list(rows) != sorted(rows):
        fail("image source manifest is unsorted")
    if rows != expected:
        fail("image source manifest differs from the complete source projection")


def validate_release_window(
    cutoff_text: str, baseline: dict[str, object], *, now: datetime | None = None
) -> None:
    from zoneinfo import ZoneInfo

    now = datetime.now(UTC) if now is None else now
    if now.tzinfo is None or cutoff_text != EARLIEST_PRODUCER_UTC:
        fail("release cutoff differs from the reviewed earliest producer")
    cutoff = datetime.strptime(cutoff_text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    captured = datetime.strptime(
        str(baseline["captured_at_utc"]), "%Y-%m-%dT%H:%M:%SZ"
    ).replace(tzinfo=UTC)
    if (
        now + timedelta(minutes=15) >= cutoff
        or now.astimezone(ZoneInfo("Asia/Shanghai")).date().isoformat()
        != baseline["business_date"]
        or not timedelta(seconds=-30) <= now - captured <= timedelta(hours=1)
    ):
        fail(
            "release baseline is stale, business date rolled over, or producer margin expired"
        )


def validate_runtime_settings(
    rows: object,
    scoring_version: str,
    cutoff_text: str,
    *,
    now: datetime | None = None,
    service: str = "content-worker",
) -> None:
    from zoneinfo import ZoneInfo

    if scoring_version not in {OLD_SCORING_VERSION, NEW_SCORING_VERSION}:
        fail("runtime scoring expectation is outside this transaction")
    if service not in APP_SERVICES:
        fail("runtime service is outside the reviewed topology")
    if not isinstance(rows, list) or not all(
        isinstance(row, str) and "=" in row for row in rows
    ):
        fail("runtime environment projection is malformed")
    environment: dict[str, str] = {}
    for row in rows:
        key, value = row.split("=", 1)
        if key in environment:
            fail("runtime environment has duplicate keys")
        environment[key] = value
    expected = {
        "CONTENT_SCORING_VERSION": scoring_version,
        "CONTENT_SELECTION_PRIORITY_RULE_VERSION": PRIORITY_RULE_VERSION,
        "BUSINESS_TIMEZONE": "Asia/Shanghai",
        "CONTENT_SLOT_MODE_ENABLED": "true",
        "CONTENT_MORNING_ENABLED": "true",
        "CONTENT_NOON_ENABLED": "true",
        "CONTENT_EVENING_ENABLED": "true",
        "CONTENT_MORNING_TARGET_HOUR": "7",
        "CONTENT_MORNING_TARGET_MINUTE": "30",
        "CONTENT_NOON_TARGET_HOUR": "12",
        "CONTENT_NOON_TARGET_MINUTE": "30",
        "CONTENT_EVENING_TARGET_HOUR": "18",
        "CONTENT_EVENING_TARGET_MINUTE": "30",
        "CONTENT_SLOT_PREPARE_LEAD_MINUTES": "90",
        "CONTENT_SLOT_DELIVERY_LATE_MINUTES": "60",
    }
    if service == "official-account-weekly-scheduler":
        expected.update(
            {
                "OFFICIAL_ACCOUNT_WEEKLY_PRODUCTION_ENABLED": "true",
                "OFFICIAL_ACCOUNT_WEEKLY_SCHEDULER_ENABLED": "true",
                "OFFICIAL_ACCOUNT_WEEKLY_MIN_WEEK_START": "2026-09-07",
                "OFFICIAL_ACCOUNT_WEEKLY_RECONCILE_SECONDS": "300",
            }
        )
    if any(environment.get(key) != value for key, value in expected.items()):
        fail(
            "runtime scoring or actual slot schedule differs from the approved projection"
        )
    now = datetime.now(UTC) if now is None else now
    if now.tzinfo is None:
        fail("runtime verification needs an aware clock")
    local_now = now.astimezone(ZoneInfo("Asia/Shanghai"))
    future: list[datetime] = []
    for day_offset in (0, 1):
        business_date = local_now.date() + timedelta(days=day_offset)
        for slot in ("MORNING", "NOON", "EVENING"):
            target = datetime.combine(
                business_date, datetime.min.time(), tzinfo=local_now.tzinfo
            ).replace(
                hour=int(environment[f"CONTENT_{slot}_TARGET_HOUR"]),
                minute=int(environment[f"CONTENT_{slot}_TARGET_MINUTE"]),
            )
            preparation = target - timedelta(
                minutes=int(environment["CONTENT_SLOT_PREPARE_LEAD_MINUTES"])
            )
            expiry = target + timedelta(
                minutes=int(environment["CONTENT_SLOT_DELIVERY_LATE_MINUTES"])
            )
            if preparation <= local_now <= expiry:
                fail("runtime is inside a natural preparation or delivery window")
            if preparation > local_now:
                future.append(preparation)
    actual = min(future).astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    if actual != cutoff_text or cutoff_text != EARLIEST_PRODUCER_UTC:
        fail("operator cutoff is not the actual next slot producer")
    if service == "official-account-weekly-scheduler":
        weekly_start = datetime(2026, 9, 7, 9, tzinfo=ZoneInfo("Asia/Shanghai"))
        if local_now >= weekly_start or min(future) >= weekly_start:
            fail("weekly production is due or precedes the bound slot cutoff")


def validate_weekly_schedule(payload: object) -> None:
    if payload != {
        "policy_version": "official-account-weekly-schedule-v1",
        "timezone": "Asia/Shanghai",
        "weekday": 0,
        "target_time": "09:00",
        "catchup_hours": 24,
        "unit": "one_weekly_batch_with_three_independent_articles",
    }:
        fail("actual weekly scheduler domain contract differs from the reviewed source")


def validate_metadata(path: Path) -> dict[str, object]:
    payload = strict_json(path.read_bytes(), "release metadata")
    keys = {
        "schema_version",
        "production_commit",
        "release_ref",
        "release_commit",
        "main_policy_commit",
        "main_tooling_commit",
        "alembic_head",
        "scheduler_cutoff_utc",
        "candidate_repository",
        "transport_tag",
        "candidate_reference",
        "candidate_config_digest",
        "source_sha256",
        "source_manifest_sha256",
        "image_archive_sha256",
        "image_source_sha256",
        "runtime_diff_sha256",
        "audit_diff_sha256",
        "production_baseline_sha256",
        "builder_sha256",
        "capture_sha256",
        "operator_sha256",
        "validator_sha256",
        "app_services",
        "service_commands",
    }
    if not isinstance(payload, dict) or set(payload) != keys:
        fail("release metadata keys changed")
    if (
        payload["schema_version"] != SCHEMA_VERSION
        or payload["production_commit"] != PRODUCTION_COMMIT
        or payload["release_ref"] != RELEASE_REF
        or payload["alembic_head"] != ALEMBIC_HEAD
        or not isinstance(payload["release_commit"], str)
        or COMMIT.fullmatch(payload["release_commit"]) is None
        or payload["release_commit"] == PRODUCTION_COMMIT
        or not isinstance(payload["main_policy_commit"], str)
        or COMMIT.fullmatch(payload["main_policy_commit"]) is None
        or not isinstance(payload["main_tooling_commit"], str)
        or COMMIT.fullmatch(payload["main_tooling_commit"]) is None
        or not isinstance(payload["scheduler_cutoff_utc"], str)
        or TIMESTAMP.fullmatch(payload["scheduler_cutoff_utc"]) is None
        or payload["scheduler_cutoff_utc"] != EARLIEST_PRODUCER_UTC
        or not isinstance(payload["candidate_repository"], str)
        or REPOSITORY.fullmatch(payload["candidate_repository"]) is None
        or not isinstance(payload["candidate_reference"], str)
        or IMAGE_REFERENCE.fullmatch(payload["candidate_reference"]) is None
        or not isinstance(payload["candidate_config_digest"], str)
        or IMAGE_ID.fullmatch(payload["candidate_config_digest"]) is None
    ):
        fail("release metadata identity changed")
    expected_tag = (
        f"{payload['candidate_repository']}:substantive-release-"
        f"{str(payload['release_commit'])[:12]}"
    )
    if payload["transport_tag"] != expected_tag:
        fail("transport tag is not bound to the release")
    for key in (
        "source_sha256",
        "source_manifest_sha256",
        "image_archive_sha256",
        "image_source_sha256",
        "runtime_diff_sha256",
        "audit_diff_sha256",
        "production_baseline_sha256",
        "builder_sha256",
        "capture_sha256",
        "operator_sha256",
        "validator_sha256",
    ):
        if not isinstance(payload[key], str) or SHA256.fullmatch(payload[key]) is None:
            fail("release metadata checksum changed")
    if payload["app_services"] != list(APP_SERVICES) or payload["service_commands"] != {
        name: list(command) for name, command in SERVICE_COMMANDS.items()
    }:
        fail("release service/entrypoint contract changed")
    return payload


def validate_stage(raw_stage: Path) -> dict[str, object]:
    stage = raw_stage.resolve(strict=True)
    metadata = stage.stat()
    if (
        not stage.is_dir()
        or has_symlink_component(raw_stage.absolute())
        or stat.S_IMODE(metadata.st_mode) != 0o700
        or metadata.st_uid != 0
        or metadata.st_gid != 0
    ):
        fail("stage must be a physical root-owned mode-0700 directory")
    entries = list(stage.iterdir())
    if {entry.name for entry in entries} != MEMBERS or any(
        not entry.is_file()
        or entry.is_symlink()
        or stat.S_IMODE(entry.stat().st_mode) != 0o600
        or entry.stat().st_uid != 0
        or entry.stat().st_gid != 0
        or entry.stat().st_size > MAX_STAGE_MEMBER
        for entry in entries
    ):
        fail("stage member set, type, owner, or mode changed")
    rows = checksum_rows(stage / "artifacts.sha256")
    if any(digest_file(stage / name) != checksum for name, checksum in rows.items()):
        fail("artifact checksum binding changed")
    payload = validate_metadata(stage / "release-metadata.json")
    baseline = validate_baseline(stage / "production-baseline.json")
    diff_rows(stage / "runtime-diff.tsv", runtime=True)
    diff_rows(stage / "audit-diff.tsv", runtime=False)
    validate_candidate_source_compatibility(
        source_manifest(stage / "source-manifest.tsv"),
        baseline_manifest(baseline["source_manifest"]),
    )
    expected_image_source = validate_source_archive(stage)
    validate_image_source(stage / "image-source.sha256", expected_image_source)
    validate_image_archive(stage, payload)
    bindings = {
        "source_sha256": "source.tar.gz",
        "source_manifest_sha256": "source-manifest.tsv",
        "image_archive_sha256": "backend-image.oci.tar.gz",
        "image_source_sha256": "image-source.sha256",
        "runtime_diff_sha256": "runtime-diff.tsv",
        "audit_diff_sha256": "audit-diff.tsv",
        "production_baseline_sha256": "production-baseline.json",
        "builder_sha256": "build-substantive-release.sh",
        "capture_sha256": "capture-substantive-production-baseline.sh",
        "operator_sha256": "substantive-release-operator.sh",
        "validator_sha256": "validate-substantive-release.py",
    }
    if any(payload[key] != digest_file(stage / name) for key, name in bindings.items()):
        fail("release metadata file binding changed")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", type=Path, nargs="?")
    parser.add_argument("--normalize-containerd-reference")
    parser.add_argument(
        "--canonicalize-legacy-oci",
        nargs=3,
        metavar=("SOURCE", "OUTPUT", "TRANSPORT_TAG"),
    )
    parser.add_argument("--environment-plan", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--window", nargs=2, metavar=("CUTOFF", "BASELINE"))
    parser.add_argument(
        "--runtime-settings", nargs=3, metavar=("SCORING_VERSION", "CUTOFF", "SERVICE")
    )
    parser.add_argument("--weekly-schedule", action="store_const", const=True)
    parser.add_argument(
        "--activate-environment",
        nargs=3,
        metavar=("SOURCE", "TARGET", "EXPECTED_CANDIDATE_SHA256"),
    )
    parser.add_argument(
        "--restore-environment",
        nargs=3,
        metavar=("SOURCE", "TARGET", "EXPECTED_CANDIDATE_SHA256"),
    )
    args = parser.parse_args()
    try:
        selected = sum(
            value is not None
            for value in (
                args.stage,
                args.normalize_containerd_reference,
                args.canonicalize_legacy_oci,
                args.environment_plan,
                args.baseline,
                args.window,
                args.runtime_settings,
                args.weekly_schedule,
                args.activate_environment,
                args.restore_environment,
            )
        )
        if selected != 1:
            fail("select exactly one validation operation")
        if args.normalize_containerd_reference is not None:
            print(normalize_containerd_reference(args.normalize_containerd_reference))
            return 0
        if args.canonicalize_legacy_oci is not None:
            source, output, transport_tag = args.canonicalize_legacy_oci
            digest = canonicalize_legacy_oci_archive(
                Path(source), Path(output), transport_tag
            )
            print(f"substantive_release_oci_canonicalized manifest_digest={digest}")
            return 0
        if args.environment_plan is not None:
            previous, candidate = environment_plan(args.environment_plan)
            print(f"{previous}:{candidate}")
            return 0
        if args.baseline is not None:
            validate_baseline(args.baseline)
            print("substantive_release_baseline_valid")
            return 0
        if args.window is not None:
            cutoff, baseline_path = args.window
            validate_release_window(cutoff, validate_baseline(Path(baseline_path)))
            print("substantive_release_window_valid")
            return 0
        if args.runtime_settings is not None:
            raw = sys.stdin.buffer.read(MAX_JSON + 1)
            if len(raw) > MAX_JSON:
                fail("runtime environment projection exceeds the byte bound")
            scoring_version, cutoff, service = args.runtime_settings
            validate_runtime_settings(
                strict_json(raw, "runtime environment"),
                scoring_version,
                cutoff,
                service=service,
            )
            print("substantive_release_runtime_settings_valid")
            return 0
        if args.weekly_schedule is not None:
            raw = sys.stdin.buffer.read(4097)
            if len(raw) > 4096:
                fail("weekly schedule projection exceeds the byte bound")
            validate_weekly_schedule(strict_json(raw, "weekly schedule"))
            print("substantive_release_weekly_schedule_valid")
            return 0
        if args.activate_environment is not None:
            source, target, expected = args.activate_environment
            activate_candidate_environment(Path(source), Path(target), expected)
            print("substantive_release_environment_activated")
            return 0
        if args.restore_environment is not None:
            source, target, expected = args.restore_environment
            restore_production_environment(Path(source), Path(target), expected)
            print("substantive_release_environment_restored")
            return 0
        if args.stage is None:
            fail("stage is required")
        payload = validate_stage(args.stage)
    except (OSError, ValueError) as exc:
        print(f"substantive_release_validation_failed reason={exc}")
        return 1
    print(
        "substantive_release_validation_ok "
        f"release_commit={payload['release_commit']} "
        f"candidate_reference={payload['candidate_reference']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
