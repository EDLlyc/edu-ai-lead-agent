from __future__ import annotations

import copy
import fcntl
import importlib.util
import json
import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

import r16_enablement as enable

MODULE_PATH = Path(__file__).with_name("r16_forward_operator.py")
SPEC = importlib.util.spec_from_file_location("r16_forward_operator", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
operator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(operator)
HEX = "a" * 64


def fixture() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    manifest = {
        "revision": "1" * 40,
        "operator_source_revision": "1" * 40,
        "base_revision": operator.BASE_REVISION,
        "base_image": operator.BASE_IMAGE,
        "image": "sha256:" + "2" * 64,
        "archive_sha256": "3" * 64,
        "operator_sha256": operator.sha(MODULE_PATH.read_bytes()),
        "schema": operator.TARGET_SCHEMA,
        "migration_chain": operator.MIGRATION_CHAIN,
        "previous_application_compatible": False,
        "host_files": dict.fromkeys(operator.HOST_REPLACEMENTS, HEX),
    }
    baseline = {
        "release_commit": operator.BASE_REVISION,
        "release_commit_secondary": operator.BASE_REVISION,
        "image": operator.BASE_IMAGE,
        "release_env_image": operator.BASE_REF,
        "schema": operator.BASE_SCHEMA,
        "optional_producer_absent": True,
        "standard_manifest_absent": True,
        "backup_timer_active": True,
        "idle": True,
        "unknown_work_count": 0,
        "pending_work_count": 0,
        "business_identity_sha256": HEX,
        "brand_identity_sha256": HEX,
        "recipient_fingerprint": HEX,
        "flags": dict.fromkeys(operator.OFF_FLAGS, False),
        "services": {
            name: {
                "image": operator.BASE_IMAGE,
                "image_ref": operator.BASE_REF,
                "running": True,
                "healthy": True,
                "restarts": 0,
                "command_sha256": HEX,
                "mounts_sha256": HEX,
                "env_sha256": HEX,
            }
            for name in operator.SERVICES
        },
        "protected_files": {
            name: {"sha256": HEX, "mode": 0o600, "uid": 0, "gid": 0}
            for name in operator.PROTECTED_FILES
        },
        "volumes": dict.fromkeys(operator.VOLUMES, HEX),
    }
    images = [
        {
            "package_id": f"news-{index}",
            "jpeg_sha256": str(index) * 64,
            "exact_source": True,
            "ocr_pass": True,
            "phone_visual_pass": True,
            "send_ready": True,
        }
        for index in (5, 6, 7)
    ]
    evidence = {
        "images": images,
        "group_test": {
            "recipient_fingerprint": HEX,
            "package_id": "news-5",
            "test_marker": True,
            "outcomes": [
                "text_confirmed",
                "original_image_confirmed",
                "infographic_confirmed",
            ],
            "artifact_sha256": "5" * 64,
        },
        "candidate_image": manifest["image"],
        "candidate_archive_sha256": manifest["archive_sha256"],
    }
    return manifest, baseline, evidence


def production_fixture() -> tuple[dict[str, Any], dict[str, Any]]:
    manifest, baseline, _ = fixture()
    manifest["real_host_sha256"] = operator.sha(
        MODULE_PATH.with_name("r16_real_host.py").read_bytes()
    )
    manifest["release_cli_sha256"] = operator.sha(
        MODULE_PATH.with_name("r16_release_cli.py").read_bytes()
    )
    manifest["enable_operator_sha256"] = operator.sha(
        MODULE_PATH.with_name("r16_enablement.py").read_bytes()
    )
    manifest["enable_host_sha256"] = operator.sha(
        MODULE_PATH.with_name("r16_enable_host.py").read_bytes()
    )
    manifest["trusted_recipient_fingerprint"] = operator.APPROVED_RECIPIENT_FINGERPRINT
    manifest["trusted_recipient_key_sha256"] = operator.APPROVED_RECIPIENT_KEY_SHA256
    baseline["recipient_fingerprint"] = operator.APPROVED_RECIPIENT_FINGERPRINT
    return manifest, baseline


class FakeHost:
    def __init__(self, baseline: dict[str, Any], *, failure: str | None = None) -> None:
        self.baseline = copy.deepcopy(baseline)
        self.failure = failure
        self.calls: list[str] = []
        self.stopped = False

    def arm_production_mutation(
        self,
        manifest: dict[str, Any],
        baseline: dict[str, Any],
        manifest_sha256: str,
    ) -> None:
        assert manifest["revision"] == "1" * 40
        assert baseline == self.baseline
        assert manifest_sha256 == "d" * 64
        self.calls.append("arm_production_mutation")

    def capture(self) -> dict[str, Any]:
        self.calls.append("capture")
        return copy.deepcopy(self.baseline)

    def capture_quiescent(self) -> dict[str, Any]:
        self.calls.append("capture_quiescent")
        assert self.stopped
        return {
            "schema": self.baseline["schema"],
            "business_identity_sha256": self.baseline["business_identity_sha256"],
            "brand_identity_sha256": self.baseline["brand_identity_sha256"],
            "recipient_fingerprint": self.baseline["recipient_fingerprint"],
            "protected_files": copy.deepcopy(self.baseline["protected_files"]),
            "volumes": copy.deepcopy(self.baseline["volumes"]),
            "flags": copy.deepcopy(self.baseline["flags"]),
            "stopped_services": list(operator.SERVICES),
            "optional_producer_absent": True,
        }

    def backup(self) -> dict[str, Any]:
        self.calls.append("backup")
        if self.failure == "backup":
            raise RuntimeError("backup_failed")
        return {
            "baseline_sha256": operator.sha(operator.canonical(self.baseline)),
            "pg_dump_sha256": HEX,
            "pg_dump_bytes": 1_024,
            "pg_restore_toc_sha256": HEX,
            "pg_restore_toc_read": True,
            "protected_files_readback": True,
            "protected_files": copy.deepcopy(self.baseline["protected_files"]),
            "protected_metadata_sha256": HEX,
            "brand_materials_readback": True,
            "brand_identity_sha256": self.baseline["brand_identity_sha256"],
            "brand_archive_sha256": HEX,
            "source_config_readback": True,
            "source_config_archives": dict.fromkeys(
                ("backend", "deploy", "scripts", "infra"), HEX
            ),
            "volumes": dict.fromkeys(operator.VOLUMES, HEX),
            "volume_readbacks": dict.fromkeys(operator.VOLUMES, True),
        }

    def rehearse_clone(self, dump_sha256: str) -> dict[str, Any]:
        self.calls.append("rehearse_clone")
        if self.failure == "clone":
            raise RuntimeError("clone_failed")
        receipt = {
            "chain": operator.MIGRATION_CHAIN,
            "source_dump_sha256": dump_sha256,
            "isolated_restore_readback": self.failure != "clone_restore",
            "isolated_target": True,
            "source_business_sha256": self.baseline["business_identity_sha256"],
            "retained_business_sha256": self.baseline["business_identity_sha256"],
            "existing_table_counts_equal": True,
            "source_schema": operator.BASE_SCHEMA,
            "target_schema": operator.TARGET_SCHEMA,
        }
        if self.failure == "clone_old_dump":
            receipt["source_dump_sha256"] = "b" * 64
        receipt["receipt_sha256"] = operator.sha(operator.canonical(receipt))
        if self.failure == "clone_forged_receipt":
            receipt["receipt_sha256"] = "c" * 64
        return receipt

    def stop_writers(self) -> None:
        self.calls.append("stop_writers")
        if self.failure == "stop":
            raise RuntimeError("stop_failed")
        self.stopped = True

    def verify_writers_stopped(self) -> bool:
        self.calls.append("verify_writers_stopped")
        assert self.stopped
        return self.failure != "stop_verify"

    def stage_candidate_image(self, manifest: dict[str, Any]) -> str:
        assert manifest["schema"] == operator.TARGET_SCHEMA
        self.calls.append("stage_candidate_image")
        if self.failure == "stage":
            raise RuntimeError("image_stage_unknown")
        return manifest["image"]

    def migrate_forward(self, command: tuple[str, ...], chain: list[str]) -> None:
        assert command == operator.ALEMBIC_ONLY_COMMAND
        assert "seed_sources" not in command
        assert "minio-init" not in command
        assert chain == operator.MIGRATION_CHAIN
        self.calls.append("migrate_forward")
        if self.failure == "migration":
            raise RuntimeError("migration_unknown")

    def read_schema_head(self) -> str:
        self.calls.append("read_schema_head")
        return (
            operator.BASE_SCHEMA
            if self.failure == "schema_verify"
            else operator.TARGET_SCHEMA
        )

    def install_candidate(self, manifest: dict[str, Any]) -> None:
        assert manifest["schema"] == operator.TARGET_SCHEMA
        self.calls.append("install_candidate")
        if self.failure == "install":
            raise RuntimeError("install_unknown")

    def start_default_off(self, services: tuple[str, ...]) -> None:
        assert services == operator.SERVICES
        self.calls.append("start_default_off")

    def verify_candidate(self, manifest: dict[str, Any]) -> bool:
        assert manifest["image"].startswith("sha256:")
        self.calls.append("verify_candidate")
        return self.failure != "verify"

    def stop_all(self) -> None:
        self.calls.append("stop_all")
        self.stopped = True


def test_plan_is_never_deployment_ready() -> None:
    manifest, baseline, evidence = fixture()
    result = operator.plan(manifest, baseline, evidence)
    assert result["phase"] == "plan_only"
    assert result["services"] == 12
    assert result["production_apply_available"] is False
    assert result["enablement_ready"] is False


def test_missing_host_file_identity_blocks_release_plan() -> None:
    manifest, baseline, evidence = fixture()
    del manifest["host_files"]["compose.yaml"]
    with pytest.raises(operator.ReleaseBlocked, match="candidate_host_files"):
        operator.plan(manifest, baseline, evidence)


def test_default_off_release_does_not_require_undelivered_poster_receipts() -> None:
    manifest, baseline, evidence = fixture()
    del evidence["images"]
    del evidence["group_test"]
    assert operator.plan(manifest, baseline, evidence)["default_off"] is True
    with pytest.raises(operator.ReleaseBlocked, match="three_news_images"):
        operator.valid_enablement_evidence(baseline, evidence)


def test_readonly_capture_has_no_backup_or_service_side_effects() -> None:
    _, baseline, _ = fixture()
    host = FakeHost(baseline)
    result = operator.capture_readonly(host)
    assert result["baseline_sha256"] == operator.sha(operator.canonical(baseline))
    assert result["production_apply_available"] is False
    assert host.calls == ["capture"]


def test_operator_commit_split_requires_reviewed_byte_equivalence() -> None:
    manifest, baseline, evidence = fixture()
    manifest["operator_source_revision"] = "9" * 40
    with pytest.raises(operator.ReleaseBlocked, match="source_split_unreviewed"):
        operator.plan(manifest, baseline, evidence)
    manifest["source_split"] = {
        "runtime_unchanged": True,
        "migrations_unchanged": True,
        "compose_unchanged": True,
        "protected_files_unchanged": True,
        "review_receipt_sha256": "9" * 64,
    }
    assert (
        operator.plan(manifest, baseline, evidence)["production_apply_available"]
        is False
    )
    with pytest.raises(
        operator.ReleaseBlocked, match="production_source_split_unverified"
    ):
        operator.valid_production_manifest(manifest)


def test_production_manifest_requires_exact_operator_source_and_host_hash() -> None:
    manifest, _, _ = fixture()
    with pytest.raises(operator.ReleaseBlocked, match="real_host_source_unpinned"):
        operator.valid_production_manifest(manifest)
    manifest["real_host_sha256"] = operator.sha(
        MODULE_PATH.with_name("r16_real_host.py").read_bytes()
    )
    manifest["release_cli_sha256"] = operator.sha(
        MODULE_PATH.with_name("r16_release_cli.py").read_bytes()
    )
    manifest["enable_operator_sha256"] = operator.sha(
        MODULE_PATH.with_name("r16_enablement.py").read_bytes()
    )
    manifest["enable_host_sha256"] = operator.sha(
        MODULE_PATH.with_name("r16_enable_host.py").read_bytes()
    )
    with pytest.raises(operator.ReleaseBlocked, match="trusted_recipient_unpinned"):
        operator.valid_production_manifest(manifest)
    manifest["trusted_recipient_fingerprint"] = operator.APPROVED_RECIPIENT_FINGERPRINT
    manifest["trusted_recipient_key_sha256"] = operator.APPROVED_RECIPIENT_KEY_SHA256
    operator.valid_production_manifest(manifest)
    manifest["real_host_sha256"] = "f" * 64
    with pytest.raises(operator.ReleaseBlocked, match="real_host_source_hash_mismatch"):
        operator.valid_production_manifest(manifest)
    manifest["real_host_sha256"] = operator.sha(
        MODULE_PATH.with_name("r16_real_host.py").read_bytes()
    )
    manifest["source_split"] = {"review_receipt_sha256": "a" * 64}
    with pytest.raises(
        operator.ReleaseBlocked, match="production_source_split_unverified"
    ):
        operator.valid_production_manifest(manifest)


@pytest.mark.parametrize(
    ("path", "value", "code"),
    [
        (("candidate_image",), "sha256:" + "9" * 64, "image_evidence_identity"),
        (("candidate_archive_sha256",), "9" * 64, "image_evidence_identity"),
    ],
)
def test_missing_release_receipts_block(
    path: tuple[str | int, ...], value: Any, code: str
) -> None:
    manifest, baseline, evidence = fixture()
    current: Any = evidence
    for key in path[:-1]:
        current = current[key]
    current[path[-1]] = value
    with pytest.raises(operator.ReleaseBlocked, match=code):
        operator.plan(manifest, baseline, evidence)


@pytest.mark.parametrize(
    ("path", "value", "code"),
    [
        (("images",), [], "three_news_images"),
        (("images", 1, "jpeg_sha256"), "5" * 64, "distinct_news_images"),
        (("group_test", "outcomes"), ["text_confirmed"], "fixed_group_triple_receipt"),
        (("group_test", "artifact_sha256"), "6" * 64, "fixed_group_triple_receipt"),
    ],
)
def test_missing_enablement_receipts_block(
    path: tuple[str | int, ...], value: Any, code: str
) -> None:
    manifest, baseline, evidence = fixture()
    current: Any = evidence
    for key in path[:-1]:
        current = current[key]
    current[path[-1]] = value
    assert operator.plan(manifest, baseline, evidence)["enablement_ready"] is False
    with pytest.raises(operator.ReleaseBlocked, match=code):
        operator.valid_enablement_evidence(baseline, evidence)


def test_old_clone_receipt_is_not_a_preflight_input() -> None:
    manifest, baseline, evidence = fixture()
    evidence["migration_clone"] = {"source_dump_sha256": HEX}
    with pytest.raises(operator.ReleaseBlocked, match="preexisting_clone_receipt"):
        operator.plan(manifest, baseline, evidence)


def test_producer_enabled_or_missing_service_blocks() -> None:
    manifest, baseline, evidence = fixture()
    baseline["flags"]["WECOM_INFOGRAPHIC_PRODUCER_ENABLED"] = True
    with pytest.raises(operator.ReleaseBlocked, match="default_off_flags"):
        operator.plan(manifest, baseline, evidence)
    baseline["flags"]["WECOM_INFOGRAPHIC_PRODUCER_ENABLED"] = False
    del baseline["services"]["wecom-dispatcher"]
    with pytest.raises(operator.ReleaseBlocked, match="service_set"):
        operator.plan(manifest, baseline, evidence)


def test_fake_one_attempt_is_forward_only(tmp_path: Path) -> None:
    manifest, baseline, evidence = fixture()
    host = FakeHost(baseline)
    attempt = tmp_path / "attempt"
    locks = (tmp_path / "deploy.lock", tmp_path / "backup.lock")
    result = operator.simulate(host, manifest, baseline, evidence, attempt, locks)
    assert result["production_apply_available"] is False
    assert host.calls == [
        "capture",
        "stop_writers",
        "verify_writers_stopped",
        "capture_quiescent",
        "backup",
        "capture_quiescent",
        "stage_candidate_image",
        "rehearse_clone",
        "migrate_forward",
        "read_schema_head",
        "install_candidate",
        "start_default_off",
        "verify_candidate",
    ]
    assert (attempt / "intent.json").exists()
    assert (attempt / "migration-intent.json").exists()
    assert (attempt / "clone-receipt.json").exists()
    assert (attempt / "simulation-receipt.json").exists()
    with pytest.raises(operator.ReleaseBlocked, match="attempt_exists_reconcile_only"):
        operator.simulate(host, manifest, baseline, evidence, attempt, locks)


@pytest.mark.parametrize(
    "failure",
    [
        "stop",
        "stop_verify",
        "stage",
        "clone",
        "migration",
        "schema_verify",
        "install",
        "verify",
    ],
)
def test_any_post_intent_failure_stops_and_requires_forward_recovery(
    tmp_path: Path, failure: str
) -> None:
    manifest, baseline, evidence = fixture()
    host = FakeHost(baseline, failure=failure)
    attempt = tmp_path / "attempt"
    with pytest.raises(RuntimeError):
        operator.simulate(
            host,
            manifest,
            baseline,
            evidence,
            attempt,
            (tmp_path / "deploy.lock", tmp_path / "backup.lock"),
        )
    assert host.calls[-1] == "stop_all"
    assert host.calls.count("migrate_forward") <= 1
    assert not (attempt / "simulation-receipt.json").exists()
    recovery = json.loads((attempt / "forward-recovery-required.json").read_text())
    assert recovery["old_app_restart_forbidden"] is True
    assert recovery["automatic_downgrade_or_restore_forbidden"] is True
    prior_calls = list(host.calls)
    with pytest.raises(operator.ReleaseBlocked, match="attempt_exists_reconcile_only"):
        operator.simulate(
            host,
            manifest,
            baseline,
            evidence,
            attempt,
            (tmp_path / "deploy.lock", tmp_path / "backup.lock"),
        )
    assert host.calls == prior_calls


def test_backup_failure_after_quiescence_requires_forward_recovery(
    tmp_path: Path,
) -> None:
    manifest, baseline, evidence = fixture()
    host = FakeHost(baseline, failure="backup")
    attempt = tmp_path / "attempt"
    with pytest.raises(RuntimeError, match="backup_failed"):
        operator.simulate(
            host,
            manifest,
            baseline,
            evidence,
            attempt,
            (tmp_path / "deploy.lock", tmp_path / "backup.lock"),
        )
    assert host.calls == [
        "capture",
        "stop_writers",
        "verify_writers_stopped",
        "capture_quiescent",
        "backup",
        "stop_all",
    ]
    assert (attempt / "intent.json").exists()
    assert (attempt / "forward-recovery-required.json").exists()
    assert not (attempt / "migration-intent.json").exists()


@pytest.mark.parametrize(
    ("path", "value", "code"),
    [
        (("pg_dump_bytes",), 0, "backup_receipt"),
        (("pg_restore_toc_read",), False, "backup_receipt"),
        (("protected_files_readback",), False, "backup_receipt"),
        (("protected_files", "compose.yaml", "sha256"), "b" * 64, "backup_receipt"),
        (("protected_metadata_sha256",), "not-a-sha", "backup_receipt"),
        (("brand_materials_readback",), False, "backup_receipt"),
        (("brand_identity_sha256",), "b" * 64, "backup_receipt"),
        (("brand_archive_sha256",), "not-a-sha", "backup_receipt"),
        (("source_config_readback",), False, "backup_receipt"),
        (("source_config_archives", "backend"), "not-a-sha", "backup_source_receipt"),
        (("volumes", operator.VOLUMES[0]), "not-a-sha", "backup_volume_receipt"),
        (("volume_readbacks", operator.VOLUMES[1]), False, "backup_volume_receipt"),
    ],
)
def test_incomplete_backup_receipt_blocks_before_intent(
    tmp_path: Path, path: tuple[str, ...], value: Any, code: str
) -> None:
    manifest, baseline, evidence = fixture()

    class IncompleteBackupHost(FakeHost):
        def backup(self) -> dict[str, Any]:
            receipt = super().backup()
            target: Any = receipt
            for key in path[:-1]:
                target = target[key]
            target[path[-1]] = value
            return receipt

    host = IncompleteBackupHost(baseline)
    attempt = tmp_path / "attempt"
    with pytest.raises(operator.ReleaseBlocked, match=code):
        operator.simulate(
            host,
            manifest,
            baseline,
            evidence,
            attempt,
            (tmp_path / "deploy.lock", tmp_path / "backup.lock"),
        )
    assert host.calls[-1] == "stop_all"
    assert (attempt / "forward-recovery-required.json").exists()
    assert not (attempt / "migration-intent.json").exists()


def test_second_lock_contention_blocks_before_host_capture(tmp_path: Path) -> None:
    manifest, baseline, evidence = fixture()
    host = FakeHost(baseline)
    backup_lock = tmp_path / "backup.lock"
    fd = os.open(backup_lock, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            operator.simulate(
                host,
                manifest,
                baseline,
                evidence,
                tmp_path / "attempt",
                (tmp_path / "deploy.lock", backup_lock),
            )
        assert host.calls == []
        assert not (tmp_path / "attempt").exists()
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def test_backup_cannot_rewrite_the_expected_baseline(tmp_path: Path) -> None:
    manifest, baseline, evidence = fixture()

    class MutatingBackupHost(FakeHost):
        def backup(self) -> dict[str, Any]:
            baseline["brand_identity_sha256"] = "b" * 64
            self.baseline = copy.deepcopy(baseline)
            return super().backup()

    host = MutatingBackupHost(baseline)
    attempt = tmp_path / "attempt"
    with pytest.raises(operator.ReleaseBlocked, match="backup_receipt"):
        operator.simulate(
            host,
            manifest,
            baseline,
            evidence,
            attempt,
            (tmp_path / "deploy.lock", tmp_path / "backup.lock"),
        )
    assert host.calls[-1] == "stop_all"
    assert (attempt / "forward-recovery-required.json").exists()
    assert not (attempt / "migration-intent.json").exists()


def test_backup_cannot_rewrite_checked_candidate_or_clone_identity(
    tmp_path: Path,
) -> None:
    manifest, baseline, evidence = fixture()
    checked_image = manifest["image"]

    class MutatingContractHost(FakeHost):
        def backup(self) -> dict[str, Any]:
            manifest["image"] = "sha256:" + "9" * 64
            return super().backup()

        def install_candidate(self, candidate: dict[str, Any]) -> None:
            assert candidate["image"] == checked_image
            super().install_candidate(candidate)

    host = MutatingContractHost(baseline)
    attempt = tmp_path / "attempt"
    operator.simulate(
        host,
        manifest,
        baseline,
        evidence,
        attempt,
        (tmp_path / "deploy.lock", tmp_path / "backup.lock"),
    )
    receipt = json.loads((attempt / "simulation-receipt.json").read_text())
    assert receipt["candidate"] == checked_image


@pytest.mark.parametrize(
    "failure", ["clone_restore", "clone_old_dump", "clone_forged_receipt"]
)
def test_fresh_clone_must_bind_actual_dump_and_verified_receipt(
    tmp_path: Path, failure: str
) -> None:
    manifest, baseline, evidence = fixture()
    host = FakeHost(baseline, failure=failure)
    attempt = tmp_path / "attempt"
    with pytest.raises(operator.ReleaseBlocked, match="fresh_migration_clone_receipt"):
        operator.simulate(
            host,
            manifest,
            baseline,
            evidence,
            attempt,
            (tmp_path / "deploy.lock", tmp_path / "backup.lock"),
        )
    assert "migrate_forward" not in host.calls
    assert not (attempt / "migration-intent.json").exists()
    assert (attempt / "forward-recovery-required.json").exists()


def test_changed_dump_bytes_use_new_hash_not_stale_clone_hash(tmp_path: Path) -> None:
    manifest, baseline, evidence = fixture()

    class ChangedDumpHost(FakeHost):
        def backup(self) -> dict[str, Any]:
            receipt = super().backup()
            receipt["pg_dump_sha256"] = "d" * 64
            return receipt

    host = ChangedDumpHost(baseline)
    attempt = tmp_path / "attempt"
    operator.simulate(
        host,
        manifest,
        baseline,
        evidence,
        attempt,
        (tmp_path / "deploy.lock", tmp_path / "backup.lock"),
    )
    clone = json.loads((attempt / "clone-receipt.json").read_text())
    assert clone["source_dump_sha256"] == "d" * 64
    assert clone["source_dump_sha256"] != HEX


def test_stopped_writer_identity_drift_blocks_before_migration(tmp_path: Path) -> None:
    manifest, baseline, evidence = fixture()

    class DriftAfterBackupHost(FakeHost):
        def backup(self) -> dict[str, Any]:
            receipt = super().backup()
            self.baseline["business_identity_sha256"] = "b" * 64
            return receipt

    host = DriftAfterBackupHost(baseline)
    attempt = tmp_path / "attempt"
    with pytest.raises(operator.ReleaseBlocked, match="post_backup_quiescent_drift"):
        operator.simulate(
            host,
            manifest,
            baseline,
            evidence,
            attempt,
            (tmp_path / "deploy.lock", tmp_path / "backup.lock"),
        )
    assert host.calls[-1] == "stop_all"
    assert "migrate_forward" not in host.calls
    assert (attempt / "forward-recovery-required.json").exists()


def test_wrong_post_migration_head_is_rejected_explicitly(tmp_path: Path) -> None:
    manifest, baseline, evidence = fixture()
    host = FakeHost(baseline, failure="schema_verify")
    attempt = tmp_path / "attempt"
    with pytest.raises(operator.ReleaseBlocked, match="target_schema_mismatch"):
        operator.simulate(
            host,
            manifest,
            baseline,
            evidence,
            attempt,
            (tmp_path / "deploy.lock", tmp_path / "backup.lock"),
        )
    assert "install_candidate" not in host.calls
    assert (attempt / "migration-intent.json").exists()
    assert (attempt / "forward-recovery-required.json").exists()


def test_wrong_staged_image_digest_blocks_before_migration(tmp_path: Path) -> None:
    manifest, baseline, evidence = fixture()

    class WrongImageHost(FakeHost):
        def stage_candidate_image(self, candidate: dict[str, Any]) -> str:
            super().stage_candidate_image(candidate)
            return "sha256:" + "9" * 64

    host = WrongImageHost(baseline)
    attempt = tmp_path / "attempt"
    with pytest.raises(operator.ReleaseBlocked, match="staged_image_identity"):
        operator.simulate(
            host,
            manifest,
            baseline,
            evidence,
            attempt,
            (tmp_path / "deploy.lock", tmp_path / "backup.lock"),
        )
    assert "migrate_forward" not in host.calls
    assert not (attempt / "migration-intent.json").exists()
    assert (attempt / "forward-recovery-required.json").exists()


def test_recovery_marker_is_written_even_if_stop_all_fails(tmp_path: Path) -> None:
    manifest, baseline, evidence = fixture()

    class StopFailsHost(FakeHost):
        def stop_all(self) -> None:
            super().stop_all()
            raise RuntimeError("stop_all_failed")

    host = StopFailsHost(baseline, failure="migration")
    attempt = tmp_path / "attempt"
    with pytest.raises(RuntimeError, match="stop_all_failed"):
        operator.simulate(
            host,
            manifest,
            baseline,
            evidence,
            attempt,
            (tmp_path / "deploy.lock", tmp_path / "backup.lock"),
        )
    assert host.calls[-1] == "stop_all"
    assert (attempt / "forward-recovery-required.json").exists()
    assert not (attempt / "simulation-receipt.json").exists()


def test_cli_production_apply_is_hard_disabled_even_with_paths(tmp_path: Path) -> None:
    result = subprocess.run(
        [
            "python3",
            str(MODULE_PATH),
            "apply",
            "--manifest",
            str(tmp_path / "missing-manifest.json"),
            "--baseline",
            str(tmp_path / "missing-baseline.json"),
            "--evidence",
            str(tmp_path / "missing-evidence.json"),
        ],
        capture_output=True,
        check=False,
        text=True,
    )
    assert result.returncode == 2
    assert json.loads(result.stdout) == {
        "phase": "blocked",
        "code": "production_apply_unavailable",
    }


def test_actual_operator_one_attempt_fake_host_is_default_off(
    tmp_path: Path,
) -> None:
    manifest, baseline = production_fixture()
    host = FakeHost(baseline)
    attempt = tmp_path / "r16-forward-fake1"
    locks = (tmp_path / "deploy.lock", tmp_path / "backup.lock")
    receipt = operator.apply_release(host, manifest, "d" * 64, attempt, locks)
    assert receipt["status"] == "deployed_default_off"
    assert receipt["simulation_only"] is False
    assert receipt["default_off"] is True
    assert (
        json.loads((attempt / "intent.json").read_text())["manifest_sha256"] == "d" * 64
    )
    assert (attempt / "backup-receipt.json").exists()
    assert (attempt / "clone-receipt.json").exists()
    assert (attempt / "migration-intent.json").exists()
    migration_intent = json.loads((attempt / "migration-intent.json").read_text())
    assert migration_intent["if_unobserved"] == "forward_reconcile_only"
    assert migration_intent["old_app_restart_forbidden"] is True
    assert migration_intent["automatic_restore_or_downgrade_forbidden"] is True
    assert json.loads((attempt / "release-receipt.json").read_text()) == receipt
    enable.valid_release_receipt(manifest, receipt)
    assert host.calls.index("backup") < host.calls.index("rehearse_clone")
    assert host.calls.index("rehearse_clone") < host.calls.index("migrate_forward")
    assert host.calls.index("migrate_forward") < host.calls.index("start_default_off")
    assert "stop_all" not in host.calls
    with pytest.raises(operator.ReleaseBlocked, match="attempt_exists_reconcile_only"):
        operator.apply_release(host, manifest, "d" * 64, attempt, locks)


@pytest.mark.parametrize(
    "failure", ["stop", "backup", "stage", "clone", "migration", "verify"]
)
def test_actual_operator_failure_is_forward_only(tmp_path: Path, failure: str) -> None:
    manifest, baseline = production_fixture()
    host = FakeHost(baseline, failure=failure)
    attempt = tmp_path / "r16-forward-fake1"
    with pytest.raises(RuntimeError):
        operator.apply_release(
            host,
            manifest,
            "d" * 64,
            attempt,
            (tmp_path / "deploy.lock", tmp_path / "backup.lock"),
        )
    assert host.calls[-1] == "stop_all"
    assert (attempt / "intent.json").exists()
    assert (attempt / "forward-recovery-required.json").exists()
    assert not (attempt / "release-receipt.json").exists()
    assert host.calls.count("migrate_forward") <= 1


def test_actual_operator_lock_contention_prevents_attempt(tmp_path: Path) -> None:
    manifest, baseline = production_fixture()
    host = FakeHost(baseline)
    backup_lock = tmp_path / "backup.lock"
    fd = os.open(backup_lock, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with pytest.raises(BlockingIOError):
            operator.apply_release(
                host,
                manifest,
                "d" * 64,
                tmp_path / "r16-forward-fake1",
                (tmp_path / "deploy.lock", backup_lock),
            )
        assert host.calls == []
        assert not (tmp_path / "r16-forward-fake1").exists()
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def test_actual_operator_wrong_group_blocks_before_intent(tmp_path: Path) -> None:
    manifest, baseline = production_fixture()
    baseline["recipient_fingerprint"] = "f" * 64
    host = FakeHost(baseline)
    attempt = tmp_path / "r16-forward-fake1"
    with pytest.raises(operator.ReleaseBlocked, match="approved_recipient_mismatch"):
        operator.apply_release(
            host,
            manifest,
            "d" * 64,
            attempt,
            (tmp_path / "deploy.lock", tmp_path / "backup.lock"),
        )
    assert host.calls == ["capture"]
    assert not attempt.exists()


def test_synthetic_crash_after_migration_intent_is_reconcile_only(
    tmp_path: Path,
) -> None:
    manifest, baseline = production_fixture()
    host = FakeHost(baseline)
    attempt = tmp_path / "r16-forward-crash1"
    attempt.mkdir(mode=0o700)
    operator.write_new(
        attempt / "migration-intent.json",
        {
            "chain": operator.MIGRATION_CHAIN,
            "forward_only": True,
            "if_unobserved": "forward_reconcile_only",
            "old_app_restart_forbidden": True,
        },
    )
    assert not (attempt / "release-receipt.json").exists()
    with pytest.raises(operator.ReleaseBlocked, match="attempt_exists_reconcile_only"):
        operator.apply_release(
            host,
            manifest,
            "d" * 64,
            attempt,
            (tmp_path / "deploy.lock", tmp_path / "backup.lock"),
        )
    assert host.calls == []
