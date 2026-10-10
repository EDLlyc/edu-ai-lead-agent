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


class AdminModelKeyConsumer(BaseModel):
    """A production service that holds model keys, and what it reported."""

    service: str
    label: str
    # False: no report in the last 5 minutes. The service then runs an image without the watch
    # (or is down) and uses its environment keys.
    reporting: bool
    # Successfully applied versions only, including explicit env restores. A failed load is
    # omitted; null means the startup database read failed.
    versions: dict[str, int] | None
    # Null is a legacy heartbeat without reliable load diagnostics; {} means no failures.
    load_errors: dict[str, str] | None
    started_at: datetime | None
    seen_at: datetime | None


class AdminModelProvidersResponse(BaseModel):
    secret_key_configured: bool
    providers: list[AdminModelProvider]
    consumers: list[AdminModelKeyConsumer]


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
