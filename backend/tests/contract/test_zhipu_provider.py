import gzip
import json
import traceback
import zlib
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import httpx
import pytest
from app.application.ports.governance import (
    EmbeddingRequest,
    FactualAnalysisPassage,
    FactualAnalysisRequest,
)
from app.core.errors import (
    InvalidProviderOutputError,
    ProviderAuthenticationError,
    ProviderDimensionMismatchError,
    ProviderInputLimitError,
    ProviderRateLimitError,
    ProviderTimeoutError,
    ProviderUnavailableError,
)
from app.domain.governance_enums import AnalysisValidationCode, EmbeddingPurpose
from app.infrastructure.ai.zhipu import ZhipuEmbeddingModel, ZhipuFactualAnalysisModel
from pydantic import SecretStr

PASSAGE_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
PUBLISHED_AT = datetime(2026, 7, 29, 8, 30, tzinfo=UTC)


class _AsyncBytesStream(httpx.AsyncByteStream):
    def __init__(self, content: bytes) -> None:
        self._content = content

    async def __aiter__(self):
        yield self._content


def _request() -> FactualAnalysisRequest:
    return FactualAnalysisRequest(
        candidate_id=UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
        title="人工智能课程指南发布",
        published_at=PUBLISHED_AT,
        language="zh-CN",
        passages=(
            FactualAnalysisPassage(
                passage_id=PASSAGE_ID,
                ordinal=0,
                passage_hash="a" * 64,
                text="教育部门发布人工智能课程指南, 要求学校完善教师培训。",
            ),
        ),
        prompt_version="factual-analysis-v1",
        schema_version="factual-analysis-schema-v1",
        taxonomy_version="ai-factual-taxonomy-v1",
        max_output_tokens=1024,
    )


def _embedding_request(*, text: str = "人工智能课程指南 教师培训") -> EmbeddingRequest:
    return EmbeddingRequest(
        artifact_id=UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc"),
        purpose=EmbeddingPurpose.NEAR_DUPLICATE,
        input_hash="c" * 64,
        text=text,
    )


def _analysis_payload() -> dict[str, object]:
    return {
        "summary": {"text": "教育部门发布人工智能课程指南。", "passage_ids": [PASSAGE_ID]},
        "key_facts": [
            {
                "text": "指南要求学校完善人工智能教师培训。",
                "passage_ids": [PASSAGE_ID],
                "event_time_start": None,
                "event_time_end": None,
                "event_time_precision": "unknown",
            }
        ],
        "entities": [
            {
                "entity_type": "organization",
                "source_mention": "教育部门",
                "canonical_name": "教育部门",
                "passage_id": PASSAGE_ID,
            }
        ],
        "categories": [{"category": "ai_education_policy", "confidence": 0.96}],
        "primary_category": "ai_education_policy",
        "keywords": ["人工智能", "课程指南", "教师培训"],
        "event_time_start": None,
        "event_time_end": None,
        "event_time_precision": "unknown",
        "publication_time": PUBLISHED_AT.isoformat(),
    }


def _response_payload(
    content: str,
    *,
    request_id: str = "provider-request-1",
    completion_tokens: int = 60,
) -> dict[str, object]:
    return {
        "id": request_id,
        "choices": [
            {
                "message": {
                    "content": content,
                    "reasoning_content": "hidden chain of thought that must be discarded",
                }
            }
        ],
        "usage": {
            "prompt_tokens": 120,
            "completion_tokens": completion_tokens,
            "completion_tokens_details": {"reasoning_tokens": 20},
        },
    }


async def _no_sleep(_: float) -> None:
    return None


def _adapter(
    handler: httpx.AsyncBaseTransport,
    *,
    max_attempts: int = 2,
    max_input_characters: int = 40_000,
    sleep: Callable[[float], Awaitable[None]] = _no_sleep,
) -> tuple[ZhipuFactualAnalysisModel, httpx.AsyncClient]:
    client = httpx.AsyncClient(transport=handler)
    return (
        ZhipuFactualAnalysisModel(
            client=client,
            base_url="https://open.bigmodel.invalid/api/paas/v4",
            api_key=SecretStr("local-contract-secret"),
            model="glm-5.2",
            connect_timeout_seconds=1,
            read_timeout_seconds=2,
            total_timeout_seconds=3,
            concurrency=2,
            max_attempts=max_attempts,
            max_input_characters=max_input_characters,
            max_output_tokens=4096,
            sleep=sleep,
        ),
        client,
    )


def _embedding_adapter(
    handler: httpx.AsyncBaseTransport,
    *,
    max_attempts: int = 2,
    max_input_characters: int = 40_000,
) -> tuple[ZhipuEmbeddingModel, httpx.AsyncClient]:
    client = httpx.AsyncClient(transport=handler)
    return (
        ZhipuEmbeddingModel(
            client=client,
            base_url="https://open.bigmodel.invalid/api/paas/v4",
            api_key=SecretStr("local-contract-secret"),
            model="embedding-3",
            dimensions=2048,
            connect_timeout_seconds=1,
            read_timeout_seconds=2,
            total_timeout_seconds=3,
            concurrency=2,
            max_attempts=max_attempts,
            max_input_characters=max_input_characters,
            sleep=_no_sleep,
        ),
        client,
    )


async def test_valid_json_object_response_crosses_boundary_as_typed_safe_metadata() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["Authorization"]
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json=_response_payload(json.dumps(_analysis_payload(), default=str)),
        )

    adapter, client = _adapter(httpx.MockTransport(handler))
    async with client:
        result = await adapter.analyze(_request())

    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert captured["url"] == "https://open.bigmodel.invalid/api/paas/v4/chat/completions"
    assert captured["authorization"] == "Bearer local-contract-secret"
    assert payload["model"] == "glm-5.2"
    assert payload["thinking"] == {"type": "disabled"}
    assert payload["response_format"] == {"type": "json_object"}
    assert payload["temperature"] == 0
    assert result.analysis.summary.passage_ids == (_request().passages[0].passage_id,)
    assert result.provider == "zhipu"
    assert result.provider_request_id == "provider-request-1"
    assert result.reasoning_tokens == 20
    assert "reasoning_content" not in repr(result)
    assert "local-contract-secret" not in repr(result)


async def test_gzip_provider_responses_are_bounded_and_decoded_explicitly() -> None:
    captured_encodings: list[str] = []
    responses = iter(
        (
            _response_payload(json.dumps(_analysis_payload(), default=str)),
            {
                "id": "embedding-request-gzip",
                "model": "embedding-3",
                "data": [{"index": 0, "embedding": [0.5] * 2048}],
                "usage": {"prompt_tokens": 12, "total_tokens": 12},
            },
        )
    )

    def handler(request: httpx.Request) -> httpx.Response:
        captured_encodings.append(request.headers["Accept-Encoding"])
        raw = json.dumps(next(responses), default=str).encode()
        return httpx.Response(
            200,
            stream=_AsyncBytesStream(gzip.compress(raw, mtime=0)),
            headers={
                "content-encoding": "gzip",
                "content-type": "application/json",
            },
        )

    transport = httpx.MockTransport(handler)
    analysis_adapter, analysis_client = _adapter(transport, max_attempts=1)
    embedding_adapter, embedding_client = _embedding_adapter(transport, max_attempts=1)
    async with analysis_client, embedding_client:
        analysis = await analysis_adapter.analyze(_request())
        embedding = await embedding_adapter.embed(_embedding_request())

    assert captured_encodings == ["gzip", "gzip"]
    assert analysis.analysis.primary_category == "ai_education_policy"
    assert embedding.dimensions == 2048
    assert embedding.provider_request_id == "embedding-request-gzip"


async def test_preloaded_mocktransport_gzip_response_remains_compatible() -> None:
    raw = json.dumps(
        _response_payload(json.dumps(_analysis_payload(), default=str)),
        default=str,
    ).encode()

    def handler(_: httpx.Request) -> httpx.Response:
        response = httpx.Response(
            200,
            content=gzip.compress(raw, mtime=0),
            headers={
                "content-encoding": "gzip",
                "content-type": "application/json",
            },
        )
        assert response.is_stream_consumed is True
        return response

    adapter, client = _adapter(httpx.MockTransport(handler), max_attempts=1)
    async with client:
        result = await adapter.analyze(_request())

    assert result.analysis.primary_category == "ai_education_policy"


async def test_gzip_encoded_and_decoded_response_sizes_are_bounded_separately() -> None:
    responses = iter(
        (
            b"x" * 16_385,
            gzip.compress(b"x" * 16_385, mtime=0),
        )
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            stream=_AsyncBytesStream(next(responses)),
            headers={
                "content-encoding": "gzip",
                "content-type": "application/json",
            },
        )

    adapter, client = _adapter(httpx.MockTransport(handler), max_attempts=1)
    async with client:
        with pytest.raises(InvalidProviderOutputError) as encoded:
            await adapter.analyze(_request())
        with pytest.raises(InvalidProviderOutputError) as decoded:
            await adapter.analyze(_request())

    expected = (AnalysisValidationCode.OUTPUT_LIMIT_EXCEEDED.value,)
    assert encoded.value.issue_codes == expected
    assert decoded.value.issue_codes == expected


async def test_unsupported_encoding_is_non_retryable_for_preloaded_responses() -> None:
    attempts = 0
    raw = json.dumps(
        _response_payload(json.dumps(_analysis_payload(), default=str)),
        default=str,
    ).encode()

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            200,
            content=zlib.compress(raw),
            headers={
                "content-encoding": "deflate",
                "content-type": "application/json",
            },
        )

    adapter, client = _adapter(httpx.MockTransport(handler), max_attempts=2)
    async with client:
        with pytest.raises(InvalidProviderOutputError) as raised:
            await adapter.analyze(_request())

    assert attempts == 1
    assert raised.value.issue_codes == (AnalysisValidationCode.INVALID_SCHEMA.value,)


async def test_malformed_content_length_is_non_retryable_typed_output_failure() -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            200,
            stream=_AsyncBytesStream(b"{}"),
            headers={
                "content-length": "invalid",
                "content-type": "application/json",
            },
        )

    adapter, client = _adapter(httpx.MockTransport(handler), max_attempts=2)
    async with client:
        with pytest.raises(InvalidProviderOutputError) as raised:
            await adapter.analyze(_request())

    assert attempts == 1
    assert raised.value.issue_codes == (AnalysisValidationCode.INVALID_SCHEMA.value,)


async def test_malformed_gzip_is_a_non_retryable_typed_output_failure() -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(
            200,
            stream=_AsyncBytesStream(b"not-a-gzip-stream"),
            headers={
                "content-encoding": "gzip",
                "content-type": "application/json",
            },
        )

    adapter, client = _adapter(httpx.MockTransport(handler), max_attempts=2)
    async with client:
        with pytest.raises(InvalidProviderOutputError) as raised:
            await adapter.analyze(_request())

    assert attempts == 1
    assert raised.value.issue_codes == (AnalysisValidationCode.INVALID_SCHEMA.value,)


async def test_malformed_json_and_unsupported_taxonomy_map_to_safe_issue_codes() -> None:
    responses = iter(
        (
            _response_payload("{not-json"),
            _response_payload(
                json.dumps(
                    {
                        **_analysis_payload(),
                        "categories": [{"category": "marketing", "confidence": 1}],
                    },
                    default=str,
                )
            ),
        )
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=next(responses))

    adapter, client = _adapter(httpx.MockTransport(handler), max_attempts=1)
    async with client:
        with pytest.raises(InvalidProviderOutputError) as malformed:
            await adapter.analyze(_request())
        with pytest.raises(InvalidProviderOutputError) as unsupported:
            await adapter.analyze(_request())

    assert malformed.value.issue_codes == (AnalysisValidationCode.MALFORMED_JSON.value,)
    assert unsupported.value.issue_codes == (AnalysisValidationCode.UNSUPPORTED_TAXONOMY.value,)


async def test_missing_evidence_maps_to_a_typed_schema_issue() -> None:
    payload = _analysis_payload()
    payload["summary"] = {"text": "教育部门发布人工智能课程指南。", "passage_ids": []}

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_response_payload(json.dumps(payload, default=str)),
        )

    adapter, client = _adapter(httpx.MockTransport(handler), max_attempts=1)
    async with client:
        with pytest.raises(InvalidProviderOutputError) as raised:
            await adapter.analyze(_request())

    assert raised.value.issue_codes == (AnalysisValidationCode.MISSING_EVIDENCE.value,)


async def test_input_limit_rejects_before_any_provider_request() -> None:
    requests = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(500)

    adapter, client = _adapter(
        httpx.MockTransport(handler),
        max_attempts=1,
        max_input_characters=10,
    )
    oversized = replace(
        _request(),
        passages=(replace(_request().passages[0], text="人工智能" * 20),),
    )
    async with client:
        with pytest.raises(ProviderInputLimitError):
            await adapter.analyze(oversized)

    assert requests == 0


async def test_input_limit_covers_complete_prompt_schema_and_metadata() -> None:
    requests = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(500)

    request = _request()
    raw_source_characters = len(request.title) + sum(
        len(passage.text) for passage in request.passages
    )
    adapter, client = _adapter(
        httpx.MockTransport(handler),
        max_attempts=1,
        max_input_characters=raw_source_characters + 10,
    )
    async with client:
        with pytest.raises(ProviderInputLimitError):
            await adapter.analyze(request)

    assert requests == 0


async def test_adapter_rejects_unsafe_direct_construction_outside_settings() -> None:
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(500)))

    def construct(
        *,
        base_url: str,
        api_key: SecretStr,
        total_timeout_seconds: float = 3,
    ) -> ZhipuFactualAnalysisModel:
        return ZhipuFactualAnalysisModel(
            client=client,
            base_url=base_url,
            api_key=api_key,
            model="glm-5.2",
            connect_timeout_seconds=1,
            read_timeout_seconds=2,
            total_timeout_seconds=total_timeout_seconds,
            concurrency=1,
            max_attempts=1,
            max_input_characters=40_000,
            max_output_tokens=4096,
        )

    async with client:
        with pytest.raises(ValueError, match="HTTPS"):
            construct(
                base_url="http://open.bigmodel.invalid/api/paas/v4",
                api_key=SecretStr("local-contract-secret"),
            )
        with pytest.raises(ValueError, match="API key"):
            construct(
                base_url="https://open.bigmodel.invalid/api/paas/v4",
                api_key=SecretStr(" "),
            )
        with pytest.raises(ValueError, match="total must cover read"):
            construct(
                base_url="https://open.bigmodel.invalid/api/paas/v4",
                api_key=SecretStr("local-contract-secret"),
                total_timeout_seconds=1,
            )


async def test_rate_limit_retries_once_then_succeeds_without_body_logging() -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429, json={"error": {"message": "secret provider body"}})
        return httpx.Response(
            200,
            json=_response_payload(json.dumps(_analysis_payload(), default=str)),
        )

    adapter, client = _adapter(httpx.MockTransport(handler))
    async with client:
        result = await adapter.analyze(_request())

    assert attempts == 2
    assert result.analysis.key_facts
    assert "secret provider body" not in repr(result)


async def test_rate_limit_exhaustion_is_typed_and_retryable() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"ignored": "raw"})

    adapter, client = _adapter(httpx.MockTransport(handler))
    async with client:
        with pytest.raises(ProviderRateLimitError) as raised:
            await adapter.analyze(_request())

    assert raised.value.retryable is True
    assert "raw" not in str(raised.value)


async def test_timeout_and_5xx_exhaustion_map_to_distinct_typed_failures() -> None:
    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("do not expose", request=request)

    timeout_adapter, timeout_client = _adapter(httpx.MockTransport(timeout_handler))
    async with timeout_client:
        with pytest.raises(ProviderTimeoutError):
            await timeout_adapter.analyze(_request())

    def unavailable_handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="do not expose provider response")

    unavailable_adapter, unavailable_client = _adapter(httpx.MockTransport(unavailable_handler))
    async with unavailable_client:
        with pytest.raises(ProviderUnavailableError) as raised:
            await unavailable_adapter.analyze(_request())

    assert "provider response" not in str(raised.value)


async def test_authentication_failure_is_not_retried_or_leaked() -> None:
    attempts = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        return httpx.Response(401, json={"message": "local-contract-secret"})

    adapter, client = _adapter(httpx.MockTransport(handler))
    async with client:
        with pytest.raises(ProviderAuthenticationError) as raised:
            await adapter.analyze(_request())

    assert attempts == 1
    assert "local-contract-secret" not in str(raised.value)


async def test_excessive_provider_output_and_unsafe_request_id_are_safely_projected() -> None:
    responses = iter(
        (
            _response_payload(
                json.dumps(_analysis_payload(), default=str),
                completion_tokens=1025,
            ),
            _response_payload(
                json.dumps(_analysis_payload(), default=str),
                request_id="reasoning_content: hidden provider material",
            ),
        )
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=next(responses))

    adapter, client = _adapter(httpx.MockTransport(handler), max_attempts=1)
    async with client:
        with pytest.raises(InvalidProviderOutputError) as excessive:
            await adapter.analyze(_request())
        result = await adapter.analyze(_request())

    assert excessive.value.issue_codes == (AnalysisValidationCode.OUTPUT_LIMIT_EXCEEDED.value,)
    assert result.provider_request_id is None


async def test_invalid_raw_provider_material_is_suppressed_from_exception_traceback() -> None:
    raw_material = "local-contract-secret reasoning_content " + _request().passages[0].text

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=_response_payload(raw_material),
        )

    adapter, client = _adapter(httpx.MockTransport(handler), max_attempts=1)
    async with client:
        with pytest.raises(InvalidProviderOutputError) as raised:
            await adapter.analyze(_request())

    rendered = "".join(traceback.format_exception(raised.value))
    assert "local-contract-secret" not in rendered
    assert "reasoning_content" not in rendered
    assert _request().passages[0].text not in rendered


async def test_embedding_3_returns_fixed_dimension_vector_and_safe_metadata() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["authorization"] = request.headers["Authorization"]
        captured["payload"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={
                "id": "embedding-request-1",
                "model": "embedding-3",
                "data": [{"index": 0, "embedding": [0.5] * 2048}],
                "usage": {"prompt_tokens": 12, "total_tokens": 12},
            },
        )

    adapter, client = _embedding_adapter(httpx.MockTransport(handler))
    async with client:
        result = await adapter.embed(_embedding_request())

    payload = captured["payload"]
    assert isinstance(payload, dict)
    assert captured["url"] == "https://open.bigmodel.invalid/api/paas/v4/embeddings"
    assert captured["authorization"] == "Bearer local-contract-secret"
    assert payload == {
        "model": "embedding-3",
        "input": "人工智能课程指南 教师培训",
        "dimensions": 2048,
    }
    assert result.dimensions == 2048
    assert len(result.vector) == 2048
    assert result.provider_request_id == "embedding-request-1"
    assert result.prompt_tokens == 12
    assert "local-contract-secret" not in repr(result)


async def test_embedding_rejects_dimension_mismatch_and_malformed_payload() -> None:
    responses = iter(
        (
            {"data": [{"index": 0, "embedding": [0.5] * 1024}]},
            {"data": [{"index": 0, "embedding": "secret raw vector material"}]},
        )
    )

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=next(responses))

    adapter, client = _embedding_adapter(httpx.MockTransport(handler), max_attempts=1)
    async with client:
        with pytest.raises(ProviderDimensionMismatchError):
            await adapter.embed(_embedding_request())
        with pytest.raises(InvalidProviderOutputError) as malformed:
            await adapter.embed(_embedding_request())

    rendered = "".join(traceback.format_exception(malformed.value))
    assert "secret raw vector material" not in rendered


async def test_embedding_input_limit_rejects_before_provider_request() -> None:
    requests = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(500)

    adapter, client = _embedding_adapter(
        httpx.MockTransport(handler),
        max_attempts=1,
        max_input_characters=5,
    )
    async with client:
        with pytest.raises(ProviderInputLimitError):
            await adapter.embed(_embedding_request(text="人工智能技术"))

    assert requests == 0


async def test_embedding_retries_rate_limit_then_maps_timeout_and_5xx() -> None:
    rate_limit_attempts = 0

    def rate_limit_handler(_: httpx.Request) -> httpx.Response:
        nonlocal rate_limit_attempts
        rate_limit_attempts += 1
        return httpx.Response(429, json={"message": "secret provider body"})

    rate_adapter, rate_client = _embedding_adapter(httpx.MockTransport(rate_limit_handler))
    async with rate_client:
        with pytest.raises(ProviderRateLimitError) as rate_error:
            await rate_adapter.embed(_embedding_request())
    assert rate_limit_attempts == 2
    assert "secret provider body" not in str(rate_error.value)

    def timeout_handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("secret timeout response", request=request)

    timeout_adapter, timeout_client = _embedding_adapter(
        httpx.MockTransport(timeout_handler), max_attempts=1
    )
    async with timeout_client:
        with pytest.raises(ProviderTimeoutError) as timeout_error:
            await timeout_adapter.embed(_embedding_request())
    assert "secret timeout response" not in str(timeout_error.value)

    unavailable_adapter, unavailable_client = _embedding_adapter(
        httpx.MockTransport(lambda _: httpx.Response(503, text="secret unavailable response")),
        max_attempts=1,
    )
    async with unavailable_client:
        with pytest.raises(ProviderUnavailableError) as unavailable_error:
            await unavailable_adapter.embed(_embedding_request())
    assert "secret unavailable response" not in str(unavailable_error.value)


async def test_embedding_rejects_non_finite_vectors_without_raw_response_leakage() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        raw_response = json.dumps(
            {
                "id": "unsafe\nrequest-id",
                "data": [{"index": 0, "embedding": [float("nan")] * 2048}],
            }
        ).encode()
        return httpx.Response(
            200,
            content=raw_response,
            headers={"content-type": "application/json"},
        )

    adapter, client = _embedding_adapter(httpx.MockTransport(handler), max_attempts=1)
    async with client:
        with pytest.raises(InvalidProviderOutputError) as raised:
            await adapter.embed(_embedding_request())

    rendered = "".join(traceback.format_exception(raised.value))
    assert "unsafe" not in rendered
    assert "nan" not in rendered.casefold()


@pytest.mark.parametrize("vector", ([0.0] * 2048, [-0.0] * 2048))
async def test_embedding_rejects_zero_vectors(vector: list[float]) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": vector}]})

    adapter, client = _embedding_adapter(httpx.MockTransport(handler), max_attempts=1)
    async with client:
        with pytest.raises(InvalidProviderOutputError):
            await adapter.embed(_embedding_request())


async def test_embedding_rejects_oversized_response_before_json_parsing() -> None:
    unsafe_tail = "provider-secret-material" * 20_000

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=("{" + unsafe_tail).encode(),
            headers={"content-type": "application/json"},
        )

    adapter, client = _embedding_adapter(httpx.MockTransport(handler), max_attempts=1)
    async with client:
        with pytest.raises(InvalidProviderOutputError) as raised:
            await adapter.embed(_embedding_request())

    assert raised.value.issue_codes == (AnalysisValidationCode.OUTPUT_LIMIT_EXCEEDED.value,)
    assert "provider-secret-material" not in str(raised.value)
