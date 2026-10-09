from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AdminModelProvider(BaseModel):
    id: str
    name: str
    used_for: str
    base_url: str | None
    models: list[str]
    source: Literal["console", "env", "none"]
    key_hint: str | None
    version: int | None
    updated_by: str | None
    updated_at: datetime | None
    # The version this API process loaded at start; null before any console version or when the
    # console keys are off. Equal to `version` once services have restarted with it.
    loaded_version: int | None


class AdminModelProvidersResponse(BaseModel):
    secret_key_configured: bool
    providers: list[AdminModelProvider]


class AdminModelKeyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    api_key: str = Field(min_length=1, max_length=400)
    note: str | None = Field(default=None, max_length=200)


class AdminModelKeyTestResponse(BaseModel):
    ok: bool
    latency_ms: int
    message: str


class AdminModelKeyVersion(BaseModel):
    version: int
    source: Literal["console", "env"]
    key_hint: str | None
    note: str | None
    restored_from: int | None
    probe_latency_ms: int | None
    created_by: str
    created_at: datetime
    current: bool


class AdminModelKeyHistoryResponse(BaseModel):
    items: list[AdminModelKeyVersion]


class AdminModelKeyRestoreRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
