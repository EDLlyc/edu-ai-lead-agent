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
VALIDATOR_PATH = RESEARCH / "validate-brand-embedding-hotfix-offline-artifacts.py"
OPERATOR_PATH = RESEARCH / "brand-embedding-hotfix-offline-release-operator.sh"
BUILDER_PATH = RESEARCH / "build-brand-embedding-hotfix-offline-artifacts.sh"
CAPTURE_PATH = RESEARCH / "capture-brand-embedding-production-baseline.sh"
RELEASE_COMMIT = "e" * 40
REPOSITORY = "registry.example.test/edu-ai/edu-ai-lead-agent"


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


def _write_source(stage: Path) -> None:
    entries = _source_entries()
    _write_tar_gz(stage / "source.tar.gz", entries)
    rows = []
    for name, kind, mode, value in entries:
        checksum = "-" if kind == "d" else _digest(value or b"")
        rows.append(f"{kind}\t{mode:04o}\t{checksum}\t{name}\n")
    (stage / "source-manifest.tsv").write_text("".join(rows), encoding="utf-8")


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
    index = _json_bytes(
        {
            "manifests": [
                {
                    "annotations": {
                        "io.containerd.image.name": transport_tag,
                        "org.opencontainers.image.ref.name": transport_tag,
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
    image_paths = (
        "alembic.ini",
        "pyproject.toml",
        "app/api_main.py",
        "app/content_worker_main.py",
        "app/core/config.py",
        "app/infrastructure/ai/factory.py",
        "alembic/versions/20260901_0042_wechat_mp_draft_jobs.py",
    )
    (stage / "image-source.sha256").write_text(
        "".join(f"{'4' * 64}  {name}\n" for name in sorted(image_paths)),
        encoding="utf-8",
    )
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
        index["manifests"][0]["annotations"]["org.opencontainers.image.ref.name"] = (
            "evil:tag"
        )
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
    [("blob", "descriptor bytes"), ("dangling", "dangling"), ("tag", "transport tag")],
)
def test_complete_oci_graph_rejects_tamper(
    tmp_path: Path, mutation: str, message: str
) -> None:
    stage = _stage(tmp_path)
    _rewrite_oci(stage, mutation)
    _rebind(stage, "image_archive_sha256", "backend-image.oci.tar.gz")
    with pytest.raises(ValueError, match=message):
        VALIDATOR.validate_stage(stage)


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
    assert 'grep -Fxq "$candidate_reference"' in builder
    assert "--env AI_PLATFORM_BASE_URL=https://open.bigmodel.cn/api/paas/v4" in builder
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
