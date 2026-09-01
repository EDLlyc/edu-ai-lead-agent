from __future__ import annotations

# ruff: noqa: RUF001 -- Chinese punctuation is intentional in the boundary label.
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.official_account_local import (
    ArticleMediaSelectionSnapshot,
    ArticleMediaSlot,
    ArticlePackage,
    ArticleQualitySummary,
    ArticleSection,
    ArticleSourceProjection,
    ArticleValidationIssue,
    ArticleVersionBundle,
    GeneratedArticleClaim,
    OfficialAccountAuditVerdict,
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OfficialAccountMaterialSourceRequest(_StrictModel):
    kind: Literal["material_package"]
    material_package_id: UUID


class OfficialAccountFixtureSourceRequest(_StrictModel):
    kind: Literal["fixture"]
    fixture_id: Literal["official-account-article-v1"] = "official-account-article-v1"


OfficialAccountSourceRequest = Annotated[
    OfficialAccountMaterialSourceRequest | OfficialAccountFixtureSourceRequest,
    Field(discriminator="kind"),
]


class OfficialAccountRunCreateRequest(_StrictModel):
    source: OfficialAccountSourceRequest
    generation_mode: Literal["fixture", "live"]

    @model_validator(mode="after")
    def validate_source_mode(self) -> OfficialAccountRunCreateRequest:
        expected = "fixture" if self.source.kind == "fixture" else "live"
        if self.generation_mode != expected:
            raise ValueError("official-account source and generation mode must match")
        return self


class EligibleMaterialPackageResponse(_StrictModel):
    id: UUID
    title: str
    status: str
    review_status: str


class OfficialAccountCapabilitiesResponse(_StrictModel):
    enabled: bool
    simulation: Literal[True] = True
    fixture_available: bool
    fixture_id: Literal["official-account-article-v1"] = "official-account-article-v1"
    live_available: bool
    live_unavailable_reason: str | None = None
    eligible_material_packages: list[EligibleMaterialPackageResponse] = Field(default_factory=list)
    boundary_label: Literal["本地模拟，未同步公众号"] = "本地模拟，未同步公众号"
    visual_semantic_enabled: bool = False
    visual_semantic_provider_mode: Literal["disabled", "fake", "alibaba"] = "disabled"
    generated_visuals_enabled: bool = False
    editor_handoff_enabled: bool = False
    editor_handoff_v2_enabled: bool = False
    editor_handoff_release_policy: Literal["manual_only", "quality_auto"] = "manual_only"


class OfficialAccountRunSummaryResponse(_StrictModel):
    id: UUID
    source_kind: Literal["material_package", "fixture"]
    material_package_id: UUID | None
    fixture_id: str | None
    generation_mode: Literal["fixture", "live"]
    provider: Literal["fake", "zhipu"]
    model: str
    request_fingerprint: str
    status: Literal[
        "queued",
        "running",
        "review_required",
        "ready",
        "failed",
        "result_unknown",
    ]
    current_stage: Literal[
        "queued",
        "generating",
        "validating",
        "auditing",
        "rendering",
        "generating_body_visuals",
        "staging_body_media",
        "staging_cover",
        "creating_local_draft",
        "ready",
        "review_required",
        "failed",
        "result_unknown",
    ]
    attempt_count: int = Field(ge=0)
    error_code: str | None
    error_retryable: bool
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    detail_url: str
    retry_url: str
    simulation: Literal[True] = True
    boundary_label: Literal["本地模拟，未同步公众号"] = "本地模拟，未同步公众号"


class OfficialAccountRunListResponse(_StrictModel):
    items: list[OfficialAccountRunSummaryResponse]
    count: int = Field(ge=0)


class OfficialAccountUsageResponse(_StrictModel):
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    reasoning_tokens: int = Field(ge=0)
    latency_ms: int = Field(ge=0)
    safe_provider_request_id: str | None


class OfficialAccountValidationResponse(_StrictModel):
    passed: bool
    issues: list[ArticleValidationIssue]


class OfficialAccountMediaResponse(_StrictModel):
    local_media_id: str
    role: Literal["body", "cover", "context"]
    ordinal: int = Field(ge=0)
    media_url: str
    media_type: str
    byte_size: int = Field(gt=0)
    sha256: str
    semantic_label: str | None = None
    assigned_section_index: int | None = Field(default=None, ge=0, le=6)
    score_band: Literal["heading", "body", "fallback"] | None = None
    selection_reason_code: (
        Literal[
            "semantic_heading_match",
            "semantic_body_match",
            "stable_fallback",
            "multimodal_similarity",
        ]
        | None
    ) = None
    selection_method: Literal["deterministic_tag", "multimodal_embedding"] | None = None
    similarity_band: Literal["very_high", "high", "medium", "low"] | None = None
    alt_text: str | None = Field(default=None, max_length=200)
    provenance_kind: (
        Literal[
            "source_news",
            "approved_catalog",
            "generated_visual",
            "image_artifact",
            "fixture",
        ]
        | None
    ) = None
    source_page_url: str | None = Field(default=None, max_length=2_048)
    caption: str | None = Field(default=None, max_length=300)
    credit: str | None = Field(default=None, max_length=200)
    rights_status: Literal["publish_permission_unverified"] | None = None
    context_only_not_evidence: bool = False


class OfficialAccountEmbeddingIdentityResponse(_StrictModel):
    provider: Literal["alibaba-model-studio"]
    model: Literal["qwen3-vl-embedding"]
    dimensions: Literal[2048]
    input_policy_version: Literal["brand-visual-embedding-input-v2"]


class OfficialAccountMediaSelectionResponse(_StrictModel):
    policy_version: str = Field(min_length=1, max_length=120)
    body_image_count: int = Field(ge=0, le=5)
    target_body_image_count: str = Field(min_length=1, max_length=100)
    safely_degraded: bool
    explanation: list[Annotated[str, Field(min_length=1, max_length=240)]] = Field(max_length=8)
    selection_mode: Literal[
        "multimodal_embedding",
        "deterministic_fallback",
        "historical",
    ] = "historical"
    semantic_status: Literal[
        "semantic_ready",
        "semantic_unavailable",
        "single_candidate",
        "not_applicable",
    ] = "not_applicable"
    semantic_unavailable_reason: str | None = Field(default=None, max_length=80)
    visual_query_version: str | None = Field(default=None, max_length=80)
    visual_selector_version: str | None = Field(default=None, max_length=80)
    embedding_identity: OfficialAccountEmbeddingIdentityResponse | None = None


class OfficialAccountGeneratedVisualResponse(_StrictModel):
    ordinal: int = Field(ge=0, le=4)
    section_index: int = Field(ge=0, le=6)
    block_index: int | None = Field(default=None, ge=0, le=12)
    block_kind: Literal["paragraph", "bullet_list", "quote", "callout"] | None = None
    reference_asset_ref: str = Field(pattern=r"^[0-9a-f]{16}$")
    selection_method: Literal["deterministic_tag", "multimodal_embedding"]
    similarity_band: Literal["very_high", "high", "medium", "low"] | None = None
    status: Literal["generating", "ready", "failed", "result_unknown"]
    request_fingerprint: str
    plan_version: str = Field(min_length=1, max_length=80)
    prompt_version: str = Field(min_length=1, max_length=80)
    output_profile_version: str | None = Field(default=None, max_length=80)
    provider: Literal["fake", "toapis", "comfly"]
    model: str = Field(min_length=1, max_length=120)
    media_type: str | None = None
    byte_size: int | None = Field(default=None, gt=0)
    sha256: str | None = None
    width: int | None = Field(default=None, ge=1, le=8192)
    height: int | None = Field(default=None, ge=1, le=8192)
    error_code: str | None = Field(default=None, max_length=80)


class OfficialAccountDraftResponse(_StrictModel):
    local_draft_id: str
    state: Literal["ready", "failed", "result_unknown"]
    simulation: Literal[True]
    preview_url: str
    resolved_fingerprint: str
    created_at: datetime
    boundary_label: Literal["本地模拟，未同步公众号"] = "本地模拟，未同步公众号"


class OfficialAccountManualReviewRequest(_StrictModel):
    decision: Literal["approved", "rejected"]
    reviewer_label: str = Field(min_length=1, max_length=80)
    note: str | None = Field(default=None, max_length=2_000)

    @field_validator("reviewer_label")
    @classmethod
    def normalize_reviewer_label(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("reviewer label cannot be blank")
        return normalized

    @field_validator("note")
    @classmethod
    def normalize_note(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class OfficialAccountManualReviewResponse(_StrictModel):
    status: Literal["pending", "approved", "rejected"]
    review_id: UUID | None = None
    reviewer_label: str | None = None
    note: str | None = None
    reviewed_at: datetime | None = None
    request_fingerprint: str | None = None
    idempotent_replay: bool = False
    editorially_approved: bool = False


class OfficialAccountNewsContextItemResponse(_StrictModel):
    ordinal: int = Field(ge=0, le=1)
    section_index: int = Field(ge=0, le=6)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    media_type: Literal["image/jpeg", "image/png", "image/webp"]
    width: int = Field(ge=320, le=8192)
    height: int = Field(ge=180, le=8192)
    alt_text: str = Field(min_length=1, max_length=200)
    caption: str | None = Field(default=None, max_length=300)
    credit: str | None = Field(default=None, max_length=200)
    source_page_url: str = Field(min_length=1, max_length=2_048)
    rights_status: Literal["publish_permission_unverified"]
    context_only_not_evidence: Literal[True]


class OfficialAccountNewsContextResponse(_StrictModel):
    selection_version: Literal["official-account-news-context-selection-v1"]
    status: Literal["not_present", "partial", "ready"]
    items: tuple[OfficialAccountNewsContextItemResponse, ...] = Field(max_length=2)


class OfficialAccountArticleResponse(_StrictModel):
    """Safe article projection; internal source-image row IDs never cross the API."""

    title: str
    digest: str
    author: str
    lead: str
    sections: tuple[ArticleSection, ...]
    conclusion: str
    claims: tuple[GeneratedArticleClaim, ...]
    sources: tuple[ArticleSourceProjection, ...]
    media_slots: tuple[ArticleMediaSlot, ...]
    topic_title: str
    quality: ArticleQualitySummary
    versions: ArticleVersionBundle
    media_selection: ArticleMediaSelectionSnapshot | None = None
    news_context_media: OfficialAccountNewsContextResponse | None = None
    content_fingerprint: str

    @classmethod
    def from_domain(cls, article: ArticlePackage) -> OfficialAccountArticleResponse:
        payload = article.model_dump(mode="python")
        context = article.news_context_media
        if context is not None:
            payload["news_context_media"] = {
                "selection_version": context.selection_version,
                "status": context.status,
                "items": [
                    item.model_dump(mode="python", exclude={"source_article_image_id"})
                    for item in context.items
                ],
            }
        return cls.model_validate(payload)


class OfficialAccountRunDetailResponse(OfficialAccountRunSummaryResponse):
    article: OfficialAccountArticleResponse | None
    validation: OfficialAccountValidationResponse | None
    audit: OfficialAccountAuditVerdict | None
    usage: OfficialAccountUsageResponse | None
    media: list[OfficialAccountMediaResponse]
    body_image: OfficialAccountMediaResponse | None
    body_images: list[OfficialAccountMediaResponse]
    context_images: list[OfficialAccountMediaResponse] = Field(default_factory=list, max_length=2)
    context_media_status: Literal["not_present", "partial", "ready"] = "not_present"
    cover_image: OfficialAccountMediaResponse | None
    media_selection: OfficialAccountMediaSelectionResponse
    generated_visuals: list[OfficialAccountGeneratedVisualResponse] = Field(default_factory=list)
    draft: OfficialAccountDraftResponse | None
    manual_review: OfficialAccountManualReviewResponse


class OfficialAccountEditorHandoffIdentityResponse(_StrictModel):
    renderer_version: Literal[
        "wechat-editor-handoff-renderer-v1-gzh-xiaosai",
        "wechat-editor-handoff-renderer-v2-gzh-xiaosai-semantic",
    ]
    style_version: Literal[
        "wechat-editor-handoff-style-v1-xiaosai-blue",
        "wechat-editor-handoff-style-v2-xiaosai-adaptive",
    ]
    template_version: Literal[
        "wechat-editor-handoff-template-v1-moyu-layout",
        "wechat-editor-handoff-template-v2-block-interleaved-mobile",
    ]
    bundle_version: Literal[
        "official-account-editor-handoff-bundle-v1",
        "official-account-editor-handoff-bundle-v2",
    ]
    preflight_version: Literal[
        "wechat-editor-handoff-preflight-v1", "wechat-editor-handoff-preflight-v2"
    ]
    rights_policy_version: Literal["editor-handoff-context-rights-v1-direct-use-disclosed"]
    theme_id: Literal["xiaosai-moyu-layout-v1"]
    theme_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    release_policy_version: Literal["editor-handoff-release-policy-v2"] | None = None
    placement_version: Literal["editor-handoff-context-placement-v2"] | None = None
    emphasis_version: Literal["editor-handoff-semantic-emphasis-v2"] | None = None
    recipe_version: Literal["editor-handoff-layout-recipe-v2"] | None = None
    mobile_binding_version: Literal["editor-handoff-mobile-binding-v2"] | None = None
    body_visual_lineage_version: Literal["editor-handoff-body-visual-lineage-v1"] | None = None


class OfficialAccountEditorHandoffReleaseResponse(_StrictModel):
    policy: Literal["manual_only", "quality_auto"]
    policy_version: Literal["editor-handoff-release-policy-v2"]
    kind: Literal["manual", "machine"]
    decision: Literal["released"]
    input_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    gate_codes: tuple[str, ...] = Field(min_length=1)
    manual_review_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")


class OfficialAccountEditorHandoffPlacementResponse(_StrictModel):
    media_name: str = Field(pattern=r"^context-0[01]\.(?:jpg|png|webp)$")
    section_index: int = Field(ge=0, le=6)
    target_block_index: int = Field(ge=0, le=49)
    insertion: Literal["after"]
    reason_code: Literal["semantic_text_overlap", "first_prose_fallback", "collision_shifted"]
    algorithm_version: Literal["editor-handoff-context-placement-v2"]
    matched_terms: tuple[str, ...] = Field(max_length=6)


class OfficialAccountEditorHandoffCheckResponse(_StrictModel):
    code: str = Field(pattern=r"^[a-z][a-z0-9_]*$", max_length=100)
    severity: Literal["info", "warning", "error"]
    passed: bool
    field: str = Field(min_length=1, max_length=120)
    detail: str = Field(min_length=1, max_length=500)


class OfficialAccountEditorHandoffMediaResponse(_StrictModel):
    name: str = Field(pattern=r"^(?:body-0[0-4]|context-0[01]|cover-wide)\.(?:jpg|png|webp)$")
    role: Literal["body", "context", "cover"]
    ordinal: int = Field(ge=0, le=49)
    download_url: str
    media_type: Literal["image/jpeg", "image/png", "image/webp"]
    byte_size: int = Field(gt=0)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    width: int = Field(ge=1, le=8192)
    height: int = Field(ge=1, le=8192)
    alt_text: str = Field(min_length=1, max_length=200)
    assigned_section_index: int | None = Field(default=None, ge=0, le=6)
    source_page_url: str | None = Field(default=None, max_length=2048)
    credit: str | None = Field(default=None, max_length=200)
    rights_status: Literal["publish_permission_unverified"] | None = None
    context_only_not_evidence: bool = False
    placement: OfficialAccountEditorHandoffPlacementResponse | None = None


class OfficialAccountEditorHandoffMobileResponse(_StrictModel):
    status: Literal["not_run", "passed"]
    viewports: tuple[Literal[320], Literal[430]] = (320, 430)
    version: Literal["editor-handoff-mobile-binding-v2"] | None = None
    content_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    body_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    media_sha256s: tuple[Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")], ...] = ()
    external_requests: Literal[0] | None = None
    copy_root_matches_body: Literal[True] | None = None


class OfficialAccountEditorHandoffResponse(_StrictModel):
    state: Literal["blocked", "ready"]
    copy_ready: bool
    simulation: Literal[True] = True
    local_only: Literal[True] = True
    published: Literal[False] = False
    boundary_label: Literal["本地交接，未同步公众号"] = "本地交接，未同步公众号"
    fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    content_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    artifact_fingerprint: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    identity: OfficialAccountEditorHandoffIdentityResponse | None = None
    release: OfficialAccountEditorHandoffReleaseResponse | None = None
    recipe: Literal["news_analysis", "tutorial_list", "case_opinion", "analysis"] | None = None
    placements: list[OfficialAccountEditorHandoffPlacementResponse] = Field(default_factory=list)
    checks: list[OfficialAccountEditorHandoffCheckResponse]
    blocking_codes: list[str]
    warning_codes: list[str]
    media: list[OfficialAccountEditorHandoffMediaResponse]
    mobile_validation: OfficialAccountEditorHandoffMobileResponse
    body_url: str | None = None
    preview_url: str | None = None
    bundle_url: str | None = None
    bundle_filename: str | None = Field(default=None, max_length=120)
    bundle_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
