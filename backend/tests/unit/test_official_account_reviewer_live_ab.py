from __future__ import annotations

import json
import os
import stat
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from typing import Literal

import pytest
from evals.official_account_reviewer_live_ab.dataset import (
    DEFAULT_CASES_PATH,
    LiveAbDatasetError,
    load_live_ab_dataset,
)
from evals.official_account_reviewer_live_ab.harness import (
    AttemptExecutor,
    LiveAbHarnessError,
    append_jsonl_durable,
    build_attempt_plans,
    build_blinded_worksheet,
    build_manifest,
    ensure_live_artifact_path,
    execute_authorized_experiment,
    load_json_model,
    preflight_failure_ledger,
    write_blinding_secret_exclusive,
    write_json_exclusive,
)
from evals.official_account_reviewer_live_ab.metrics import (
    build_live_ab_report,
    build_report_failure_ledger,
)
from evals.official_account_reviewer_live_ab.models import (
    ADJUDICATION_SCHEMA_VERSION,
    ATTEMPT_SCHEMA_VERSION,
    AUTHORIZATION_SCHEMA_VERSION,
    JUDGMENT_SCHEMA_VERSION,
    LIVE_AUTHORIZATION_ACKNOWLEDGEMENT,
    REPORT_CONFIRMATION_ACKNOWLEDGEMENT,
    AttemptObservation,
    AttemptPlan,
    AttemptStatus,
    BlindMapRow,
    ExperimentArm,
    ExperimentVersions,
    FailureCode,
    FailureLedger,
    HumanAdjudication,
    HumanJudgment,
    LiveAbCase,
    LiveAuthorization,
    PricingSnapshot,
    ProviderCallObservation,
    ProviderCallStatus,
    ProviderUsage,
    ReviewOutcome,
    RevisionArtifact,
    RunManifest,
    WorksheetRow,
)
from evals.official_account_reviewer_live_ab.privacy import scan_evidence
from evals.official_account_reviewer_live_ab.reporting import (
    build_calibration_candidate,
    canonical_json,
    render_markdown,
    render_worksheet_csv,
    report_sha256,
)
from evals.official_account_reviewer_live_ab.runner import main as runner_main

FIXED_NOW = datetime(2026, 9, 3, 1, 0, tzinfo=UTC)
BLINDING_SECRET = b"reviewer-live-ab-test-secret-0001"


def _manifest(
    *,
    repetitions: int = 2,
    minimum_evidence_pairs: int = 8,
    blinding_secret: bytes = BLINDING_SECRET,
    run_ref: str | None = None,
) -> RunManifest:
    dataset = load_live_ab_dataset()
    return build_manifest(
        dataset=dataset,
        run_ref=run_ref or f"reviewer-ab-unit-r{repetitions}",
        created_at=FIXED_NOW - timedelta(hours=1),
        execution_window_start=FIXED_NOW,
        execution_window_end=FIXED_NOW + timedelta(hours=1),
        git_sha="a" * 40,
        provider="provider-test",
        model="model-test",
        temperature=0.0,
        seed=7,
        versions=ExperimentVersions(
            writer_version="official.writer.initial",
            reviewer_r1_version="official.reviewer.r1",
            repair_writer_version="official.writer.repair",
            reviewer_r2_version="official.reviewer.r2",
            prompt_version="official-account-reviewer-prompt-v1",
            rubric_version="official-account-editorial-rubric-v1",
            review_policy_version="official-account-review-policy-v1",
            repair_policy_version="official-account-repair-policy-v1",
            enforce_policy_version="official-account-review-enforce-v1",
            registry_sha256="b" * 64,
        ),
        pricing=PricingSnapshot(
            effective_date="2026-09-02",
            input_usd_per_million_tokens=1.0,
            output_usd_per_million_tokens=2.0,
            reasoning_usd_per_million_tokens=2.0,
            pricing_source_sha256="c" * 64,
        ),
        sample_count=4,
        repetitions=repetitions,
        max_input_tokens_per_call=4_096,
        max_output_tokens_per_call=1_024,
        max_cost_per_provider_call_usd=0.05,
        minimum_evidence_pairs=minimum_evidence_pairs,
        minimum_double_annotated_pairs=4 if repetitions == 2 else 2,
        blinding_secret=blinding_secret,
        bootstrap_samples=1_000,
        bootstrap_seed=11,
    )


def _authorization(manifest: RunManifest) -> LiveAuthorization:
    return LiveAuthorization(
        schema_version=AUTHORIZATION_SCHEMA_VERSION,
        manifest_sha256=manifest.manifest_sha256,
        provider=manifest.provider,
        model=manifest.model,
        sample_count=manifest.sample_count,
        repetitions=manifest.repetitions,
        max_provider_calls=manifest.max_provider_calls,
        max_cost_per_provider_call_usd=manifest.max_cost_per_provider_call_usd,
        max_total_cost_usd=manifest.max_total_cost_usd,
        valid_from=manifest.execution_window_start - timedelta(minutes=5),
        valid_until=manifest.execution_window_end + timedelta(minutes=5),
        approved_by_ref="reviewer:human-owner",
        acknowledgement=LIVE_AUTHORIZATION_ACKNOWLEDGEMENT,
    )


def _is_defect_case(case_id: str) -> bool:
    return case_id.rsplit("-", 1)[1] in {"001", "009"}


def _provider_call(
    plan: AttemptPlan,
    index: int,
    phase: Literal["reviewer_r1", "repair_writer", "reviewer_r2"],
) -> ProviderCallObservation:
    return ProviderCallObservation(
        call_index=index,
        phase=phase,
        status=ProviderCallStatus.COMPLETED,
        request_fingerprint=sha256(f"{plan.attempt_ref}:{index}".encode()).hexdigest(),
        latency_ms=20 + index,
        usage=ProviderUsage(input_tokens=100, output_tokens=20, reasoning_tokens=0),
    )


def _observation(plan: AttemptPlan) -> AttemptObservation:
    initial = RevisionArtifact(
        revision_no=1,
        artifact_sha256=plan.initial_article_sha256,
        artifact_ref=f"artifact:{plan.initial_article_sha256[:20]}",
    )
    defect = _is_defect_case(plan.case_id)
    if plan.arm is ExperimentArm.BASELINE:
        return AttemptObservation(
            schema_version=ATTEMPT_SCHEMA_VERSION,
            attempt_ref=plan.attempt_ref,
            manifest_sha256=plan.manifest_sha256,
            authorization_sha256=plan.authorization_sha256,
            case_id=plan.case_id,
            repetition=plan.repetition,
            arm=plan.arm,
            initial_article_sha256=plan.initial_article_sha256,
            status=AttemptStatus.COMPLETED,
            initial_decision=ReviewOutcome.ACCEPTED,
            final_decision=ReviewOutcome.ACCEPTED,
            critical_defect_detected_on_initial=False,
            revisions=(initial,),
            total_latency_ms=10,
        )
    if defect:
        repaired_sha = sha256(f"repair:{plan.case_id}:{plan.repetition}".encode()).hexdigest()
        return AttemptObservation(
            schema_version=ATTEMPT_SCHEMA_VERSION,
            attempt_ref=plan.attempt_ref,
            manifest_sha256=plan.manifest_sha256,
            authorization_sha256=plan.authorization_sha256,
            case_id=plan.case_id,
            repetition=plan.repetition,
            arm=plan.arm,
            initial_article_sha256=plan.initial_article_sha256,
            status=AttemptStatus.COMPLETED,
            initial_decision=ReviewOutcome.REJECTED,
            final_decision=ReviewOutcome.ACCEPTED,
            critical_defect_detected_on_initial=True,
            repair_performed=True,
            revisions=(
                initial,
                RevisionArtifact(
                    revision_no=2,
                    artifact_sha256=repaired_sha,
                    artifact_ref=f"artifact:{repaired_sha[:20]}",
                ),
            ),
            provider_calls=(
                _provider_call(plan, 1, "reviewer_r1"),
                _provider_call(plan, 2, "repair_writer"),
                _provider_call(plan, 3, "reviewer_r2"),
            ),
            total_latency_ms=90,
        )
    return AttemptObservation(
        schema_version=ATTEMPT_SCHEMA_VERSION,
        attempt_ref=plan.attempt_ref,
        manifest_sha256=plan.manifest_sha256,
        authorization_sha256=plan.authorization_sha256,
        case_id=plan.case_id,
        repetition=plan.repetition,
        arm=plan.arm,
        initial_article_sha256=plan.initial_article_sha256,
        status=AttemptStatus.COMPLETED,
        initial_decision=ReviewOutcome.ACCEPTED,
        final_decision=ReviewOutcome.ACCEPTED,
        critical_defect_detected_on_initial=False,
        revisions=(initial,),
        provider_calls=(_provider_call(plan, 1, "reviewer_r1"),),
        total_latency_ms=30,
    )


def _evidence(
    manifest: RunManifest,
) -> tuple[
    tuple[AttemptObservation, ...],
    tuple[WorksheetRow, ...],
    tuple[BlindMapRow, ...],
    tuple[HumanJudgment, ...],
    tuple[HumanAdjudication, ...],
]:
    authorization = _authorization(manifest)
    observations = tuple(
        _observation(plan) for plan in build_attempt_plans(manifest, authorization)
    )
    worksheet, mapping = build_blinded_worksheet(
        manifest=manifest,
        authorization=authorization,
        observations=observations,
        blinding_secret=BLINDING_SECRET,
    )
    judgments: list[HumanJudgment] = []
    adjudications: list[HumanAdjudication] = []
    for row in mapping:
        defect = _is_defect_case(row.case_id)
        editorial_pass = not defect or row.arm is ExperimentArm.TREATMENT
        critical = defect and row.arm is ExperimentArm.BASELINE
        for annotator in ("annotator:one", "annotator:two"):
            judgments.append(
                HumanJudgment(
                    schema_version=JUDGMENT_SCHEMA_VERSION,
                    blind_ref=row.blind_ref,
                    annotator_ref=annotator,
                    editorial_pass=editorial_pass,
                    critical_defect_present=critical,
                    defect_codes=("critical:unsupported-claim",) if critical else (),
                )
            )
        adjudications.append(
            HumanAdjudication(
                schema_version=ADJUDICATION_SCHEMA_VERSION,
                blind_ref=row.blind_ref,
                source_annotator_refs=("annotator:one", "annotator:two"),
                method="consensus",
                editorial_pass=editorial_pass,
                critical_defect_present=critical,
                defect_codes=("critical:unsupported-claim",) if critical else (),
            )
        )
    return observations, worksheet, mapping, tuple(judgments), tuple(adjudications)


def test_dataset_and_manifest_freeze_stratified_identical_paired_inputs() -> None:
    dataset = load_live_ab_dataset()
    manifest = _manifest()

    assert len(dataset.cases) == 12
    assert {case.split for case in dataset.cases} == {"calibration", "holdout"}
    assert {case.split for case in dataset.cases if case.case_id in manifest.selected_case_ids} == {
        "calibration",
        "holdout",
    }
    assert manifest.max_provider_calls == 4 * 2 * 3
    assert manifest.max_total_cost_usd == 1.2
    assert all(
        binding.initial_article_sha256
        == binding.baseline_initial_sha256
        == binding.treatment_initial_sha256
        for binding in manifest.case_bindings
    )

    tampered = manifest.model_dump(mode="json")
    tampered["provider"] = "different-provider"
    with pytest.raises(ValueError, match="manifest SHA-256"):
        RunManifest.model_validate(tampered)


def test_dataset_rejects_privacy_labels_and_duplicate_json_keys(tmp_path: Path) -> None:
    records = DEFAULT_CASES_PATH.read_text(encoding="utf-8").splitlines()
    first = json.loads(records[0])
    first["api_key"] = "sk-" + ("x" * 24)
    records[0] = json.dumps(first, ensure_ascii=False, separators=(",", ":"))
    unsafe = tmp_path / "unsafe.jsonl"
    unsafe.write_text("\n".join(records) + "\n", encoding="utf-8")

    with pytest.raises(LiveAbDatasetError, match="unsafe live A/B record"):
        load_live_ab_dataset(unsafe)

    duplicate = tmp_path / "duplicate.jsonl"
    duplicate.write_text(
        DEFAULT_CASES_PATH.read_text(encoding="utf-8").replace(
            '"case_id":"review-ab-001"',
            '"case_id":"review-ab-001","case_id":"review-ab-001"',
            1,
        ),
        encoding="utf-8",
    )
    with pytest.raises(LiveAbDatasetError, match="invalid live A/B JSON"):
        load_live_ab_dataset(duplicate)
    assert "prohibited_key:provider_body" in scan_evidence({"provider_body": "raw"})


def test_privacy_scan_distinguishes_typed_hash_entropy_from_article_pii() -> None:
    # Cryptographic evidence is uniformly random and can coincidentally contain a
    # phone or identity-number-shaped digit run. Only a correctly named, complete
    # SHA-256 field is exempt; the same text in content remains blocked.
    digit_heavy_digest = ("a" + ("1" * 18) + "b").ljust(64, "a")

    assert scan_evidence({"artifact_commitment_sha256": digit_heavy_digest}) == ()
    assert "identity_number" in scan_evidence({"article_text": digit_heavy_digest})
    assert "identity_number" in scan_evidence({"artifact_commitment_sha256": "1" * 18})


def test_preflight_requires_exact_authorization_and_emits_zero_call_ledger() -> None:
    manifest = _manifest()
    authorization = _authorization(manifest)

    assert preflight_failure_ledger(manifest, authorization=authorization, now=FIXED_NOW) is None
    missing = preflight_failure_ledger(manifest, authorization=None, now=FIXED_NOW)
    assert missing is not None
    assert missing.reason is FailureCode.AUTHORIZATION_MISSING
    assert missing.live_model_calls == 0
    assert missing.uplift_claims == ()

    mismatch = authorization.model_copy(update={"model": "other-model"})
    blocked = preflight_failure_ledger(manifest, authorization=mismatch, now=FIXED_NOW)
    assert blocked is not None
    assert blocked.reason is FailureCode.AUTHORIZATION_MISMATCH
    expired = preflight_failure_ledger(
        manifest,
        authorization=authorization,
        now=authorization.valid_until + timedelta(seconds=1),
    )
    assert expired is not None
    assert expired.reason is FailureCode.AUTHORIZATION_EXPIRED

    tampered = missing.model_dump(mode="json")
    tampered["live_model_calls"] = 1
    with pytest.raises(ValueError, match="zero live calls"):
        FailureLedger.model_validate(tampered)
    hash_tampered = missing.model_dump(mode="json")
    hash_tampered["planned_max_provider_calls"] -= 1
    with pytest.raises(ValueError, match="failure-ledger SHA-256"):
        FailureLedger.model_validate(hash_tampered)


def test_cli_live_is_explicitly_disconnected_and_secure(tmp_path: Path) -> None:
    manifest = _manifest()
    authorization = _authorization(manifest)
    manifest_path = tmp_path / "manifest.json"
    authorization_path = tmp_path / "authorization.json"
    ledger_path = tmp_path / "live-failure-ledger.json"
    env_example = Path(__file__).resolve().parents[3] / ".env.example"
    config_path = Path(__file__).resolve().parents[2] / "app/core/config.py"
    before = (env_example.read_bytes(), config_path.read_bytes())
    write_json_exclusive(manifest_path, manifest)
    write_json_exclusive(authorization_path, authorization)

    result = runner_main(
        (
            "live",
            "--manifest",
            str(manifest_path),
            "--authorization",
            str(authorization_path),
            "--failure-ledger",
            str(ledger_path),
            "--at",
            FIXED_NOW.isoformat(),
        )
    )

    assert result == 2
    ledger = FailureLedger.model_validate_json(ledger_path.read_text(encoding="utf-8"))
    assert ledger.reason is FailureCode.EXECUTOR_NOT_INSTALLED
    assert ledger.live_model_calls == 0
    assert stat.S_IMODE(ledger_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(authorization_path.stat().st_mode) == 0o600
    assert before == (env_example.read_bytes(), config_path.read_bytes())


def test_cli_prepare_is_a_zero_call_dry_run_with_exact_ceilings(tmp_path: Path) -> None:
    output_dir = tmp_path / "prepared"

    result = runner_main(
        (
            "prepare",
            "--output-dir",
            str(output_dir),
            "--run-ref",
            "reviewer-ab-cli-unit",
            "--git-sha",
            "a" * 40,
            "--provider",
            "provider-test",
            "--model",
            "model-test",
            "--window-start",
            FIXED_NOW.isoformat(),
            "--window-end",
            (FIXED_NOW + timedelta(hours=1)).isoformat(),
            "--max-cost-per-call-usd",
            "0.05",
            "--pricing-effective-date",
            "2026-09-02",
            "--input-usd-per-million",
            "1",
            "--output-usd-per-million",
            "2",
            "--reasoning-usd-per-million",
            "2",
            "--pricing-source-sha256",
            "c" * 64,
            "--registry-sha256",
            "b" * 64,
        )
    )

    assert result == 0
    manifest = RunManifest.model_validate_json(
        (output_dir / "manifest.json").read_text(encoding="utf-8")
    )
    ledger = FailureLedger.model_validate_json(
        (output_dir / "failure-ledger.json").read_text(encoding="utf-8")
    )
    assert manifest.max_provider_calls == 36
    assert manifest.max_total_cost_usd == 1.8
    assert ledger.reason is FailureCode.AUTHORIZATION_MISSING
    assert ledger.live_model_calls == 0
    assert ledger.uplift_claims == ()
    assert stat.S_IMODE((output_dir / ".blinding-key").stat().st_mode) == 0o600
    assert stat.S_IMODE((output_dir / "manifest.json").stat().st_mode) == 0o600
    assert stat.S_IMODE((output_dir / "failure-ledger.json").stat().st_mode) == 0o600


class _SuccessfulExecutor(AttemptExecutor):
    def __init__(self) -> None:
        self.attempt_refs: list[str] = []

    async def execute(self, *, plan: AttemptPlan, case: LiveAbCase) -> AttemptObservation:
        assert case.case_id == plan.case_id
        self.attempt_refs.append(plan.attempt_ref)
        return _observation(plan)


class _AmbiguousExecutor(AttemptExecutor):
    def __init__(self) -> None:
        self.calls = 0

    async def execute(self, *, plan: AttemptPlan, case: LiveAbCase) -> AttemptObservation:
        del case
        self.calls += 1
        if plan.arm is ExperimentArm.TREATMENT:
            raise RuntimeError("raw provider exception must not enter evidence")
        return _observation(plan)


@pytest.mark.asyncio
async def test_executor_runs_each_attempt_once_and_persists_secure_ledger(tmp_path: Path) -> None:
    manifest = _manifest(repetitions=1, minimum_evidence_pairs=4)
    executor = _SuccessfulExecutor()

    observations = await execute_authorized_experiment(
        manifest=manifest,
        authorization=_authorization(manifest),
        dataset=load_live_ab_dataset(),
        executor=executor,
        output_dir=tmp_path / "success",
        now=FIXED_NOW,
    )

    assert len(observations) == 8
    assert executor.attempt_refs == [
        plan.attempt_ref for plan in build_attempt_plans(manifest, _authorization(manifest))
    ]
    attempts_path = tmp_path / "success/attempts.jsonl"
    assert len(attempts_path.read_text(encoding="utf-8").splitlines()) == 8
    assert stat.S_IMODE(attempts_path.stat().st_mode) == 0o600
    assert stat.S_IMODE((tmp_path / "success/authorization.json").stat().st_mode) == 0o600


@pytest.mark.asyncio
async def test_ambiguous_attempt_stops_without_retry_or_raw_error(tmp_path: Path) -> None:
    manifest = _manifest(repetitions=1, minimum_evidence_pairs=4)
    executor = _AmbiguousExecutor()
    output_dir = tmp_path / "unknown"

    with pytest.raises(LiveAbHarnessError, match="stopped without retry"):
        await execute_authorized_experiment(
            manifest=manifest,
            authorization=_authorization(manifest),
            dataset=load_live_ab_dataset(),
            executor=executor,
            output_dir=output_dir,
            now=FIXED_NOW,
        )

    assert executor.calls == 2
    ledger_text = (output_dir / "failure-ledger.json").read_text(encoding="utf-8")
    assert "raw provider exception" not in ledger_text
    ledger = FailureLedger.model_validate_json(ledger_text)
    assert ledger.reason is FailureCode.PROVIDER_RESULT_UNKNOWN
    assert ledger.live_model_calls is None
    assert len((output_dir / "attempts.jsonl").read_text().splitlines()) == 1


def test_blinded_worksheet_has_no_arm_model_decision_or_secret() -> None:
    manifest = _manifest()
    observations, worksheet, mapping, _, _ = _evidence(manifest)
    rendered = render_worksheet_csv(worksheet)

    assert len(worksheet) == len(observations)
    assert {row.candidate for row in worksheet} == {"A", "B"}
    assert {row.arm for row in mapping} == {ExperimentArm.BASELINE, ExperimentArm.TREATMENT}
    assert all(row.artifact_ref == f"artifact:{row.blind_ref}" for row in worksheet)
    assert not {row.artifact_ref for row in worksheet}.intersection(
        {row.source_artifact_ref for row in mapping}
    )
    assert not {row.artifact_commitment_sha256 for row in worksheet}.intersection(
        {row.artifact_sha256 for row in mapping}
    )
    for prohibited in (
        "baseline_single_writer",
        "treatment_governed_reviewer",
        manifest.provider,
        manifest.model,
        "accepted",
        BLINDING_SECRET.hex(),
        "/root/",
    ):
        assert prohibited not in rendered

    different_run = _manifest(run_ref="reviewer-ab-unit-different-run")
    different_authorization = _authorization(different_run)
    different_observations = tuple(
        _observation(plan) for plan in build_attempt_plans(different_run, different_authorization)
    )
    different_rows, _ = build_blinded_worksheet(
        manifest=different_run,
        authorization=different_authorization,
        observations=different_observations,
        blinding_secret=BLINDING_SECRET,
    )
    assert not {row.artifact_commitment_sha256 for row in worksheet}.intersection(
        {row.artifact_commitment_sha256 for row in different_rows}
    )

    different_secret = b"reviewer-live-ab-test-secret-0002"
    different_key_manifest = _manifest(
        blinding_secret=different_secret,
        run_ref="reviewer-ab-unit-different-key",
    )
    different_key_authorization = _authorization(different_key_manifest)
    different_key_observations = tuple(
        _observation(plan)
        for plan in build_attempt_plans(different_key_manifest, different_key_authorization)
    )
    different_key_rows, _ = build_blinded_worksheet(
        manifest=different_key_manifest,
        authorization=different_key_authorization,
        observations=different_key_observations,
        blinding_secret=different_secret,
    )
    assert not {row.artifact_commitment_sha256 for row in worksheet}.intersection(
        {row.artifact_commitment_sha256 for row in different_key_rows}
    )


def test_cli_imports_attempts_and_human_gold_into_recomputable_report(tmp_path: Path) -> None:
    manifest = _manifest()
    observations, _, _, judgments, adjudications = _evidence(manifest)
    manifest_path = tmp_path / "manifest.json"
    authorization_path = tmp_path / "authorization.json"
    attempts_path = tmp_path / "attempts.jsonl"
    key_path = tmp_path / ".blinding-key"
    worksheet_path = tmp_path / "worksheet.jsonl"
    worksheet_csv_path = tmp_path / "worksheet.csv"
    mapping_path = tmp_path / "blind-map.jsonl"
    judgments_path = tmp_path / "judgments.jsonl"
    adjudications_path = tmp_path / "adjudications.jsonl"
    report_path = tmp_path / "report.json"
    markdown_path = tmp_path / "report.md"
    report_failure_path = tmp_path / "report-failure-ledger.json"
    write_json_exclusive(manifest_path, manifest)
    write_json_exclusive(authorization_path, _authorization(manifest))
    write_blinding_secret_exclusive(key_path, BLINDING_SECRET)
    for observation in observations:
        append_jsonl_durable(attempts_path, observation)
    for judgment in judgments:
        append_jsonl_durable(judgments_path, judgment)
    for adjudication in adjudications:
        append_jsonl_durable(adjudications_path, adjudication)

    worksheet_result = runner_main(
        (
            "worksheet",
            "--manifest",
            str(manifest_path),
            "--authorization",
            str(authorization_path),
            "--attempts",
            str(attempts_path),
            "--blinding-key",
            str(key_path),
            "--worksheet-jsonl",
            str(worksheet_path),
            "--worksheet-csv",
            str(worksheet_csv_path),
            "--blind-map-jsonl",
            str(mapping_path),
        )
    )
    report_result = runner_main(
        (
            "report",
            "--manifest",
            str(manifest_path),
            "--authorization",
            str(authorization_path),
            "--attempts",
            str(attempts_path),
            "--worksheet",
            str(worksheet_path),
            "--blind-map",
            str(mapping_path),
            "--blinding-key",
            str(key_path),
            "--judgments",
            str(judgments_path),
            "--adjudications",
            str(adjudications_path),
            "--report-json",
            str(report_path),
            "--report-markdown",
            str(markdown_path),
            "--failure-ledger",
            str(report_failure_path),
        )
    )

    assert worksheet_result == 0
    assert report_result == 0
    assert "baseline_single_writer" not in worksheet_csv_path.read_text(encoding="utf-8")
    assert "treatment_governed_reviewer" not in worksheet_path.read_text(encoding="utf-8")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["conclusion_eligible"] is True
    assert len(report["resume_claims"]) == 1
    assert not report_failure_path.exists()
    assert _authorization(manifest).approved_by_ref not in json.dumps(report)
    assert LIVE_AUTHORIZATION_ACKNOWLEDGEMENT not in json.dumps(report)
    for path in (
        worksheet_path,
        worksheet_csv_path,
        mapping_path,
        report_path,
        markdown_path,
    ):
        assert stat.S_IMODE(path.stat().st_mode) == 0o600

    different_authorization = _authorization(manifest).model_copy(
        update={"approved_by_ref": "reviewer:different-local-approval"}
    )
    different_authorization_path = tmp_path / "different-authorization.json"
    cross_run_failure_path = tmp_path / "cross-run-failure-ledger.json"
    write_json_exclusive(different_authorization_path, different_authorization)
    cross_run_result = runner_main(
        (
            "report",
            "--manifest",
            str(manifest_path),
            "--authorization",
            str(different_authorization_path),
            "--attempts",
            str(attempts_path),
            "--worksheet",
            str(worksheet_path),
            "--blind-map",
            str(mapping_path),
            "--blinding-key",
            str(key_path),
            "--judgments",
            str(judgments_path),
            "--adjudications",
            str(adjudications_path),
            "--report-json",
            str(tmp_path / "cross-run-report.json"),
            "--report-markdown",
            str(tmp_path / "cross-run-report.md"),
            "--failure-ledger",
            str(cross_run_failure_path),
        )
    )
    cross_run_ledger = FailureLedger.model_validate_json(
        cross_run_failure_path.read_text(encoding="utf-8")
    )
    assert cross_run_result == 2
    assert cross_run_ledger.reason is FailureCode.ARTIFACT_INTEGRITY_FAILED
    assert cross_run_ledger.live_model_calls == sum(
        len(item.provider_calls) for item in observations
    )
    assert cross_run_ledger.uplift_claims == ()
    assert not (tmp_path / "cross-run-report.json").exists()


def test_human_gold_report_emits_paired_ci_variance_bad_cases_and_confirmed_candidate() -> None:
    manifest = _manifest()
    observations, worksheet, mapping, judgments, adjudications = _evidence(manifest)

    report = build_live_ab_report(
        manifest=manifest,
        authorization=_authorization(manifest),
        dataset=load_live_ab_dataset(),
        observations=observations,
        worksheet=worksheet,
        blind_map=mapping,
        blinding_secret=BLINDING_SECRET,
        judgments=judgments,
        adjudications=adjudications,
    )

    baseline, treatment = report.arms
    assert report.conclusion_eligible is True
    assert report.evidence_blockers == ()
    assert report.complete_pair_count == 8
    assert report.human_agreement.double_annotated_pair_count >= 4
    assert report.human_agreement.judgment_count == 24
    assert report.human_agreement.editorial_pairwise_agreement == 1.0
    assert baseline.editorial_pass_at_2 == 0.5
    assert treatment.editorial_pass_at_2 == 1.0
    assert baseline.critical_defect_recall == 0.0
    assert treatment.critical_defect_recall == 1.0
    assert baseline.false_accept_count == 4
    assert baseline.false_accept_rate == 1.0
    assert treatment.false_accept_count == 0
    assert treatment.false_accept_rate is None
    assert treatment.p95_latency_ms is not None
    assert treatment.estimated_cost_usd is not None
    assert len(report.paired_estimates) == 2
    assert all(item.repetition_delta_variance == 0.0 for item in report.paired_estimates)
    assert any(case.reason_codes == ("false_accept",) for case in report.bad_cases)
    assert len(report.resume_claims) == 1
    assert report.incremental.provider_call_count == treatment.provider_call_count
    assert report.incremental.estimated_cost_usd == treatment.estimated_cost_usd
    assert report.authorization_sha256 == report.evidence_artifact_hashes.authorization_sha256
    markdown = render_markdown(report)
    assert "online business uplift" in report.disclaimer
    assert BLINDING_SECRET.hex() not in canonical_json(report)
    assert _authorization(manifest).approved_by_ref not in canonical_json(report)
    assert "95% bootstrap CI" in markdown

    with pytest.raises(ValueError, match="exact human confirmation"):
        build_calibration_candidate(
            report=report,
            confirmed_at=FIXED_NOW,
            confirmed_by_ref="reviewer:human-owner",
            confirmation="yes",
            expected_report_sha256=report_sha256(report),
        )
    with pytest.raises(ValueError, match="canonical report SHA-256"):
        build_calibration_candidate(
            report=report,
            confirmed_at=FIXED_NOW,
            confirmed_by_ref="reviewer:human-owner",
            confirmation=REPORT_CONFIRMATION_ACKNOWLEDGEMENT,
            expected_report_sha256="0" * 64,
        )
    candidate = build_calibration_candidate(
        report=report,
        confirmed_at=FIXED_NOW,
        confirmed_by_ref="reviewer:human-owner",
        confirmation=REPORT_CONFIRMATION_ACKNOWLEDGEMENT,
        expected_report_sha256=report_sha256(report),
    )
    assert (
        candidate.report_sha256
        == sha256(
            json.dumps(
                report.model_dump(mode="json"),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            ).encode()
            + b"\n"
        ).hexdigest()
    )
    assert candidate.production_mode_changed is False
    assert candidate.authorization_sha256 == report.authorization_sha256


def test_calibration_agreement_uses_only_adjudication_sources() -> None:
    manifest = _manifest()
    observations, worksheet, mapping, judgments, adjudications = _evidence(manifest)
    calibration_cases = {
        case.case_id for case in load_live_ab_dataset().cases if case.split == "calibration"
    }
    mapping_by_blind = {row.blind_ref: row for row in mapping}
    single_source = tuple(
        item.model_copy(
            update={
                "source_annotator_refs": (item.source_annotator_refs[0],),
                "method": "single",
            }
        )
        if mapping_by_blind[item.blind_ref].case_id in calibration_cases
        else item
        for item in adjudications
    )

    report = build_live_ab_report(
        manifest=manifest,
        authorization=_authorization(manifest),
        dataset=load_live_ab_dataset(),
        observations=observations,
        worksheet=worksheet,
        blind_map=mapping,
        blinding_secret=BLINDING_SECRET,
        judgments=judgments,
        adjudications=single_source,
    )

    assert report.human_agreement.double_annotated_pair_count == 0
    assert report.human_agreement.judgment_count == 0
    assert report.human_agreement.editorial_pairwise_agreement is None
    assert "human_calibration_incomplete" in report.evidence_blockers
    assert report.resume_claims == ()

    disputed = adjudications[0].model_dump(mode="json") | {"method": "adjudicated"}
    with pytest.raises(ValueError, match="independent adjudicator"):
        HumanAdjudication.model_validate(disputed)


def test_unknown_usage_or_incomplete_evidence_emits_no_uplift_or_resume_claim(
    tmp_path: Path,
) -> None:
    manifest = _manifest()
    observations, worksheet, mapping, judgments, adjudications = _evidence(manifest)
    treatment_index = next(
        index for index, item in enumerate(observations) if item.arm is ExperimentArm.TREATMENT
    )
    target = observations[treatment_index]
    changed_call = target.provider_calls[0].model_copy(update={"usage": None})
    changed_target = target.model_copy(
        update={"provider_calls": (changed_call, *target.provider_calls[1:])}
    )
    with_unknown = (
        *observations[:treatment_index],
        changed_target,
        *observations[treatment_index + 1 :],
    )

    report = build_live_ab_report(
        manifest=manifest,
        authorization=_authorization(manifest),
        dataset=load_live_ab_dataset(),
        observations=with_unknown,
        worksheet=worksheet,
        blind_map=mapping,
        blinding_secret=BLINDING_SECRET,
        judgments=judgments,
        adjudications=adjudications,
    )

    assert report.conclusion_eligible is False
    assert "unknown_usage_cost" in report.evidence_blockers
    assert report.paired_estimates == ()
    assert report.resume_claims == ()
    assert report.arms[1].estimated_cost_usd is None
    assert "No uplift estimate is emitted" in render_markdown(report)
    with pytest.raises(ValueError, match="ineligible"):
        build_calibration_candidate(
            report=report,
            confirmed_at=FIXED_NOW,
            confirmed_by_ref="reviewer:human-owner",
            confirmation=REPORT_CONFIRMATION_ACKNOWLEDGEMENT,
            expected_report_sha256=report_sha256(report),
        )
    unknown_ledger = build_report_failure_ledger(
        manifest,
        _authorization(manifest),
        report,
        created_at=FIXED_NOW,
    )
    assert unknown_ledger.reason is FailureCode.USAGE_UNKNOWN_COST
    assert unknown_ledger.conclusion_eligible is False
    assert unknown_ledger.uplift_claims == ()

    manifest_path = tmp_path / "manifest.json"
    authorization_path = tmp_path / "authorization.json"
    attempts_path = tmp_path / "attempts.jsonl"
    mapping_path = tmp_path / "blind-map.jsonl"
    judgments_path = tmp_path / "judgments.jsonl"
    adjudications_path = tmp_path / "adjudications.jsonl"
    failure_path = tmp_path / "failure-ledger.json"
    write_json_exclusive(manifest_path, manifest)
    write_json_exclusive(authorization_path, _authorization(manifest))
    write_blinding_secret_exclusive(tmp_path / ".blinding-key", BLINDING_SECRET)
    for path, rows in (
        (attempts_path, with_unknown),
        (tmp_path / "worksheet.jsonl", worksheet),
        (mapping_path, mapping),
        (judgments_path, judgments),
        (adjudications_path, adjudications),
    ):
        for row in rows:
            append_jsonl_durable(path, row)
    assert (
        runner_main(
            (
                "report",
                "--manifest",
                str(manifest_path),
                "--authorization",
                str(authorization_path),
                "--attempts",
                str(attempts_path),
                "--worksheet",
                str(tmp_path / "worksheet.jsonl"),
                "--blind-map",
                str(mapping_path),
                "--blinding-key",
                str(tmp_path / ".blinding-key"),
                "--judgments",
                str(judgments_path),
                "--adjudications",
                str(adjudications_path),
                "--report-json",
                str(tmp_path / "report.json"),
                "--report-markdown",
                str(tmp_path / "report.md"),
                "--failure-ledger",
                str(failure_path),
            )
        )
        == 2
    )
    assert (
        FailureLedger.model_validate_json(failure_path.read_text(encoding="utf-8")).reason
        is FailureCode.USAGE_UNKNOWN_COST
    )

    removed_pair = (manifest.selected_case_ids[-1], manifest.repetitions)
    incomplete_observations = tuple(
        item for item in observations if (item.case_id, item.repetition) != removed_pair
    )
    incomplete_blind_refs = {
        row.blind_ref for row in mapping if (row.case_id, row.repetition) != removed_pair
    }
    incomplete = build_live_ab_report(
        manifest=manifest,
        authorization=_authorization(manifest),
        dataset=load_live_ab_dataset(),
        observations=incomplete_observations,
        worksheet=tuple(row for row in worksheet if row.blind_ref in incomplete_blind_refs),
        blind_map=tuple(row for row in mapping if row.blind_ref in incomplete_blind_refs),
        blinding_secret=BLINDING_SECRET,
        judgments=tuple(row for row in judgments if row.blind_ref in incomplete_blind_refs),
        adjudications=tuple(row for row in adjudications if row.blind_ref in incomplete_blind_refs),
    )
    assert incomplete.conclusion_eligible is False
    assert "insufficient_evidence" in incomplete.evidence_blockers
    assert incomplete.failure_taxonomy == {"missing_attempt": 2}
    assert incomplete.paired_estimates == ()
    assert incomplete.resume_claims == ()
    incomplete_ledger = build_report_failure_ledger(
        manifest,
        _authorization(manifest),
        incomplete,
        created_at=FIXED_NOW,
    )
    assert incomplete_ledger.reason is FailureCode.INCOMPLETE_ATTEMPTS


def test_secure_artifact_write_is_atomic_and_never_overwrites(tmp_path: Path) -> None:
    manifest = _manifest()
    ledger = preflight_failure_ledger(manifest, authorization=None, now=FIXED_NOW)
    assert ledger is not None
    path = tmp_path / "failure-ledger.json"
    write_json_exclusive(path, ledger)
    original = path.read_bytes()

    with pytest.raises(LiveAbHarnessError, match="atomically"):
        write_json_exclusive(path, ledger)

    assert path.read_bytes() == original
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert not tuple(path for path in tmp_path.iterdir() if path.name.endswith(".tmp"))

    with pytest.raises(LiveAbHarnessError, match="backend/evals"):
        ensure_live_artifact_path(DEFAULT_CASES_PATH.parent / "forbidden-live-run")


def test_evidence_io_rejects_symlinks_and_non_private_inputs(tmp_path: Path) -> None:
    manifest = _manifest()
    source = tmp_path / "manifest.json"
    write_json_exclusive(source, manifest)
    linked = tmp_path / "linked.json"
    linked.symlink_to(source)

    with pytest.raises(LiveAbHarnessError, match="could not be read"):
        load_json_model(linked, RunManifest)

    source.chmod(0o644)
    with pytest.raises(LiveAbHarnessError, match="private regular file"):
        load_json_model(source, RunManifest)

    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    ledger = preflight_failure_ledger(manifest, authorization=None, now=FIXED_NOW)
    assert ledger is not None
    with pytest.raises(LiveAbHarnessError, match="atomically"):
        write_json_exclusive(linked_parent / "ledger.json", ledger)
    assert not (real_parent / "ledger.json").exists()


def test_attempt_contract_rejects_fake_repairs_and_duplicate_requests() -> None:
    manifest = _manifest(repetitions=1, minimum_evidence_pairs=4)
    observations, worksheet, mapping, judgments, adjudications = _evidence(manifest)
    repair = next(item for item in observations if item.repair_performed)

    with pytest.raises(ValueError, match="initial rejection"):
        AttemptObservation.model_validate(
            repair.model_dump(mode="json") | {"initial_decision": "accepted"}
        )
    duplicate_revision = repair.model_dump(mode="json")
    duplicate_revision["revisions"][1]["artifact_sha256"] = duplicate_revision["revisions"][0][
        "artifact_sha256"
    ]
    with pytest.raises(ValueError, match="distinct"):
        AttemptObservation.model_validate(duplicate_revision)

    treatments = [item for item in observations if item.arm is ExperimentArm.TREATMENT]
    first, second = treatments[:2]
    duplicated_call = second.provider_calls[0].model_copy(
        update={"request_fingerprint": first.provider_calls[0].request_fingerprint}
    )
    changed_second = second.model_copy(
        update={"provider_calls": (duplicated_call, *second.provider_calls[1:])}
    )
    changed_observations = tuple(
        changed_second if item.attempt_ref == second.attempt_ref else item for item in observations
    )
    with pytest.raises(LiveAbHarnessError, match="request fingerprints"):
        build_live_ab_report(
            manifest=manifest,
            authorization=_authorization(manifest),
            dataset=load_live_ab_dataset(),
            observations=changed_observations,
            worksheet=worksheet,
            blind_map=mapping,
            blinding_secret=BLINDING_SECRET,
            judgments=judgments,
            adjudications=adjudications,
        )

    tampered_worksheet = (
        worksheet[0].model_copy(update={"artifact_commitment_sha256": "0" * 64}),
        *worksheet[1:],
    )
    with pytest.raises(LiveAbHarnessError, match="worksheet commitment"):
        build_live_ab_report(
            manifest=manifest,
            authorization=_authorization(manifest),
            dataset=load_live_ab_dataset(),
            observations=observations,
            worksheet=tampered_worksheet,
            blind_map=mapping,
            blinding_secret=BLINDING_SECRET,
            judgments=judgments,
            adjudications=adjudications,
        )

    changed_authorization = _authorization(manifest).model_copy(
        update={"approved_by_ref": "reviewer:other-local-approval"}
    )
    with pytest.raises(LiveAbHarnessError, match="frozen plan"):
        build_live_ab_report(
            manifest=manifest,
            authorization=changed_authorization,
            dataset=load_live_ab_dataset(),
            observations=observations,
            worksheet=worksheet,
            blind_map=mapping,
            blinding_secret=BLINDING_SECRET,
            judgments=judgments,
            adjudications=adjudications,
        )


def test_cli_errors_are_closed_and_do_not_echo_private_paths(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    private_path = tmp_path / "private-input-with-sensitive-name.json"
    os.symlink(tmp_path / "missing-target", private_path)

    result = runner_main(
        (
            "preflight",
            "--manifest",
            str(private_path),
            "--authorization",
            str(private_path),
            "--failure-ledger",
            str(tmp_path / "failure.json"),
        )
    )

    captured = capsys.readouterr()
    assert result == 1
    assert captured.err.strip() == "Reviewer live A/B harness failed: evidence_rejected"
    assert str(tmp_path) not in captured.err
