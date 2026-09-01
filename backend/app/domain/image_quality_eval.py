"""Provider-independent contracts for explainable image-quality evaluation.

The module owns the closed six-dimension vocabulary shared by offline fixtures and
optional production observers.  It deliberately contains no SQLAlchemy, provider,
or image-byte handling so callers can bind observations to already-produced
publication hashes without crossing infrastructure boundaries.
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import StrEnum
from typing import Annotated, Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

IMAGE_EVAL_CASE_SCHEMA_VERSION: Final[Literal["image-quality-eval-case-v1"]] = (
    "image-quality-eval-case-v1"
)
IMAGE_EVAL_OBSERVATION_SCHEMA_VERSION: Final[Literal["image-quality-eval-observation-v1"]] = (
    "image-quality-eval-observation-v1"
)
IMAGE_EVAL_RUBRIC_SCHEMA_VERSION: Final[Literal["image-quality-eval-rubric-v1"]] = (
    "image-quality-eval-rubric-v1"
)
IMAGE_EVAL_RUBRIC_VERSION: Final[Literal["image-quality-rubric-v1"]] = "image-quality-rubric-v1"
IMAGE_EVAL_DECISION_POLICY_VERSION: Final[Literal["image-quality-decision-policy-v1"]] = (
    "image-quality-decision-policy-v1"
)

BoundedIdentifier = Annotated[
    str,
    StringConstraints(min_length=1, max_length=160, pattern=r"^[a-z0-9][a-z0-9._:-]*$"),
]
Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class ImageEvalDimension(StrEnum):
    """The six independently reported quality constructs in the MVP."""

    SEMANTIC_FAITHFULNESS = "semantic_faithfulness"
    IP_IDENTITY = "ip_identity"
    OCR_TEXT = "ocr_text"
    AESTHETICS_ARTIFACTS = "aesthetics_artifacts"
    PUBLICATION_LAYOUT = "publication_layout"
    BATCH_DIVERSITY = "batch_diversity"


IMAGE_EVAL_SINGLE_IMAGE_DIMENSIONS: Final[tuple[ImageEvalDimension, ...]] = (
    ImageEvalDimension.SEMANTIC_FAITHFULNESS,
    ImageEvalDimension.IP_IDENTITY,
    ImageEvalDimension.OCR_TEXT,
    ImageEvalDimension.AESTHETICS_ARTIFACTS,
    ImageEvalDimension.PUBLICATION_LAYOUT,
)


class ImageEvalSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


class ImageEvalIssueCode(StrEnum):
    SEMANTIC_CORE_ENTITY_MISSING = "semantic_core_entity_missing"
    SEMANTIC_RELATION_MISMATCH = "semantic_relation_mismatch"
    SEMANTIC_CONTEXT_AMBIGUOUS = "semantic_context_ambiguous"
    IP_CHARACTER_IDENTITY_MISMATCH = "ip_character_identity_mismatch"
    IP_REQUIRED_MARK_MISSING = "ip_required_mark_missing"
    IP_IDENTITY_BORDERLINE = "ip_identity_borderline"
    OCR_REQUIRED_TEXT_MISMATCH = "ocr_required_text_mismatch"
    OCR_FORBIDDEN_TEXT_DETECTED = "ocr_forbidden_text_detected"
    OCR_LOW_CONFIDENCE = "ocr_low_confidence"
    ARTIFACT_SUBJECT_MALFORMED = "artifact_subject_malformed"
    ARTIFACT_VISUAL_NOISE = "artifact_visual_noise"
    AESTHETICS_HIERARCHY_WEAK = "aesthetics_hierarchy_weak"
    LAYOUT_REQUIRED_SUBJECT_CROPPED = "layout_required_subject_cropped"
    LAYOUT_REQUIRED_TEXT_OUTSIDE_SAFE_AREA = "layout_required_text_outside_safe_area"
    LAYOUT_SMALL_TEXT_WARNING = "layout_small_text_warning"
    DIVERSITY_EXACT_DUPLICATE = "diversity_exact_duplicate"
    DIVERSITY_NEAR_DUPLICATE = "diversity_near_duplicate"
    DIVERSITY_SCENE_REPETITION = "diversity_scene_repetition"
    PROVIDER_AUDIT_UNCLASSIFIED = "provider_audit_unclassified"


class ImageEvalObservationStatus(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class ImageEvalUnavailableReason(StrEnum):
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    INVALID_OUTPUT = "invalid_output"
    IDENTITY_MISMATCH = "identity_mismatch"
    NOT_OBSERVED = "not_observed"


class ImageEvalDecisionKind(StrEnum):
    ACCEPTED = "accepted"
    MANUAL_REVIEW = "manual_review"
    REJECTED = "rejected"
    UNAVAILABLE = "unavailable"


class ImageEvalFixtureKind(StrEnum):
    POSITIVE = "positive"
    WARNING = "warning"
    BORDERLINE = "borderline"
    HARD_NEGATIVE = "hard_negative"
    UNAVAILABLE = "unavailable"


class ImageEvalEvaluatorKind(StrEnum):
    FROZEN_FIXTURE = "frozen_fixture"
    DETERMINISTIC = "deterministic"
    PROVIDER_AUDIT = "provider_audit"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ImageEvalCriterion(_FrozenModel):
    """One case-specific, evaluator-facing assertion."""

    criterion_id: BoundedIdentifier
    description: str = Field(min_length=1, max_length=240)
    critical: bool


class ImageEvalCase(_FrozenModel):
    """Sanitized gold label for one final-publication observation."""

    schema_version: Literal["image-quality-eval-case-v1"]
    case_id: BoundedIdentifier
    fixture_kind: ImageEvalFixtureKind
    dimension: ImageEvalDimension
    content_ref: BoundedIdentifier
    publication_sha256: Sha256Hex
    criteria: tuple[ImageEvalCriterion, ...] = Field(min_length=1, max_length=8)
    gold_issue_codes: tuple[ImageEvalIssueCode, ...] = Field(max_length=8)
    expected_decision: ImageEvalDecisionKind

    @model_validator(mode="after")
    def validate_case(self) -> Self:
        criterion_ids = tuple(criterion.criterion_id for criterion in self.criteria)
        if len(criterion_ids) != len(set(criterion_ids)):
            raise ValueError("criterion IDs must be unique within a case")
        if len(self.gold_issue_codes) != len(set(self.gold_issue_codes)):
            raise ValueError("gold issue codes must be unique within a case")
        return self


class ImageEvalIssue(_FrozenModel):
    """A bounded, explainable issue emitted by an evaluator."""

    code: ImageEvalIssueCode
    dimension: ImageEvalDimension
    severity: ImageEvalSeverity
    evidence_ref: BoundedIdentifier
    score: float | None = Field(default=None, ge=0, le=1)
    confidence: float | None = Field(default=None, ge=0, le=1)


class ImageEvalObservation(_FrozenModel):
    """Reusable observation bound to the exact final publication bytes."""

    schema_version: Literal["image-quality-eval-observation-v1"]
    observation_id: BoundedIdentifier
    subject_ref: BoundedIdentifier
    publication_sha256: Sha256Hex
    dimension: ImageEvalDimension
    status: ImageEvalObservationStatus
    evaluator_kind: ImageEvalEvaluatorKind
    evaluator_version: BoundedIdentifier
    rubric_version: BoundedIdentifier
    provider: BoundedIdentifier | None = None
    model: BoundedIdentifier | None = None
    request_fingerprint: Sha256Hex | None = None
    score: float | None = Field(default=None, ge=0, le=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    evidence_refs: tuple[BoundedIdentifier, ...] = Field(default=(), max_length=16)
    issues: tuple[ImageEvalIssue, ...] = Field(default=(), max_length=16)
    unavailable_reason: ImageEvalUnavailableReason | None = None

    @model_validator(mode="after")
    def validate_observation(self) -> Self:
        if len(self.evidence_refs) != len(set(self.evidence_refs)):
            raise ValueError("observation evidence refs must be unique")
        issue_codes = tuple(issue.code for issue in self.issues)
        if len(issue_codes) != len(set(issue_codes)):
            raise ValueError("observation issue codes must be unique")
        evidence_refs = set(self.evidence_refs)
        if any(issue.evidence_ref not in evidence_refs for issue in self.issues):
            raise ValueError("observation issues must reference declared evidence")
        if any(issue.dimension is not self.dimension for issue in self.issues):
            raise ValueError("observation issues must use the observation dimension")
        if self.status is ImageEvalObservationStatus.UNAVAILABLE:
            if self.unavailable_reason is None:
                raise ValueError("unavailable observations require a reason")
            if self.issues or self.score is not None or self.confidence is not None:
                raise ValueError("unavailable observations cannot claim issues or scores")
        elif self.unavailable_reason is not None:
            raise ValueError("available observations cannot have an unavailable reason")
        return self


class ImageEvalDimensionDefinition(_FrozenModel):
    dimension: ImageEvalDimension
    description: str = Field(min_length=1, max_length=400)


class ImageEvalIssueDefinition(_FrozenModel):
    code: ImageEvalIssueCode
    dimension: ImageEvalDimension
    severity: ImageEvalSeverity
    description: str = Field(min_length=1, max_length=400)


class ImageEvalRubric(_FrozenModel):
    schema_version: Literal["image-quality-eval-rubric-v1"]
    rubric_version: Literal["image-quality-rubric-v1"]
    decision_policy_version: Literal["image-quality-decision-policy-v1"]
    dimensions: tuple[ImageEvalDimensionDefinition, ...]
    issues: tuple[ImageEvalIssueDefinition, ...]

    @model_validator(mode="after")
    def validate_rubric(self) -> Self:
        dimensions = tuple(item.dimension for item in self.dimensions)
        if len(dimensions) != len(set(dimensions)):
            raise ValueError("rubric dimensions must be unique")
        if set(dimensions) != set(ImageEvalDimension):
            raise ValueError("rubric must define all and only the six image dimensions")
        issue_codes = tuple(item.code for item in self.issues)
        if len(issue_codes) != len(set(issue_codes)):
            raise ValueError("rubric issue codes must be unique")
        if set(issue_codes) != set(ImageEvalIssueCode):
            raise ValueError("rubric must define the complete closed issue taxonomy")
        return self


class ImageEvalDecision(_FrozenModel):
    decision: ImageEvalDecisionKind
    hard_gate_passed: bool
    manual_review_required: bool
    ranking_score: float | None = Field(default=None, ge=0, le=1)
    decision_policy_version: BoundedIdentifier
    reason_codes: tuple[ImageEvalIssueCode, ...]


class ImageEvalDimensionDecision(_FrozenModel):
    dimension: ImageEvalDimension
    decision: ImageEvalDecisionKind
    hard_gate_passed: bool
    manual_review_required: bool
    reason_codes: tuple[ImageEvalIssueCode, ...]


class ImageEvalBatchDecision(_FrozenModel):
    """One aggregate decision over distinct per-dimension observations."""

    decision: ImageEvalDecisionKind
    hard_gate_passed: bool
    manual_review_required: bool
    decision_policy_version: BoundedIdentifier
    reason_codes: tuple[ImageEvalIssueCode, ...]
    dimensions: tuple[ImageEvalDimensionDecision, ...]


class ImageEvalContractError(ValueError):
    """An observation or rubric violates the shared closed contract."""


_ISSUE_CONTRACTS: dict[ImageEvalIssueCode, tuple[ImageEvalDimension, ImageEvalSeverity]] = {
    ImageEvalIssueCode.SEMANTIC_CORE_ENTITY_MISSING: (
        ImageEvalDimension.SEMANTIC_FAITHFULNESS,
        ImageEvalSeverity.CRITICAL,
    ),
    ImageEvalIssueCode.SEMANTIC_RELATION_MISMATCH: (
        ImageEvalDimension.SEMANTIC_FAITHFULNESS,
        ImageEvalSeverity.CRITICAL,
    ),
    ImageEvalIssueCode.SEMANTIC_CONTEXT_AMBIGUOUS: (
        ImageEvalDimension.SEMANTIC_FAITHFULNESS,
        ImageEvalSeverity.WARNING,
    ),
    ImageEvalIssueCode.IP_CHARACTER_IDENTITY_MISMATCH: (
        ImageEvalDimension.IP_IDENTITY,
        ImageEvalSeverity.CRITICAL,
    ),
    ImageEvalIssueCode.IP_REQUIRED_MARK_MISSING: (
        ImageEvalDimension.IP_IDENTITY,
        ImageEvalSeverity.CRITICAL,
    ),
    ImageEvalIssueCode.IP_IDENTITY_BORDERLINE: (
        ImageEvalDimension.IP_IDENTITY,
        ImageEvalSeverity.WARNING,
    ),
    ImageEvalIssueCode.OCR_REQUIRED_TEXT_MISMATCH: (
        ImageEvalDimension.OCR_TEXT,
        ImageEvalSeverity.CRITICAL,
    ),
    ImageEvalIssueCode.OCR_FORBIDDEN_TEXT_DETECTED: (
        ImageEvalDimension.OCR_TEXT,
        ImageEvalSeverity.CRITICAL,
    ),
    ImageEvalIssueCode.OCR_LOW_CONFIDENCE: (
        ImageEvalDimension.OCR_TEXT,
        ImageEvalSeverity.WARNING,
    ),
    ImageEvalIssueCode.ARTIFACT_SUBJECT_MALFORMED: (
        ImageEvalDimension.AESTHETICS_ARTIFACTS,
        ImageEvalSeverity.CRITICAL,
    ),
    ImageEvalIssueCode.ARTIFACT_VISUAL_NOISE: (
        ImageEvalDimension.AESTHETICS_ARTIFACTS,
        ImageEvalSeverity.WARNING,
    ),
    ImageEvalIssueCode.AESTHETICS_HIERARCHY_WEAK: (
        ImageEvalDimension.AESTHETICS_ARTIFACTS,
        ImageEvalSeverity.WARNING,
    ),
    ImageEvalIssueCode.LAYOUT_REQUIRED_SUBJECT_CROPPED: (
        ImageEvalDimension.PUBLICATION_LAYOUT,
        ImageEvalSeverity.CRITICAL,
    ),
    ImageEvalIssueCode.LAYOUT_REQUIRED_TEXT_OUTSIDE_SAFE_AREA: (
        ImageEvalDimension.PUBLICATION_LAYOUT,
        ImageEvalSeverity.CRITICAL,
    ),
    ImageEvalIssueCode.LAYOUT_SMALL_TEXT_WARNING: (
        ImageEvalDimension.PUBLICATION_LAYOUT,
        ImageEvalSeverity.WARNING,
    ),
    ImageEvalIssueCode.DIVERSITY_EXACT_DUPLICATE: (
        ImageEvalDimension.BATCH_DIVERSITY,
        ImageEvalSeverity.CRITICAL,
    ),
    ImageEvalIssueCode.DIVERSITY_NEAR_DUPLICATE: (
        ImageEvalDimension.BATCH_DIVERSITY,
        ImageEvalSeverity.WARNING,
    ),
    ImageEvalIssueCode.DIVERSITY_SCENE_REPETITION: (
        ImageEvalDimension.BATCH_DIVERSITY,
        ImageEvalSeverity.WARNING,
    ),
    ImageEvalIssueCode.PROVIDER_AUDIT_UNCLASSIFIED: (
        ImageEvalDimension.AESTHETICS_ARTIFACTS,
        ImageEvalSeverity.WARNING,
    ),
}


def build_image_eval_issue(
    *,
    code: ImageEvalIssueCode | str,
    dimension: ImageEvalDimension,
    severity: ImageEvalSeverity,
    evidence_ref: str,
    score: float | None = None,
    confidence: float | None = None,
) -> ImageEvalIssue:
    """Build one closed issue, mapping unknown provider codes to manual review.

    Unknown provider codes never create new dimensions or silently pass.  They are
    normalized to a stable warning in ``aesthetics_artifacts`` so the decision
    policy sends the result to manual review.
    """

    try:
        normalized_code = ImageEvalIssueCode(code)
    except ValueError:
        normalized_code = ImageEvalIssueCode.PROVIDER_AUDIT_UNCLASSIFIED
        dimension = ImageEvalDimension.AESTHETICS_ARTIFACTS
        severity = ImageEvalSeverity.WARNING
    expected_dimension, expected_severity = _ISSUE_CONTRACTS[normalized_code]
    if dimension is not expected_dimension or severity is not expected_severity:
        raise ImageEvalContractError(
            "image eval issue dimension/severity does not match the closed taxonomy"
        )
    return ImageEvalIssue(
        code=normalized_code,
        dimension=dimension,
        severity=severity,
        evidence_ref=evidence_ref,
        score=score,
        confidence=confidence,
    )


def build_image_eval_observation(
    *,
    observation_id: str,
    subject_ref: str,
    publication_sha256: str,
    dimension: ImageEvalDimension,
    status: ImageEvalObservationStatus,
    evaluator_kind: ImageEvalEvaluatorKind,
    evaluator_version: str,
    rubric_version: str = IMAGE_EVAL_RUBRIC_VERSION,
    provider: str | None = None,
    model: str | None = None,
    request_fingerprint: str | None = None,
    score: float | None = None,
    confidence: float | None = None,
    evidence_refs: Sequence[str] = (),
    issues: Sequence[ImageEvalIssue] = (),
    unavailable_reason: ImageEvalUnavailableReason | None = None,
) -> ImageEvalObservation:
    """Construct a strict reusable observation without any eval-runner dependency."""

    return ImageEvalObservation(
        schema_version=IMAGE_EVAL_OBSERVATION_SCHEMA_VERSION,
        observation_id=observation_id,
        subject_ref=subject_ref,
        publication_sha256=publication_sha256,
        dimension=dimension,
        status=status,
        evaluator_kind=evaluator_kind,
        evaluator_version=evaluator_version,
        rubric_version=rubric_version,
        provider=provider,
        model=model,
        request_fingerprint=request_fingerprint,
        score=score,
        confidence=confidence,
        evidence_refs=tuple(evidence_refs),
        issues=tuple(issues),
        unavailable_reason=unavailable_reason,
    )


def decide_image_eval(
    observation: ImageEvalObservation,
    rubric: ImageEvalRubric,
) -> ImageEvalDecision:
    """Apply the versioned hard-gate/manual-review policy to one observation."""

    _validate_observation_contract(observation, rubric)
    if observation.status is ImageEvalObservationStatus.UNAVAILABLE:
        return ImageEvalDecision(
            decision=ImageEvalDecisionKind.UNAVAILABLE,
            hard_gate_passed=False,
            manual_review_required=True,
            ranking_score=None,
            decision_policy_version=IMAGE_EVAL_DECISION_POLICY_VERSION,
            reason_codes=(),
        )
    critical = tuple(
        issue.code for issue in observation.issues if issue.severity is ImageEvalSeverity.CRITICAL
    )
    if critical:
        return ImageEvalDecision(
            decision=ImageEvalDecisionKind.REJECTED,
            hard_gate_passed=False,
            manual_review_required=False,
            ranking_score=observation.score,
            decision_policy_version=IMAGE_EVAL_DECISION_POLICY_VERSION,
            reason_codes=critical,
        )
    warnings = tuple(
        issue.code for issue in observation.issues if issue.severity is ImageEvalSeverity.WARNING
    )
    if warnings:
        return ImageEvalDecision(
            decision=ImageEvalDecisionKind.MANUAL_REVIEW,
            hard_gate_passed=True,
            manual_review_required=True,
            ranking_score=observation.score,
            decision_policy_version=IMAGE_EVAL_DECISION_POLICY_VERSION,
            reason_codes=warnings,
        )
    return ImageEvalDecision(
        decision=ImageEvalDecisionKind.ACCEPTED,
        hard_gate_passed=True,
        manual_review_required=False,
        ranking_score=observation.score,
        decision_policy_version=IMAGE_EVAL_DECISION_POLICY_VERSION,
        reason_codes=(),
    )


def decide_image_eval_batch(
    observations: Sequence[ImageEvalObservation],
    rubric: ImageEvalRubric,
) -> ImageEvalBatchDecision:
    """Aggregate distinct dimension observations without flattening their issue taxonomy."""

    if not observations:
        raise ImageEvalContractError("image eval batch requires at least one observation")
    ordered = tuple(sorted(observations, key=lambda item: item.dimension.value))
    dimensions = tuple(item.dimension for item in ordered)
    if len(dimensions) != len(set(dimensions)):
        raise ImageEvalContractError("image eval batch dimensions must be unique")
    subjects = {item.subject_ref for item in ordered}
    hashes = {item.publication_sha256 for item in ordered}
    if len(subjects) != 1 or len(hashes) != 1:
        raise ImageEvalContractError("image eval batch must bind one subject and publication hash")
    decisions = tuple(decide_image_eval(item, rubric) for item in ordered)
    projected = tuple(
        ImageEvalDimensionDecision(
            dimension=observation.dimension,
            decision=decision.decision,
            hard_gate_passed=decision.hard_gate_passed,
            manual_review_required=decision.manual_review_required,
            reason_codes=decision.reason_codes,
        )
        for observation, decision in zip(ordered, decisions, strict=True)
    )
    kinds = {item.decision for item in decisions}
    if ImageEvalDecisionKind.REJECTED in kinds:
        decision_kind = ImageEvalDecisionKind.REJECTED
        hard_gate_passed = False
        manual_review_required = False
    elif ImageEvalDecisionKind.UNAVAILABLE in kinds:
        decision_kind = ImageEvalDecisionKind.UNAVAILABLE
        hard_gate_passed = False
        manual_review_required = True
    elif ImageEvalDecisionKind.MANUAL_REVIEW in kinds:
        decision_kind = ImageEvalDecisionKind.MANUAL_REVIEW
        hard_gate_passed = True
        manual_review_required = True
    else:
        decision_kind = ImageEvalDecisionKind.ACCEPTED
        hard_gate_passed = True
        manual_review_required = False
    reason_codes = tuple(
        sorted({code for item in decisions for code in item.reason_codes}, key=str)
    )
    return ImageEvalBatchDecision(
        decision=decision_kind,
        hard_gate_passed=hard_gate_passed,
        manual_review_required=manual_review_required,
        decision_policy_version=IMAGE_EVAL_DECISION_POLICY_VERSION,
        reason_codes=reason_codes,
        dimensions=projected,
    )


def active_image_eval_rubric() -> ImageEvalRubric:
    """Build the production-safe active rubric without importing offline eval artifacts."""

    dimension_descriptions = {
        ImageEvalDimension.SEMANTIC_FAITHFULNESS: (
            "Required entities, actions, counts, and relationships match the visual brief."
        ),
        ImageEvalDimension.IP_IDENTITY: (
            "Approved character identity and distinctive marks remain recognizable."
        ),
        ImageEvalDimension.OCR_TEXT: (
            "Required visible text is exact and forbidden text is absent."
        ),
        ImageEvalDimension.AESTHETICS_ARTIFACTS: (
            "Subjects and scientific objects are legible and free from material artifacts."
        ),
        ImageEvalDimension.PUBLICATION_LAYOUT: (
            "Final publication bytes retain required subjects and text inside safe areas."
        ),
        ImageEvalDimension.BATCH_DIVERSITY: (
            "A publication batch avoids exact and review-worthy perceptual repetition."
        ),
    }
    return ImageEvalRubric(
        schema_version=IMAGE_EVAL_RUBRIC_SCHEMA_VERSION,
        rubric_version=IMAGE_EVAL_RUBRIC_VERSION,
        decision_policy_version=IMAGE_EVAL_DECISION_POLICY_VERSION,
        dimensions=tuple(
            ImageEvalDimensionDefinition(
                dimension=dimension,
                description=dimension_descriptions[dimension],
            )
            for dimension in ImageEvalDimension
        ),
        issues=tuple(
            ImageEvalIssueDefinition(
                code=code,
                dimension=contract[0],
                severity=contract[1],
                description=f"Stable closed issue contract for {code.value}.",
            )
            for code, contract in _ISSUE_CONTRACTS.items()
        ),
    )


def issue_contract(
    code: ImageEvalIssueCode,
) -> tuple[ImageEvalDimension, ImageEvalSeverity]:
    """Return the stable dimension/severity pair for reporting and fixture validation."""

    return _ISSUE_CONTRACTS[code]


def _validate_observation_contract(
    observation: ImageEvalObservation,
    rubric: ImageEvalRubric,
) -> None:
    if observation.rubric_version != rubric.rubric_version:
        raise ImageEvalContractError("observation rubric version does not match the active rubric")
    rubric_issues = {item.code: item for item in rubric.issues}
    for issue in observation.issues:
        definition = rubric_issues[issue.code]
        expected_dimension, expected_severity = _ISSUE_CONTRACTS[issue.code]
        if (
            issue.dimension is not definition.dimension
            or issue.severity is not definition.severity
            or issue.dimension is not expected_dimension
            or issue.severity is not expected_severity
        ):
            raise ImageEvalContractError(
                "observation issue does not match the rubric and closed taxonomy"
            )
