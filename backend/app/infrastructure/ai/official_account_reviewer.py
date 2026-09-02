from __future__ import annotations

import json
from typing import Self

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator

from app.application.ports.official_account_reviewer import (
    OfficialAccountReviewerRequest,
    OfficialAccountReviewerResult,
)
from app.application.services.official_account_reviewer import build_reviewer_prompt
from app.domain.official_account_reviewer import (
    ReviewIssue,
    ReviewIssueSource,
    build_review_verdict,
)
from app.infrastructure.ai.official_account_local import (
    _complete_strict_json,
    _StructuredArticleClient,
)
from app.infrastructure.ai.zhipu import _safe_provider_request_id


class _ReviewerProviderOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str = Field(min_length=1, max_length=160)
    request_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    article_ref: str = Field(min_length=1, max_length=160)
    article_fingerprint: str = Field(pattern=r"^[0-9a-f]{64}$")
    reviewer_version: str = Field(min_length=1, max_length=160)
    prompt_version: str = Field(min_length=1, max_length=160)
    issues: tuple[ReviewIssue, ...] = Field(default=(), max_length=6)

    @model_validator(mode="after")
    def reviewer_only(self) -> Self:
        if any(issue.source is not ReviewIssueSource.REVIEWER for issue in self.issues):
            raise ValueError("editorial Reviewer cannot claim a hard-gate issue")
        return self


class ZhipuOfficialAccountReviewer:
    def __init__(self, transport: _StructuredArticleClient) -> None:
        self._transport = transport

    @property
    def provider(self) -> str:
        return "zhipu"

    @property
    def model(self) -> str:
        return self._transport.model

    async def review(
        self,
        request: OfficialAccountReviewerRequest,
    ) -> OfficialAccountReviewerResult:
        content, completion, metrics, corrections = await _complete_strict_json(
            transport=self._transport,
            base_prompt=build_reviewer_prompt(request),
            output_tokens=request.max_output_tokens,
            schema=_ReviewerProviderOutput,
            schema_name="OfficialAccountReviewerOutput",
            include_schema_in_initial_system=True,
        )
        output = _parse_reviewer_provider_output(content)
        contract = request.contract
        if (
            output.request_id != contract.request_id
            or output.request_fingerprint != contract.request_fingerprint
            or output.article_ref != contract.identity.article_ref
            or output.article_fingerprint != contract.identity.article_fingerprint
            or output.reviewer_version != contract.reviewer_version
            or output.prompt_version != contract.prompt_version
        ):
            raise ValueError("Reviewer provider output identity changed")
        verdict = build_review_verdict(contract, reviewer_issues=output.issues)
        return OfficialAccountReviewerResult(
            verdict=verdict,
            provider=self.provider,
            model=self.model,
            provider_request_id=_safe_provider_request_id(completion.id),
            prompt_tokens=metrics[0],
            completion_tokens=metrics[1],
            reasoning_tokens=metrics[2],
            latency_ms=metrics[3],
            validation_corrections=corrections,
        )


def _parse_reviewer_provider_output(content: str) -> _ReviewerProviderOutput:
    def reject_duplicate_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
        payload: dict[str, object] = {}
        for key, value in pairs:
            if key in payload:
                raise ValueError("Reviewer provider JSON contains duplicate fields")
            payload[key] = value
        return payload

    payload = json.loads(content, object_pairs_hook=reject_duplicate_fields)
    return _ReviewerProviderOutput.model_validate(payload)


def create_zhipu_official_account_reviewer(
    *,
    client: httpx.AsyncClient,
    base_url: str,
    api_key: SecretStr,
    model: str,
    connect_timeout_seconds: float,
    read_timeout_seconds: float,
    total_timeout_seconds: float,
    concurrency: int,
    max_attempts: int,
    max_input_characters: int,
    max_output_tokens: int,
    max_validation_corrections: int,
) -> ZhipuOfficialAccountReviewer:
    return ZhipuOfficialAccountReviewer(
        _StructuredArticleClient(
            client=client,
            base_url=base_url,
            api_key=api_key,
            model=model,
            connect_timeout_seconds=connect_timeout_seconds,
            read_timeout_seconds=read_timeout_seconds,
            total_timeout_seconds=total_timeout_seconds,
            concurrency=concurrency,
            max_attempts=max_attempts,
            max_input_characters=max_input_characters,
            max_output_tokens=max_output_tokens,
            max_validation_corrections=max_validation_corrections,
        )
    )
