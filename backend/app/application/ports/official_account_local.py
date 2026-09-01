from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol
from uuid import UUID

from app.domain.image_quality_eval import (
    IMAGE_EVAL_SINGLE_IMAGE_DIMENSIONS,
    ImageEvalBatchDecision,
    ImageEvalDecisionKind,
    ImageEvalEvaluatorKind,
    ImageEvalObservation,
    ImageEvalObservationStatus,
    active_image_eval_rubric,
    decide_image_eval_batch,
)
from app.domain.official_account_local import (
    ArticleMediaSelectionSnapshot,
    ArticlePackage,
    ArticleValidationIssue,
    GeneratedArticleDraft,
    GeneratedArticleSection,
    OfficialAccountAuditVerdict,
    OfficialAccountSourceSnapshot,
    RenderedOfficialAccountHtml,
    SemanticMediaAssignment,
    fingerprint,
)


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


@dataclass(frozen=True, slots=True)
class OfficialAccountVersionIdentity:
    provider: Literal["fake", "zhipu"]
    model: str
    generator_prompt_version: str
    article_schema_version: str
    auditor_prompt_version: str
    audit_schema_version: str
    rule_version: str
    renderer_version: str
    style_version: str
    template_version: str
    local_adapter_version: str
    default_author: str
    min_characters: int
    target_min_characters: int
    target_max_characters: int
    max_characters: int
    media_plan_version: str | None = None
    visual_query_version: str | None = None
    visual_selector_version: str | None = None
    generated_visual_plan_version: str | None = None
    generated_visual_prompt_version: str | None = None
    context_media_plan_version: str | None = None


@dataclass(frozen=True, slots=True)
class OfficialAccountGenerationRequest:
    run_id: UUID
    source: OfficialAccountSourceSnapshot
    identity: OfficialAccountVersionIdentity
    request_fingerprint: str
    max_output_tokens: int


@dataclass(frozen=True, slots=True)
class OfficialAccountGenerationResult:
    draft: GeneratedArticleDraft
    provider: str
    model: str
    request_fingerprint: str
    provider_request_id: str | None
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int
    latency_ms: int
    validation_corrections: int = 0


@dataclass(frozen=True, slots=True)
class OfficialAccountAuditRequest:
    run_id: UUID
    source: OfficialAccountSourceSnapshot
    article: ArticlePackage
    identity: OfficialAccountVersionIdentity
    request_fingerprint: str
    max_output_tokens: int


@dataclass(frozen=True, slots=True)
class OfficialAccountAuditResult:
    verdict: OfficialAccountAuditVerdict
    provider: str
    model: str
    request_fingerprint: str
    provider_request_id: str | None
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int
    latency_ms: int
    validation_corrections: int = 0


@dataclass(frozen=True, slots=True)
class ClaimedOfficialAccountRun:
    run_id: UUID
    attempt_number: int
    lease_token: UUID
    generation_mode: Literal["fixture", "live"]
    identity: OfficialAccountVersionIdentity
    current_stage: str


@dataclass(frozen=True, slots=True)
class StoredOfficialAccountArticle:
    id: UUID
    article: ArticlePackage
    validation_issues: tuple[ArticleValidationIssue, ...]
    audit: OfficialAccountAuditVerdict | None
    provider_request_id: str | None
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int
    latency_ms: int
    created_at: datetime

    @property
    def validation_passed(self) -> bool:
        return not any(issue.severity == "error" for issue in self.validation_issues)


@dataclass(frozen=True, slots=True)
class StoredOfficialAccountRender:
    id: UUID
    article_version_id: UUID
    canonical_html: str
    render_fingerprint: str


@dataclass(frozen=True, slots=True)
class StoredOfficialAccountManualReview:
    id: UUID
    run_id: UUID
    decision: Literal["approved", "rejected"]
    reviewer_label: str
    note: str | None
    request_fingerprint: str
    reviewed_at: datetime


@dataclass(frozen=True, slots=True)
class OfficialAccountGeneratedVisualPlan:
    """Safe, durable identity for one generated local body visual.

    Prompt text, provider bodies, catalog raw IDs and storage locations deliberately do not
    appear here.  The public catalog reference and immutable checksums are sufficient to
    reconstruct the bounded prompt at the worker boundary and fence recovery.
    """

    run_id: UUID
    article_version_id: UUID
    render_version_id: UUID
    ordinal: int
    section_index: int
    reference_asset_ref: str
    reference_catalog_version: str
    reference_source_checksum: str
    reference_publication_checksum: str
    selection_method: Literal["deterministic_tag", "multimodal_embedding"]
    similarity_band: Literal["very_high", "high", "medium", "low"] | None
    request_fingerprint: str
    plan_version: str
    prompt_version: str
    provider: Literal["fake", "toapis", "comfly"]
    model: str
    block_index: int | None = None
    block_kind: Literal["paragraph", "bullet_list", "quote", "callout"] | None = None
    block_fingerprint: str | None = None
    reference_input_version: str | None = None
    reference_input_checksum: str | None = None
    output_profile_version: str | None = None


@dataclass(frozen=True, slots=True)
class StoredOfficialAccountGeneratedVisual:
    id: UUID
    plan: OfficialAccountGeneratedVisualPlan
    status: Literal["generating", "ready", "failed", "result_unknown"]
    media_type: str | None
    byte_size: int | None
    sha256: str | None
    width: int | None
    height: int | None
    error_code: str | None
    created_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class OfficialAccountGeneratedVisualResult:
    media_type: str
    byte_size: int
    sha256: str
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class OfficialAccountGeneratedVisualEvalResult:
    """Safe aggregate audit result bound to final publication bytes."""

    publication_sha256: str
    evaluator_version: str
    audit_prompt_version: str
    rubric_version: str
    decision_policy_version: str
    request_fingerprint: str
    observations: tuple[ImageEvalObservation, ...]
    decision: ImageEvalBatchDecision
    provider: str | None = None
    model: str | None = None

    def __post_init__(self) -> None:
        if not _is_sha256(self.publication_sha256) or not _is_sha256(self.request_fingerprint):
            raise ValueError("generated visual eval hashes must be SHA-256")
        for field_name, value in (
            ("evaluator version", self.evaluator_version),
            ("audit prompt version", self.audit_prompt_version),
            ("rubric version", self.rubric_version),
            ("decision policy version", self.decision_policy_version),
        ):
            if not value.strip() or len(value) > 80:
                raise ValueError(f"generated visual eval {field_name} is invalid")
        observations = tuple(self.observations)
        if {item.dimension for item in observations} != set(IMAGE_EVAL_SINGLE_IMAGE_DIMENSIONS):
            raise ValueError("generated visual eval must cover the five single-image dimensions")
        if any(item.publication_sha256 != self.publication_sha256 for item in observations):
            raise ValueError("generated visual eval observation hash changed")
        if len({item.dimension for item in observations}) != len(observations):
            raise ValueError("generated visual eval observation dimensions must be unique")
        if len({item.subject_ref for item in observations}) != 1:
            raise ValueError("generated visual eval observation subject changed")
        if any(
            item.evaluator_kind is not ImageEvalEvaluatorKind.PROVIDER_AUDIT
            or item.evaluator_version != self.evaluator_version
            or item.rubric_version != self.rubric_version
            or item.request_fingerprint != self.request_fingerprint
            or item.provider != self.provider
            or item.model != self.model
            for item in observations
        ):
            raise ValueError("generated visual eval observation identity changed")
        if self.decision.decision_policy_version != self.decision_policy_version:
            raise ValueError("generated visual eval decision policy changed")
        active_rubric = active_image_eval_rubric()
        if (
            self.rubric_version == active_rubric.rubric_version
            and self.decision_policy_version == active_rubric.decision_policy_version
        ):
            recomputed = decide_image_eval_batch(observations, active_rubric)
            if recomputed != self.decision:
                raise ValueError("generated visual eval decision does not match observations")
        if self.decision.decision is ImageEvalDecisionKind.UNAVAILABLE:
            if self.provider is not None or self.model is not None:
                raise ValueError("unavailable generated visual eval cannot claim provider identity")
            if any(
                item.status is not ImageEvalObservationStatus.UNAVAILABLE for item in observations
            ):
                raise ValueError("unavailable generated visual eval must be wholly unavailable")
        elif not self.provider or not self.model:
            raise ValueError("available generated visual eval requires provider identity")
        object.__setattr__(self, "observations", observations)

    @property
    def issue_codes(self) -> tuple[str, ...]:
        return tuple(code.value for code in self.decision.reason_codes)


def generated_visual_eval_record_fingerprint(
    *,
    generated_visual_id: UUID,
    run_id: UUID,
    result: OfficialAccountGeneratedVisualEvalResult,
) -> str:
    """Derive one immutable record identity from normalized, content-bearing fields."""

    observations = tuple(
        item.model_dump(mode="json")
        for item in sorted(result.observations, key=lambda item: item.dimension.value)
    )
    return fingerprint(
        "official-account-generated-visual-eval-record-v1",
        generated_visual_id,
        run_id,
        result.publication_sha256,
        result.evaluator_version,
        result.audit_prompt_version,
        result.rubric_version,
        result.decision_policy_version,
        result.request_fingerprint,
        result.provider,
        result.model,
        observations,
        result.decision.model_dump(mode="json"),
    )


@dataclass(frozen=True, slots=True)
class StoredOfficialAccountGeneratedVisualEval:
    id: UUID
    generated_visual_id: UUID
    run_id: UUID
    record_fingerprint: str
    result: OfficialAccountGeneratedVisualEvalResult
    completed_at: datetime

    def __post_init__(self) -> None:
        expected = generated_visual_eval_record_fingerprint(
            generated_visual_id=self.generated_visual_id,
            run_id=self.run_id,
            result=self.result,
        )
        if self.record_fingerprint != expected:
            raise ValueError("generated visual eval record fingerprint changed")


@dataclass(frozen=True, slots=True)
class OfficialAccountSourceMedia:
    source_image_artifact_id: UUID | None
    fixture_id: str | None
    media_type: str
    byte_size: int
    sha256: str
    ordinal: int = 0
    semantic_label: str = "正文主图"
    selection_reason: str = "已通过上游图片校验与审校"
    candidate_id: str = ""
    semantic_tags: tuple[str, ...] = ()
    alt_text: str = ""
    caption_text: str = ""
    publication_priority: int = 100
    assigned_section_index: int | None = None
    score_band: Literal["heading", "body", "fallback"] | None = None
    selection_reason_code: str | None = None
    selection_method: Literal["deterministic_tag", "multimodal_embedding"] = "deterministic_tag"
    similarity_band: Literal["very_high", "high", "medium", "low"] | None = None
    catalog_asset_id: str | None = None
    catalog_asset_ref: str | None = None
    catalog_version: str | None = None
    source_master_sha256: str | None = None
    generated_visual_id: UUID | None = None
    source_article_image_id: UUID | None = None
    source_page_url: str | None = None
    image_url: str | None = None
    credit: str | None = None
    rights_status: str | None = None
    context_only_not_evidence: bool = False
    width: int | None = None
    height: int | None = None


@dataclass(frozen=True, slots=True)
class OfficialAccountMediaRequest:
    run_id: UUID
    render_version_id: UUID
    source_image_artifact_id: UUID | None
    fixture_id: str | None
    role: Literal["body", "cover", "context"]
    ordinal: int
    source_sha256: str
    media_type: str
    byte_size: int
    local_adapter_version: str
    request_fingerprint: str
    catalog_asset_id: str | None = None
    catalog_asset_ref: str | None = None
    catalog_version: str | None = None
    source_master_sha256: str | None = None
    source_article_image_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class OfficialAccountMediaResult:
    local_media_id: str
    role: Literal["body", "cover", "context"]
    ordinal: int
    media_url: str
    media_type: str
    byte_size: int
    sha256: str
    semantic_label: str | None = None
    assigned_section_index: int | None = None
    score_band: Literal["heading", "body", "fallback"] | None = None
    selection_reason_code: str | None = None
    selection_method: Literal["deterministic_tag", "multimodal_embedding"] | None = None
    similarity_band: Literal["very_high", "high", "medium", "low"] | None = None
    alt_text: str | None = None
    provenance_kind: str | None = None
    source_page_url: str | None = None
    caption: str | None = None
    credit: str | None = None
    rights_status: str | None = None
    context_only_not_evidence: bool = False


@dataclass(frozen=True, slots=True)
class OfficialAccountMediaSelectionResult:
    assignments: tuple[SemanticMediaAssignment, ...]
    snapshot: ArticleMediaSelectionSnapshot
    candidates: tuple[OfficialAccountSourceMedia, ...]


@dataclass(frozen=True, slots=True)
class OfficialAccountDraftRequest:
    run_id: UUID
    render_version_id: UUID
    title: str
    digest: str
    author: str
    resolved_html: str
    body_media: OfficialAccountMediaResult
    cover_media: OfficialAccountMediaResult
    request_fingerprint: str
    body_media_items: tuple[OfficialAccountMediaResult, ...] = ()
    context_media_items: tuple[OfficialAccountMediaResult, ...] = ()


@dataclass(frozen=True, slots=True)
class OfficialAccountDraftResult:
    local_draft_id: str
    simulation: Literal[True]
    resolved_html: str


class OfficialAccountArticleGenerator(Protocol):
    async def generate(
        self,
        request: OfficialAccountGenerationRequest,
    ) -> OfficialAccountGenerationResult: ...


class OfficialAccountArticleAuditor(Protocol):
    async def audit(
        self,
        request: OfficialAccountAuditRequest,
    ) -> OfficialAccountAuditResult: ...


class OfficialAccountMediaAdapter(Protocol):
    async def stage(
        self,
        request: OfficialAccountMediaRequest,
    ) -> OfficialAccountMediaResult: ...


class OfficialAccountGeneratedVisualStore(Protocol):
    async def put_immutable(self, body: bytes, *, media_type: str = "image/png") -> Any: ...


class OfficialAccountDraftAdapter(Protocol):
    async def create(
        self,
        request: OfficialAccountDraftRequest,
    ) -> OfficialAccountDraftResult: ...


class OfficialAccountCatalogMediaProvider(Protocol):
    async def load_candidates(self) -> tuple[OfficialAccountSourceMedia, ...]: ...

    async def revalidate_candidate(
        self,
        candidate: OfficialAccountSourceMedia,
    ) -> OfficialAccountSourceMedia: ...

    async def catalog_is_current(
        self,
        candidates: tuple[OfficialAccountSourceMedia, ...],
    ) -> bool: ...

    async def read_publication_bytes(
        self,
        *,
        catalog_asset_ref: str,
        catalog_version: str,
        source_master_sha256: str,
        publication_sha256: str,
    ) -> bytes: ...


class OfficialAccountMediaSemanticRanker(Protocol):
    async def select(
        self,
        *,
        topic_title: str,
        sections: tuple[GeneratedArticleSection, ...],
        candidates: tuple[OfficialAccountSourceMedia, ...],
        enabled: bool,
        media_plan_version: str,
    ) -> OfficialAccountMediaSelectionResult: ...


class OfficialAccountRunRepository(Protocol):
    async def claim(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
        max_attempts: int,
    ) -> ClaimedOfficialAccountRun | None: ...

    async def heartbeat(
        self,
        *,
        claimed: ClaimedOfficialAccountRun,
        lease_seconds: int,
    ) -> bool: ...

    async def load_source(
        self,
        claimed: ClaimedOfficialAccountRun,
    ) -> OfficialAccountSourceSnapshot: ...

    async def load_source_media(
        self,
        claimed: ClaimedOfficialAccountRun,
    ) -> OfficialAccountSourceMedia: ...

    async def load_source_media_candidates(
        self,
        claimed: ClaimedOfficialAccountRun,
    ) -> tuple[OfficialAccountSourceMedia, ...]: ...

    async def load_news_context_candidates(
        self,
        claimed: ClaimedOfficialAccountRun,
    ) -> tuple[OfficialAccountSourceMedia, ...]: ...

    async def get_article(self, run_id: UUID) -> StoredOfficialAccountArticle | None: ...

    async def get_render(self, run_id: UUID) -> StoredOfficialAccountRender | None: ...

    async def get_media(
        self,
        run_id: UUID,
        role: Literal["body", "cover", "context"],
        ordinal: int = 0,
    ) -> tuple[UUID, OfficialAccountMediaResult] | None: ...

    async def list_media(
        self,
        run_id: UUID,
        role: Literal["body", "cover", "context"] | None = None,
    ) -> tuple[tuple[UUID, OfficialAccountMediaResult], ...]: ...

    async def get_draft(self, run_id: UUID) -> object | None: ...

    async def get_manual_review(
        self,
        run_id: UUID,
    ) -> StoredOfficialAccountManualReview | None: ...

    async def get_generated_visual(
        self,
        *,
        run_id: UUID,
        ordinal: int,
    ) -> StoredOfficialAccountGeneratedVisual | None: ...

    async def list_generated_visuals(
        self,
        *,
        run_id: UUID,
    ) -> tuple[StoredOfficialAccountGeneratedVisual, ...]: ...

    async def list_generated_visual_evals(
        self,
        *,
        run_id: UUID,
    ) -> tuple[StoredOfficialAccountGeneratedVisualEval, ...]: ...

    async def create_generated_visual_intent(
        self,
        *,
        claimed: ClaimedOfficialAccountRun,
        plan: OfficialAccountGeneratedVisualPlan,
    ) -> StoredOfficialAccountGeneratedVisual | None: ...

    async def persist_generated_visual(
        self,
        *,
        claimed: ClaimedOfficialAccountRun,
        plan: OfficialAccountGeneratedVisualPlan,
        result: OfficialAccountGeneratedVisualResult,
        eval_result: OfficialAccountGeneratedVisualEvalResult | None = None,
    ) -> StoredOfficialAccountGeneratedVisual | None: ...

    async def fail_generated_visual(
        self,
        *,
        claimed: ClaimedOfficialAccountRun,
        plan: OfficialAccountGeneratedVisualPlan,
        error_code: str,
        result_unknown: bool = False,
    ) -> bool: ...

    async def persist_article(
        self,
        *,
        claimed: ClaimedOfficialAccountRun,
        article: ArticlePackage,
        result: OfficialAccountGenerationResult,
        validation_issues: tuple[ArticleValidationIssue, ...],
    ) -> StoredOfficialAccountArticle | None: ...

    async def persist_audit(
        self,
        *,
        claimed: ClaimedOfficialAccountRun,
        article: StoredOfficialAccountArticle,
        result: OfficialAccountAuditResult,
    ) -> StoredOfficialAccountArticle | None: ...

    async def persist_render(
        self,
        *,
        claimed: ClaimedOfficialAccountRun,
        article: StoredOfficialAccountArticle,
        rendered: RenderedOfficialAccountHtml,
    ) -> StoredOfficialAccountRender | None: ...

    async def persist_media(
        self,
        *,
        claimed: ClaimedOfficialAccountRun,
        render: StoredOfficialAccountRender,
        source_media: OfficialAccountSourceMedia,
        request_fingerprint: str,
        result: OfficialAccountMediaResult,
    ) -> tuple[UUID, OfficialAccountMediaResult] | None: ...

    async def persist_draft(
        self,
        *,
        claimed: ClaimedOfficialAccountRun,
        render: StoredOfficialAccountRender,
        body_media_id: UUID,
        body_media_ids: tuple[UUID, ...],
        cover_media_id: UUID,
        request_fingerprint: str,
        result: OfficialAccountDraftResult,
    ) -> object | None: ...

    async def fail(
        self,
        *,
        claimed: ClaimedOfficialAccountRun,
        error_code: str,
        retryable: bool,
        retry_base_seconds: int,
        max_attempts: int,
        result_unknown: bool = False,
        safe_metadata: dict[str, object] | None = None,
    ) -> bool: ...
