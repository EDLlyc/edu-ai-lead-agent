#!/usr/bin/env python3
"""Pure, bounded validation for the task-local WeChat draft offline release stage."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tarfile
from pathlib import Path, PurePosixPath
from typing import NoReturn

SHA = re.compile(r"[0-9a-f]{64}")
COMMIT = re.compile(r"[0-9a-f]{40}")
IMAGE_ID = re.compile(r"sha256:[0-9a-f]{64}")
TAG = re.compile(r"edu-ai-lead-agent-backend:wechat-draft-[0-9a-f]{12}")
MEMBERS = {
    "artifacts.sha256",
    "backend-image.tar.gz",
    "backend-image.tar.gz.sha256",
    "production-baseline.json",
    "release-metadata.json",
    "source-files.sha256",
    "source.tar.gz",
    "source.tar.gz.sha256",
    "validate-wechat-draft-offline-artifacts.py",
    "wechat-draft-offline-release-operator.sh",
}
CHECKSUM_TARGETS = MEMBERS - {"artifacts.sha256"}
REQUIRED_SOURCE = {
    "compose.yaml",
    "backend/alembic.ini",
    "backend/pyproject.toml",
    "backend/app/wechat_official_account_draft_main.py",
    "backend/app/infrastructure/wechat_official_account/artifacts.py",
    "backend/alembic/versions/20260901_0042_wechat_official_account_draft_jobs.py",
    "deploy/release/migration-compatibility.json",
}
MAX_MEMBER_BYTES = 8 * 1024 * 1024 * 1024
MAX_SOURCE_BYTES = 2 * 1024 * 1024 * 1024
MAX_IMAGE_BYTES = 8 * 1024 * 1024 * 1024
MAX_JSON_BYTES = 16 * 1024 * 1024


def fail(message: str) -> NoReturn:
    raise ValueError(message)


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            value.update(chunk)
    return value.hexdigest()


def safe_relative(value: str) -> str:
    path = PurePosixPath(value.removeprefix("./"))
    normalized = str(path)
    if (
        not normalized
        or path.is_absolute()
        or normalized != value.removeprefix("./")
        or any(part in {"", ".", ".."} for part in path.parts)
        or any(character in normalized for character in "\0\r\n\t")
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


def checksum_rows(path: Path, expected: set[str]) -> dict[str, str]:
    rows: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  ([A-Za-z0-9][A-Za-z0-9._-]*)", line)
        if match is None or match.group(2) in rows:
            fail("checksum manifest is malformed")
        rows[match.group(2)] = match.group(1)
    if set(rows) != expected or list(rows) != sorted(rows):
        fail("checksum manifest member set changed")
    return rows


def validate_source(stage: Path) -> None:
    manifest_rows: dict[str, str] = {}
    for line in (
        (stage / "source-files.sha256").read_text(encoding="utf-8").splitlines()
    ):
        match = re.fullmatch(r"([0-9a-f]{64})  ([^\r\n]+)", line)
        if match is None:
            fail("source manifest is malformed")
        name = safe_relative(match.group(2))
        if name in manifest_rows:
            fail("source manifest contains duplicates")
        manifest_rows[name] = match.group(1)
    if list(manifest_rows) != sorted(manifest_rows) or not REQUIRED_SOURCE.issubset(
        manifest_rows
    ):
        fail("source manifest is incomplete or unsorted")

    observed: dict[str, str] = {}
    total = 0
    try:
        with tarfile.open(stage / "source.tar.gz", mode="r:gz") as archive:
            for member in archive:
                name = safe_relative(member.name)
                if member.isdir():
                    continue
                if not member.isfile() or member.issym() or member.islnk():
                    fail("source archive contains a non-regular member")
                if member.size < 0 or member.size > MAX_SOURCE_BYTES:
                    fail("source archive member exceeds bound")
                total += member.size
                if total > MAX_SOURCE_BYTES or name in observed:
                    fail("source archive exceeds aggregate bound")
                stream = archive.extractfile(member)
                if stream is None:
                    fail("source archive member is unreadable")
                value = hashlib.sha256()
                while chunk := stream.read(1024 * 1024):
                    value.update(chunk)
                observed[name] = value.hexdigest()
    except (OSError, tarfile.TarError) as exc:
        raise ValueError("source archive is unreadable") from exc
    if observed != manifest_rows:
        fail("source archive differs from its manifest")


def validate_metadata(stage: Path) -> dict[str, object]:
    try:
        payload = json.loads((stage / "release-metadata.json").read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("release metadata is invalid") from exc
    expected_keys = {
        "schema_version",
        "release_commit",
        "candidate_tag",
        "candidate_id",
        "alembic_head",
        "source_sha256",
        "source_manifest_sha256",
        "image_archive_sha256",
        "operator_sha256",
        "production_baseline_sha256",
        "validator_sha256",
        "runtime_modules",
    }
    if not isinstance(payload, dict) or set(payload) != expected_keys:
        fail("release metadata keys changed")
    if payload["schema_version"] != 1 or payload["alembic_head"] != "20260901_0042":
        fail("release metadata schema identity changed")
    if (
        not isinstance(payload["release_commit"], str)
        or COMMIT.fullmatch(payload["release_commit"]) is None
    ):
        fail("release commit is invalid")
    if (
        not isinstance(payload["candidate_tag"], str)
        or TAG.fullmatch(payload["candidate_tag"]) is None
    ):
        fail("candidate tag is invalid")
    if (
        not isinstance(payload["candidate_id"], str)
        or IMAGE_ID.fullmatch(payload["candidate_id"]) is None
    ):
        fail("candidate image ID is invalid")
    for key in (
        "source_sha256",
        "source_manifest_sha256",
        "image_archive_sha256",
        "operator_sha256",
        "production_baseline_sha256",
        "validator_sha256",
    ):
        if not isinstance(payload[key], str) or SHA.fullmatch(payload[key]) is None:
            fail(f"{key} is invalid")
    expected_modules = [
        "app.api_main",
        "app.scheduler_main",
        "app.worker_main",
        "app.governance_scheduler_main",
        "app.governance_worker_main",
        "app.content_scheduler_main",
        "app.content_worker_main",
        "app.wecom_dispatcher_main",
        "app.wechat_official_account_draft_main",
    ]
    if payload["runtime_modules"] != expected_modules:
        fail("runtime module contract changed")
    return payload


def validate_production_baseline(stage: Path) -> None:
    try:
        payload = json.loads((stage / "production-baseline.json").read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("production baseline is invalid") from exc
    expected_keys = {
        "schema_version",
        "observed_at_utc",
        "current_alembic_head",
        "current_image_id",
        "current_image_revision",
        "source_tree_sha256",
        "env_sha256",
        "release_env_sha256",
        "restart_counts",
        "running_services",
    }
    if not isinstance(payload, dict) or set(payload) != expected_keys:
        fail("production baseline keys changed")
    if (
        payload["schema_version"] != 1
        or payload["current_alembic_head"] != "20260825_0036"
        or not isinstance(payload["observed_at_utc"], str)
        or re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z",
            payload["observed_at_utc"],
        )
        is None
        or not isinstance(payload["current_image_id"], str)
        or IMAGE_ID.fullmatch(payload["current_image_id"]) is None
        or not isinstance(payload["current_image_revision"], str)
        or COMMIT.fullmatch(payload["current_image_revision"]) is None
    ):
        fail("production baseline identity is invalid")
    for key in ("source_tree_sha256", "env_sha256", "release_env_sha256"):
        if not isinstance(payload[key], str) or SHA.fullmatch(payload[key]) is None:
            fail("production baseline checksum is invalid")
    expected_services = sorted(
        [
            "postgres",
            "minio",
            "acquisition-api",
            "acquisition-scheduler",
            "acquisition-worker",
            "governance-scheduler",
            "governance-worker",
            "content-scheduler",
            "content-worker",
            "wecom-dispatcher",
        ]
    )
    if payload["running_services"] != expected_services:
        fail("production baseline service set changed")
    restart_counts = payload["restart_counts"]
    if (
        not isinstance(restart_counts, dict)
        or set(restart_counts) != set(expected_services)
        or any(
            not isinstance(service, str)
            or isinstance(value, bool)
            or not isinstance(value, int)
            or value < 0
            for service, value in restart_counts.items()
        )
    ):
        fail("production baseline restart counts are invalid")


def _json_blob(blobs: dict[str, tuple[str, int, bytes | None]], name: str) -> object:
    record = blobs.get(name)
    if record is None or record[2] is None:
        fail("image archive JSON member is absent or oversized")
    try:
        return json.loads(record[2])
    except json.JSONDecodeError as exc:
        raise ValueError("image archive JSON is invalid") from exc


def _oci_blob_name(digest_value: object) -> str:
    if not isinstance(digest_value, str) or not digest_value.startswith("sha256:"):
        fail("OCI descriptor digest is invalid")
    value = digest_value.removeprefix("sha256:")
    if SHA.fullmatch(value) is None:
        fail("OCI descriptor digest is invalid")
    return f"blobs/sha256/{value}"


def validate_image_archive(stage: Path, metadata: dict[str, object]) -> None:
    blobs: dict[str, tuple[str, int, bytes | None]] = {}
    total = 0
    try:
        with tarfile.open(stage / "backend-image.tar.gz", mode="r:gz") as archive:
            for member in archive:
                name = safe_relative(member.name)
                if member.isdir():
                    continue
                if (
                    not member.isfile()
                    or member.issym()
                    or member.islnk()
                    or name in blobs
                ):
                    fail("image archive member type or identity is unsafe")
                if member.size < 0 or member.size > MAX_IMAGE_BYTES:
                    fail("image archive member exceeds bound")
                total += member.size
                if total > MAX_IMAGE_BYTES:
                    fail("image archive exceeds aggregate bound")
                stream = archive.extractfile(member)
                if stream is None:
                    fail("image archive member is unreadable")
                value = hashlib.sha256()
                captured = bytearray() if member.size <= MAX_JSON_BYTES else None
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
        raise ValueError("image archive is unreadable") from exc

    expected_tag = metadata["candidate_tag"]
    expected_commit = metadata["release_commit"]
    if "manifest.json" in blobs:
        manifest = _json_blob(blobs, "manifest.json")
        if (
            not isinstance(manifest, list)
            or len(manifest) != 1
            or not isinstance(manifest[0], dict)
        ):
            fail("classic image manifest must contain one image")
        record = manifest[0]
        config_name = record.get("Config")
        layers = record.get("Layers")
        tags = record.get("RepoTags")
        if (
            not isinstance(config_name, str)
            or not isinstance(layers, list)
            or not layers
            or len(set(layers)) != len(layers)
            or not all(isinstance(layer, str) and layer in blobs for layer in layers)
            or not isinstance(tags, list)
            or expected_tag not in tags
        ):
            fail("classic image manifest graph is incomplete")
        config_name = safe_relative(config_name)
        if (
            not config_name.endswith(".json")
            or config_name.removesuffix(".json")
            != str(metadata["candidate_id"]).removeprefix("sha256:")
            or blobs[config_name][0] != config_name.removesuffix(".json")
        ):
            fail("classic image config identity changed")
        config = _json_blob(blobs, config_name)
    elif "index.json" in blobs and "oci-layout" in blobs:
        index = _json_blob(blobs, "index.json")
        if not isinstance(index, dict) or not isinstance(index.get("manifests"), list):
            fail("OCI index is invalid")
        descriptors = index["manifests"]
        if len(descriptors) != 1 or not isinstance(descriptors[0], dict):
            fail("OCI index must contain one manifest")
        manifest_name = _oci_blob_name(descriptors[0].get("digest"))
        if (
            manifest_name not in blobs
            or blobs[manifest_name][0] != manifest_name.rsplit("/", 1)[1]
        ):
            fail("OCI manifest digest binding changed")
        manifest = _json_blob(blobs, manifest_name)
        if not isinstance(manifest, dict) or not isinstance(
            manifest.get("config"), dict
        ):
            fail("OCI image manifest is invalid")
        config_name = _oci_blob_name(manifest["config"].get("digest"))
        layers = manifest.get("layers")
        if not isinstance(layers, list) or not layers:
            fail("OCI image layers are absent")
        for descriptor in layers:
            if not isinstance(descriptor, dict):
                fail("OCI layer descriptor is invalid")
            layer_name = _oci_blob_name(descriptor.get("digest"))
            if (
                layer_name not in blobs
                or blobs[layer_name][0] != layer_name.rsplit("/", 1)[1]
            ):
                fail("OCI layer digest binding changed")
        if (
            config_name not in blobs
            or blobs[config_name][0] != config_name.rsplit("/", 1)[1]
        ):
            fail("OCI config digest binding changed")
        if config_name.rsplit("/", 1)[1] != str(metadata["candidate_id"]).removeprefix(
            "sha256:"
        ):
            fail("OCI image config identity changed")
        config = _json_blob(blobs, config_name)
    else:
        fail("image archive is neither classic Docker nor OCI layout")

    if not isinstance(config, dict):
        fail("image config is invalid")
    runtime = config.get("config")
    labels = runtime.get("Labels") if isinstance(runtime, dict) else None
    if (
        config.get("architecture") != "amd64"
        or not isinstance(runtime, dict)
        or runtime.get("User") != "app"
        or not isinstance(labels, dict)
        or labels.get("org.opencontainers.image.revision") != expected_commit
    ):
        fail("image architecture, user, or revision label changed")


def validate_stage(path: Path) -> dict[str, object]:
    stage = path.resolve(strict=True)
    if (
        not stage.is_dir()
        or has_symlink_component(path.absolute())
        or (stage.stat().st_mode & 0o777) != 0o700
        or stage.stat().st_uid != 0
        or stage.stat().st_gid != 0
    ):
        fail("stage must be a physical root-owned mode-0700 directory")
    observed = {
        item.name
        for item in stage.iterdir()
        if item.is_file() and not item.is_symlink()
    }
    if observed != MEMBERS or any(
        (stage / name).stat().st_mode & 0o777 != 0o600
        or (stage / name).stat().st_uid != 0
        or (stage / name).stat().st_gid != 0
        for name in MEMBERS
    ):
        fail("stage member set, ownership, or mode changed")
    if any((stage / name).stat().st_size > MAX_MEMBER_BYTES for name in MEMBERS):
        fail("stage member exceeds bound")
    rows = checksum_rows(stage / "artifacts.sha256", CHECKSUM_TARGETS)
    for name, expected in rows.items():
        if digest(stage / name) != expected:
            fail("stage checksum mismatch")
    for sidecar, target in (
        ("source.tar.gz.sha256", "source.tar.gz"),
        ("backend-image.tar.gz.sha256", "backend-image.tar.gz"),
    ):
        row = checksum_rows(stage / sidecar, {target})
        if digest(stage / target) != row[target]:
            fail("archive sidecar checksum mismatch")
    payload = validate_metadata(stage)
    validate_production_baseline(stage)
    validate_image_archive(stage, payload)
    validate_source(stage)
    bindings = {
        "source_sha256": digest(stage / "source.tar.gz"),
        "source_manifest_sha256": digest(stage / "source-files.sha256"),
        "image_archive_sha256": digest(stage / "backend-image.tar.gz"),
        "operator_sha256": digest(stage / "wechat-draft-offline-release-operator.sh"),
        "production_baseline_sha256": digest(stage / "production-baseline.json"),
        "validator_sha256": digest(
            stage / "validate-wechat-draft-offline-artifacts.py"
        ),
    }
    if any(payload[key] != value for key, value in bindings.items()):
        fail("release metadata binding mismatch")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", type=Path)
    args = parser.parse_args()
    try:
        payload = validate_stage(args.stage)
    except ValueError as exc:
        print(f"artifact_validation_failed reason={exc}")
        return 1
    print(
        "artifact_validation_ok "
        f"release_commit={payload['release_commit']} candidate_id={payload['candidate_id']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
