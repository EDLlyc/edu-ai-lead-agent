#!/usr/bin/env python3
"""Import-only full-coverage enablement PLAN and fake-host simulation.

No production adapter is accepted by the CLI. The existing R16 release starts
default-off; this separate contract models the user's direct all-news target
only after a distinct real default-off release receipt and the currently
required quality/fixed-group evidence. Python simulation is not an authority
to send a WeCom message or enable a host.
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any, Protocol

from r16_forward_operator import (
    OFF_FLAGS,
    SERVICES,
    TARGET_SCHEMA,
    ReleaseBlocked,
    canonical,
    is_sha,
    require,
    sha,
    two_local_locks,
    valid_enablement_evidence,
    valid_manifest,
    write_new,
)

POLICY = "r16-direct-all-news-after-release-v1"
NOTICE_VERSION = "wecom-infographic-advisory-notice-v1"
MAX_JPEG_BYTES = 2 * 1024 * 1024
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
    """A simulated release receipt is explicitly non-promotable."""
    require(
        release.get("version") == "r16-default-off-receipt-v1"
        and release.get("candidate") == manifest["image"]
        and release.get("revision") == manifest["revision"]
        and release.get("schema") == TARGET_SCHEMA
        and release.get("services") == len(SERVICES)
        and release.get("default_off") is True
        and release.get("verified") is True
        and release.get("simulation_only") is False
        and isinstance(release.get("activation_attempt_id"), str)
        and re.fullmatch(
            r"r16-forward-[a-z0-9][a-z0-9-]{4,63}", release["activation_attempt_id"]
        )
        is not None
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
        and current.get("unknown_work_count") == 0
        and type(current.get("pending_work_count")) is int
        and current.get("pending_work_count") == 0
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


def valid_same_news_evidence(
    baseline: dict[str, Any], evidence: dict[str, Any]
) -> None:
    """Preserve existing strict image/group gate, then bind final JPEG details."""
    valid_enablement_evidence(baseline, evidence)
    require(evidence.get("rollout_policy") == POLICY, "enablement_policy")
    samples = evidence["images"]
    by_package = {item["package_id"]: item for item in samples}
    identities: set[tuple[str, str, int, str]] = set()
    for item in samples:
        identity = (
            item.get("business_date"),
            item.get("slot"),
            item.get("ordinal"),
            item.get("base_job_id"),
        )
        require(
            isinstance(item.get("business_date"), str)
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
            and is_sha(item.get("source_url_sha256"))
            and item.get("footer_url_sha256") == item["source_url_sha256"]
            and isinstance(item.get("source_date"), str)
            and re.fullmatch(r"\d{4}-\d{2}-\d{2}", item["source_date"]) is not None
            and item.get("footer_date") == item["source_date"]
            and item.get("warning_notice_version") == NOTICE_VERSION
            and item.get("warning_visible") is True
            and item.get("image_intent_count") == 1
            and item.get("image_result_known") is True
            and item.get("delivery_unknown") is False,
            "same_news_final_jpeg",
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


def plan(
    manifest: dict[str, Any],
    release: dict[str, Any],
    current: dict[str, Any],
    evidence: dict[str, Any],
) -> dict[str, Any]:
    valid_manifest(manifest)
    valid_release_receipt(manifest, release)
    valid_current(manifest, release, current, enabled=False)
    valid_same_news_evidence(current, evidence)
    return {
        "phase": "enablement_plan_only",
        "policy": POLICY,
        "release_receipt_sha256": release["receipt_sha256"],
        "current_sha256": sha(canonical(current)),
        "evidence_sha256": sha(canonical(evidence)),
        "recipient_fingerprint": current["recipient_fingerprint"],
        "slots": list(SLOTS),
        "max_ordinal": MAX_ORDINAL,
        "flags": ACTIVE_FLAGS,
        "review_mode": REVIEW_MODE,
        "production_enable_available": False,
        "reason": "declarative receipts and fake-host simulation cannot authenticate a live target or send outcome",
    }


class SimulatedEnableHost(Protocol):
    """Fake-only; no production implementation or CLI path exists."""

    def capture(self) -> dict[str, Any]: ...
    def install_flags(
        self, flags: dict[str, bool], max_ordinal: int, review_mode: str
    ) -> None: ...
    def restart_dispatcher(self, command: tuple[str, ...]) -> None: ...
    def start_producer(self, command: tuple[str, ...]) -> None: ...
    def disable_supplement_preserve_base(self) -> None: ...


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
                "policy": POLICY,
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
                "policy": POLICY,
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
                            "policy": POLICY,
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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "enable"))
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--release", type=Path)
    parser.add_argument("--current", type=Path)
    parser.add_argument("--evidence", type=Path)
    args = parser.parse_args()
    if args.action == "enable":
        print(json.dumps({"phase": "blocked", "code": "production_enable_unavailable"}))
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
