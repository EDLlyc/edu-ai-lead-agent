from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class MaterialPackageCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    copy_generation_run_id: UUID
    reviewer: str = Field(default="internal", min_length=1, max_length=120)


class MaterialReviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    decision: Literal["approved", "rejected"]
    reviewer: str = Field(min_length=1, max_length=120)
    note: str | None = Field(default=None, max_length=500)


class ImageStorageMetadataResponse(BaseModel):
    access: Literal["private"]
    immutable: bool
    content_addressed: bool


class VisualTextLayerResponse(BaseModel):
    title: str
    learning_line: str
    keywords: list[str]
    brand_values: list[str]


class VisualBriefResponse(BaseModel):
    version: str
    category: str
    learning_goal: str
    scene: str
    main_action: str
    characters: list[str]
    asset_tags: list[str]
    reference_roles: list[str]
    render_text_mode: str
    text_layer: VisualTextLayerResponse


class VisualReferenceResponse(BaseModel):
    role: Literal["identity_reference", "action_reference", "style_reference", "legacy"]
    asset_id: str
    filename: str
    sha256: str
    selection_reason: str
    fallback: bool


class ControlledVisualPlanResponse(BaseModel):
    scene: Literal[
        "science_lab",
        "robotics_workshop",
        "ai_studio",
        "space_observatory",
        "science_library",
        "innovation_exhibition",
        "campus_maker_space",
        "field_observation_station",
        "engineering_test_field",
        "future_classroom",
    ]
    composition: Literal[
        "central_hero",
        "left_right_dialogue",
        "over_shoulder",
        "diagonal_action",
        "foreground_object",
        "split_depth",
        "top_down_workbench",
        "wide_environment",
    ]
    camera: Literal[
        "eye_level_medium",
        "low_angle_wide",
        "high_angle",
        "close_up_detail",
        "wide_establishing",
    ]
    cast: Literal["xiaosai_solo", "sai_xiansheng_solo", "duo"]
    slot_tone: Literal["fresh_start", "analytical_focus", "reflective_discovery"]
    subject: Literal[
        "robot_arm",
        "ai_sensor_console",
        "telescope_star_map",
        "microscope_sample",
        "experiment_apparatus",
        "science_book_model",
        "rocket_satellite_model",
        "competition_prototype",
    ]
    relaxation_codes: list[str] = Field(default_factory=list, max_length=8)


class ImageDiversityResponse(BaseModel):
    policy_version: str
    brief_version: str
    selector_version: str
    prompt_version: str
    pipeline_version: str
    similarity_policy_version: str
    hash_version: str
    plan: ControlledVisualPlanResponse
    retry_count: int = Field(ge=0, le=1)
    active_plan_ordinal: int = Field(ge=1, le=2)
    final_plan_ordinal: int | None = Field(default=None, ge=1, le=2)
    warning: bool
    warning_code: Literal["near_duplicate_after_retry"] | None
    near_duplicate: bool | None
    exact_duplicate: bool | None
    nearest_distance: int | None = Field(default=None, ge=0, le=64)
    threshold: int | None = Field(default=None, ge=0, le=64)
    candidate_count: int | None = Field(default=None, ge=0, le=1_000)
    decision: Literal["accepted", "regenerate", "accepted_with_warning"] | None


class ImageValidationResponse(BaseModel):
    version: str
    configured: bool
    passed: bool | None
    issue_codes: list[str]
    provider: str | None
    model: str | None
    media_type: str | None = None
    width: int | None = None
    height: int | None = None
    byte_size: int | None = None


class ImageAuditResponse(BaseModel):
    version: str
    configured: bool
    status: Literal["accepted", "rejected", "not_applicable", "not_configured", "unknown"]
    passed: bool | None
    issue_codes: list[str]
    provider: str | None
    model: str | None


class ImageFallbackAssetResponse(BaseModel):
    asset_id: str
    filename: str
    sha256: str
    role: Literal["identity_reference", "action_reference", "style_reference", "legacy"]
    selection_reason: str
    fallback: bool


class ImageFallbackResponse(BaseModel):
    version: Literal["image-fallback-v1"]
    state: Literal["not_used", "neutralized_retry", "brand_catalog"]
    provider_rejection_retry_count: int = Field(ge=0, le=1)
    initial_error_code: str | None = Field(
        ...,
        pattern=r"^[a-z][a-z0-9_.-]{0,119}$",
    )
    primary_provider: str | None
    primary_model: str | None
    asset: ImageFallbackAssetResponse | None = None


class ImageArtifactResponse(BaseModel):
    id: UUID
    status: Literal["queued", "running", "succeeded", "failed", "review_required"]
    provider: str
    model: str
    request_fingerprint: str
    width: int | None
    height: int | None
    media_type: str | None
    byte_size: int | None
    sha256: str | None
    storage_metadata: ImageStorageMetadataResponse
    error_code: str | None
    download_url: str | None
    reference_mode: Literal[
        "legacy_single",
        "single_reference",
        "single_fallback",
        "budgeted_multi_reference",
        "multi_reference",
    ] = "legacy_single"
    visual_brief: VisualBriefResponse | None = None
    references: list[VisualReferenceResponse] = Field(default_factory=list)
    repair_count: int = 0
    fallback: ImageFallbackResponse
    validation: ImageValidationResponse
    audit: ImageAuditResponse
    diversity: ImageDiversityResponse | None = None


class MaterialPackageSummaryResponse(BaseModel):
    id: UUID
    copy_generation_run_id: UUID
    status: Literal["queued", "ready", "awaiting_manual_use", "completed", "rejected", "failed"]
    review_status: Literal["pending", "approved", "rejected"]
    business_date: str
    content_slot: Literal["morning", "noon", "evening"] | None = None
    ordinal: int | None = Field(default=None, ge=1, le=3)
    target_at: datetime | None = None
    expires_at: datetime | None = None
    created_at: datetime
    detail_url: str


class MaterialPackageResponse(MaterialPackageSummaryResponse):
    model_config = ConfigDict(populate_by_name=True)

    package_version: int
    topic: dict[str, object]
    copy_: dict[str, object] = Field(alias="copy")
    sources: list[dict[str, object]]
    brand_bindings: list[dict[str, object]]
    validation: dict[str, object]
    audit: dict[str, object]
    versions: dict[str, object]
    image: ImageArtifactResponse
    review_note: str | None
    reviewed_at: datetime | None
    review_url: str
    download_url: str


class MaterialPackageDownloadResponse(MaterialPackageResponse):
    download_kind: Literal["material_package_json"] = "material_package_json"


class MaterialPackageListResponse(BaseModel):
    items: list[MaterialPackageSummaryResponse]
    count: int
