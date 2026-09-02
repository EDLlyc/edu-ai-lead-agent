"""Provider-independent contracts for a governed official-account Reviewer.

The module intentionally owns only closed schemas, input binding, hard-gate
precedence, deterministic fingerprints, and code-owned repair directives. It
does not import a provider, persistence adapter, or production executor.
"""

from __future__ import annotations

import json
from enum import StrEnum
from hashlib import sha256
from typing import Annotated, Final, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

REVIEW_REQUEST_SCHEMA_VERSION: Final[Literal["official-account-review-request-v1"]] = (
    "official-account-review-request-v1"
)
REVIEW_VERDICT_SCHEMA_VERSION: Final[Literal["official-account-review-verdict-v1"]] = (
    "official-account-review-verdict-v1"
)
REVIEW_RUBRIC_SCHEMA_VERSION: Final[Literal["official-account-review-rubric-v1"]] = (
    "official-account-review-rubric-v1"
)
REVIEW_RUBRIC_VERSION: Final[Literal["official-account-editorial-rubric-v1"]] = (
    "official-account-editorial-rubric-v1"
)
REVIEW_POLICY_VERSION: Final[Literal["official-account-review-policy-v1"]] = (
    "official-account-review-policy-v1"
)
REPAIR_POLICY_VERSION: Final[Literal["official-account-repair-policy-v1"]] = (
    "official-account-repair-policy-v1"
)

BoundedIdentifier = Annotated[
    str,
    StringConstraints(min_length=1, max_length=160, pattern=r"^[a-z0-9][a-z0-9._:-]*$"),
]
Sha256Hex = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]


class ReviewDecision(StrEnum):
    ACCEPTED = "accepted"
    MANUAL_REVIEW = "manual_review"
    REJECTED = "rejected"
    UNAVAILABLE = "unavailable"


class ReviewDimension(StrEnum):
    FACTUAL_GROUNDING = "factual_grounding"
    BRAND_TONE = "brand_tone"
    STRUCTURE_READABILITY = "structure_readability"
    PRIVACY_SAFETY = "privacy_safety"
    INSTRUCTION_BOUNDARY = "instruction_boundary"
    MARKETING_INTEGRITY = "marketing_integrity"


class ReviewSeverity(StrEnum):
    WARNING = "warning"
    CRITICAL = "critical"


class ReviewIssueCode(StrEnum):
    FACT_NOT_ENTAILED = "fact_not_entailed"
    EVIDENCE_REFERENCE_MISSING = "evidence_reference_missing"
    FACTUAL_CONTEXT_AMBIGUOUS = "factual_context_ambiguous"
    BRAND_TONE_MISMATCH = "brand_tone_mismatch"
    BRAND_VOICE_AMBIGUOUS = "brand_voice_ambiguous"
    HEADING_HIERARCHY_INVALID = "heading_hierarchy_invalid"
    PARAGRAPH_DENSITY_HIGH = "paragraph_density_high"
    STRUCTURE_AMBIGUOUS = "structure_ambiguous"
    PRIVACY_RISK = "privacy_risk"
    SAFETY_RISK = "safety_risk"
    MINOR_IDENTIFIABLE_DETAIL = "minor_identifiable_detail"
    PROMPT_INJECTION_DETECTED = "prompt_injection_detected"
    IMPROPER_DISTRIBUTION_INSTRUCTION = "improper_distribution_instruction"
    INSTRUCTION_CONTEXT_AMBIGUOUS = "instruction_context_ambiguous"
    MARKETING_CLAIM_EXAGGERATED = "marketing_claim_exaggerated"
    CALL_TO_ACTION_TOO_AGGRESSIVE = "call_to_action_too_aggressive"
    MARKETING_CONTEXT_AMBIGUOUS = "marketing_context_ambiguous"


class ReviewReferenceKind(StrEnum):
    ARTICLE = "article"
    SECTION = "section"
    BLOCK = "block"
    CLAIM = "claim"
    EVIDENCE = "evidence"


class ReviewIssueSource(StrEnum):
    REVIEWER = "reviewer"
    HARD_GATE = "hard_gate"


class ReviewUnavailableReason(StrEnum):
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    INVALID_OUTPUT = "invalid_output"
    IDENTITY_MISMATCH = "identity_mismatch"


class ReviewHardGateCode(StrEnum):
    FACT_NOT_ENTAILED = "fact_not_entailed"
    EVIDENCE_REFERENCE_MISSING = "evidence_reference_missing"
    PRIVACY_RISK = "privacy_risk"
    SAFETY_RISK = "safety_risk"
    MINOR_IDENTIFIABLE_DETAIL = "minor_identifiable_detail"
    PROMPT_INJECTION_DETECTED = "prompt_injection_detected"
    IMPROPER_DISTRIBUTION_INSTRUCTION = "improper_distribution_instruction"


class RepairOperation(StrEnum):
    ALIGN_BRAND_TONE = "align_brand_tone"
    REWRITE_HEADING_HIERARCHY = "rewrite_heading_hierarchy"
    SPLIT_DENSE_PARAGRAPH = "split_dense_paragraph"
    QUALIFY_MARKETING_CLAIM = "qualify_marketing_claim"
    SOFTEN_CALL_TO_ACTION = "soften_call_to_action"


class _FrozenModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ReviewIssueContract(_FrozenModel):
    dimension: ReviewDimension
    severity: ReviewSeverity
    repair_operation: RepairOperation | None = None

    @property
    def repairable(self) -> bool:
        return self.repair_operation is not None


_ISSUE_CONTRACTS: Final[dict[ReviewIssueCode, ReviewIssueContract]] = {
    ReviewIssueCode.FACT_NOT_ENTAILED: ReviewIssueContract(
        dimension=ReviewDimension.FACTUAL_GROUNDING,
        severity=ReviewSeverity.CRITICAL,
    ),
    ReviewIssueCode.EVIDENCE_REFERENCE_MISSING: ReviewIssueContract(
        dimension=ReviewDimension.FACTUAL_GROUNDING,
        severity=ReviewSeverity.CRITICAL,
    ),
    ReviewIssueCode.FACTUAL_CONTEXT_AMBIGUOUS: ReviewIssueContract(
        dimension=ReviewDimension.FACTUAL_GROUNDING,
        severity=ReviewSeverity.WARNING,
    ),
    ReviewIssueCode.BRAND_TONE_MISMATCH: ReviewIssueContract(
        dimension=ReviewDimension.BRAND_TONE,
        severity=ReviewSeverity.WARNING,
        repair_operation=RepairOperation.ALIGN_BRAND_TONE,
    ),
    ReviewIssueCode.BRAND_VOICE_AMBIGUOUS: ReviewIssueContract(
        dimension=ReviewDimension.BRAND_TONE,
        severity=ReviewSeverity.WARNING,
    ),
    ReviewIssueCode.HEADING_HIERARCHY_INVALID: ReviewIssueContract(
        dimension=ReviewDimension.STRUCTURE_READABILITY,
        severity=ReviewSeverity.WARNING,
        repair_operation=RepairOperation.REWRITE_HEADING_HIERARCHY,
    ),
    ReviewIssueCode.PARAGRAPH_DENSITY_HIGH: ReviewIssueContract(
        dimension=ReviewDimension.STRUCTURE_READABILITY,
        severity=ReviewSeverity.WARNING,
        repair_operation=RepairOperation.SPLIT_DENSE_PARAGRAPH,
    ),
    ReviewIssueCode.STRUCTURE_AMBIGUOUS: ReviewIssueContract(
        dimension=ReviewDimension.STRUCTURE_READABILITY,
        severity=ReviewSeverity.WARNING,
    ),
    ReviewIssueCode.PRIVACY_RISK: ReviewIssueContract(
        dimension=ReviewDimension.PRIVACY_SAFETY,
        severity=ReviewSeverity.CRITICAL,
    ),
    ReviewIssueCode.SAFETY_RISK: ReviewIssueContract(
        dimension=ReviewDimension.PRIVACY_SAFETY,
        severity=ReviewSeverity.CRITICAL,
    ),
    ReviewIssueCode.MINOR_IDENTIFIABLE_DETAIL: ReviewIssueContract(
        dimension=ReviewDimension.PRIVACY_SAFETY,
        severity=ReviewSeverity.CRITICAL,
    ),
    ReviewIssueCode.PROMPT_INJECTION_DETECTED: ReviewIssueContract(
        dimension=ReviewDimension.INSTRUCTION_BOUNDARY,
        severity=ReviewSeverity.CRITICAL,
    ),
    ReviewIssueCode.IMPROPER_DISTRIBUTION_INSTRUCTION: ReviewIssueContract(
        dimension=ReviewDimension.INSTRUCTION_BOUNDARY,
        severity=ReviewSeverity.CRITICAL,
    ),
    ReviewIssueCode.INSTRUCTION_CONTEXT_AMBIGUOUS: ReviewIssueContract(
        dimension=ReviewDimension.INSTRUCTION_BOUNDARY,
        severity=ReviewSeverity.WARNING,
    ),
    ReviewIssueCode.MARKETING_CLAIM_EXAGGERATED: ReviewIssueContract(
        dimension=ReviewDimension.MARKETING_INTEGRITY,
        severity=ReviewSeverity.WARNING,
        repair_operation=RepairOperation.QUALIFY_MARKETING_CLAIM,
    ),
    ReviewIssueCode.CALL_TO_ACTION_TOO_AGGRESSIVE: ReviewIssueContract(
        dimension=ReviewDimension.MARKETING_INTEGRITY,
        severity=ReviewSeverity.WARNING,
        repair_operation=RepairOperation.SOFTEN_CALL_TO_ACTION,
    ),
    ReviewIssueCode.MARKETING_CONTEXT_AMBIGUOUS: ReviewIssueContract(
        dimension=ReviewDimension.MARKETING_INTEGRITY,
        severity=ReviewSeverity.WARNING,
    ),
}

_HARD_GATE_TO_ISSUE: Final[dict[ReviewHardGateCode, ReviewIssueCode]] = {
    ReviewHardGateCode.FACT_NOT_ENTAILED: ReviewIssueCode.FACT_NOT_ENTAILED,
    ReviewHardGateCode.EVIDENCE_REFERENCE_MISSING: ReviewIssueCode.EVIDENCE_REFERENCE_MISSING,
    ReviewHardGateCode.PRIVACY_RISK: ReviewIssueCode.PRIVACY_RISK,
    ReviewHardGateCode.SAFETY_RISK: ReviewIssueCode.SAFETY_RISK,
    ReviewHardGateCode.MINOR_IDENTIFIABLE_DETAIL: ReviewIssueCode.MINOR_IDENTIFIABLE_DETAIL,
    ReviewHardGateCode.PROMPT_INJECTION_DETECTED: ReviewIssueCode.PROMPT_INJECTION_DETECTED,
    ReviewHardGateCode.IMPROPER_DISTRIBUTION_INSTRUCTION: (
        ReviewIssueCode.IMPROPER_DISTRIBUTION_INSTRUCTION
    ),
}

_REVIEWER_ALLOWED_CODES: Final[frozenset[ReviewIssueCode]] = frozenset(
    set(ReviewIssueCode).difference(_HARD_GATE_TO_ISSUE.values())
)
_ACTIONABLE_REPAIR_REFERENCE_KINDS: Final[frozenset[ReviewReferenceKind]] = frozenset(
    {
        ReviewReferenceKind.ARTICLE,
        ReviewReferenceKind.SECTION,
        ReviewReferenceKind.BLOCK,
    }
)


class ReviewReference(_FrozenModel):
    kind: ReviewReferenceKind
    ref: BoundedIdentifier


class ReviewInputIdentity(_FrozenModel):
    article_ref: BoundedIdentifier
    article_fingerprint: Sha256Hex
    section_refs: tuple[BoundedIdentifier, ...] = Field(min_length=1, max_length=32)
    block_refs: tuple[BoundedIdentifier, ...] = Field(default=(), max_length=128)
    claim_refs: tuple[BoundedIdentifier, ...] = Field(default=(), max_length=64)
    evidence_refs: tuple[BoundedIdentifier, ...] = Field(default=(), max_length=128)

    @model_validator(mode="after")
    def validate_unique_references(self) -> Self:
        for label, refs in (
            ("section", self.section_refs),
            ("block", self.block_refs),
            ("claim", self.claim_refs),
            ("evidence", self.evidence_refs),
        ):
            if len(refs) != len(set(refs)):
                raise ValueError(f"{label} references must be unique")
        return self


class ReviewHardGateFailure(_FrozenModel):
    code: ReviewHardGateCode
    reference: ReviewReference


class ReviewRequest(_FrozenModel):
    schema_version: Literal["official-account-review-request-v1"]
    request_id: BoundedIdentifier
    identity: ReviewInputIdentity
    reviewer_version: BoundedIdentifier
    prompt_version: BoundedIdentifier
    rubric_version: Literal["official-account-editorial-rubric-v1"]
    review_policy_version: Literal["official-account-review-policy-v1"]
    repair_policy_version: Literal["official-account-repair-policy-v1"]
    hard_gate_failures: tuple[ReviewHardGateFailure, ...] = Field(default=(), max_length=8)
    request_fingerprint: Sha256Hex

    @model_validator(mode="after")
    def validate_request(self) -> Self:
        keys = tuple(
            (item.code, item.reference.kind, item.reference.ref) for item in self.hard_gate_failures
        )
        if len(keys) != len(set(keys)):
            raise ValueError("hard-gate failures must be unique")
        dimensions = tuple(
            _ISSUE_CONTRACTS[_HARD_GATE_TO_ISSUE[item.code]].dimension
            for item in self.hard_gate_failures
        )
        if len(dimensions) != len(set(dimensions)):
            raise ValueError("hard-gate failure dimensions must be unique")
        for failure in self.hard_gate_failures:
            _validate_reference_binding(self.identity, failure.reference)
        expected = _request_fingerprint(self)
        if self.request_fingerprint != expected:
            raise ValueError("review request fingerprint changed")
        return self


class ReviewIssue(_FrozenModel):
    code: ReviewIssueCode
    dimension: ReviewDimension
    severity: ReviewSeverity
    source: ReviewIssueSource
    references: tuple[ReviewReference, ...] = Field(min_length=1, max_length=8)

    @model_validator(mode="after")
    def validate_issue(self) -> Self:
        contract = _ISSUE_CONTRACTS[self.code]
        if self.dimension is not contract.dimension or self.severity is not contract.severity:
            raise ValueError("review issue does not match the code-owned taxonomy")
        keys = tuple((item.kind, item.ref) for item in self.references)
        if len(keys) != len(set(keys)):
            raise ValueError("review issue references must be unique")
        if (
            self.source is ReviewIssueSource.HARD_GATE
            and self.code not in _HARD_GATE_TO_ISSUE.values()
        ):
            raise ValueError("hard-gate source requires a hard-gate issue code")
        if self.source is ReviewIssueSource.REVIEWER and self.code not in _REVIEWER_ALLOWED_CODES:
            raise ValueError("Reviewer cannot emit a hard-gate issue code")
        if contract.repairable and not any(
            reference.kind in _ACTIONABLE_REPAIR_REFERENCE_KINDS for reference in self.references
        ):
            raise ValueError("repairable review issue requires an actionable article target")
        return self


class ReviewVerdict(_FrozenModel):
    schema_version: Literal["official-account-review-verdict-v1"]
    decision: ReviewDecision
    request_id: BoundedIdentifier
    request_fingerprint: Sha256Hex
    article_ref: BoundedIdentifier
    article_fingerprint: Sha256Hex
    reviewer_version: BoundedIdentifier
    prompt_version: BoundedIdentifier
    rubric_version: Literal["official-account-editorial-rubric-v1"]
    review_policy_version: Literal["official-account-review-policy-v1"]
    repair_policy_version: Literal["official-account-repair-policy-v1"]
    issues: tuple[ReviewIssue, ...] = Field(default=(), max_length=16)
    unavailable_reason: ReviewUnavailableReason | None = None
    record_fingerprint: Sha256Hex

    @model_validator(mode="after")
    def validate_verdict(self) -> Self:
        issue_keys = tuple(
            (issue.code, tuple((ref.kind, ref.ref) for ref in issue.references))
            for issue in self.issues
        )
        if len(issue_keys) != len(set(issue_keys)):
            raise ValueError("review issues must be unique")
        dimensions = tuple(issue.dimension for issue in self.issues)
        if len(dimensions) != len(set(dimensions)):
            raise ValueError("review issue dimensions must be unique")
        if self.issues != tuple(sorted(self.issues, key=_issue_sort_key)):
            raise ValueError("review issues must use canonical ordering")
        expected_decision = _decision_for(self.issues, self.unavailable_reason)
        if self.decision is not expected_decision:
            raise ValueError("review decision does not match the closed decision policy")
        if self.record_fingerprint != _record_fingerprint(self):
            raise ValueError("review verdict record fingerprint changed")
        return self


class ReviewDimensionDefinition(_FrozenModel):
    dimension: ReviewDimension
    description: str = Field(min_length=1, max_length=400)


class ReviewIssueDefinition(_FrozenModel):
    code: ReviewIssueCode
    dimension: ReviewDimension
    severity: ReviewSeverity
    repairable: bool


class ReviewRubric(_FrozenModel):
    schema_version: Literal["official-account-review-rubric-v1"]
    rubric_version: Literal["official-account-editorial-rubric-v1"]
    review_policy_version: Literal["official-account-review-policy-v1"]
    repair_policy_version: Literal["official-account-repair-policy-v1"]
    dimensions: tuple[ReviewDimensionDefinition, ...]
    issues: tuple[ReviewIssueDefinition, ...]

    @model_validator(mode="after")
    def validate_rubric(self) -> Self:
        dimensions = tuple(item.dimension for item in self.dimensions)
        if len(dimensions) != len(set(dimensions)):
            raise ValueError("rubric dimensions must be unique")
        if set(dimensions) != set(ReviewDimension):
            raise ValueError("rubric must define every review dimension")
        issue_codes = tuple(item.code for item in self.issues)
        if len(issue_codes) != len(set(issue_codes)):
            raise ValueError("rubric issue codes must be unique")
        if set(issue_codes) != set(ReviewIssueCode):
            raise ValueError("rubric must define the complete issue taxonomy")
        for item in self.issues:
            contract = _ISSUE_CONTRACTS[item.code]
            if (
                item.dimension is not contract.dimension
                or item.severity is not contract.severity
                or item.repairable is not contract.repairable
            ):
                raise ValueError("rubric issue does not match the code-owned taxonomy")
        return self


class RepairDirective(_FrozenModel):
    directive_id: BoundedIdentifier
    issue_code: ReviewIssueCode
    target: ReviewReference
    operation: RepairOperation
    repair_policy_version: Literal["official-account-repair-policy-v1"]

    @model_validator(mode="after")
    def validate_directive(self) -> Self:
        contract = _ISSUE_CONTRACTS[self.issue_code]
        if contract.repair_operation is None or self.operation is not contract.repair_operation:
            raise ValueError("repair directive does not match the code-owned repair policy")
        if self.target.kind not in _ACTIONABLE_REPAIR_REFERENCE_KINDS:
            raise ValueError("repair directive requires an actionable article target")
        return self


class ReviewContractError(ValueError):
    """A request, verdict, or repair projection violates the shared contract."""


def build_review_request(
    *,
    request_id: str,
    identity: ReviewInputIdentity,
    reviewer_version: str,
    prompt_version: str,
    hard_gate_failures: tuple[ReviewHardGateFailure, ...] = (),
) -> ReviewRequest:
    fingerprint_payload = {
        "schema_version": REVIEW_REQUEST_SCHEMA_VERSION,
        "request_id": request_id,
        "identity": identity,
        "reviewer_version": reviewer_version,
        "prompt_version": prompt_version,
        "rubric_version": REVIEW_RUBRIC_VERSION,
        "review_policy_version": REVIEW_POLICY_VERSION,
        "repair_policy_version": REPAIR_POLICY_VERSION,
        "hard_gate_failures": hard_gate_failures,
    }
    return ReviewRequest(
        schema_version=REVIEW_REQUEST_SCHEMA_VERSION,
        request_id=request_id,
        identity=identity,
        reviewer_version=reviewer_version,
        prompt_version=prompt_version,
        rubric_version=REVIEW_RUBRIC_VERSION,
        review_policy_version=REVIEW_POLICY_VERSION,
        repair_policy_version=REPAIR_POLICY_VERSION,
        hard_gate_failures=hard_gate_failures,
        request_fingerprint=_fingerprint(fingerprint_payload),
    )


def build_review_issue(
    *,
    code: ReviewIssueCode,
    source: ReviewIssueSource,
    references: tuple[ReviewReference, ...],
) -> ReviewIssue:
    contract = _ISSUE_CONTRACTS[code]
    return ReviewIssue(
        code=code,
        dimension=contract.dimension,
        severity=contract.severity,
        source=source,
        references=references,
    )


def build_review_verdict(
    request: ReviewRequest,
    *,
    reviewer_issues: tuple[ReviewIssue, ...] = (),
    unavailable_reason: ReviewUnavailableReason | None = None,
) -> ReviewVerdict:
    if any(issue.source is not ReviewIssueSource.REVIEWER for issue in reviewer_issues):
        raise ReviewContractError("Reviewer output cannot claim a hard-gate source")
    if unavailable_reason is not None and reviewer_issues:
        raise ReviewContractError("unavailable Reviewer output cannot contain reviewer issues")
    hard_gate_dimensions = {
        _ISSUE_CONTRACTS[_HARD_GATE_TO_ISSUE[failure.code]].dimension
        for failure in request.hard_gate_failures
    }
    issues_by_key = {
        (issue.code, tuple((ref.kind, ref.ref) for ref in issue.references)): issue
        for issue in reviewer_issues
        if issue.dimension not in hard_gate_dimensions
    }
    for failure in request.hard_gate_failures:
        issue = build_review_issue(
            code=_HARD_GATE_TO_ISSUE[failure.code],
            source=ReviewIssueSource.HARD_GATE,
            references=(failure.reference,),
        )
        key = (issue.code, tuple((ref.kind, ref.ref) for ref in issue.references))
        issues_by_key[key] = issue
    issues = tuple(sorted(issues_by_key.values(), key=_issue_sort_key))
    effective_unavailable = unavailable_reason if not request.hard_gate_failures else None
    decision = _decision_for(issues, effective_unavailable)
    fingerprint_payload = {
        "schema_version": REVIEW_VERDICT_SCHEMA_VERSION,
        "decision": decision,
        "request_id": request.request_id,
        "request_fingerprint": request.request_fingerprint,
        "article_ref": request.identity.article_ref,
        "article_fingerprint": request.identity.article_fingerprint,
        "reviewer_version": request.reviewer_version,
        "prompt_version": request.prompt_version,
        "rubric_version": request.rubric_version,
        "review_policy_version": request.review_policy_version,
        "repair_policy_version": request.repair_policy_version,
        "issues": issues,
        "unavailable_reason": effective_unavailable,
    }
    verdict = ReviewVerdict(
        schema_version=REVIEW_VERDICT_SCHEMA_VERSION,
        decision=decision,
        request_id=request.request_id,
        request_fingerprint=request.request_fingerprint,
        article_ref=request.identity.article_ref,
        article_fingerprint=request.identity.article_fingerprint,
        reviewer_version=request.reviewer_version,
        prompt_version=request.prompt_version,
        rubric_version=request.rubric_version,
        review_policy_version=request.review_policy_version,
        repair_policy_version=request.repair_policy_version,
        issues=issues,
        unavailable_reason=effective_unavailable,
        record_fingerprint=_fingerprint(fingerprint_payload),
    )
    validate_review_verdict_binding(request, verdict)
    return verdict


def validate_review_verdict_binding(request: ReviewRequest, verdict: ReviewVerdict) -> None:
    """Bind all verdict identities and references to one typed review input."""

    identity_matches = (
        verdict.request_id == request.request_id
        and verdict.request_fingerprint == request.request_fingerprint
        and verdict.article_ref == request.identity.article_ref
        and verdict.article_fingerprint == request.identity.article_fingerprint
        and verdict.reviewer_version == request.reviewer_version
        and verdict.prompt_version == request.prompt_version
        and verdict.rubric_version == request.rubric_version
        and verdict.review_policy_version == request.review_policy_version
        and verdict.repair_policy_version == request.repair_policy_version
    )
    if not identity_matches:
        raise ReviewContractError("review verdict identity does not match its typed request")
    for issue in verdict.issues:
        for reference in issue.references:
            _validate_reference_binding(request.identity, reference)
    hard_gate_keys = {
        (_HARD_GATE_TO_ISSUE[item.code], item.reference.kind, item.reference.ref)
        for item in request.hard_gate_failures
    }
    verdict_hard_gate_keys = {
        (issue.code, reference.kind, reference.ref)
        for issue in verdict.issues
        if issue.source is ReviewIssueSource.HARD_GATE
        for reference in issue.references
    }
    if verdict_hard_gate_keys != hard_gate_keys:
        raise ReviewContractError("review verdict does not preserve hard-gate failures")


def project_repair_directives(
    request: ReviewRequest,
    verdict: ReviewVerdict,
) -> tuple[RepairDirective, ...]:
    """Project closed repair operations; model-authored instruction text is impossible."""

    validate_review_verdict_binding(request, verdict)
    if any(issue.severity is ReviewSeverity.CRITICAL for issue in verdict.issues):
        return ()
    directives = []
    for ordinal, issue in enumerate(verdict.issues, start=1):
        contract = _ISSUE_CONTRACTS[issue.code]
        if contract.repair_operation is None:
            continue
        target = next(
            reference
            for reference in issue.references
            if reference.kind in _ACTIONABLE_REPAIR_REFERENCE_KINDS
        )
        directives.append(
            RepairDirective(
                directive_id=f"repair:{ordinal:02d}:{issue.code.value}",
                issue_code=issue.code,
                target=target,
                operation=contract.repair_operation,
                repair_policy_version=REPAIR_POLICY_VERSION,
            )
        )
    return tuple(directives)


def active_review_rubric() -> ReviewRubric:
    descriptions = {
        ReviewDimension.FACTUAL_GROUNDING: "Claims remain bound to governed evidence.",
        ReviewDimension.BRAND_TONE: "Tone follows the approved official-account voice.",
        ReviewDimension.STRUCTURE_READABILITY: "Headings and paragraphs remain publication-ready.",
        ReviewDimension.PRIVACY_SAFETY: "Private or unsafe content cannot pass review.",
        ReviewDimension.INSTRUCTION_BOUNDARY: "Untrusted or distribution instructions cannot pass.",
        ReviewDimension.MARKETING_INTEGRITY: "Marketing language remains qualified and restrained.",
    }
    return ReviewRubric(
        schema_version=REVIEW_RUBRIC_SCHEMA_VERSION,
        rubric_version=REVIEW_RUBRIC_VERSION,
        review_policy_version=REVIEW_POLICY_VERSION,
        repair_policy_version=REPAIR_POLICY_VERSION,
        dimensions=tuple(
            ReviewDimensionDefinition(dimension=dimension, description=descriptions[dimension])
            for dimension in ReviewDimension
        ),
        issues=tuple(
            ReviewIssueDefinition(
                code=code,
                dimension=contract.dimension,
                severity=contract.severity,
                repairable=contract.repairable,
            )
            for code, contract in _ISSUE_CONTRACTS.items()
        ),
    )


def issue_contract(code: ReviewIssueCode) -> ReviewIssueContract:
    return _ISSUE_CONTRACTS[code]


def reviewer_issue_allowed(code: ReviewIssueCode) -> bool:
    """Return whether the editorial Reviewer may emit this code directly."""

    return code in _REVIEWER_ALLOWED_CODES


def _decision_for(
    issues: tuple[ReviewIssue, ...],
    unavailable_reason: ReviewUnavailableReason | None,
) -> ReviewDecision:
    if issues and unavailable_reason is not None:
        raise ValueError("unavailable review cannot contain issues")
    if unavailable_reason is not None:
        return ReviewDecision.UNAVAILABLE
    if any(issue.severity is ReviewSeverity.CRITICAL for issue in issues):
        return ReviewDecision.REJECTED
    if any(_ISSUE_CONTRACTS[issue.code].repairable for issue in issues):
        return ReviewDecision.REJECTED
    if issues:
        return ReviewDecision.MANUAL_REVIEW
    return ReviewDecision.ACCEPTED


def _validate_reference_binding(
    identity: ReviewInputIdentity,
    reference: ReviewReference,
) -> None:
    allowed = {
        ReviewReferenceKind.ARTICLE: (identity.article_ref,),
        ReviewReferenceKind.SECTION: identity.section_refs,
        ReviewReferenceKind.BLOCK: identity.block_refs,
        ReviewReferenceKind.CLAIM: identity.claim_refs,
        ReviewReferenceKind.EVIDENCE: identity.evidence_refs,
    }
    if reference.ref not in allowed[reference.kind]:
        raise ReviewContractError("review reference is not declared by the typed input")


def _request_fingerprint(request: ReviewRequest) -> str:
    return _fingerprint(request.model_dump(mode="json", exclude={"request_fingerprint"}))


def _record_fingerprint(verdict: ReviewVerdict) -> str:
    return _fingerprint(verdict.model_dump(mode="json", exclude={"record_fingerprint"}))


def _issue_sort_key(issue: ReviewIssue) -> tuple[str, str, str, tuple[tuple[str, str], ...]]:
    return (
        issue.dimension.value,
        issue.code.value,
        issue.source.value,
        tuple((ref.kind.value, ref.ref) for ref in issue.references),
    )


def _fingerprint(value: object) -> str:
    payload = json.dumps(
        _jsonable(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return sha256(payload.encode("utf-8")).hexdigest()


def _jsonable(value: object) -> object:
    if isinstance(value, BaseModel):
        return _jsonable(value.model_dump(mode="json"))
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value
