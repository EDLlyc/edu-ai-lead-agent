from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.ip_assets import (
    IpAssetCharacter,
    IpAssetLeaderboardPeriod,
    IpAssetMembershipSource,
    IpAssetOrientation,
    IpAssetSearchMode,
    IpAssetSearchVersion,
    IpAssetSemanticStatus,
    IpAssetSource,
    IpAssetStatus,
    IpAssetType,
)


class IpAssetCardResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_ref: str
    canonical_name: str
    character: IpAssetCharacter
    asset_type: IpAssetType
    source_kind: IpAssetSource
    department: str = Field(description="Self-reported descriptive label; not verified identity")
    contributor: str = Field(description="Self-reported descriptive label; not verified identity")
    emotion: str
    action: str
    scene: str
    intended_use: str
    style: str
    tags: list[str]
    media_type: Literal["image/png", "image/jpeg", "image/webp"]
    byte_size: int
    width: int
    height: int
    has_alpha: bool
    orientation: IpAssetOrientation
    status: IpAssetStatus
    semantic_status: IpAssetSemanticStatus
    shared: bool
    favorite: bool = False
    created_at: datetime
    preview_url: str
    download_url: str


class IpAssetDetailResponse(IpAssetCardResponse):
    safe_original_filename: str
    checksum_ref: str
    name_version: int


class IpAssetListResponse(BaseModel):
    items: list[IpAssetCardResponse]
    next_cursor: str | None


class IpAssetProfileCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=80)
    department: str = Field(min_length=1, max_length=80)


class IpAssetProfileResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile_ref: str
    display_name: str
    department: str
    identity_boundary: Literal["browser_local_unverified"] = "browser_local_unverified"
    created_at: datetime


class IpAssetPersonalItemResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset: IpAssetCardResponse
    membership_sources: list[IpAssetMembershipSource]
    favorite: bool


class IpAssetPersonalListResponse(BaseModel):
    items: list[IpAssetPersonalItemResponse]
    next_cursor: str | None


class IpAssetFavoriteResponse(BaseModel):
    asset_ref: str
    favorite: bool


class IpAssetShareResponse(BaseModel):
    asset: IpAssetDetailResponse
    shared: Literal[True] = True


class IpAssetLeaderboardItemResponse(BaseModel):
    asset: IpAssetCardResponse
    download_count: int = Field(ge=1)


class IpAssetLeaderboardResponse(BaseModel):
    period: IpAssetLeaderboardPeriod
    generated_at: datetime
    items: list[IpAssetLeaderboardItemResponse]


class IpAssetUploadResponse(BaseModel):
    asset: IpAssetDetailResponse
    duplicate: bool
    near_duplicate_ref: str | None = None
    near_duplicate_distance: int | None = Field(default=None, ge=0, le=64)


class IpAssetRecognitionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["suggested"] = "suggested"
    character: IpAssetCharacter
    asset_type: IpAssetType
    emotion: str = Field(default="", max_length=40)
    action: str = Field(default="", max_length=40)
    scene: str = Field(default="", max_length=60)
    intended_use: str = Field(default="", max_length=60)
    style: str = Field(default="", max_length=40)
    tags: list[str] = Field(default_factory=list, max_length=20)
    provider: str = Field(min_length=1, max_length=120)
    model: str = Field(min_length=1, max_length=120)


class IpAssetTextSearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    message: str = Field(min_length=1, max_length=2_000)
    prior_turns: list[str] = Field(default_factory=list, max_length=4)
    character: IpAssetCharacter | None = None
    asset_type: IpAssetType | None = None
    department: str = Field(default="", max_length=80)
    source_kind: IpAssetSource | None = None
    orientation: IpAssetOrientation | None = None
    tag: str = Field(default="", max_length=40)
    limit: int = Field(default=20, ge=1, le=40)


class IpAssetSearchItemResponse(BaseModel):
    asset: IpAssetCardResponse
    similarity: float | None = Field(default=None, ge=-1, le=1)
    explanation: str = Field(max_length=240)


class IpAssetSearchResponse(BaseModel):
    mode: IpAssetSearchMode
    degraded_reason: str | None
    search_version: IpAssetSearchVersion
    items: list[IpAssetSearchItemResponse]


class IpAssetZipRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    asset_refs: list[str] = Field(min_length=1, max_length=50)


class IpAssetGenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    prompt: str = Field(min_length=8, max_length=2_000)
    character: IpAssetCharacter
    asset_type: IpAssetType
    department: str = Field(default="", max_length=80)
    contributor: str = Field(default="", max_length=80)
    ratio: Literal["1:1"] = "1:1"
    reference_asset_ref: str | None = Field(default=None, max_length=24)
    reference_asset_refs: list[str] | None = Field(default=None, min_length=1, max_length=3)
    idempotency_key: str = Field(min_length=8, max_length=128)

    @model_validator(mode="after")
    def validate_reference_shape(self) -> IpAssetGenerationRequest:
        if self.reference_asset_ref is not None and self.reference_asset_refs is not None:
            raise ValueError("legacy and ordered reference fields cannot be combined")
        refs = (
            self.reference_asset_refs
            if self.reference_asset_refs is not None
            else ([self.reference_asset_ref] if self.reference_asset_ref is not None else [])
        )
        if not refs or len(set(refs)) != len(refs):
            raise ValueError("one to three distinct references are required")
        return self


class IpAssetGenerationResponse(BaseModel):
    job_ref: str
    status: Literal["queued", "running", "succeeded", "failed"]
    created: bool
    generation_available: bool = True
    output_asset_ref: str | None = None
    reference_asset_refs: list[str]
    reference_asset_ref: str | None = None
    error_code: str | None = None
    status_url: str
    created_at: datetime
    completed_at: datetime | None


class IpAssetCapabilitiesResponse(BaseModel):
    enabled: bool
    authentication: Literal["none"] = "none"
    deployment_boundary: Literal["company_intranet"] = "company_intranet"
    semantic_search_available: bool
    generation_available: bool
    recognition_available: bool
    max_upload_bytes: Literal[26214400] = 26_214_400
    accepted_media_types: list[Literal["image/png", "image/jpeg", "image/webp"]]
