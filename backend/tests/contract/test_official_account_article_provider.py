from __future__ import annotations

# ruff: noqa: RUF001 -- Chinese provider instructions are byte-compatible contract values.
import json
from dataclasses import replace
from uuid import uuid4

import httpx
import pytest
from app.application.ports.official_account_local import (
    OfficialAccountAuditRequest,
    OfficialAccountGenerationRequest,
    OfficialAccountRepairRequest,
    OfficialAccountVersionIdentity,
)
from app.application.services.official_account_local import (
    article_version_bundle,
    build_audit_prompt,
    build_generation_prompt,
    repair_request_fingerprint,
    run_request_fingerprint,
)
from app.core.errors import (
    InvalidProviderOutputError,
    ProviderInputLimitError,
    provider_validation_issues_metadata,
)
from app.domain.official_account_local import (
    OFFICIAL_ACCOUNT_ARTICLE_SCHEMA_V5_VERSION,
    OFFICIAL_ACCOUNT_ARTICLE_SCHEMA_VERSION,
    OFFICIAL_ACCOUNT_AUDITOR_PROMPT_V1_VERSION,
    OFFICIAL_ACCOUNT_AUDITOR_PROMPT_VERSION,
    OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V4_VERSION,
    OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V5_VERSION,
    OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V7_VERSION,
    OFFICIAL_ACCOUNT_GENERATOR_PROMPT_VERSION,
    OFFICIAL_ACCOUNT_RULE_VERSION,
    GeneratedArticleDraft,
    OfficialAccountAuditVerdict,
    build_article_package,
    canonical_json,
)
from app.domain.official_account_reviewer import (
    REPAIR_POLICY_VERSION,
    RepairDirective,
    RepairOperation,
    ReviewIssueCode,
    ReviewReference,
    ReviewReferenceKind,
)
from app.infrastructure.ai.official_account_local import (
    create_zhipu_official_account_models,
)
from app.infrastructure.official_account_local import (
    DeterministicFakeOfficialAccountArticleGenerator,
    fixture_source_snapshot,
)
from pydantic import SecretStr


def _identity() -> OfficialAccountVersionIdentity:
    return OfficialAccountVersionIdentity(
        provider="zhipu",
        model="glm-4-plus",
        generator_prompt_version="official-account-generator-v1",
        article_schema_version="official-account-article-schema-v1",
        auditor_prompt_version="official-account-auditor-v1",
        audit_schema_version="official-account-audit-schema-v1",
        rule_version="official-account-rules-v1",
        renderer_version="wechat-html-renderer-v1",
        style_version="wechat-inline-style-v1",
        template_version="wechat-fragment-template-v1",
        local_adapter_version="official-account-local-adapter-v1",
        default_author="赛先生",
        min_characters=1_200,
        target_min_characters=1_800,
        target_max_characters=2_600,
        max_characters=4_000,
    )


def _generation_request() -> OfficialAccountGenerationRequest:
    source = fixture_source_snapshot()
    identity = _identity()
    return OfficialAccountGenerationRequest(
        run_id=uuid4(),
        source=source,
        identity=identity,
        request_fingerprint=run_request_fingerprint(
            source_fingerprint=source.source_fingerprint,
            generation_mode="live",
            identity=identity,
        ),
        max_output_tokens=8_192,
    )


def _v8_generation_request() -> OfficialAccountGenerationRequest:
    request = _generation_request()
    identity = replace(
        request.identity,
        generator_prompt_version=OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V5_VERSION,
        article_schema_version=OFFICIAL_ACCOUNT_ARTICLE_SCHEMA_VERSION,
        auditor_prompt_version=OFFICIAL_ACCOUNT_AUDITOR_PROMPT_VERSION,
        rule_version=OFFICIAL_ACCOUNT_RULE_VERSION,
    )
    return replace(
        request,
        identity=identity,
        request_fingerprint=run_request_fingerprint(
            source_fingerprint=request.source.source_fingerprint,
            generation_mode="live",
            identity=identity,
        ),
    )


def _v9_generation_request() -> OfficialAccountGenerationRequest:
    request = _v8_generation_request()
    identity = replace(
        request.identity,
        generator_prompt_version=OFFICIAL_ACCOUNT_GENERATOR_PROMPT_VERSION,
        article_schema_version=OFFICIAL_ACCOUNT_ARTICLE_SCHEMA_V5_VERSION,
    )
    return replace(
        request,
        identity=identity,
        request_fingerprint=run_request_fingerprint(
            source_fingerprint=request.source.source_fingerprint,
            generation_mode="live",
            identity=identity,
        ),
    )


def _v10_generation_request() -> OfficialAccountGenerationRequest:
    request = _v9_generation_request()
    identity = replace(
        request.identity,
        generator_prompt_version=OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V7_VERSION,
    )
    return replace(
        request,
        identity=identity,
        request_fingerprint=run_request_fingerprint(
            source_fingerprint=request.source.source_fingerprint,
            generation_mode="live",
            identity=identity,
        ),
    )


def _v7_generation_request() -> OfficialAccountGenerationRequest:
    request = _generation_request()
    identity = replace(
        request.identity,
        generator_prompt_version=OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V4_VERSION,
        article_schema_version=OFFICIAL_ACCOUNT_ARTICLE_SCHEMA_VERSION,
        auditor_prompt_version=OFFICIAL_ACCOUNT_AUDITOR_PROMPT_V1_VERSION,
        rule_version=OFFICIAL_ACCOUNT_RULE_VERSION,
    )
    return replace(
        request,
        identity=identity,
        request_fingerprint=run_request_fingerprint(
            source_fingerprint=request.source.source_fingerprint,
            generation_mode="live",
            identity=identity,
        ),
    )


async def _valid_draft_json(request: OfficialAccountGenerationRequest) -> str:
    fake_request = OfficialAccountGenerationRequest(
        run_id=request.run_id,
        source=request.source,
        identity=request.identity,
        request_fingerprint=request.request_fingerprint,
        max_output_tokens=request.max_output_tokens,
    )
    result = await DeterministicFakeOfficialAccountArticleGenerator().generate(fake_request)
    return result.draft.model_dump_json()


async def _repair_request() -> OfficialAccountRepairRequest:
    generation_request = _generation_request()
    generated = await DeterministicFakeOfficialAccountArticleGenerator().generate(
        generation_request
    )
    article = build_article_package(
        draft=generated.draft,
        source=generation_request.source,
        versions=article_version_bundle(generation_request.identity),
        default_author=generation_request.identity.default_author,
    )
    return OfficialAccountRepairRequest(
        run_id=generation_request.run_id,
        source=generation_request.source,
        article=article,
        directives=(
            RepairDirective(
                directive_id="repair:01:brand-tone",
                issue_code=ReviewIssueCode.BRAND_TONE_MISMATCH,
                target=ReviewReference(
                    kind=ReviewReferenceKind.SECTION,
                    ref="section:00",
                ),
                operation=RepairOperation.ALIGN_BRAND_TONE,
                repair_policy_version=REPAIR_POLICY_VERSION,
            ),
        ),
        identity=generation_request.identity,
        request_fingerprint=generation_request.request_fingerprint,
        max_output_tokens=generation_request.max_output_tokens,
    )


def _completion(content: str, request: httpx.Request) -> httpx.Response:
    return httpx.Response(
        200,
        request=request,
        json={
            "id": "safe-provider-request-1",
            "choices": [{"message": {"content": content}}],
            "usage": {
                "prompt_tokens": 31,
                "completion_tokens": 520,
                "completion_tokens_details": {"reasoning_tokens": 0},
            },
        },
    )


def _models(
    client: httpx.AsyncClient,
    *,
    corrections: int = 1,
    max_input_characters: int = 100_000,
):
    return create_zhipu_official_account_models(
        client=client,
        base_url="https://provider.test/v4",
        api_key=SecretStr("server-only-key"),
        model="glm-4-plus",
        connect_timeout_seconds=2,
        read_timeout_seconds=5,
        total_timeout_seconds=10,
        concurrency=1,
        max_attempts=1,
        max_input_characters=max_input_characters,
        max_output_tokens=8_192,
        max_validation_corrections=corrections,
    )


@pytest.mark.asyncio
async def test_live_generator_uses_bounded_json_contract_and_safe_metadata() -> None:
    generation_request = _generation_request()
    valid = await _valid_draft_json(generation_request)

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert request.url == "https://provider.test/v4/chat/completions"
        assert request.headers["Authorization"] == "Bearer server-only-key"
        assert payload["temperature"] == 0
        assert payload["thinking"] == {"type": "disabled"}
        assert payload["response_format"] == {"type": "json_object"}
        assert "禁止HTML" in payload["messages"][1]["content"]
        return _completion(valid, request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        follow_redirects=False,
    ) as client:
        generator, _auditor = _models(client)
        result = await generator.generate(generation_request)

    assert result.provider == "zhipu"
    assert result.model == "glm-4-plus"
    assert result.provider_request_id == "safe-provider-request-1"
    assert result.prompt_tokens == 31
    assert result.completion_tokens == 520
    assert result.validation_corrections == 0
    assert "server-only-key" not in repr(result)


@pytest.mark.asyncio
async def test_live_repairer_uses_closed_directives_and_strict_schema_contract() -> None:
    repair_request = await _repair_request()
    valid = await _valid_draft_json(_generation_request())
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        payload = json.loads(request.content)
        system = payload["messages"][0]["content"]
        prompt = payload["messages"][1]["content"]
        assert "GeneratedArticleDraft" in system
        assert "<REPAIR_DIRECTIVES>" in prompt
        assert "align_brand_tone" in prompt
        assert "<ORIGINAL_ARTICLE>" in prompt
        assert "只能执行" in prompt
        assert payload["temperature"] == 0
        assert payload["thinking"] == {"type": "disabled"}
        assert payload["response_format"] == {"type": "json_object"}
        return _completion(valid, request)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        follow_redirects=False,
    ) as client:
        repairer, _auditor = _models(client)
        result = await repairer.repair(repair_request)

    assert calls == 1
    assert result.provider == "zhipu"
    assert result.model == "glm-4-plus"
    assert result.request_fingerprint == repair_request_fingerprint(repair_request)
    assert result.provider_request_id == "safe-provider-request-1"
    assert result.validation_corrections == 0


@pytest.mark.asyncio
async def test_live_v8_generator_puts_canonical_schema_in_initial_system_message() -> None:
    generation_request = _v8_generation_request()
    valid = await _valid_draft_json(generation_request)
    expected_schema = canonical_json(GeneratedArticleDraft.model_json_schema(mode="validation"))

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        system = str(payload["messages"][0]["content"])
        assert system.startswith("只返回严格JSON对象，不输出Markdown、HTML、URL或解释。\n")
        assert f"<OUTPUT_SCHEMA>{expected_schema}</OUTPUT_SCHEMA>" in system
        assert payload["messages"][1]["content"] == build_generation_prompt(generation_request)
        return _completion(valid, request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        generator, _auditor = _models(client)
        result = await generator.generate(generation_request)

    assert result.validation_corrections == 0


@pytest.mark.asyncio
async def test_live_v9_generator_keeps_schema_first_with_v6_length_buffer_prompt() -> None:
    generation_request = _v9_generation_request()
    valid = await _valid_draft_json(generation_request)
    expected_schema = canonical_json(GeneratedArticleDraft.model_json_schema(mode="validation"))

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        system = str(payload["messages"][0]["content"])
        user = str(payload["messages"][1]["content"])
        assert f"<OUTPUT_SCHEMA>{expected_schema}</OUTPUT_SCHEMA>" in system
        assert user == build_generation_prompt(generation_request)
        assert "输出JSON前必须按系统确定性口径逐项自检正文字符数" in user
        assert "主动留出长度缓冲" in user
        return _completion(valid, request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        generator, _auditor = _models(client)
        result = await generator.generate(generation_request)

    assert result.validation_corrections == 0


@pytest.mark.asyncio
async def test_live_v10_generator_keeps_schema_first_and_requires_five_to_seven_sections() -> None:
    generation_request = _v10_generation_request()
    valid = await _valid_draft_json(generation_request)

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        system = str(payload["messages"][0]["content"])
        user = str(payload["messages"][1]["content"])
        assert "<OUTPUT_SCHEMA>" in system
        assert user == build_generation_prompt(generation_request)
        assert "主动留出长度缓冲" in user
        assert "文章必须包含5--7个section" in user
        return _completion(valid, request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        generator, _auditor = _models(client)
        result = await generator.generate(generation_request)

    assert 5 <= len(result.draft.sections) <= 7
    assert result.validation_corrections == 0


@pytest.mark.asyncio
async def test_live_v8_generator_counts_initial_schema_toward_input_limit() -> None:
    generation_request = _v8_generation_request()
    base_prompt = build_generation_prompt(generation_request)
    schema = canonical_json(GeneratedArticleDraft.model_json_schema(mode="validation"))
    initial_system = (
        "只返回严格JSON对象，不输出Markdown、HTML、URL或解释。\n"
        "输出必须通过GeneratedArticleDraft的严格校验，只输出一个JSON对象。"
        f"<OUTPUT_SCHEMA>{schema}</OUTPUT_SCHEMA>"
    )
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _completion("{}", request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        generator, _auditor = _models(
            client,
            max_input_characters=len(base_prompt) + len(initial_system) - 1,
        )
        with pytest.raises(ProviderInputLimitError):
            await generator.generate(generation_request)

    assert calls == 0


@pytest.mark.asyncio
async def test_live_v7_payload_keeps_the_frozen_initial_system_message() -> None:
    generation_request = _v7_generation_request()
    valid = await _valid_draft_json(generation_request)

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["messages"] == [
            {
                "role": "system",
                "content": "只返回严格JSON对象，不输出Markdown、HTML、URL或解释。",
            },
            {"role": "user", "content": build_generation_prompt(generation_request)},
        ]
        return _completion(valid, request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        generator, _auditor = _models(client)
        result = await generator.generate(generation_request)

    assert result.validation_corrections == 0


@pytest.mark.asyncio
async def test_live_generator_allows_one_safe_schema_correction() -> None:
    generation_request = _generation_request()
    valid = await _valid_draft_json(generation_request)
    observed_wrong_shape = json.dumps(
        {
            "headline": "PRIVATE-RAW-SENTINEL",
            "summary": "legacy summary",
            "author": generation_request.identity.default_author,
            "lead": "legacy lead",
            "sections": [
                {
                    "heading": f"legacy section {index}",
                    "blocks": [{"text": "legacy block", "claim_refs": []}],
                }
                for index in range(3)
            ],
            "conclusion": "legacy conclusion",
            "claims": [],
            "legacy_body": "legacy extra field",
        },
        ensure_ascii=False,
        separators=(",", ":"),
    )
    expected_schema = canonical_json(GeneratedArticleDraft.model_json_schema(mode="validation"))
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        prompt = str(json.loads(request.content)["messages"][1]["content"])
        if calls == 1:
            assert prompt == build_generation_prompt(generation_request)
            assert "<VALIDATION_SCHEMA>" not in prompt
            return _completion(observed_wrong_shape, request)
        assert "VALIDATION_ERRORS" in prompt
        assert f"<VALIDATION_SCHEMA>{expected_schema}</VALIDATION_SCHEMA>" in prompt
        assert "<VALIDATION_INVARIANTS>" not in prompt
        assert '"required":["title","digest","author","lead","sections"' in prompt
        assert '"propertyName":"kind"' in prompt
        assert "PRIVATE-RAW-SENTINEL" not in prompt
        corrected = valid if "<VALIDATION_SCHEMA>" in prompt else observed_wrong_shape
        return _completion(corrected, request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        generator, _auditor = _models(client)
        result = await generator.generate(generation_request)

    assert calls == 2
    assert result.validation_corrections == 1


@pytest.mark.asyncio
async def test_live_generator_applies_input_limit_to_schema_correction_prompt() -> None:
    generation_request = _generation_request()
    base_prompt = build_generation_prompt(generation_request)
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return _completion('{"title":"PRIVATE-RAW-SENTINEL"}', request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        generator, _auditor = _models(
            client,
            max_input_characters=len(base_prompt)
            + len("只返回严格JSON对象，不输出Markdown、HTML、URL或解释。"),
        )
        with pytest.raises(ProviderInputLimitError):
            await generator.generate(generation_request)

    assert calls == 1


@pytest.mark.asyncio
async def test_live_generator_stops_after_exhausting_schema_correction() -> None:
    generation_request = _generation_request()
    sentinels = ("PRIVATE-FIRST-RAW-FIELD", "PRIVATE-FINAL-RAW-FIELD")
    responses = [
        json.dumps({sentinel: "private value"}, separators=(",", ":")) for sentinel in sentinels
    ]
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        response = _completion(responses[calls], request)
        calls += 1
        return response

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        generator, _auditor = _models(client, corrections=1)
        with pytest.raises(InvalidProviderOutputError) as raised:
            await generator.generate(generation_request)

    assert calls == 2
    assert raised.value.issue_codes == ("invalid_article_schema",)
    safe_metadata = json.dumps(
        provider_validation_issues_metadata(raised.value.validation_issues),
        ensure_ascii=False,
    )
    assert all(sentinel not in str(raised.value) for sentinel in sentinels)
    assert all(sentinel not in repr(raised.value) for sentinel in sentinels)
    assert all(sentinel not in safe_metadata for sentinel in sentinels)


@pytest.mark.asyncio
async def test_live_generator_rejects_malformed_output_without_raw_content() -> None:
    generation_request = _generation_request()
    sentinel = "PRIVATE-RAW-MALFORMED"

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: _completion(f"not-json-{sentinel}", request))
    ) as client:
        generator, _auditor = _models(client, corrections=0)
        with pytest.raises(InvalidProviderOutputError) as raised:
            await generator.generate(generation_request)

    assert sentinel not in str(raised.value)
    assert sentinel not in repr(raised.value)


@pytest.mark.asyncio
async def test_live_auditor_returns_only_allowlisted_verdict() -> None:
    generation_request = _generation_request()
    fake_result = await DeterministicFakeOfficialAccountArticleGenerator().generate(
        generation_request
    )
    article = build_article_package(
        draft=fake_result.draft,
        source=generation_request.source,
        versions=article_version_bundle(generation_request.identity),
        default_author=generation_request.identity.default_author,
    )
    audit_request = OfficialAccountAuditRequest(
        run_id=generation_request.run_id,
        source=generation_request.source,
        article=article,
        identity=generation_request.identity,
        request_fingerprint=generation_request.request_fingerprint,
        max_output_tokens=1_024,
    )

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: _completion(
                '{"accepted":true,"issue_codes":[],"claim_ids":[]}', request
            )
        )
    ) as client:
        _generator, auditor = _models(client)
        result = await auditor.audit(audit_request)

    assert result.verdict.accepted is True
    assert result.verdict.issue_codes == ()
    assert result.provider == "zhipu"


@pytest.mark.asyncio
async def test_live_v8_auditor_puts_schema_and_conditional_invariants_in_system_message() -> None:
    generation_request = _generation_request()
    fake_result = await DeterministicFakeOfficialAccountArticleGenerator().generate(
        generation_request
    )
    article = build_article_package(
        draft=fake_result.draft,
        source=generation_request.source,
        versions=article_version_bundle(generation_request.identity),
        default_author=generation_request.identity.default_author,
    )
    v8_identity = _v8_generation_request().identity
    audit_request = OfficialAccountAuditRequest(
        run_id=generation_request.run_id,
        source=generation_request.source,
        article=article,
        identity=v8_identity,
        request_fingerprint=run_request_fingerprint(
            source_fingerprint=generation_request.source.source_fingerprint,
            generation_mode="live",
            identity=v8_identity,
        ),
        max_output_tokens=1_024,
    )
    expected_schema = canonical_json(
        OfficialAccountAuditVerdict.model_json_schema(mode="validation")
    )

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        system = str(payload["messages"][0]["content"])
        assert f"<OUTPUT_SCHEMA>{expected_schema}</OUTPUT_SCHEMA>" in system
        assert "<VALIDATION_INVARIANTS>" in system
        assert '"accepted":{"const":true}' in system
        assert payload["messages"][1]["content"] == build_audit_prompt(audit_request)
        return _completion('{"accepted":true,"issue_codes":[],"claim_ids":[]}', request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        _generator, auditor = _models(client)
        result = await auditor.audit(audit_request)

    assert result.verdict.accepted is True


@pytest.mark.asyncio
async def test_live_auditor_correction_includes_cross_field_invariants() -> None:
    generation_request = _generation_request()
    fake_result = await DeterministicFakeOfficialAccountArticleGenerator().generate(
        generation_request
    )
    article = build_article_package(
        draft=fake_result.draft,
        source=generation_request.source,
        versions=article_version_bundle(generation_request.identity),
        default_author=generation_request.identity.default_author,
    )
    audit_request = OfficialAccountAuditRequest(
        run_id=generation_request.run_id,
        source=generation_request.source,
        article=article,
        identity=generation_request.identity,
        request_fingerprint=generation_request.request_fingerprint,
        max_output_tokens=1_024,
    )
    base_prompt = build_audit_prompt(audit_request)
    raw_sentinel = "PRIVATE-RAW-AUDIT"
    invalid = json.dumps(
        {
            "accepted": True,
            "issue_codes": ["fact_not_entailed"],
            "claim_ids": [raw_sentinel],
        },
        separators=(",", ":"),
    )
    valid = '{"accepted":true,"issue_codes":[],"claim_ids":[]}'
    expected_invariants = canonical_json(
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
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        prompt = str(json.loads(request.content)["messages"][1]["content"])
        if calls == 1:
            assert prompt == base_prompt
            assert "<VALIDATION_INVARIANTS>" not in prompt
            return _completion(invalid, request)
        invariant_tag = f"<VALIDATION_INVARIANTS>{expected_invariants}</VALIDATION_INVARIANTS>"
        assert prompt.startswith(base_prompt)
        assert invariant_tag in prompt
        assert '"loc":["root"],"type":"value_error"' in prompt
        assert raw_sentinel not in prompt
        return _completion(valid if invariant_tag in prompt else invalid, request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        _generator, auditor = _models(client, corrections=1)
        result = await auditor.audit(audit_request)

    assert calls == 2
    assert result.verdict.accepted is True
    assert result.validation_corrections == 1
