from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import r16_enablement as enable
import r16_forward_operator as release_operator

HEX = "a" * 64


def fixture() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    manifest = {
        "revision": "1" * 40,
        "operator_source_revision": "1" * 40,
        "base_revision": release_operator.BASE_REVISION,
        "base_image": release_operator.BASE_IMAGE,
        "image": "sha256:" + "2" * 64,
        "archive_sha256": "3" * 64,
        "operator_sha256": release_operator.sha(
            Path(release_operator.__file__).read_bytes()
        ),
        "real_host_sha256": "7" * 64,
        "release_cli_sha256": "8" * 64,
        "schema": release_operator.TARGET_SCHEMA,
        "migration_chain": release_operator.MIGRATION_CHAIN,
        "previous_application_compatible": False,
        "host_files": dict.fromkeys(release_operator.HOST_REPLACEMENTS, HEX),
    }
    released = {
        "version": "r16-default-off-production-receipt-v1",
        "status": "deployed_default_off",
        "attempt_id": "r16-forward-20260927-test",
        "manifest_sha256": "6" * 64,
        "candidate": manifest["image"],
        "revision": manifest["revision"],
        "archive_sha256": manifest["archive_sha256"],
        "operator_sha256": manifest["operator_sha256"],
        "real_host_sha256": manifest.get("real_host_sha256"),
        "release_cli_sha256": manifest.get("release_cli_sha256"),
        "schema": release_operator.TARGET_SCHEMA,
        "migration_chain": release_operator.MIGRATION_CHAIN,
        "services": len(release_operator.SERVICES),
        "default_off": True,
        "simulation_only": False,
        "recipient_fingerprint": HEX,
        "pre_stop_baseline_sha256": HEX,
        "baseline_sha256": HEX,
        "quiescent_receipt_sha256": HEX,
        "backup_receipt_sha256": "4" * 64,
        "clone_receipt_sha256": "5" * 64,
    }
    released["receipt_sha256"] = enable._receipt_hash(released)
    current: dict[str, Any] = {
        "image": manifest["image"],
        "revision": manifest["revision"],
        "schema": release_operator.TARGET_SCHEMA,
        "recipient_fingerprint": HEX,
        "base_delivery_healthy": True,
        "unknown_work_count": 0,
        "pending_work_count": 0,
        "flags": dict.fromkeys(release_operator.OFF_FLAGS, False),
        "producer_running": False,
        "max_ordinal": 1,
        "review_mode": "strict",
        "services": {
            name: {
                "image": manifest["image"],
                "running": True,
                "healthy": True,
            }
            for name in release_operator.SERVICES
        },
    }
    current["services"]["wecom-dispatcher"]["runtime_infographic"] = {
        **dict.fromkeys(enable.DISPATCHER_FLAGS, False),
        "WECOM_INFOGRAPHIC_REVIEW_MODE": "strict",
        "WECOM_INFOGRAPHIC_MAX_ORDINAL": 1,
    }
    images = []
    for index, slot in enumerate(enable.SLOTS, start=1):
        images.append(
            {
                "package_id": f"news-{index}",
                "base_job_id": f"base-{index}",
                "business_date": "2026-09-27",
                "slot": slot,
                "ordinal": index,
                "recipient_fingerprint": HEX,
                "jpeg_sha256": str(index) * 64,
                "jpeg_bytes": 800_000 + index,
                "media_type": "image/jpeg",
                "final_jpeg_checked": True,
                "jpeg_width": 1152,
                "jpeg_height": 2048,
                "source_url_sha256": str(index + 3) * 64,
                "footer_url_sha256": str(index + 3) * 64,
                "source_date": "2026-09-26",
                "footer_date": "2026-09-26",
                "warning_notice_version": enable.NOTICE_VERSION,
                "warning_visible": True,
                "image_intent_count": 1,
                "image_result_known": True,
                "delivery_unknown": False,
                "exact_source": True,
                "ocr_pass": True,
                "phone_visual_pass": True,
                "send_ready": True,
            }
        )
    group = {
        "recipient_fingerprint": HEX,
        "package_id": "news-1",
        "base_job_id": "base-1",
        "business_date": "2026-09-27",
        "slot": "morning",
        "ordinal": 1,
        "test_marker": True,
        "outcomes": [
            "text_confirmed",
            "original_image_confirmed",
            "infographic_confirmed",
        ],
        "artifact_sha256": "1" * 64,
        "jpeg_bytes": 800_001,
        "source_url_sha256": "4" * 64,
        "unknown_count": 0,
        "infographic_attempt_count": 1,
    }
    group["receipt_sha256"] = enable._receipt_hash(group)
    evidence = {
        "rollout_policy": enable.POLICY,
        "images": images,
        "group_test": group,
        "failure_isolation": {
            "base_status": "delivered",
            "text_confirmed": True,
            "original_image_confirmed": True,
            "supplement_status": "failed",
            "unknown_result_auto_replayed": False,
            "test_receipt_sha256": "f" * 64,
        },
    }
    return manifest, released, current, evidence


def direct_first_live_fixture(
    *,
    with_candidate: bool = False,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    manifest, released, current, strict_evidence = fixture()
    auth = {
        "version": enable.DIRECT_FIRST_LIVE_AUTH_VERSION,
        "decision": enable.DIRECT_FIRST_LIVE_DECISION,
        "scope": "every_delivered_news_all_three_slots",
        "user_authorization_record_sha256": "6" * 64,
        "operator_id": "release-operator-1",
        "operator_approved_at_utc": "2026-09-27T06:00:00Z",
        "operator_acknowledged": True,
        "recipient_fingerprint_method": "sha256(group_webhook\\0key)",
        "recipient_route": "existing_ordinary_group_webhook",
        "ordinary_group_acknowledged": True,
        "recipient_fingerprint": current["recipient_fingerprint"],
        "release_receipt_sha256": released["receipt_sha256"],
        "waive_three_previews": True,
        "waive_fixed_group_test": True,
        "first_success_to_ordinary_group": True,
        "max_daily_image_intents": 9,
        "provider_failure_preserves_base": True,
        "unknown_result_auto_replay": False,
    }
    auth["authorization_sha256"] = release_operator.sha(
        release_operator.canonical(
            {key: value for key, value in auth.items() if key != "authorization_sha256"}
        )
    )
    evidence = {
        "enablement_mode": enable.DIRECT_FIRST_LIVE_MODE,
        "rollout_policy": enable.DIRECT_FIRST_LIVE_POLICY,
        "direct_first_live_authorization": auth,
        "failure_isolation": strict_evidence["failure_isolation"],
    }
    if with_candidate:
        candidate = strict_evidence["images"][0]
        evidence["first_live_candidate"] = candidate
        evidence["first_live_expected"] = {
            field: candidate[field]
            for field in (
                "package_id",
                "base_job_id",
                "business_date",
                "slot",
                "ordinal",
                "recipient_fingerprint",
                "source_url_sha256",
                "source_date",
                "jpeg_sha256",
            )
        }
        evidence["first_live_expected"].update(
            {
                "max_daily_image_intents": 9,
                "base_text_confirmed": True,
                "base_original_image_confirmed": True,
                "within_slot_window": True,
            }
        )
    return manifest, released, current, evidence


class FakeHost:
    def __init__(self, current: dict[str, Any], failure: str | None = None) -> None:
        self.current = copy.deepcopy(current)
        self.failure = failure
        self.calls: list[str] = []

    def capture(self) -> dict[str, Any]:
        self.calls.append("capture")
        return copy.deepcopy(self.current)

    def arm_production_mutation(
        self, manifest: dict[str, Any], current: dict[str, Any]
    ) -> None:
        self.calls.append("arm_production_mutation")
        assert manifest["image"] == current["image"]

    def install_flags(
        self, flags: dict[str, bool], max_ordinal: int, review_mode: str
    ) -> None:
        self.calls.append("install_flags")
        if self.failure == "flags":
            raise RuntimeError("flags_failed")
        self.current["flags"] = dict(flags)
        self.current["max_ordinal"] = max_ordinal
        self.current["review_mode"] = review_mode

    def restart_dispatcher(self, command: tuple[str, ...]) -> None:
        self.calls.append("restart_dispatcher")
        assert "--no-deps" in command
        assert command[-1] == "wecom-dispatcher"
        assert "backend-migrate" not in command
        if self.failure == "dispatcher":
            raise RuntimeError("dispatcher_failed")
        self.current["services"]["wecom-dispatcher"]["runtime_infographic"] = {
            **{name: self.current["flags"][name] for name in enable.DISPATCHER_FLAGS},
            "WECOM_INFOGRAPHIC_REVIEW_MODE": self.current["review_mode"],
            "WECOM_INFOGRAPHIC_MAX_ORDINAL": self.current["max_ordinal"],
        }

    def start_producer(self, command: tuple[str, ...]) -> None:
        self.calls.append("start_producer")
        assert "--no-deps" in command
        assert "--profile" in command and "infographic" in command
        assert command[-1] == "wecom-infographic-producer"
        assert "minio-init" not in command
        if self.failure == "producer":
            raise RuntimeError("producer_failed")
        self.current["producer_running"] = True
        self.current["producer_image"] = self.current["image"]
        self.current["producer_healthy"] = True
        self.current["producer_runtime_infographic"] = {
            **{name: self.current["flags"][name] for name in enable.PRODUCER_FLAGS},
            "WECOM_INFOGRAPHIC_REVIEW_MODE": self.current["review_mode"],
            "WECOM_INFOGRAPHIC_MAX_ORDINAL": self.current["max_ordinal"],
        }
        if self.failure == "wrong_recipient":
            self.current["recipient_fingerprint"] = "b" * 64
        if self.failure == "base_regressed":
            self.current["base_delivery_healthy"] = False
        if self.failure == "wrong_dispatcher_runtime":
            self.current["services"]["wecom-dispatcher"]["runtime_infographic"][
                "WECOM_INFOGRAPHIC_DELIVERY_ENABLED"
            ] = False
        if self.failure == "wrong_producer_runtime":
            self.current["producer_runtime_infographic"][
                "WECOM_INFOGRAPHIC_PRODUCER_ENABLED"
            ] = False

    def disable_supplement_preserve_base(self) -> None:
        self.calls.append("disable_supplement_preserve_base")
        self.current["flags"] = dict.fromkeys(release_operator.OFF_FLAGS, False)
        self.current["max_ordinal"] = 1
        self.current["review_mode"] = "strict"
        self.current["producer_running"] = False
        self.current["base_delivery_healthy"] = True


def test_plan_explicit_direct_all_news_but_never_authorizes_production() -> None:
    manifest, released, current, evidence = fixture()
    result = enable.plan(manifest, released, current, evidence)
    assert result["phase"] == "enablement_plan_only"
    assert result["production_enable_available"] is False
    assert result["slots"] == ["morning", "noon", "evening"]
    assert result["max_ordinal"] == 3
    assert result["flags"]["WECOM_INFOGRAPHIC_TEST_ENABLED"] is False
    assert result["waived_pre_enable_gates"] == []
    assert all(
        result["flags"][f"WECOM_INFOGRAPHIC_{slot.upper()}_ENABLED"]
        for slot in enable.SLOTS
    )
    assert "morning_gray" not in evidence


def test_simulated_default_off_receipt_cannot_be_promoted() -> None:
    manifest, released, current, evidence = fixture()
    released["simulation_only"] = True
    released["receipt_sha256"] = enable._receipt_hash(released)
    with pytest.raises(
        release_operator.ReleaseBlocked, match="default_off_release_receipt"
    ):
        enable.plan(manifest, released, current, evidence)


@pytest.mark.parametrize(
    ("section", "field", "value", "code"),
    [
        ("current", "max_ordinal", 2, "enablement_current_identity"),
        ("current", "recipient_fingerprint", "b" * 64, "enablement_current_identity"),
        ("current", "unknown_work_count", 1, "enablement_current_identity"),
        ("evidence", "rollout_policy", "morning-only", "enablement_policy"),
        ("sample", "jpeg_bytes", 2 * 1024 * 1024 + 1, "same_news_final_jpeg"),
        ("sample", "jpeg_width", 1024, "same_news_final_jpeg"),
        ("sample", "image_intent_count", True, "same_news_final_jpeg"),
        ("sample", "footer_url_sha256", "b" * 64, "same_news_final_jpeg"),
        ("sample", "footer_date", "2026-09-27", "same_news_final_jpeg"),
        ("sample", "recipient_fingerprint", "b" * 64, "same_news_final_jpeg"),
        ("sample", "image_intent_count", 2, "same_news_final_jpeg"),
        ("sample", "image_result_known", False, "same_news_final_jpeg"),
        ("sample", "delivery_unknown", True, "same_news_final_jpeg"),
        ("sample", "warning_visible", False, "same_news_final_jpeg"),
        ("group", "base_job_id", "base-other", "same_news_fixed_group_receipt"),
        ("group", "jpeg_bytes", 1, "same_news_fixed_group_receipt"),
        ("group", "unknown_count", 1, "same_news_fixed_group_receipt"),
        (
            "isolation",
            "unknown_result_auto_replayed",
            True,
            "base_delivery_failure_isolation",
        ),
        ("isolation", "base_status", "failed", "base_delivery_failure_isolation"),
    ],
)
def test_wrong_identity_bytes_source_or_replay_blocks(
    section: str, field: str, value: Any, code: str
) -> None:
    manifest, released, current, evidence = fixture()
    target: dict[str, Any]
    if section == "current":
        target = current
    elif section == "sample":
        target = evidence["images"][0]
    elif section == "group":
        target = evidence["group_test"]
    elif section == "isolation":
        target = evidence["failure_isolation"]
    else:
        target = evidence
    target[field] = value
    if section == "group":
        target["receipt_sha256"] = enable._receipt_hash(target)
    with pytest.raises(release_operator.ReleaseBlocked, match=code):
        enable.plan(manifest, released, current, evidence)


def test_fixed_group_remains_required() -> None:
    manifest, released, current, evidence = fixture()
    del evidence["group_test"]
    with pytest.raises(
        release_operator.ReleaseBlocked, match="fixed_group_triple_receipt"
    ):
        enable.plan(manifest, released, current, evidence)


def test_direct_first_live_requires_explicit_authorization_not_three_images() -> None:
    manifest, released, current, evidence = direct_first_live_fixture()
    assert "images" not in evidence and "group_test" not in evidence
    result = enable.plan(manifest, released, current, evidence)
    assert result["enablement_mode"] == enable.DIRECT_FIRST_LIVE_MODE
    assert result["policy"] == enable.DIRECT_FIRST_LIVE_POLICY
    assert result["first_success_to_ordinary_group"] is True
    assert result["max_daily_image_intents"] == 9
    assert result["slots"] == ["morning", "noon", "evening"]
    assert result["max_ordinal"] == 3
    assert all(
        result["flags"][f"WECOM_INFOGRAPHIC_{slot.upper()}_ENABLED"]
        for slot in enable.SLOTS
    )
    assert result["waived_pre_enable_gates"] == [
        "three_approved_jpegs",
        "fixed_group_triple_receipt",
    ]
    assert (
        result["authorization_sha256"]
        == evidence["direct_first_live_authorization"]["authorization_sha256"]
    )
    assert result["production_enable_available"] is False


@pytest.mark.parametrize(
    ("section", "field", "value", "code"),
    [
        ("evidence", "enablement_mode", "other", "enablement_mode"),
        ("evidence", "rollout_policy", enable.POLICY, "enablement_policy"),
        ("auth", "decision", "try_test_group_first", "direct_first_live_authorization"),
        (
            "auth",
            "user_authorization_record_sha256",
            "",
            "direct_first_live_authorization",
        ),
        ("auth", "operator_acknowledged", False, "direct_first_live_authorization"),
        (
            "auth",
            "recipient_route",
            "fixed_test_group_webhook",
            "direct_first_live_authorization",
        ),
        (
            "auth",
            "ordinary_group_acknowledged",
            False,
            "direct_first_live_authorization",
        ),
        ("auth", "recipient_fingerprint", "b" * 64, "direct_first_live_authorization"),
        (
            "auth",
            "release_receipt_sha256",
            "b" * 64,
            "direct_first_live_authorization",
        ),
        ("auth", "waive_fixed_group_test", False, "direct_first_live_authorization"),
        (
            "auth",
            "first_success_to_ordinary_group",
            False,
            "direct_first_live_authorization",
        ),
        ("auth", "max_daily_image_intents", 10, "direct_first_live_authorization"),
        ("auth", "unknown_result_auto_replay", True, "direct_first_live_authorization"),
        ("auth", "authorization_sha256", "0" * 64, "direct_first_live_authorization"),
        ("current", "recipient_fingerprint", "b" * 64, "enablement_current_identity"),
    ],
)
def test_direct_first_live_waiver_and_recipient_cannot_drift(
    section: str, field: str, value: Any, code: str
) -> None:
    manifest, released, current, evidence = direct_first_live_fixture()
    target = (
        evidence["direct_first_live_authorization"]
        if section == "auth"
        else current
        if section == "current"
        else evidence
    )
    target[field] = value
    if section == "auth" and field != "authorization_sha256":
        target["authorization_sha256"] = release_operator.sha(
            release_operator.canonical(
                {
                    key: item
                    for key, item in target.items()
                    if key != "authorization_sha256"
                }
            )
        )
    with pytest.raises(release_operator.ReleaseBlocked, match=code):
        enable.plan(manifest, released, current, evidence)


def test_direct_first_live_rejects_extra_waiver_claims() -> None:
    manifest, released, current, evidence = direct_first_live_fixture()
    evidence["waive_source_identity"] = True
    with pytest.raises(
        release_operator.ReleaseBlocked, match="direct_first_live_evidence_fields"
    ):
        enable.plan(manifest, released, current, evidence)
    del evidence["waive_source_identity"]
    auth = evidence["direct_first_live_authorization"]
    auth["waive_final_jpeg_checks"] = True
    auth["authorization_sha256"] = release_operator.sha(
        release_operator.canonical(
            {key: value for key, value in auth.items() if key != "authorization_sha256"}
        )
    )
    with pytest.raises(
        release_operator.ReleaseBlocked, match="direct_first_live_authorization"
    ):
        enable.plan(manifest, released, current, evidence)


def test_direct_first_live_provider_failure_must_preserve_base() -> None:
    manifest, released, current, evidence = direct_first_live_fixture()
    evidence["failure_isolation"]["original_image_confirmed"] = False
    with pytest.raises(
        release_operator.ReleaseBlocked, match="base_delivery_failure_isolation"
    ):
        enable.plan(manifest, released, current, evidence)


def test_strict_mode_cannot_import_direct_waiver() -> None:
    manifest, released, current, evidence = fixture()
    _, _, _, direct = direct_first_live_fixture()
    evidence["direct_first_live_authorization"] = direct[
        "direct_first_live_authorization"
    ]
    with pytest.raises(release_operator.ReleaseBlocked, match="strict_no_waiver"):
        enable.plan(manifest, released, current, evidence)
    del evidence["images"]
    with pytest.raises(release_operator.ReleaseBlocked, match="three_news_images"):
        enable.plan(manifest, released, current, evidence)


@pytest.mark.parametrize(
    ("section", "field", "value", "code"),
    [
        ("candidate", "package_id", "other-news", "first_live_same_package_identity"),
        ("candidate", "base_job_id", "other-base", "first_live_same_package_identity"),
        (
            "candidate",
            "business_date",
            "2026-09-28",
            "first_live_same_package_identity",
        ),
        ("candidate", "source_url_sha256", "b" * 64, "same_news_final_jpeg"),
        ("candidate", "footer_date", "2026-09-25", "same_news_final_jpeg"),
        ("candidate", "recipient_fingerprint", "b" * 64, "same_news_final_jpeg"),
        ("candidate", "jpeg_bytes", 2 * 1024 * 1024 + 1, "same_news_final_jpeg"),
        ("candidate", "jpeg_bytes", 0, "same_news_final_jpeg"),
        ("candidate", "media_type", "image/png", "same_news_final_jpeg"),
        ("candidate", "jpeg_height", 1900, "same_news_final_jpeg"),
        ("candidate", "final_jpeg_checked", False, "same_news_final_jpeg"),
        ("candidate", "image_intent_count", 2, "same_news_final_jpeg"),
        ("candidate", "image_result_known", False, "same_news_final_jpeg"),
        ("candidate", "delivery_unknown", True, "same_news_final_jpeg"),
        ("candidate", "warning_visible", False, "same_news_final_jpeg"),
        (
            "expected",
            "base_original_image_confirmed",
            False,
            "first_live_same_package_identity",
        ),
        ("expected", "within_slot_window", False, "first_live_same_package_identity"),
        ("expected", "max_daily_image_intents", 10, "first_live_same_package_identity"),
    ],
)
def test_direct_first_live_candidate_must_still_be_own_sendable_jpeg(
    section: str, field: str, value: Any, code: str
) -> None:
    manifest, released, current, evidence = direct_first_live_fixture(
        with_candidate=True
    )
    target = evidence[
        "first_live_candidate" if section == "candidate" else "first_live_expected"
    ]
    target[field] = value
    with pytest.raises(release_operator.ReleaseBlocked, match=code):
        enable.plan(manifest, released, current, evidence)


def test_direct_first_live_candidate_envelope_and_group_claim_cannot_be_partial() -> (
    None
):
    manifest, released, current, evidence = direct_first_live_fixture(
        with_candidate=True
    )
    assert (
        enable.plan(manifest, released, current, evidence)[
            "production_enable_available"
        ]
        is False
    )
    del evidence["first_live_expected"]
    with pytest.raises(
        release_operator.ReleaseBlocked, match="first_live_candidate_pair"
    ):
        enable.plan(manifest, released, current, evidence)
    _, _, _, evidence = direct_first_live_fixture()
    evidence["group_test"] = {}
    with pytest.raises(
        release_operator.ReleaseBlocked, match="direct_first_live_no_legacy_receipts"
    ):
        enable.plan(manifest, released, current, evidence)


def test_direct_first_live_simulation_records_waiver_and_remains_non_promotable(
    tmp_path: Path,
) -> None:
    manifest, released, current, evidence = direct_first_live_fixture()
    attempt = tmp_path / "direct-first-live"
    result = enable.simulate(
        FakeHost(current),
        manifest,
        released,
        current,
        evidence,
        attempt,
        (tmp_path / "deploy.lock", tmp_path / "backup.lock"),
    )
    assert result["production_enable_available"] is False
    intent = json.loads((attempt / "enablement-intent.json").read_text())
    receipt = json.loads((attempt / "simulation-enablement-receipt.json").read_text())
    assert intent["policy"] == enable.DIRECT_FIRST_LIVE_POLICY
    assert (
        receipt["authorization_sha256"]
        == evidence["direct_first_live_authorization"]["authorization_sha256"]
    )
    assert receipt["simulation_only"] is True
    assert receipt["waived_pre_enable_gates"] == [
        "three_approved_jpegs",
        "fixed_group_triple_receipt",
    ]


def test_direct_first_live_provider_failure_must_leave_base_delivered() -> None:
    manifest, released, current, evidence = direct_first_live_fixture()
    evidence["failure_isolation"]["original_image_confirmed"] = False
    with pytest.raises(
        release_operator.ReleaseBlocked, match="base_delivery_failure_isolation"
    ):
        enable.plan(manifest, released, current, evidence)


def test_simulated_enablement_has_separate_receipt_and_one_attempt(
    tmp_path: Path,
) -> None:
    manifest, released, current, evidence = fixture()
    host = FakeHost(current)
    attempt = tmp_path / "enablement"
    result = enable.simulate(
        host,
        manifest,
        released,
        current,
        evidence,
        attempt,
        (tmp_path / "deploy.lock", tmp_path / "backup.lock"),
    )
    assert result["production_enable_available"] is False
    assert host.calls == [
        "capture",
        "install_flags",
        "restart_dispatcher",
        "start_producer",
        "capture",
    ]
    receipt = json.loads((attempt / "simulation-enablement-receipt.json").read_text())
    assert receipt["max_ordinal"] == 3
    assert receipt["slots"] == ["morning", "noon", "evening"]
    assert receipt["simulation_only"] is True
    assert receipt["receipt_sha256"] == enable._receipt_hash(receipt)
    with pytest.raises(
        release_operator.ReleaseBlocked,
        match="enablement_attempt_exists_reconcile_only",
    ):
        enable.simulate(
            host,
            manifest,
            released,
            current,
            evidence,
            attempt,
            (tmp_path / "deploy.lock", tmp_path / "backup.lock"),
        )


@pytest.mark.parametrize(
    "failure",
    [
        "flags",
        "dispatcher",
        "producer",
        "wrong_recipient",
        "base_regressed",
        "wrong_dispatcher_runtime",
        "wrong_producer_runtime",
    ],
)
def test_enablement_failure_disables_supplement_but_preserves_base(
    tmp_path: Path, failure: str
) -> None:
    manifest, released, current, evidence = fixture()
    host = FakeHost(current, failure=failure)
    attempt = tmp_path / "enablement"
    with pytest.raises((RuntimeError, release_operator.ReleaseBlocked)):
        enable.simulate(
            host,
            manifest,
            released,
            current,
            evidence,
            attempt,
            (tmp_path / "deploy.lock", tmp_path / "backup.lock"),
        )
    assert host.calls[-1] == "disable_supplement_preserve_base"
    assert host.current["base_delivery_healthy"] is True
    assert host.current["producer_running"] is False
    assert all(value is False for value in host.current["flags"].values())
    assert (attempt / "enablement-recovery-required.json").exists()
    assert not (attempt / "simulation-enablement-receipt.json").exists()


def test_cli_enable_hard_refuses_without_reading_input_files() -> None:
    path = Path(enable.__file__)
    result = subprocess.run(
        [
            sys.executable,
            "-I",
            str(path),
            "enable",
            "--manifest",
            "/missing/secret.json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert json.loads(result.stdout) == {
        "phase": "blocked",
        "code": "execute_required",
    }


def test_cli_refuses_nonisolated_python_before_sibling_import() -> None:
    path = Path(enable.__file__)
    result = subprocess.run(
        [sys.executable, str(path), "enable", "--execute"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert json.loads(result.stdout) == {
        "phase": "blocked",
        "code": "isolated_python_required",
    }


def test_isolated_cli_rejects_unsealed_bundle_before_sibling_import() -> None:
    path = Path(enable.__file__)
    result = subprocess.run(
        [sys.executable, "-I", str(path), "enable", "--execute"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
    assert json.loads(result.stdout) == {
        "phase": "blocked",
        "code": "bundle_auth_failed",
    }


def _release_baseline_fixture(recipient_fingerprint: str) -> dict[str, Any]:
    return {
        "release_commit": release_operator.BASE_REVISION,
        "release_commit_secondary": release_operator.BASE_REVISION,
        "image": release_operator.BASE_IMAGE,
        "release_env_image": release_operator.BASE_REF,
        "schema": release_operator.BASE_SCHEMA,
        "optional_producer_absent": True,
        "standard_manifest_absent": True,
        "backup_timer_active": True,
        "idle": True,
        "unknown_work_count": 0,
        "pending_work_count": 0,
        "business_identity_sha256": "a" * 64,
        "brand_identity_sha256": "a" * 64,
        "recipient_fingerprint": recipient_fingerprint,
        "flags": dict.fromkeys(release_operator.OFF_FLAGS, False),
        "services": {
            name: {
                "image": release_operator.BASE_IMAGE,
                "image_ref": release_operator.BASE_REF,
                "running": True,
                "healthy": True,
                "restarts": 0,
                "command_sha256": HEX,
                "mounts_sha256": HEX,
                "env_sha256": HEX,
            }
            for name in release_operator.SERVICES
        },
        "protected_files": {
            name: {"sha256": HEX, "mode": 0o600, "uid": 0, "gid": 0}
            for name in release_operator.PROTECTED_FILES
        },
        "volumes": dict.fromkeys(release_operator.VOLUMES, HEX),
    }


def _production_fixture(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], Path, str, Path]:
    manifest, released, current, evidence = direct_first_live_fixture()
    authorization_record = tmp_path / "user-authorization.md"
    authorization_record.write_bytes(b"test-only direct-first-live user decision\n")
    os.chmod(authorization_record, 0o600)
    monkeypatch.setattr(
        enable,
        "USER_AUTHORIZATION_RECORD_SHA256",
        release_operator.sha(authorization_record.read_bytes()),
    )
    fingerprint = release_operator.APPROVED_RECIPIENT_FINGERPRINT
    current["recipient_fingerprint"] = fingerprint
    released["recipient_fingerprint"] = fingerprint
    released["receipt_sha256"] = enable._receipt_hash(released)
    auth = evidence["direct_first_live_authorization"]
    auth["recipient_fingerprint"] = fingerprint
    auth["release_receipt_sha256"] = released["receipt_sha256"]
    auth["user_authorization_record_sha256"] = enable.USER_AUTHORIZATION_RECORD_SHA256
    auth["authorization_sha256"] = release_operator.sha(
        release_operator.canonical(
            {key: value for key, value in auth.items() if key != "authorization_sha256"}
        )
    )
    release_dir = tmp_path / released["attempt_id"]
    release_dir.mkdir(mode=0o700)
    manifest_sha = "6" * 64
    pre_stop = _release_baseline_fixture(fingerprint)
    snapshot = {
        "schema": release_operator.BASE_SCHEMA,
        "business_identity_sha256": "b" * 64,
        "brand_identity_sha256": pre_stop["brand_identity_sha256"],
        "recipient_fingerprint": fingerprint,
        "protected_files": pre_stop["protected_files"],
        "volumes": pre_stop["volumes"],
        "flags": pre_stop["flags"],
        "stopped_services": list(release_operator.SERVICES),
        "optional_producer_absent": True,
    }
    quiescent = release_operator.quiescent_receipt(pre_stop, snapshot)
    released["pre_stop_baseline_sha256"] = quiescent["pre_stop_baseline_sha256"]
    released["baseline_sha256"] = release_operator.sha(
        release_operator.canonical(quiescent["baseline"])
    )
    released["quiescent_receipt_sha256"] = quiescent["receipt_sha256"]
    backup = {
        "baseline_sha256": released["baseline_sha256"],
        "pg_dump_sha256": "9" * 64,
        "pg_dump_bytes": 1024,
        "pg_restore_toc_sha256": HEX,
        "pg_restore_toc_read": True,
        "protected_files_readback": True,
        "protected_files": pre_stop["protected_files"],
        "protected_metadata_sha256": HEX,
        "brand_materials_readback": True,
        "brand_identity_sha256": pre_stop["brand_identity_sha256"],
        "brand_archive_sha256": HEX,
        "source_config_readback": True,
        "source_config_archives": dict.fromkeys(
            ("backend", "deploy", "scripts", "infra"), HEX
        ),
        "minio": {
            "kind": "unversioned-current-object-logical-v1",
            "bucket": "edu-ai-materials",
            "inventory_sha256": pre_stop["volumes"][release_operator.MINIO_VOLUME],
            "manifest_sha256": HEX,
            "readback_tree_sha256": HEX,
            "object_count": 1,
            "bytes": 8,
            "source_bytes_readback": True,
            "local_bytes_readback": True,
            "metadata_readback": True,
        },
        "volumes": dict.fromkeys(release_operator.ARCHIVE_VOLUMES, HEX),
        "volume_readbacks": dict.fromkeys(release_operator.ARCHIVE_VOLUMES, True),
    }
    clone: dict[str, Any] = {
        "chain": release_operator.MIGRATION_CHAIN,
        "source_dump_sha256": backup["pg_dump_sha256"],
        "source_schema": release_operator.BASE_SCHEMA,
        "target_schema": release_operator.TARGET_SCHEMA,
        "isolated_restore_readback": True,
        "isolated_target": True,
        "existing_table_counts_equal": True,
        "source_business_sha256": "b" * 64,
        "retained_business_sha256": "b" * 64,
    }
    clone["receipt_sha256"] = enable._receipt_hash(clone)
    released["backup_receipt_sha256"] = release_operator.sha(
        release_operator.canonical(backup)
    )
    released["clone_receipt_sha256"] = clone["receipt_sha256"]
    released["receipt_sha256"] = enable._receipt_hash(released)
    auth["release_receipt_sha256"] = released["receipt_sha256"]
    auth["authorization_sha256"] = release_operator.sha(
        release_operator.canonical(
            {key: value for key, value in auth.items() if key != "authorization_sha256"}
        )
    )
    intent = {
        "version": "r16-default-off-intent-v1",
        "candidate": manifest["image"],
        "revision": manifest["revision"],
        "manifest_sha256": manifest_sha,
        "baseline_sha256": released["pre_stop_baseline_sha256"],
        "old_app_restart_forbidden_after_migration_intent": True,
        "simulation_only": False,
    }
    migration_intent = {
        "chain": release_operator.MIGRATION_CHAIN,
        "forward_only": True,
        "clone_receipt_sha256": clone["receipt_sha256"],
        "backup_receipt_sha256": released["backup_receipt_sha256"],
        "if_unobserved": "forward_reconcile_only",
        "old_app_restart_forbidden": True,
        "automatic_restore_or_downgrade_forbidden": True,
    }
    for name, data in (
        ("intent.json", intent),
        ("quiescent-baseline.json", quiescent),
        ("release-receipt.json", released),
        ("backup-receipt.json", backup),
        ("clone-receipt.json", clone),
        ("migration-intent.json", migration_intent),
    ):
        path = release_dir / name
        path.write_bytes(release_operator.canonical(data))
        os.chmod(path, 0o600)
    return manifest, current, evidence, release_dir, manifest_sha, authorization_record


def test_production_enable_uses_real_release_tree_and_separate_receipt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, current, evidence, release_dir, manifest_sha, authorization_record = (
        _production_fixture(tmp_path, monkeypatch)
    )
    monkeypatch.setattr(
        enable, "valid_production_manifest", release_operator.valid_manifest
    )
    host = FakeHost(current)
    receipt = enable.enable_production(
        host,
        manifest,
        manifest_sha,
        release_dir,
        evidence,
        authorization_record,
        tmp_path / "r16-enable-one-attempt",
        (tmp_path / "deploy.lock", tmp_path / "backup.lock"),
    )
    assert receipt["status"] == "enabled_all_news"
    assert (
        receipt["recipient_fingerprint"]
        == release_operator.APPROVED_RECIPIENT_FINGERPRINT
    )
    assert receipt["receipt_sha256"] == enable._receipt_hash(receipt)
    assert host.calls == [
        "capture",
        "arm_production_mutation",
        "install_flags",
        "restart_dispatcher",
        "start_producer",
        "capture",
    ]
    assert (tmp_path / "r16-enable-one-attempt" / "enablement-receipt.json").exists()
    with pytest.raises(
        release_operator.ReleaseBlocked, match="prior_enable_attempt_reconcile_only"
    ):
        enable.enable_production(
            host,
            manifest,
            manifest_sha,
            release_dir,
            evidence,
            authorization_record,
            tmp_path / "r16-enable-second-attempt",
            (tmp_path / "deploy.lock", tmp_path / "backup.lock"),
        )


@pytest.mark.parametrize(
    ("corruption", "code"),
    [
        ("weak_release", "default_off_release_receipt"),
        ("wrong_manifest", "release_attempt_crosscheck"),
        ("wrong_user_auth", "user_authorization_record_mismatch"),
        ("wrong_authorization_file", "user_authorization_file_mismatch"),
        ("wrong_migration_intent", "release_migration_intent_crosscheck"),
        ("wrong_quiescent", "quiescent_release_chain"),
        ("wrong_backup_baseline", "quiescent_release_chain"),
        ("forged_backup_brand", "backup_receipt"),
        ("wrong_clone_business", "quiescent_release_chain"),
        ("public_release_dir", "release_attempt_directory"),
        ("recovery_marker", "release_recovery_marker"),
        ("broken_recovery_marker", "release_recovery_marker"),
    ],
)
def test_production_enable_rejects_untrusted_provenance_before_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    corruption: str,
    code: str,
) -> None:
    manifest, current, evidence, release_dir, manifest_sha, authorization_record = (
        _production_fixture(tmp_path, monkeypatch)
    )
    monkeypatch.setattr(
        enable, "valid_production_manifest", release_operator.valid_manifest
    )
    if corruption == "weak_release":
        path = release_dir / "release-receipt.json"
        value = json.loads(path.read_bytes())
        del value["archive_sha256"]
        value["receipt_sha256"] = enable._receipt_hash(value)
        path.write_bytes(release_operator.canonical(value))
    elif corruption == "wrong_manifest":
        manifest_sha = "b" * 64
    elif corruption == "wrong_user_auth":
        evidence["direct_first_live_authorization"][
            "user_authorization_record_sha256"
        ] = "b" * 64
    elif corruption == "wrong_authorization_file":
        authorization_record.write_bytes(b"changed user decision\n")
    elif corruption == "wrong_migration_intent":
        path = release_dir / "migration-intent.json"
        value = json.loads(path.read_bytes())
        value["forward_only"] = False
        path.write_bytes(release_operator.canonical(value))
    elif corruption == "wrong_quiescent":
        path = release_dir / "quiescent-baseline.json"
        value = json.loads(path.read_bytes())
        value["snapshot"]["business_identity_sha256"] = "c" * 64
        path.write_bytes(release_operator.canonical(value))
    elif corruption == "wrong_backup_baseline":
        path = release_dir / "backup-receipt.json"
        value = json.loads(path.read_bytes())
        value["baseline_sha256"] = "c" * 64
        path.write_bytes(release_operator.canonical(value))
    elif corruption == "forged_backup_brand":
        path = release_dir / "backup-receipt.json"
        value = json.loads(path.read_bytes())
        value["brand_identity_sha256"] = "c" * 64
        path.write_bytes(release_operator.canonical(value))
        release_path = release_dir / "release-receipt.json"
        release = json.loads(release_path.read_bytes())
        release["backup_receipt_sha256"] = release_operator.sha(
            release_operator.canonical(value)
        )
        release["receipt_sha256"] = enable._receipt_hash(release)
        release_path.write_bytes(release_operator.canonical(release))
        auth = evidence["direct_first_live_authorization"]
        auth["release_receipt_sha256"] = release["receipt_sha256"]
        auth["authorization_sha256"] = release_operator.sha(
            release_operator.canonical(
                {
                    key: value
                    for key, value in auth.items()
                    if key != "authorization_sha256"
                }
            )
        )
    elif corruption == "wrong_clone_business":
        path = release_dir / "clone-receipt.json"
        value = json.loads(path.read_bytes())
        value["source_business_sha256"] = "c" * 64
        path.write_bytes(release_operator.canonical(value))
    elif corruption == "public_release_dir":
        os.chmod(release_dir, 0o755)
    elif corruption == "broken_recovery_marker":
        (release_dir / "forward-recovery-required.json").symlink_to("missing-target")
    else:
        (release_dir / "forward-recovery-required.json").write_text("{}")
    host = FakeHost(current)
    with pytest.raises(release_operator.ReleaseBlocked, match=code):
        enable.enable_production(
            host,
            manifest,
            manifest_sha,
            release_dir,
            evidence,
            authorization_record,
            tmp_path / "r16-enable-attempt",
            (tmp_path / "deploy.lock", tmp_path / "backup.lock"),
        )
    assert host.calls == []
    assert not (tmp_path / "r16-enable-attempt").exists()


def test_production_enable_failure_disables_only_supplement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest, current, evidence, release_dir, manifest_sha, authorization_record = (
        _production_fixture(tmp_path, monkeypatch)
    )
    monkeypatch.setattr(
        enable, "valid_production_manifest", release_operator.valid_manifest
    )
    host = FakeHost(current, failure="producer")
    attempt = tmp_path / "r16-enable-producer-failure"
    with pytest.raises(RuntimeError, match="producer_failed"):
        enable.enable_production(
            host,
            manifest,
            manifest_sha,
            release_dir,
            evidence,
            authorization_record,
            attempt,
            (tmp_path / "deploy.lock", tmp_path / "backup.lock"),
        )
    assert host.calls[-1] == "disable_supplement_preserve_base"
    assert host.current["base_delivery_healthy"] is True
    assert host.current["producer_running"] is False
    assert (attempt / "enablement-recovery-required.json").exists()
    assert not (attempt / "enablement-receipt.json").exists()
