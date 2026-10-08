from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class AdminLoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1, max_length=200)


class AdminMeResponse(BaseModel):
    username: str
    display_name: str
    role: Literal["owner", "editor"]
    expires_at: datetime


class AdminAuditEventResponse(BaseModel):
    id: UUID
    occurred_at: datetime
    username: str
    action: str
    target_type: str | None
    target_id: str | None
    detail: dict[str, Any]


class AdminAuditEventListResponse(BaseModel):
    items: list[AdminAuditEventResponse]
    count: int
