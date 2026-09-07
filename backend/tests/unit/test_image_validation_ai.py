from __future__ import annotations

import base64
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest
from app.application.ports.image_generation import ImageReference
from app.application.ports.image_validation import (
    ImageQualityAuditRequest,
    ImageTextRecognitionRequest,
)
from app.core.errors import (
    InvalidProviderOutputError,
    ProviderError,
    ProviderIdentityMismatchError,
    ProviderInputLimitError,
)
from app.domain.visual_brief import AcceptedVisualContext, build_visual_brief
from app.infrastructure.ai.image_validation import (
    OpenAICompatibleImageQualityAuditor,
    OpenAICompatibleImageTextRecognizer,
)
from pydantic import SecretStr

IMAGE_BYTES = b"bounded-image-fixture"


def _completion(content: str, *, model: str = "vision-model") -> dict[str, object]:
    return {
        "id": "vision-request-1",
        "model": model,
        "choices": [{"message": {"content": content}}],
    }


def _recognizer(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    max_request_bytes: int = 64 * 1024,
) -> tuple[OpenAICompatibleImageTextRecognizer, httpx.AsyncClient]:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        follow_redirects=False,
    )
    return (
        OpenAICompatibleImageTextRecognizer(
            client=client,
            base_url="https://vision.provider.test/v1",
            api_key=SecretStr("test-only-key"),
            model="vision-model",
            connect_timeout_seconds=1,
            read_timeout_seconds=2,
            total_timeout_seconds=3,
            concurrency=1,
            max_attempts=1,
            max_request_bytes=max_request_bytes,
            max_response_bytes=16 * 1024,
        ),
        client,
    )


def _auditor(
    handler: Callable[[httpx.Request], httpx.Response],
    *,
    max_request_bytes: int = 128 * 1024,
    model: str = "vision-model",
    base_url: str = "https://vision.provider.test/v1",
) -> tuple[OpenAICompatibleImageQualityAuditor, httpx.AsyncClient]:
    client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        follow_redirects=False,
        trust_env=False,
    )
    return (
        OpenAICompatibleImageQualityAuditor(
            client=client,
            base_url=base_url,
            api_key=SecretStr("test-only-key"),
            model=model,
            connect_timeout_seconds=1,
            read_timeout_seconds=2,
            total_timeout_seconds=3,
            concurrency=1,
            max_attempts=1,
            max_request_bytes=max_request_bytes,
            max_response_bytes=16 * 1024,
        ),
        client,
    )


def _data_url_bytes(value: str) -> bytes:
    _prefix, encoded = value.split(",", 1)
    return base64.b64decode(encoded, validate=True)


def _audit_request() -> ImageQualityAuditRequest:
    return ImageQualityAuditRequest(
        image_bytes=IMAGE_BYTES,
        request_fingerprint="audit-fingerprint",
        visual_brief=build_visual_brief(
            AcceptedVisualContext(
                topic_title="机器人世界模型取得新进展",
                topic_summary="机器人通过尝试和反馈改进动作。",
            )
        ),
        references=(
            ImageReference(
                role="identity_reference",
                asset_id="xiao-sai-identity",
                filename="xiao-sai.png",
                sha256="a" * 64,
                image_bytes=b"identity-reference",
                selection_reason="approved identity asset",
            ),
            ImageReference(
                role="action_reference",
                asset_id="robotics-action",
                filename="robotics.png",
                sha256="b" * 64,
                image_bytes=b"action-reference",
            ),
        ),
        criteria=(
            "Semantic: depict the exact article scene.",
            "IP identity: preserve the approved protagonist.",
        ),
        prompt_version="image-quality-audit-prompt-v2-publication",
        rubric_version="image-quality-rubric-v1",
    )


@pytest.mark.asyncio
async def test_vision_ocr_sends_a_bounded_data_url_and_returns_typed_result() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["request"] = request
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json=_completion(json.dumps({"recognized_lines": ["科学", "探索"]})),
        )

    adapter, client = _recognizer(handler)
    async with client:
        result = await adapter.recognize(
            ImageTextRecognitionRequest(
                image_bytes=IMAGE_BYTES,
                request_fingerprint="ocr-fingerprint",
                expected_text=("科学", "探索"),
            )
        )

    payload = captured["payload"]
    assert captured["request"].url == "https://vision.provider.test/v1/chat/completions"
    assert captured["request"].headers["authorization"] == "Bearer test-only-key"
    assert payload["model"] == "vision-model"
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["temperature"] == 0.0
    content = payload["messages"][1]["content"]
    prompt_context = json.loads(content[0]["text"])
    assert prompt_context["request_fingerprint"] == "ocr-fingerprint"
    assert prompt_context["require_order"] is False
    assert _data_url_bytes(content[1]["image_url"]["url"]) == IMAGE_BYTES
    assert result.recognized_lines == ("科学", "探索")
    assert result.provider == "openai-compatible"
    assert result.model == "vision-model"
    assert result.request_fingerprint == "ocr-fingerprint"
    assert "test-only-key" not in repr(result)


@pytest.mark.asyncio
async def test_vision_ocr_rejects_malformed_or_free_form_json() -> None:
    responses = iter(
        (
            _completion("not-json"),
            _completion('Here is the answer: {"recognized_lines":["科学"]}'),
            _completion('```json\n{"recognized_lines":["科学"]}\n```'),
        )
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=next(responses))

    adapter, client = _recognizer(handler)
    request = ImageTextRecognitionRequest(
        image_bytes=IMAGE_BYTES,
        request_fingerprint="ocr-fingerprint",
        expected_text=("科学",),
    )
    async with client:
        with pytest.raises(InvalidProviderOutputError) as malformed:
            await adapter.recognize(request)
        with pytest.raises(InvalidProviderOutputError):
            await adapter.recognize(request)
        with pytest.raises(InvalidProviderOutputError):
            await adapter.recognize(request)

    assert malformed.value.issue_codes == ("invalid_schema",)
    assert "not-json" not in str(malformed.value)


@pytest.mark.asyncio
async def test_vision_ocr_rejects_unexpected_text_even_when_json_is_valid() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_completion(json.dumps({"recognized_lines": ["科学", "unapproved text"]})),
        )

    adapter, client = _recognizer(handler)
    async with client:
        with pytest.raises(InvalidProviderOutputError) as raised:
            await adapter.recognize(
                ImageTextRecognitionRequest(
                    image_bytes=IMAGE_BYTES,
                    request_fingerprint="ocr-fingerprint",
                    expected_text=("科学",),
                )
            )

    assert raised.value.issue_codes == ("unexpected_visual_text",)


@pytest.mark.asyncio
async def test_vision_ocr_rejects_reordered_controlled_text() -> None:
    expected = ("赛先生科学", "人工智能", "理解智能如何学习与反馈")

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_completion(
                json.dumps({"recognized_lines": list(reversed(expected))}, ensure_ascii=False)
            ),
        )

    adapter, client = _recognizer(handler)
    async with client:
        with pytest.raises(InvalidProviderOutputError) as raised:
            await adapter.recognize(
                ImageTextRecognitionRequest(
                    image_bytes=IMAGE_BYTES,
                    request_fingerprint="controlled-ocr-fingerprint",
                    expected_text=expected,
                    require_order=True,
                )
            )

    assert raised.value.issue_codes == ("misordered_visual_text",)


@pytest.mark.asyncio
async def test_vision_audit_accepts_typed_reference_inputs_in_order() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json=_completion(json.dumps({"accepted": True, "issues": []})),
        )

    adapter, client = _auditor(handler)
    async with client:
        result = await adapter.audit(_audit_request())

    payload = captured["payload"]
    assert set(payload) == {"model", "messages", "max_tokens", "thinking", "do_sample"}
    assert payload["thinking"] == {"type": "disabled"}
    assert payload["do_sample"] is False
    content = payload["messages"][1]["content"]
    assert len(content) == 4
    assert _data_url_bytes(content[1]["image_url"]["url"]) == IMAGE_BYTES
    assert _data_url_bytes(content[2]["image_url"]["url"]) == b"identity-reference"
    assert _data_url_bytes(content[3]["image_url"]["url"]) == b"action-reference"
    assert content[2]["image_url"]["url"].startswith("data:image/png;base64,")
    prompt_context = json.loads(content[0]["text"])
    assert prompt_context["request_fingerprint"] == "audit-fingerprint"
    assert prompt_context["prompt_version"] == "image-quality-audit-prompt-v2-publication"
    assert prompt_context["rubric_version"] == "image-quality-rubric-v1"
    assert prompt_context["case_criteria"] == [
        "Semantic: depict the exact article scene.",
        "IP identity: preserve the approved protagonist.",
    ]
    issue_contracts = {item["code"]: item for item in prompt_context["allowed_issue_contracts"]}
    assert "provider_audit_unclassified" not in issue_contracts
    assert issue_contracts["semantic_core_entity_missing"] == {
        "code": "semantic_core_entity_missing",
        "dimension": "semantic_faithfulness",
        "severity": "error",
    }
    assert issue_contracts["ip_identity_borderline"]["severity"] == "warning"
    assert "diversity_exact_duplicate" not in issue_contracts
    assert prompt_context["typed_references"][0]["role"] == "identity_reference"
    assert prompt_context["typed_references"][1]["asset_id"] == "robotics-action"
    assert result.accepted is True
    assert result.issues == ()
    assert result.provider == "openai-compatible"
    assert result.request_fingerprint == "audit-fingerprint"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    (
        '{"accepted":true,"issues":[]}',
        ' \n{"accepted":true,"issues":[]}\n ',
        '```json\n{"accepted":true,"issues":[]}\n```',
    ),
)
async def test_glm_vision_audit_exact_route_model_and_json_framing(content: str) -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert request.url == "https://open.bigmodel.cn/api/paas/v4/chat/completions"
        payload = json.loads(request.content)
        assert payload["model"] == "glm-5v-turbo"
        image_url = payload["messages"][1]["content"][1]["image_url"]["url"]
        assert image_url.startswith("data:image/jpeg;base64,")
        assert _data_url_bytes(image_url) == IMAGE_BYTES
        return httpx.Response(200, json=_completion(content, model="glm-5v-turbo"))

    adapter, client = _auditor(
        handler, model="glm-5v-turbo", base_url="https://open.bigmodel.cn/api/paas/v4"
    )
    async with client:
        result = await adapter.audit(
            ImageQualityAuditRequest(
                image_bytes=IMAGE_BYTES,
                media_type="image/jpeg",
                request_fingerprint="final-jpeg-fingerprint",
                criteria=("Review the final publication crop.",),
            )
        )
    assert calls == 1
    assert result.model == "glm-5v-turbo"
    assert result.accepted is True
    assert result.issues == ()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "content",
    (
        'private sentinel {"accepted":true,"issues":[]}',
        '{"accepted":true,"issues":[]} private sentinel',
        '{"accepted":true,"issues":[]} {}',
        '[{"accepted":true,"issues":[]}]',
        '```JSON\n{"accepted":true,"issues":[]}\n```',
        '```\n{"accepted":true,"issues":[]}\n```',
        '```json\n{"accepted":true,"issues":[]}',
        '```json\n{"accepted":true,"issues":[]}\n```\n```json\n{}\n```',
        '{"accepted":false,"accepted":true,"issues":[]}',
        '{"accepted":false,"issues":[{"code":"a","code":"b","severity":"error"}]}',
        '{"accepted":true,"issues":[],"reason":"private sentinel"}',
        '{"accepted":"true","issues":[]}',
        '{"accepted":true,"issues":null}',
        '{"accepted":NaN,"issues":[]}',
        '{"accepted":true,"issues":[{"code":"a","severity":"error"}]}',
        '{"accepted":false,"issues":[{"code":"a","severity":"warning","extra":1}]}',
        "[" * 2_000 + "]" * 2_000,
    ),
)
async def test_vision_audit_rejects_ambiguous_or_invalid_output_once(content: str) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_completion(content))

    adapter, client = _auditor(handler)
    async with client:
        with pytest.raises(InvalidProviderOutputError) as raised:
            await adapter.audit(_audit_request())
    assert calls == 1
    assert raised.value.issue_codes == ("invalid_schema",)
    assert "private sentinel" not in str(raised.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("returned_model", ("glm-5.2", "glm-5v-turbo-alias", "GLM-5V-TURBO", ""))
async def test_glm_audit_rejects_returned_model_mismatch_once(returned_model: str) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200, json=_completion('{"accepted":true,"issues":[]}', model=returned_model)
        )

    adapter, client = _auditor(handler, model="glm-5v-turbo")
    async with client:
        with pytest.raises(ProviderIdentityMismatchError):
            await adapter.audit(_audit_request())
    assert calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "envelope",
    (
        '{"model":"glm-5.2","model":"glm-5v-turbo","choices":%s}',
        '{"model":"glm-5v-turbo","choices":[],"choices":%s}',
        '{"model":"glm-5v-turbo","usage":{"total_tokens":NaN},"choices":%s}',
        '{"model":"glm-5v-turbo","usage":{"total_tokens":Infinity},"choices":%s}',
    ),
)
async def test_glm_audit_rejects_ambiguous_or_non_json_completion_envelopes(
    envelope: str,
) -> None:
    calls = 0
    choices = json.dumps([{"message": {"content": '{"accepted":true,"issues":[]}'}}])

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, content=(envelope % choices).encode())

    adapter, client = _auditor(handler, model="glm-5v-turbo")
    async with client:
        with pytest.raises(InvalidProviderOutputError) as raised:
            await adapter.audit(_audit_request())
    assert calls == 1
    assert raised.value.issue_codes == ("invalid_schema",)


@pytest.mark.asyncio
async def test_glm_audit_rejects_duplicate_nested_completion_content() -> None:
    rejected = json.dumps('{"accepted":false,"issues":[]}')
    accepted = json.dumps('{"accepted":true,"issues":[]}')
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            200,
            content=(
                '{"model":"glm-5v-turbo","choices":[{"message":{'
                f'"content":{rejected},"content":{accepted}'
                "}}]}"
            ).encode(),
        )

    adapter, client = _auditor(handler, model="glm-5v-turbo")
    async with client:
        with pytest.raises(InvalidProviderOutputError):
            await adapter.audit(_audit_request())
    assert calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("failure", "expected_code"),
    (
        ("timeout", "provider_timeout"),
        ("unavailable", "provider_unavailable"),
        ("missing_model", "invalid_provider_output"),
        ("oversized", "invalid_provider_output"),
    ),
)
async def test_glm_audit_projects_safe_failure_without_retry(
    failure: str, expected_code: str
) -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if failure == "timeout":
            raise httpx.ReadTimeout("private sentinel")
        if failure == "unavailable":
            return httpx.Response(503, text="private sentinel")
        if failure == "oversized":
            return httpx.Response(200, text="private sentinel" * 2_000)
        completion = _completion('{"accepted":true,"issues":[]}')
        del completion["model"]
        return httpx.Response(200, json=completion)

    adapter, client = _auditor(handler, model="glm-5v-turbo")
    async with client:
        with pytest.raises(ProviderError) as raised:
            await adapter.audit(_audit_request())
    assert calls == 1
    assert raised.value.code == expected_code
    assert "private sentinel" not in str(raised.value)


@pytest.mark.asyncio
async def test_vision_audit_preserves_warnings_for_the_callers_policy() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_completion(
                '{"accepted":true,"issues":[{"code":"ip_identity_borderline",'
                '"severity":"warning"}]}'
            ),
        )

    adapter, client = _auditor(handler)
    async with client:
        result = await adapter.audit(_audit_request())
    assert result.accepted is True
    assert result.issue_codes == ("ip_identity_borderline",)
    assert result.issues[0].severity == "warning"


@pytest.mark.asyncio
async def test_vision_audit_request_limit_prevents_provider_call() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    adapter, client = _auditor(handler, max_request_bytes=100)
    async with client:
        with pytest.raises(ProviderInputLimitError):
            await adapter.audit(_audit_request())
    assert calls == 0


@pytest.mark.asyncio
async def test_vision_audit_returns_only_bounded_rejection_issues() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_completion(
                json.dumps(
                    {
                        "accepted": False,
                        "issues": [{"code": "identity_mismatch", "severity": "error"}],
                    }
                )
            ),
        )

    adapter, client = _auditor(handler)
    async with client:
        result = await adapter.audit(_audit_request())

    assert result.accepted is False
    assert result.issue_codes == ("identity_mismatch",)
    assert result.issues[0].severity == "error"


@pytest.mark.asyncio
async def test_vision_adapter_rejects_oversized_request_before_provider_call() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(500)

    adapter, client = _recognizer(handler, max_request_bytes=100)
    async with client:
        with pytest.raises(ProviderInputLimitError):
            await adapter.recognize(
                ImageTextRecognitionRequest(
                    image_bytes=IMAGE_BYTES,
                    request_fingerprint="ocr-fingerprint",
                    expected_text=("科学",),
                )
            )

    assert calls == 0


@pytest.mark.asyncio
async def test_vision_adapter_validates_provider_model_and_optional_fingerprint() -> None:
    responses = iter(
        (
            httpx.Response(200, json=_completion('{"recognized_lines":["科学"]}', model="other")),
            httpx.Response(
                200,
                json={
                    **_completion('{"recognized_lines":["科学"]}'),
                    "request_fingerprint": "wrong-fingerprint",
                },
            ),
        )
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return next(responses)

    adapter, client = _recognizer(handler)
    request = ImageTextRecognitionRequest(
        image_bytes=IMAGE_BYTES,
        request_fingerprint="ocr-fingerprint",
        expected_text=("科学",),
    )
    async with client:
        with pytest.raises(ProviderIdentityMismatchError):
            await adapter.recognize(request)
        with pytest.raises(ProviderIdentityMismatchError):
            await adapter.recognize(request)


def test_vision_adapter_requires_an_https_origin() -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200)))
    with pytest.raises(ValueError, match="HTTPS"):
        OpenAICompatibleImageTextRecognizer(
            client=client,
            base_url="http://vision.provider.test/v1",
            api_key=SecretStr("test-only-key"),
            model="vision-model",
            connect_timeout_seconds=1,
            read_timeout_seconds=2,
            total_timeout_seconds=3,
            concurrency=1,
            max_attempts=1,
            max_request_bytes=1_024,
            max_response_bytes=1_024,
        )
