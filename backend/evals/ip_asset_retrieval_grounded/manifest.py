from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, cast

from pydantic import ValidationError

from .models import (
    EVALUATOR_V2_VERSION,
    RUBRIC_V2_VERSION,
    GroundedRetrievalRunV2,
    GroundedSafeArtifactHash,
    GroundedSafeManifestMetrics,
    GroundedSafeRunManifestV2,
)

_PROHIBITED_MANIFEST_KEYS = frozenset(
    {
        "query",
        "query_text",
        "filename",
        "path",
        "image_path",
        "vector",
        "prompt",
        "provider_body",
        "provider_request_id",
        "user_id",
        "profile_id",
        "session_id",
        "ip",
        "user_agent",
        "cookie",
        "similarity",
        "score",
        "rank",
    }
)


def load_selective_report(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("grounded selective report could not be read") from error
    if not isinstance(raw, dict) or raw.get("schema_version") != (
        "ip-asset-grounded-selective-report-v2"
    ):
        raise ValueError("grounded selective report schema is invalid")
    _reject_prohibited_fields(raw, artifact="selective report")
    return cast(dict[str, Any], raw)


def current_git_sha(repo_root: Path) -> str:
    process = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=repo_root,
        check=False,
        capture_output=True,
        text=True,
    )
    sha = process.stdout.strip().casefold()
    if (
        process.returncode != 0
        or len(sha) != 40
        or any(char not in "0123456789abcdef" for char in sha)
    ):
        raise ValueError("grounded safe manifest could not resolve git SHA")
    return sha


def build_safe_manifest(
    *,
    run: GroundedRetrievalRunV2,
    run_path: Path,
    report: dict[str, Any],
    report_path: Path,
    git_sha: str,
) -> GroundedSafeRunManifestV2:
    _validate_run_artifact(run, run_path)
    _validate_report_artifact(report, report_path)
    _validate_report_identity(run, report)
    paired = report.get("paired_bootstrap", {})
    candidate = report.get("candidate", {})
    dev = _aggregate(candidate, "dev")
    holdout = _aggregate(candidate, "holdout")
    selected_policy = report.get("selection", {}).get("selected_policy", {})
    return GroundedSafeRunManifestV2(
        schema_version="ip-asset-grounded-safe-manifest-v2",
        run_ref=run.run_ref,
        git_sha=git_sha,
        evidence_tier="model_corpus_quality",
        maturity="seed",
        evaluator_version=EVALUATOR_V2_VERSION,
        rubric_version=RUBRIC_V2_VERSION,
        search_version=run.search_version,
        embedding_execution_mode=run.embedding_execution_mode,
        embedding_provider=run.embedding_provider,
        embedding_model=run.embedding_model,
        embedding_input_policy_version=run.embedding_input_policy_version,
        asset_set_fingerprint=run.asset_set_fingerprint,
        query_dataset_sha256=run.query_dataset_sha256,
        seed_dataset_sha256=run.seed_dataset_sha256,
        robustness_dataset_sha256=run.robustness_dataset_sha256,
        review_ledger_sha256=run.review_ledger_sha256,
        selected_policy_ref=str(selected_policy.get("policy_ref", "")),
        bootstrap_samples=_integer(paired, "samples"),
        bootstrap_seed=_integer(paired, "seed"),
        duration_ms=run.duration_ms,
        provider_request_count=run.provider_request_count,
        input_token_count=run.input_token_count,
        estimated_cost_usd=run.estimated_cost_usd,
        metrics=GroundedSafeManifestMetrics(
            dev_coverage=_required_rate(dev, "decision_coverage"),
            dev_selective_risk=_optional_rate(dev, "selective_risk"),
            dev_no_answer_false_positive_rate=_optional_rate(dev, "no_answer_false_positive_rate"),
            dev_answerable_false_abstention_rate=_optional_rate(
                dev, "answerable_false_abstention_rate"
            ),
            holdout_coverage=_required_rate(holdout, "decision_coverage"),
            holdout_selective_risk=_optional_rate(holdout, "selective_risk"),
            holdout_no_answer_false_positive_rate=_optional_rate(
                holdout, "no_answer_false_positive_rate"
            ),
            holdout_answerable_false_abstention_rate=_optional_rate(
                holdout, "answerable_false_abstention_rate"
            ),
        ),
        artifacts=(
            GroundedSafeArtifactHash(artifact_ref="grounded_run_v2", sha256=_sha256_file(run_path)),
            GroundedSafeArtifactHash(
                artifact_ref="selective_report_v2", sha256=_sha256_file(report_path)
            ),
        ),
        validity_notes=(
            "codex_seed_not_human_gold",
            "no_human_agreement",
            "holdout_not_used_for_policy_selection",
            "no_online_effectiveness_claim",
            "cost_unavailable_when_null",
            "harness_bound_to_run_and_artifact_hashes",
            "contamination_not_independently_audited",
            "ambiguous_or_broken_cases_not_independently_adjudicated",
            "corpus_drift_requires_new_asset_set_fingerprint",
        ),
    )


def load_safe_manifest(path: Path) -> GroundedSafeRunManifestV2:
    try:
        body = path.read_bytes()
        raw = json.loads(body)
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("grounded safe manifest could not be read") from error
    prohibited = _find_keys(raw, _PROHIBITED_MANIFEST_KEYS)
    if prohibited:
        raise ValueError(
            "grounded safe manifest contains prohibited fields: " + ", ".join(sorted(prohibited))
        )
    try:
        return GroundedSafeRunManifestV2.model_validate_json(body, strict=True)
    except ValidationError as error:
        raise ValueError("grounded safe manifest schema is invalid") from error


def validate_safe_manifest_artifacts(
    manifest: GroundedSafeRunManifestV2,
    *,
    run: GroundedRetrievalRunV2,
    run_path: Path,
    report: dict[str, Any],
    report_path: Path,
) -> None:
    expected = build_safe_manifest(
        run=run,
        run_path=run_path,
        report=report,
        report_path=report_path,
        git_sha=manifest.git_sha,
    )
    if manifest != expected:
        raise ValueError("grounded safe manifest identity or artifact hash drifted")


def _validate_run_artifact(run: GroundedRetrievalRunV2, run_path: Path) -> None:
    try:
        body = run_path.read_bytes()
        raw = json.loads(body)
        artifact_run = GroundedRetrievalRunV2.model_validate_json(body, strict=True)
    except (OSError, json.JSONDecodeError, ValidationError) as error:
        raise ValueError("grounded safe manifest run artifact is invalid") from error
    _reject_prohibited_fields(raw, artifact="run artifact")
    if artifact_run != run:
        raise ValueError("grounded safe manifest run object does not match its artifact")


def _validate_report_artifact(report: dict[str, Any], report_path: Path) -> None:
    artifact_report = load_selective_report(report_path)
    normalized = json.loads(json.dumps(report, ensure_ascii=False, sort_keys=True))
    if artifact_report != normalized:
        raise ValueError("grounded safe manifest report object does not match its artifact")


def _validate_report_identity(run: GroundedRetrievalRunV2, report: dict[str, Any]) -> None:
    _reject_prohibited_fields(report, artifact="selective report")
    expected_run = {
        "run_ref": run.run_ref,
        "created_at": run.created_at,
        "search_version": run.search_version,
        "embedding_execution_mode": run.embedding_execution_mode,
        "embedding_provider": run.embedding_provider,
        "embedding_model": run.embedding_model,
        "embedding_dimensions": run.embedding_dimensions,
        "embedding_input_policy_version": run.embedding_input_policy_version,
        "asset_set_fingerprint": run.asset_set_fingerprint,
        "query_dataset_sha256": run.query_dataset_sha256,
        "seed_dataset_sha256": run.seed_dataset_sha256,
        "robustness_dataset_sha256": run.robustness_dataset_sha256,
        "review_ledger_sha256": run.review_ledger_sha256,
        "duration_ms": run.duration_ms,
        "provider_request_count": run.provider_request_count,
        "input_token_count": run.input_token_count,
        "estimated_cost_usd": run.estimated_cost_usd,
    }
    if report.get("run") != expected_run:
        raise ValueError("grounded safe manifest report identity does not match the run")
    truthfulness = report.get("truthfulness")
    required_truth = {
        "human_gold": False,
        "human_agreement_available": False,
        "online_user_effectiveness": False,
        "production_threshold_activated": False,
        "holdout_used_for_policy_selection": False,
    }
    if not isinstance(truthfulness, dict) or any(
        truthfulness.get(key) is not value for key, value in required_truth.items()
    ):
        raise ValueError("grounded safe manifest report truthfulness boundary is invalid")
    selection = report.get("selection")
    if not isinstance(selection, dict) or selection.get("split") != "dev":
        raise ValueError("grounded safe manifest report selection is not dev-only")


def _aggregate(candidate: object, split: str) -> dict[str, Any]:
    if not isinstance(candidate, dict):
        raise ValueError("grounded selective report candidate is invalid")
    split_body = candidate.get(split)
    if not isinstance(split_body, dict) or not isinstance(split_body.get("aggregate"), dict):
        raise ValueError("grounded selective report aggregate is missing")
    return cast(dict[str, Any], split_body["aggregate"])


def _required_rate(body: dict[str, Any], key: str) -> float:
    value = body.get(key)
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError("grounded selective report rate is invalid")
    return float(value)


def _optional_rate(body: dict[str, Any], key: str) -> float | None:
    value = body.get(key)
    if value is None:
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ValueError("grounded selective report optional rate is invalid")
    return float(value)


def _integer(body: object, key: str) -> int:
    if not isinstance(body, dict):
        raise ValueError("grounded selective report bootstrap identity is invalid")
    value = body.get(key)
    if not isinstance(value, int) or isinstance(value, bool):
        raise ValueError("grounded selective report bootstrap value is invalid")
    return value


def _sha256_file(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise ValueError("grounded safe manifest artifact could not be hashed") from error


def _reject_prohibited_fields(value: object, *, artifact: str) -> None:
    prohibited = _find_keys(value, _PROHIBITED_MANIFEST_KEYS)
    if prohibited:
        raise ValueError(
            f"grounded safe manifest {artifact} contains prohibited fields: "
            + ", ".join(sorted(prohibited))
        )


def _find_keys(value: object, prohibited: frozenset[str]) -> set[str]:
    if isinstance(value, dict):
        found = {str(key).casefold() for key in value if str(key).casefold() in prohibited}
        for child in value.values():
            found.update(_find_keys(child, prohibited))
        return found
    if isinstance(value, list):
        found_list: set[str] = set()
        for child in value:
            found_list.update(_find_keys(child, prohibited))
        return found_list
    return set()
