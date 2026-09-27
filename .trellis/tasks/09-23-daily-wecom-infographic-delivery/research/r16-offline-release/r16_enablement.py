#!/usr/bin/env -S python3 -I
"""Separate, one-attempt R16 infographic enablement after a default-off release.

The executable path requires the real release receipt, a pinned source manifest,
the ordinary-group fingerprint and the user's direct-first-live decision. It
never sends a message itself; the runtime still validates each final JPEG.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any, Protocol, cast


def _authenticate_entry_before_sibling_import() -> None:
    """Validate the sealed bundle before importing any sibling as root."""
    if not sys.flags.isolated:
        print(json.dumps({"phase": "blocked", "code": "isolated_python_required"}))
        raise SystemExit(2)
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("action", nargs="?")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--manifest-sha256")
    parser.add_argument("--operator-sha256")
    parser.add_argument("--release-launcher-sha256")
    args, _ = parser.parse_known_args()
    if args.action == "enable" and not args.execute:
        print(json.dumps({"phase": "blocked", "code": "execute_required"}))
        raise SystemExit(2)
    try:
        if not (
            args.bundle
            and args.manifest
            and args.manifest_sha256
            and args.operator_sha256
            and args.release_launcher_sha256
            and Path(__file__).absolute() == args.bundle / "r16_enablement.py"
            and args.manifest == args.bundle / "candidate.json"
            and re.fullmatch(r"[0-9a-f]{64}", args.operator_sha256)
            and hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
            == args.operator_sha256
        ):
            raise ValueError("unsealed enable entry")
        launcher = args.bundle / "r16_release_cli.py"
        # Load the stdlib-only launcher by its exact path without placing the
        # bundle on sys.path. Its full source hash is checked by the launcher
        # before it authenticates the remaining source siblings and manifest.
        if (
            not re.fullmatch(r"[0-9a-f]{64}", args.release_launcher_sha256)
            or hashlib.sha256(launcher.read_bytes()).hexdigest()
            != args.release_launcher_sha256
        ):
            raise ValueError("unsealed release launcher")
        spec = importlib.util.spec_from_file_location("r16_release_cli", launcher)
        if spec is None or spec.loader is None:
            raise ValueError("missing release launcher")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.authenticate_bundle(
            launcher,
            args.bundle,
            args.manifest,
            args.manifest_sha256,
            args.release_launcher_sha256,
        )
    except Exception:  # noqa: BLE001 - never expose bundle paths or secrets
        print(json.dumps({"phase": "blocked", "code": "bundle_auth_failed"}))
        raise SystemExit(2) from None
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(args.bundle))


if __name__ == "__main__":
    _authenticate_entry_before_sibling_import()

from r16_forward_operator import (
    APPROVED_RECIPIENT_FINGERPRINT,
    BASE_SCHEMA,
    MIGRATION_CHAIN,
    OFF_FLAGS,
    SERVICES,
    TARGET_SCHEMA,
    ReleaseBlocked,
    canonical,
    fsync_directory,
    is_sha,
    require,
    sha,
    two_local_locks,
    valid_enablement_evidence,
    valid_manifest,
    valid_production_manifest,
    write_new,
)

POLICY = "r16-direct-all-news-after-release-v1"
DIRECT_FIRST_LIVE_POLICY = "r16-direct-first-live-after-release-v1"
DIRECT_FIRST_LIVE_AUTH_VERSION = "r16-direct-first-live-authorization-v1"
DIRECT_FIRST_LIVE_DECISION = "first_successful_image_to_ordinary_group"
STRICT_MODE = "legacy_strict"
DIRECT_FIRST_LIVE_MODE = "direct_first_live"
DIRECT_AUTH_FIELDS = frozenset(
    {
        "version",
        "decision",
        "scope",
        "user_authorization_record_sha256",
        "operator_id",
        "operator_approved_at_utc",
        "operator_acknowledged",
        "recipient_fingerprint_method",
        "recipient_route",
        "ordinary_group_acknowledged",
        "recipient_fingerprint",
        "release_receipt_sha256",
        "waive_three_previews",
        "waive_fixed_group_test",
        "first_success_to_ordinary_group",
        "max_daily_image_intents",
        "provider_failure_preserves_base",
        "unknown_result_auto_replay",
        "authorization_sha256",
    }
)
DIRECT_EVIDENCE_FIELDS = frozenset(
    {
        "enablement_mode",
        "rollout_policy",
        "direct_first_live_authorization",
        "failure_isolation",
        "first_live_candidate",
        "first_live_expected",
    }
)
MAX_DAILY_IMAGE_INTENTS = 9
USER_AUTHORIZATION_RECORD_SHA256 = (
    "ea52cdb7d3c26737e83a13c64893a35b367354ef051e9f3412860790e6def2b2"
)
NOTICE_VERSION = "wecom-infographic-advisory-notice-v1"
MAX_JPEG_BYTES = 2 * 1024 * 1024
JPEG_GEOMETRY = (1152, 2048)
SLOTS = ("morning", "noon", "evening")
ACTIVE_FLAGS = {
    "WECOM_INFOGRAPHIC_PRODUCER_ENABLED": True,
    "WECOM_INFOGRAPHIC_DELIVERY_ENABLED": True,
    "WECOM_INFOGRAPHIC_TEST_ENABLED": False,
    "WECOM_INFOGRAPHIC_MORNING_ENABLED": True,
    "WECOM_INFOGRAPHIC_NOON_ENABLED": True,
    "WECOM_INFOGRAPHIC_EVENING_ENABLED": True,
}
DISPATCHER_FLAGS = (
    "WECOM_INFOGRAPHIC_DELIVERY_ENABLED",
    "WECOM_INFOGRAPHIC_TEST_ENABLED",
    "WECOM_INFOGRAPHIC_MORNING_ENABLED",
    "WECOM_INFOGRAPHIC_NOON_ENABLED",
    "WECOM_INFOGRAPHIC_EVENING_ENABLED",
)
PRODUCER_FLAGS = (
    "WECOM_INFOGRAPHIC_PRODUCER_ENABLED",
    "WECOM_INFOGRAPHIC_MORNING_ENABLED",
    "WECOM_INFOGRAPHIC_NOON_ENABLED",
    "WECOM_INFOGRAPHIC_EVENING_ENABLED",
)
MAX_ORDINAL = 3
REVIEW_MODE = "advisory"
DISPATCHER_START = (
    "docker",
    "compose",
    "up",
    "-d",
    "--no-build",
    "--no-deps",
    "--pull",
    "never",
    "wecom-dispatcher",
)
PRODUCER_START = (
    "docker",
    "compose",
    "--profile",
    "infographic",
    "up",
    "-d",
    "--no-build",
    "--no-deps",
    "--pull",
    "never",
    "wecom-infographic-producer",
)
FORBIDDEN_START_TOKENS = frozenset(
    {"backend-migrate", "seed_sources", "minio-init", "up --build"}
)


def _receipt_hash(receipt: dict[str, Any]) -> str:
    return sha(
        canonical(
            {key: value for key, value in receipt.items() if key != "receipt_sha256"}
        )
    )


def valid_release_receipt(manifest: dict[str, Any], release: dict[str, Any]) -> None:
    """Only the real operator's default-off production receipt can advance."""
    require(
        set(release)
        == {
            "version",
            "status",
            "attempt_id",
            "manifest_sha256",
            "candidate",
            "revision",
            "archive_sha256",
            "operator_sha256",
            "real_host_sha256",
            "release_cli_sha256",
            "schema",
            "migration_chain",
            "services",
            "default_off",
            "recipient_fingerprint",
            "baseline_sha256",
            "backup_receipt_sha256",
            "clone_receipt_sha256",
            "simulation_only",
            "receipt_sha256",
        }
        and release.get("version") == "r16-default-off-production-receipt-v1"
        and release.get("status") == "deployed_default_off"
        and isinstance(release.get("attempt_id"), str)
        and re.fullmatch(
            r"r16-forward-[A-Za-z0-9][A-Za-z0-9.-]{4,63}", release["attempt_id"]
        )
        is not None
        and is_sha(release.get("manifest_sha256"))
        and release.get("candidate") == manifest["image"]
        and release.get("revision") == manifest["revision"]
        and release.get("archive_sha256") == manifest.get("archive_sha256")
        and is_sha(release.get("archive_sha256"))
        and release.get("operator_sha256") == manifest.get("operator_sha256")
        and is_sha(release.get("operator_sha256"))
        and release.get("real_host_sha256") == manifest.get("real_host_sha256")
        and is_sha(release.get("real_host_sha256"))
        and release.get("release_cli_sha256") == manifest.get("release_cli_sha256")
        and is_sha(release.get("release_cli_sha256"))
        and release.get("schema") == TARGET_SCHEMA
        and release.get("migration_chain") == MIGRATION_CHAIN
        and release.get("services") == len(SERVICES)
        and release.get("default_off") is True
        and release.get("simulation_only") is False
        and is_sha(release.get("recipient_fingerprint"))
        and is_sha(release.get("baseline_sha256"))
        and is_sha(release.get("backup_receipt_sha256"))
        and is_sha(release.get("clone_receipt_sha256"))
        and release.get("receipt_sha256") == _receipt_hash(release),
        "default_off_release_receipt",
    )


def valid_current(
    manifest: dict[str, Any],
    release: dict[str, Any],
    current: dict[str, Any],
    *,
    enabled: bool,
) -> None:
    flags = current.get("flags")
    expected_flags = ACTIVE_FLAGS if enabled else dict.fromkeys(OFF_FLAGS, False)
    require(
        current.get("image") == manifest["image"]
        and current.get("revision") == manifest["revision"]
        and current.get("schema") == TARGET_SCHEMA
        and current.get("recipient_fingerprint") == release["recipient_fingerprint"]
        and current.get("base_delivery_healthy") is True
        and type(current.get("unknown_work_count")) is int
        and (
            current.get("unknown_work_count", -1) >= 0
            if enabled
            else current.get("unknown_work_count") == 0
        )
        and type(current.get("pending_work_count")) is int
        and (
            current.get("pending_work_count", -1) >= 0
            if enabled
            else current.get("pending_work_count") == 0
        )
        and isinstance(flags, dict)
        and flags == expected_flags
        and current.get("producer_running") is enabled
        and current.get("max_ordinal") == (MAX_ORDINAL if enabled else 1)
        and current.get("review_mode") == (REVIEW_MODE if enabled else "strict"),
        "enablement_current_identity",
    )
    services = current.get("services")
    require(
        isinstance(services, dict)
        and set(services) == set(SERVICES)
        and all(
            isinstance(item, dict)
            and item.get("image") == manifest["image"]
            and item.get("running") is True
            and item.get("healthy") is True
            for item in services.values()
        ),
        "enablement_service_set",
    )
    assert isinstance(services, dict)
    dispatcher = services["wecom-dispatcher"]
    assert isinstance(dispatcher, dict)
    expected_dispatcher: dict[str, object] = {
        name: expected_flags[name] for name in DISPATCHER_FLAGS
    }
    expected_dispatcher.update(
        {
            "WECOM_INFOGRAPHIC_REVIEW_MODE": REVIEW_MODE if enabled else "strict",
            "WECOM_INFOGRAPHIC_MAX_ORDINAL": MAX_ORDINAL if enabled else 1,
        }
    )
    require(
        dispatcher.get("runtime_infographic") == expected_dispatcher,
        "enablement_dispatcher_runtime",
    )
    if enabled:
        expected_producer: dict[str, object] = {
            name: ACTIVE_FLAGS[name] for name in PRODUCER_FLAGS
        }
        expected_producer.update(
            {
                "WECOM_INFOGRAPHIC_REVIEW_MODE": REVIEW_MODE,
                "WECOM_INFOGRAPHIC_MAX_ORDINAL": MAX_ORDINAL,
            }
        )
        require(
            current.get("producer_image") == manifest["image"]
            and current.get("producer_healthy") is True
            and current.get("producer_runtime_infographic") == expected_producer,
            "enablement_producer_identity",
        )


def _valid_final_jpeg(baseline: dict[str, Any], item: dict[str, Any]) -> None:
    """Validate a proposed final JPEG; this never grants a send by itself."""
    require(
        isinstance(item.get("package_id"), str)
        and bool(item["package_id"])
        and is_sha(item.get("jpeg_sha256"))
        and item.get("exact_source") is True
        and item.get("send_ready") is True
        and item.get("business_date") is not None
        and isinstance(item.get("business_date"), str)
        and re.fullmatch(r"\d{4}-\d{2}-\d{2}", item["business_date"]) is not None
        and item.get("slot") in SLOTS
        and type(item.get("ordinal")) is int
        and 1 <= item["ordinal"] <= MAX_ORDINAL
        and isinstance(item.get("base_job_id"), str)
        and bool(item["base_job_id"])
        and item.get("recipient_fingerprint") == baseline["recipient_fingerprint"]
        and type(item.get("jpeg_bytes")) is int
        and 0 < item["jpeg_bytes"] <= MAX_JPEG_BYTES
        and item.get("media_type") == "image/jpeg"
        and item.get("final_jpeg_checked") is True
        and (item.get("jpeg_width"), item.get("jpeg_height")) == JPEG_GEOMETRY
        and is_sha(item.get("source_url_sha256"))
        and item.get("footer_url_sha256") == item["source_url_sha256"]
        and isinstance(item.get("source_date"), str)
        and re.fullmatch(r"\d{4}-\d{2}-\d{2}", item["source_date"]) is not None
        and item.get("footer_date") == item["source_date"]
        and item.get("warning_notice_version") == NOTICE_VERSION
        and item.get("warning_visible") is True
        and type(item.get("image_intent_count")) is int
        and item["image_intent_count"] == 1
        and item.get("image_result_known") is True
        and item.get("delivery_unknown") is False,
        "same_news_final_jpeg",
    )


def valid_first_live_candidate(
    baseline: dict[str, Any], expected: dict[str, Any], item: dict[str, Any]
) -> None:
    """Bind an optional first-live image to its own expected formal package."""
    _valid_final_jpeg(baseline, item)
    require(
        all(
            expected.get(field) == item[field]
            for field in (
                "package_id",
                "base_job_id",
                "business_date",
                "slot",
                "ordinal",
                "recipient_fingerprint",
                "source_url_sha256",
                "source_date",
            )
        )
        and expected.get("jpeg_sha256") == item["jpeg_sha256"]
        and expected.get("max_daily_image_intents") == MAX_DAILY_IMAGE_INTENTS
        and expected.get("base_text_confirmed") is True
        and expected.get("base_original_image_confirmed") is True
        and expected.get("within_slot_window") is True,
        "first_live_same_package_identity",
    )


def _valid_failure_isolation(evidence: dict[str, Any]) -> None:
    isolation = evidence.get("failure_isolation")
    require(
        isinstance(isolation, dict)
        and isolation.get("base_status") == "delivered"
        and isolation.get("text_confirmed") is True
        and isolation.get("original_image_confirmed") is True
        and isolation.get("supplement_status") == "failed"
        and isolation.get("unknown_result_auto_replayed") is False
        and is_sha(isolation.get("test_receipt_sha256")),
        "base_delivery_failure_isolation",
    )


def _valid_direct_authorization(
    release: dict[str, Any], baseline: dict[str, Any], evidence: dict[str, Any]
) -> None:
    auth = evidence.get("direct_first_live_authorization")
    require(
        isinstance(auth, dict)
        and set(auth) == DIRECT_AUTH_FIELDS
        and auth.get("version") == DIRECT_FIRST_LIVE_AUTH_VERSION
        and auth.get("decision") == DIRECT_FIRST_LIVE_DECISION
        and auth.get("scope") == "every_delivered_news_all_three_slots"
        and is_sha(auth.get("user_authorization_record_sha256"))
        and isinstance(auth.get("operator_id"), str)
        and re.fullmatch(r"[A-Za-z0-9._-]{3,64}", auth["operator_id"]) is not None
        and isinstance(auth.get("operator_approved_at_utc"), str)
        and re.fullmatch(
            r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z",
            auth["operator_approved_at_utc"],
        )
        is not None
        and auth.get("operator_acknowledged") is True
        and auth.get("recipient_fingerprint_method") == "sha256(group_webhook\\0key)"
        and auth.get("recipient_route") == "existing_ordinary_group_webhook"
        and auth.get("ordinary_group_acknowledged") is True
        and auth.get("recipient_fingerprint") == baseline["recipient_fingerprint"]
        and auth.get("release_receipt_sha256") == release["receipt_sha256"]
        and auth.get("waive_three_previews") is True
        and auth.get("waive_fixed_group_test") is True
        and auth.get("first_success_to_ordinary_group") is True
        and auth.get("max_daily_image_intents") == MAX_DAILY_IMAGE_INTENTS
        and auth.get("provider_failure_preserves_base") is True
        and auth.get("unknown_result_auto_replay") is False
        and auth.get("authorization_sha256")
        == sha(
            canonical(
                {
                    key: value
                    for key, value in auth.items()
                    if key != "authorization_sha256"
                }
            )
        ),
        "direct_first_live_authorization",
    )


def valid_same_news_evidence(
    baseline: dict[str, Any],
    evidence: dict[str, Any],
    release: dict[str, Any] | None = None,
) -> None:
    """Strict legacy gates remain; direct-first-live needs explicit bound waiver."""
    mode = evidence.get("enablement_mode", STRICT_MODE)
    require(mode in (STRICT_MODE, DIRECT_FIRST_LIVE_MODE), "enablement_mode")
    if mode == DIRECT_FIRST_LIVE_MODE:
        require(
            evidence.get("images", []) == [] and "group_test" not in evidence,
            "direct_first_live_no_legacy_receipts",
        )
        require(
            set(evidence) <= DIRECT_EVIDENCE_FIELDS, "direct_first_live_evidence_fields"
        )
        require(
            evidence.get("rollout_policy") == DIRECT_FIRST_LIVE_POLICY,
            "enablement_policy",
        )
        require(release is not None, "direct_first_live_authorization")
        assert release is not None
        _valid_direct_authorization(release, baseline, evidence)
        candidate = evidence.get("first_live_candidate")
        expected = evidence.get("first_live_expected")
        require(
            (candidate is None and expected is None)
            or (isinstance(candidate, dict) and isinstance(expected, dict)),
            "first_live_candidate_pair",
        )
        if isinstance(candidate, dict) and isinstance(expected, dict):
            valid_first_live_candidate(baseline, expected, candidate)
        _valid_failure_isolation(evidence)
        return

    valid_enablement_evidence(baseline, evidence)
    require(evidence.get("rollout_policy") == POLICY, "enablement_policy")
    require("direct_first_live_authorization" not in evidence, "strict_no_waiver")
    samples = evidence["images"]
    by_package = {item["package_id"]: item for item in samples}
    identities: set[tuple[str, str, int, str]] = set()
    for item in samples:
        _valid_final_jpeg(baseline, item)
        identity = (
            item.get("business_date"),
            item.get("slot"),
            item.get("ordinal"),
            item.get("base_job_id"),
        )
        identities.add(identity)
    require(len(identities) == len(samples), "distinct_news_lineage")
    group = evidence["group_test"]
    sample = by_package[group["package_id"]]
    require(
        group.get("base_job_id") == sample["base_job_id"]
        and group.get("business_date") == sample["business_date"]
        and group.get("slot") == sample["slot"]
        and group.get("ordinal") == sample["ordinal"]
        and group.get("jpeg_bytes") == sample["jpeg_bytes"]
        and group.get("source_url_sha256") == sample["source_url_sha256"]
        and group.get("unknown_count") == 0
        and group.get("infographic_attempt_count") == 1
        and group.get("receipt_sha256") == _receipt_hash(group),
        "same_news_fixed_group_receipt",
    )
    _valid_failure_isolation(evidence)


def plan(
    manifest: dict[str, Any],
    release: dict[str, Any],
    current: dict[str, Any],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    valid_manifest(manifest)
    valid_release_receipt(manifest, release)
    valid_current(manifest, release, current, enabled=False)
    valid_same_news_evidence(current, evidence, release)
    mode = evidence.get("enablement_mode", STRICT_MODE)
    selected_policy = (
        DIRECT_FIRST_LIVE_POLICY if mode == DIRECT_FIRST_LIVE_MODE else POLICY
    )
    return {
        "phase": "enablement_plan_only",
        "policy": selected_policy,
        "enablement_mode": mode,
        "release_receipt_sha256": release["receipt_sha256"],
        "current_sha256": sha(canonical(current)),
        "evidence_sha256": sha(canonical(evidence)),
        "recipient_fingerprint": current["recipient_fingerprint"],
        "slots": list(SLOTS),
        "max_ordinal": MAX_ORDINAL,
        "flags": ACTIVE_FLAGS,
        "review_mode": REVIEW_MODE,
        "max_daily_image_intents": MAX_DAILY_IMAGE_INTENTS,
        "first_success_to_ordinary_group": mode == DIRECT_FIRST_LIVE_MODE,
        "waived_pre_enable_gates": (
            ["three_approved_jpegs", "fixed_group_triple_receipt"]
            if mode == DIRECT_FIRST_LIVE_MODE
            else []
        ),
        "authorization_sha256": (
            evidence["direct_first_live_authorization"]["authorization_sha256"]
            if mode == DIRECT_FIRST_LIVE_MODE
            else None
        ),
        "production_enable_available": False,
        "reason": "declarative receipts and fake-host simulation cannot authenticate a live target or send outcome",
    }


class SimulatedEnableHost(Protocol):
    """Small host boundary shared by fake tests and the separately armed CLI."""

    def capture(self) -> dict[str, Any]: ...
    def install_flags(
        self, flags: dict[str, bool], max_ordinal: int, review_mode: str
    ) -> None: ...
    def restart_dispatcher(self, command: tuple[str, ...]) -> None: ...
    def start_producer(self, command: tuple[str, ...]) -> None: ...
    def disable_supplement_preserve_base(self) -> None: ...


class ProductionEnableHost(SimulatedEnableHost, Protocol):
    def arm_production_mutation(
        self, manifest: dict[str, Any], current: dict[str, Any]
    ) -> None: ...


def simulate(
    host: SimulatedEnableHost,
    manifest: dict[str, Any],
    release: dict[str, Any],
    current: dict[str, Any],
    evidence: dict[str, Any],
    attempt_dir: Path,
    lock_paths: tuple[Path, Path],
) -> dict[str, Any]:
    """One attempt on an injected fake; never a production activation method."""
    checked = plan(manifest, release, current, evidence)
    frozen_manifest = json.loads(canonical(manifest))
    frozen_release = json.loads(canonical(release))
    frozen_current = json.loads(canonical(current))
    frozen_evidence = json.loads(canonical(evidence))
    require(not attempt_dir.exists(), "enablement_attempt_exists_reconcile_only")
    with two_local_locks(lock_paths):
        require(host.capture() == frozen_current, "enablement_fresh_current_drift")
        attempt_dir.mkdir(mode=0o700, exist_ok=False)
        write_new(
            attempt_dir / "enablement-intent.json",
            {
                "policy": checked["policy"],
                "enablement_mode": checked["enablement_mode"],
                "authorization_sha256": checked["authorization_sha256"],
                "waived_pre_enable_gates": checked["waived_pre_enable_gates"],
                "release_receipt_sha256": frozen_release["receipt_sha256"],
                "recipient_fingerprint": frozen_current["recipient_fingerprint"],
                "evidence_sha256": checked["evidence_sha256"],
                "all_slots": list(SLOTS),
                "max_ordinal": MAX_ORDINAL,
                "unknown_result_auto_replay": False,
                "simulation_only": True,
            },
        )
        completed = False
        try:
            host.install_flags(dict(ACTIVE_FLAGS), MAX_ORDINAL, REVIEW_MODE)
            require(
                not any(token in DISPATCHER_START for token in FORBIDDEN_START_TOKENS)
                and "--no-deps" in DISPATCHER_START
                and "--no-build" in DISPATCHER_START
                and DISPATCHER_START[-1] == "wecom-dispatcher",
                "forbidden_dispatcher_dependency",
            )
            host.restart_dispatcher(DISPATCHER_START)
            require(
                not any(token in PRODUCER_START for token in FORBIDDEN_START_TOKENS)
                and "--no-deps" in PRODUCER_START,
                "forbidden_producer_dependency",
            )
            require(
                "--no-build" in PRODUCER_START
                and PRODUCER_START[-1] == "wecom-infographic-producer"
                and PRODUCER_START[PRODUCER_START.index("--profile") + 1]
                == "infographic",
                "forbidden_producer_dependency",
            )
            host.start_producer(PRODUCER_START)
            post = host.capture()
            valid_current(frozen_manifest, frozen_release, post, enabled=True)
            require(
                post["recipient_fingerprint"]
                == frozen_current["recipient_fingerprint"],
                "enablement_recipient_drift",
            )
            receipt = {
                "version": "r16-all-news-enablement-receipt-v1",
                "policy": checked["policy"],
                "enablement_mode": checked["enablement_mode"],
                "authorization_sha256": checked["authorization_sha256"],
                "waived_pre_enable_gates": checked["waived_pre_enable_gates"],
                "candidate": frozen_manifest["image"],
                "release_receipt_sha256": frozen_release["receipt_sha256"],
                "before_sha256": sha(canonical(frozen_current)),
                "after_sha256": sha(canonical(post)),
                "evidence_sha256": sha(canonical(frozen_evidence)),
                "recipient_fingerprint": frozen_current["recipient_fingerprint"],
                "slots": list(SLOTS),
                "max_ordinal": MAX_ORDINAL,
                "base_delivery_healthy": True,
                "unknown_result_auto_replay": False,
                "simulation_only": True,
            }
            receipt["receipt_sha256"] = _receipt_hash(receipt)
            write_new(attempt_dir / "simulation-enablement-receipt.json", receipt)
            completed = True
        finally:
            if not completed:
                try:
                    write_new(
                        attempt_dir / "enablement-recovery-required.json",
                        {
                            "policy": checked["policy"],
                            "candidate": frozen_manifest["image"],
                            "disable_supplement_only": True,
                            "preserve_base_text_and_original_image": True,
                            "no_auto_replay_unknown": True,
                            "simulation_only": True,
                        },
                    )
                finally:
                    host.disable_supplement_preserve_base()
    return {"phase": "simulated_enablement", "production_enable_available": False}


def valid_release_attempt_files(
    manifest: dict[str, Any], manifest_sha256: str, release_dir: Path
) -> dict[str, Any]:
    """Authenticate the actual completed release tree, not a supplied JSON story."""
    info = release_dir.lstat()
    require(
        release_dir.name.startswith("r16-forward-")
        and re.fullmatch(
            r"r16-forward-[A-Za-z0-9][A-Za-z0-9.-]{4,63}", release_dir.name
        )
        is not None
        and stat.S_ISDIR(info.st_mode)
        and info.st_uid == os.geteuid()
        and stat.S_IMODE(info.st_mode) == 0o700,
        "release_attempt_directory",
    )

    def private_json(name: str) -> dict[str, Any]:
        path = release_dir / name
        info = path.lstat()
        require(
            stat.S_ISREG(info.st_mode)
            and info.st_nlink == 1
            and info.st_uid == os.geteuid()
            and stat.S_IMODE(info.st_mode) == 0o600,
            "release_attempt_file_type",
        )
        value = json.loads(path.read_bytes())
        require(isinstance(value, dict), "release_attempt_json")
        return cast(dict[str, Any], value)

    require(
        not (release_dir / "forward-recovery-required.json").exists()
        and not (release_dir / "forward-recovery-required.json").is_symlink(),
        "release_recovery_marker",
    )
    intent = private_json("intent.json")
    release = private_json("release-receipt.json")
    backup = private_json("backup-receipt.json")
    clone = private_json("clone-receipt.json")
    migration_intent = private_json("migration-intent.json")
    valid_release_receipt(manifest, release)
    require(
        intent.get("version") == "r16-default-off-intent-v1"
        and release["attempt_id"] == release_dir.name
        and release["manifest_sha256"] == manifest_sha256
        and intent.get("candidate") == manifest["image"]
        and intent.get("revision") == manifest["revision"]
        and intent.get("manifest_sha256") == manifest_sha256
        and intent.get("baseline_sha256") == release["baseline_sha256"]
        and intent.get("old_app_restart_forbidden_after_migration_intent") is True
        and intent.get("simulation_only") is False
        and is_sha(backup.get("pg_dump_sha256"))
        and type(backup.get("pg_dump_bytes")) is int
        and backup["pg_dump_bytes"] > 0
        and backup.get("pg_restore_toc_read") is True
        and backup.get("protected_files_readback") is True
        and release["backup_receipt_sha256"] == sha(canonical(backup))
        and clone.get("chain") == MIGRATION_CHAIN
        and clone.get("source_dump_sha256") == backup["pg_dump_sha256"]
        and clone.get("source_schema") == BASE_SCHEMA
        and clone.get("target_schema") == TARGET_SCHEMA
        and clone.get("isolated_restore_readback") is True
        and clone.get("isolated_target") is True
        and clone.get("existing_table_counts_equal") is True
        and is_sha(clone.get("source_business_sha256"))
        and clone.get("retained_business_sha256") == clone["source_business_sha256"]
        and release["clone_receipt_sha256"] == clone.get("receipt_sha256")
        and clone.get("receipt_sha256") == _receipt_hash(clone),
        "release_attempt_crosscheck",
    )
    require(
        migration_intent.get("chain") == MIGRATION_CHAIN
        and migration_intent.get("forward_only") is True
        and migration_intent.get("clone_receipt_sha256") == clone["receipt_sha256"]
        and migration_intent.get("backup_receipt_sha256")
        == release["backup_receipt_sha256"]
        and migration_intent.get("if_unobserved") == "forward_reconcile_only"
        and migration_intent.get("old_app_restart_forbidden") is True
        and migration_intent.get("automatic_restore_or_downgrade_forbidden") is True,
        "release_migration_intent_crosscheck",
    )
    return release


def valid_authorization_record(path: Path) -> None:
    """Require the exact separately preserved user-decision file, not a JSON claim."""
    info = path.lstat()
    require(
        stat.S_ISREG(info.st_mode)
        and info.st_nlink == 1
        and info.st_uid == os.geteuid()
        and stat.S_IMODE(info.st_mode) == 0o600
        and 0 < info.st_size <= 64 * 1024
        and sha(path.read_bytes()) == USER_AUTHORIZATION_RECORD_SHA256,
        "user_authorization_file_mismatch",
    )


def enable_production(
    host: ProductionEnableHost,
    manifest: dict[str, Any],
    manifest_sha256: str,
    release_dir: Path,
    evidence: dict[str, Any],
    authorization_record: Path,
    attempt_dir: Path,
    lock_paths: tuple[Path, Path],
) -> dict[str, Any]:
    """Forward-only enablement; no retry or replay after an ambiguous attempt."""
    valid_production_manifest(manifest)
    require(is_sha(manifest_sha256), "manifest_hash_unpinned")
    require(
        attempt_dir.name.startswith("r16-enable-")
        and re.fullmatch(r"r16-enable-[A-Za-z0-9][A-Za-z0-9.-]{4,63}", attempt_dir.name)
        is not None
        and not attempt_dir.exists(),
        "enablement_attempt_exists_reconcile_only",
    )
    require(
        evidence.get("enablement_mode") == DIRECT_FIRST_LIVE_MODE,
        "production_direct_mode_required",
    )
    auth = evidence.get("direct_first_live_authorization")
    require(
        isinstance(auth, dict)
        and auth.get("user_authorization_record_sha256")
        == USER_AUTHORIZATION_RECORD_SHA256,
        "user_authorization_record_mismatch",
    )
    valid_authorization_record(authorization_record)
    with two_local_locks(lock_paths):
        require(not attempt_dir.exists(), "enablement_attempt_exists_reconcile_only")
        require(
            not any(
                item.name.startswith("r16-enable-")
                for item in attempt_dir.parent.iterdir()
            ),
            "prior_enable_attempt_reconcile_only",
        )
        release = valid_release_attempt_files(manifest, manifest_sha256, release_dir)
        require(
            release["recipient_fingerprint"] == APPROVED_RECIPIENT_FINGERPRINT,
            "approved_recipient_mismatch",
        )
        current = host.capture()
        checked = plan(manifest, release, current, evidence)
        require(
            current["recipient_fingerprint"] == APPROVED_RECIPIENT_FINGERPRINT,
            "approved_recipient_mismatch",
        )
        host.arm_production_mutation(manifest, current)
        attempt_dir.mkdir(mode=0o700, exist_ok=False)
        fsync_directory(attempt_dir.parent)
        write_new(
            attempt_dir / "enablement-intent.json",
            {
                "version": "r16-direct-first-live-intent-v1",
                "candidate": manifest["image"],
                "revision": manifest["revision"],
                "manifest_sha256": manifest_sha256,
                "release_receipt_sha256": release["receipt_sha256"],
                "before_sha256": sha(canonical(current)),
                "evidence_sha256": checked["evidence_sha256"],
                "authorization_sha256": checked["authorization_sha256"],
                "recipient_fingerprint": APPROVED_RECIPIENT_FINGERPRINT,
                "user_authorization_record_sha256": USER_AUTHORIZATION_RECORD_SHA256,
                "simulation_only": False,
                "unknown_result_auto_replay": False,
            },
        )
        completed = False
        try:
            host.install_flags(dict(ACTIVE_FLAGS), MAX_ORDINAL, REVIEW_MODE)
            host.restart_dispatcher(DISPATCHER_START)
            host.start_producer(PRODUCER_START)
            after = host.capture()
            valid_current(manifest, release, after, enabled=True)
            require(
                after["recipient_fingerprint"] == APPROVED_RECIPIENT_FINGERPRINT,
                "enablement_recipient_drift",
            )
            receipt = {
                "version": "r16-direct-first-live-production-receipt-v1",
                "status": "enabled_all_news",
                "candidate": manifest["image"],
                "revision": manifest["revision"],
                "schema": TARGET_SCHEMA,
                "release_receipt_sha256": release["receipt_sha256"],
                "before_sha256": sha(canonical(current)),
                "after_sha256": sha(canonical(after)),
                "evidence_sha256": checked["evidence_sha256"],
                "authorization_sha256": checked["authorization_sha256"],
                "user_authorization_record_sha256": USER_AUTHORIZATION_RECORD_SHA256,
                "recipient_fingerprint": APPROVED_RECIPIENT_FINGERPRINT,
                "slots": list(SLOTS),
                "max_ordinal": MAX_ORDINAL,
                "review_mode": REVIEW_MODE,
                "max_daily_image_intents": MAX_DAILY_IMAGE_INTENTS,
                "first_success_to_ordinary_group": True,
                "base_delivery_healthy": True,
                "unknown_result_auto_replay": False,
                "simulation_only": False,
            }
            receipt["receipt_sha256"] = _receipt_hash(receipt)
            write_new(attempt_dir / "enablement-receipt.json", receipt)
            completed = True
        finally:
            if not completed:
                try:
                    write_new(
                        attempt_dir / "enablement-recovery-required.json",
                        {
                            "version": "r16-enablement-recovery-v1",
                            "candidate": manifest["image"],
                            "disable_supplement_only": True,
                            "preserve_base_text_and_original_image": True,
                            "no_auto_replay_unknown": True,
                            "simulation_only": False,
                        },
                    )
                finally:
                    host.disable_supplement_preserve_base()
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "enable"))
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--release", type=Path)
    parser.add_argument("--current", type=Path)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--authorization-record", type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--bundle", type=Path)
    parser.add_argument("--manifest-sha256")
    parser.add_argument("--operator-sha256")
    parser.add_argument("--enable-host-sha256")
    parser.add_argument("--release-launcher-sha256")
    parser.add_argument("--release-attempt", type=Path)
    parser.add_argument("--attempt-name")
    args = parser.parse_args()
    if args.action == "enable":
        if not args.execute:
            print(json.dumps({"phase": "blocked", "code": "execute_required"}))
            return 2
        try:
            from r16_release_cli import authenticate_bundle, trusted_path

            require(os.geteuid() == 0, "root_required")
            require(
                args.bundle is not None
                and args.manifest is not None
                and args.evidence is not None
                and args.authorization_record is not None
                and args.release_attempt is not None
                and isinstance(args.attempt_name, str)
                and is_sha(args.manifest_sha256)
                and is_sha(args.operator_sha256)
                and is_sha(args.enable_host_sha256)
                and is_sha(args.release_launcher_sha256),
                "enable_arguments",
            )
            require(
                Path(__file__).absolute() == args.bundle / "r16_enablement.py"
                and args.manifest == args.bundle / "candidate.json",
                "enable_not_in_sealed_bundle",
            )
            require(
                args.operator_sha256 == sha(Path(__file__).read_bytes())
                and args.enable_host_sha256
                == sha(Path(__file__).with_name("r16_enable_host.py").read_bytes()),
                "enable_operator_source_hash",
            )
            require(
                args.release_attempt.parent == Path("/opt/edu-ai-release-backups")
                and not args.release_attempt.is_symlink(),
                "release_attempt_location",
            )
            manifest = authenticate_bundle(
                args.bundle / "r16_release_cli.py",
                args.bundle,
                args.manifest,
                args.manifest_sha256,
                args.release_launcher_sha256,
            )
            require(
                manifest.get("enable_operator_sha256") == args.operator_sha256
                and manifest.get("enable_host_sha256") == args.enable_host_sha256,
                "enable_source_not_manifest_pinned",
            )
            trusted_path(args.evidence, directory=False)
            trusted_path(args.authorization_record, directory=False)
            trusted_path(args.release_attempt, directory=True)
            require(
                stat.S_IMODE(args.evidence.stat().st_mode) == 0o600
                and 0 < args.evidence.stat().st_size <= 64 * 1024,
                "enable_evidence_file",
            )
            evidence = json.loads(args.evidence.read_bytes())
            require(
                isinstance(manifest, dict) and isinstance(evidence, dict),
                "enable_input_json",
            )
            from r16_enable_host import EnablePaths, RealEnableHost
            from r16_real_host import BACKUP_ROOT, SubprocessRunner

            host = RealEnableHost(SubprocessRunner(), EnablePaths(), manifest)
            receipt = enable_production(
                host,
                manifest,
                args.manifest_sha256,
                args.release_attempt,
                evidence,
                args.authorization_record,
                BACKUP_ROOT / args.attempt_name,
                (
                    Path("/var/lock/edu-ai-deploy.lock"),
                    Path("/var/lock/edu-ai-backup.lock"),
                ),
            )
            print(
                json.dumps(
                    {
                        "phase": "enabled_all_news",
                        "candidate": receipt["candidate"],
                        "receipt_sha256": receipt["receipt_sha256"],
                        "recipient_fingerprint": receipt["recipient_fingerprint"],
                    },
                    sort_keys=True,
                )
            )
            return 0
        except Exception as exc:  # noqa: BLE001 - redact unexpected host failures
            known = (
                isinstance(exc, ReleaseBlocked)
                or exc.__class__.__name__ == "LaunchBlocked"
            )
            code = str(exc) if known else "enable_input_or_host_failure"
            if re.fullmatch(r"[a-z][a-z0-9_]*", code) is None:
                code = "enable_input_or_host_failure"
            print(json.dumps({"phase": "blocked", "code": code}))
            return 2
    if not (args.manifest and args.release and args.current and args.evidence):
        parser.error("plan requires --manifest, --release, --current and --evidence")
    try:
        result = plan(
            json.loads(args.manifest.read_bytes()),
            json.loads(args.release.read_bytes()),
            json.loads(args.current.read_bytes()),
            json.loads(args.evidence.read_bytes()),
        )
    except (ReleaseBlocked, OSError, ValueError, TypeError, KeyError) as exc:
        print(json.dumps({"phase": "blocked", "code": str(exc)}))
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
