from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class TopicRerankSummaryResponse(BaseModel):
    outcome: Literal["not_applied", "applied", "skipped", "fallback"]
    enabled: bool
    policy_version: str
    config_fingerprint: str
    provider: str
    model: str
    candidate_count: int = Field(ge=0, le=8)
    failure_code: str | None
    request_fingerprint: str | None
    prompt_fingerprint: str | None
    prompt_tokens: int = Field(ge=0)
    completion_tokens: int = Field(ge=0)
    reasoning_tokens: int = Field(ge=0)
    latency_ms: int = Field(ge=0)
