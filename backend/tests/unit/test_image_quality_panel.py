from __future__ import annotations

import json
import stat
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
from pathlib import Path

import pytest
from app.core.config import Settings
from app.domain.image_quality_eval import ImageEvalDimension
from evals.image_quality_panel.dataset import build_image_panel_dataset, repeat_case_refs
from evals.image_quality_panel.execution import execute_image_plan
from evals.image_quality_panel.metrics import build_candidate_artifact, build_report
from evals.image_quality_panel.models import (
    ALL_MODEL_SPECS,
    IMAGE_EVALUATOR_MODEL_SPEC,
    IMAGE_PANEL_PROMPT_VERSION,
    DatasetSplit,
    GoldKind,
    SourceCatalog,
)
from evals.image_quality_panel.planning import (
    CALLS_PER_MODEL,
    TOTAL_CALL_CEILING,
    ImageExperimentPlan,
    bind_authorization,
    build_experiment_plan,
    issue_authorization,
)
from evals.image_quality_panel.sources import (
    DEFAULT_SOURCE_CATALOG,
    ImagePanelSourceError,
    load_source_catalog,
    preflight_sources,
)
from evals.model_panel import (
    MODEL_PANEL_AUTHORIZATION_ACKNOWLEDGEMENT,
    ArmDecision,
    ArmVerdict,
    AttemptStatus,
    CanonicalChoice,
    JudgeVote,
    NativeCost,
    PanelAttempt,
    PanelFailureCode,
    PanelModelIdentity,
    PresentationOrder,
    PresentedChoice,
    ProviderNativeLimit,
    ProviderUsage,
    VoteProfile,
    build_pairwise_user_prompt,
)
from evals.model_panel.models import PresentedArtifactGroup
from pydantic import ValidationError

NOW = datetime(2026, 9, 3, 1, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def image_dataset(tmp_path_factory: pytest.TempPathFactory):
    directory = tmp_path_factory.mktemp("image-panel")
    directory.chmod(0o700)
    return build_image_panel_dataset(artifact_directory=directory)


@pytest.fixture(scope="module")
def image_plan(image_dataset) -> ImageExperimentPlan:
    identities = tuple(_identity(spec) for spec in ALL_MODEL_SPECS)
    return build_experiment_plan(
        dataset=image_dataset,
        run_ref="image-panel-run-1",
        blind_key=b"deterministic-test-blind-key-32-bytes!!",
        identities=identities,
        provider_limits=(
            ProviderNativeLimit(
                provider_ref="zhipu",
                unit="cny",
                maximum=Decimal("100"),
            ),
        ),
        maximum_native_cost_by_model={spec.model_ref: Decimal("1") for spec in ALL_MODEL_SPECS},
        git_sha="a" * 40,
        created_at=NOW,
        execution_window_start=NOW,
        execution_window_end=NOW + timedelta(days=1),
    )


@pytest.fixture(scope="module")
def authorized_image_plan(image_plan: ImageExperimentPlan):
    authorization = issue_authorization(
        manifest=image_plan.manifest,
        valid_from=NOW,
        valid_until=NOW + timedelta(hours=1),
        approved_by_ref="owner",
        acknowledgement=MODEL_PANEL_AUTHORIZATION_ACKNOWLEDGEMENT,
    )
    return bind_authorization(image_plan, authorization, now=NOW), authorization


def test_source_catalog_and_dataset_preserve_six_family_validity(image_dataset) -> None:
    catalog = load_source_catalog()
    preflight_sources(catalog)

    assert len(catalog.sources) == 6
    assert len({source.source_family for source in catalog.sources}) == 6
    assert len(catalog.derivatives) == 4
    assert all(derivative.derivative_of for derivative in catalog.derivatives)
    assert image_dataset.case_n == 48
    assert image_dataset.effective_source_cluster_n == 6
    assert (
        image_dataset.source_catalog_sha256
        == sha256(DEFAULT_SOURCE_CATALOG.read_bytes()).hexdigest()
    )
    assert len(image_dataset.artifact_paths) == 120
    assert all(
        stat.S_IMODE(path.stat().st_mode) == 0o600 for path in image_dataset.artifact_paths.values()
    )
    assert image_dataset.cases[0].capability_gate is True
    assert image_dataset.cases[0].dimension is ImageEvalDimension.BATCH_DIVERSITY
    assert len(image_dataset.cases[0].arm_0.artifacts) == 2
    assert len(image_dataset.cases[0].arm_1.artifacts) == 2

    by_dimension = {
        dimension: sum(case.dimension is dimension for case in image_dataset.cases)
        for dimension in ImageEvalDimension
    }
    assert set(by_dimension.values()) == {8}
    assert sum(case.gold_kind is GoldKind.OBJECTIVE_RECIPE for case in image_dataset.cases) == 36
    assert (
        sum(case.gold_kind is GoldKind.SUBJECTIVE_UNLABELED for case in image_dataset.cases) == 12
    )
    assert sum(case.split is DatasetSplit.CALIBRATION for case in image_dataset.cases) == 24
    assert sum(case.split is DatasetSplit.HOLDOUT for case in image_dataset.cases) == 24
    assert len(repeat_case_refs(image_dataset.cases)) == 12
    assert {
        case.case_ref
        for case in image_dataset.cases
        if case.gold_kind is GoldKind.SUBJECTIVE_UNLABELED
    } == set(repeat_case_refs(image_dataset.cases))
    assert sum(case.gold_choice is CanonicalChoice.FIRST for case in image_dataset.cases) == 18
    assert sum(case.gold_choice is CanonicalChoice.SECOND for case in image_dataset.cases) == 18
    family_split = {source.source_family: source.split for source in catalog.sources}
    assert list(family_split.values()).count(DatasetSplit.CALIBRATION) == 3
    assert list(family_split.values()).count(DatasetSplit.HOLDOUT) == 3
    assert all(
        family_split[family] is case.split
        for case in image_dataset.cases
        for family in case.source_families
    )


def test_dataset_transforms_are_byte_deterministic(
    image_dataset,
    tmp_path: Path,
) -> None:
    second_directory = tmp_path / "second"
    second_directory.mkdir(mode=0o700)
    second = build_image_panel_dataset(artifact_directory=second_directory)

    assert second.dataset_sha256 == image_dataset.dataset_sha256
    assert {
        artifact_ref: path.read_bytes() for artifact_ref, path in second.artifact_paths.items()
    } == {
        artifact_ref: path.read_bytes()
        for artifact_ref, path in image_dataset.artifact_paths.items()
    }


def test_source_preflight_rejects_hash_drift_private_path_and_dirty_git(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from evals.image_quality_panel import sources as source_module

    catalog = load_source_catalog()
    first = catalog.sources[0]
    drifted = first.model_copy(update={"content_sha256": "0" * 64})
    drifted_catalog = catalog.model_copy(update={"sources": (drifted, *catalog.sources[1:])})
    with pytest.raises(ImagePanelSourceError, match="hash or size drifted"):
        preflight_sources(drifted_catalog)

    private = first.model_copy(update={"repository_path": "private/source.png"})
    private_catalog = catalog.model_copy(update={"sources": (private, *catalog.sources[1:])})
    with pytest.raises(ImagePanelSourceError, match="outside the approved public"):
        preflight_sources(private_catalog)

    raw = json.loads(DEFAULT_SOURCE_CATALOG.read_text(encoding="utf-8"))
    raw.pop("external_model_use_basis")
    with pytest.raises(ValidationError):
        SourceCatalog.model_validate_json(json.dumps(raw))

    real_git = source_module._git

    def dirty_git(repository_root: Path, *arguments: str) -> str:
        if arguments[:2] == ("status", "--porcelain"):
            return " M public-source.png"
        return real_git(repository_root, *arguments)

    monkeypatch.setattr(source_module, "_git", dirty_git)
    with pytest.raises(ImagePanelSourceError, match="dirty"):
        preflight_sources(catalog)


def test_plan_is_exactly_120_hash_bound_calls_with_full_ba_inversion(
    image_plan: ImageExperimentPlan,
    image_dataset,
) -> None:
    assert TOTAL_CALL_CEILING == 48 * 2 + 12 * 2 == 120
    assert len(image_plan.requests) == image_plan.manifest.total_request_limit == 120
    counts = {
        model_ref: sum(request.evaluator_model_ref == model_ref for request in image_plan.requests)
        for model_ref in {spec.model_ref for spec in ALL_MODEL_SPECS}
    }
    assert set(counts.values()) == {CALLS_PER_MODEL}

    first_model = image_plan.manifest.identities[0].identity_ref
    model_requests = [
        request for request in image_plan.requests if request.evaluator_model_ref == first_model
    ]
    ab, ba = model_requests[:2]
    assert ab.presentation_order is PresentationOrder.AB
    assert ba.presentation_order is PresentationOrder.BA
    assert len(ab.artifacts) == len(ba.artifacts) == 4
    assert not any(
        artifact.presented_group is PresentedArtifactGroup.REFERENCE for artifact in ab.artifacts
    )
    assert ab.blind_a_ref == ba.blind_b_ref
    assert ab.blind_b_ref == ba.blind_a_ref
    assert {item.artifact_ref for item in ab.artifacts}.isdisjoint(image_dataset.artifact_paths)
    assert {item.artifact_ref for item in ab.artifacts}.isdisjoint(
        item.artifact_ref for item in ba.artifacts
    )
    assert [item.sha256 for item in ab.artifacts[:2]] == [item.sha256 for item in ba.artifacts[2:]]
    assert [item.sha256 for item in ab.artifacts[2:]] == [item.sha256 for item in ba.artifacts[:2]]
    assert ab.request_fingerprint != ba.request_fingerprint
    assert all(request.max_attempts == 1 for request in image_plan.requests)


def test_image_prompt_v2_is_exact_symmetric_and_contains_no_gold_leakage(
    image_plan: ImageExperimentPlan,
) -> None:
    request = image_plan.requests[0]
    rubric = image_plan.rubric_by_dimension[ImageEvalDimension(request.dimension)]

    prompt = build_pairwise_user_prompt(
        request=request,
        rubric_instruction=rubric,
        candidate_a_text="",
        candidate_b_text="",
    )

    assert request.prompt_version == image_plan.manifest.prompt_version
    assert request.prompt_version == IMAGE_PANEL_PROMPT_VERSION
    assert (
        "OUTPUT_KEYS=profile,choice,a_decision,b_decision,a_critical,b_critical,"
        "a_issue_codes,b_issue_codes,confidence"
    ) in prompt
    assert "OUTPUT_KEYS_EXACT_ONLY=true" in prompt
    assert "accept=>critical:false,issue_codes:[]" in prompt
    assert "reject=>critical:boolean,at_least_one_allowed_issue_code" in prompt
    assert "abstain=>critical:null,issue_codes:[]" in prompt
    assert "ISSUE_CODE_ARRAY_RULES=unique,lexically_sorted,allowed_only" in prompt
    assert request.case_ref not in prompt
    assert not any(
        leaked in prompt.lower() for leaked in ("arm_0", "arm_1", "gold_choice", "objective_recipe")
    )


def test_authorization_is_explicit_and_does_not_change_request_fingerprint(
    image_plan: ImageExperimentPlan,
) -> None:
    with pytest.raises(ValueError, match="acknowledgement"):
        issue_authorization(
            manifest=image_plan.manifest,
            valid_from=NOW,
            valid_until=NOW + timedelta(hours=1),
            approved_by_ref="owner",
            acknowledgement="no",
        )
    authorization = issue_authorization(
        manifest=image_plan.manifest,
        valid_from=NOW,
        valid_until=NOW + timedelta(hours=1),
        approved_by_ref="owner",
        acknowledgement=MODEL_PANEL_AUTHORIZATION_ACKNOWLEDGEMENT,
    )
    bound = bind_authorization(image_plan, authorization, now=NOW)
    assert {request.authorization_sha256 for request in bound.requests} == {
        authorization.authorization_sha256
    }
    assert [request.request_fingerprint for request in bound.requests] == [
        request.request_fingerprint for request in image_plan.requests
    ]


def test_report_recomputes_objective_metrics_and_single_model_stability(
    image_dataset,
    authorized_image_plan,
) -> None:
    image_plan, authorization = authorized_image_plan
    attempts = tuple(
        _completed_attempt(
            request,
            image_plan,
            image_dataset,
            invert_subjective=False,
        )
        for request in image_plan.requests
    )
    report = build_report(
        dataset=image_dataset,
        manifest=image_plan.manifest,
        authorization=authorization,
        evaluator_model_ref=IMAGE_EVALUATOR_MODEL_SPEC.model_ref,
        attempts=attempts,
    )
    score = report.evaluator
    assert score.evaluator_model_ref == IMAGE_EVALUATOR_MODEL_SPEC.model_ref
    assert score.objective.pair_accuracy == 1
    assert score.objective.arm_decision_macro_f1 == 1
    assert score.objective.critical_false_accept_rate == 0
    assert score.objective.acceptable_false_reject_rate == 0
    assert score.objective.critical_flag_false_positive_rate == 0
    assert score.objective.critical_flag_false_negative_rate == 0
    assert score.objective.effective_source_cluster_n == 6
    assert {
        item.dimension: item.score.effective_source_cluster_n
        for item in score.objective_by_dimension
    } == {
        ImageEvalDimension.SEMANTIC_FAITHFULNESS: 4,
        ImageEvalDimension.IP_IDENTITY: 2,
        ImageEvalDimension.OCR_TEXT: 2,
        ImageEvalDimension.AESTHETICS_ARTIFACTS: 4,
        ImageEvalDimension.PUBLICATION_LAYOUT: 4,
        ImageEvalDimension.BATCH_DIVERSITY: 6,
    }
    assert len(score.objective_by_split) == 2
    assert {item.split for item in score.objective_by_split} == set(DatasetSplit)
    assert all(item.score.critical_false_accept_rate == 0 for item in score.objective_by_split)
    assert all(item.score.effective_source_cluster_n == 3 for item in score.objective_by_split)
    assert score.subjective_stability.case_count == 12
    assert score.subjective_stability.eligible_case_count == 12
    assert score.subjective_stability.coverage == 1
    assert score.subjective_stability.position_stability == 1
    assert score.subjective_stability.abstention_count == 0
    assert score.subjective_stability.repeat_pair_count == 12
    assert score.subjective_stability.repeat_eligible_count == 12
    assert score.subjective_stability.repeat_consistency == 1
    assert len(score.subjective_stability_by_split) == 2
    assert all(item.score.case_count == 6 for item in score.subjective_stability_by_split)
    assert score.execution.repeat_consistency == 1
    artifact = build_candidate_artifact(report)
    assert artifact.non_activating is True
    assert artifact.enforce_eligible is False
    assert artifact.production_model_changed is False
    assert report.human_labels == 0
    assert report.external_label_n == 0
    assert report.single_model_only is True
    assert artifact.selection_recommendation is False

    def collect_keys(value: object) -> set[str]:
        if isinstance(value, dict):
            return {str(key) for key in value} | set().union(
                *(collect_keys(child) for child in value.values())
            )
        if isinstance(value, (list, tuple)):
            return set().union(*(collect_keys(child) for child in value))
        return set()

    report_keys = collect_keys(report.model_dump(mode="json"))
    assert report_keys.isdisjoint({"consensus", "agreement", "kappa", "proxy_gold"})

    failed_one_ba = tuple(
        _failed_attempt(attempt)
        if (
            attempt.case_ref == image_dataset.cases[0].case_ref
            and attempt.repeat_index == 0
            and attempt.presentation_order is PresentationOrder.BA
        )
        else attempt
        for attempt in attempts
    )
    reduced = build_report(
        dataset=image_dataset,
        manifest=image_plan.manifest,
        authorization=authorization,
        evaluator_model_ref=IMAGE_EVALUATOR_MODEL_SPEC.model_ref,
        attempts=failed_one_ba,
    )
    reduced_score = reduced.evaluator.objective
    assert reduced_score.case_count == reduced_score.critical_gold_count == 36
    assert reduced_score.critical_non_gold_count == 36
    assert reduced_score.eligible_case_count == 35
    assert reduced_score.pair_accuracy == pytest.approx(35 / 36)
    assert reduced_score.confusion.gold_accept_unresolved == 1
    assert reduced_score.confusion.gold_reject_unresolved == 1
    assert reduced_score.critical_false_accept_rate == 0
    assert reduced_score.acceptable_false_reject_rate == 0

    subjective_ref = next(
        case.case_ref
        for case in image_dataset.cases
        if case.gold_kind is GoldKind.SUBJECTIVE_UNLABELED
    )
    abstained_attempts = tuple(
        _abstained_attempt(attempt) if attempt.case_ref == subjective_ref else attempt
        for attempt in attempts
    )
    abstained = build_report(
        dataset=image_dataset,
        manifest=image_plan.manifest,
        authorization=authorization,
        evaluator_model_ref=IMAGE_EVALUATOR_MODEL_SPEC.model_ref,
        attempts=abstained_attempts,
    ).evaluator.subjective_stability
    assert abstained.eligible_case_count == 11
    assert abstained.coverage == pytest.approx(11 / 12)
    assert abstained.position_stability == pytest.approx(11 / 12)
    assert abstained.abstention_count == 1
    assert abstained.abstention_rate == pytest.approx(1 / 12)
    assert abstained.repeat_eligible_count == 11
    assert abstained.repeat_consistency == pytest.approx(11 / 12)
    assert abstained.bad_case_aliases == (subjective_ref,)

    conflicted_attempts = tuple(
        _completed_attempt(request, image_plan, image_dataset, invert_subjective=True)
        if request.case_ref == subjective_ref
        and request.repeat_index == 0
        and request.presentation_order is PresentationOrder.BA
        else attempt
        for request, attempt in zip(image_plan.requests, attempts, strict=True)
    )
    conflicted = build_report(
        dataset=image_dataset,
        manifest=image_plan.manifest,
        authorization=authorization,
        evaluator_model_ref=IMAGE_EVALUATOR_MODEL_SPEC.model_ref,
        attempts=conflicted_attempts,
    ).evaluator.subjective_stability
    assert conflicted.position_conflict_count == 1
    assert conflicted.position_conflict_rate == pytest.approx(1 / 12)
    assert conflicted.position_stability == pytest.approx(11 / 12)
    assert conflicted.repeat_consistency == pytest.approx(11 / 12)


def test_report_rejects_attempt_not_bound_to_manifest(
    image_dataset,
    authorized_image_plan,
) -> None:
    image_plan, authorization = authorized_image_plan
    attempt = _completed_attempt(
        image_plan.requests[0],
        image_plan,
        image_dataset,
        invert_subjective=False,
    )
    forged = attempt.model_copy(update={"attempt_ref": "attempt-forged"})
    with pytest.raises(ValueError, match="frozen manifest attempt"):
        build_report(
            dataset=image_dataset,
            manifest=image_plan.manifest,
            authorization=authorization,
            evaluator_model_ref=IMAGE_EVALUATOR_MODEL_SPEC.model_ref,
            attempts=(forged,),
        )


def test_report_rejects_reordered_attempt_prefix(
    image_dataset,
    authorized_image_plan,
) -> None:
    image_plan, authorization = authorized_image_plan
    attempts = tuple(
        _completed_attempt(
            request,
            image_plan,
            image_dataset,
            invert_subjective=False,
        )
        for request in image_plan.requests[:2]
    )

    with pytest.raises(ValueError, match="plan prefix"):
        build_report(
            dataset=image_dataset,
            manifest=image_plan.manifest,
            authorization=authorization,
            evaluator_model_ref=IMAGE_EVALUATOR_MODEL_SPEC.model_ref,
            attempts=tuple(reversed(attempts)),
        )


def test_plan_rejects_model_ref_bound_to_wrong_requested_model(image_dataset) -> None:
    identities = list(_identity(spec) for spec in ALL_MODEL_SPECS)
    identities[0] = identities[0].model_copy(
        update={"requested_model": "wrong-vision-model", "returned_model": "wrong-vision-model"}
    )
    with pytest.raises(ValueError, match="frozen model and provider routes"):
        build_experiment_plan(
            dataset=image_dataset,
            run_ref="image-panel-run-wrong-model",
            blind_key=b"deterministic-test-blind-key-32-bytes!!",
            identities=tuple(identities),
            provider_limits=(
                ProviderNativeLimit(
                    provider_ref="zhipu",
                    unit="cny",
                    maximum=Decimal("100"),
                ),
            ),
            maximum_native_cost_by_model={spec.model_ref: Decimal("1") for spec in ALL_MODEL_SPECS},
            git_sha="a" * 40,
            created_at=NOW,
            execution_window_start=NOW,
            execution_window_end=NOW + timedelta(days=1),
        )


@pytest.mark.asyncio
async def test_first_capability_failure_stops_unique_model_without_fallback(
    image_dataset,
    image_plan: ImageExperimentPlan,
) -> None:
    authorization = issue_authorization(
        manifest=image_plan.manifest,
        valid_from=NOW,
        valid_until=NOW + timedelta(hours=1),
        approved_by_ref="owner",
        acknowledgement=MODEL_PANEL_AUTHORIZATION_ACKNOWLEDGEMENT,
    )
    bound = bind_authorization(image_plan, authorization, now=NOW)
    executions = {
        identity.identity_ref: _FailFirstExecution(identity)
        for identity in bound.manifest.identities
    }
    result = await execute_image_plan(
        plan=bound,
        authorization=authorization,
        dataset=image_dataset,
        execution_by_model=executions,  # type: ignore[arg-type]
        now=NOW,
    )
    assert len(result.attempts) == 1
    assert result.stopped_model_refs == (IMAGE_EVALUATOR_MODEL_SPEC.model_ref,)
    assert result.skipped_attempt_count == 119
    assert all(execution.calls == 1 for execution in executions.values())


def test_dedicated_audit_model_default_does_not_enable_observation() -> None:
    settings = Settings(_env_file=None)
    assert settings.image_quality_audit_model == "glm-5v-turbo"
    assert settings.image_quality_audit_enabled is False
    assert settings.image_quality_eval_mode == "off"
    with pytest.raises(ValueError, match="audit model identifier"):
        Settings(_env_file=None, image_quality_audit_model="glm vision")


def _identity(spec) -> PanelModelIdentity:
    return PanelModelIdentity(
        identity_ref=spec.model_ref,
        gateway=spec.gateway,
        provider=spec.provider,
        model_family=spec.model_ref,
        requested_model=spec.requested_model,
        returned_model=spec.requested_model,
        endpoint_host_sha256=sha256(b"test.example").hexdigest(),
        adapter_version="one-shot-test-v1",
        pricing_snapshot_sha256=sha256(b"pricing").hexdigest(),
    )


def _completed_attempt(
    request,
    plan: ImageExperimentPlan,
    dataset,
    *,
    invert_subjective: bool,
) -> PanelAttempt:
    case = next(case for case in dataset.cases if case.case_ref == request.case_ref)
    if case.gold_kind is GoldKind.OBJECTIVE_RECIPE:
        choice = case.gold_choice
        first_verdict = case.gold_first_verdict
        second_verdict = case.gold_second_verdict
    else:
        choice = CanonicalChoice.SECOND if invert_subjective else CanonicalChoice.FIRST
        first_verdict = ArmVerdict(
            decision=ArmDecision.ACCEPT,
            critical=False,
            issue_codes=(),
        )
        second_verdict = first_verdict
    assert choice is not None and first_verdict is not None and second_verdict is not None
    if request.presentation_order is PresentationOrder.AB:
        presented_choice = (
            PresentedChoice.A if choice is CanonicalChoice.FIRST else PresentedChoice.B
        )
        presented_a, presented_b = first_verdict, second_verdict
    else:
        presented_choice = (
            PresentedChoice.B if choice is CanonicalChoice.FIRST else PresentedChoice.A
        )
        presented_a, presented_b = second_verdict, first_verdict
    vote = JudgeVote(
        schema_version="model-panel-vote-v1",
        attempt_ref=request.attempt_ref,
        pair_ref=request.pair_ref,
        case_ref=request.case_ref,
        evaluator_model_ref=request.evaluator_model_ref,
        request_fingerprint=request.request_fingerprint,
        presentation_order=request.presentation_order,
        repeat_index=request.repeat_index,
        vote_profile=VoteProfile.IMAGE_PAIR_ARM_VERDICT,
        presented_choice=presented_choice,
        canonical_choice=choice,
        issue_codes=(),
        presented_a_verdict=presented_a,
        presented_b_verdict=presented_b,
        canonical_first_verdict=first_verdict,
        canonical_second_verdict=second_verdict,
        confidence=0.9,
    )
    identity = next(
        item
        for item in plan.manifest.identities
        if item.identity_ref == request.evaluator_model_ref
    )
    return PanelAttempt(
        schema_version="model-panel-attempt-v1",
        run_ref=request.run_ref,
        manifest_sha256=request.manifest_sha256,
        authorization_sha256=request.authorization_sha256,
        attempt_ref=request.attempt_ref,
        pair_ref=request.pair_ref,
        case_ref=request.case_ref,
        evaluator_model_ref=request.evaluator_model_ref,
        presentation_order=request.presentation_order,
        repeat_index=request.repeat_index,
        request_fingerprint=request.request_fingerprint,
        status=AttemptStatus.COMPLETED,
        started_at=NOW,
        finished_at=NOW,
        identity=identity,
        usage=ProviderUsage(
            input_tokens=100,
            output_tokens=20,
            native_cost=NativeCost(unit=request.native_cost_unit, amount=Decimal("0.01")),
        ),
        latency_ms=10,
        vote=vote,
    )


def _failed_attempt(attempt: PanelAttempt) -> PanelAttempt:
    payload = attempt.model_dump()
    payload.update(
        {
            "status": AttemptStatus.FAILED,
            "identity": None,
            "usage": None,
            "vote": None,
            "failure_code": PanelFailureCode.INVALID_PROVIDER_OUTPUT,
        }
    )
    return PanelAttempt.model_validate(payload)


def _abstained_attempt(attempt: PanelAttempt) -> PanelAttempt:
    assert attempt.vote is not None
    abstain = ArmVerdict(decision=ArmDecision.ABSTAIN, critical=None, issue_codes=())
    vote_payload = attempt.vote.model_dump()
    vote_payload.update(
        {
            "presented_choice": PresentedChoice.ABSTAIN,
            "canonical_choice": CanonicalChoice.ABSTAIN,
            "presented_a_verdict": abstain,
            "presented_b_verdict": abstain,
            "canonical_first_verdict": abstain,
            "canonical_second_verdict": abstain,
        }
    )
    attempt_payload = attempt.model_dump()
    attempt_payload["vote"] = JudgeVote.model_validate(vote_payload)
    return PanelAttempt.model_validate(attempt_payload)


class _FailFirstExecution:
    def __init__(self, identity: PanelModelIdentity) -> None:
        self.identity = identity
        self.calls = 0

    async def execute(self, *, identity, request, material) -> PanelAttempt:
        self.calls += 1
        assert identity == self.identity
        assert len(material.images) == 4
        return PanelAttempt(
            schema_version="model-panel-attempt-v1",
            run_ref=request.run_ref,
            manifest_sha256=request.manifest_sha256,
            authorization_sha256=request.authorization_sha256,
            attempt_ref=request.attempt_ref,
            pair_ref=request.pair_ref,
            case_ref=request.case_ref,
            evaluator_model_ref=request.evaluator_model_ref,
            presentation_order=request.presentation_order,
            repeat_index=request.repeat_index,
            request_fingerprint=request.request_fingerprint,
            status=AttemptStatus.FAILED,
            started_at=NOW,
            finished_at=NOW,
            latency_ms=1,
            failure_code=PanelFailureCode.INVALID_PROVIDER_OUTPUT,
        )
