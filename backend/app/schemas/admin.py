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


class AdminAccountResponse(BaseModel):
    username: str
    display_name: str
    role: Literal["owner", "editor"]
    active: bool
    locked: bool
    last_login_at: datetime | None
    created_at: datetime
    live_sessions: int


class AdminAccountListResponse(BaseModel):
    items: list[AdminAccountResponse]
    count: int


class AdminAccountCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=80)
    display_name: str = Field(min_length=1, max_length=80)
    role: Literal["owner", "editor"]


class AdminAccountUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    role: Literal["owner", "editor"] | None = None


class AdminAccountWithPasswordResponse(BaseModel):
    """A created or reset account; `initial_password` is shown once and never again."""

    account: AdminAccountResponse
    initial_password: str


class AdminPasswordChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=1, max_length=200)


class AdminPasswordChangedResponse(BaseModel):
    other_sessions_ended: int
