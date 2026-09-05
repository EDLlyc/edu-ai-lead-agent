from __future__ import annotations

import gzip
import hashlib
import importlib.util
import io
import json
import os
import subprocess
import tarfile
from pathlib import Path
from types import ModuleType

import pytest

RESEARCH = Path(__file__).resolve().parent
REPOSITORY_ROOT = RESEARCH.parents[3]
VALIDATOR_PATH = RESEARCH / "validate-brand-embedding-hotfix-offline-artifacts.py"
OPERATOR_PATH = RESEARCH / "brand-embedding-hotfix-offline-release-operator.sh"
BUILDER_PATH = RESEARCH / "build-brand-embedding-hotfix-offline-artifacts.sh"
CAPTURE_PATH = RESEARCH / "capture-brand-embedding-production-baseline.sh"
RELEASE_COMMIT = "e" * 40
EXACT_RELEASE_SOURCE_COMMIT = "dfd6703637062ce07d52f848d9bb82a68250f474"
REPOSITORY = "registry.example.test/edu-ai/edu-ai-lead-agent"
SOURCE_URL = "https://codeup.aliyun.com/601cdb1a841cc46b7c49b115/marketingUseOnly/edu-ai-lead-agent.git"


def _load_validator() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "brand_hotfix_validator", VALIDATOR_PATH
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VALIDATOR = _load_validator()


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode()


def _digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_tar_gz(
    path: Path, entries: list[tuple[str, str, int, bytes | None]]
) -> None:
    with (
        path.open("wb") as output,
        gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0) as zipped,
        tarfile.open(fileobj=zipped, mode="w|") as archive,
    ):
        for name, kind, mode, value in entries:
            info = tarfile.TarInfo(name + ("/" if kind == "d" else ""))
            info.mode = mode
            info.uid = 0
            info.gid = 0
            info.mtime = 0
            if kind == "d":
                info.type = tarfile.DIRTYPE
                archive.addfile(info)
            else:
                assert value is not None
                info.type = tarfile.REGTYPE
                info.size = len(value)
                archive.addfile(info, io.BytesIO(value))


def _source_entries() -> list[tuple[str, str, int, bytes | None]]:
    directories = {
        "backend",
        "backend/alembic",
        "backend/alembic/versions",
        "backend/app",
        "backend/app/core",
        "backend/app/infrastructure",
        "backend/app/infrastructure/ai",
        "deploy",
        "infra",
        "scripts",
    }
    files = {
        ".env.example": b"BRAND_EMBEDDING_PROVIDER_MODE=auto\n",
        ".gitattributes": b"* text=auto\n",
        ".gitignore": b".env\n",
        "AGENTS.md": b"managed\n",
        "Makefile": b"doctor:\n\t@true\n",
        "README.md": b"release\n",
        "environment.yml": b"name: release\n",
        "compose.yaml": b"services: {}\n",
        "backend/alembic.ini": b"[alembic]\n",
        "backend/pyproject.toml": b"[project]\nname='test'\n",
        "backend/alembic/versions/20260901_0042_wechat_mp_draft_jobs.py": b"revision='20260901_0042'\n",
        "backend/app/api_main.py": b"app = object()\n",
        "backend/app/content_worker_main.py": b"async def main(): pass\n",
        "backend/app/core/config.py": b"BRAND = 'zhipu'\n",
        "backend/app/infrastructure/ai/factory.py": b"def create(): return None\n",
        "scripts/doctor.sh": b"#!/usr/bin/env bash\nexit 0\n",
        "scripts/validate_brand_delivery_config.py": b"raise SystemExit(0)\n",
    }
    entries: list[tuple[str, str, int, bytes | None]] = [
        (name, "d", 0o755, None) for name in sorted(directories)
    ]
    entries.extend(
        (name, "f", 0o755 if name == "scripts/doctor.sh" else 0o644, value)
        for name, value in sorted(files.items())
    )
    return sorted(entries)


def _write_source(
    stage: Path,
    entries: list[tuple[str, str, int, bytes | None]] | None = None,
) -> None:
    if entries is None:
        entries = _source_entries()
    _write_tar_gz(stage / "source.tar.gz", entries)
    rows = []
    for name, kind, mode, value in entries:
        checksum = "-" if kind == "d" else _digest(value or b"")
        rows.append(f"{kind}\t{mode:04o}\t{checksum}\t{name}\n")
    (stage / "source-manifest.tsv").write_text("".join(rows), encoding="utf-8")


def _write_image_source(
    stage: Path, entries: list[tuple[str, str, int, bytes | None]]
) -> None:
    rows: list[tuple[str, str]] = []
    for name, kind, _mode, value in entries:
        if kind != "f" or not name.startswith("backend/"):
            continue
        relative = name.removeprefix("backend/")
        relative_path = Path(relative)
        if relative in {"alembic.ini", "pyproject.toml"} or (
            relative_path.suffix in {".py", ".html"}
            and relative_path.parts[0] in {"app", "alembic"}
        ):
            assert value is not None
            rows.append((relative, _digest(value)))
    (stage / "image-source.sha256").write_text(
        "".join(f"{checksum}  {name}\n" for name, checksum in sorted(rows)),
        encoding="utf-8",
    )


def _exact_release_source_entries(
    worktree: Path,
) -> list[tuple[str, str, int, bytes | None]]:
    result = subprocess.run(
        [
            "git",
            "archive",
            "--format=tar",
            EXACT_RELEASE_SOURCE_COMMIT,
            "--",
            "backend",
            "deploy",
            "infra",
            "scripts",
            "compose.yaml",
            ".env.example",
            ".gitattributes",
            ".gitignore",
            "AGENTS.md",
            "Makefile",
            "README.md",
            "environment.yml",
        ],
        cwd=REPOSITORY_ROOT,
        check=False,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr.decode(errors="replace")
    entries: list[tuple[str, str, int, bytes | None]] = []
    with tarfile.open(fileobj=io.BytesIO(result.stdout), mode="r:") as archive:
        for member in archive:
            name = member.name.rstrip("/")
            assert VALIDATOR.safe_path(name) == name
            if member.isdir():
                entries.append((name, "d", 0o755, None))
                continue
            assert member.isfile() and not member.issym() and not member.islnk()
            stream = archive.extractfile(member)
            assert stream is not None
            value = stream.read()
            mode = 0o755 if member.mode & 0o111 else 0o644
            entries.append((name, "f", mode, value))
            if name.startswith("backend/"):
                target = worktree / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(value)
    return sorted(entries)


def _oci_graph() -> tuple[bytes, str, str]:
    layer = gzip.compress(b"one reviewed layer", mtime=0)
    layer_digest = _digest(layer)
    diff_id = _digest(b"one reviewed layer")
    config = _json_bytes(
        {
            "architecture": "amd64",
            "config": {
                "Labels": {"org.opencontainers.image.revision": RELEASE_COMMIT},
                "User": "app",
            },
            "os": "linux",
            "rootfs": {"diff_ids": [f"sha256:{diff_id}"], "type": "layers"},
        }
    )
    config_digest = _digest(config)
    manifest = _json_bytes(
        {
            "config": {
                "digest": f"sha256:{config_digest}",
                "mediaType": "application/vnd.oci.image.config.v1+json",
                "size": len(config),
            },
            "layers": [
                {
                    "digest": f"sha256:{layer_digest}",
                    "mediaType": "application/vnd.oci.image.layer.v1.tar+gzip",
                    "size": len(layer),
                }
            ],
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "schemaVersion": 2,
        }
    )
    manifest_digest = _digest(manifest)
    transport_tag = f"{REPOSITORY}:brand-embedding-{RELEASE_COMMIT[:12]}"
    normalized_reference = VALIDATOR.normalize_containerd_reference(transport_tag)
    short_reference = transport_tag.rsplit(":", 1)[1]
    index = _json_bytes(
        {
            "manifests": [
                {
                    "annotations": {
                        "io.containerd.image.name": normalized_reference,
                        "org.opencontainers.image.ref.name": short_reference,
                    },
                    "digest": f"sha256:{manifest_digest}",
                    "mediaType": "application/vnd.oci.image.manifest.v1+json",
                    "platform": {"architecture": "amd64", "os": "linux"},
                    "size": len(manifest),
                }
            ],
            "mediaType": "application/vnd.oci.image.index.v1+json",
            "schemaVersion": 2,
        }
    )
    output = io.BytesIO()
    with (
        gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0) as zipped,
        tarfile.open(fileobj=zipped, mode="w|") as archive,
    ):
        values = {
            "oci-layout": _json_bytes({"imageLayoutVersion": "1.0.0"}),
            "index.json": index,
            f"blobs/sha256/{manifest_digest}": manifest,
            f"blobs/sha256/{config_digest}": config,
            f"blobs/sha256/{layer_digest}": layer,
        }
        for directory in ("blobs", "blobs/sha256"):
            info = tarfile.TarInfo(directory + "/")
            info.type = tarfile.DIRTYPE
            info.mode = 0o755
            archive.addfile(info)
        for name, value in sorted(values.items()):
            info = tarfile.TarInfo(name)
            info.mode = 0o644
            info.size = len(value)
            archive.addfile(info, io.BytesIO(value))
    return output.getvalue(), f"sha256:{manifest_digest}", f"sha256:{config_digest}"


def _legacy_oci_archive(path: Path, mutation: str = "") -> tuple[str, str]:
    raw_layer = b"one reviewed legacy layer"
    layer = (
        raw_layer if mutation == "uncompressed" else gzip.compress(raw_layer, mtime=0)
    )
    layer_digest = _digest(layer)
    diff_id = _digest(raw_layer)
    config = _json_bytes(
        {
            "architecture": "amd64",
            "config": {
                "Labels": {"org.opencontainers.image.revision": RELEASE_COMMIT},
                "User": "app",
            },
            "os": "linux",
            "rootfs": {"diff_ids": [f"sha256:{diff_id}"], "type": "layers"},
        }
    )
    config_digest = _digest(config)
    manifest = _json_bytes(
        {
            "config": {
                "digest": f"sha256:{config_digest}",
                "mediaType": "application/vnd.oci.image.config.v1+json",
                "size": len(config),
            },
            "layers": [
                {
                    "digest": f"sha256:{layer_digest}",
                    "mediaType": (
                        "application/invalid"
                        if mutation == "malformed"
                        else (
                            "application/vnd.docker.image.rootfs.diff.tar"
                            if mutation == "uncompressed"
                            else "application/vnd.docker.image.rootfs.diff.tar.gzip"
                        )
                    ),
                    "size": len(layer),
                }
            ],
            "mediaType": "application/vnd.oci.image.manifest.v1+json",
            "schemaVersion": 2,
        }
    )
    manifest_digest = _digest(manifest)
    normalized = f"{REPOSITORY}:brand-embedding-{RELEASE_COMMIT[:12]}"
    index = _json_bytes(
        {
            "manifests": [
                {
                    "annotations": {
                        "io.containerd.image.name": normalized,
                        "org.opencontainers.image.ref.name": (
                            f"brand-embedding-{RELEASE_COMMIT[:12]}"
                        ),
                    },
                    "digest": f"sha256:{manifest_digest}",
                    "mediaType": (
                        "application/vnd.oci.image.index.v1+json"
                        if mutation == "nested"
                        else "application/vnd.oci.image.manifest.v1+json"
                    ),
                    "platform": None,
                    "size": len(manifest),
                }
            ],
            "mediaType": "application/vnd.oci.image.index.v1+json",
            "schemaVersion": 2,
        }
    )
    if mutation == "duplicate-json":
        index = index.replace(
            b'"schemaVersion":2}',
            b'"schemaVersion":2,"schemaVersion":2}',
        )
    values = {
        "oci-layout": _json_bytes({"imageLayoutVersion": "1.0.0"}),
        "index.json": index,
        f"blobs/sha256/{manifest_digest}": manifest,
        f"blobs/sha256/{config_digest}": config,
        f"blobs/sha256/{layer_digest}": layer,
    }
    if mutation == "dangling":
        dangling = b"dangling"
        values[f"blobs/sha256/{_digest(dangling)}"] = dangling
    with tarfile.open(path, "w") as archive:
        for directory in ("blobs", "blobs/sha256"):
            info = tarfile.TarInfo(directory)
            info.type = tarfile.DIRTYPE
            info.mode = 0o755
            info.uid = 0
            info.gid = 0
            archive.addfile(info)
        for name, value in sorted(values.items()):
            info = tarfile.TarInfo(name)
            info.mode = 0o644
            info.uid = 0
            info.gid = 0
            info.size = len(value)
            archive.addfile(info, io.BytesIO(value))
        if mutation == "symlink":
            info = tarfile.TarInfo("linked")
            info.type = tarfile.SYMTYPE
            info.linkname = "index.json"
            info.mode = 0o777
            archive.addfile(info)
        elif mutation == "hardlink":
            info = tarfile.TarInfo("linked")
            info.type = tarfile.LNKTYPE
            info.linkname = "index.json"
            info.mode = 0o777
            archive.addfile(info)
        elif mutation == "duplicate":
            info = tarfile.TarInfo("index.json")
            info.mode = 0o644
            info.uid = 0
            info.gid = 0
            info.size = len(index)
            archive.addfile(info, io.BytesIO(index))
        elif mutation == "path":
            info = tarfile.TarInfo("../index.json")
            info.mode = 0o644
            info.uid = 0
            info.gid = 0
            info.size = len(index)
            archive.addfile(info, io.BytesIO(index))
    return f"sha256:{manifest_digest}", f"sha256:{config_digest}"


def _baseline(terminal_count: int = 18) -> dict[str, object]:
    effects = {name: 0 for name in VALIDATOR.EFFECT_COUNT_ORDER}
    effects["copy_provider_unavailable_terminal"] = terminal_count
    services = sorted((*VALIDATOR.INFRA_SERVICES, *VALIDATOR.APP_SERVICES))
    return {
        "schema_version": 1,
        "captured_at_utc": "2026-09-04T05:00:00Z",
        "business_timezone": "Asia/Shanghai",
        "business_date": "2026-09-04",
        "content_max_attempts": 3,
        "frozen_copy_job_count": 7,
        "frozen_copy_job_sha256": "4" * 64,
        "current_commit": VALIDATOR.PRODUCTION_COMMIT,
        "current_alembic_head": VALIDATOR.ALEMBIC_HEAD,
        "current_image_id": "sha256:" + "d" * 64,
        "current_image_reference": f"{REPOSITORY}@sha256:{'c' * 64}",
        "current_image_revision": VALIDATOR.PRODUCTION_COMMIT,
        "primary_env_sha256": "1" * 64,
        "primary_env_mode": 0o600,
        "primary_env_uid": 1000,
        "primary_env_gid": 1001,
        "release_env_sha256": "2" * 64,
        "legacy_release_commit_sha256": _digest(
            VALIDATOR.LEGACY_PRODUCTION_COMMIT + b"\n"
        ),
        "legacy_release_commit_mode": 0o600,
        "legacy_release_commit_uid": 1000,
        "legacy_release_commit_gid": 1001,
        "running_services": services,
        "restart_counts": {name: 0 for name in services},
        "effect_counts": effects,
        "source_manifest": [
            {
                "kind": "f",
                "path": ".gitattributes",
                "mode": 0o600,
                "uid": 0,
                "gid": 0,
                "sha256": "3" * 64,
            }
        ],
    }


def _metadata(
    stage: Path, manifest_digest: str, config_digest: str
) -> dict[str, object]:
    commands = {
        name: list(command) for name, command in VALIDATOR.SERVICE_COMMANDS.items()
    }
    return {
        "schema_version": 1,
        "production_commit": VALIDATOR.PRODUCTION_COMMIT,
        "release_ref": VALIDATOR.RELEASE_REF,
        "release_commit": RELEASE_COMMIT,
        "main_fix_commit": "f" * 40,
        "main_operator_commit": "a" * 40,
        "alembic_head": VALIDATOR.ALEMBIC_HEAD,
        "scheduler_cutoff_utc": "2099-01-01T00:00:00Z",
        "candidate_repository": REPOSITORY,
        "transport_tag": f"{REPOSITORY}:brand-embedding-{RELEASE_COMMIT[:12]}",
        "candidate_reference": f"{REPOSITORY}@{manifest_digest}",
        "candidate_config_digest": config_digest,
        "source_sha256": VALIDATOR.digest_file(stage / "source.tar.gz"),
        "source_manifest_sha256": VALIDATOR.digest_file(stage / "source-manifest.tsv"),
        "image_archive_sha256": VALIDATOR.digest_file(
            stage / "backend-image.oci.tar.gz"
        ),
        "image_source_sha256": VALIDATOR.digest_file(stage / "image-source.sha256"),
        "runtime_diff_sha256": VALIDATOR.digest_file(stage / "runtime-diff.tsv"),
        "audit_diff_sha256": VALIDATOR.digest_file(stage / "audit-diff.tsv"),
        "production_baseline_sha256": VALIDATOR.digest_file(
            stage / "production-baseline.json"
        ),
        "builder_sha256": VALIDATOR.digest_file(stage / BUILDER_PATH.name),
        "capture_sha256": VALIDATOR.digest_file(stage / CAPTURE_PATH.name),
        "operator_sha256": VALIDATOR.digest_file(stage / OPERATOR_PATH.name),
        "validator_sha256": VALIDATOR.digest_file(stage / VALIDATOR_PATH.name),
        "app_services": list(VALIDATOR.APP_SERVICES),
        "service_commands": commands,
    }


def _refresh_artifacts(stage: Path) -> None:
    rows = []
    for name in sorted(VALIDATOR.CHECKSUM_TARGETS):
        rows.append(f"{VALIDATOR.digest_file(stage / name)}  {name}\n")
    (stage / "artifacts.sha256").write_text("".join(rows), encoding="utf-8")
    for name in VALIDATOR.MEMBERS:
        (stage / name).chmod(0o600)


def _rebind(stage: Path, metadata_key: str, filename: str) -> None:
    metadata = json.loads((stage / "release-metadata.json").read_bytes())
    metadata[metadata_key] = VALIDATOR.digest_file(stage / filename)
    (stage / "release-metadata.json").write_bytes(_json_bytes(metadata))
    _refresh_artifacts(stage)


def _stage(tmp_path: Path) -> Path:
    stage = tmp_path / "stage"
    stage.mkdir(mode=0o700, parents=True)
    _write_source(stage)
    image, manifest_digest, config_digest = _oci_graph()
    (stage / "backend-image.oci.tar.gz").write_bytes(image)
    _write_image_source(stage, _source_entries())
    (stage / "runtime-diff.tsv").write_text(
        "".join(
            f"{VALIDATOR.RUNTIME_DIFF[name]}\t{name}\n"
            for name in sorted(VALIDATOR.RUNTIME_DIFF)
        ),
        encoding="utf-8",
    )
    audit_rows = {
        **VALIDATOR.AUDIT_EXACT,
        f"{VALIDATOR.AUDIT_TASK_PREFIX}prd.md": "A",
    }
    (stage / "audit-diff.tsv").write_text(
        "".join(f"{status}\t{name}\n" for name, status in sorted(audit_rows.items())),
        encoding="utf-8",
    )
    (stage / "production-baseline.json").write_bytes(_json_bytes(_baseline()))
    for source in (BUILDER_PATH, CAPTURE_PATH, OPERATOR_PATH, VALIDATOR_PATH):
        (stage / source.name).write_bytes(source.read_bytes())
    metadata = _metadata(stage, manifest_digest, config_digest)
    (stage / "release-metadata.json").write_bytes(_json_bytes(metadata))
    _refresh_artifacts(stage)
    stage.chmod(0o700)
    return stage


def test_valid_stage_binds_distinct_manifest_config_and_repository_digest(
    tmp_path: Path,
) -> None:
    stage = _stage(tmp_path)
    payload = VALIDATOR.validate_stage(stage)
    assert payload["candidate_reference"].startswith(f"{REPOSITORY}@sha256:")
    assert (
        payload["candidate_reference"].rsplit("@", 1)[1]
        != payload["candidate_config_digest"]
    )


def test_stage_rejects_unexpected_python_bytecode_cache(tmp_path: Path) -> None:
    stage = _stage(tmp_path)
    cache = stage / "__pycache__"
    cache.mkdir(mode=0o700)
    bytecode = cache / "validator.cpython-311.pyc"
    bytecode.write_bytes(b"unexpected bytecode")
    bytecode.chmod(0o600)

    with pytest.raises(ValueError, match="stage member set"):
        VALIDATOR.validate_stage(stage)


@pytest.mark.parametrize(
    "name",
    [
        "source.tar.gz",
        "source-manifest.tsv",
        "backend-image.oci.tar.gz",
        "runtime-diff.tsv",
        "production-baseline.json",
        OPERATOR_PATH.name,
    ],
)
def test_stage_rejects_checksum_tamper(tmp_path: Path, name: str) -> None:
    stage = _stage(tmp_path)
    with (stage / name).open("ab") as stream:
        stream.write(b"tamper")
    with pytest.raises(ValueError, match="checksum"):
        VALIDATOR.validate_stage(stage)


def test_runtime_diff_must_be_exact_and_audit_diff_is_bounded(tmp_path: Path) -> None:
    stage = _stage(tmp_path)
    rows = (stage / "runtime-diff.tsv").read_text(encoding="utf-8").splitlines()
    (stage / "runtime-diff.tsv").write_text(
        "\n".join(rows[:-1]) + "\n", encoding="utf-8"
    )
    _rebind(stage, "runtime_diff_sha256", "runtime-diff.tsv")
    with pytest.raises(ValueError, match="runtime diff"):
        VALIDATOR.validate_stage(stage)

    stage = _stage(tmp_path / "audit")
    (stage / "audit-diff.tsv").write_text("M\tfrontend/src/main.ts\n", encoding="utf-8")
    _rebind(stage, "audit_diff_sha256", "audit-diff.tsv")
    with pytest.raises(ValueError, match="audit/test allowlist"):
        VALIDATOR.validate_stage(stage)

    stage = _stage(tmp_path / "missing-audit")
    rows = (stage / "audit-diff.tsv").read_text(encoding="utf-8").splitlines()
    (stage / "audit-diff.tsv").write_text(
        "\n".join(row for row in rows if "quality-guidelines.md" not in row) + "\n",
        encoding="utf-8",
    )
    _rebind(stage, "audit_diff_sha256", "audit-diff.tsv")
    with pytest.raises(ValueError, match="audit/test allowlist"):
        VALIDATOR.validate_stage(stage)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("release_ref", "refs/remotes/origin/main", "identity"),
        ("alembic_head", "20260902_0043", "identity"),
        ("candidate_reference", f"{REPOSITORY}:mutable", "identity"),
    ],
)
def test_release_identity_drift_is_rejected(
    tmp_path: Path, field: str, value: str, message: str
) -> None:
    stage = _stage(tmp_path)
    metadata = json.loads((stage / "release-metadata.json").read_bytes())
    metadata[field] = value
    (stage / "release-metadata.json").write_bytes(_json_bytes(metadata))
    _refresh_artifacts(stage)
    with pytest.raises(ValueError, match=message):
        VALIDATOR.validate_stage(stage)


@pytest.mark.parametrize(
    ("position", "value"),
    [(4, "fixture"), (9, "901"), (11, "3")],
)
def test_production_weekly_command_is_exactly_bound(
    tmp_path: Path, position: int, value: str
) -> None:
    stage = _stage(tmp_path)
    metadata = json.loads((stage / "release-metadata.json").read_bytes())
    metadata["service_commands"]["official-account-weekly-dag-worker"][position] = value
    (stage / "release-metadata.json").write_bytes(_json_bytes(metadata))
    _refresh_artifacts(stage)
    with pytest.raises(ValueError, match="service/entrypoint"):
        VALIDATOR.validate_stage(stage)


def test_terminal_baseline_accepts_more_than_diagnosed_minimum(tmp_path: Path) -> None:
    stage = _stage(tmp_path)
    baseline = _baseline(terminal_count=23)
    (stage / "production-baseline.json").write_bytes(_json_bytes(baseline))
    _rebind(stage, "production_baseline_sha256", "production-baseline.json")
    VALIDATOR.validate_stage(stage)


@pytest.mark.parametrize(
    "key",
    [
        "claimable_copy_jobs",
        "running_copy_jobs",
        "current_business_date_copy_jobs",
        "future_copy_jobs",
    ],
)
def test_copy_claim_gates_must_remain_zero(tmp_path: Path, key: str) -> None:
    stage = _stage(tmp_path)
    baseline = _baseline()
    effects = baseline["effect_counts"]
    assert isinstance(effects, dict)
    effects[key] = 1
    (stage / "production-baseline.json").write_bytes(_json_bytes(baseline))
    _rebind(stage, "production_baseline_sha256", "production-baseline.json")
    with pytest.raises(ValueError, match="effect counters"):
        VALIDATOR.validate_stage(stage)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("schema_bool", "identity"),
        ("schema_float", "identity"),
        ("service", "service topology"),
        ("image", "identity"),
        ("env", "environment checksum"),
        ("head", "identity"),
        ("terminal", "effect counters"),
        ("legacy", "legacy release marker"),
        ("legacy_type", "legacy release marker"),
        ("primary_mode", "primary environment baseline identity"),
        ("primary_owner", "primary environment baseline identity"),
        ("primary_group", "primary environment baseline identity"),
        ("primary_mode_bool", "primary environment baseline identity"),
        ("primary_mode_float", "primary environment baseline identity"),
        ("primary_uid_bool", "primary environment baseline identity"),
        ("primary_uid_float", "primary environment baseline identity"),
        ("primary_gid_bool", "primary environment baseline identity"),
        ("primary_gid_float", "primary environment baseline identity"),
        ("pending", "effect counters"),
        ("business_timezone", "business-date claim identity"),
        ("business_date", "business-date claim identity"),
        ("business_date_invalid", "business-date claim identity"),
        ("max_attempts", "business-date claim identity"),
        ("max_attempts_bool", "business-date claim identity"),
        ("frozen_count", "frozen copy cohort identity"),
        ("frozen_count_bool", "frozen copy cohort identity"),
        ("frozen_digest", "frozen copy cohort identity"),
        ("restart", "restart counts"),
    ],
)
def test_production_baseline_drift_is_rejected(
    tmp_path: Path, mutation: str, message: str
) -> None:
    stage = _stage(tmp_path)
    baseline = json.loads((stage / "production-baseline.json").read_bytes())
    if mutation == "schema_bool":
        baseline["schema_version"] = True
    elif mutation == "schema_float":
        baseline["schema_version"] = 1.0
    elif mutation == "service":
        baseline["running_services"].pop()
    elif mutation == "image":
        baseline["current_image_reference"] = f"{REPOSITORY}:mutable"
    elif mutation == "env":
        baseline["primary_env_sha256"] = "bad"
    elif mutation == "head":
        baseline["current_alembic_head"] = "20260902_0043"
    elif mutation == "terminal":
        baseline["effect_counts"]["copy_provider_unavailable_terminal"] = 17
    elif mutation == "legacy":
        baseline["legacy_release_commit_sha256"] = _digest(b"drifted\n")
    elif mutation == "legacy_type":
        baseline["legacy_release_commit_uid"] = 1000.0
    elif mutation == "primary_mode":
        baseline["primary_env_mode"] = 0o640
    elif mutation == "primary_owner":
        baseline["primary_env_uid"] = 0
    elif mutation == "primary_group":
        baseline["primary_env_gid"] = 0
    elif mutation == "primary_mode_bool":
        baseline["primary_env_mode"] = True
    elif mutation == "primary_mode_float":
        baseline["primary_env_mode"] = float(0o600)
    elif mutation == "primary_uid_bool":
        baseline["primary_env_uid"] = True
    elif mutation == "primary_uid_float":
        baseline["primary_env_uid"] = 1000.0
    elif mutation == "primary_gid_bool":
        baseline["primary_env_gid"] = True
    elif mutation == "primary_gid_float":
        baseline["primary_env_gid"] = 1001.0
    elif mutation == "pending":
        baseline["effect_counts"]["pending_wecom_jobs"] = 1
    elif mutation == "business_timezone":
        baseline["business_timezone"] = "UTC"
    elif mutation == "business_date":
        baseline["business_date"] = 20260904
    elif mutation == "business_date_invalid":
        baseline["business_date"] = "2026-09-31"
    elif mutation == "max_attempts":
        baseline["content_max_attempts"] = 4
    elif mutation == "max_attempts_bool":
        baseline["content_max_attempts"] = True
    elif mutation == "frozen_count":
        baseline["frozen_copy_job_count"] = 6
    elif mutation == "frozen_count_bool":
        baseline["frozen_copy_job_count"] = True
    elif mutation == "frozen_digest":
        baseline["frozen_copy_job_sha256"] = "bad"
    else:
        baseline["restart_counts"]["content-worker"] = 1
    (stage / "production-baseline.json").write_bytes(_json_bytes(baseline))
    _rebind(stage, "production_baseline_sha256", "production-baseline.json")
    with pytest.raises(ValueError, match=message):
        VALIDATOR.validate_stage(stage)


def _rewrite_oci(stage: Path, mutate: str) -> None:
    image_path = stage / "backend-image.oci.tar.gz"
    with tarfile.open(image_path, "r:gz") as archive:
        entries: dict[str, bytes] = {}
        for member in archive:
            if not member.isfile():
                continue
            stream = archive.extractfile(member)
            assert stream is not None
            entries[member.name.rstrip("/")] = stream.read()
    if mutate == "blob":
        blob = next(name for name in entries if name.startswith("blobs/sha256/"))
        entries[blob] += b"tamper"
    elif mutate == "dangling":
        entries[f"blobs/sha256/{'9' * 64}"] = b"dangling"
    else:
        index = json.loads(entries["index.json"])
        if mutate == "old_full_annotations":
            transport_tag = f"{REPOSITORY}:brand-embedding-{RELEASE_COMMIT[:12]}"
            index["manifests"][0]["annotations"] = {
                "io.containerd.image.name": transport_tag,
                "org.opencontainers.image.ref.name": transport_tag,
            }
        else:
            index["manifests"][0]["annotations"][
                "org.opencontainers.image.ref.name"
            ] = "evil:tag"
        entries["index.json"] = _json_bytes(index)
    tar_entries: list[tuple[str, str, int, bytes | None]] = [
        ("blobs", "d", 0o755, None),
        ("blobs/sha256", "d", 0o755, None),
    ]
    tar_entries.extend(
        (name, "f", 0o644, value) for name, value in sorted(entries.items())
    )
    _write_tar_gz(image_path, tar_entries)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("blob", "descriptor bytes"),
        ("dangling", "dangling"),
        ("tag", "transport tag"),
        ("old_full_annotations", "transport tag"),
    ],
)
def test_complete_oci_graph_rejects_tamper(
    tmp_path: Path, mutation: str, message: str
) -> None:
    stage = _stage(tmp_path)
    _rewrite_oci(stage, mutation)
    _rebind(stage, "image_archive_sha256", "backend-image.oci.tar.gz")
    with pytest.raises(ValueError, match=message):
        VALIDATOR.validate_stage(stage)


@pytest.mark.parametrize(
    ("reference", "expected"),
    [
        (
            "edu-ai-lead-agent-backend:brand-embedding-eeeeeeeeeeee",
            "docker.io/library/edu-ai-lead-agent-backend:brand-embedding-eeeeeeeeeeee",
        ),
        (
            "team/backend:brand-embedding-eeeeeeeeeeee",
            "docker.io/team/backend:brand-embedding-eeeeeeeeeeee",
        ),
        (
            "registry.example.test/team/backend:brand-embedding-eeeeeeeeeeee",
            "registry.example.test/team/backend:brand-embedding-eeeeeeeeeeee",
        ),
        (
            "localhost:5000/team/backend:brand-embedding-eeeeeeeeeeee",
            "localhost:5000/team/backend:brand-embedding-eeeeeeeeeeee",
        ),
    ],
)
def test_containerd_reference_normalization_is_exact(
    reference: str, expected: str
) -> None:
    assert VALIDATOR.normalize_containerd_reference(reference) == expected


@pytest.mark.parametrize(
    "reference",
    [
        "Backend:brand-embedding-eeeeeeeeeeee",
        "backend",
        "backend@sha256:" + "1" * 64,
        "registry.example.test//backend:brand-embedding-eeeeeeeeeeee",
        "registry.example.test/backend:tag:extra",
        "registry.example.test/-backend:brand-embedding-eeeeeeeeeeee",
    ],
)
def test_containerd_reference_normalization_rejects_ambiguous_input(
    reference: str,
) -> None:
    with pytest.raises(ValueError, match="cannot be normalized safely"):
        VALIDATOR.normalize_containerd_reference(reference)


@pytest.mark.parametrize(
    ("legacy_kind", "expected_media_type"),
    [
        ("", "application/vnd.oci.image.layer.v1.tar+gzip"),
        ("uncompressed", "application/vnd.oci.image.layer.v1.tar"),
    ],
)
def test_legacy_oci_canonicalization_is_accepted_by_strict_validator(
    tmp_path: Path, legacy_kind: str, expected_media_type: str
) -> None:
    legacy = tmp_path / "legacy.tar"
    original_manifest, config_digest = _legacy_oci_archive(legacy, legacy_kind)
    canonical = tmp_path / "canonical.tar"
    transport_tag = f"{REPOSITORY}:brand-embedding-{RELEASE_COMMIT[:12]}"

    canonical_manifest = VALIDATOR.canonicalize_legacy_oci_archive(
        legacy, canonical, transport_tag
    )
    repeated = tmp_path / "canonical-repeated.tar"
    assert (
        VALIDATOR.canonicalize_legacy_oci_archive(legacy, repeated, transport_tag)
        == canonical_manifest
    )

    assert canonical_manifest != original_manifest
    assert canonical.read_bytes() == repeated.read_bytes()
    with tarfile.open(canonical, "r:") as archive:
        names = {member.name.rstrip("/") for member in archive}
        index_stream = archive.extractfile("index.json")
        assert index_stream is not None
        index = json.load(index_stream)
        manifest_stream = archive.extractfile(
            f"blobs/sha256/{index['manifests'][0]['digest'][7:]}"
        )
        assert manifest_stream is not None
        manifest = json.load(manifest_stream)
        config_stream = archive.extractfile(
            f"blobs/sha256/{manifest['config']['digest'][7:]}"
        )
        layer_stream = archive.extractfile(
            f"blobs/sha256/{manifest['layers'][0]['digest'][7:]}"
        )
        assert config_stream is not None
        assert layer_stream is not None
        canonical_config = config_stream.read()
        canonical_layer = layer_stream.read()
    with tarfile.open(legacy, "r:") as archive:
        original_config_stream = archive.extractfile(
            f"blobs/sha256/{manifest['config']['digest'][7:]}"
        )
        original_layer_stream = archive.extractfile(
            f"blobs/sha256/{manifest['layers'][0]['digest'][7:]}"
        )
        assert original_config_stream is not None
        assert original_layer_stream is not None
        assert canonical_config == original_config_stream.read()
        assert canonical_layer == original_layer_stream.read()
    assert index["manifests"][0]["platform"] == {
        "architecture": "amd64",
        "os": "linux",
    }
    assert index["manifests"][0]["annotations"] == {
        "io.containerd.image.name": VALIDATOR.normalize_containerd_reference(
            transport_tag
        ),
        "org.opencontainers.image.ref.name": transport_tag.rsplit(":", 1)[1],
    }
    assert manifest["layers"][0]["mediaType"] == expected_media_type
    assert f"blobs/sha256/{original_manifest[7:]}" not in names

    stage = _stage(tmp_path / "strict")
    with (
        canonical.open("rb") as source,
        (stage / "backend-image.oci.tar.gz").open("wb") as raw_output,
        gzip.GzipFile(filename="", mode="wb", fileobj=raw_output, mtime=0) as output,
    ):
        while chunk := source.read(1024 * 1024):
            output.write(chunk)
    metadata = json.loads((stage / "release-metadata.json").read_bytes())
    metadata["candidate_config_digest"] = config_digest
    metadata["candidate_reference"] = f"{REPOSITORY}@{canonical_manifest}"
    metadata["image_archive_sha256"] = VALIDATOR.digest_file(
        stage / "backend-image.oci.tar.gz"
    )
    (stage / "release-metadata.json").write_bytes(_json_bytes(metadata))
    _refresh_artifacts(stage)
    payload = VALIDATOR.validate_stage(stage)
    assert payload["candidate_reference"] == f"{REPOSITORY}@{canonical_manifest}"


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        ("malformed", "layer media type"),
        ("nested", "descriptor"),
        ("dangling", "dangling"),
        ("symlink", "unsafe"),
        ("hardlink", "unsafe"),
        ("duplicate", "duplicate"),
        ("duplicate-json", "duplicate JSON keys"),
        ("path", "unsafe archive path"),
    ],
)
def test_legacy_oci_canonicalization_rejects_unsafe_graphs(
    tmp_path: Path, mutation: str, message: str
) -> None:
    legacy = tmp_path / f"legacy-{mutation}.tar"
    _legacy_oci_archive(legacy, mutation)
    output = tmp_path / f"canonical-{mutation}.tar"
    transport_tag = f"{REPOSITORY}:brand-embedding-{RELEASE_COMMIT[:12]}"

    with pytest.raises(ValueError, match=message):
        VALIDATOR.canonicalize_legacy_oci_archive(legacy, output, transport_tag)

    assert not output.exists()


def test_legacy_oci_canonicalization_enforces_total_size_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    legacy = tmp_path / "legacy.tar"
    _legacy_oci_archive(legacy)
    monkeypatch.setattr(VALIDATOR, "MAX_ARCHIVE_TOTAL", 1)

    with pytest.raises(ValueError, match="exceeds its bound"):
        VALIDATOR.canonicalize_legacy_oci_archive(
            legacy,
            tmp_path / "canonical.tar",
            f"{REPOSITORY}:brand-embedding-{RELEASE_COMMIT[:12]}",
        )


def test_operator_is_one_shot_null_stdin_and_has_no_effect_surface() -> None:
    operator = OPERATOR_PATH.read_text(encoding="utf-8")
    for service in VALIDATOR.APP_SERVICES:
        assert service in operator
    assert "operator stdin must be /dev/null" in operator
    assert operator.count("compose run --rm --no-deps -T backend-migrate") == 1
    assert "candidate was already attempted" in operator
    assert "pending_wecom_jobs" in operator
    assert "provider_calls=0" in operator
    assert "send_calls=0" in operator
    assert "replay_calls=0" in operator
    assert (
        operator.count(
            "--env AI_PLATFORM_BASE_URL=https://open.bigmodel.cn/api/paas/v4"
        )
        == 1
    )
    for forbidden in ("curl ", "wget ", "http://", "INSERT ", "UPDATE "):
        assert forbidden not in operator
    assert "printf 'APP_IMAGE=%s\\n' \"$candidate_reference\"" in operator
    assert "printf 'APP_IMAGE=%s\\n' \"$candidate_config_digest\"" not in operator
    assert "printf 'APP_IMAGE=%s\\n' \"$transport_tag\"" not in operator


def test_operator_all_container_creation_paths_are_statically_no_build() -> None:
    operator = OPERATOR_PATH.read_text(encoding="utf-8")
    assert operator.count("docker compose") == 1
    creation_lines = [
        line.strip()
        for line in operator.splitlines()
        if line.strip().startswith(("compose create ", "compose up "))
    ]
    assert creation_lines == [
        'compose up -d --no-build --no-deps "${APP_SERVICES[@]}" >/dev/null || return 1',
        'compose up -d --no-build --no-deps "${APP_SERVICES[@]}"',
    ]
    assert operator.count("compose run --rm --no-deps -T backend-migrate") == 1
    assert "compose run --build" not in operator


@pytest.mark.parametrize("operation", ["create", "up"])
def test_operator_compose_rejects_container_creation_without_no_build(
    tmp_path: Path, operation: str
) -> None:
    calls = tmp_path / "docker.calls"
    result = _source_operator_shell(
        tmp_path,
        f"""
docker() {{ printf '%s\\n' "$*" >>{calls!s}; }}
compose {operation} service
""",
    )

    assert result.returncode != 0
    assert f"production Compose {operation} requires --no-build" in result.stderr
    assert not calls.exists()


@pytest.mark.parametrize("operation", ["create", "up"])
def test_operator_compose_forwards_no_build_container_creation(
    tmp_path: Path, operation: str
) -> None:
    calls = tmp_path / "docker.calls"
    result = _source_operator_shell(
        tmp_path,
        f"""
IFS=' '
docker() {{ printf '%s\\n' "$*" >>{calls!s}; }}
compose {operation} --no-build service
""",
    )

    assert result.returncode == 0, result.stderr
    call = calls.read_text(encoding="utf-8")
    assert call.startswith(
        f"compose --project-name edu-ai-lead-agent --project-directory {tmp_path / 'app'} "
    )
    assert call.endswith(f" {operation} --no-build service\n")


@pytest.mark.parametrize("operation", ["create", "up"])
@pytest.mark.parametrize("build_argument", ["--build", "--build=true", "--build=false"])
def test_operator_compose_container_creation_rejects_build_even_with_no_build(
    tmp_path: Path, operation: str, build_argument: str
) -> None:
    calls = tmp_path / "docker.calls"
    result = _source_operator_shell(
        tmp_path,
        f"""
docker() {{ printf '%s\\n' "$*" >>{calls!s}; }}
compose {operation} --no-build {build_argument} service
""",
    )

    assert result.returncode != 0
    assert f"production Compose {operation} forbids --build" in result.stderr
    assert not calls.exists()


@pytest.mark.parametrize("build_argument", ["--build", "--build=true", "--build=false"])
def test_operator_compose_run_forbids_explicit_build(
    tmp_path: Path, build_argument: str
) -> None:
    calls = tmp_path / "docker.calls"
    result = _source_operator_shell(
        tmp_path,
        f"""
docker() {{ printf '%s\\n' "$*" >>{calls!s}; }}
compose run {build_argument} service
""",
    )

    assert result.returncode != 0
    assert "production Compose run forbids --build" in result.stderr
    assert not calls.exists()


def test_operator_compose_run_forwards_migration_without_build(tmp_path: Path) -> None:
    calls = tmp_path / "docker.calls"
    result = _source_operator_shell(
        tmp_path,
        f"""
IFS=' '
docker() {{ printf '%s\\n' "$*" >>{calls!s}; }}
compose run --rm --no-deps -T backend-migrate
""",
    )

    assert result.returncode == 0, result.stderr
    call = calls.read_text(encoding="utf-8")
    assert call.startswith(
        f"compose --project-name edu-ai-lead-agent --project-directory {tmp_path / 'app'} "
    )
    assert call.endswith(" run --rm --no-deps -T backend-migrate\n")
    assert "--build" not in call
    assert "--no-build" not in call


def test_capture_and_builder_bind_authority_topology_and_read_only_baseline() -> None:
    capture = CAPTURE_PATH.read_text(encoding="utf-8")
    builder = BUILDER_PATH.read_text(encoding="utf-8")
    assert f"readonly PRODUCTION_COMMIT={VALIDATOR.PRODUCTION_COMMIT}" in capture
    assert f"readonly ALEMBIC_HEAD={VALIDATOR.ALEMBIC_HEAD}" in capture
    assert "running service topology differs" in capture
    assert "the twelve application services do not share one image" in capture
    assert "copy_provider_unavailable" in capture
    assert "pending_wecom_jobs" in capture
    assert "claimable_copy_jobs" in capture
    assert "running_copy_jobs" in capture
    assert "current_business_date_copy_jobs" in capture
    assert "future_copy_jobs" in capture
    assert "frozen_copy_job_sha256" in capture
    assert "ORDER BY run.business_date, job.id::text" in capture
    assert r"run.business_date = '\''$1'\''::date" in capture
    assert "job.available_at <= statement_timestamp()" in capture
    assert "job.attempt_count < $2::integer" in capture
    assert "current_image_reference" in capture
    assert "primary_env_mode" in capture
    assert "primary_env_uid" in capture
    assert "primary_env_gid" in capture
    assert 'getattr(os, "O_NOFOLLOW", 0)' in capture
    assert "primary environment changed during baseline capture" in capture
    operator = OPERATOR_PATH.read_text(encoding="utf-8")
    assert 'getattr(os, "O_NOFOLLOW", 0)' in operator
    assert operator.count("copy_state_matches_baseline") >= 7
    assert operator.count("verify_baseline") == 3
    assert "frozen_copy_job_sha256" in operator
    for forbidden in ("INSERT ", "UPDATE ", "DELETE ", "curl ", "wget "):
        assert forbidden not in capture

    assert f"readonly RELEASE_REF={VALIDATOR.RELEASE_REF}" in builder
    assert f"readonly PRODUCTION_COMMIT={VALIDATOR.PRODUCTION_COMMIT}" in builder
    assert "readonly CONTAINERD_ADDRESS=/run/containerd/containerd.sock" in builder
    assert 'ctr --address "$CONTAINERD_ADDRESS"' in builder
    assert "fetch --quiet --no-tags origin" in builder
    assert '"$RELEASE_HEAD_REF:$RELEASE_REF" "$MAIN_HEAD_REF:$MAIN_REF"' in builder
    assert 'merge-base --is-ancestor "$PRODUCTION_COMMIT" "$release_sha"' in builder
    assert 'rev-parse --verify "${RELEASE_REF}^{commit}"' in builder
    assert 'show "${release_sha}:${TASK_PATH}/${BUILDER_NAME}"' in builder
    assert "diff --name-status --no-renames" in builder
    assert (
        "complete runtime diff does not equal the reviewed eight-path allowlist"
        in builder
    )
    assert "--platform linux/amd64" in builder
    assert "manifest-descriptor:io.containerd.image.name" in builder
    assert "manifest-descriptor:org.opencontainers.image.ref.name" in builder
    assert "DOCKER_BUILDKIT=0" in builder
    assert "--skip-manifest-json --platform linux/amd64" in builder
    assert "io.containerd.snapshotter.v1" in builder
    assert "--canonicalize-legacy-oci" in builder
    assert "docker buildx capability probe failed; refusing fallback" in builder
    assert 'grep -Fxq "$candidate_reference"' in builder
    assert "--env AI_PLATFORM_BASE_URL=https://open.bigmodel.cn/api/paas/v4" in builder
    assert '--entrypoint alembic "$candidate_reference"' in builder
    assert "-c alembic.ini heads" in builder
    assert '[[ "$observed" == "$ALEMBIC_HEAD (head)" ]]' in builder
    assert VALIDATOR.SERVICE_COMMANDS["official-account-weekly-dag-worker"] == (
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
    )


def test_capture_accepts_documented_stale_legacy_marker_and_rejects_drift(
    tmp_path: Path,
) -> None:
    app = tmp_path / "app"
    app.mkdir()
    marker = app / "RELEASE_COMMIT"
    marker.write_bytes(VALIDATOR.LEGACY_PRODUCTION_COMMIT + b"\n")
    marker.chmod(0o600)
    os.chown(marker, 1000, 1001)
    environment = os.environ.copy()
    environment.update(
        {
            "BRAND_HOTFIX_CAPTURE_SOURCE_ONLY": "1",
            "BRAND_HOTFIX_CAPTURE_TEST_APP_DIR": str(app),
        }
    )
    accepted = subprocess.run(
        ["bash", "-c", f"source {CAPTURE_PATH!s}\nvalidate_legacy_release_marker"],
        env=environment,
        check=False,
        text=True,
        capture_output=True,
    )
    assert accepted.returncode == 0, accepted.stderr
    assert VALIDATOR.LEGACY_PRODUCTION_COMMIT.decode() not in accepted.stdout

    marker.write_text("deadbee\n", encoding="utf-8")
    rejected = subprocess.run(
        ["bash", "-c", f"source {CAPTURE_PATH!s}\nvalidate_legacy_release_marker"],
        env=environment,
        check=False,
        text=True,
        capture_output=True,
    )
    assert rejected.returncode != 0
    assert "legacy release marker differs" in rejected.stderr


REVIEWED_FROZEN_DATES = (
    "2026-08-04",
    "2026-08-05",
    "2026-08-07",
    "2026-08-08",
    "2026-08-09",
    "2026-08-10",
    "2026-08-11",
)


def _frozen_copy_rows() -> list[str]:
    return [
        (
            f"00000000-0000-4000-8000-{index:012d}|"
            f"10000000-0000-4000-8000-{index:012d}|queued|{business_date}|0|"
            f"2026-08-12T00:00:0{index}.000000Z"
        )
        for index, business_date in enumerate(REVIEWED_FROZEN_DATES, start=1)
    ]


def _run_frozen_copy_cohort(
    tmp_path: Path, script: Path, rows: list[str]
) -> subprocess.CompletedProcess[str]:
    shell_rows = "\n".join(f"  printf '%s\\n' '{row}'" for row in rows)
    environment = os.environ.copy()
    environment.update(
        {
            "BRAND_HOTFIX_CAPTURE_SOURCE_ONLY": "1",
            "BRAND_HOTFIX_CAPTURE_TEST_APP_DIR": str(tmp_path),
            "BRAND_HOTFIX_OPERATOR_SOURCE_ONLY": "1",
            "BRAND_HOTFIX_OPERATOR_TEST_ROOT": str(tmp_path),
        }
    )
    return subprocess.run(
        [
            "bash",
            "-c",
            (
                f"source {script!s}\ncompose() {{\n{shell_rows}\n}}\n"
                "frozen_copy_cohort 2026-09-04"
            ),
        ],
        env=environment,
        check=False,
        text=True,
        capture_output=True,
    )


@pytest.mark.parametrize(
    "script", [CAPTURE_PATH, OPERATOR_PATH], ids=["capture", "operator"]
)
def test_frozen_copy_cohort_outputs_only_count_and_stable_digest(
    tmp_path: Path, script: Path
) -> None:
    rows = _frozen_copy_rows()
    canonical = ("\n".join(rows) + "\n").encode()
    result = _run_frozen_copy_cohort(tmp_path, script, rows)
    assert result.returncode == 0, result.stderr
    assert result.stdout == f"7:{_digest(canonical)}\n"
    assert "00000000-" not in result.stdout


@pytest.mark.parametrize(
    "script", [CAPTURE_PATH, OPERATOR_PATH], ids=["capture", "operator"]
)
@pytest.mark.parametrize("mutation", ["count", "date", "status", "attempt", "order"])
def test_frozen_copy_cohort_rejects_pre_capture_identity_drift(
    tmp_path: Path, script: Path, mutation: str
) -> None:
    rows = _frozen_copy_rows()
    if mutation == "count":
        rows.pop()
    elif mutation == "date":
        rows[2] = rows[2].replace("2026-08-07", "2026-08-06")
    elif mutation == "status":
        rows[2] = rows[2].replace("|queued|", "|retry_scheduled|")
    elif mutation == "attempt":
        rows[2] = rows[2].replace("|2026-08-07|0|", "|2026-08-07|1|")
    else:
        rows[1], rows[2] = rows[2], rows[1]

    result = _run_frozen_copy_cohort(tmp_path, script, rows)

    assert result.returncode != 0
    assert "frozen copy cohort" in result.stderr
    assert "00000000-" not in result.stdout + result.stderr


@pytest.mark.parametrize(
    "script", [CAPTURE_PATH, OPERATOR_PATH], ids=["capture", "operator"]
)
def test_effect_count_query_and_index_schema_match_real_claim_contract(
    tmp_path: Path, script: Path
) -> None:
    arguments = tmp_path / f"{script.stem}.arguments"
    expected = [18, *range(1, 11), *([0] * 8)]
    expected_row = ":".join(map(str, expected))
    baseline = _baseline(terminal_count=18)
    effects = baseline["effect_counts"]
    assert isinstance(effects, dict)
    for index, key in enumerate(VALIDATOR.EFFECT_COUNT_ORDER[1:11], start=1):
        effects[key] = index
    baseline_path = tmp_path / f"{script.stem}.baseline.json"
    baseline_path.write_bytes(_json_bytes(baseline))
    environment = os.environ.copy()
    environment.update(
        {
            "BRAND_HOTFIX_CAPTURE_SOURCE_ONLY": "1",
            "BRAND_HOTFIX_CAPTURE_TEST_APP_DIR": str(tmp_path),
            "BRAND_HOTFIX_OPERATOR_SOURCE_ONLY": "1",
            "BRAND_HOTFIX_OPERATOR_TEST_ROOT": str(tmp_path),
        }
    )
    result = subprocess.run(
        [
            "bash",
            "-c",
            (
                f"source {script!s}\n"
                f"compose() {{ printf '%s\\0' \"$@\" >{arguments!s}; "
                f"printf '%s\\n' '{expected_row}'; }}\n"
                "effect_counts 2026-09-04"
            ),
        ],
        env=environment,
        check=False,
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == expected_row + "\n"
    query = arguments.read_bytes().decode().split("\0")[6]
    assert "run.business_date = '$1'::date" in query
    assert "job.status IN ('queued', 'retry_scheduled')" in query
    assert "job.available_at <= statement_timestamp()" in query
    assert "job.attempt_count < $2::integer" in query
    assert "copy_generation_jobs WHERE status = 'running'" in query
    assert "run.business_date > '$1'::date" in query
    assert "job.status IN ('queued', 'running', 'retry_scheduled')" in query

    if script == OPERATOR_PATH:
        indexed = _source_operator_shell(
            tmp_path,
            f"baseline_json={baseline_path!s}\nbaseline_effect_counts",
        )
        assert indexed.returncode == 0, indexed.stderr
        assert indexed.stdout == expected_row + "\n"


@pytest.mark.parametrize(
    ("mode", "uid", "gid", "accepted"),
    [
        (0o600, 1000, 1001, True),
        (0o640, 1000, 1001, False),
        (0o600, 0, 1001, False),
        (0o600, 1000, 0, False),
    ],
)
def test_capture_binds_reviewed_primary_environment_metadata(
    tmp_path: Path, mode: int, uid: int, gid: int, accepted: bool
) -> None:
    app = tmp_path / "app"
    app.mkdir()
    primary_env = app / ".env"
    primary_env.write_text("secret=value\n", encoding="utf-8")
    primary_env.chmod(mode)
    os.chown(primary_env, uid, gid)
    environment = os.environ.copy()
    environment.update(
        {
            "BRAND_HOTFIX_CAPTURE_SOURCE_ONLY": "1",
            "BRAND_HOTFIX_CAPTURE_TEST_APP_DIR": str(app),
        }
    )

    result = subprocess.run(
        ["bash", "-c", f"source {CAPTURE_PATH!s}\nvalidate_primary_environment"],
        env=environment,
        check=False,
        text=True,
        capture_output=True,
    )

    assert (result.returncode == 0) is accepted
    if not accepted:
        assert "reviewed stable physical mode and owner" in result.stderr


def test_capture_rejects_linked_primary_environment(tmp_path: Path) -> None:
    app = tmp_path / "app"
    app.mkdir()
    target = tmp_path / "primary.env"
    target.write_text("secret=value\n", encoding="utf-8")
    target.chmod(0o600)
    os.chown(target, 1000, 1001)
    (app / ".env").symlink_to(target)
    environment = os.environ.copy()
    environment.update(
        {
            "BRAND_HOTFIX_CAPTURE_SOURCE_ONLY": "1",
            "BRAND_HOTFIX_CAPTURE_TEST_APP_DIR": str(app),
        }
    )

    result = subprocess.run(
        ["bash", "-c", f"source {CAPTURE_PATH!s}\nvalidate_primary_environment"],
        env=environment,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode != 0
    assert "reviewed stable physical mode and owner" in result.stderr


@pytest.mark.parametrize("failure", ["", "fetch", "ref", "ancestor"])
def test_fake_builder_authority_harness(tmp_path: Path, failure: str) -> None:
    repository = tmp_path / "repository"
    committed_builder = repository / (
        ".trellis/tasks/09-04-production-brand-embedding-hotfix/research/"
        + BUILDER_PATH.name
    )
    committed_builder.parent.mkdir(parents=True)
    committed_builder.write_bytes(BUILDER_PATH.read_bytes())
    shell = f"""
export BRAND_HOTFIX_BUILDER_SOURCE_ONLY=1
source {BUILDER_PATH!s}
repo_root={repository!s}
scratch={tmp_path / "scratch"!s}
release_sha={RELEASE_COMMIT}
main_fix_commit={"f" * 40}
main_operator_commit={"a" * 40}
git_clean() {{
  if [[ "${{1:-}}" == -C ]]; then shift 2; fi
  case "${{1:-}}" in
    config) printf '%s\\n' "$SOURCE_URL" ;;
    rev-parse)
      if [[ "${{3:-}}" == "${{RELEASE_REF}}^{{commit}}" ]]; then
        [[ {failure!r} == ref ]] && printf '%s\\n' "{"d" * 40}" || printf '%s\\n' "$release_sha"
      else
        printf '%s\\n' "{"b" * 40}"
      fi
      ;;
    merge-base)
      if [[ "${{3:-}}" == "$PRODUCTION_COMMIT" && {failure!r} == ancestor ]]; then
        return 1
      fi
      return 0
      ;;
    show) command cat {BUILDER_PATH!s} ;;
    *) return 91 ;;
  esac
}}
git_fetch() {{
  [[ {failure!r} != fetch ]]
}}
assert_authority
"""
    result = subprocess.run(
        ["bash", "-c", shell], check=False, text=True, capture_output=True
    )
    if failure:
        assert result.returncode != 0
        expected = {
            "fetch": "authoritative Codeup refs",
            "ref": "fetched hotfix ref",
            "ancestor": "production commit",
        }[failure]
        assert expected in result.stderr
    else:
        assert result.returncode == 0, result.stderr


def _source_builder_shell(body: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["BRAND_HOTFIX_BUILDER_SOURCE_ONLY"] = "1"
    return subprocess.run(
        ["bash", "-c", f"source {BUILDER_PATH!s}\n{body}"],
        env=environment,
        check=False,
        text=True,
        capture_output=True,
    )


@pytest.mark.parametrize("baseline_is_valid", [True, False])
def test_builder_baseline_preflight_is_fail_closed_and_preserves_exact_stage_member_set(
    tmp_path: Path, baseline_is_valid: bool
) -> None:
    stage = tmp_path / "stage"
    stage.mkdir(mode=0o700)
    staged_validator = stage / VALIDATOR_PATH.name
    staged_validator.write_bytes(VALIDATOR_PATH.read_bytes())
    staged_validator.chmod(0o600)
    staged_baseline = stage / "production-baseline.json"
    staged_baseline.write_bytes(
        _json_bytes(_baseline()) if baseline_is_valid else b"{}"
    )
    staged_baseline.chmod(0o600)
    members_before = {path.name for path in stage.iterdir()}

    result = _source_builder_shell(f"stage={stage!s}\nvalidate_staged_baseline")

    assert (result.returncode == 0) is baseline_is_valid, result.stderr
    assert {path.name for path in stage.iterdir()} == members_before
    assert not (stage / "__pycache__").exists()


def test_builder_disables_bytecode_for_every_staged_validator_execution() -> None:
    builder = BUILDER_PATH.read_text(encoding="utf-8")
    invocations = [
        line.strip()
        for line in builder.splitlines()
        if line.strip().startswith("python3 ") and "$VALIDATOR_NAME" in line
    ]

    assert len(invocations) == 6
    assert all(line.startswith("python3 -B ") for line in invocations)


@pytest.mark.parametrize(
    ("probe", "route", "accepted"),
    [
        ("available", "buildx", True),
        ("missing", "legacy-containerd", True),
        ("broken", "", False),
    ],
)
def test_builder_route_is_selected_only_by_capability_probe(
    probe: str, route: str, accepted: bool
) -> None:
    result = _source_builder_shell(
        f"""
IFS=' '
docker_clean() {{
  if [[ "$*" == "buildx version" ]]; then
    case {probe!r} in
      available) printf 'github.com/docker/buildx 1.0\n'; return 0 ;;
      missing) printf 'docker: unknown command: docker buildx\n' >&2; return 1 ;;
      broken) printf 'buildx plugin crashed\n' >&2; return 2 ;;
    esac
  fi
  return 90
}}
validate_legacy_builder_capabilities() {{ printf 'legacy-capability-ok\n' >&2; }}
select_image_builder_route
"""
    )
    assert (result.returncode == 0) is accepted
    if accepted:
        assert result.stdout == route + "\n"
        assert ("legacy-capability-ok" in result.stderr) is (probe == "missing")
    else:
        assert "refusing fallback" in result.stderr
        assert "legacy-capability-ok" not in result.stderr


def test_selected_buildx_failure_never_retries_with_legacy(tmp_path: Path) -> None:
    legacy_called = tmp_path / "legacy-called"
    result = _source_builder_shell(
        f"""
scratch={tmp_path / "scratch"!s}
stage={tmp_path / "stage"!s}
repo_root={tmp_path / "repository"!s}
worktree={tmp_path / "worktree"!s}
release_sha={RELEASE_COMMIT}
transport_tag=edu-ai-lead-agent-backend:brand-embedding-{RELEASE_COMMIT[:12]}
git_clean() {{ printf '2026-09-04T00:00:00+00:00\n'; }}
select_image_builder_route() {{ printf 'buildx\n'; }}
assert_transport_tag_absent() {{ candidate_image_owned=1; }}
normalize_containerd_reference() {{ printf 'docker.io/library/%s\n' "$1"; }}
run_buildx_image() {{ return 42; }}
run_legacy_docker_build() {{ touch {legacy_called!s}; }}
build_and_probe_image
"""
    )
    assert result.returncode != 0
    assert not legacy_called.exists()


def test_builder_image_source_probe_emits_one_canonical_row_per_file(
    tmp_path: Path,
) -> None:
    backend = tmp_path / "backend"
    files = {
        "alembic.ini": b"[alembic]\n",
        "pyproject.toml": b"[project]\n",
        "app/api_main.py": b"app = object()\n",
        "app/template.html": b"<p>safe</p>\n",
        "alembic/versions/revision.py": b"revision = 'test'\n",
    }
    excluded = {
        "app/runtime.txt": b"not copied into the image-source manifest\n",
        "alembic/README": b"not a Python or HTML source file\n",
    }
    for name, value in (files | excluded).items():
        path = backend / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)
    captured_script = tmp_path / "probe.py"
    observed = tmp_path / "observed-image-source.sha256"
    result = _source_builder_shell(
        f"""
docker() {{
  while (($#)); do
    if [[ "$1" == -c ]]; then
      shift
      printf '%s' "$1" >{captured_script!s}
      return 0
    fi
    shift
  done
  return 90
}}
write_observed_image_source_manifest candidate:reviewed {observed!s}
"""
    )
    assert result.returncode == 0, result.stderr
    probe = captured_script.read_text(encoding="utf-8")
    assert r"\\n" not in probe
    probe = probe.replace('pathlib.Path("/app")', f"pathlib.Path({str(backend)!r})")
    executed = subprocess.run(
        ["python3", "-c", probe], check=False, text=True, capture_output=True
    )
    assert executed.returncode == 0, executed.stderr
    expected = "".join(f"{_digest(files[name])}  {name}\n" for name in sorted(files))
    assert executed.stdout == expected
    assert executed.stdout.count("\n") == len(files)


def test_builder_and_operator_share_the_exact_complete_image_source_probe(
    tmp_path: Path,
) -> None:
    worktree = tmp_path / "release"
    entries = _exact_release_source_entries(worktree)
    stage = tmp_path / "stage"
    stage.mkdir()
    _write_source(stage, entries)
    expected = stage / "image-source.sha256"
    builder_probe = tmp_path / "builder-probe.py"
    operator_probe = tmp_path / "operator-probe.py"

    builder_result = _source_builder_shell(
        f"""
worktree={worktree!s}
stage={stage!s}
docker() {{
  while (($#)); do
    if [[ "$1" == -c ]]; then
      shift
      printf '%s' "$1" >{builder_probe!s}
      return 0
    fi
    shift
  done
  return 90
}}
write_image_source_manifest
write_observed_image_source_manifest candidate:reviewed {tmp_path / "builder-observed"!s}
"""
    )
    operator_result = _source_operator_shell(
        tmp_path / "operator-root",
        f"""
docker() {{
  while (($#)); do
    if [[ "$1" == -c ]]; then
      shift
      printf '%s' "$1" >{operator_probe!s}
      return 0
    fi
    shift
  done
  return 90
}}
write_observed_image_source_manifest candidate:reviewed {tmp_path / "operator-observed"!s}
""",
    )

    assert builder_result.returncode == 0, builder_result.stderr
    assert operator_result.returncode == 0, operator_result.stderr
    assert operator_probe.read_bytes() == builder_probe.read_bytes()
    probe = operator_probe.read_text(encoding="utf-8").replace(
        'pathlib.Path("/app")', f"pathlib.Path({str(worktree / 'backend')!r})"
    )
    executed = subprocess.run(
        ["python3", "-c", probe], check=False, text=True, capture_output=True
    )
    assert executed.returncode == 0, executed.stderr
    assert executed.stdout == expected.read_text(encoding="utf-8")
    rows = executed.stdout.splitlines()
    assert len(rows) == 298
    assert rows[0].endswith("  alembic.ini")
    assert next(row for row in rows if row.endswith("  alembic/env.py")) != rows[0]


def test_exact_release_image_source_is_sorted_and_fully_bound(tmp_path: Path) -> None:
    worktree = tmp_path / "release"
    entries = _exact_release_source_entries(worktree)
    stage = tmp_path / "stage"
    stage.mkdir()
    _write_source(stage, entries)

    result = _source_builder_shell(
        f"worktree={worktree!s}\nstage={stage!s}\nwrite_image_source_manifest"
    )

    assert result.returncode == 0, result.stderr
    expected = VALIDATOR.validate_source_archive(stage)
    VALIDATOR.validate_image_source(stage / "image-source.sha256", expected)
    rows = (stage / "image-source.sha256").read_text(encoding="utf-8").splitlines()
    assert len(rows) == 298
    assert rows[0].endswith("  alembic.ini")
    assert any(
        row.endswith("  alembic/versions/20260901_0042_wechat_mp_draft_jobs.py")
        for row in rows
    )


@pytest.mark.parametrize("mutation", ["missing", "duplicate"])
def test_source_archive_requires_one_declared_alembic_head(
    tmp_path: Path, mutation: str
) -> None:
    entries = _source_entries()
    head_name = "backend/alembic/versions/20260901_0042_wechat_mp_draft_jobs.py"
    if mutation == "missing":
        entries = [
            (
                name,
                kind,
                mode,
                b"revision='20260901_0999'\n" if name == head_name else value,
            )
            for name, kind, mode, value in entries
        ]
        message = "Alembic head revision declaration is missing"
    else:
        entries.append(
            (
                "backend/alembic/versions/renamed_head.py",
                "f",
                0o644,
                b"revision='20260901_0042'\n",
            )
        )
        entries.sort()
        message = "Alembic revision declaration is duplicated"
    stage = tmp_path / "stage"
    stage.mkdir()
    _write_source(stage, entries)

    with pytest.raises(ValueError, match=message):
        VALIDATOR.validate_source_archive(stage)


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (b"down_revision = None\n", "missing or duplicated"),
        (b"revision = make_revision()\n", "not a static string"),
        (b"revision = 'one'\nrevision = 'two'\n", "missing or duplicated"),
        (b"revision: str\nrevision = 'one'\n", "missing or duplicated"),
        (b"revision = 'one'\nrevision += 'two'\n", "dynamically rebound"),
    ],
)
def test_alembic_revision_requires_one_static_unmodified_declaration(
    source: bytes, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        VALIDATOR.alembic_revision(source, "reviewed.py")


@pytest.mark.parametrize(
    ("source", "message"),
    [
        (
            b"revision = 'reviewed'\n" + b"#" * VALIDATOR.MAX_ALEMBIC_SOURCE,
            "source exceeds its bound",
        ),
        (
            b"revision = 'reviewed'\n"
            + b"value = 0\n" * (VALIDATOR.MAX_ALEMBIC_AST_NODES // 3),
            "AST exceeds its bound",
        ),
    ],
)
def test_alembic_revision_ast_has_explicit_resource_bounds(
    source: bytes, message: str
) -> None:
    with pytest.raises(ValueError, match=message):
        VALIDATOR.alembic_revision(source, "reviewed.py")


def test_source_archive_bounds_alembic_revision_count(tmp_path: Path) -> None:
    entries = _source_entries()
    entries.extend(
        (
            f"backend/alembic/versions/generated_{index:03d}.py",
            "f",
            0o644,
            f"revision = 'generated_{index:03d}'\n".encode(),
        )
        for index in range(VALIDATOR.MAX_ALEMBIC_REVISIONS)
    )
    entries.sort()
    stage = tmp_path / "stage"
    stage.mkdir()
    _write_source(stage, entries)

    with pytest.raises(ValueError, match="revision count exceeds its bound"):
        VALIDATOR.validate_source_archive(stage)


def test_image_source_rejects_a_partial_dynamic_migration_projection(
    tmp_path: Path,
) -> None:
    stage = _stage(tmp_path)
    expected = VALIDATOR.validate_source_archive(stage)
    rows = (stage / "image-source.sha256").read_text(encoding="utf-8").splitlines()
    migration_rows = [row for row in rows if "  alembic/versions/" in row]
    assert len(migration_rows) == 1
    (stage / "image-source.sha256").write_text(
        "\n".join(row for row in rows if row != migration_rows[0]) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="complete source projection"):
        VALIDATOR.validate_image_source(stage / "image-source.sha256", expected)


@pytest.mark.parametrize(
    "unsafe_name", ["app/injected\nrow.py", "app/injected\trow.py"]
)
def test_builder_image_source_manifests_reject_record_injection_paths(
    tmp_path: Path, unsafe_name: str
) -> None:
    backend = tmp_path / "backend"
    required = {
        "alembic.ini": b"[alembic]\n",
        "pyproject.toml": b"[project]\n",
        "app/api_main.py": b"app = object()\n",
        unsafe_name: b"injected = True\n",
    }
    for name, value in required.items():
        path = backend / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)

    host_result = _source_builder_shell(
        f"""
worktree={tmp_path!s}
stage={tmp_path!s}
write_image_source_manifest
"""
    )
    assert host_result.returncode != 0
    assert "image source scope contains an unsafe path" in host_result.stderr

    captured_script = tmp_path / "probe.py"
    observed = tmp_path / "observed-image-source.sha256"
    capture_result = _source_builder_shell(
        f"""
docker() {{
  while (($#)); do
    if [[ "$1" == -c ]]; then
      shift
      printf '%s' "$1" >{captured_script!s}
      return 0
    fi
    shift
  done
  return 90
}}
write_observed_image_source_manifest candidate:reviewed {observed!s}
"""
    )
    assert capture_result.returncode == 0, capture_result.stderr
    probe = captured_script.read_text(encoding="utf-8")
    probe = probe.replace('pathlib.Path("/app")', f"pathlib.Path({str(backend)!r})")
    executed = subprocess.run(
        ["python3", "-c", probe], check=False, text=True, capture_output=True
    )
    assert executed.returncode != 0
    assert "image source scope contains an unsafe path" in executed.stderr
    assert executed.stdout == ""


def test_legacy_builder_capability_gate_binds_local_containerd() -> None:
    result = _source_builder_shell(
        """
IFS=' '
scratch=/tmp/brand-builder-test
validate_containerd_socket() { return 0; }
docker_clean() {
  case "$*" in
    "context show") printf 'default\n' ;;
    "context inspect --format {{.Endpoints.docker.Host}} default") printf 'unix:///var/run/docker.sock\n' ;;
    "version --format {{.Client.Version}} {{.Server.Version}}") printf '29.1.3 29.1.3\n' ;;
    "info --format {{.OSType}}/{{.Architecture}}") printf 'linux/x86_64\n' ;;
    "info --format {{json .DriverStatus}}") printf '[["driver-type","io.containerd.snapshotter.v1"]]\n' ;;
    "build --help") printf '  --pull value\n  --platform value\n  --tag value\n' ;;
    *) return 90 ;;
  esac
}
ctr_clean() {
  case "$*" in
    version) printf 'Client:\n  Version:  2.2.1\nServer:\n  Version:  2.2.1\n' ;;
    "namespaces list -q") printf 'moby\n' ;;
    "--namespace moby images inspect --help") return 0 ;;
    "--namespace moby images export --help") printf '%s\n' ' --skip-manifest-json' ' --platform value' ;;
    *) return 91 ;;
  esac
}
validate_legacy_builder_capabilities
"""
    )
    assert result.returncode == 0, result.stderr


def test_legacy_builder_capability_gate_rejects_unreviewed_docker_version() -> None:
    result = _source_builder_shell(
        """
IFS=' '
scratch=/tmp/brand-builder-test
validate_containerd_socket() { return 0; }
docker_clean() {
  case "$*" in
    "context show") printf 'default\n' ;;
    "context inspect --format {{.Endpoints.docker.Host}} default") printf 'unix:///var/run/docker.sock\n' ;;
    "version --format {{.Client.Version}} {{.Server.Version}}") printf '30.0.0 30.0.0\n' ;;
    *) return 90 ;;
  esac
}
validate_legacy_builder_capabilities
"""
    )
    assert result.returncode != 0
    assert "differ from the reviewed pair" in result.stderr


def test_ctr_commands_bind_the_reviewed_server_address(tmp_path: Path) -> None:
    capture = tmp_path / "ctr.argv"
    result = _source_builder_shell(
        f"""
scratch={tmp_path / "scratch"!s}
capture={capture!s}
env() {{ printf '%s\\0' "$@" >"$capture"; }}
ctr_clean --namespace moby images inspect docker.io/library/example:reviewed
"""
    )
    assert result.returncode == 0, result.stderr
    assert capture.read_bytes().split(b"\0")[:-1] == [
        b"-i",
        b"PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        f"HOME={tmp_path / 'scratch'!s}".encode(),
        b"LC_ALL=C",
        b"ctr",
        b"--address",
        b"/run/containerd/containerd.sock",
        b"--namespace",
        b"moby",
        b"images",
        b"inspect",
        b"docker.io/library/example:reviewed",
    ]


def test_legacy_build_argv_and_environment_are_exact(tmp_path: Path) -> None:
    capture = tmp_path / "legacy-build.argv"
    scratch = tmp_path / "scratch"
    worktree = tmp_path / "worktree"
    result = _source_builder_shell(
        f"""
scratch={scratch!s}
worktree={worktree!s}
release_sha={RELEASE_COMMIT}
transport_tag=edu-ai-lead-agent-backend:brand-embedding-{RELEASE_COMMIT[:12]}
capture={capture!s}
env() {{ printf '%s\\0' "$@" >"$capture"; }}
run_legacy_docker_build 2026-09-04T00:00:00+00:00
"""
    )
    assert result.returncode == 0, result.stderr
    argv = capture.read_bytes().split(b"\0")[:-1]
    assert argv == [
        b"-i",
        b"PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        f"HOME={scratch!s}".encode(),
        b"LC_ALL=C",
        b"DOCKER_BUILDKIT=0",
        b"docker",
        b"build",
        b"--pull",
        b"--platform",
        b"linux/amd64",
        b"--build-arg",
        f"CODEUP_COMMIT={RELEASE_COMMIT}".encode(),
        b"--build-arg",
        f"SOURCE_URL={SOURCE_URL}".encode(),
        b"--build-arg",
        b"BUILD_CREATED=2026-09-04T00:00:00+00:00",
        b"--tag",
        f"edu-ai-lead-agent-backend:brand-embedding-{RELEASE_COMMIT[:12]}".encode(),
        f"{worktree!s}/backend".encode(),
    ]


def test_buildx_uses_loadable_normalized_oci_reference_annotations(
    tmp_path: Path,
) -> None:
    capture = tmp_path / "buildx.argv"
    scratch = tmp_path / "scratch"
    worktree = tmp_path / "worktree"
    transport_tag = f"edu-ai-lead-agent-backend:brand-embedding-{RELEASE_COMMIT[:12]}"
    normalized = VALIDATOR.normalize_containerd_reference(transport_tag)
    short = transport_tag.rsplit(":", 1)[1]
    result = _source_builder_shell(
        f"""
scratch={scratch!s}
worktree={worktree!s}
release_sha={RELEASE_COMMIT}
transport_tag={transport_tag}
containerd_reference={normalized}
short_transport_reference={short}
capture={capture!s}
env() {{ printf '%s\\0' "$@" >"$capture"; }}
run_buildx_image 2026-09-04T00:00:00+00:00 {tmp_path / "image.oci.tar"!s}
"""
    )
    assert result.returncode == 0, result.stderr
    argv = capture.read_bytes().split(b"\0")[:-1]
    assert f"manifest-descriptor:io.containerd.image.name={normalized}".encode() in argv
    assert (
        f"manifest-descriptor:org.opencontainers.image.ref.name={short}".encode()
        in argv
    )
    assert (
        f"manifest-descriptor:io.containerd.image.name={transport_tag}".encode()
        not in argv
    )


def test_legacy_raw_tag_is_discarded_only_after_owned_build(tmp_path: Path) -> None:
    calls = tmp_path / "discard.calls"
    transport_tag = f"edu-ai-lead-agent-backend:brand-embedding-{RELEASE_COMMIT[:12]}"
    result = _source_builder_shell(
        f"""
IFS=' '
candidate_image_owned=1
transport_tag={transport_tag}
legacy_builder_image_id=sha256:{"4" * 64}
candidate_owned_image_id=$legacy_builder_image_id
removed=0
docker_clean() {{
  printf '%s\n' "$*" >>{calls!s}
  case "$*" in
    "image inspect --format {{{{.Id}}}} {transport_tag}")
      [[ "$removed" == 0 ]] || return 1
      printf 'sha256:%s\n' '{"4" * 64}'
      ;;
    "image rm {transport_tag}") removed=1 ;;
    "image ls --quiet --filter reference={transport_tag}")
      [[ "$removed" == 1 ]]
      ;;
    *) return 90 ;;
  esac
}}
discard_owned_legacy_transport_tag
printf 'owned=%s:%s\n' "$candidate_image_owned" "$candidate_owned_image_id"
"""
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "owned=0:\n"
    assert calls.read_text(encoding="utf-8").splitlines() == [
        f"image inspect --format {{{{.Id}}}} {transport_tag}",
        f"image rm {transport_tag}",
        f"image ls --quiet --filter reference={transport_tag}",
    ]


def test_legacy_raw_tag_discard_refuses_unowned_reference(tmp_path: Path) -> None:
    calls = tmp_path / "discard.calls"
    result = _source_builder_shell(
        f"""
candidate_image_owned=0
transport_tag=edu-ai-lead-agent-backend:brand-embedding-{RELEASE_COMMIT[:12]}
legacy_builder_image_id=sha256:{"4" * 64}
docker_clean() {{ touch {calls!s}; }}
discard_owned_legacy_transport_tag
"""
    )
    assert result.returncode != 0
    assert "ownership is unavailable" in result.stderr
    assert not calls.exists()


def test_legacy_builder_identity_is_bound_before_raw_tag_removal(
    tmp_path: Path,
) -> None:
    calls = tmp_path / "legacy-bind.calls"
    transport_tag = f"edu-ai-lead-agent-backend:brand-embedding-{RELEASE_COMMIT[:12]}"
    image_id = "sha256:" + "4" * 64
    result = _source_builder_shell(
        f"""
IFS=' '
candidate_image_owned=0
candidate_owned_image_id=
transport_tag={transport_tag}
docker_clean() {{
  printf '%s\n' "$*" >>{calls!s}
  printf '%s\n' {image_id}
}}
bind_legacy_builder_image_identity
printf 'owned=%s:%s:%s\n' \
  "$candidate_image_owned" "$candidate_owned_image_id" "$legacy_builder_image_id"
candidate_image_owned=0
"""
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == f"owned=1:{image_id}:{image_id}\n"
    assert calls.read_text(encoding="utf-8").splitlines() == [
        f"image inspect --format {{{{.Id}}}} {transport_tag}"
    ]


def test_legacy_raw_tag_discard_rejects_identity_drift(tmp_path: Path) -> None:
    calls = tmp_path / "discard.calls"
    transport_tag = f"edu-ai-lead-agent-backend:brand-embedding-{RELEASE_COMMIT[:12]}"
    result = _source_builder_shell(
        f"""
IFS=' '
candidate_image_owned=1
transport_tag={transport_tag}
legacy_builder_image_id=sha256:{"4" * 64}
candidate_owned_image_id=$legacy_builder_image_id
docker_clean() {{
  printf '%s\n' "$*" >>{calls!s}
  if [[ "$*" == "image inspect --format {{{{.Id}}}} {transport_tag}" ]]; then
    printf 'sha256:%s\n' '{"5" * 64}'
    return 0
  fi
  return 90
}}
discard_owned_legacy_transport_tag
"""
    )
    assert result.returncode != 0
    assert "identity changed" in result.stderr
    assert (
        f"image rm {transport_tag}"
        not in calls.read_text(encoding="utf-8").splitlines()
    )


def test_load_preflight_abandons_ownership_when_transport_tag_appears(
    tmp_path: Path,
) -> None:
    calls = tmp_path / "load-preflight.calls"
    transport_tag = f"edu-ai-lead-agent-backend:brand-embedding-{RELEASE_COMMIT[:12]}"
    result = _source_builder_shell(
        f"""
IFS=' '
candidate_image_owned=1
candidate_reference_owned=1
candidate_owned_image_id=sha256:{"4" * 64}
transport_tag={transport_tag}
docker_clean() {{
  printf '%s\n' "$*" >>{calls!s}
  printf 'sha256:%s\n' '{"5" * 64}'
}}
assert_transport_tag_absent_before_load
"""
    )
    assert result.returncode != 0
    assert "appeared before validated OCI load" in result.stderr
    assert calls.read_text(encoding="utf-8").splitlines() == [
        f"image ls --quiet --filter reference={transport_tag}"
    ]
    assert f"image rm {transport_tag}" not in calls.read_text(encoding="utf-8")


def test_load_preflight_does_not_treat_docker_error_as_tag_absence(
    tmp_path: Path,
) -> None:
    calls = tmp_path / "load-preflight-error.calls"
    transport_tag = f"edu-ai-lead-agent-backend:brand-embedding-{RELEASE_COMMIT[:12]}"
    result = _source_builder_shell(
        f"""
IFS=' '
candidate_image_owned=1
candidate_reference_owned=1
candidate_owned_image_id=sha256:{"4" * 64}
transport_tag={transport_tag}
docker_clean() {{
  printf '%s\n' "$*" >>{calls!s}
  return 72
}}
assert_transport_tag_absent_before_load
"""
    )
    assert result.returncode != 0
    assert "load preflight failed" in result.stderr
    assert calls.read_text(encoding="utf-8").splitlines() == [
        f"image ls --quiet --filter reference={transport_tag}"
    ]


def test_cleanup_abandons_transport_tag_that_drifted_after_load(
    tmp_path: Path,
) -> None:
    calls = tmp_path / "cleanup-drift.calls"
    transport_tag = f"edu-ai-lead-agent-backend:brand-embedding-{RELEASE_COMMIT[:12]}"
    result = _source_builder_shell(
        f"""
IFS=' '
candidate_image_owned=1
candidate_reference_owned=1
candidate_owned_image_id=sha256:{"4" * 64}
transport_tag={transport_tag}
candidate_reference=edu-ai-lead-agent-backend@sha256:{"1" * 64}
docker_clean() {{
  printf '%s\n' "$*" >>{calls!s}
  printf 'sha256:%s\n' '{"5" * 64}'
}}
cleanup_candidate_image
printf 'owned=%s:%s:%s\n' \
  "$candidate_image_owned" "$candidate_reference_owned" "$candidate_owned_image_id"
"""
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "owned=0:0:\n"
    assert calls.read_text(encoding="utf-8").splitlines() == [
        f"image inspect --format {{{{.Id}}}} {transport_tag}"
    ]


def test_builder_identity_mismatch_diagnostic_contains_only_sha256_identities() -> None:
    config_digest = "sha256:" + "a" * 64
    manifest_digest = "sha256:" + "b" * 64
    loaded_digest = "sha256:" + "c" * 64
    result = _source_builder_shell(
        f"""
candidate_config_digest={config_digest}
candidate_manifest_digest={manifest_digest}
candidate_image_owned=1
candidate_reference_owned=1
candidate_owned_image_id=sha256:{"d" * 64}
transport_tag=edu-ai-lead-agent-backend:brand-embedding-{RELEASE_COMMIT[:12]}
bind_loaded_candidate_image_identity {loaded_digest}
"""
    )
    assert result.returncode != 0
    assert (
        result.stderr.splitlines()[0]
        == "[brand-embedding-builder] image identity mismatch "
        f"manifest={manifest_digest} config={config_digest} loaded={loaded_digest}"
    )
    assert f"brand-embedding-{RELEASE_COMMIT[:12]}" not in result.stderr


def test_builder_malformed_loaded_identity_is_not_echoed() -> None:
    result = _source_builder_shell(
        f"""
candidate_config_digest=sha256:{"a" * 64}
candidate_manifest_digest=sha256:{"b" * 64}
candidate_image_owned=1
candidate_reference_owned=1
candidate_owned_image_id=sha256:{"d" * 64}
bind_loaded_candidate_image_identity unsafe-loaded-value
"""
    )
    assert result.returncode != 0
    assert "not a SHA-256 identity" in result.stderr
    assert "unsafe-loaded-value" not in result.stderr


@pytest.mark.parametrize("identity_kind", ["config", "manifest"])
def test_builder_accepts_exact_image_id_for_both_docker_image_stores(
    identity_kind: str,
) -> None:
    config_digest = "sha256:" + "a" * 64
    manifest_digest = "sha256:" + "b" * 64
    loaded_id = config_digest if identity_kind == "config" else manifest_digest
    result = _source_builder_shell(
        f"""
candidate_config_digest={config_digest}
candidate_manifest_digest={manifest_digest}
candidate_image_owned=0
candidate_reference_owned=1
candidate_owned_image_id=
bind_loaded_candidate_image_identity {loaded_id}
printf 'owned=%s:%s\n' "$candidate_image_owned" "$candidate_owned_image_id"
candidate_image_owned=0
"""
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == f"owned=1:{loaded_id}\n"


def test_builder_rejects_image_id_outside_validated_oci_graph() -> None:
    result = _source_builder_shell(
        f"""
candidate_config_digest=sha256:{"a" * 64}
candidate_manifest_digest=sha256:{"b" * 64}
loaded_image_id_matches_candidate sha256:{"c" * 64}
"""
    )
    assert result.returncode != 0


@pytest.mark.parametrize("mutation", ["", "dangling"])
def test_builder_strictly_validates_oci_graph_before_loading(
    tmp_path: Path, mutation: str
) -> None:
    stage = _stage(tmp_path)
    if mutation:
        _rewrite_oci(stage, mutation)
    members_before = {path.relative_to(stage).as_posix() for path in stage.rglob("*")}
    metadata = json.loads((stage / "release-metadata.json").read_bytes())
    result = _source_builder_shell(
        f"""
stage={stage!s}
release_sha={metadata["release_commit"]}
transport_tag={metadata["transport_tag"]}
candidate_repository={metadata["candidate_repository"]}
candidate_reference={metadata["candidate_reference"]}
candidate_config_digest={metadata["candidate_config_digest"]}
candidate_manifest_digest={str(metadata["candidate_reference"]).rsplit("@", 1)[1]}
validate_candidate_image_graph
"""
    )
    assert (result.returncode != 0) is bool(mutation), result.stderr
    assert {
        path.relative_to(stage).as_posix() for path in stage.rglob("*")
    } == members_before
    assert not (stage / "__pycache__").exists()
    if not mutation:
        VALIDATOR.validate_stage(stage)

    builder = BUILDER_PATH.read_text(encoding="utf-8")
    validation_call = "  validate_candidate_image_graph \\\n"
    validated_load = (
        '  gzip -dc "$stage/backend-image.oci.tar.gz" | docker image load >/dev/null'
    )
    assert builder.index(validation_call) < builder.index(validated_load)
    assert (
        builder.index(validation_call)
        < builder.index("    discard_owned_legacy_transport_tag || return 1")
        < builder.index(validated_load)
    )
    assert 'docker image load -i "$raw_archive"' not in builder


def test_candidate_image_cleanup_is_scoped_to_derived_references(
    tmp_path: Path,
) -> None:
    calls = tmp_path / "cleanup.calls"
    result = _source_builder_shell(
        f"""
IFS=' '
scratch=/tmp/brand-builder-test
candidate_image_owned=1
candidate_reference_owned=1
candidate_owned_image_id=sha256:{"2" * 64}
transport_tag=edu-ai-lead-agent-backend:brand-embedding-{RELEASE_COMMIT[:12]}
candidate_reference=edu-ai-lead-agent-backend@sha256:{"1" * 64}
docker_clean() {{
  printf '%s\n' "$*" >>{calls!s}
  printf 'sha256:%s\n' '{"2" * 64}'
}}
cleanup_candidate_image
printf 'owned=%s:%s\n' "$candidate_image_owned" "$candidate_owned_image_id"
"""
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "owned=0:\n"
    assert calls.read_text(encoding="utf-8").splitlines() == [
        (
            f"image inspect --format {{{{.Id}}}} "
            f"edu-ai-lead-agent-backend:brand-embedding-{RELEASE_COMMIT[:12]}"
        ),
        (
            f"image inspect --format {{{{.Id}}}} "
            f"edu-ai-lead-agent-backend@sha256:{'1' * 64}"
        ),
        f"image rm edu-ai-lead-agent-backend@sha256:{'1' * 64}",
        f"image rm edu-ai-lead-agent-backend:brand-embedding-{RELEASE_COMMIT[:12]}",
    ]


def test_candidate_cleanup_preserves_preexisting_repo_digest(tmp_path: Path) -> None:
    calls = tmp_path / "cleanup.calls"
    inventory = tmp_path / "preexisting-repo-digests"
    candidate = f"edu-ai-lead-agent-backend@sha256:{'1' * 64}"
    inventory.write_text(candidate + "\n", encoding="utf-8")
    result = _source_builder_shell(
        f"""
IFS=' '
scratch=/tmp/brand-builder-test
candidate_image_owned=1
candidate_reference_owned=0
candidate_owned_image_id=sha256:{"2" * 64}
preexisting_repo_digests={inventory!s}
transport_tag=edu-ai-lead-agent-backend:brand-embedding-{RELEASE_COMMIT[:12]}
candidate_reference={candidate}
docker_clean() {{
  printf '%s\n' "$*" >>{calls!s}
  printf 'sha256:%s\n' '{"2" * 64}'
}}
bind_candidate_reference_ownership
cleanup_candidate_image
printf 'owned=%s:%s\n' "$candidate_image_owned" "$candidate_reference_owned"
"""
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "owned=0:0\n"
    assert calls.read_text(encoding="utf-8").splitlines() == [
        (
            f"image inspect --format {{{{.Id}}}} "
            f"edu-ai-lead-agent-backend:brand-embedding-{RELEASE_COMMIT[:12]}"
        ),
        f"image rm edu-ai-lead-agent-backend:brand-embedding-{RELEASE_COMMIT[:12]}",
    ]


def _source_operator_shell(
    test_root: Path, body: str
) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment.update(
        {
            "BRAND_HOTFIX_OPERATOR_SOURCE_ONLY": "1",
            "BRAND_HOTFIX_OPERATOR_TEST_ROOT": str(test_root),
        }
    )
    return subprocess.run(
        ["bash", "-c", f"source {OPERATOR_PATH!s}\n{body}"],
        env=environment,
        check=False,
        text=True,
        capture_output=True,
    )


@pytest.mark.parametrize(
    ("mutation", "accepted"),
    [
        ("", True),
        ("missing-build", False),
        ("build-context", False),
        ("build-extra", False),
        ("pull-policy-build", False),
        ("image", False),
        ("command", False),
    ],
)
def test_operator_candidate_compose_binds_reviewed_inherited_build_metadata(
    tmp_path: Path, mutation: str, accepted: bool
) -> None:
    app_dir = tmp_path / "app"
    app_dir.mkdir()
    candidate_reference = f"{REPOSITORY}@sha256:{'b' * 64}"
    services: dict[str, dict[str, object]] = {
        name: {
            "build": {
                "context": str(app_dir / "backend"),
                "dockerfile": "Dockerfile",
            },
            "command": list(VALIDATOR.SERVICE_COMMANDS[name]),
            "image": candidate_reference,
        }
        for name in VALIDATOR.APP_SERVICES
    }
    target = services[VALIDATOR.APP_SERVICES[0]]
    if mutation == "missing-build":
        del target["build"]
    elif mutation == "build-context":
        target_build = target["build"]
        assert isinstance(target_build, dict)
        target_build["context"] = str(tmp_path / "unreviewed")
    elif mutation == "build-extra":
        target_build = target["build"]
        assert isinstance(target_build, dict)
        target_build["args"] = {"UNREVIEWED": "1"}
    elif mutation == "pull-policy-build":
        target["pull_policy"] = "build"
    elif mutation == "image":
        target["image"] = "unreviewed:latest"
    elif mutation == "command":
        target["command"] = ["python", "unreviewed.py"]
    rendered = tmp_path / "compose.json"
    rendered.write_bytes(_json_bytes({"services": services}))

    result = _source_operator_shell(
        tmp_path,
        f"""
IFS=' '
candidate_reference={candidate_reference}
compose() {{
  [[ "$*" == "config --format json" ]] || return 90
  cat {rendered!s}
}}
verify_candidate_compose
""",
    )

    assert (result.returncode == 0) is accepted, result.stderr
    if not accepted:
        assert "candidate Compose topology validation failed" in result.stderr


@pytest.mark.parametrize("identity_kind", ["config", "manifest"])
def test_operator_accepts_exact_image_id_for_both_docker_image_stores(
    tmp_path: Path, identity_kind: str
) -> None:
    config_digest = "sha256:" + "a" * 64
    manifest_digest = "sha256:" + "b" * 64
    loaded_id = config_digest if identity_kind == "config" else manifest_digest
    result = _source_operator_shell(
        tmp_path,
        f"""
candidate_config_digest={config_digest}
candidate_manifest_digest={manifest_digest}
loaded_image_id_matches_candidate {loaded_id}
""",
    )
    assert result.returncode == 0, result.stderr


def test_operator_rejects_image_id_outside_validated_oci_graph(
    tmp_path: Path,
) -> None:
    result = _source_operator_shell(
        tmp_path,
        f"""
candidate_config_digest=sha256:{"a" * 64}
candidate_manifest_digest=sha256:{"b" * 64}
loaded_image_id_matches_candidate sha256:{"c" * 64}
""",
    )
    assert result.returncode != 0


def test_operator_rejects_successful_load_without_transport_tag(
    tmp_path: Path,
) -> None:
    stage = tmp_path / "stage"
    stage.mkdir()
    (stage / "backend-image.oci.tar.gz").write_bytes(b"not-read-by-stub")
    transport_tag = f"edu-ai-lead-agent-backend:brand-embedding-{RELEASE_COMMIT[:12]}"
    result = _source_operator_shell(
        tmp_path,
        f"""
IFS=' '
stage_dir={stage!s}
transport_tag={transport_tag}
gzip() {{ return 0; }}
docker() {{
  case "$*" in
    "image ls --quiet --no-trunc --filter reference={transport_tag}") return 0 ;;
    "image ls --digests --format {{{{.Repository}}}}@{{{{.Digest}}}}") return 0 ;;
    "image load") return 0 ;;
    "image inspect --format {{{{.Id}}}} {transport_tag}") return 1 ;;
    *) return 90 ;;
  esac
}}
load_and_verify_candidate
""",
    )
    assert result.returncode != 0
    assert "did not create the transport tag" in result.stderr


def test_operator_source_probe_failure_cleans_only_the_owned_inactive_candidate(
    tmp_path: Path,
) -> None:
    stage = tmp_path / "stage"
    stage.mkdir()
    (stage / "backend-image.oci.tar.gz").write_bytes(b"not-read-by-stub")
    calls = tmp_path / "docker.calls"
    transport_tag = f"{REPOSITORY}:brand-embedding-{RELEASE_COMMIT[:12]}"
    candidate_id = "sha256:" + "b" * 64
    candidate_reference = f"{REPOSITORY}@{candidate_id}"
    baseline_id = "sha256:" + "d" * 64
    result = _source_operator_shell(
        tmp_path,
        f"""
IFS=' '
stage_dir={stage!s}
transport_tag={transport_tag}
candidate_reference={candidate_reference}
candidate_manifest_digest={candidate_id}
candidate_config_digest=sha256:{"a" * 64}
gzip() {{ return 0; }}
docker() {{
  printf '%s\n' "$*" >>{calls!s}
  case "$*" in
    "image ls --quiet --no-trunc --filter reference={transport_tag}") return 0 ;;
    "image ls --digests --format {{{{.Repository}}}}@{{{{.Digest}}}}") return 0 ;;
    "image load") return 0 ;;
    "image inspect --format {{{{.Id}}}} {transport_tag}") printf '%s\n' {candidate_id} ;;
    "image inspect --format {{{{range .RepoDigests}}}}{{{{println .}}}}{{{{end}}}} {transport_tag}")
      printf '%s\n' {candidate_reference}
      ;;
    "image inspect --format {{{{.Id}}}} {candidate_reference}") printf '%s\n' {candidate_id} ;;
    "run "*"--env-file "*) return 0 ;;
    "run "*) printf 'not-the-reviewed-manifest\n' ;;
    "container ls --all --quiet --no-trunc") printf 'running-baseline\n' ;;
    "container inspect --format {{{{.Image}}}} running-baseline") printf '%s\n' {baseline_id} ;;
    "image rm {candidate_reference}") return 0 ;;
    "image rm {transport_tag}") return 0 ;;
    *) return 90 ;;
  esac
}}
if load_and_verify_candidate; then
  rc=0
else
  rc=$?
fi
cleanup_candidate_image
printf 'rc=%s owned=%s:%s\n' "$rc" "$candidate_image_owned" "$candidate_reference_owned"
""",
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "rc=1 owned=0:0\n"
    assert "loaded image source differs from the complete manifest" in result.stderr
    docker_calls = calls.read_text(encoding="utf-8").splitlines()
    assert "container inspect --format {{.Image}} running-baseline" in docker_calls
    assert [call for call in docker_calls if call.startswith("image rm ")] == [
        f"image rm {candidate_reference}",
        f"image rm {transport_tag}",
    ]
    assert baseline_id != candidate_id


def test_operator_preflight_source_mismatch_exits_before_quiescence(
    tmp_path: Path,
) -> None:
    events = tmp_path / "events"
    result = _source_operator_shell(
        tmp_path,
        f"""
EVENTS={events!s}
parse_args() {{ preflight_only=1; printf 'parse\n' >>"$EVENTS"; }}
require_physical_operator() {{ printf 'physical\n' >>"$EVENTS"; }}
validate_stage() {{ printf 'stage\n' >>"$EVENTS"; }}
require_safe_window() {{ printf 'window\n' >>"$EVENTS"; }}
verify_baseline() {{ printf 'baseline\n' >>"$EVENTS"; }}
load_and_verify_candidate() {{
  printf 'source-mismatch\n' >>"$EVENTS"
  die 'loaded image source differs from the complete manifest'
}}
verify_candidate_compose() {{ printf 'compose\n' >>"$EVENTS"; }}
reject_repeat() {{ printf 'repeat\n' >>"$EVENTS"; }}
run_activation() {{ printf 'quiesce\n' >>"$EVENTS"; }}
main --stage-dir /unused --scheduler-cutoff-utc 2099-01-01T00:00:00Z --preflight-only
""",
    )

    assert result.returncode != 0
    assert "loaded image source differs from the complete manifest" in result.stderr
    assert events.read_text(encoding="utf-8").splitlines() == [
        "parse",
        "physical",
        "stage",
        "window",
        "baseline",
        "source-mismatch",
    ]


def test_operator_preflight_compose_mismatch_exits_before_quiescence(
    tmp_path: Path,
) -> None:
    events = tmp_path / "events"
    result = _source_operator_shell(
        tmp_path,
        f"""
EVENTS={events!s}
parse_args() {{ preflight_only=1; printf 'parse\n' >>"$EVENTS"; }}
require_physical_operator() {{ printf 'physical\n' >>"$EVENTS"; }}
validate_stage() {{ printf 'stage\n' >>"$EVENTS"; }}
require_safe_window() {{ printf 'window\n' >>"$EVENTS"; }}
verify_baseline() {{ printf 'baseline\n' >>"$EVENTS"; }}
load_and_verify_candidate() {{ printf 'candidate\n' >>"$EVENTS"; }}
verify_candidate_compose() {{
  printf 'compose-mismatch\n' >>"$EVENTS"
  die 'candidate Compose topology validation failed'
}}
reject_repeat() {{ printf 'repeat\n' >>"$EVENTS"; }}
run_activation() {{ printf 'quiesce\n' >>"$EVENTS"; }}
main --stage-dir /unused --scheduler-cutoff-utc 2099-01-01T00:00:00Z --preflight-only
""",
    )

    assert result.returncode != 0
    assert "candidate Compose topology validation failed" in result.stderr
    assert events.read_text(encoding="utf-8").splitlines() == [
        "parse",
        "physical",
        "stage",
        "window",
        "baseline",
        "candidate",
        "compose-mismatch",
    ]


def test_operator_cleanup_preserves_a_candidate_used_by_any_container(
    tmp_path: Path,
) -> None:
    calls = tmp_path / "docker.calls"
    transport_tag = f"{REPOSITORY}:brand-embedding-{RELEASE_COMMIT[:12]}"
    candidate_id = "sha256:" + "b" * 64
    candidate_reference = f"{REPOSITORY}@{candidate_id}"
    result = _source_operator_shell(
        tmp_path,
        f"""
IFS=' '
transport_tag={transport_tag}
candidate_reference={candidate_reference}
candidate_image_owned=1
candidate_reference_owned=1
candidate_owned_image_id={candidate_id}
docker() {{
  printf '%s\n' "$*" >>{calls!s}
  case "$*" in
    "image inspect --format {{{{.Id}}}} {transport_tag}") printf '%s\n' {candidate_id} ;;
    "container ls --all --quiet --no-trunc") printf 'candidate-container\n' ;;
    "container inspect --format {{{{.Image}}}} candidate-container") printf '%s\n' {candidate_id} ;;
    *) return 90 ;;
  esac
}}
cleanup_candidate_image
printf 'owned=%s:%s\n' "$candidate_image_owned" "$candidate_reference_owned"
""",
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "owned=0:0\n"
    assert not any(
        call.startswith("image rm ")
        for call in calls.read_text(encoding="utf-8").splitlines()
    )


def test_operator_cleanup_preserves_candidate_when_container_inventory_fails(
    tmp_path: Path,
) -> None:
    calls = tmp_path / "docker.calls"
    transport_tag = f"{REPOSITORY}:brand-embedding-{RELEASE_COMMIT[:12]}"
    candidate_id = "sha256:" + "b" * 64
    candidate_reference = f"{REPOSITORY}@{candidate_id}"
    result = _source_operator_shell(
        tmp_path,
        f"""
IFS=' '
transport_tag={transport_tag}
candidate_reference={candidate_reference}
candidate_image_owned=1
candidate_reference_owned=1
candidate_owned_image_id={candidate_id}
docker() {{
  printf '%s\n' "$*" >>{calls!s}
  case "$*" in
    "image inspect --format {{{{.Id}}}} {transport_tag}") printf '%s\n' {candidate_id} ;;
    "container ls --all --quiet --no-trunc") return 72 ;;
    *) return 90 ;;
  esac
}}
cleanup_candidate_image
printf 'owned=%s:%s\n' "$candidate_image_owned" "$candidate_reference_owned"
""",
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "owned=0:0\n"
    docker_calls = calls.read_text(encoding="utf-8").splitlines()
    assert docker_calls == [
        f"image inspect --format {{{{.Id}}}} {transport_tag}",
        "container ls --all --quiet --no-trunc",
    ]
    assert not any(call.startswith("image rm ") for call in docker_calls)


@pytest.mark.parametrize("failure", ["reference-inspect", "reference-drift"])
def test_operator_cleanup_preserves_candidate_when_owned_reference_is_uncertain(
    tmp_path: Path, failure: str
) -> None:
    calls = tmp_path / "docker.calls"
    transport_tag = f"{REPOSITORY}:brand-embedding-{RELEASE_COMMIT[:12]}"
    candidate_id = "sha256:" + "b" * 64
    candidate_reference = f"{REPOSITORY}@{candidate_id}"
    reference_result = (
        "return 72"
        if failure == "reference-inspect"
        else f"printf '%s\\n' sha256:{'c' * 64}"
    )
    result = _source_operator_shell(
        tmp_path,
        f"""
IFS=' '
transport_tag={transport_tag}
candidate_reference={candidate_reference}
candidate_image_owned=1
candidate_reference_owned=1
candidate_owned_image_id={candidate_id}
docker() {{
  printf '%s\n' "$*" >>{calls!s}
  case "$*" in
    "image inspect --format {{{{.Id}}}} {transport_tag}") printf '%s\n' {candidate_id} ;;
    "container ls --all --quiet --no-trunc") return 0 ;;
    "image inspect --format {{{{.Id}}}} {candidate_reference}") {reference_result} ;;
    *) return 90 ;;
  esac
}}
cleanup_candidate_image
printf 'owned=%s:%s\n' "$candidate_image_owned" "$candidate_reference_owned"
""",
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "owned=0:0\n"
    docker_calls = calls.read_text(encoding="utf-8").splitlines()
    assert docker_calls == [
        f"image inspect --format {{{{.Id}}}} {transport_tag}",
        "container ls --all --quiet --no-trunc",
        f"image inspect --format {{{{.Id}}}} {candidate_reference}",
    ]
    assert not any(call.startswith("image rm ") for call in docker_calls)


def test_operator_cleanup_preserves_candidate_when_container_inspect_fails(
    tmp_path: Path,
) -> None:
    calls = tmp_path / "docker.calls"
    transport_tag = f"{REPOSITORY}:brand-embedding-{RELEASE_COMMIT[:12]}"
    candidate_id = "sha256:" + "b" * 64
    result = _source_operator_shell(
        tmp_path,
        f"""
IFS=' '
transport_tag={transport_tag}
candidate_image_owned=1
candidate_reference_owned=1
candidate_owned_image_id={candidate_id}
docker() {{
  printf '%s\n' "$*" >>{calls!s}
  case "$*" in
    "image inspect --format {{{{.Id}}}} {transport_tag}") printf '%s\n' {candidate_id} ;;
    "container ls --all --quiet --no-trunc") printf 'unknown-container\n' ;;
    "container inspect --format {{{{.Image}}}} unknown-container") return 72 ;;
    *) return 90 ;;
  esac
}}
cleanup_candidate_image
printf 'owned=%s:%s\n' "$candidate_image_owned" "$candidate_reference_owned"
""",
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "owned=0:0\n"
    docker_calls = calls.read_text(encoding="utf-8").splitlines()
    assert docker_calls == [
        f"image inspect --format {{{{.Id}}}} {transport_tag}",
        "container ls --all --quiet --no-trunc",
        "container inspect --format {{.Image}} unknown-container",
    ]
    assert not any(call.startswith("image rm ") for call in docker_calls)


def test_operator_cleanup_preserves_transport_tag_after_identity_drift(
    tmp_path: Path,
) -> None:
    calls = tmp_path / "docker.calls"
    transport_tag = f"{REPOSITORY}:brand-embedding-{RELEASE_COMMIT[:12]}"
    candidate_id = "sha256:" + "b" * 64
    drifted_id = "sha256:" + "c" * 64
    result = _source_operator_shell(
        tmp_path,
        f"""
IFS=' '
transport_tag={transport_tag}
candidate_image_owned=1
candidate_reference_owned=1
candidate_owned_image_id={candidate_id}
docker() {{
  printf '%s\n' "$*" >>{calls!s}
  case "$*" in
    "image inspect --format {{{{.Id}}}} {transport_tag}") printf '%s\n' {drifted_id} ;;
    *) return 90 ;;
  esac
}}
cleanup_candidate_image
printf 'owned=%s:%s\n' "$candidate_image_owned" "$candidate_reference_owned"
""",
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == "owned=0:0\n"
    docker_calls = calls.read_text(encoding="utf-8").splitlines()
    assert docker_calls == [f"image inspect --format {{{{.Id}}}} {transport_tag}"]
    assert not any(call.startswith("image rm ") for call in docker_calls)


def test_operator_reuses_but_never_owns_an_exact_preloaded_candidate(
    tmp_path: Path,
) -> None:
    calls = tmp_path / "docker.calls"
    transport_tag = f"{REPOSITORY}:brand-embedding-{RELEASE_COMMIT[:12]}"
    candidate_id = "sha256:" + "b" * 64
    candidate_reference = f"{REPOSITORY}@{candidate_id}"
    result = _source_operator_shell(
        tmp_path,
        f"""
IFS=' '
transport_tag={transport_tag}
candidate_reference={candidate_reference}
candidate_manifest_digest={candidate_id}
candidate_config_digest=sha256:{"a" * 64}
docker() {{
  printf '%s\n' "$*" >>{calls!s}
  case "$*" in
    "image ls --quiet --no-trunc --filter reference={transport_tag}") printf '%s\n' {candidate_id} ;;
    "image inspect --format {{{{.Id}}}} {transport_tag}") printf '%s\n' {candidate_id} ;;
    "image inspect --format {{{{range .RepoDigests}}}}{{{{println .}}}}{{{{end}}}} {transport_tag}")
      printf '%s\n' {candidate_reference}
      ;;
    "image inspect --format {{{{.Id}}}} {candidate_reference}") printf '%s\n' {candidate_id} ;;
    *) return 90 ;;
  esac
}}
load_or_reuse_candidate_image
cleanup_candidate_image
printf 'runtime=%s owned=%s:%s\n' \
  "$candidate_runtime_image_id" "$candidate_image_owned" "$candidate_reference_owned"
""",
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout == f"runtime={candidate_id} owned=0:0\n"
    docker_calls = calls.read_text(encoding="utf-8").splitlines()
    assert "image load" not in docker_calls
    assert not any(call.startswith("image rm ") for call in docker_calls)


def test_candidate_readiness_uses_the_observed_docker_image_id() -> None:
    operator = OPERATOR_PATH.read_text(encoding="utf-8")
    assert 'verify_service_set "$candidate_runtime_image_id" zero' in operator
    assert 'verify_service_set "$candidate_config_digest" zero' not in operator
    reference_gate = "docker image inspect --format '{{.Id}}' \"$candidate_reference\""
    assert operator.index(reference_gate) < operator.index(
        "candidate_runtime_image_id=$loaded_id"
    )


@pytest.mark.parametrize("drift_service", ["", "content-worker"])
def test_candidate_service_set_binds_all_twelve_apps_to_observed_image_id(
    tmp_path: Path, drift_service: str
) -> None:
    observed_id = "sha256:" + "b" * 64
    image_checks = tmp_path / "image-checks"
    result = _source_operator_shell(
        tmp_path,
        f"""
IFS=' '
EXPECTED_IMAGE={observed_id}
DRIFT_SERVICE={drift_service}
IMAGE_CHECKS={image_checks!s}
compose() {{
  if [[ "$*" == "ps --services --status running" ]]; then
    printf '%s\n' "${{ALL_SERVICES[@]}}" | tr ' ' '\n' | sort
    return
  fi
  if [[ "$1 $2" == "ps -q" ]]; then
    printf 'container-%s\n' "$3"
    return
  fi
  return 90
}}
docker() {{
  local format=$3 container=$4 service=${{4#container-}}
  [[ "$1 $2" == "inspect --format" ]] || return 91
  case "$format" in
    '{{{{.State.Status}}}}') printf 'running\n' ;;
    '{{{{.RestartCount}}}}') printf '0\n' ;;
    '{{{{if .State.Health}}}}{{{{.State.Health.Status}}}}{{{{end}}}}') printf 'healthy\n' ;;
    '{{{{.Image}}}}')
      printf '%s\n' "$service" >>"$IMAGE_CHECKS"
      if [[ -n "$DRIFT_SERVICE" && "$service" == "$DRIFT_SERVICE" ]]; then
        printf 'sha256:%064d\n' 0
      else
        printf '%s\n' "$EXPECTED_IMAGE"
      fi
      ;;
    *) return 92 ;;
  esac
}}
candidate_runtime_image_id=$EXPECTED_IMAGE
verify_service_set "$candidate_runtime_image_id" zero
""",
    )
    assert (result.returncode != 0) is bool(drift_service), result.stderr
    checked_services = image_checks.read_text(encoding="utf-8").splitlines()
    if not drift_service:
        assert checked_services == list(VALIDATOR.APP_SERVICES)
    else:
        assert checked_services[-1] == drift_service


@pytest.mark.parametrize(
    ("drift", "accepted"),
    [
        ("", True),
        ("date", False),
        ("boundary", False),
        ("effects", False),
        ("cohort", False),
    ],
)
def test_copy_state_gate_binds_business_date_and_frozen_cohort(
    tmp_path: Path, drift: str, accepted: bool
) -> None:
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_bytes(_json_bytes(_baseline()))
    date_calls = tmp_path / "date-calls"
    date_calls.write_text("0\n", encoding="utf-8")
    body = f"""
baseline_json={baseline_path!s}
current_business_date() {{
  if [[ {drift!r} == date ]]; then printf '2026-09-05\\n'; return; fi
  if [[ {drift!r} == boundary ]]; then
    value=$(cat {date_calls!s})
    value=$((value + 1))
    printf '%s\\n' "$value" >{date_calls!s}
    [[ $value -eq 1 ]] && printf '2026-09-04\\n' || printf '2026-09-05\\n'
    return
  fi
  printf '2026-09-04\\n'
}}
effect_counts() {{
  [[ {drift!r} == effects ]] && printf 'drifted\\n' || baseline_effect_counts
}}
frozen_copy_cohort() {{
  [[ {drift!r} == cohort ]] && printf '7:{"5" * 64}\\n' || baseline_frozen_copy_cohort
}}
copy_state_matches_baseline
"""
    result = _source_operator_shell(tmp_path, body)
    assert (result.returncode == 0) is accepted


def test_candidate_source_cannot_omit_a_captured_production_path(
    tmp_path: Path,
) -> None:
    stage = tmp_path / "stage"
    stage.mkdir()
    _write_source(stage)
    baseline = tmp_path / "baseline.json"
    baseline.write_bytes(
        _json_bytes(
            {
                "source_manifest": [
                    {
                        "kind": "f",
                        "path": "legacy-only.txt",
                        "mode": 0o600,
                        "uid": 0,
                        "gid": 0,
                        "sha256": "1" * 64,
                    }
                ]
            }
        )
    )
    workspace = tmp_path / "workspace"
    workspace.mkdir()

    result = _source_operator_shell(
        tmp_path,
        "\n".join(
            (
                f"workspace={workspace!s}",
                f"stage_dir={stage!s}",
                f"baseline_json={baseline!s}",
                "prepare_candidate_source",
            )
        ),
    )

    assert result.returncode != 0
    assert "candidate source omits a captured production path" in result.stderr


def test_operator_rejects_repeat_and_expired_cutoff(tmp_path: Path) -> None:
    attempts = tmp_path / "attempts"
    attempts.mkdir()
    marker = attempts / f"{RELEASE_COMMIT}.brand-embedding-attempted"
    marker.write_text("attempted\n", encoding="utf-8")
    result = _source_operator_shell(
        tmp_path,
        f"release_commit={RELEASE_COMMIT}\nreject_repeat",
    )
    assert result.returncode != 0
    assert "already attempted" in result.stderr

    result = _source_operator_shell(
        tmp_path / "cutoff",
        "scheduler_cutoff_utc=2000-01-01T00:00:00Z\nrequire_safe_window",
    )
    assert result.returncode != 0


@pytest.mark.parametrize("mutation", ["mode", "owner", "group", "bytes"])
def test_operator_rejects_primary_environment_drift(
    tmp_path: Path, mutation: str
) -> None:
    app = tmp_path / "app"
    app.mkdir(parents=True)
    primary_env = app / ".env"
    primary_env.write_text("safe\n", encoding="utf-8")
    primary_env.chmod(0o600)
    os.chown(primary_env, 1000, 1001)
    baseline = _baseline()
    baseline["primary_env_sha256"] = _digest(b"safe\n")
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_bytes(_json_bytes(baseline))
    if mutation == "mode":
        primary_env.chmod(0o640)
    elif mutation == "owner":
        os.chown(primary_env, 0, 1001)
    elif mutation == "group":
        os.chown(primary_env, 1000, 0)
    else:
        primary_env.write_text("drifted\n", encoding="utf-8")

    result = _source_operator_shell(
        tmp_path,
        f"baseline_json={baseline_path!s}\nprimary_env_matches_baseline",
    )

    assert result.returncode != 0


def test_primary_environment_rollback_restores_bytes_mode_and_owner(
    tmp_path: Path,
) -> None:
    app = tmp_path / "app"
    backup = tmp_path / "backup"
    app.mkdir(parents=True)
    backup.mkdir()
    expected = b"safe\n"
    saved_env = backup / "env.before"
    saved_env.write_bytes(expected)
    saved_env.chmod(0o600)
    os.chown(saved_env, 1000, 1001)
    primary_env = app / ".env"
    primary_env.write_bytes(b"drifted\n")
    primary_env.chmod(0o644)
    os.chown(primary_env, 0, 0)
    baseline = _baseline()
    baseline["primary_env_sha256"] = _digest(expected)
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_bytes(_json_bytes(baseline))

    result = _source_operator_shell(
        tmp_path,
        "\n".join(
            (
                f"baseline_json={baseline_path!s}",
                f"backup_dir={backup!s}",
                "restore_primary_environment_from_backup",
            )
        ),
    )

    assert result.returncode == 0, result.stderr
    assert primary_env.read_bytes() == expected
    assert primary_env.stat().st_mode & 0o777 == 0o600
    assert (primary_env.stat().st_uid, primary_env.stat().st_gid) == (1000, 1001)


def test_primary_environment_rollback_rejects_invalid_backup(
    tmp_path: Path,
) -> None:
    app = tmp_path / "app"
    backup = tmp_path / "backup"
    app.mkdir(parents=True)
    backup.mkdir()
    saved_env = backup / "env.before"
    saved_env.write_bytes(b"safe\n")
    saved_env.chmod(0o640)
    os.chown(saved_env, 1000, 1001)
    primary_env = app / ".env"
    primary_env.write_bytes(b"drifted\n")
    primary_env.chmod(0o644)
    baseline = _baseline()
    baseline["primary_env_sha256"] = _digest(b"safe\n")
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_bytes(_json_bytes(baseline))

    result = _source_operator_shell(
        tmp_path,
        "\n".join(
            (
                f"baseline_json={baseline_path!s}",
                f"backup_dir={backup!s}",
                "restore_primary_environment_from_backup",
            )
        ),
    )

    assert result.returncode != 0
    assert primary_env.read_bytes() == b"drifted\n"


def test_primary_environment_rollback_cleans_temporary_on_atomic_move_failure(
    tmp_path: Path,
) -> None:
    app = tmp_path / "app"
    backup = tmp_path / "backup"
    app.mkdir(parents=True)
    backup.mkdir()
    expected = b"safe\n"
    saved_env = backup / "env.before"
    saved_env.write_bytes(expected)
    saved_env.chmod(0o600)
    os.chown(saved_env, 1000, 1001)
    primary_env = app / ".env"
    primary_env.write_bytes(b"drifted\n")
    primary_env.chmod(0o644)
    baseline = _baseline()
    baseline["primary_env_sha256"] = _digest(expected)
    baseline_path = tmp_path / "baseline.json"
    baseline_path.write_bytes(_json_bytes(baseline))

    result = _source_operator_shell(
        tmp_path,
        "\n".join(
            (
                f"baseline_json={baseline_path!s}",
                f"backup_dir={backup!s}",
                "mv() { return 23; }",
                "restore_primary_environment_from_backup",
            )
        ),
    )

    assert result.returncode != 0
    assert primary_env.read_bytes() == b"drifted\n"
    assert not list(backup.glob(".primary-env-restore.*"))


@pytest.mark.parametrize("pre_start_drift", [False, True])
def test_rollback_checks_copy_state_before_and_after_restarting_writers(
    tmp_path: Path, pre_start_drift: bool
) -> None:
    app = tmp_path / "app"
    backup = tmp_path / "backup"
    app.mkdir(parents=True)
    backup.mkdir()
    values = {
        ".env": b"safe\n",
        ".release.env": b"APP_IMAGE=old\n",
        ".release-commit": (VALIDATOR.PRODUCTION_COMMIT + "\n").encode(),
        "RELEASE_COMMIT": VALIDATOR.LEGACY_PRODUCTION_COMMIT + b"\n",
    }
    backup_names = {
        ".env": "env.before",
        ".release.env": "release.env.before",
        ".release-commit": "release-commit.before",
        "RELEASE_COMMIT": "legacy-release-commit.before",
    }
    for name, value in values.items():
        (app / name).write_bytes(b"candidate\n")
        (backup / backup_names[name]).write_bytes(value)
        (backup / backup_names[name]).chmod(0o600)
    events = tmp_path / "rollback-events"
    result = _source_operator_shell(
        tmp_path,
        f"""
backup_dir={backup!s}
baseline_json=/unused
EVENTS={events!s}
compose() {{ printf 'compose:%s\\n' "$*" >>"$EVENTS"; }}
primary_env_matches_baseline() {{ return 0; }}
json_string() {{ printf '{"1" * 64}\\n'; }}
sha256sum() {{ printf '{"1" * 64}  %s\\n' "$1"; }}
baseline_legacy_identity() {{ printf '600:0:0\\n'; }}
marker_equals() {{ return 0; }}
database_head() {{ printf '%s\\n' "$ALEMBIC_HEAD"; }}
verify_service_set() {{ return 0; }}
copy_state_calls=0
copy_state_matches_baseline() {{
  copy_state_calls=$((copy_state_calls + 1))
  printf 'copy-state:%s\\n' "$copy_state_calls" >>"$EVENTS"
  [[ {str(pre_start_drift).lower()} != true || $copy_state_calls -ne 1 ]]
}}
restore_previous_state
""",
    )

    events_text = events.read_text(encoding="utf-8")
    assert (result.returncode != 0) is pre_start_drift
    assert events_text.index("compose:stop") < events_text.index("copy-state:1")
    if pre_start_drift:
        assert "compose:up" not in events_text
    else:
        assert events_text.count("copy-state:") == 2
        assert events_text.index("copy-state:1") < events_text.index("compose:up")
        assert events_text.index("compose:up") < events_text.index("copy-state:2")


def test_evidence_records_captured_terminal_count_without_fixed_literal(
    tmp_path: Path,
) -> None:
    backup = tmp_path / "backup"
    backup.mkdir()
    result = _source_operator_shell(
        tmp_path,
        f"""
backup_dir={backup!s}
release_commit={RELEASE_COMMIT}
candidate_reference={REPOSITORY}@sha256:{"b" * 64}
baseline_effect_counts() {{ printf '23:0:0\\n'; }}
baseline_frozen_copy_cohort() {{ printf '7:{"4" * 64}\\n'; }}
json_string() {{ printf '2026-09-04\\n'; }}
write_evidence
""",
    )
    assert result.returncode == 0, result.stderr
    evidence = (backup / "brand-embedding-activation-evidence.txt").read_text(
        encoding="utf-8"
    )
    assert "copy_provider_unavailable_terminal=23\n" in evidence
    assert "copy_provider_unavailable_terminal=18\n" not in evidence
    assert "frozen_copy_job_count=7\n" in evidence
    assert f"frozen_copy_job_sha256={'4' * 64}\n" in evidence


def _activation_harness(
    tmp_path: Path, failure: str = ""
) -> subprocess.CompletedProcess[str]:
    app = tmp_path / "app"
    app.mkdir(parents=True)
    (app / ".env").write_text("safe\n", encoding="utf-8")
    (app / ".env").chmod(0o600)
    os.chown(app / ".env", 1000, 1001)
    (app / ".release-commit").write_text(
        VALIDATOR.PRODUCTION_COMMIT + "\n", encoding="utf-8"
    )
    legacy_marker = app / "RELEASE_COMMIT"
    legacy_marker.write_bytes(VALIDATOR.LEGACY_PRODUCTION_COMMIT + b"\n")
    legacy_marker.chmod(0o600)
    os.chown(legacy_marker, 1000, 1001)
    events = tmp_path / "events"
    fail_function = (
        "write_candidate_release_env() { printf 'release-env-failed\\n' >>\"$EVENTS\"; return 17; }"
        if failure == "pre_migration"
        else "write_candidate_release_env() { printf 'release-env\\n' >>\"$EVENTS\"; }"
    )
    compose_failure = "return 19" if failure == "migration" else "return 0"
    primary_env_sha256 = _digest(b"safe\n")
    body = f"""
EVENTS={events!s}
release_commit={RELEASE_COMMIT}
candidate_config_digest=sha256:{"a" * 64}
candidate_reference={REPOSITORY}@sha256:{"b" * 64}
baseline_json=/unused
verify_baseline() {{ printf 'locked-baseline\\n' >>"$EVENTS"; }}
prepare_roots_and_attempt() {{
  mkdir -p "$BACKUP_ROOT"
  chmod 700 "$BACKUP_ROOT"
  backup_dir="$BACKUP_ROOT/backup"
  mkdir -p "$backup_dir"
  cp -a "$PRIMARY_ENV" "$backup_dir/env.before"
  cp -a "$RELEASE_MARKER" "$backup_dir/release-commit.before"
  cp -a "$LEGACY_RELEASE_MARKER" "$backup_dir/legacy-release-commit.before"
  printf 'prepare\\n' >>"$EVENTS"
}}
prepare_candidate_source() {{ printf 'candidate-source\\n' >>"$EVENTS"; }}
quiesce_and_backup() {{ recovery_armed=1; printf 'quiesce-backup\\n' >>"$EVENTS"; }}
verify_quiesced_baseline() {{
  printf 'quiesced-baseline\\n' >>"$EVENTS"
  [[ {failure!r} != quiesced_drift ]] || return 1
  [[ {failure!r} != quiesced_metadata_drift ]] || chmod 640 "$PRIMARY_ENV"
  primary_env_matches_baseline
}}
activate_source() {{
  source_activated=1
  write_commit_marker "$RELEASE_MARKER" "$release_commit"
  write_commit_marker "$LEGACY_RELEASE_MARKER" "$release_commit"
  printf 'activate-source\\n' >>"$EVENTS"
}}
verify_installed_source() {{ printf 'verify-source\\n' >>"$EVENTS"; }}
{fail_function}
compose() {{
  printf 'compose' >>"$EVENTS"
  printf ' <%s>' "$@" >>"$EVENTS"
  printf '\\n' >>"$EVENTS"
  if [[ "${{1:-}}" == run ]]; then {compose_failure}; fi
  return 0
}}
database_head() {{ printf '%s\\n' "$ALEMBIC_HEAD"; }}
wait_for_candidate() {{ printf 'wait-ready\\n' >>"$EVENTS"; }}
require_safe_window() {{ printf 'window\\n' >>"$EVENTS"; }}
effect_counts() {{
  [[ {failure!r} != final_metadata_drift ]] || chmod 640 "$PRIMARY_ENV"
  [[ {failure!r} == counter_drift ]] && printf '24:0\\n' || printf '23:0\\n'
}}
baseline_effect_counts() {{ printf '23:0\\n'; }}
copy_state_calls=0
copy_state_matches_baseline() {{
  copy_state_calls=$((copy_state_calls + 1))
  printf 'copy-state-%s\\n' "$copy_state_calls" >>"$EVENTS"
  [[ {failure!r} != final_metadata_drift || $copy_state_calls -ne 3 ]] || chmod 640 "$PRIMARY_ENV"
  [[ {failure!r} != copy_pre_migration_drift || $copy_state_calls -ne 1 ]] || return 1
  [[ {failure!r} != copy_pre_start_drift || $copy_state_calls -ne 2 ]] || return 1
  [[ {failure!r} != counter_drift || $copy_state_calls -ne 3 ]] || return 1
}}
sha256sum() {{ printf '%s  %s\\n' "{"1" * 64}" "$1"; }}
json_string() {{ printf '%s\\n' "{primary_env_sha256}"; }}
baseline_primary_identity() {{ printf '600:1000:1001\\n'; }}
release_reference() {{ printf '%s\\n' "$candidate_reference"; }}
docker() {{ printf '%s\\n' "$release_commit"; }}
write_evidence() {{ printf 'evidence\\n' >>"$EVENTS"; }}
restore_previous_state() {{
  cp -a "$backup_dir/env.before" "$PRIMARY_ENV"
  cp -a "$backup_dir/release-commit.before" "$RELEASE_MARKER"
  cp -a "$backup_dir/legacy-release-commit.before" "$LEGACY_RELEASE_MARKER"
  printf 'restore-previous\\n' >>"$EVENTS"
}}
stop_writers_for_incident() {{ printf 'stop-incident\\n' >>"$EVENTS"; }}
run_activation
"""
    return _source_operator_shell(tmp_path, body)


def test_fake_operator_success_runs_one_migration_and_no_effect_command(
    tmp_path: Path,
) -> None:
    result = _activation_harness(tmp_path)
    assert result.returncode == 0, result.stderr
    events = (tmp_path / "events").read_text(encoding="utf-8")
    assert events.count("<run> <--rm> <--no-deps> <-T> <backend-migrate>") == 1
    assert events.count("<up> <-d> <--no-build> <--no-deps>") == 1
    assert "quiesce-backup" in events
    assert events.index("locked-baseline") < events.index("prepare")
    assert events.index("quiesce-backup") < events.index("quiesced-baseline")
    assert events.index("quiesced-baseline") < events.index("activate-source")
    assert events.index("copy-state-1") < events.index("<backend-migrate>")
    assert events.index("<backend-migrate>") < events.index("copy-state-2")
    assert events.index("copy-state-2") < events.index("copy-state-3")
    assert "wait-ready" in events
    assert "evidence" in events
    assert "restore-previous" not in events
    assert all(word not in events for word in ("provider", "send", "enqueue", "replay"))
    for marker_name in (".release-commit", "RELEASE_COMMIT"):
        marker = tmp_path / "app" / marker_name
        assert marker.read_text(encoding="utf-8") == RELEASE_COMMIT + "\n"
        assert marker.stat().st_mode & 0o777 == 0o600
        assert (marker.stat().st_uid, marker.stat().st_gid) == (0, 0)


@pytest.mark.parametrize(
    "failure",
    [
        "quiesced_drift",
        "quiesced_metadata_drift",
        "pre_migration",
        "migration",
        "copy_pre_migration_drift",
        "copy_pre_start_drift",
        "counter_drift",
        "final_metadata_drift",
    ],
)
def test_fake_operator_restores_previous_state_when_schema_is_unchanged(
    tmp_path: Path, failure: str
) -> None:
    result = _activation_harness(tmp_path, failure)
    assert result.returncode != 0
    events = (tmp_path / "events").read_text(encoding="utf-8")
    assert "quiesce-backup" in events
    assert "restore-previous" in events
    assert "stop-incident" not in events
    legacy_marker = tmp_path / "app" / "RELEASE_COMMIT"
    assert legacy_marker.read_bytes() == VALIDATOR.LEGACY_PRODUCTION_COMMIT + b"\n"
    assert legacy_marker.stat().st_mode & 0o777 == 0o600
    assert (legacy_marker.stat().st_uid, legacy_marker.stat().st_gid) == (1000, 1001)
    primary_env = tmp_path / "app" / ".env"
    assert primary_env.read_text(encoding="utf-8") == "safe\n"
    assert primary_env.stat().st_mode & 0o777 == 0o600
    assert (primary_env.stat().st_uid, primary_env.stat().st_gid) == (1000, 1001)
    if failure in {
        "quiesced_drift",
        "quiesced_metadata_drift",
        "pre_migration",
        "copy_pre_migration_drift",
    }:
        assert "<backend-migrate>" not in events
    if failure in {"quiesced_drift", "quiesced_metadata_drift"}:
        assert "activate-source" not in events
    else:
        if failure not in {"pre_migration", "copy_pre_migration_drift"}:
            assert events.count("<run> <--rm> <--no-deps> <-T> <backend-migrate>") == 1
