from __future__ import annotations

# ruff: noqa: RUF001 -- Chinese punctuation is intentional in the boundary label.
from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.domain.official_account_local import (
    ArticlePackage,
    ArticleValidationIssue,
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
    role: Literal["body", "cover"]
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
    alt_text: str | None = Field(default=None, max_length=160)


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


class OfficialAccountRunDetailResponse(OfficialAccountRunSummaryResponse):
    article: ArticlePackage | None
    validation: OfficialAccountValidationResponse | None
    audit: OfficialAccountAuditVerdict | None
    usage: OfficialAccountUsageResponse | None
    media: list[OfficialAccountMediaResponse]
    body_image: OfficialAccountMediaResponse | None
    body_images: list[OfficialAccountMediaResponse]
    cover_image: OfficialAccountMediaResponse | None
    media_selection: OfficialAccountMediaSelectionResponse
    generated_visuals: list[OfficialAccountGeneratedVisualResponse] = Field(default_factory=list)
    draft: OfficialAccountDraftResponse | None
    manual_review: OfficialAccountManualReviewResponse
