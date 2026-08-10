from __future__ import annotations

# ruff: noqa: RUF001
import asyncio
import json
import re
from time import perf_counter_ns
from typing import Any
from urllib.parse import urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr, ValidationError

from app.application.ports.copy_generation import (
    DraftAuditRequest,
    DraftAuditResult,
    DraftGenerationRequest,
    DraftGenerationResult,
)
from app.application.services.copy_generation import (
    auditor_request_fingerprint,
    build_auditor_prompt,
    build_generator_prompt,
    generator_request_fingerprint,
)
from app.core.errors import (
    InvalidProviderOutputError,
    ProviderInputLimitError,
    ProviderValidationIssue,
    normalize_provider_validation_issues,
    provider_validation_issues_metadata,
)
from app.infrastructure.ai.zhipu import _post_json_with_retries, _safe_provider_request_id
from app.schemas.copy_generation import AuditVerdict, CopyIssue, DraftClaim, MaterialDraft

_PROVIDER_JSON_MAX_CHARACTERS = 32_768
_PROVIDER_JSON_MAX_AFFIX_CHARACTERS = 512
_JSON_PRIMITIVE = re.compile(
    r'(?:true|false|null|-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?|"(?:[^"\\]|\\.)*")',
    re.DOTALL,
)


class ProviderJsonEnvelopeError(ValueError):
    __slots__ = ("validation_type",)

    def __init__(self, validation_type: str) -> None:
        super().__init__("provider JSON envelope is invalid")
        self.validation_type = validation_type


def extract_provider_json_object(
    content: str,
    *,
    max_characters: int = _PROVIDER_JSON_MAX_CHARACTERS,
    max_affix_characters: int = _PROVIDER_JSON_MAX_AFFIX_CHARACTERS,
) -> str:
    """Extract one bounded top-level JSON object without interpreting surrounding prose."""

    if max_characters < 2 or max_affix_characters < 0:
        raise ValueError("provider JSON extraction limits are invalid")
    if len(content) > max_characters:
        raise ProviderJsonEnvelopeError("json_too_long")
    stripped = content.strip()
    if not stripped:
        raise ProviderJsonEnvelopeError("json_invalid")
    if stripped.startswith("```") or stripped.endswith("```"):
        lines = stripped.splitlines()
        if (
            len(lines) < 3
            or lines[0].strip().casefold() != "```json"
            or lines[-1].strip() != "```"
            or stripped.count("```") != 2
        ):
            raise ProviderJsonEnvelopeError("json_invalid")
        return _extract_unique_json_object(
            "\n".join(lines[1:-1]).strip(),
            max_affix_characters=0,
        )
    if "```" in stripped:
        raise ProviderJsonEnvelopeError("json_invalid")
    return _extract_unique_json_object(
        stripped,
        max_affix_characters=max_affix_characters,
    )


def _extract_unique_json_object(content: str, *, max_affix_characters: int) -> str:
    if content.lstrip().startswith("["):
        raise ProviderJsonEnvelopeError("json_array_root")
    start = content.find("{")
    if start < 0:
        raise ProviderJsonEnvelopeError("json_invalid")
    prefix = content[:start].strip()
    if len(prefix) > max_affix_characters:
        raise ProviderJsonEnvelopeError("json_affix_too_long")
    if _contains_competing_json_structure(prefix):
        raise ProviderJsonEnvelopeError("json_multiple_structures")

    depth = 0
    in_string = False
    escaped = False
    end: int | None = None
    for index in range(start, len(content)):
        character = content[index]
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth < 0:
                raise ProviderJsonEnvelopeError("json_invalid")
            if depth == 0:
                end = index
                break
    if end is None:
        raise ProviderJsonEnvelopeError("json_unclosed")

    suffix = content[end + 1 :].strip()
    if len(suffix) > max_affix_characters:
        raise ProviderJsonEnvelopeError("json_affix_too_long")
    if _contains_competing_json_structure(suffix):
        raise ProviderJsonEnvelopeError("json_multiple_structures")
    candidate = content[start : end + 1]
    try:
        parsed: object = json.loads(candidate, parse_constant=_reject_non_json_constant)
    except (json.JSONDecodeError, TypeError, ValueError):
        raise ProviderJsonEnvelopeError("json_invalid") from None
    if not isinstance(parsed, dict):
        raise ProviderJsonEnvelopeError("json_array_root")
    return candidate


def _contains_competing_json_structure(value: str) -> bool:
    if not value:
        return False
    if any(character in value for character in "{}[]"):
        return True
    return _JSON_PRIMITIVE.fullmatch(value) is not None


def _reject_non_json_constant(_value: str) -> None:
    raise ValueError("non-standard JSON constant")


class DeterministicFakeMaterialDraftGenerator:
    def __init__(self, *, model: str) -> None:
        self._model = model

    async def generate(self, request: DraftGenerationRequest) -> DraftGenerationResult:
        evidence = request.topic.evidence[0]
        brand = request.brand_context[0]
        fact = _bounded_sentence(evidence.exact_quote, 120)
        brand_statement = "赛先生重视科学精神、好奇心、思考力和创造力。"
        opinion = "这也提醒我们，和孩子一起理解技术、提出问题，比追逐概念更有价值。"
        body = (
            f"📚 今天想和家长分享一条科技教育动态：{fact}\n"
            "孩子从真实问题开始观察技术，才会把陌生名词变成理解世界的线索。🔎\n\n"
            f"🤖 {opinion}\n"
            "科学学习的价值不只在答案，而在提问、找证据和动手验证想法。💡\n\n"
            f"✨ {brand_statement}\n"
            "在赛先生，孩子会观察、实践、复盘，把好奇心慢慢变成解决问题的能力。🚀"
        )
        copywriting = f"{body}\n#赛先生科学 #人工智能启蒙 #科学思维"
        draft = MaterialDraft(
            copywriting=copywriting,
            parent_takeaway="帮助家长用可靠信息和开放问题陪伴孩子理解人工智能。",
            interaction="你最近和孩子讨论过哪一个人工智能或机器人话题？",
            source_note=f"信息来源：{evidence.source_name}（原文链接供内部审核核对）。",
            image_prompt=(
                "深蓝与亮蓝科技背景，橙色点缀，友好圆润的科学教育插画，"
                "家长与孩子共同观察人工智能和机器人，不出现真人正脸、文字承诺或平台标识。"
            ),
            claims=(
                DraftClaim(
                    id="fact-1",
                    text=fact,
                    kind="external_fact",
                    evidence_ids=(evidence.evidence_id,),
                ),
                DraftClaim(
                    id="brand-1",
                    text=brand_statement,
                    kind="brand_statement",
                    brand_chunk_ids=(brand.chunk_id,),
                ),
                DraftClaim(id="opinion-1", text=opinion, kind="opinion"),
            ),
        )
        return DraftGenerationResult(
            draft=draft,
            provider="fake",
            model=self._model,
            request_fingerprint=generator_request_fingerprint(request, "fake", self._model),
            provider_request_id=None,
            prompt_tokens=0,
            completion_tokens=0,
            reasoning_tokens=0,
            latency_ms=0,
        )


class DeterministicFakeMaterialDraftAuditor:
    def __init__(self, *, model: str) -> None:
        self._model = model

    async def audit(self, request: DraftAuditRequest) -> DraftAuditResult:
        if "需要人工修复" in request.draft.copywriting:
            verdict = AuditVerdict(
                accepted=False,
                issues=(
                    CopyIssue(
                        code="brand_fit",
                        message="表达不符合品牌语气",
                        severity="error",
                        field="copywriting",
                    ),
                ),
            )
        else:
            verdict = AuditVerdict(accepted=True)
        return DraftAuditResult(
            verdict=verdict,
            provider="fake",
            model=self._model,
            request_fingerprint=auditor_request_fingerprint(request, "fake", self._model),
            provider_request_id=None,
            prompt_tokens=0,
            completion_tokens=0,
            reasoning_tokens=0,
            latency_ms=0,
        )


class _ProviderModel(BaseModel):
    model_config = ConfigDict(extra="ignore")


class _CompletionTokenDetails(_ProviderModel):
    reasoning_tokens: int = Field(default=0, ge=0)


class _Usage(_ProviderModel):
    prompt_tokens: int = Field(default=0, ge=0)
    completion_tokens: int = Field(default=0, ge=0)
    completion_tokens_details: _CompletionTokenDetails | None = None


class _Message(_ProviderModel):
    content: str


class _Choice(_ProviderModel):
    message: _Message


class _ChatCompletion(_ProviderModel):
    id: str | None = None
    choices: tuple[_Choice, ...] = Field(min_length=1)
    usage: _Usage = Field(default_factory=_Usage)


class _ZhipuStructuredCopyClient:
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
            raise ValueError("copy provider base URL must be a safe HTTPS origin/path")
        api_key_value = api_key.get_secret_value().strip()
        if not api_key_value or any(character in api_key_value for character in "\r\n"):
            raise ValueError("copy provider API key is invalid")
        if not model.strip() or any(character.isspace() for character in model.strip()):
            raise ValueError("copy provider model is invalid")
        self.client = client
        self.url = f"{base_url.strip().rstrip('/')}/chat/completions"
        self.api_key = SecretStr(api_key_value)
        self.model = model.strip()
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
        self, *, prompt: str, output_tokens: int
    ) -> tuple[str, _ChatCompletion, int]:
        if len(prompt) > self.max_input_characters:
            raise ProviderInputLimitError()
        bounded_tokens = min(output_tokens, self.max_output_tokens)
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "只返回严格JSON，不输出Markdown或解释。"},
                {"role": "user", "content": prompt},
            ],
            # Structured copy/audit is a constrained transformation task. GLM-5.2 enables
            # thinking by default; disabling it keeps the bounded output budget for the JSON
            # answer instead of allowing reasoning tokens to exhaust the response first.
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
            max_response_bytes=max(16_384, bounded_tokens * 16),
        )
        try:
            completion = _ChatCompletion.model_validate(response.json())
        except (json.JSONDecodeError, ValidationError, TypeError, ValueError):
            raise InvalidProviderOutputError(("invalid_schema",)) from None
        if completion.usage.completion_tokens > bounded_tokens:
            raise InvalidProviderOutputError(("output_limit_exceeded",))
        return (
            completion.choices[0].message.content,
            completion,
            max(0, (perf_counter_ns() - started) // 1_000_000),
        )


class ZhipuMaterialDraftGenerator:
    def __init__(self, client: _ZhipuStructuredCopyClient) -> None:
        self._client = client

    async def generate(self, request: DraftGenerationRequest) -> DraftGenerationResult:
        base_prompt = build_generator_prompt(request)
        corrections = 0
        validation_errors: str | None = None
        total_prompt_tokens = 0
        total_completion_tokens = 0
        total_reasoning_tokens = 0
        total_latency_ms = 0
        while True:
            correction = (
                "\n上一次输出未通过JSON结构校验。请仅按既定Schema重新输出，不要增加解释。"
                f"<VALIDATION_ERRORS>{validation_errors}</VALIDATION_ERRORS>"
                if corrections
                else ""
            )
            content, completion, latency_ms = await self._client.complete(
                prompt=f"{base_prompt}{correction}",
                output_tokens=request.max_output_tokens,
            )
            details = completion.usage.completion_tokens_details
            total_prompt_tokens += completion.usage.prompt_tokens
            total_completion_tokens += completion.usage.completion_tokens
            total_reasoning_tokens += details.reasoning_tokens if details else 0
            total_latency_ms += latency_ms
            try:
                normalized_content = extract_provider_json_object(content)
                draft = MaterialDraft.model_validate_json(normalized_content)
                break
            except (ProviderJsonEnvelopeError, ValidationError) as error:
                validation_issues = _safe_provider_output_issues(error)
                if corrections >= self._client.max_validation_corrections:
                    raise InvalidProviderOutputError(
                        ("invalid_draft_schema",),
                        validation_issues=validation_issues,
                    ) from None
                validation_errors = _serialize_validation_issues(validation_issues)
                corrections += 1
        return DraftGenerationResult(
            draft=draft,
            provider="zhipu",
            model=self._client.model,
            request_fingerprint=generator_request_fingerprint(request, "zhipu", self._client.model),
            provider_request_id=_safe_provider_request_id(completion.id),
            prompt_tokens=total_prompt_tokens,
            completion_tokens=total_completion_tokens,
            reasoning_tokens=total_reasoning_tokens,
            latency_ms=total_latency_ms,
            validation_corrections=corrections,
        )


class ZhipuMaterialDraftAuditor:
    def __init__(self, client: _ZhipuStructuredCopyClient) -> None:
        self._client = client

    async def audit(self, request: DraftAuditRequest) -> DraftAuditResult:
        base_prompt = build_auditor_prompt(request)
        corrections = 0
        validation_errors: str | None = None
        total_prompt_tokens = 0
        total_completion_tokens = 0
        total_reasoning_tokens = 0
        total_latency_ms = 0
        while True:
            correction = (
                "\n上一次输出未通过AuditVerdict结构校验。请仅按既定Schema重新输出合法JSON。"
                f"<VALIDATION_ERRORS>{validation_errors}</VALIDATION_ERRORS>"
                if corrections
                else ""
            )
            content, completion, latency_ms = await self._client.complete(
                prompt=f"{base_prompt}{correction}",
                output_tokens=request.max_output_tokens,
            )
            details = completion.usage.completion_tokens_details
            total_prompt_tokens += completion.usage.prompt_tokens
            total_completion_tokens += completion.usage.completion_tokens
            total_reasoning_tokens += details.reasoning_tokens if details else 0
            total_latency_ms += latency_ms
            try:
                normalized_content = extract_provider_json_object(content)
                verdict = AuditVerdict.model_validate_json(normalized_content)
                break
            except (ProviderJsonEnvelopeError, ValidationError) as error:
                validation_issues = _safe_provider_output_issues(error)
                if corrections >= self._client.max_validation_corrections:
                    raise InvalidProviderOutputError(
                        ("invalid_audit_schema",),
                        validation_issues=validation_issues,
                    ) from None
                validation_errors = _serialize_validation_issues(validation_issues)
                corrections += 1
        return DraftAuditResult(
            verdict=verdict,
            provider="zhipu",
            model=self._client.model,
            request_fingerprint=auditor_request_fingerprint(request, "zhipu", self._client.model),
            provider_request_id=_safe_provider_request_id(completion.id),
            prompt_tokens=total_prompt_tokens,
            completion_tokens=total_completion_tokens,
            reasoning_tokens=total_reasoning_tokens,
            latency_ms=total_latency_ms,
            validation_corrections=corrections,
        )


def create_zhipu_copy_models(
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
) -> tuple[ZhipuMaterialDraftGenerator, ZhipuMaterialDraftAuditor]:
    transport = _ZhipuStructuredCopyClient(
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
    return ZhipuMaterialDraftGenerator(transport), ZhipuMaterialDraftAuditor(transport)


def _bounded_sentence(value: str, limit: int) -> str:
    normalized = " ".join(value.split()).strip()
    if len(normalized) <= limit:
        return normalized
    boundaries = [
        match.end() for match in re.finditer(r"[。！？!?；;]", normalized) if match.end() <= 300
    ]
    preferred = [boundary for boundary in boundaries if boundary <= limit]
    if preferred:
        return normalized[: preferred[-1]].strip()
    if boundaries:
        return normalized[: boundaries[0]].strip()
    if len(normalized) <= 300:
        return normalized
    return f"{normalized[:297].rstrip('，,；;：: ')}……"


def _safe_validation_issues(error: ValidationError) -> tuple[ProviderValidationIssue, ...]:
    return normalize_provider_validation_issues(
        (item["loc"], item["type"])
        for item in error.errors(
            include_url=False,
            include_context=False,
            include_input=False,
        )
    )


def _safe_provider_output_issues(
    error: ProviderJsonEnvelopeError | ValidationError,
) -> tuple[ProviderValidationIssue, ...]:
    if isinstance(error, ValidationError):
        return _safe_validation_issues(error)
    return normalize_provider_validation_issues([(("root",), error.validation_type)])


def _serialize_validation_issues(issues: tuple[ProviderValidationIssue, ...]) -> str:
    return json.dumps(
        provider_validation_issues_metadata(issues),
        ensure_ascii=False,
        separators=(",", ":"),
    )
