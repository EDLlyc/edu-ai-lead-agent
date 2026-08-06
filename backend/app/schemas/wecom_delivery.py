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
