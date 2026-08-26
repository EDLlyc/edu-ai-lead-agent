from __future__ import annotations

# ruff: noqa: RUF001 -- Chinese punctuation is intentional in model instructions.
import asyncio
import json
from time import perf_counter_ns
from typing import Any
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from app.application.ports.official_account_local import (
    OfficialAccountAuditRequest,
    OfficialAccountAuditResult,
    OfficialAccountGenerationRequest,
    OfficialAccountGenerationResult,
)
from app.application.services.official_account_local import (
    audit_request_fingerprint,
    build_audit_prompt,
    build_generation_prompt,
    generation_request_fingerprint,
)
from app.core.errors import (
    InvalidProviderOutputError,
    ProviderInputLimitError,
    ProviderValidationIssue,
    normalize_provider_validation_issues,
)
from app.domain.official_account_local import (
    OFFICIAL_ACCOUNT_AUDITOR_PROMPT_VERSION,
    OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V5_VERSION,
    OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V7_VERSION,
    OFFICIAL_ACCOUNT_GENERATOR_PROMPT_VERSION,
    OFFICIAL_ACCOUNT_RULE_VERSION,
    GeneratedArticleDraft,
    OfficialAccountAuditVerdict,
    canonical_json,
)
from app.infrastructure.ai.provider_json import (
    ProviderJsonEnvelopeError,
    extract_provider_json_object,
)
from app.infrastructure.ai.zhipu import _post_json_with_retries, _safe_provider_request_id

_MAX_VALIDATION_SCHEMA_CHARACTERS = 16_384
_MAX_VALIDATION_INVARIANT_HINT_CHARACTERS = 2_048
_BASE_SYSTEM_INSTRUCTION = "只返回严格JSON对象，不输出Markdown、HTML、URL或解释。"


class _ProviderModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _CompletionTokenDetails(_ProviderModel):
    reasoning_tokens: int = Field(default=0, ge=0)


class _Usage(_ProviderModel):
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    completion_tokens_details: _CompletionTokenDetails | None = None


class _Message(_ProviderModel):
    content: str = Field(min_length=1)


class _Choice(_ProviderModel):
    message: _Message


class _ChatCompletion(_ProviderModel):
    id: str | None = None
    choices: tuple[_Choice, ...] = Field(min_length=1, max_length=1)
    usage: _Usage = Field(default_factory=_Usage)


class _StructuredArticleClient:
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
        max_validation_corrections: int,
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
            raise ValueError("article provider base URL must be a safe HTTPS origin/path")
        secret = api_key.get_secret_value().strip()
        if not secret or any(character in secret for character in "\r\n"):
            raise ValueError("article provider API key is invalid")
        normalized_model = model.strip()
        if (
            not normalized_model
            or len(normalized_model) > 120
            or any(character.isspace() for character in normalized_model)
        ):
            raise ValueError("article provider model is invalid")
        self.client = client
        self.url = f"{base_url.strip().rstrip('/')}/chat/completions"
        self.api_key = SecretStr(secret)
        self.model = normalized_model
        self.timeout = httpx.Timeout(
            connect=connect_timeout_seconds,
            read=read_timeout_seconds,
            write=connect_timeout_seconds,
            pool=connect_timeout_seconds,
        )
        self.total_timeout_seconds = total_timeout_seconds
        self.semaphore = asyncio.Semaphore(concurrency)
        self.max_attempts = max_attempts
        self.max_input_characters = max_input_characters
        self.max_output_tokens = max_output_tokens
        self.max_validation_corrections = max_validation_corrections

    async def complete(
        self,
        *,
        prompt: str,
        output_tokens: int,
        system_instruction: str | None = None,
    ) -> tuple[str, _ChatCompletion, int]:
        bounded_system_instruction = system_instruction or _BASE_SYSTEM_INSTRUCTION
        if len(prompt) + len(bounded_system_instruction) > self.max_input_characters:
            raise ProviderInputLimitError()
        bounded_tokens = min(output_tokens, self.max_output_tokens)
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": bounded_system_instruction,
                },
                {"role": "user", "content": prompt},
            ],
            "thinking": {"type": "disabled"},
            "response_format": {"type": "json_object"},
            "temperature": 0.0,
            "max_tokens": bounded_tokens,
        }
        started = perf_counter_ns()
        response = await _post_json_with_retries(
            client=self.client,
            url=self.url,
            api_key=self.api_key,
            http_timeout=self.timeout,
            total_timeout_seconds=self.total_timeout_seconds,
            semaphore=self.semaphore,
            max_attempts=self.max_attempts,
            sleep=asyncio.sleep,
            payload=payload,
            max_response_bytes=max(32_768, bounded_tokens * 24),
        )
        try:
            completion = _ChatCompletion.model_validate(response.json())
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError):
            raise InvalidProviderOutputError(("invalid_completion_envelope",)) from None
        if completion.usage.completion_tokens > bounded_tokens:
            raise InvalidProviderOutputError(("output_limit_exceeded",))
        return (
            completion.choices[0].message.content,
            completion,
            max(0, (perf_counter_ns() - started) // 1_000_000),
        )


class ZhipuOfficialAccountArticleGenerator:
    def __init__(self, transport: _StructuredArticleClient) -> None:
        self._transport = transport

    async def generate(
        self,
        request: OfficialAccountGenerationRequest,
    ) -> OfficialAccountGenerationResult:
        content, completion, metrics, corrections = await _complete_strict_json(
            transport=self._transport,
            base_prompt=build_generation_prompt(request),
            output_tokens=request.max_output_tokens,
            schema=GeneratedArticleDraft,
            schema_name="GeneratedArticleDraft",
            include_schema_in_initial_system=(
                request.identity.generator_prompt_version
                in {
                    OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V5_VERSION,
                    OFFICIAL_ACCOUNT_GENERATOR_PROMPT_VERSION,
                    OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V7_VERSION,
                }
                and request.identity.rule_version == OFFICIAL_ACCOUNT_RULE_VERSION
            ),
        )
        draft = GeneratedArticleDraft.model_validate_json(content)
        return OfficialAccountGenerationResult(
            draft=draft,
            provider="zhipu",
            model=self._transport.model,
            request_fingerprint=generation_request_fingerprint(request),
            provider_request_id=_safe_provider_request_id(completion.id),
            prompt_tokens=metrics[0],
            completion_tokens=metrics[1],
            reasoning_tokens=metrics[2],
            latency_ms=metrics[3],
            validation_corrections=corrections,
        )


class ZhipuOfficialAccountArticleAuditor:
    def __init__(self, transport: _StructuredArticleClient) -> None:
        self._transport = transport

    async def audit(
        self,
        request: OfficialAccountAuditRequest,
    ) -> OfficialAccountAuditResult:
        content, completion, metrics, corrections = await _complete_strict_json(
            transport=self._transport,
            base_prompt=build_audit_prompt(request),
            output_tokens=request.max_output_tokens,
            schema=OfficialAccountAuditVerdict,
            schema_name="OfficialAccountAuditVerdict",
            include_schema_in_initial_system=(
                request.identity.auditor_prompt_version == OFFICIAL_ACCOUNT_AUDITOR_PROMPT_VERSION
            ),
        )
        verdict = OfficialAccountAuditVerdict.model_validate_json(content)
        return OfficialAccountAuditResult(
            verdict=verdict,
            provider="zhipu",
            model=self._transport.model,
            request_fingerprint=audit_request_fingerprint(request),
            provider_request_id=_safe_provider_request_id(completion.id),
            prompt_tokens=metrics[0],
            completion_tokens=metrics[1],
            reasoning_tokens=metrics[2],
            latency_ms=metrics[3],
            validation_corrections=corrections,
        )


async def _complete_strict_json(
    *,
    transport: _StructuredArticleClient,
    base_prompt: str,
    output_tokens: int,
    schema: type[BaseModel],
    schema_name: str,
    include_schema_in_initial_system: bool,
) -> tuple[str, _ChatCompletion, tuple[int, int, int, int], int]:
    corrections = 0
    validation_issues: tuple[ProviderValidationIssue, ...] = ()
    totals = [0, 0, 0, 0]
    system_instruction = (
        _initial_system_instruction(schema=schema, schema_name=schema_name)
        if include_schema_in_initial_system
        else _BASE_SYSTEM_INSTRUCTION
    )
    while True:
        correction = ""
        if corrections:
            validation_schema = _validation_schema(schema)
            invariant_hint = _validation_invariant_hint(schema)
            correction = (
                f"\n上一次输出未通过{schema_name}结构校验。只按下列Schema重新输出JSON。"
                f"<VALIDATION_SCHEMA>{validation_schema}</VALIDATION_SCHEMA>"
                f"{invariant_hint}"
                f"<VALIDATION_ERRORS>{canonical_json(_issue_projection(validation_issues))}"
                "</VALIDATION_ERRORS>"
            )
        raw_content, completion, latency_ms = await transport.complete(
            prompt=f"{base_prompt}{correction}",
            output_tokens=output_tokens,
            system_instruction=system_instruction,
        )
        details = completion.usage.completion_tokens_details
        totals[0] += completion.usage.prompt_tokens
        totals[1] += completion.usage.completion_tokens
        totals[2] += details.reasoning_tokens if details is not None else 0
        totals[3] += latency_ms
        try:
            normalized = extract_provider_json_object(raw_content)
            schema.model_validate_json(normalized)
            return (
                normalized,
                completion,
                (totals[0], totals[1], totals[2], totals[3]),
                corrections,
            )
        except ProviderJsonEnvelopeError:
            validation_issues = (
                ProviderValidationIssue(loc=("root",), type="json_envelope_invalid"),
            )
        except ValidationError as error:
            validation_issues = _safe_validation_issues(schema, error)
        if corrections >= transport.max_validation_corrections:
            raise InvalidProviderOutputError(
                ("invalid_article_schema",),
                validation_issues=validation_issues,
            ) from None
        corrections += 1


def _issue_projection(
    issues: tuple[ProviderValidationIssue, ...],
) -> list[dict[str, object]]:
    return [{"loc": list(issue.loc), "type": issue.type} for issue in issues]


def _safe_validation_issues(
    schema: type[BaseModel],
    error: ValidationError,
) -> tuple[ProviderValidationIssue, ...]:
    safe_location_segments = _schema_location_segments(schema)
    return normalize_provider_validation_issues(
        (
            tuple(
                segment
                if isinstance(segment, int) or segment in safe_location_segments
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


def _schema_location_segments(schema: type[BaseModel]) -> frozenset[str]:
    segments = {"root"}

    def visit(node: object) -> None:
        if isinstance(node, dict):
            properties = node.get("properties")
            if isinstance(properties, dict):
                segments.update(str(name) for name in properties)
            for value in node.values():
                visit(value)
        elif isinstance(node, list):
            for value in node:
                visit(value)

    visit(schema.model_json_schema(mode="validation"))
    return frozenset(segments)


def _validation_schema(schema: type[BaseModel]) -> str:
    serialized = canonical_json(schema.model_json_schema(mode="validation"))
    if len(serialized) > _MAX_VALIDATION_SCHEMA_CHARACTERS:
        raise ProviderInputLimitError()
    return serialized


def _initial_system_instruction(*, schema: type[BaseModel], schema_name: str) -> str:
    return (
        f"{_BASE_SYSTEM_INSTRUCTION}\n"
        f"输出必须通过{schema_name}的严格校验，只输出一个JSON对象。"
        f"<OUTPUT_SCHEMA>{_validation_schema(schema)}</OUTPUT_SCHEMA>"
        f"{_validation_invariant_hint(schema)}"
    )


def _validation_invariant_hint(schema: type[BaseModel]) -> str:
    if schema is not OfficialAccountAuditVerdict:
        return ""
    serialized = canonical_json(
        {
            "allOf": [
                {
                    "if": {
                        "properties": {"accepted": {"const": True}},
                        "required": ["accepted"],
                    },
                    "then": {
                        "properties": {
                            "claim_ids": {"maxItems": 0},
                            "issue_codes": {"maxItems": 0},
                        }
                    },
                },
                {
                    "if": {
                        "properties": {"accepted": {"const": False}},
                        "required": ["accepted"],
                    },
                    "then": {
                        "properties": {"issue_codes": {"minItems": 1}},
                        "required": ["issue_codes"],
                    },
                },
            ]
        }
    )
    tagged = f"<VALIDATION_INVARIANTS>{serialized}</VALIDATION_INVARIANTS>"
    if len(tagged) > _MAX_VALIDATION_INVARIANT_HINT_CHARACTERS:
        raise ProviderInputLimitError()
    return tagged


def create_zhipu_official_account_models(
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
) -> tuple[ZhipuOfficialAccountArticleGenerator, ZhipuOfficialAccountArticleAuditor]:
    transport = _StructuredArticleClient(
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
    return (
        ZhipuOfficialAccountArticleGenerator(transport),
        ZhipuOfficialAccountArticleAuditor(transport),
    )
