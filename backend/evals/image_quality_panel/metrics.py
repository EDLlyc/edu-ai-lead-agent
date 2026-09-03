"""Objective gold metrics and unlabeled single-model stability metrics."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from decimal import Decimal
from statistics import median
from typing import Literal, Self

from app.domain.image_quality_eval import ImageEvalDimension
from pydantic import BaseModel, ConfigDict, Field, model_validator

from evals.model_panel import (
    ArmDecision,
    AttemptStatus,
    OrderControlledVote,
    OrderControlStatus,
    PanelAttempt,
    PanelAuthorization,
    PanelManifest,
    PresentationOrder,
    VoteProfile,
    evidence_sha256,
    repeat_is_consistent,
    require_privacy_safe,
    resolve_order_control,
)
from evals.model_panel.privacy import PrivacyProfile

from .dataset import LoadedImagePanelDataset, repeat_case_refs
from .models import (
    IMAGE_EVALUATOR_MODEL_SPEC,
    IMAGE_PANEL_REPORT_DISCLAIMER,
    DatasetSplit,
    GoldKind,
    ImagePanelCase,
    Sha256Hex,
)


class ReportModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class ConfusionCounts(ReportModel):
    gold_accept_predicted_accept: int = Field(ge=0)
    gold_accept_predicted_reject: int = Field(ge=0)
    gold_accept_unresolved: int = Field(ge=0)
    gold_reject_predicted_accept: int = Field(ge=0)
    gold_reject_predicted_reject: int = Field(ge=0)
    gold_reject_unresolved: int = Field(ge=0)


class ObjectiveScore(ReportModel):
    case_count: int = Field(ge=0)
    effective_source_cluster_n: int = Field(ge=0, le=6)
    eligible_case_count: int = Field(ge=0)
    pair_correct_count: int = Field(ge=0)
    pair_accuracy: float = Field(ge=0, le=1)
    arm_count: int = Field(ge=0)
    arm_decision_macro_f1: float = Field(ge=0, le=1)
    critical_gold_count: int = Field(ge=0)
    critical_non_gold_count: int = Field(ge=0)
    critical_false_accept_count: int = Field(ge=0)
    critical_false_accept_rate: float = Field(ge=0, le=1)
    acceptable_false_reject_count: int = Field(ge=0)
    acceptable_false_reject_rate: float = Field(ge=0, le=1)
    critical_flag_false_positive_count: int = Field(ge=0)
    critical_flag_false_positive_rate: float = Field(ge=0, le=1)
    critical_flag_false_negative_count: int = Field(ge=0)
    critical_flag_false_negative_rate: float = Field(ge=0, le=1)
    confusion: ConfusionCounts
    bad_case_aliases: tuple[str, ...]


class DimensionObjectiveScore(ReportModel):
    dimension: ImageEvalDimension
    score: ObjectiveScore


class SplitObjectiveScore(ReportModel):
    split: DatasetSplit
    score: ObjectiveScore


class SubjectiveStabilityScore(ReportModel):
    case_count: int = Field(ge=0)
    effective_source_cluster_n: int = Field(ge=0, le=6)
    eligible_case_count: int = Field(ge=0)
    coverage: float = Field(ge=0, le=1)
    position_consistent_count: int = Field(ge=0)
    position_stability: float = Field(ge=0, le=1)
    abstention_count: int = Field(ge=0)
    abstention_rate: float = Field(ge=0, le=1)
    position_conflict_count: int = Field(ge=0)
    position_conflict_rate: float = Field(ge=0, le=1)
    incomplete_count: int = Field(ge=0)
    repeat_pair_count: int = Field(ge=0)
    repeat_eligible_count: int = Field(ge=0)
    repeat_consistent_count: int = Field(ge=0)
    repeat_consistency: float = Field(ge=0, le=1)
    bad_case_aliases: tuple[str, ...]


class SplitSubjectiveStabilityScore(ReportModel):
    split: DatasetSplit
    score: SubjectiveStabilityScore


class ExecutionScore(ReportModel):
    expected_call_count: int = Field(ge=1)
    observed_attempt_count: int = Field(ge=0)
    completed_attempt_count: int = Field(ge=0)
    failed_attempt_count: int = Field(ge=0)
    position_conflict_count: int = Field(ge=0)
    incomplete_cell_count: int = Field(ge=0)
    primary_order_consistent_count: int = Field(ge=0)
    repeat_pair_count: int = Field(ge=0)
    repeat_consistent_count: int = Field(ge=0)
    repeat_consistency: float = Field(ge=0, le=1)
    latency_p50_ms: float | None = Field(default=None, ge=0)
    latency_p95_ms: float | None = Field(default=None, ge=0)
    known_usage_count: int = Field(ge=0)
    unknown_usage_count: int = Field(ge=0)
    input_tokens_known: int = Field(ge=0)
    output_tokens_known: int = Field(ge=0)
    native_cost_unit: str | None = None
    native_cost_known: Decimal | None = Field(default=None, ge=0)


class EvaluatorScore(ReportModel):
    evaluator_model_ref: str
    objective: ObjectiveScore
    objective_by_dimension: tuple[DimensionObjectiveScore, ...]
    objective_by_split: tuple[SplitObjectiveScore, ...]
    subjective_stability: SubjectiveStabilityScore
    subjective_stability_by_split: tuple[SplitSubjectiveStabilityScore, ...]
    execution: ExecutionScore


class ImagePanelReport(ReportModel):
    schema_version: Literal["image-single-model-report-v1"] = "image-single-model-report-v1"
    track: Literal["image_quality_single_model_eval"] = "image_quality_single_model_eval"
    gold_kind: Literal["objective_recipe_only"] = "objective_recipe_only"
    disclaimer: str = IMAGE_PANEL_REPORT_DISCLAIMER
    human_labels: Literal[0] = 0
    external_label_n: Literal[0] = 0
    single_model_only: Literal[True] = True
    enforce_eligible: Literal[False] = False
    production_mode_changed: Literal[False] = False
    dataset_version: str
    dataset_sha256: Sha256Hex
    manifest_sha256: Sha256Hex
    authorization_sha256: Sha256Hex
    case_n: Literal[48] = 48
    effective_source_cluster_n: Literal[6] = 6
    calibration_case_n: Literal[24] = 24
    holdout_case_n: Literal[24] = 24
    evaluator: EvaluatorScore
    report_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_report_hash(self) -> Self:
        payload = self.model_dump(mode="json", exclude={"report_sha256"})
        if evidence_sha256(payload) != self.report_sha256:
            raise ValueError("image panel report SHA-256 does not match its payload")
        return self


class NonActivatingCandidateArtifact(ReportModel):
    schema_version: Literal["image-panel-candidate-artifact-v2"] = (
        "image-panel-candidate-artifact-v2"
    )
    report_sha256: Sha256Hex
    observed_model_refs: tuple[str, ...]
    human_labels: Literal[0] = 0
    external_label_n: Literal[0] = 0
    single_model_only: Literal[True] = True
    selection_recommendation: Literal[False] = False
    non_activating: Literal[True] = True
    enforce_eligible: Literal[False] = False
    production_model_changed: Literal[False] = False
    artifact_sha256: Sha256Hex

    @model_validator(mode="after")
    def validate_artifact_hash(self) -> Self:
        payload = self.model_dump(mode="json", exclude={"artifact_sha256"})
        if evidence_sha256(payload) != self.artifact_sha256:
            raise ValueError("candidate artifact SHA-256 does not match its payload")
        return self


def build_order_controlled_votes(
    *,
    dataset: LoadedImagePanelDataset,
    model_refs: Sequence[str],
    attempts: Sequence[PanelAttempt],
) -> tuple[OrderControlledVote, ...]:
    votes_by_cell = {
        (
            attempt.evaluator_model_ref,
            attempt.case_ref,
            attempt.repeat_index,
            attempt.presentation_order,
        ): attempt.vote
        for attempt in attempts
        if attempt.vote is not None
    }
    repeat_refs = frozenset(repeat_case_refs(dataset.cases))
    results: list[OrderControlledVote] = []
    for model_ref in sorted(set(model_refs)):
        for case in dataset.cases:
            repeat_indexes = (0, 1) if case.case_ref in repeat_refs else (0,)
            for repeat_index in repeat_indexes:
                results.append(
                    resolve_order_control(
                        evaluator_model_ref=model_ref,
                        pair_ref=case.pair_ref,
                        case_ref=case.case_ref,
                        repeat_index=repeat_index,
                        vote_profile=VoteProfile.IMAGE_PAIR_ARM_VERDICT,
                        ab_vote=votes_by_cell.get(
                            (model_ref, case.case_ref, repeat_index, PresentationOrder.AB)
                        ),
                        ba_vote=votes_by_cell.get(
                            (model_ref, case.case_ref, repeat_index, PresentationOrder.BA)
                        ),
                    )
                )
    return tuple(results)


def build_report(
    *,
    dataset: LoadedImagePanelDataset,
    manifest: PanelManifest,
    authorization: PanelAuthorization,
    evaluator_model_ref: str,
    attempts: Sequence[PanelAttempt],
) -> ImagePanelReport:
    if evaluator_model_ref != IMAGE_EVALUATOR_MODEL_SPEC.model_ref:
        raise ValueError("report requires the unique frozen GLM-5V-Turbo identity")
    all_refs = (evaluator_model_ref,)
    _validate_manifest_evidence(dataset=dataset, manifest=manifest)
    if (
        authorization.manifest_sha256 != manifest.manifest_sha256
        or authorization.total_request_limit != manifest.total_request_limit
        or authorization.model_request_limits != manifest.model_request_limits
        or authorization.provider_native_limits != manifest.provider_native_limits
    ):
        raise ValueError("authorization is not bound to the frozen image-panel manifest")
    _validate_attempt_evidence(
        cases=dataset.cases,
        model_refs=all_refs,
        attempts=attempts,
        manifest=manifest,
        authorization_sha256=authorization.authorization_sha256,
    )
    order_votes = build_order_controlled_votes(
        dataset=dataset,
        model_refs=all_refs,
        attempts=attempts,
    )
    primary_by_case_model = {
        (vote.case_ref, vote.evaluator_model_ref): vote
        for vote in order_votes
        if vote.repeat_index == 0
    }
    subjective_cases = tuple(
        case for case in dataset.cases if case.gold_kind is GoldKind.SUBJECTIVE_UNLABELED
    )
    score = EvaluatorScore(
        evaluator_model_ref=evaluator_model_ref,
        objective=_objective_score(dataset.cases, primary_by_case_model, evaluator_model_ref),
        objective_by_dimension=tuple(
            DimensionObjectiveScore(
                dimension=dimension,
                score=_objective_score(
                    tuple(case for case in dataset.cases if case.dimension is dimension),
                    primary_by_case_model,
                    evaluator_model_ref,
                ),
            )
            for dimension in ImageEvalDimension
        ),
        objective_by_split=tuple(
            SplitObjectiveScore(
                split=split,
                score=_objective_score(
                    tuple(case for case in dataset.cases if case.split is split),
                    primary_by_case_model,
                    evaluator_model_ref,
                ),
            )
            for split in DatasetSplit
        ),
        subjective_stability=_subjective_stability_score(
            cases=subjective_cases,
            order_votes=order_votes,
            model_ref=evaluator_model_ref,
        ),
        subjective_stability_by_split=tuple(
            SplitSubjectiveStabilityScore(
                split=split,
                score=_subjective_stability_score(
                    cases=tuple(case for case in subjective_cases if case.split is split),
                    order_votes=order_votes,
                    model_ref=evaluator_model_ref,
                ),
            )
            for split in DatasetSplit
        ),
        execution=_execution_score(
            model_ref=evaluator_model_ref,
            cases=dataset.cases,
            attempts=attempts,
            order_votes=order_votes,
        ),
    )
    payload: dict[str, object] = {
        "schema_version": "image-single-model-report-v1",
        "track": "image_quality_single_model_eval",
        "gold_kind": "objective_recipe_only",
        "disclaimer": IMAGE_PANEL_REPORT_DISCLAIMER,
        "human_labels": 0,
        "external_label_n": 0,
        "single_model_only": True,
        "enforce_eligible": False,
        "production_mode_changed": False,
        "dataset_version": dataset.dataset_version,
        "dataset_sha256": dataset.dataset_sha256,
        "manifest_sha256": manifest.manifest_sha256,
        "authorization_sha256": authorization.authorization_sha256,
        "case_n": 48,
        "effective_source_cluster_n": 6,
        "calibration_case_n": 24,
        "holdout_case_n": 24,
        "evaluator": score,
    }
    payload["report_sha256"] = evidence_sha256(payload)
    report = ImagePanelReport.model_validate(payload)
    require_privacy_safe(report, profile=PrivacyProfile.SAFE_REPORT)
    return report


def build_candidate_artifact(report: ImagePanelReport) -> NonActivatingCandidateArtifact:
    payload: dict[str, object] = {
        "schema_version": "image-panel-candidate-artifact-v2",
        "report_sha256": report.report_sha256,
        "observed_model_refs": (report.evaluator.evaluator_model_ref,),
        "human_labels": 0,
        "external_label_n": 0,
        "single_model_only": True,
        "selection_recommendation": False,
        "non_activating": True,
        "enforce_eligible": False,
        "production_model_changed": False,
    }
    payload["artifact_sha256"] = evidence_sha256(payload)
    artifact = NonActivatingCandidateArtifact.model_validate(payload)
    require_privacy_safe(artifact, profile=PrivacyProfile.SAFE_REPORT)
    return artifact


def _validate_attempt_evidence(
    *,
    cases: Sequence[ImagePanelCase],
    model_refs: Sequence[str],
    attempts: Sequence[PanelAttempt],
    manifest: PanelManifest,
    authorization_sha256: str,
) -> None:
    case_by_ref = {case.case_ref: case for case in cases}
    repeat_refs = frozenset(repeat_case_refs(tuple(cases)))
    allowed_models = frozenset(model_refs)
    identity_by_ref = {identity.identity_ref: identity for identity in manifest.identities}
    binding_by_ref = {binding.attempt_ref: binding for binding in manifest.attempt_bindings}
    seen: set[tuple[str, str, int, PresentationOrder]] = set()
    for attempt in attempts:
        key = (
            attempt.evaluator_model_ref,
            attempt.case_ref,
            attempt.repeat_index,
            attempt.presentation_order,
        )
        case = case_by_ref.get(attempt.case_ref)
        binding = binding_by_ref.get(attempt.attempt_ref)
        if (
            attempt.run_ref != manifest.run_ref
            or attempt.manifest_sha256 != manifest.manifest_sha256
            or attempt.authorization_sha256 != authorization_sha256
            or attempt.evaluator_model_ref not in allowed_models
            or case is None
            or attempt.pair_ref != case.pair_ref
            or attempt.repeat_index not in {0, 1}
            or (attempt.repeat_index == 1 and attempt.case_ref not in repeat_refs)
            or attempt.status is AttemptStatus.STARTED
        ):
            raise ValueError("attempt evidence is outside the frozen image-panel plan")
        if binding is None or (
            binding.pair_ref,
            binding.case_ref,
            binding.evaluator_model_ref,
            binding.presentation_order,
            binding.repeat_index,
            binding.request_fingerprint,
        ) != (
            attempt.pair_ref,
            attempt.case_ref,
            attempt.evaluator_model_ref,
            attempt.presentation_order,
            attempt.repeat_index,
            attempt.request_fingerprint,
        ):
            raise ValueError("attempt evidence is not bound to a frozen manifest attempt")
        if attempt.identity is not None and (
            attempt.identity != identity_by_ref[attempt.evaluator_model_ref]
        ):
            raise ValueError("attempt returned identity differs from the frozen manifest")
        if key in seen:
            raise ValueError("attempt evidence contains a duplicate AB/BA cell")
        seen.add(key)
    for model_ref in allowed_models:
        planned = tuple(
            binding.attempt_ref
            for binding in manifest.attempt_bindings
            if binding.evaluator_model_ref == model_ref
        )
        observed = tuple(
            attempt.attempt_ref for attempt in attempts if attempt.evaluator_model_ref == model_ref
        )
        if observed != planned[: len(observed)]:
            raise ValueError("attempt evidence for each model must be a plan prefix")
        if observed:
            first = next(
                attempt
                for attempt in attempts
                if attempt.evaluator_model_ref == model_ref and attempt.attempt_ref == planned[0]
            )
            if first.status is not AttemptStatus.COMPLETED and len(observed) != 1:
                raise ValueError("a failed capability gate must stop that model plan")


def _validate_manifest_evidence(
    *,
    dataset: LoadedImagePanelDataset,
    manifest: PanelManifest,
) -> None:
    expected_identities = {
        spec.model_ref: (spec.requested_model, spec.gateway, spec.provider)
        for spec in (IMAGE_EVALUATOR_MODEL_SPEC,)
    }
    actual_identities = {
        identity.identity_ref: (
            identity.requested_model,
            identity.gateway,
            identity.provider,
        )
        for identity in manifest.identities
    }
    binding_counts = Counter(binding.evaluator_model_ref for binding in manifest.attempt_bindings)
    if (
        manifest.track != "image-quality-single-model-eval"
        or manifest.dataset_version != dataset.dataset_version
        or manifest.dataset_sha256 != dataset.dataset_sha256
        or actual_identities != expected_identities
        or manifest.total_request_limit != 120
        or set(binding_counts.values()) != {120}
        or len(binding_counts) != 1
    ):
        raise ValueError("manifest is not the frozen 120-call image evaluation")
    case_by_ref = {case.case_ref: case for case in dataset.cases}
    repeat_refs = frozenset(repeat_case_refs(dataset.cases))
    expected_cells = tuple(
        (case.case_ref, repeat_index, order)
        for repeat_index in (0, 1)
        for case in dataset.cases
        if repeat_index == 0 or case.case_ref in repeat_refs
        for order in (PresentationOrder.AB, PresentationOrder.BA)
    )
    for model_ref in expected_identities:
        bindings = tuple(
            binding
            for binding in manifest.attempt_bindings
            if binding.evaluator_model_ref == model_ref
        )
        actual_cells = tuple(
            (binding.case_ref, binding.repeat_index, binding.presentation_order)
            for binding in bindings
        )
        if actual_cells != expected_cells or any(
            binding.pair_ref != case_by_ref[binding.case_ref].pair_ref
            or binding.target_model_ref is not None
            or binding.max_input_tokens != 32_768
            or binding.max_output_tokens != 512
            for binding in bindings
        ):
            raise ValueError("manifest attempt cells differ from the frozen image dataset")


def _objective_score(
    cases: Sequence[ImagePanelCase],
    votes: Mapping[tuple[str, str], OrderControlledVote],
    model_ref: str,
) -> ObjectiveScore:
    objective = tuple(case for case in cases if case.gold_kind is GoldKind.OBJECTIVE_RECIPE)
    pair_correct = 0
    eligible = 0
    confusion: Counter[tuple[str, str]] = Counter()
    critical_gold = 0
    critical_non_gold = 0
    false_accepts = 0
    false_rejects = 0
    critical_flag_false_positives = 0
    critical_flag_false_negatives = 0
    bad: set[str] = set()
    for case in objective:
        vote = votes[(case.case_ref, model_ref)]
        if vote.status is OrderControlStatus.CONSISTENT:
            eligible += 1
            if vote.canonical_choice is case.gold_choice:
                pair_correct += 1
            else:
                bad.add(case.case_ref)
        else:
            bad.add(case.case_ref)
        for gold, predicted in (
            (case.gold_first_verdict, vote.canonical_first_verdict),
            (case.gold_second_verdict, vote.canonical_second_verdict),
        ):
            if gold is None:
                raise ValueError("objective case is missing an arm gold verdict")
            gold_label = gold.decision.value
            predicted_label = predicted.decision.value if predicted is not None else "unresolved"
            confusion[(gold_label, predicted_label)] += 1
            if gold.critical:
                critical_gold += 1
                if predicted is not None and predicted.decision is ArmDecision.ACCEPT:
                    false_accepts += 1
                    bad.add(case.case_ref)
                if predicted is None or predicted.critical is not True:
                    critical_flag_false_negatives += 1
                    bad.add(case.case_ref)
            else:
                critical_non_gold += 1
                if predicted is not None and predicted.decision is ArmDecision.REJECT:
                    false_rejects += 1
                    bad.add(case.case_ref)
                if predicted is not None and predicted.critical is True:
                    critical_flag_false_positives += 1
                    bad.add(case.case_ref)
    accepted_f1 = _label_f1(confusion, ArmDecision.ACCEPT.value)
    rejected_f1 = _label_f1(confusion, ArmDecision.REJECT.value)
    return ObjectiveScore(
        case_count=len(objective),
        effective_source_cluster_n=len(
            {family for case in objective for family in case.source_families}
        ),
        eligible_case_count=eligible,
        pair_correct_count=pair_correct,
        pair_accuracy=_ratio(pair_correct, len(objective)),
        arm_count=len(objective) * 2,
        arm_decision_macro_f1=(accepted_f1 + rejected_f1) / 2,
        critical_gold_count=critical_gold,
        critical_non_gold_count=critical_non_gold,
        critical_false_accept_count=false_accepts,
        critical_false_accept_rate=_ratio(false_accepts, critical_gold),
        acceptable_false_reject_count=false_rejects,
        acceptable_false_reject_rate=_ratio(false_rejects, critical_non_gold),
        critical_flag_false_positive_count=critical_flag_false_positives,
        critical_flag_false_positive_rate=_ratio(
            critical_flag_false_positives,
            critical_non_gold,
        ),
        critical_flag_false_negative_count=critical_flag_false_negatives,
        critical_flag_false_negative_rate=_ratio(
            critical_flag_false_negatives,
            critical_gold,
        ),
        confusion=ConfusionCounts(
            gold_accept_predicted_accept=confusion[("accept", "accept")],
            gold_accept_predicted_reject=confusion[("accept", "reject")],
            gold_accept_unresolved=sum(
                count
                for (gold, predicted), count in confusion.items()
                if gold == "accept" and predicted not in {"accept", "reject"}
            ),
            gold_reject_predicted_accept=confusion[("reject", "accept")],
            gold_reject_predicted_reject=confusion[("reject", "reject")],
            gold_reject_unresolved=sum(
                count
                for (gold, predicted), count in confusion.items()
                if gold == "reject" and predicted not in {"accept", "reject"}
            ),
        ),
        bad_case_aliases=tuple(sorted(bad)),
    )


def _subjective_stability_score(
    *,
    cases: Sequence[ImagePanelCase],
    order_votes: Sequence[OrderControlledVote],
    model_ref: str,
) -> SubjectiveStabilityScore:
    """Measure one evaluator against itself; subjective cases have no correctness label."""

    case_refs = {case.case_ref for case in cases}
    primary = {
        vote.case_ref: vote
        for vote in order_votes
        if vote.evaluator_model_ref == model_ref
        and vote.case_ref in case_refs
        and vote.repeat_index == 0
    }
    repeated = {
        vote.case_ref: vote
        for vote in order_votes
        if vote.evaluator_model_ref == model_ref
        and vote.case_ref in case_refs
        and vote.repeat_index == 1
    }
    if set(primary) != case_refs or set(repeated) != case_refs:
        raise ValueError("every subjective case requires primary and repeat AB/BA cells")
    eligible = sum(vote.status is OrderControlStatus.CONSISTENT for vote in primary.values())
    abstentions = sum(vote.status is OrderControlStatus.ABSTAINED for vote in primary.values())
    conflicts = sum(
        vote.status is OrderControlStatus.POSITION_CONFLICT for vote in primary.values()
    )
    incomplete = sum(vote.status is OrderControlStatus.INCOMPLETE for vote in primary.values())
    repeat_eligible = sum(
        primary[case_ref].status is OrderControlStatus.CONSISTENT
        and repeated[case_ref].status is OrderControlStatus.CONSISTENT
        for case_ref in case_refs
    )
    repeat_matches = sum(
        repeat_is_consistent(primary[case_ref], repeated[case_ref]) for case_ref in case_refs
    )
    bad = tuple(
        sorted(
            case_ref
            for case_ref in case_refs
            if primary[case_ref].status is not OrderControlStatus.CONSISTENT
            or not repeat_is_consistent(primary[case_ref], repeated[case_ref])
        )
    )
    return SubjectiveStabilityScore(
        case_count=len(cases),
        effective_source_cluster_n=len(
            {family for case in cases for family in case.source_families}
        ),
        eligible_case_count=eligible,
        coverage=_ratio(eligible, len(cases)),
        position_consistent_count=eligible,
        position_stability=_ratio(eligible, len(cases)),
        abstention_count=abstentions,
        abstention_rate=_ratio(abstentions, len(cases)),
        position_conflict_count=conflicts,
        position_conflict_rate=_ratio(conflicts, len(cases)),
        incomplete_count=incomplete,
        repeat_pair_count=len(cases),
        repeat_eligible_count=repeat_eligible,
        repeat_consistent_count=repeat_matches,
        repeat_consistency=_ratio(repeat_matches, len(cases)),
        bad_case_aliases=bad,
    )


def _execution_score(
    *,
    model_ref: str,
    cases: Sequence[ImagePanelCase],
    attempts: Sequence[PanelAttempt],
    order_votes: Sequence[OrderControlledVote],
) -> ExecutionScore:
    model_attempts = tuple(item for item in attempts if item.evaluator_model_ref == model_ref)
    model_votes = tuple(item for item in order_votes if item.evaluator_model_ref == model_ref)
    primary = tuple(item for item in model_votes if item.repeat_index == 0)
    repeated = {item.case_ref: item for item in model_votes if item.repeat_index == 1}
    initial = {item.case_ref: item for item in primary}
    repeat_refs = repeat_case_refs(tuple(cases))
    repeat_matches = sum(
        repeat_is_consistent(initial[case_ref], repeated[case_ref]) for case_ref in repeat_refs
    )
    latencies = sorted(
        float(item.latency_ms) for item in model_attempts if item.latency_ms is not None
    )
    usage = tuple(item.usage for item in model_attempts if item.usage is not None)
    known = tuple(item for item in usage if item.fully_known)
    units = {item.native_cost.unit for item in known if item.native_cost is not None}
    native_cost = (
        sum((item.native_cost.amount for item in known if item.native_cost is not None), Decimal(0))
        if len(units) == 1
        else None
    )
    return ExecutionScore(
        expected_call_count=120,
        observed_attempt_count=len(model_attempts),
        completed_attempt_count=sum(item.vote is not None for item in model_attempts),
        failed_attempt_count=sum(item.vote is None for item in model_attempts),
        position_conflict_count=sum(
            item.status is OrderControlStatus.POSITION_CONFLICT for item in model_votes
        ),
        incomplete_cell_count=sum(
            item.status is OrderControlStatus.INCOMPLETE for item in model_votes
        ),
        primary_order_consistent_count=sum(
            item.status is OrderControlStatus.CONSISTENT for item in primary
        ),
        repeat_pair_count=len(repeat_refs),
        repeat_consistent_count=repeat_matches,
        repeat_consistency=_ratio(repeat_matches, len(repeat_refs)),
        latency_p50_ms=median(latencies) if latencies else None,
        latency_p95_ms=_percentile(latencies, 0.95) if latencies else None,
        known_usage_count=len(known),
        unknown_usage_count=len(model_attempts) - len(known),
        input_tokens_known=sum(item.input_tokens or 0 for item in known),
        output_tokens_known=sum(item.output_tokens or 0 for item in known),
        native_cost_unit=next(iter(units)) if len(units) == 1 else None,
        native_cost_known=native_cost,
    )


def _label_f1(confusion: Mapping[tuple[str, str], int], label: str) -> float:
    true_positive = confusion[(label, label)]
    false_positive = sum(
        count
        for (gold, predicted), count in confusion.items()
        if gold != label and predicted == label
    )
    false_negative = sum(
        count
        for (gold, predicted), count in confusion.items()
        if gold == label and predicted != label
    )
    precision = _ratio(true_positive, true_positive + false_positive)
    recall = _ratio(true_positive, true_positive + false_negative)
    return 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)


def _percentile(values: Sequence[float], quantile: float) -> float:
    if not values:
        raise ValueError("percentile requires observations")
    position = (len(values) - 1) * quantile
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return values[lower]
    return values[lower] + (values[upper] - values[lower]) * (position - lower)


def _ratio(numerator: int, denominator: int) -> float:
    return numerator / denominator if denominator else 0.0
