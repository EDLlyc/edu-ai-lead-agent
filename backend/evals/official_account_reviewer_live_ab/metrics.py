"""Human-gold paired metrics and conservative evidence eligibility for Reviewer A/B."""

from __future__ import annotations

import hmac
import random
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime
from hashlib import sha256
from statistics import variance
from typing import Literal, Self, cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .dataset import LoadedLiveAbDataset
from .harness import (
    LiveAbHarnessError,
    blind_artifact_commitment,
    build_attempt_plans,
    build_failure_ledger,
    provider_call_cost_usd,
    provider_call_was_attempted,
    validate_attempt_binding,
)
from .models import (
    REPORT_SCHEMA_VERSION,
    AttemptObservation,
    AttemptStatus,
    BlindMapRow,
    ExperimentArm,
    FailureCode,
    FailureLedger,
    HumanAdjudication,
    HumanJudgment,
    LiveAuthorization,
    ReviewOutcome,
    RunManifest,
    WorksheetRow,
    evidence_sha256,
)
from .privacy import require_privacy_safe

REPORT_DISCLAIMER = (
    "Human adjudication is the primary truth source. LLM-judge output is not accepted by this "
    "report path. Metrics apply only to the frozen synthetic dataset, provider/model/version "
    "bundle, and execution window in the bound manifest; they are not online business uplift. "
    "The authorization is an explicit local artifact, not a cryptographic provider receipt; a "
    "future live adapter must revalidate it immediately before every provider boundary."
)


class _ReportModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ArmMetrics(_ReportModel):
    arm: ExperimentArm
    evaluated_pair_count: int = Field(ge=0)
    editorial_pass_at_1: float | None = Field(default=None, ge=0, le=1)
    editorial_pass_at_2: float | None = Field(default=None, ge=0, le=1)
    critical_gold_count: int = Field(ge=0)
    critical_detected_count: int = Field(ge=0)
    critical_defect_recall: float | None = Field(default=None, ge=0, le=1)
    gold_negative_count: int = Field(ge=0)
    false_accept_count: int = Field(ge=0)
    false_accept_rate: float | None = Field(default=None, ge=0, le=1)
    gold_positive_count: int = Field(ge=0)
    false_reject_count: int = Field(ge=0)
    false_reject_rate: float | None = Field(default=None, ge=0, le=1)
    manual_review_count: int = Field(ge=0)
    manual_review_rate: float | None = Field(default=None, ge=0, le=1)
    p50_latency_ms: float | None = Field(default=None, ge=0)
    p95_latency_ms: float | None = Field(default=None, ge=0)
    provider_call_count: int = Field(ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    reasoning_tokens: int | None = Field(default=None, ge=0)
    unknown_usage_call_count: int = Field(ge=0)
    known_cost_lower_bound_usd: float = Field(ge=0)
    estimated_cost_usd: float | None = Field(default=None, ge=0)


class PairedEstimate(_ReportModel):
    metric: Literal["editorial_pass_at_2", "critical_defect_recall"]
    pair_count: int = Field(ge=1)
    baseline_mean: float
    treatment_mean: float
    treatment_minus_baseline: float
    confidence_level: float = Field(default=0.95, ge=0.95, le=0.95)
    ci_lower: float
    ci_upper: float
    bootstrap_samples: int = Field(ge=1_000, le=20_000)
    bootstrap_seed: int = Field(ge=0)
    repetition_delta_variance: float | None = Field(default=None, ge=0)


class HumanAgreement(_ReportModel):
    double_annotated_pair_count: int = Field(ge=0)
    judgment_count: int = Field(ge=0)
    editorial_pairwise_agreement: float | None = Field(default=None, ge=0, le=1)
    critical_pairwise_agreement: float | None = Field(default=None, ge=0, le=1)


class IncrementalMetrics(_ReportModel):
    p50_latency_ms: float | None
    p95_latency_ms: float | None
    provider_call_count: int
    known_cost_lower_bound_usd: float
    estimated_cost_usd: float | None


class EvidenceArtifactHashes(_ReportModel):
    authorization_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    attempts_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    worksheet_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    blind_map_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    judgments_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    adjudications_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class BadCase(_ReportModel):
    pair_ref: str
    arm: ExperimentArm
    reason_codes: tuple[str, ...]


class ResumeClaim(_ReportModel):
    metric: Literal["editorial_pass_at_2", "critical_defect_recall"]
    absolute_delta: float
    confidence_interval: tuple[float, float]
    dataset_scope: str
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class LiveAbReport(_ReportModel):
    schema_version: Literal["official-account-review-live-ab-report-v1"]
    disclaimer: str
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    authorization_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dataset_version: Literal["official-account-review-live-ab-dataset-v1"]
    dataset_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider: str
    model: str
    sample_count: int = Field(ge=1)
    repetitions: int = Field(ge=1)
    expected_attempt_count: int = Field(ge=2)
    observed_attempt_count: int = Field(ge=0)
    complete_pair_count: int = Field(ge=0)
    live_model_calls: int = Field(ge=0)
    human_gold: Literal[True] = True
    llm_judge_used: Literal[False] = False
    online_business_uplift_measured: Literal[False] = False
    integrity_passed: bool
    conclusion_eligible: bool
    evidence_blockers: tuple[str, ...]
    arms: tuple[ArmMetrics, ArmMetrics]
    incremental: IncrementalMetrics
    evidence_artifact_hashes: EvidenceArtifactHashes
    paired_estimates: tuple[PairedEstimate, ...]
    human_agreement: HumanAgreement
    failure_taxonomy: dict[str, int]
    bad_cases: tuple[BadCase, ...]
    resume_claims: tuple[ResumeClaim, ...]

    @model_validator(mode="after")
    def validate_report_projection(self) -> Self:
        if self.disclaimer != REPORT_DISCLAIMER:
            raise ValueError("report disclaimer must retain the evidence-scope warning")
        if tuple(item.arm for item in self.arms) != (
            ExperimentArm.BASELINE,
            ExperimentArm.TREATMENT,
        ):
            raise ValueError("report arms must retain the frozen baseline/treatment order")
        expected_attempts = self.sample_count * self.repetitions * 2
        if self.expected_attempt_count != expected_attempts:
            raise ValueError("report expected-attempt count drifted from its scope")
        if self.observed_attempt_count > expected_attempts:
            raise ValueError("report contains more attempts than its manifest scope")
        if self.complete_pair_count > self.sample_count * self.repetitions:
            raise ValueError("report contains more pairs than its manifest scope")
        if self.live_model_calls > self.sample_count * self.repetitions * 3:
            raise ValueError("report contains more provider calls than its manifest scope")
        if self.authorization_sha256 != self.evidence_artifact_hashes.authorization_sha256:
            raise ValueError("report authorization identity drifted from its evidence hashes")
        expected_eligibility = self.integrity_passed and not self.evidence_blockers
        if self.conclusion_eligible != expected_eligibility:
            raise ValueError("report conclusion eligibility drifted from its evidence gate")
        if self.conclusion_eligible:
            if self.observed_attempt_count != self.expected_attempt_count:
                raise ValueError("eligible report must contain the complete attempt set")
            if any(item.evaluated_pair_count != self.complete_pair_count for item in self.arms):
                raise ValueError("eligible report arm denominators must equal complete pairs")
            if self.live_model_calls != sum(item.provider_call_count for item in self.arms):
                raise ValueError("eligible report provider-call totals do not conserve")
        if not self.conclusion_eligible and (self.paired_estimates or self.resume_claims):
            raise ValueError("ineligible report cannot contain uplift estimates or resume claims")
        estimates_by_metric = {item.metric: item for item in self.paired_estimates}
        if len(estimates_by_metric) != len(self.paired_estimates):
            raise ValueError("report paired-estimate metrics must be unique")
        claims_by_metric = {item.metric: item for item in self.resume_claims}
        if len(claims_by_metric) != len(self.resume_claims):
            raise ValueError("report resume-claim metrics must be unique")
        expected_claim_metrics = {
            item.metric
            for item in self.paired_estimates
            if item.treatment_minus_baseline > 0 and item.ci_lower > 0
        }
        if set(claims_by_metric) != expected_claim_metrics:
            raise ValueError("report resume claims selectively diverged from paired estimates")
        expected_scope = (
            f"{self.dataset_version};n={self.sample_count};repetitions={self.repetitions};"
            f"provider={self.provider};model={self.model}"
        )
        for metric, claim in claims_by_metric.items():
            estimate = estimates_by_metric[metric]
            if (
                claim.absolute_delta != estimate.treatment_minus_baseline
                or claim.confidence_interval != (estimate.ci_lower, estimate.ci_upper)
                or claim.dataset_scope != expected_scope
                or claim.manifest_sha256 != self.manifest_sha256
            ):
                raise ValueError("report resume claim drifted from its paired estimate")
        return self


def build_live_ab_report(
    *,
    manifest: RunManifest,
    authorization: LiveAuthorization,
    dataset: LoadedLiveAbDataset,
    observations: Sequence[AttemptObservation],
    worksheet: Sequence[WorksheetRow],
    blind_map: Sequence[BlindMapRow],
    blinding_secret: bytes,
    judgments: Sequence[HumanJudgment],
    adjudications: Sequence[HumanAdjudication],
) -> LiveAbReport:
    """Recompute the report entirely from hash-bound attempts and blinded human labels."""

    require_privacy_safe(observations)
    require_privacy_safe(worksheet)
    require_privacy_safe(blind_map)
    require_privacy_safe(judgments)
    require_privacy_safe(adjudications)
    _validate_manifest_dataset(manifest, dataset)
    plans = build_attempt_plans(manifest, authorization)
    plan_by_ref = {plan.attempt_ref: plan for plan in plans}
    observation_by_key: dict[tuple[str, int, ExperimentArm], AttemptObservation] = {}
    for observation in observations:
        plan = plan_by_ref.get(observation.attempt_ref)
        if plan is None:
            raise LiveAbHarnessError("attempt is outside the report manifest")
        validate_attempt_binding(manifest, plan, observation)
        key = (observation.case_id, observation.repetition, observation.arm)
        if key in observation_by_key:
            raise LiveAbHarnessError("duplicate attempt in report evidence")
        observation_by_key[key] = observation
    request_fingerprints = tuple(
        call.request_fingerprint
        for observation in observations
        for call in observation.provider_calls
    )
    if len(request_fingerprints) != len(set(request_fingerprints)):
        raise LiveAbHarnessError("provider request fingerprints must be unique per logical call")

    mapping_by_key, mapping_by_blind = _validate_blind_map(
        manifest,
        observation_by_key,
        blind_map,
        worksheet,
        blinding_secret,
    )
    judgment_by_key = _validate_judgments(mapping_by_blind, judgments)
    adjudication_by_blind = _validate_adjudications(
        mapping_by_blind,
        judgment_by_key,
        adjudications,
    )

    failure_taxonomy = _failure_taxonomy(plans, observation_by_key)
    complete_pairs = _complete_pairs(
        manifest,
        observation_by_key,
        mapping_by_key,
        adjudication_by_blind,
    )
    double_annotated_pairs = _double_annotated_calibration_pairs(
        dataset,
        mapping_by_key,
        judgment_by_key,
        adjudication_by_blind,
    )
    agreement = _human_agreement(
        mapping_by_key,
        judgment_by_key,
        adjudication_by_blind,
        double_annotated_pairs,
    )
    blockers: list[str] = []
    if len(observation_by_key) != len(plans):
        blockers.append("incomplete_attempts")
    if any(item.status is not AttemptStatus.COMPLETED for item in observations):
        blockers.append("provider_failure_present")
    if len(complete_pairs) < manifest.minimum_evidence_pairs:
        blockers.append("insufficient_evidence")
    if len(adjudication_by_blind) != len(blind_map) or len(blind_map) != len(plans):
        blockers.append("incomplete_human_labels")
    if len(double_annotated_pairs) < manifest.minimum_double_annotated_pairs:
        blockers.append("human_calibration_incomplete")
    unknown_usage = sum(call.usage is None for item in observations for call in item.provider_calls)
    if unknown_usage:
        blockers.append("unknown_usage_cost")
    known_cost = sum(
        provider_call_cost_usd(call, manifest.pricing) or 0.0
        for item in observations
        for call in item.provider_calls
    )
    if known_cost > manifest.max_total_cost_usd + 1e-9:
        blockers.append("total_cost_ceiling_exceeded")
    if failure_taxonomy:
        blockers.append("failure_taxonomy_nonempty")
    blockers = sorted(set(blockers))
    integrity_passed = not {
        "incomplete_attempts",
        "incomplete_human_labels",
        "provider_failure_present",
        "total_cost_ceiling_exceeded",
    }.intersection(blockers)
    eligible = integrity_passed and not blockers

    arms = cast(
        tuple[ArmMetrics, ArmMetrics],
        tuple(
            _arm_metrics(
                arm,
                complete_pairs,
                observation_by_key,
                mapping_by_key,
                adjudication_by_blind,
                manifest,
            )
            for arm in (ExperimentArm.BASELINE, ExperimentArm.TREATMENT)
        ),
    )
    baseline, treatment = arms
    incremental = IncrementalMetrics(
        p50_latency_ms=_difference(treatment.p50_latency_ms, baseline.p50_latency_ms),
        p95_latency_ms=_difference(treatment.p95_latency_ms, baseline.p95_latency_ms),
        provider_call_count=treatment.provider_call_count - baseline.provider_call_count,
        known_cost_lower_bound_usd=round(
            treatment.known_cost_lower_bound_usd - baseline.known_cost_lower_bound_usd,
            8,
        ),
        estimated_cost_usd=_difference(
            treatment.estimated_cost_usd,
            baseline.estimated_cost_usd,
            digits=8,
        ),
    )
    paired_estimates = (
        _paired_estimates(
            manifest,
            complete_pairs,
            observation_by_key,
            mapping_by_key,
            adjudication_by_blind,
        )
        if eligible
        else ()
    )
    bad_cases = _bad_cases(
        complete_pairs,
        observation_by_key,
        mapping_by_key,
        adjudication_by_blind,
    )
    claims = tuple(
        ResumeClaim(
            metric=item.metric,
            absolute_delta=item.treatment_minus_baseline,
            confidence_interval=(item.ci_lower, item.ci_upper),
            dataset_scope=(
                f"{manifest.dataset_version};n={manifest.sample_count};"
                f"repetitions={manifest.repetitions};provider={manifest.provider};"
                f"model={manifest.model}"
            ),
            manifest_sha256=manifest.manifest_sha256,
        )
        for item in paired_estimates
        if item.treatment_minus_baseline > 0 and item.ci_lower > 0
    )
    report = LiveAbReport(
        schema_version=REPORT_SCHEMA_VERSION,
        disclaimer=REPORT_DISCLAIMER,
        manifest_sha256=manifest.manifest_sha256,
        authorization_sha256=evidence_sha256(authorization),
        dataset_version=manifest.dataset_version,
        dataset_sha256=manifest.dataset_sha256,
        provider=manifest.provider,
        model=manifest.model,
        sample_count=manifest.sample_count,
        repetitions=manifest.repetitions,
        expected_attempt_count=len(plans),
        observed_attempt_count=len(observations),
        complete_pair_count=len(complete_pairs),
        live_model_calls=sum(
            provider_call_was_attempted(call)
            for item in observations
            for call in item.provider_calls
        ),
        integrity_passed=integrity_passed,
        conclusion_eligible=eligible,
        evidence_blockers=tuple(blockers),
        arms=arms,
        incremental=incremental,
        evidence_artifact_hashes=EvidenceArtifactHashes(
            authorization_sha256=evidence_sha256(authorization),
            attempts_sha256=evidence_sha256(tuple(observations)),
            worksheet_sha256=evidence_sha256(tuple(worksheet)),
            blind_map_sha256=evidence_sha256(tuple(blind_map)),
            judgments_sha256=evidence_sha256(tuple(judgments)),
            adjudications_sha256=evidence_sha256(tuple(adjudications)),
        ),
        paired_estimates=paired_estimates,
        human_agreement=agreement,
        failure_taxonomy=dict(sorted(failure_taxonomy.items())),
        bad_cases=bad_cases,
        resume_claims=claims,
    )
    require_privacy_safe(report)
    return report


def build_report_failure_ledger(
    manifest: RunManifest,
    authorization: LiveAuthorization,
    report: LiveAbReport,
    *,
    created_at: datetime,
) -> FailureLedger:
    """Project an ineligible report to the same closed, no-uplift failure contract."""

    if report.conclusion_eligible:
        raise ValueError("eligible report does not need a failure ledger")
    blockers = set(report.evidence_blockers)
    if "provider_failure_present" in blockers:
        reason = FailureCode.PROVIDER_FAILED
    elif "unknown_usage_cost" in blockers:
        reason = FailureCode.USAGE_UNKNOWN_COST
    elif "incomplete_attempts" in blockers:
        reason = FailureCode.INCOMPLETE_ATTEMPTS
    elif "incomplete_human_labels" in blockers:
        reason = FailureCode.INCOMPLETE_HUMAN_LABELS
    elif "human_calibration_incomplete" in blockers:
        reason = FailureCode.HUMAN_CALIBRATION_INCOMPLETE
    elif "insufficient_evidence" in blockers:
        reason = FailureCode.INSUFFICIENT_EVIDENCE
    else:
        reason = FailureCode.ARTIFACT_INTEGRITY_FAILED
    return build_failure_ledger(
        manifest,
        reason=reason,
        created_at=created_at,
        live_model_calls=report.live_model_calls,
        authorization=authorization,
    )


PairKey = tuple[str, int]
AttemptKey = tuple[str, int, ExperimentArm]


def _validate_manifest_dataset(
    manifest: RunManifest,
    dataset: LoadedLiveAbDataset,
) -> None:
    if (
        manifest.dataset_version != dataset.dataset_version
        or manifest.dataset_sha256 != dataset.dataset_sha256
    ):
        raise LiveAbHarnessError("report dataset drifted from the manifest")
    bound = {item.case_id: item.initial_article_sha256 for item in manifest.case_bindings}
    if any(
        dataset.article_sha256_by_case.get(case_id) != digest for case_id, digest in bound.items()
    ):
        raise LiveAbHarnessError("report initial Article identity drifted")


def _validate_blind_map(
    manifest: RunManifest,
    observations: Mapping[AttemptKey, AttemptObservation],
    rows: Sequence[BlindMapRow],
    worksheet: Sequence[WorksheetRow],
    blinding_secret: bytes,
) -> tuple[dict[AttemptKey, BlindMapRow], dict[str, BlindMapRow]]:
    if not hmac.compare_digest(
        sha256(blinding_secret).hexdigest(),
        manifest.blinding_secret_sha256,
    ):
        raise LiveAbHarnessError("report blinding secret drifted from the manifest")
    worksheet_by_blind: dict[str, WorksheetRow] = {}
    for item in worksheet:
        if item.blind_ref in worksheet_by_blind:
            raise LiveAbHarnessError("worksheet blind identities must be unique")
        if (
            item.annotator_ref is not None
            or item.editorial_pass is not None
            or item.critical_defect_present is not None
            or item.defect_codes
        ):
            raise LiveAbHarnessError("report requires the original unlabeled worksheet")
        worksheet_by_blind[item.blind_ref] = item
    by_key: dict[AttemptKey, BlindMapRow] = {}
    by_blind: dict[str, BlindMapRow] = {}
    allowed_cases = set(manifest.selected_case_ids)
    for row in rows:
        if row.case_id not in allowed_cases or row.repetition > manifest.repetitions:
            raise LiveAbHarnessError("blind map escaped the manifest scope")
        key = (row.case_id, row.repetition, row.arm)
        if row.pair_ref != f"pair:{row.case_id}:{row.repetition}":
            raise LiveAbHarnessError("blind map pair identity drifted")
        if key in by_key or row.blind_ref in by_blind:
            raise LiveAbHarnessError("blind map identities must be unique")
        observation = observations.get(key)
        if observation is None or observation.status is not AttemptStatus.COMPLETED:
            raise LiveAbHarnessError("blind map references a missing or failed attempt")
        final = observation.revisions[-1]
        if (
            final.revision_no != row.revision_no
            or final.artifact_ref != row.source_artifact_ref
            or not hmac.compare_digest(final.artifact_sha256, row.artifact_sha256)
        ):
            raise LiveAbHarnessError("blind map artifact drifted from the attempt")
        worksheet_row = worksheet_by_blind.get(row.blind_ref)
        expected_commitment = blind_artifact_commitment(
            blinding_secret,
            manifest.manifest_sha256,
            row.pair_ref,
            row.candidate,
            row.blind_ref,
            row.artifact_sha256,
        )
        if (
            worksheet_row is None
            or worksheet_row.pair_ref != row.pair_ref
            or worksheet_row.candidate != row.candidate
            or worksheet_row.artifact_ref != f"artifact:{row.blind_ref}"
            or not hmac.compare_digest(
                worksheet_row.artifact_commitment_sha256,
                row.artifact_commitment_sha256,
            )
            or not hmac.compare_digest(row.artifact_commitment_sha256, expected_commitment)
        ):
            raise LiveAbHarnessError("worksheet commitment drifted from its private blind map")
        by_key[key] = row
        by_blind[row.blind_ref] = row
    if set(worksheet_by_blind) != set(by_blind):
        raise LiveAbHarnessError("worksheet and blind map must have exact identity coverage")
    candidates_by_pair: dict[str, set[str]] = defaultdict(set)
    for row in rows:
        candidates_by_pair[row.pair_ref].add(row.candidate)
    if any(candidates != {"A", "B"} for candidates in candidates_by_pair.values()):
        raise LiveAbHarnessError("each blinded pair must contain exactly candidates A and B")
    return by_key, by_blind


def _validate_judgments(
    mapping_by_blind: Mapping[str, BlindMapRow],
    judgments: Sequence[HumanJudgment],
) -> dict[tuple[str, str], HumanJudgment]:
    result: dict[tuple[str, str], HumanJudgment] = {}
    for item in judgments:
        if item.blind_ref not in mapping_by_blind:
            raise LiveAbHarnessError("human judgment references an unknown blind item")
        key = (item.blind_ref, item.annotator_ref)
        if key in result:
            raise LiveAbHarnessError("duplicate human judgment")
        result[key] = item
    return result


def _validate_adjudications(
    mapping_by_blind: Mapping[str, BlindMapRow],
    judgments: Mapping[tuple[str, str], HumanJudgment],
    adjudications: Sequence[HumanAdjudication],
) -> dict[str, HumanAdjudication]:
    result: dict[str, HumanAdjudication] = {}
    for item in adjudications:
        if item.blind_ref not in mapping_by_blind or item.blind_ref in result:
            raise LiveAbHarnessError("adjudication identity is unknown or duplicated")
        sources: list[HumanJudgment] = []
        for annotator in item.source_annotator_refs:
            source = judgments.get((item.blind_ref, annotator))
            if source is None:
                raise LiveAbHarnessError("adjudication source judgment is missing")
            sources.append(source)
        outcomes = {(source.editorial_pass, source.critical_defect_present) for source in sources}
        adjudicated = (item.editorial_pass, item.critical_defect_present)
        if item.method == "consensus" and (len(outcomes) != 1 or adjudicated not in outcomes):
            raise LiveAbHarnessError("consensus adjudication disagrees with its source judgments")
        if item.method == "single" and adjudicated not in outcomes:
            raise LiveAbHarnessError("single adjudication disagrees with its source judgment")
        result[item.blind_ref] = item
    return result


def _failure_taxonomy(
    plans: Sequence[object],
    observations: Mapping[AttemptKey, AttemptObservation],
) -> Counter[str]:
    taxonomy: Counter[str] = Counter()
    if len(observations) < len(plans):
        taxonomy["missing_attempt"] = len(plans) - len(observations)
    for item in observations.values():
        if item.status is not AttemptStatus.COMPLETED and item.failure_code is not None:
            taxonomy[f"attempt:{item.failure_code.value}"] += 1
        for call in item.provider_calls:
            if call.failure_code is not None:
                taxonomy[f"provider_call:{call.failure_code.value}"] += 1
    return taxonomy


def _complete_pairs(
    manifest: RunManifest,
    observations: Mapping[AttemptKey, AttemptObservation],
    mappings: Mapping[AttemptKey, BlindMapRow],
    adjudications: Mapping[str, HumanAdjudication],
) -> tuple[PairKey, ...]:
    pairs: list[PairKey] = []
    for case_id in manifest.selected_case_ids:
        for repetition in range(1, manifest.repetitions + 1):
            keys = tuple((case_id, repetition, arm) for arm in manifest.arms)
            if all(
                key in observations
                and observations[key].status is AttemptStatus.COMPLETED
                and key in mappings
                and mappings[key].blind_ref in adjudications
                for key in keys
            ):
                baseline_label = adjudications[mappings[keys[0]].blind_ref]
                treatment = observations[keys[1]]
                if (
                    treatment.revisions[0].artifact_sha256
                    != observations[keys[0]].revisions[0].artifact_sha256
                ):
                    raise LiveAbHarnessError("paired observations do not share revision 1")
                if not treatment.repair_performed:
                    treatment_label = adjudications[mappings[keys[1]].blind_ref]
                    if (
                        baseline_label.editorial_pass != treatment_label.editorial_pass
                        or baseline_label.critical_defect_present
                        != treatment_label.critical_defect_present
                    ):
                        raise LiveAbHarnessError(
                            "identical paired artifacts received inconsistent human gold"
                        )
                pairs.append((case_id, repetition))
    return tuple(pairs)


def _double_annotated_calibration_pairs(
    dataset: LoadedLiveAbDataset,
    mappings: Mapping[AttemptKey, BlindMapRow],
    judgments: Mapping[tuple[str, str], HumanJudgment],
    adjudications: Mapping[str, HumanAdjudication],
) -> tuple[PairKey, ...]:
    split_by_case = {case.case_id: case.split for case in dataset.cases}
    annotators_by_blind: dict[str, set[str]] = defaultdict(set)
    for blind_ref, annotator_ref in judgments:
        annotators_by_blind[blind_ref].add(annotator_ref)
    pair_keys = {(case_id, repetition) for case_id, repetition, _ in mappings}
    result: list[PairKey] = []
    for case_id, repetition in sorted(pair_keys):
        if split_by_case.get(case_id) != "calibration":
            continue
        keys = tuple(
            (case_id, repetition, arm) for arm in (ExperimentArm.BASELINE, ExperimentArm.TREATMENT)
        )
        if not all(key in mappings for key in keys):
            continue
        blind_refs = tuple(mappings[key].blind_ref for key in keys)
        if any(
            blind_ref not in adjudications or adjudications[blind_ref].method == "single"
            for blind_ref in blind_refs
        ):
            continue
        source_sets = tuple(
            set(adjudications[blind_ref].source_annotator_refs) for blind_ref in blind_refs
        )
        common_annotators = set.intersection(*source_sets)
        if any(
            not source_sets[index].issubset(annotators_by_blind[blind_ref])
            for index, blind_ref in enumerate(blind_refs)
        ):
            continue
        if len(common_annotators) >= 2:
            result.append((case_id, repetition))
    return tuple(result)


def _human_agreement(
    mappings: Mapping[AttemptKey, BlindMapRow],
    judgments: Mapping[tuple[str, str], HumanJudgment],
    adjudications: Mapping[str, HumanAdjudication],
    double_annotated_pairs: Sequence[PairKey],
) -> HumanAgreement:
    eligible_blind_refs = {
        mappings[(case_id, repetition, arm)].blind_ref
        for case_id, repetition in double_annotated_pairs
        for arm in (ExperimentArm.BASELINE, ExperimentArm.TREATMENT)
    }
    grouped: dict[str, list[HumanJudgment]] = defaultdict(list)
    for (blind_ref, annotator_ref), judgment in judgments.items():
        if (
            blind_ref in eligible_blind_refs
            and annotator_ref in adjudications[blind_ref].source_annotator_refs
        ):
            grouped[blind_ref].append(judgment)
    editorial_matches = 0
    critical_matches = 0
    comparisons = 0
    for group in grouped.values():
        if len(group) < 2:
            continue
        for index, left in enumerate(group):
            for right in group[index + 1 :]:
                comparisons += 1
                editorial_matches += left.editorial_pass == right.editorial_pass
                critical_matches += left.critical_defect_present == right.critical_defect_present
    return HumanAgreement(
        double_annotated_pair_count=len(double_annotated_pairs),
        judgment_count=sum(len(group) for group in grouped.values()),
        editorial_pairwise_agreement=_ratio(editorial_matches, comparisons),
        critical_pairwise_agreement=_ratio(critical_matches, comparisons),
    )


def _arm_metrics(
    arm: ExperimentArm,
    pairs: Sequence[PairKey],
    observations: Mapping[AttemptKey, AttemptObservation],
    mappings: Mapping[AttemptKey, BlindMapRow],
    adjudications: Mapping[str, HumanAdjudication],
    manifest: RunManifest,
) -> ArmMetrics:
    records: list[tuple[AttemptObservation, HumanAdjudication, HumanAdjudication]] = []
    for case_id, repetition in pairs:
        item = observations[(case_id, repetition, arm)]
        final_label = adjudications[mappings[(case_id, repetition, arm)].blind_ref]
        initial_label = adjudications[
            mappings[(case_id, repetition, ExperimentArm.BASELINE)].blind_ref
        ]
        records.append((item, initial_label, final_label))
    critical_records = tuple(record for record in records if record[1].critical_defect_present)
    false_accepts = sum(
        item.final_decision is ReviewOutcome.ACCEPTED and not final.editorial_pass
        for item, _, final in records
    )
    false_rejects = sum(
        item.final_decision is not ReviewOutcome.ACCEPTED and final.editorial_pass
        for item, _, final in records
    )
    calls = tuple(call for item, _, _ in records for call in item.provider_calls)
    gold_negative_count = sum(not final.editorial_pass for _, _, final in records)
    gold_positive_count = sum(final.editorial_pass for _, _, final in records)
    known_cost = sum(provider_call_cost_usd(call, manifest.pricing) or 0.0 for call in calls)
    usage_complete = all(call.usage is not None for call in calls)
    return ArmMetrics(
        arm=arm,
        evaluated_pair_count=len(records),
        editorial_pass_at_1=_mean(
            tuple(float(initial.editorial_pass) for _, initial, _ in records)
        ),
        editorial_pass_at_2=_mean(tuple(float(final.editorial_pass) for _, _, final in records)),
        critical_gold_count=len(critical_records),
        critical_detected_count=sum(
            bool(item.critical_defect_detected_on_initial) for item, _, _ in critical_records
        ),
        critical_defect_recall=_mean(
            tuple(
                float(bool(item.critical_defect_detected_on_initial))
                for item, _, _ in critical_records
            )
        ),
        gold_negative_count=gold_negative_count,
        false_accept_count=false_accepts,
        false_accept_rate=_ratio(false_accepts, gold_negative_count),
        gold_positive_count=gold_positive_count,
        false_reject_count=false_rejects,
        false_reject_rate=_ratio(false_rejects, gold_positive_count),
        manual_review_count=sum(
            item.final_decision is ReviewOutcome.MANUAL_REVIEW for item, _, _ in records
        ),
        manual_review_rate=_ratio(
            sum(item.final_decision is ReviewOutcome.MANUAL_REVIEW for item, _, _ in records),
            len(records),
        ),
        p50_latency_ms=_percentile(tuple(item.total_latency_ms for item, _, _ in records), 0.5),
        p95_latency_ms=_percentile(tuple(item.total_latency_ms for item, _, _ in records), 0.95),
        provider_call_count=len(calls),
        input_tokens=(
            sum(call.usage.input_tokens for call in calls if call.usage) if usage_complete else None
        ),
        output_tokens=(
            sum(call.usage.output_tokens for call in calls if call.usage)
            if usage_complete
            else None
        ),
        reasoning_tokens=(
            sum(call.usage.reasoning_tokens for call in calls if call.usage)
            if usage_complete
            else None
        ),
        unknown_usage_call_count=sum(call.usage is None for call in calls),
        known_cost_lower_bound_usd=round(known_cost, 8),
        estimated_cost_usd=round(known_cost, 8) if usage_complete else None,
    )


def _paired_estimates(
    manifest: RunManifest,
    pairs: Sequence[PairKey],
    observations: Mapping[AttemptKey, AttemptObservation],
    mappings: Mapping[AttemptKey, BlindMapRow],
    adjudications: Mapping[str, HumanAdjudication],
) -> tuple[PairedEstimate, ...]:
    pass_pairs: list[tuple[float, float, str, int]] = []
    recall_pairs: list[tuple[float, float, str, int]] = []
    for case_id, repetition in pairs:
        baseline_key = (case_id, repetition, ExperimentArm.BASELINE)
        treatment_key = (case_id, repetition, ExperimentArm.TREATMENT)
        baseline_label = adjudications[mappings[baseline_key].blind_ref]
        treatment_label = adjudications[mappings[treatment_key].blind_ref]
        pass_pairs.append(
            (
                float(baseline_label.editorial_pass),
                float(treatment_label.editorial_pass),
                case_id,
                repetition,
            )
        )
        if baseline_label.critical_defect_present:
            recall_pairs.append(
                (
                    float(bool(observations[baseline_key].critical_defect_detected_on_initial)),
                    float(bool(observations[treatment_key].critical_defect_detected_on_initial)),
                    case_id,
                    repetition,
                )
            )
    estimates = [
        _paired_estimate(
            "editorial_pass_at_2",
            pass_pairs,
            samples=manifest.bootstrap_samples,
            seed=manifest.bootstrap_seed,
        )
    ]
    if len({item[2] for item in recall_pairs}) >= 2:
        estimates.append(
            _paired_estimate(
                "critical_defect_recall",
                recall_pairs,
                samples=manifest.bootstrap_samples,
                seed=manifest.bootstrap_seed + 1,
            )
        )
    return tuple(estimates)


def _paired_estimate(
    metric: Literal["editorial_pass_at_2", "critical_defect_recall"],
    values: Sequence[tuple[float, float, str, int]],
    *,
    samples: int,
    seed: int,
) -> PairedEstimate:
    baseline = tuple(item[0] for item in values)
    treatment = tuple(item[1] for item in values)
    deltas = tuple(right - left for left, right in zip(baseline, treatment, strict=True))
    deltas_by_case: dict[str, list[float]] = defaultdict(list)
    for left, right, case_id, _ in values:
        deltas_by_case[case_id].append(right - left)
    case_means = tuple(sum(group) / len(group) for _, group in sorted(deltas_by_case.items()))
    generator = random.Random(seed)
    bootstrapped = sorted(
        sum(case_means[generator.randrange(len(case_means))] for _ in case_means) / len(case_means)
        for _ in range(samples)
    )
    repetition_values: dict[int, list[float]] = defaultdict(list)
    for left, right, _, repetition in values:
        repetition_values[repetition].append(right - left)
    repetition_means = [sum(group) / len(group) for group in repetition_values.values()]
    return PairedEstimate(
        metric=metric,
        pair_count=len(values),
        baseline_mean=sum(baseline) / len(baseline),
        treatment_mean=sum(treatment) / len(treatment),
        treatment_minus_baseline=sum(deltas) / len(deltas),
        ci_lower=_sorted_percentile(bootstrapped, 0.025),
        ci_upper=_sorted_percentile(bootstrapped, 0.975),
        bootstrap_samples=samples,
        bootstrap_seed=seed,
        repetition_delta_variance=(
            variance(repetition_means) if len(repetition_means) >= 2 else None
        ),
    )


def _bad_cases(
    pairs: Sequence[PairKey],
    observations: Mapping[AttemptKey, AttemptObservation],
    mappings: Mapping[AttemptKey, BlindMapRow],
    adjudications: Mapping[str, HumanAdjudication],
) -> tuple[BadCase, ...]:
    result: list[BadCase] = []
    for case_id, repetition in pairs:
        for arm in (ExperimentArm.BASELINE, ExperimentArm.TREATMENT):
            key = (case_id, repetition, arm)
            item = observations[key]
            label = adjudications[mappings[key].blind_ref]
            reasons: list[str] = []
            if item.final_decision is ReviewOutcome.ACCEPTED and not label.editorial_pass:
                reasons.append("false_accept")
            if item.final_decision is not ReviewOutcome.ACCEPTED and label.editorial_pass:
                reasons.append("false_reject")
            if arm is ExperimentArm.TREATMENT:
                baseline_label = adjudications[
                    mappings[(case_id, repetition, ExperimentArm.BASELINE)].blind_ref
                ]
                if baseline_label.editorial_pass and not label.editorial_pass:
                    reasons.append("treatment_regression")
            if reasons:
                result.append(
                    BadCase(
                        pair_ref=f"pair:{case_id}:{repetition}",
                        arm=arm,
                        reason_codes=tuple(reasons),
                    )
                )
    return tuple(result)


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _mean(values: Sequence[float]) -> float | None:
    return round(sum(values) / len(values), 6) if values else None


def _percentile(values: Sequence[int], quantile: float) -> float | None:
    if not values:
        return None
    return _sorted_percentile(sorted(float(value) for value in values), quantile)


def _difference(
    right: float | None,
    left: float | None,
    *,
    digits: int = 4,
) -> float | None:
    if right is None or left is None:
        return None
    return round(right - left, digits)


def _sorted_percentile(values: Sequence[float], quantile: float) -> float:
    if len(values) == 1:
        return values[0]
    position = (len(values) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(values) - 1)
    fraction = position - lower
    return values[lower] * (1 - fraction) + values[upper] * fraction
