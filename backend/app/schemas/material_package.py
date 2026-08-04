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


class MaterialPackageSummaryResponse(BaseModel):
    id: UUID
    copy_generation_run_id: UUID
    status: Literal["queued", "ready", "awaiting_manual_use", "completed", "rejected", "failed"]
    review_status: Literal["pending", "approved", "rejected"]
    business_date: str
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
