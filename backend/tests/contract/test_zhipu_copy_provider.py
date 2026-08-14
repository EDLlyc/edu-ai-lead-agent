from __future__ import annotations

# ruff: noqa: RUF001
import json
from datetime import UTC, date, datetime
from uuid import uuid4

import httpx
import pytest
from app.application.ports.copy_generation import DraftAuditRequest, DraftGenerationRequest
from app.application.services.copy_generation import build_copy_version_bundle
from app.core.config import Settings
from app.core.errors import (
    InvalidProviderOutputError,
    ProviderAuthenticationError,
    provider_validation_issues_metadata,
)
from app.domain.copy_generation import (
    ActiveBrandContext,
    EligibleEvidence,
    LegacyDailyTopicOrigin,
    LockedTopicContext,
)
from app.infrastructure.ai.copy_generation import (
    ProviderJsonEnvelopeError,
    create_zhipu_copy_models,
    extract_provider_json_object,
)
from app.schemas.copy_generation import DraftClaim, MaterialDraft
from pydantic import SecretStr, ValidationError


def _request() -> DraftGenerationRequest:
    evidence_id = uuid4()
    topic = LockedTopicContext(
        origin=LegacyDailyTopicOrigin(
            daily_topic_selection_id=uuid4(),
            topic_selection_run_id=uuid4(),
        ),
        business_date=date(2026, 7, 30),
        timezone="Asia/Shanghai",
        scoring_profile="preview",
        decision_kind="selected",
        selected_event_id=uuid4(),
        selected_event_version_id=uuid4(),
        no_topic_code=None,
        title="机器人研究进展",
        summary="权威来源发布研究进展。",
        evidence=(
            EligibleEvidence(
                evidence_id=evidence_id,
                candidate_id=uuid4(),
                passage_id=uuid4(),
                occurrence_id=uuid4(),
                snapshot_id=uuid4(),
                source_name="权威来源",
                source_url="https://example.test/source",
                source_tier="A",
                published_at=datetime(2026, 7, 30, tzinfo=UTC),
                exact_quote="研究团队发布了机器人学习的新进展。",
            ),
        ),
    )
    brand = ActiveBrandContext(
        chunk_id=uuid4(),
        document_id=uuid4(),
        version_id=uuid4(),
        document_title="品牌语气",
        document_kind="tone",
        text="表达应准确、克制、温暖，不制造教育焦虑。",
    )
    return DraftGenerationRequest(
        run_id=uuid4(),
        topic=topic,
        brand_context=(brand,),
        version_bundle=build_copy_version_bundle(
            Settings(
                ai_provider_mode="zhipu",
                ai_platform_base_url="https://provider.test/v4",
            )
        ),
        draft_version=1,
        max_output_tokens=1024,
    )


def _valid_draft(request: DraftGenerationRequest) -> MaterialDraft:
    fact = request.topic.evidence[0].exact_quote
    brand_text = "赛先生倡导准确、克制、温暖的科学教育表达。"
    return MaterialDraft(
        copywriting=(
            f"今天和家长分享一条人工智能与机器人动态：{fact}{brand_text}"
            "我们可以陪孩子从可靠信息出发，观察技术如何发展，并通过提问建立自己的理解。"
            "\n\n#赛先生科学 #机器人启蒙 #科学思维"
        ),
        parent_takeaway="用可靠信息和开放问题陪伴孩子理解人工智能。",
        interaction="你会和孩子讨论哪一个机器人问题？",
        source_note="信息来源：权威来源。",
        image_prompt="蓝色科技教育插画，家长和孩子观察机器人，不出现真人正脸。",
        claims=(
            DraftClaim(
                id="fact-1",
                text=fact,
                kind="external_fact",
                evidence_ids=(request.topic.evidence[0].evidence_id,),
            ),
            DraftClaim(
                id="brand-1",
                text=brand_text,
                kind="brand_statement",
                brand_chunk_ids=(request.brand_context[0].chunk_id,),
            ),
        ),
    )


def _completion(content: str, request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        request=request,
        json={
            "id": "safe-provider-id",
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 20},
        },
    )


def _user_prompt(request_body: str) -> str:
    payload = json.loads(request_body)
    return str(payload["messages"][1]["content"])


def _invalid_draft_with_secret_bindings(
    request: DraftGenerationRequest, *, count: int, secret_marker: str
) -> str:
    payload = _valid_draft(request).model_dump(mode="json")
    payload["claims"] = [
        {
            "id": f"fact-{index}",
            "text": "研究团队发布了机器人学习的新进展。",
            "kind": "external_fact",
            "evidence_ids": [f"{secret_marker}-{index}"],
            "brand_chunk_ids": [],
        }
        for index in range(count)
    ]
    return json.dumps(payload, ensure_ascii=False)


@pytest.mark.parametrize(
    ("content", "expected"),
    [
        ('{"value":"ok"}', '{"value":"ok"}'),
        ('```json\n{"value":"ok"}\n```', '{"value":"ok"}'),
        ('结果如下：\n{"value":"ok"}\n请审核。', '{"value":"ok"}'),
        (
            '说明：\n{"value":"花括号 { }、引号 \\" 与反斜杠 \\\\"}\n结束。',
            '{"value":"花括号 { }、引号 \\" 与反斜杠 \\\\"}',
        ),
    ],
)
def test_provider_json_extractor_accepts_one_bounded_object(content: str, expected: str) -> None:
    assert extract_provider_json_object(content) == expected


@pytest.mark.parametrize(
    ("content", "validation_type"),
    [
        ('[{"value":"array-root"}]', "json_array_root"),
        ('{"a":1} {"b":2}', "json_multiple_structures"),
        ('{"a":1} trailing [2]', "json_multiple_structures"),
        ('prefix {"a":"unterminated"', "json_unclosed"),
        ('prefix {not-json} {"a":1}', "json_multiple_structures"),
        ("```json\n{}\n```\n```json\n{}\n```", "json_invalid"),
        ('{"a":1} true', "json_multiple_structures"),
        (f'{"x" * 513} {{"a":1}}', "json_affix_too_long"),
        ('{"a":"PRIVATE-RAW-\\x"}', "json_invalid"),
        ('{"a":NaN}', "json_invalid"),
    ],
)
def test_provider_json_extractor_rejects_ambiguous_or_invalid_envelopes(
    content: str, validation_type: str
) -> None:
    with pytest.raises(ProviderJsonEnvelopeError) as raised:
        extract_provider_json_object(content)

    assert raised.value.validation_type == validation_type
    assert "PRIVATE-RAW" not in str(raised.value)


def test_provider_json_extractor_rejects_over_limit_without_retaining_content() -> None:
    content = 'PRIVATE-OVER-LIMIT-{"value":"ok"}'
    with pytest.raises(ProviderJsonEnvelopeError) as raised:
        extract_provider_json_object(content, max_characters=10)

    assert raised.value.validation_type == "json_too_long"
    assert "PRIVATE-OVER-LIMIT" not in str(raised.value)


def test_provider_json_envelope_does_not_relax_material_draft_schema() -> None:
    request = _request()
    payload = _valid_draft(request).model_dump(mode="json")
    payload["unexpected"] = "PRIVATE-EXTRA-VALUE"
    normalized = extract_provider_json_object(
        f"```json\n{json.dumps(payload, ensure_ascii=False)}\n```"
    )

    with pytest.raises(ValidationError) as raised:
        MaterialDraft.model_validate_json(normalized)

    errors = raised.value.errors(include_url=False, include_context=False, include_input=False)
    assert errors == [
        {
            "type": "extra_forbidden",
            "loc": ("unexpected",),
            "msg": "Extra inputs are not permitted",
        }
    ]
    assert "PRIVATE-EXTRA-VALUE" not in json.dumps(errors, ensure_ascii=False)


@pytest.mark.asyncio
async def test_zhipu_copy_provider_performs_one_schema_correction_and_strips_audit_authority() -> (
    None
):
    request = _request()
    draft = _valid_draft(request)
    responses = [
        "not-json",
        draft.model_dump_json(),
        '{"accepted":true,"issues":[],"evidence_ids":["not-allowed"]}',
        '{"accepted":true,"issues":[]}',
    ]
    request_bodies: list[str] = []

    def handler(http_request: httpx.Request) -> httpx.Response:
        request_bodies.append(http_request.content.decode())
        return _completion(responses.pop(0), http_request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        generator, auditor = create_zhipu_copy_models(
            client=client,
            base_url="https://provider.test/v4",
            api_key=SecretStr("test-only-key"),
            model="glm-test",
            connect_timeout_seconds=1,
            read_timeout_seconds=2,
            total_timeout_seconds=3,
            concurrency=1,
            max_attempts=1,
            max_input_characters=20_000,
            max_output_tokens=2048,
            max_validation_corrections=1,
        )
        generated = await generator.generate(request)
        audited = await auditor.audit(
            DraftAuditRequest(
                run_id=request.run_id,
                draft_version_id=uuid4(),
                topic=request.topic,
                brand_context=request.brand_context,
                draft=generated.draft,
                version_bundle=request.version_bundle,
                max_output_tokens=512,
            )
        )

    assert generated.validation_corrections == 1
    assert audited.validation_corrections == 1
    assert audited.verdict.accepted is True
    assert responses == []
    generator_prompt = _user_prompt(request_bodies[0])
    generator_correction = _user_prompt(request_bodies[1])
    audit_prompt = _user_prompt(request_bodies[2])
    audit_correction = _user_prompt(request_bodies[3])
    request_payloads = [json.loads(body) for body in request_bodies]

    assert all(payload["thinking"] == {"type": "disabled"} for payload in request_payloads)

    assert "<OUTPUT_SCHEMA>" in generator_prompt
    assert '"copywriting"' in generator_prompt
    assert '"evidence_ids"' in generator_prompt
    assert '"type":"json_invalid"' in generator_correction
    assert "not-json" not in generator_correction

    assert "<OUTPUT_SCHEMA>" in audit_prompt
    assert '"accepted"' in audit_prompt
    assert request.topic.evidence[0].exact_quote in audit_prompt
    assert request.brand_context[0].text in audit_prompt
    assert '"type":"extra_forbidden"' in audit_correction
    assert '"loc":["evidence_ids"]' in audit_correction
    assert "not-allowed" not in audit_correction


@pytest.mark.asyncio
async def test_zhipu_copy_provider_projects_authentication_failure_without_body() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, request=request, content=b"secret provider body")

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        generator, _ = create_zhipu_copy_models(
            client=client,
            base_url="https://provider.test/v4",
            api_key=SecretStr("test-only-key"),
            model="glm-test",
            connect_timeout_seconds=1,
            read_timeout_seconds=2,
            total_timeout_seconds=3,
            concurrency=1,
            max_attempts=1,
            max_input_characters=20_000,
            max_output_tokens=2048,
            max_validation_corrections=1,
        )
        with pytest.raises(ProviderAuthenticationError) as raised:
            await generator.generate(_request())

    assert "secret provider body" not in str(raised.value)


@pytest.mark.asyncio
async def test_zhipu_copy_provider_retains_only_bounded_final_validation_locations() -> None:
    request = _request()
    first_secret = "PRIVATE-FIRST-RAW-VALUE"
    final_secret = "PRIVATE-FINAL-RAW-VALUE"
    responses = [
        _invalid_draft_with_secret_bindings(request, count=2, secret_marker=first_secret),
        _invalid_draft_with_secret_bindings(request, count=16, secret_marker=final_secret),
    ]
    request_bodies: list[str] = []

    def handler(http_request: httpx.Request) -> httpx.Response:
        request_bodies.append(http_request.content.decode())
        return _completion(responses.pop(0), http_request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        generator, _ = create_zhipu_copy_models(
            client=client,
            base_url="https://provider.test/v4",
            api_key=SecretStr("test-only-key"),
            model="glm-test",
            connect_timeout_seconds=1,
            read_timeout_seconds=2,
            total_timeout_seconds=3,
            concurrency=1,
            max_attempts=1,
            max_input_characters=20_000,
            max_output_tokens=2048,
            max_validation_corrections=1,
        )
        with pytest.raises(InvalidProviderOutputError) as raised:
            await generator.generate(request)

    correction_prompt = _user_prompt(request_bodies[1])
    safe_metadata = provider_validation_issues_metadata(raised.value.validation_issues)
    assert raised.value.issue_codes == ("invalid_draft_schema",)
    assert len(safe_metadata) == 12
    assert safe_metadata[0] == {
        "loc": ["claims", 0, "evidence_ids", 0],
        "type": "uuid_parsing",
    }
    assert safe_metadata[-1]["loc"] == ["claims", 11, "evidence_ids", 0]
    assert '"loc":["claims",0,"evidence_ids",0]' in correction_prompt
    assert '"type":"uuid_parsing"' in correction_prompt
    assert first_secret not in correction_prompt
    assert final_secret not in correction_prompt
    assert final_secret not in str(raised.value)
    assert final_secret not in json.dumps(safe_metadata, ensure_ascii=False)


@pytest.mark.asyncio
async def test_zhipu_copy_provider_accepts_fenced_and_explained_json_objects() -> None:
    request = _request()
    draft = _valid_draft(request)
    responses = [
        f"```json\n{draft.model_dump_json()}\n```",
        '审校结果如下：\n{"accepted":true,"issues":[]}\n请进入内部审核。',
    ]

    def handler(http_request: httpx.Request) -> httpx.Response:
        return _completion(responses.pop(0), http_request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        generator, auditor = create_zhipu_copy_models(
            client=client,
            base_url="https://provider.test/v4",
            api_key=SecretStr("test-only-key"),
            model="glm-test",
            connect_timeout_seconds=1,
            read_timeout_seconds=2,
            total_timeout_seconds=3,
            concurrency=1,
            max_attempts=1,
            max_input_characters=20_000,
            max_output_tokens=2048,
            max_validation_corrections=1,
        )
        generated = await generator.generate(request)
        audited = await auditor.audit(
            DraftAuditRequest(
                run_id=request.run_id,
                draft_version_id=uuid4(),
                topic=request.topic,
                brand_context=request.brand_context,
                draft=generated.draft,
                version_bundle=request.version_bundle,
                max_output_tokens=512,
            )
        )

    assert generated.draft == draft
    assert generated.validation_corrections == 0
    assert audited.verdict.accepted is True
    assert audited.validation_corrections == 0
    assert responses == []


@pytest.mark.asyncio
async def test_zhipu_copy_provider_projects_ambiguous_envelope_without_raw_content() -> None:
    request = _request()
    raw_marker = "PRIVATE-MULTIPLE-OBJECTS"
    invalid = f'说明：{{"marker":"{raw_marker}"}} {{"second":true}}'
    responses = [invalid, invalid]
    request_bodies: list[str] = []

    def handler(http_request: httpx.Request) -> httpx.Response:
        request_bodies.append(http_request.content.decode())
        return _completion(responses.pop(0), http_request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        generator, _ = create_zhipu_copy_models(
            client=client,
            base_url="https://provider.test/v4",
            api_key=SecretStr("test-only-key"),
            model="glm-test",
            connect_timeout_seconds=1,
            read_timeout_seconds=2,
            total_timeout_seconds=3,
            concurrency=1,
            max_attempts=1,
            max_input_characters=20_000,
            max_output_tokens=2048,
            max_validation_corrections=1,
        )
        with pytest.raises(InvalidProviderOutputError) as raised:
            await generator.generate(request)

    correction_prompt = _user_prompt(request_bodies[1])
    safe_metadata = provider_validation_issues_metadata(raised.value.validation_issues)
    assert safe_metadata == [
        {
            "loc": ["root"],
            "type": "json_multiple_structures",
        }
    ]
    assert '"type":"json_multiple_structures"' in correction_prompt
    assert raw_marker not in correction_prompt
    assert raw_marker not in str(raised.value)
    assert raw_marker not in json.dumps(safe_metadata, ensure_ascii=False)
