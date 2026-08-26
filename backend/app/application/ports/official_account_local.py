from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Protocol
from uuid import UUID

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
)


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
