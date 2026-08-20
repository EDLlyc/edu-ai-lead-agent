from __future__ import annotations

import asyncio
import hashlib
import json
from collections.abc import Awaitable, Callable
from time import perf_counter_ns
from typing import Any, Literal, get_args
from urllib.parse import urlsplit
from uuid import UUID

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from app.application.services.topic_reranking import build_topic_rerank_prompt
from app.core.errors import (
    ProviderInputLimitError,
    ProviderValidationIssue,
    TopicRerankInvalidProviderOutputError,
    normalize_provider_validation_issues,
)
from app.domain.topic_rerank import (
    LEGACY_TOPIC_RERANK_POLICY_VERSION,
    STRICT_JSON_TOPIC_RERANK_POLICY_VERSIONS,
    TOPIC_RERANK_REASON_CODES,
    TopicRerankCandidate,
    TopicRerankItem,
    TopicRerankModelResult,
    TopicRerankRequest,
)
from app.infrastructure.ai.provider_json import (
    ProviderJsonEnvelopeError,
    extract_provider_json_object,
)
from app.infrastructure.ai.zhipu import _post_json_with_retries

_Sleep = Callable[[float], Awaitable[None]]
TopicRerankReasonCode = Literal[
    "communication_value",
    "information_gain",
    "timeliness",
    "audience_relevance",
    "column_fit",
    "insight_potential",
    "topic_diversity",
]
_MAX_PROVIDER_METRIC = 2_147_483_647
_SAFE_VALIDATION_LOC_SEGMENTS = frozenset(
    {
        "choices",
        "completion_tokens",
        "completion_tokens_details",
        "content",
        "event_id",
        "explanation",
        "items",
        "message",
        "ordinal",
        "prompt_tokens",
        "reason_codes",
        "root",
        "usage",
    }
)


class _ProviderModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _Usage(_ProviderModel):
    prompt_tokens: int = Field(default=0, ge=0, le=_MAX_PROVIDER_METRIC, strict=True)
    completion_tokens: int = Field(default=0, ge=0, le=_MAX_PROVIDER_METRIC, strict=True)
    completion_tokens_details: dict[str, Any] | None = None


class _Message(_ProviderModel):
    content: str


class _Choice(_ProviderModel):
    message: _Message


class _ChatCompletion(_ProviderModel):
    choices: tuple[_Choice, ...] = Field(min_length=1, max_length=1)
    usage: _Usage = Field(default_factory=_Usage)


class _TopicRerankItemOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    event_id: str = Field(min_length=36, max_length=36)
    ordinal: int = Field(ge=1, le=8)
    reason_codes: tuple[TopicRerankReasonCode, ...] = Field(min_length=1, max_length=3)
    explanation: str = Field(min_length=1, max_length=160)


class _TopicRerankOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    items: tuple[_TopicRerankItemOutput, ...] = Field(min_length=1, max_length=8)


class DeterministicFakeTopicReranker:
    """Provider-free sorter derived only from allowlisted candidate projections."""

    def __init__(self, *, model: str) -> None:
        if not model.strip() or len(model) > 120:
            raise ValueError("fake topic rerank model must be non-blank and bounded")
        self._model = model.strip()

    async def rerank(self, request: TopicRerankRequest) -> TopicRerankModelResult:
        started = perf_counter_ns()
        prompt = build_topic_rerank_prompt(request)

        def key(candidate: TopicRerankCandidate) -> tuple[float, float, int]:
            value = (
                candidate.communication_potential * 0.24
                + candidate.education_relevance * 0.18
                + candidate.frontier_significance * 0.18
                + candidate.product_fit * 0.16
                + candidate.editorial_priority * 0.14
                + (candidate.slot_affinity or 0.0) * 0.10
                - candidate.controversy_risk * 0.08
                - candidate.marketing_risk * 0.08
            )
            return (-value, -candidate.event_time.timestamp(), candidate.event_id.int)

        groups: dict[int, list[TopicRerankCandidate]] = {0: [], 1: []}
        for candidate in request.candidates:
            groups[candidate.priority_group].append(candidate)
        ordered = tuple(
            candidate
            for priority_group in (0, 1)
            for candidate in sorted(groups[priority_group], key=key)
        )
        items = tuple(
            TopicRerankItem(
                event_id=candidate.event_id,
                ordinal=ordinal,
                reason_codes=_fake_reason_codes(candidate),
                explanation="基于受控编辑信号与栏目适配度排序。",
            )
            for ordinal, candidate in enumerate(ordered, start=1)
        )
        serialized = json.dumps(
            {
                "items": [
                    {
                        "event_id": str(item.event_id),
                        "ordinal": item.ordinal,
                        "reason_codes": list(item.reason_codes),
                        "explanation": item.explanation,
                    }
                    for item in items
                ]
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        latency_ms = max(0, (perf_counter_ns() - started) // 1_000_000)
        return TopicRerankModelResult(
            items=items,
            provider="fake",
            model=self._model,
            prompt_fingerprint=prompt.fingerprint,
            prompt_tokens=max(1, (len(prompt.system_message) + len(prompt.user_message)) // 4),
            completion_tokens=max(1, len(serialized) // 4),
            reasoning_tokens=0,
            latency_ms=latency_ms,
        )


def _fake_reason_codes(candidate: TopicRerankCandidate) -> tuple[str, ...]:
    scored = [
        (candidate.communication_potential, "communication_value"),
        (candidate.education_relevance, "audience_relevance"),
        (candidate.frontier_significance, "information_gain"),
        (candidate.product_fit + (candidate.slot_affinity or 0.0), "column_fit"),
        (candidate.editorial_priority, "insight_potential"),
    ]
    ordered = tuple(code for _, code in sorted(scored, reverse=True)[:2])
    if len(set(ordered)) != len(ordered):
        digest = hashlib.sha256(str(candidate.event_id).encode()).digest()
        return (
            ("communication_value", "topic_diversity")
            if digest[0] % 2
            else (
                "information_gain",
                "insight_potential",
            )
        )
    return ordered


class ZhipuTopicReranker:
    """Strict OpenAI-compatible JSON adapter for bounded topic reranking."""

    def __init__(
        self,
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
        sleep: _Sleep = asyncio.sleep,
    ) -> None:
        parsed = urlsplit(base_url.strip())
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("topic rerank base URL must be HTTPS without credentials")
        secret = api_key.get_secret_value().strip()
        if not secret or any(character in secret for character in "\r\n"):
            raise ValueError("topic rerank API key must be non-blank without line breaks")
        if not model.strip() or len(model) > 120 or any(character.isspace() for character in model):
            raise ValueError("topic rerank model must be a bounded identifier")
        if concurrency < 1 or max_attempts < 1:
            raise ValueError("topic rerank concurrency and attempts must be positive")
        if (
            connect_timeout_seconds <= 0
            or read_timeout_seconds <= 0
            or total_timeout_seconds < read_timeout_seconds
        ):
            raise ValueError("topic rerank timeouts are invalid")
        if max_input_characters < 1 or max_output_tokens < 128:
            raise ValueError("topic rerank input and output limits are invalid")
        self._client = client
        self._url = f"{base_url.strip().rstrip('/')}/chat/completions"
        self._api_key = SecretStr(secret)
        self._model = model.strip()
        self._timeout = httpx.Timeout(
            connect=connect_timeout_seconds,
            read=read_timeout_seconds,
            write=connect_timeout_seconds,
            pool=connect_timeout_seconds,
        )
        self._total_timeout_seconds = total_timeout_seconds
        self._semaphore = asyncio.Semaphore(concurrency)
        self._max_attempts = max_attempts
        self._max_input_characters = max_input_characters
        self._max_output_tokens = max_output_tokens
        self._sleep = sleep

    async def rerank(self, request: TopicRerankRequest) -> TopicRerankModelResult:
        prompt = build_topic_rerank_prompt(request)
        if len(prompt.system_message) + len(prompt.user_message) > self._max_input_characters:
            raise ProviderInputLimitError()
        output_limit = min(request.max_output_tokens, self._max_output_tokens)
        payload: dict[str, Any] = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": prompt.system_message},
                {"role": "user", "content": prompt.user_message},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.0,
            "max_tokens": output_limit,
        }
        if request.policy_version in STRICT_JSON_TOPIC_RERANK_POLICY_VERSIONS:
            payload["thinking"] = {"type": "disabled"}
            payload["do_sample"] = False
        elif request.policy_version != LEGACY_TOPIC_RERANK_POLICY_VERSION:
            raise ValueError("unsupported topic rerank request policy")
        started = perf_counter_ns()
        response = await _post_json_with_retries(
            client=self._client,
            url=self._url,
            api_key=self._api_key,
            http_timeout=self._timeout,
            total_timeout_seconds=self._total_timeout_seconds,
            semaphore=self._semaphore,
            max_attempts=self._max_attempts,
            sleep=self._sleep,
            payload=payload,
            max_response_bytes=max(16_384, output_limit * 16),
        )
        latency_ms = max(0, (perf_counter_ns() - started) // 1_000_000)
        try:
            response_payload = response.json()
        except (json.JSONDecodeError, TypeError, ValueError):
            raise _invalid_topic_rerank_output(
                "topic_rerank_completion_invalid",
                prompt_fingerprint=prompt.fingerprint,
                latency_ms=latency_ms,
                validation_issues=_root_issue("json_invalid"),
            ) from None
        try:
            completion = _ChatCompletion.model_validate(response_payload)
        except ValidationError as error:
            raise _invalid_topic_rerank_output(
                "topic_rerank_completion_invalid",
                prompt_fingerprint=prompt.fingerprint,
                latency_ms=latency_ms,
                validation_issues=_safe_validation_issues(error),
            ) from None
        reasoning_tokens = 0
        details = completion.usage.completion_tokens_details
        if isinstance(details, dict):
            value = details.get("reasoning_tokens", 0)
            if (
                isinstance(value, int)
                and not isinstance(value, bool)
                and 0 <= value <= _MAX_PROVIDER_METRIC
            ):
                reasoning_tokens = value
        metrics = {
            "prompt_tokens": completion.usage.prompt_tokens,
            "completion_tokens": completion.usage.completion_tokens,
            "reasoning_tokens": reasoning_tokens,
            "latency_ms": latency_ms,
        }
        if completion.usage.completion_tokens > output_limit:
            raise _invalid_topic_rerank_output(
                "topic_rerank_schema_invalid",
                prompt_fingerprint=prompt.fingerprint,
                validation_issues=_issue(("usage", "completion_tokens"), "output_limit_exceeded"),
                **metrics,
            )
        content = completion.choices[0].message.content
        if request.policy_version in STRICT_JSON_TOPIC_RERANK_POLICY_VERSIONS:
            try:
                normalized_content = extract_provider_json_object(content)
            except ProviderJsonEnvelopeError as error:
                raise _invalid_topic_rerank_output(
                    "topic_rerank_json_envelope_invalid",
                    prompt_fingerprint=prompt.fingerprint,
                    validation_issues=_root_issue(error.validation_type),
                    **metrics,
                ) from None
        else:
            normalized_content = content
        try:
            output = _TopicRerankOutput.model_validate_json(normalized_content)
        except ValidationError as error:
            raise _invalid_topic_rerank_output(
                "topic_rerank_schema_invalid",
                prompt_fingerprint=prompt.fingerprint,
                validation_issues=_safe_validation_issues(error),
                **metrics,
            ) from None
        items = _build_topic_rerank_items(
            output,
            prompt_fingerprint=prompt.fingerprint,
            metrics=metrics,
        )
        return TopicRerankModelResult(
            items=items,
            provider="zhipu",
            model=self._model,
            prompt_fingerprint=prompt.fingerprint,
            prompt_tokens=completion.usage.prompt_tokens,
            completion_tokens=completion.usage.completion_tokens,
            reasoning_tokens=reasoning_tokens,
            latency_ms=latency_ms,
        )


def _parse_event_id(value: str) -> UUID:
    return UUID(value)


def _build_topic_rerank_items(
    output: _TopicRerankOutput,
    *,
    prompt_fingerprint: str,
    metrics: dict[str, int],
) -> tuple[TopicRerankItem, ...]:
    items: list[TopicRerankItem] = []
    for index, item in enumerate(output.items):
        try:
            event_id = _parse_event_id(item.event_id)
        except (TypeError, ValueError):
            raise _invalid_topic_rerank_output(
                "topic_rerank_schema_invalid",
                prompt_fingerprint=prompt_fingerprint,
                validation_issues=_issue(("items", index, "event_id"), "uuid_parsing"),
                **metrics,
            ) from None
        try:
            items.append(
                TopicRerankItem(
                    event_id=event_id,
                    ordinal=item.ordinal,
                    reason_codes=tuple(item.reason_codes),
                    explanation=item.explanation.strip(),
                )
            )
        except ValueError:
            field = (
                "reason_codes"
                if len(set(item.reason_codes)) != len(item.reason_codes)
                else "explanation"
            )
            raise _invalid_topic_rerank_output(
                "topic_rerank_schema_invalid",
                prompt_fingerprint=prompt_fingerprint,
                validation_issues=_issue(("items", index, field), "value_error"),
                **metrics,
            ) from None
    return tuple(items)


def _invalid_topic_rerank_output(
    issue_code: str,
    *,
    prompt_fingerprint: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    reasoning_tokens: int = 0,
    latency_ms: int = 0,
    validation_issues: tuple[ProviderValidationIssue, ...] = (),
) -> TopicRerankInvalidProviderOutputError:
    return TopicRerankInvalidProviderOutputError(
        issue_code,
        prompt_fingerprint=prompt_fingerprint,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        reasoning_tokens=reasoning_tokens,
        latency_ms=latency_ms,
        validation_issues=validation_issues,
    )


def _safe_validation_issues(error: ValidationError) -> tuple[ProviderValidationIssue, ...]:
    return normalize_provider_validation_issues(
        (
            tuple(
                segment
                if isinstance(segment, int) or segment in _SAFE_VALIDATION_LOC_SEGMENTS
                else "unknown"
                for segment in item["loc"]
            ),
            item["type"],
        )
        for item in error.errors(
            include_url=False,
            include_context=False,
            include_input=False,
        )
    )


def _issue(loc: tuple[str | int, ...], issue_type: str) -> tuple[ProviderValidationIssue, ...]:
    return normalize_provider_validation_issues(((loc, issue_type),))


def _root_issue(issue_type: str) -> tuple[ProviderValidationIssue, ...]:
    return _issue(("root",), issue_type)


assert set(get_args(TopicRerankReasonCode)) == TOPIC_RERANK_REASON_CODES
