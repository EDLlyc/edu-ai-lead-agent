"""Bounded OpenAI-compatible transport with no environment or live-provider defaults."""

from __future__ import annotations

import base64
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from hashlib import sha256
from typing import Any, Protocol
from urllib.parse import urlsplit

import httpx

from .models import (
    MAX_IMAGE_BYTES,
    MAX_IMAGES,
    MAX_REQUEST_BYTES,
    ArtifactReference,
    NativeCost,
    PairwiseJudgeRequest,
    PanelModelIdentity,
    VoteProfile,
)
from .parsing import (
    UNTRUSTED_BOUNDARY_SYSTEM_INSTRUCTION,
    JudgeContentProfile,
    ModelPanelParseError,
    build_pairwise_user_prompt,
    strict_json_object,
)

OPENAI_COMPATIBLE_TRANSPORT_VERSION = "openai-compatible-model-panel-v1"
ALLOWED_IMAGE_MEDIA_TYPES = frozenset({"image/png", "image/jpeg", "image/webp"})


class OpenAICompatibleRequestProfile(StrEnum):
    """Closed request dialects; callers cannot inject arbitrary provider options."""

    JSON_OBJECT = "json-object-v1"
    ZHIPU_VISION = "zhipu-vision-v1"


class PanelTransportError(RuntimeError):
    """A safe transport failure that never exposes a response, prompt, URL, or credential."""

    def __init__(self, code: str, *, outcome_unknown: bool) -> None:
        super().__init__(code)
        self.code = code
        self.outcome_unknown = outcome_unknown


class NativeCostExtractor(Protocol):
    def __call__(self, response: dict[str, Any]) -> NativeCost | None: ...


class JudgeTransport(Protocol):
    async def complete(
        self,
        *,
        identity: PanelModelIdentity,
        request: PairwiseJudgeRequest,
        material: JudgeMaterial,
    ) -> TransportCompletion: ...


@dataclass(frozen=True, slots=True)
class JudgeImage:
    reference: ArtifactReference
    content: bytes

    def __post_init__(self) -> None:
        if not self.content or len(self.content) > MAX_IMAGE_BYTES:
            raise ValueError("judge image has an invalid byte length")
        if len(self.content) != self.reference.byte_size:
            raise ValueError("judge image byte length does not match its reference")
        if sha256(self.content).hexdigest() != self.reference.sha256:
            raise ValueError("judge image hash does not match its reference")
        if not _matches_signature(self.reference.media_type, self.content):
            raise ValueError("judge image signature does not match its media type")


@dataclass(frozen=True, slots=True)
class JudgeMaterial:
    rubric_instruction: str
    candidate_a_text: str = ""
    candidate_b_text: str = ""
    images: tuple[JudgeImage, ...] = ()

    def validate_against(self, request: PairwiseJudgeRequest) -> None:
        if len(self.images) > MAX_IMAGES:
            raise ValueError("judge material contains too many images")
        if sha256(self.rubric_instruction.encode("utf-8")).hexdigest() != request.rubric_sha256:
            raise ValueError("judge rubric does not match its frozen hash")
        if (
            sha256(self.candidate_a_text.encode("utf-8")).hexdigest()
            != request.candidate_a_text_sha256
            or sha256(self.candidate_b_text.encode("utf-8")).hexdigest()
            != request.candidate_b_text_sha256
        ):
            raise ValueError("judge candidate text does not match its frozen hash")
        actual_refs = tuple(image.reference for image in self.images)
        if actual_refs != request.artifacts:
            raise ValueError("judge material images do not match the request artifacts")
        if (
            request.vote_profile
            in {
                VoteProfile.TEXT_PAIR,
                VoteProfile.TEXT_PAIR_ARM_VERDICT,
            }
            and self.images
        ):
            raise ValueError("text vote profile cannot contain image material")


@dataclass(frozen=True, slots=True)
class TransportCompletion:
    """Ephemeral provider output. Callers must validate and discard ``content`` immediately."""

    returned_model: str
    content: str
    input_tokens: int | None
    output_tokens: int | None
    reasoning_tokens: int | None
    native_cost: NativeCost | None
    judge_content_profile: JudgeContentProfile = JudgeContentProfile.EXACT_JSON


@dataclass(frozen=True, slots=True)
class OpenAICompatibleEndpoint:
    chat_completions_url: str
    allowed_hosts: tuple[str, ...]
    allowed_models: tuple[str, ...]
    timeout_seconds: float = 90.0
    max_request_bytes: int = MAX_REQUEST_BYTES
    max_response_bytes: int = 4 * 1024 * 1024

    def __post_init__(self) -> None:
        parsed = urlsplit(self.chat_completions_url)
        if (
            parsed.scheme != "https"
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or not parsed.hostname
            or not parsed.path.endswith("/chat/completions")
        ):
            raise ValueError("model-panel endpoint must be an exact HTTPS chat-completions URL")
        normalized_hosts = tuple(sorted({host.lower() for host in self.allowed_hosts}))
        if not normalized_hosts or normalized_hosts != self.allowed_hosts:
            raise ValueError("allowed hosts must be unique, lowercase, and sorted")
        if parsed.hostname.lower() not in normalized_hosts:
            raise ValueError("model-panel endpoint host is not allowlisted")
        normalized_models = tuple(sorted(set(self.allowed_models)))
        if not normalized_models or normalized_models != self.allowed_models:
            raise ValueError("allowed models must be unique and lexically sorted")
        if any(not model or len(model) > 192 for model in normalized_models):
            raise ValueError("allowed model identity has an invalid length")
        if not 1 <= self.timeout_seconds <= 420:
            raise ValueError("model-panel timeout is outside the bounded range")
        if not 1 <= self.max_request_bytes <= MAX_REQUEST_BYTES:
            raise ValueError("model-panel request limit is outside the bounded range")
        if not 1 <= self.max_response_bytes <= 4 * 1024 * 1024:
            raise ValueError("model-panel response limit is outside the bounded range")


class OpenAICompatibleJudgeTransport:
    """One-shot adapter used by ToAPIs or direct Zhipu through explicit injection."""

    def __init__(
        self,
        *,
        client: httpx.AsyncClient,
        endpoint: OpenAICompatibleEndpoint,
        bearer_token: str,
        native_cost_extractor: NativeCostExtractor,
        request_profile: OpenAICompatibleRequestProfile = (
            OpenAICompatibleRequestProfile.JSON_OBJECT
        ),
    ) -> None:
        if not bearer_token or len(bearer_token) > 4_096:
            raise ValueError("provider credential has an invalid length")
        if not isinstance(request_profile, OpenAICompatibleRequestProfile):
            raise ValueError("model-panel request profile must be a closed profile")
        self._client = client
        self._endpoint = endpoint
        self._bearer_token = bearer_token
        self._native_cost_extractor = native_cost_extractor
        self._request_profile = request_profile

    async def complete(
        self,
        *,
        identity: PanelModelIdentity,
        request: PairwiseJudgeRequest,
        material: JudgeMaterial,
    ) -> TransportCompletion:
        endpoint_host = urlsplit(self._endpoint.chat_completions_url).hostname
        if endpoint_host is None:
            raise PanelTransportError("provider_identity_mismatch", outcome_unknown=False)
        if (
            identity.requested_model not in self._endpoint.allowed_models
            or identity.endpoint_host_sha256 != sha256(endpoint_host.encode("ascii")).hexdigest()
        ):
            raise PanelTransportError("provider_identity_mismatch", outcome_unknown=False)
        material.validate_against(request)
        prompt = build_pairwise_user_prompt(
            request=request,
            rubric_instruction=material.rubric_instruction,
            candidate_a_text=material.candidate_a_text,
            candidate_b_text=material.candidate_b_text,
        )
        content: list[dict[str, object]] = [{"type": "text", "text": prompt}]
        for image in material.images:
            group = image.reference.presented_group.value
            label = "REFERENCE" if group == "reference" else f"CANDIDATE_{group}"
            content.append(
                {
                    "type": "text",
                    "text": f"<UNTRUSTED_{label}_IMAGE ref={image.reference.artifact_ref}>",
                }
            )
            encoded = base64.b64encode(image.content).decode("ascii")
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{image.reference.media_type};base64,{encoded}",
                    },
                }
            )
            content.append(
                {
                    "type": "text",
                    "text": f"</UNTRUSTED_{label}_IMAGE>",
                }
            )
        messages: list[dict[str, object]] = [
            {"role": "system", "content": UNTRUSTED_BOUNDARY_SYSTEM_INSTRUCTION},
            {"role": "user", "content": content},
        ]
        payload = _request_payload(
            profile=self._request_profile,
            requested_model=identity.requested_model,
            max_output_tokens=request.max_output_tokens,
            messages=messages,
        )
        encoded_payload = _canonical_transport_json(payload)
        if len(encoded_payload) > self._endpoint.max_request_bytes:
            raise PanelTransportError("provider_request_too_large", outcome_unknown=False)
        try:
            async with self._client.stream(
                "POST",
                self._endpoint.chat_completions_url,
                content=encoded_payload,
                headers={
                    "Authorization": f"Bearer {self._bearer_token}",
                    "Content-Type": "application/json",
                },
                timeout=self._endpoint.timeout_seconds,
                follow_redirects=False,
            ) as response:
                if response.status_code < 200 or response.status_code >= 300:
                    raise PanelTransportError(
                        "provider_rejected",
                        outcome_unknown=response.status_code >= 500,
                    )
                media_type = (
                    response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
                )
                if media_type != "application/json":
                    raise PanelTransportError(
                        "provider_envelope_invalid",
                        outcome_unknown=False,
                    )
                response_body = bytearray()
                async for chunk in response.aiter_bytes():
                    if len(response_body) + len(chunk) > self._endpoint.max_response_bytes:
                        raise PanelTransportError(
                            "provider_envelope_invalid",
                            outcome_unknown=False,
                        )
                    response_body.extend(chunk)
        except PanelTransportError:
            raise
        except httpx.TimeoutException as exc:
            raise PanelTransportError("provider_timeout", outcome_unknown=True) from exc
        except httpx.RequestError as exc:
            raise PanelTransportError("provider_connection_failed", outcome_unknown=True) from exc
        try:
            envelope = strict_json_object(
                bytes(response_body),
                max_bytes=self._endpoint.max_response_bytes,
            )
            returned_model = _required_string(envelope, "model")
            content_text = _completion_content(envelope)
            usage = _usage(envelope)
            native_cost = self._native_cost_extractor(envelope)
        except (ModelPanelParseError, ValueError, TypeError, InvalidOperation) as exc:
            raise PanelTransportError(
                "provider_envelope_invalid",
                outcome_unknown=False,
            ) from exc
        return TransportCompletion(
            returned_model=returned_model,
            content=content_text,
            input_tokens=None if usage is None else usage[0],
            output_tokens=None if usage is None else usage[1],
            reasoning_tokens=None if usage is None else usage[2],
            native_cost=native_cost,
            judge_content_profile=(
                JudgeContentProfile.ZHIPU_VISION
                if self._request_profile is OpenAICompatibleRequestProfile.ZHIPU_VISION
                else JudgeContentProfile.EXACT_JSON
            ),
        )


def _request_payload(
    *,
    profile: OpenAICompatibleRequestProfile,
    requested_model: str,
    max_output_tokens: int,
    messages: list[dict[str, object]],
) -> dict[str, object]:
    if profile is OpenAICompatibleRequestProfile.JSON_OBJECT:
        return {
            "model": requested_model,
            "temperature": 0,
            "max_tokens": max_output_tokens,
            "response_format": {"type": "json_object"},
            "messages": messages,
        }
    if profile is OpenAICompatibleRequestProfile.ZHIPU_VISION:
        return {
            "model": requested_model,
            "max_tokens": max_output_tokens,
            "thinking": {"type": "disabled"},
            "do_sample": False,
            "messages": messages,
        }
    raise ValueError("unsupported model-panel request profile")


def decimal_native_cost_extractor(
    *,
    unit: str,
    top_level_field: str,
) -> NativeCostExtractor:
    """Build an explicit extractor for a documented top-level native-cost field."""

    def extract(response: dict[str, Any]) -> NativeCost | None:
        raw = response.get(top_level_field)
        if raw is None:
            return None
        if isinstance(raw, bool) or not isinstance(raw, (str, int, float)):
            raise ValueError("native cost has an invalid type")
        value = Decimal(str(raw))
        if not value.is_finite() or value < 0:
            raise ValueError("native cost must be finite and non-negative")
        return NativeCost(unit=unit, amount=value)

    return extract


def _canonical_transport_json(value: object) -> bytes:
    import json

    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


def _required_string(value: dict[str, Any], key: str) -> str:
    item = value.get(key)
    if not isinstance(item, str) or not item or len(item) > 192:
        raise ValueError("provider envelope contains an invalid string field")
    return item


def _completion_content(envelope: dict[str, Any]) -> str:
    choices = envelope.get("choices")
    if not isinstance(choices, list) or len(choices) != 1:
        raise ValueError("provider envelope must contain exactly one choice")
    choice = choices[0]
    if not isinstance(choice, dict):
        raise ValueError("provider choice has an invalid shape")
    finish_reason = choice.get("finish_reason")
    if finish_reason not in {"stop", "completed"}:
        raise ValueError("provider choice did not finish normally")
    message = choice.get("message")
    if not isinstance(message, dict):
        raise ValueError("provider message has an invalid shape")
    content = message.get("content")
    if not isinstance(content, str) or not content:
        raise ValueError("provider completion content is missing")
    return content


def _usage(envelope: dict[str, Any]) -> tuple[int, int, int | None] | None:
    value = envelope.get("usage")
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("provider usage has an invalid shape")
    input_tokens = _one_non_negative_integer(value, "prompt_tokens", "input_tokens")
    output_tokens = _one_non_negative_integer(value, "completion_tokens", "output_tokens")
    reasoning_tokens = value.get("reasoning_tokens")
    if reasoning_tokens is not None and (
        isinstance(reasoning_tokens, bool)
        or not isinstance(reasoning_tokens, int)
        or not 0 <= reasoning_tokens <= 10_000_000
    ):
        raise ValueError("provider reasoning usage is invalid")
    return input_tokens, output_tokens, reasoning_tokens


def _one_non_negative_integer(value: dict[str, Any], *keys: str) -> int:
    present = [value[key] for key in keys if key in value]
    if len(present) != 1:
        raise ValueError("provider usage must contain exactly one compatible token field")
    item = present[0]
    if isinstance(item, bool) or not isinstance(item, int) or not 0 <= item <= 10_000_000:
        raise ValueError("provider token usage is outside bounds")
    return int(item)


def _matches_signature(media_type: str, content: bytes) -> bool:
    if media_type not in ALLOWED_IMAGE_MEDIA_TYPES:
        return False
    if media_type == "image/png":
        return content.startswith(b"\x89PNG\r\n\x1a\n")
    if media_type == "image/jpeg":
        return content.startswith(b"\xff\xd8\xff")
    return len(content) >= 12 and content[:4] == b"RIFF" and content[8:12] == b"WEBP"
