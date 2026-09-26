from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

WeComDeliveryStatus = Literal[
    "queued",
    "running",
    "partial",
    "delivery_unknown",
    "delivered",
    "failed",
    "cancelled",
    "delivery_window_expired",
]
WeComMessageStatus = Literal["pending", "running", "delivered", "failed", "unknown", "skipped"]


class WeComRecipientResponse(BaseModel):
    id: str
    display_name: str
    enabled: bool


class WeComRecipientListResponse(BaseModel):
    items: list[WeComRecipientResponse]
    count: int


class WeComDeliveryCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    recipient_id: str = Field(min_length=1, max_length=80)
    mode: Literal["test", "formal"] = "formal"
    include_copy: bool = True
    include_image: bool = True


class WeComDeliveryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    material_package_id: UUID
    delivery_window_id: UUID | None
    content_slot_selection_id: UUID | None
    sequence_ordinal: int | None = Field(default=None, ge=1, le=3)
    not_before: datetime | None
    expires_at: datetime | None
    recipient_id: str
    mode: Literal["test", "formal"]
    package_version: int
    status: WeComDeliveryStatus
    text_status: WeComMessageStatus
    image_status: WeComMessageStatus
    include_copy: bool
    include_image: bool
    attempt_count: int
    last_error_code: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    retry_url: str


class WeComInfographicAttemptResponse(BaseModel):
    attempt_number: int
    result_state: Literal["succeeded", "failed", "unknown"]
    safe_response_code: str | None
    created_at: datetime


class WeComInfographicStatusResponse(BaseModel):
    """Safe projection; an absent job is not a successful infographic send."""

    base_job_id: UUID
    base_status: WeComDeliveryStatus
    infographic_job_id: UUID | None
    infographic_status: str | None
    infographic_safe_error_code: str | None
    quality_mode: Literal["strict", "advisory"] | None
    warning_codes: list[str]
    warning_notice_version: str | None
    content_slot_selection_id: UUID | None
    sequence_ordinal: int | None
    business_date: str | None
    content_slot: str | None
    package_version: int | None
    delivery_sha256: str | None
    delivery_byte_size: int | None
    delivery_width: int | None
    delivery_height: int | None
    ocr_status: str | None
    footer_ocr_status: str | None
    visual_status: str | None
    supplement_id: UUID | None
    supplement_status: str | None
    supplement_safe_error_code: str | None
    supplement_attempt_count: int
    supplement_expires_at: datetime | None
    attempts: list[WeComInfographicAttemptResponse]
