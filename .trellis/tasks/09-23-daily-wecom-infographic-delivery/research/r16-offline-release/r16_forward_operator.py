#!/usr/bin/env python3
"""R16 forward-only release contract and local simulation, never production apply.

The real host adapter is intentionally absent. A plan proves only that a
reviewed evidence *shape* is complete; it cannot authenticate live host state
or backup bytes. `apply` always refuses. `simulate` is for fake-host tests and
enforces one attempt, both locks, a checked backup, and forward-only failure.
"""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import re
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Protocol

BASE_REVISION = "36b24d67b969a433f19c691bb9d12a3c13e00244"
BASE_IMAGE = "sha256:d740275be855c258d2dbaccb180b65e8a14e949070f8597fcca4b3fb984eeb1f"
BASE_REF = "offline.local/edu-ai/edu-ai-lead-agent-backend@" + BASE_IMAGE
BASE_SCHEMA = "20260916_0048"
TARGET_SCHEMA = "20260926_0050"
MIGRATION_CHAIN = [BASE_SCHEMA, "20260923_0049", TARGET_SCHEMA]
ALEMBIC_ONLY_COMMAND = (
    "python",
    "-m",
    "alembic",
    "-c",
    "/app/alembic.ini",
    "upgrade",
    TARGET_SCHEMA,
)
SERVICES = (
    "acquisition-api",
    "acquisition-scheduler",
    "acquisition-worker",
    "governance-scheduler",
    "governance-worker",
    "content-scheduler",
    "content-worker",
    "official-account-weekly-dag-worker",
    "official-account-weekly-scheduler",
    "official-account-local-worker",
    "wechat-official-account-draft-worker",
    "wecom-dispatcher",
)
PROTECTED_FILES = (
    ".env",
    ".release.env",
    ".release-commit",
    "RELEASE_COMMIT",
    "compose.yaml",
    "scripts/edu-ai-release-common.sh",
    "deploy/release/migration-compatibility.json",
    "deploy/release/deploy.py",
    "scripts/edu-ai-production-check.sh",
    "scripts/doctor.sh",
)
VOLUMES = (
    "edu-ai-lead-agent_minio_data",
    "edu-ai-lead-agent_wechat_mp_draft_artifacts",
    "edu-ai-lead-agent_official_account_weekly_dag_output",
)
OFF_FLAGS = (
    "WECOM_INFOGRAPHIC_PRODUCER_ENABLED",
    "WECOM_INFOGRAPHIC_DELIVERY_ENABLED",
    "WECOM_INFOGRAPHIC_TEST_ENABLED",
    "WECOM_INFOGRAPHIC_MORNING_ENABLED",
    "WECOM_INFOGRAPHIC_NOON_ENABLED",
    "WECOM_INFOGRAPHIC_EVENING_ENABLED",
)
SHA = re.compile(r"[0-9a-f]{64}\Z")


class ReleaseBlocked(RuntimeError):
    pass


def require(value: bool, code: str) -> None:
    if not value:
        raise ReleaseBlocked(code)


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def is_sha(value: Any) -> bool:
    return isinstance(value, str) and SHA.fullmatch(value) is not None


def valid_manifest(manifest: dict[str, Any]) -> None:
    require(
        re.fullmatch(r"[0-9a-f]{40}", manifest.get("revision", "")) is not None
        and re.fullmatch(r"[0-9a-f]{40}", manifest.get("operator_source_revision", ""))
        is not None
        and manifest.get("base_revision") == BASE_REVISION
        and manifest.get("base_image") == BASE_IMAGE
        and manifest.get("schema") == TARGET_SCHEMA
        and manifest.get("migration_chain") == MIGRATION_CHAIN
        and manifest.get("previous_application_compatible") is False
        and isinstance(manifest.get("image"), str)
        and re.fullmatch(r"sha256:[0-9a-f]{64}", manifest["image"]) is not None
        and is_sha(manifest.get("archive_sha256"))
        and manifest.get("operator_sha256") == sha(Path(__file__).read_bytes()),
        "candidate_manifest",
    )
    if manifest["operator_source_revision"] != manifest["revision"]:
        split = manifest.get("source_split")
        require(
            isinstance(split, dict)
            and split.get("runtime_unchanged") is True
            and split.get("migrations_unchanged") is True
            and split.get("compose_unchanged") is True
            and split.get("protected_files_unchanged") is True
            and is_sha(split.get("review_receipt_sha256")),
            "source_split_unreviewed",
        )


def valid_baseline(baseline: dict[str, Any]) -> None:
    require(
        baseline.get("release_commit") == BASE_REVISION
        and baseline.get("release_commit_secondary") == BASE_REVISION
        and baseline.get("image") == BASE_IMAGE
        and baseline.get("release_env_image") == BASE_REF
        and baseline.get("schema") == BASE_SCHEMA
        and baseline.get("optional_producer_absent") is True
        and baseline.get("standard_manifest_absent") is True
        and baseline.get("backup_timer_active") is True
        and baseline.get("idle") is True
        and type(baseline.get("unknown_work_count")) is int
        and baseline["unknown_work_count"] == 0
        and type(baseline.get("pending_work_count")) is int
        and baseline["pending_work_count"] == 0
        and is_sha(baseline.get("business_identity_sha256"))
        and is_sha(baseline.get("brand_identity_sha256"))
        and is_sha(baseline.get("recipient_fingerprint")),
        "baseline_identity",
    )
    flags = baseline.get("flags")
    require(
        isinstance(flags, dict)
        and set(flags) == set(OFF_FLAGS)
        and all(flags[name] is False for name in OFF_FLAGS),
        "default_off_flags",
    )
    services = baseline.get("services")
    require(
        isinstance(services, dict) and set(services) == set(SERVICES), "service_set"
    )
    assert isinstance(services, dict)
    for item in services.values():
        require(
            isinstance(item, dict)
            and item.get("image") == BASE_IMAGE
            and item.get("image_ref") == BASE_REF
            and item.get("running") is True
            and item.get("healthy") is True
            and item.get("restarts") == 0
            and is_sha(item.get("command_sha256"))
            and is_sha(item.get("mounts_sha256"))
            and is_sha(item.get("env_sha256")),
            "service_identity",
        )
    protected = baseline.get("protected_files")
    require(
        isinstance(protected, dict) and set(protected) == set(PROTECTED_FILES),
        "protected_file_set",
    )
    assert isinstance(protected, dict)
    for item in protected.values():
        require(
            isinstance(item, dict)
            and is_sha(item.get("sha256"))
            and type(item.get("mode")) is int
            and type(item.get("uid")) is int
            and type(item.get("gid")) is int,
            "protected_file_identity",
        )
    volumes = baseline.get("volumes")
    require(isinstance(volumes, dict) and set(volumes) == set(VOLUMES), "volume_set")
    assert isinstance(volumes, dict)
    require(all(is_sha(value) for value in volumes.values()), "volume_identity")


def valid_evidence(
    manifest: dict[str, Any], baseline: dict[str, Any], evidence: dict[str, Any]
) -> None:
    images = evidence.get("images")
    require(isinstance(images, list) and len(images) == 3, "three_news_images")
    assert isinstance(images, list)
    packages: set[str] = set()
    image_hashes: set[str] = set()
    image_by_package: dict[str, str] = {}
    for item in images:
        require(
            isinstance(item, dict)
            and isinstance(item.get("package_id"), str)
            and item["package_id"]
            and is_sha(item.get("jpeg_sha256"))
            and item.get("exact_source") is True
            and item.get("ocr_pass") is True
            and item.get("phone_visual_pass") is True
            and item.get("send_ready") is True,
            "image_quality_receipt",
        )
        packages.add(item["package_id"])
        image_hashes.add(item["jpeg_sha256"])
        image_by_package[item["package_id"]] = item["jpeg_sha256"]
    require(len(packages) == len(image_hashes) == 3, "distinct_news_images")
    group = evidence.get("group_test")
    require(isinstance(group, dict), "fixed_group_triple_receipt")
    assert isinstance(group, dict)
    group_package_id = group.get("package_id")
    require(
        isinstance(group_package_id, str)
        and group.get("recipient_fingerprint") == baseline["recipient_fingerprint"]
        and group_package_id in packages
        and group.get("test_marker") is True
        and group.get("outcomes")
        == ["text_confirmed", "original_image_confirmed", "infographic_confirmed"]
        and is_sha(group.get("artifact_sha256"))
        and group.get("artifact_sha256") == image_by_package.get(group_package_id),
        "fixed_group_triple_receipt",
    )
    migration = evidence.get("migration_clone")
    require(
        isinstance(migration, dict)
        and migration.get("chain") == MIGRATION_CHAIN
        and migration.get("source_business_sha256")
        == baseline["business_identity_sha256"]
        and migration.get("retained_business_sha256")
        == baseline["business_identity_sha256"]
        and migration.get("existing_table_counts_equal") is True
        and migration.get("isolated_restore_readback") is True
        and migration.get("isolated_target") is True
        and is_sha(migration.get("source_dump_sha256"))
        and migration.get("source_schema") == BASE_SCHEMA
        and migration.get("target_schema") == TARGET_SCHEMA
        and is_sha(migration.get("receipt_sha256")),
        "migration_clone_receipt",
    )
    require(
        evidence.get("candidate_image") == manifest["image"]
        and evidence.get("candidate_archive_sha256") == manifest["archive_sha256"],
        "image_evidence_identity",
    )


def plan(
    manifest: dict[str, Any], baseline: dict[str, Any], evidence: dict[str, Any]
) -> dict[str, Any]:
    valid_manifest(manifest)
    valid_baseline(baseline)
    valid_evidence(manifest, baseline, evidence)
    return {
        "phase": "plan_only",
        "candidate_revision": manifest["revision"],
        "candidate_image": manifest["image"],
        "baseline_sha256": sha(canonical(baseline)),
        "services": len(SERVICES),
        "default_off": True,
        "migration_chain": MIGRATION_CHAIN,
        "production_apply_available": False,
        "reason": "declarative receipts are not live capture, verified backup, or an audited host adapter",
    }


def valid_backup(backup: dict[str, Any], baseline: dict[str, Any]) -> None:
    require(
        backup.get("baseline_sha256") == sha(canonical(baseline))
        and is_sha(backup.get("pg_dump_sha256"))
        and type(backup.get("pg_dump_bytes")) is int
        and backup["pg_dump_bytes"] > 0
        and is_sha(backup.get("pg_restore_toc_sha256"))
        and backup.get("pg_restore_toc_read") is True
        and backup.get("protected_files_readback") is True
        and backup.get("protected_files") == baseline["protected_files"]
        and backup.get("brand_materials_readback") is True
        and backup.get("brand_identity_sha256") == baseline["brand_identity_sha256"]
        and backup.get("source_config_readback") is True,
        "backup_receipt",
    )
    volumes = backup.get("volumes")
    volume_readbacks = backup.get("volume_readbacks")
    require(
        isinstance(volumes, dict)
        and set(volumes) == set(VOLUMES)
        and all(is_sha(volumes[name]) for name in VOLUMES)
        and isinstance(volume_readbacks, dict)
        and set(volume_readbacks) == set(VOLUMES)
        and all(volume_readbacks[name] is True for name in VOLUMES),
        "backup_volume_receipt",
    )


def valid_quiescent(snapshot: dict[str, Any], baseline: dict[str, Any]) -> None:
    """Bind a stopped-writer capture to the pre-stop protected identities."""
    require(
        snapshot
        == {
            "schema": BASE_SCHEMA,
            "business_identity_sha256": baseline["business_identity_sha256"],
            "brand_identity_sha256": baseline["brand_identity_sha256"],
            "recipient_fingerprint": baseline["recipient_fingerprint"],
            "protected_files": baseline["protected_files"],
            "volumes": baseline["volumes"],
            "flags": baseline["flags"],
            "stopped_services": list(SERVICES),
            "optional_producer_absent": True,
        },
        "quiescent_identity",
    )


class SimulatedHost(Protocol):
    """Fake-only adapter; no production implementation is supplied."""

    def capture(self) -> dict[str, Any]: ...
    def capture_quiescent(self) -> dict[str, Any]: ...
    def backup(self) -> dict[str, Any]: ...
    def stop_writers(self) -> None: ...
    def verify_writers_stopped(self) -> bool: ...
    def stage_candidate_image(self, manifest: dict[str, Any]) -> str: ...
    def migrate_forward(self, command: tuple[str, ...], chain: list[str]) -> None: ...
    def read_schema_head(self) -> str: ...
    def install_candidate(self, manifest: dict[str, Any]) -> None: ...
    def start_default_off(self, services: tuple[str, ...]) -> None: ...
    def verify_candidate(self, manifest: dict[str, Any]) -> bool: ...
    def stop_all(self) -> None: ...


def capture_readonly(host: SimulatedHost) -> dict[str, Any]:
    """Validate one live-shaped snapshot without writing or trusting a cache."""
    baseline = host.capture()
    valid_baseline(baseline)
    return {
        "phase": "capture_only",
        "baseline_sha256": sha(canonical(baseline)),
        "services": len(SERVICES),
        "default_off": True,
        "production_apply_available": False,
    }


@contextmanager
def two_local_locks(paths: tuple[Path, Path]) -> Iterator[None]:
    handles = []
    try:
        for path in paths:
            fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
            handles.append(fd)
            info = os.fstat(fd)
            require(
                stat.S_ISREG(info.st_mode)
                and stat.S_IMODE(info.st_mode) == 0o600
                and info.st_uid == os.geteuid()
                and info.st_nlink == 1,
                "lock_identity",
            )
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        for fd in reversed(handles):
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)


def write_new(path: Path, value: dict[str, Any]) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as stream:
        stream.write(canonical(value))
        stream.flush()
        os.fsync(stream.fileno())


def simulate(
    host: SimulatedHost,
    manifest: dict[str, Any],
    baseline: dict[str, Any],
    evidence: dict[str, Any],
    attempt_dir: Path,
    lock_paths: tuple[Path, Path],
) -> dict[str, Any]:
    """Exercise the irreversible order only against an injected fake host."""
    planned = plan(manifest, baseline, evidence)
    # Do not let an injected host rewrite any caller-owned contract during
    # backup and thereby make later comparisons agree with unreviewed drift.
    frozen_manifest = json.loads(canonical(manifest))
    frozen_baseline = json.loads(canonical(baseline))
    frozen_evidence = json.loads(canonical(evidence))
    require(not attempt_dir.exists(), "attempt_exists_reconcile_only")
    with two_local_locks(lock_paths):
        require(host.capture() == frozen_baseline, "fresh_baseline_drift")
        attempt_dir.mkdir(mode=0o700, exist_ok=False)
        write_new(
            attempt_dir / "intent.json",
            {
                "candidate": frozen_manifest["image"],
                "baseline_sha256": planned["baseline_sha256"],
                "old_app_restart_forbidden_after_migration_intent": True,
                "simulation_only": True,
            },
        )
        completed = False
        try:
            host.stop_writers()
            require(host.verify_writers_stopped() is True, "writers_not_stopped")
            before_backup = host.capture_quiescent()
            valid_quiescent(before_backup, frozen_baseline)
            backup = host.backup()
            valid_backup(backup, frozen_baseline)
            require(
                backup["pg_dump_sha256"]
                == frozen_evidence["migration_clone"]["source_dump_sha256"],
                "clone_backup_identity",
            )
            after_backup = host.capture_quiescent()
            require(after_backup == before_backup, "post_backup_quiescent_drift")
            require(
                host.stage_candidate_image(frozen_manifest) == frozen_manifest["image"],
                "staged_image_identity",
            )
            write_new(
                attempt_dir / "migration-intent.json",
                {"chain": MIGRATION_CHAIN, "forward_only": True},
            )
            host.migrate_forward(ALEMBIC_ONLY_COMMAND, MIGRATION_CHAIN)
            require(host.read_schema_head() == TARGET_SCHEMA, "target_schema_mismatch")
            host.install_candidate(frozen_manifest)
            host.start_default_off(SERVICES)
            require(
                host.verify_candidate(frozen_manifest) is True, "candidate_postcheck"
            )
            write_new(
                attempt_dir / "simulation-receipt.json",
                {
                    "candidate": frozen_manifest["image"],
                    "default_off": True,
                    "verified": True,
                },
            )
            completed = True
        finally:
            if not completed:
                try:
                    write_new(
                        attempt_dir / "forward-recovery-required.json",
                        {
                            "candidate": frozen_manifest["image"],
                            "old_app_restart_forbidden": True,
                            "automatic_downgrade_or_restore_forbidden": True,
                        },
                    )
                finally:
                    host.stop_all()
    return {"phase": "simulated_success", "production_apply_available": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "apply"))
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    if args.action == "apply":
        print(json.dumps({"phase": "blocked", "code": "production_apply_unavailable"}))
        return 2
    if not (args.manifest and args.baseline and args.evidence):
        parser.error("plan requires --manifest, --baseline and --evidence")
    try:
        manifest = json.loads(args.manifest.read_bytes())
        baseline = json.loads(args.baseline.read_bytes())
        evidence = json.loads(args.evidence.read_bytes())
        result = plan(manifest, baseline, evidence)
    except (ReleaseBlocked, OSError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({"phase": "blocked", "code": str(exc)}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
