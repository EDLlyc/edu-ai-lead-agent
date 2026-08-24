from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from uuid import uuid4

import pytest
from app.application.ports.official_account_local import (
    OfficialAccountGenerationRequest,
    OfficialAccountVersionIdentity,
)
from app.application.services.official_account_local import (
    article_version_bundle,
    build_generation_prompt,
    run_request_fingerprint,
)
from app.domain.official_account_local import (
    OFFICIAL_ACCOUNT_ARTICLE_SCHEMA_V1_VERSION,
    OFFICIAL_ACCOUNT_ARTICLE_SCHEMA_V2_VERSION,
    OFFICIAL_ACCOUNT_ARTICLE_SCHEMA_V3_VERSION,
    OFFICIAL_ACCOUNT_AUDIT_SCHEMA_VERSION,
    OFFICIAL_ACCOUNT_AUDITOR_PROMPT_V1_VERSION,
    OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V1_VERSION,
    OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V2_VERSION,
    OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V3_VERSION,
    OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V4_VERSION,
    OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V2_VERSION,
    OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V3_VERSION,
    OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V4_VERSION,
    OFFICIAL_ACCOUNT_MEDIA_PLAN_V1_VERSION,
    OFFICIAL_ACCOUNT_MEDIA_PLAN_V2_VERSION,
    OFFICIAL_ACCOUNT_RENDERER_V4_VERSION,
    OFFICIAL_ACCOUNT_RENDERER_V5_VERSION,
    OFFICIAL_ACCOUNT_RENDERER_V6_VERSION,
    OFFICIAL_ACCOUNT_RULE_V1_VERSION,
    OFFICIAL_ACCOUNT_RULE_V2_VERSION,
    OFFICIAL_ACCOUNT_RULE_V3_VERSION,
    OFFICIAL_ACCOUNT_RULE_VERSION,
    OFFICIAL_ACCOUNT_STYLE_V4_VERSION,
    OFFICIAL_ACCOUNT_STYLE_V5_VERSION,
    OFFICIAL_ACCOUNT_STYLE_V6_VERSION,
    OFFICIAL_ACCOUNT_TEMPLATE_V4_VERSION,
    OFFICIAL_ACCOUNT_TEMPLATE_V5_VERSION,
    OFFICIAL_ACCOUNT_TEMPLATE_V6_VERSION,
    ArticleParagraphBlock,
    ArticleSection,
    GeneratedArticleClaim,
    SemanticMediaCandidate,
    article_body_character_count,
    article_package_fingerprint,
    assign_semantic_body_media,
    build_article_package,
    plan_body_media_slots,
    validate_article_package,
)
from app.infrastructure.official_account_local import (
    FIXTURE_BODY_ALT_TEXTS,
    FIXTURE_BODY_CAPTIONS,
    FIXTURE_BODY_IMAGE_LABELS,
    FIXTURE_BODY_PUBLICATION_SHA256S,
    FIXTURE_BODY_SEMANTIC_TAGS,
    DeterministicFakeOfficialAccountArticleGenerator,
    fixture_source_snapshot,
)
from pydantic import ValidationError


def identity() -> OfficialAccountVersionIdentity:
    return OfficialAccountVersionIdentity(
        provider="fake",
        model="official-account-fixture-v1",
        generator_prompt_version=OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V4_VERSION,
        article_schema_version=OFFICIAL_ACCOUNT_ARTICLE_SCHEMA_V3_VERSION,
        media_plan_version=OFFICIAL_ACCOUNT_MEDIA_PLAN_V2_VERSION,
        auditor_prompt_version=OFFICIAL_ACCOUNT_AUDITOR_PROMPT_V1_VERSION,
        audit_schema_version=OFFICIAL_ACCOUNT_AUDIT_SCHEMA_VERSION,
        rule_version=OFFICIAL_ACCOUNT_RULE_VERSION,
        renderer_version=OFFICIAL_ACCOUNT_RENDERER_V6_VERSION,
        style_version=OFFICIAL_ACCOUNT_STYLE_V6_VERSION,
        template_version=OFFICIAL_ACCOUNT_TEMPLATE_V6_VERSION,
        local_adapter_version=OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V4_VERSION,
        default_author="赛先生",
        min_characters=1_200,
        target_min_characters=1_800,
        target_max_characters=2_600,
        max_characters=4_000,
    )


def test_absent_generated_visual_identity_preserves_the_existing_run_fingerprint() -> None:
    source = fixture_source_snapshot(multi_image=True, semantic_media=True)

    assert (
        run_request_fingerprint(
            source_fingerprint=source.source_fingerprint,
            generation_mode="fixture",
            identity=identity(),
        )
        == "fb2234c65f8cc448f5e4b8de5800a9ad339be424c2ed73c128696bf5efb9702b"
    )


async def fixture_article():
    source = fixture_source_snapshot(multi_image=True, semantic_media=True)
    configured_identity = identity()
    request_fingerprint = run_request_fingerprint(
        source_fingerprint=source.source_fingerprint,
        generation_mode="fixture",
        identity=configured_identity,
    )
    result = await DeterministicFakeOfficialAccountArticleGenerator().generate(
        OfficialAccountGenerationRequest(
            run_id=uuid4(),
            source=source,
            identity=configured_identity,
            request_fingerprint=request_fingerprint,
            max_output_tokens=8_192,
        )
    )
    assignments = assign_semantic_body_media(
        sections=result.draft.sections,
        candidates=tuple(
            SemanticMediaCandidate(
                candidate_id=f"fixture-publication-{checksum}",
                sha256=checksum,
                semantic_label=FIXTURE_BODY_IMAGE_LABELS[ordinal],
                semantic_tags=FIXTURE_BODY_SEMANTIC_TAGS[ordinal],
                alt_text=FIXTURE_BODY_ALT_TEXTS[ordinal],
                caption_text=FIXTURE_BODY_CAPTIONS[ordinal],
                publication_priority=ordinal,
            )
            for ordinal, checksum in enumerate(FIXTURE_BODY_PUBLICATION_SHA256S)
        ),
    )
    article = build_article_package(
        draft=result.draft,
        source=source,
        versions=article_version_bundle(configured_identity),
        default_author=configured_identity.default_author,
        body_media_candidate_count=3,
        semantic_media_assignments=assignments,
    )
    return source, configured_identity, article


async def historical_fixture_article():
    source = fixture_source_snapshot()
    configured_identity = replace(
        identity(),
        article_schema_version=OFFICIAL_ACCOUNT_ARTICLE_SCHEMA_V1_VERSION,
        media_plan_version=None,
        renderer_version=OFFICIAL_ACCOUNT_RENDERER_V4_VERSION,
        style_version=OFFICIAL_ACCOUNT_STYLE_V4_VERSION,
        template_version=OFFICIAL_ACCOUNT_TEMPLATE_V4_VERSION,
        local_adapter_version=OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V2_VERSION,
        generator_prompt_version=OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V3_VERSION,
        rule_version=OFFICIAL_ACCOUNT_RULE_V3_VERSION,
    )
    result = await DeterministicFakeOfficialAccountArticleGenerator().generate(
        _generation_request(configured_identity)
    )
    article = build_article_package(
        draft=result.draft,
        source=source,
        versions=article_version_bundle(configured_identity),
        default_author=configured_identity.default_author,
    )
    return source, configured_identity, article


async def historical_multi_fixture_article():
    source = fixture_source_snapshot(multi_image=True)
    configured_identity = replace(
        identity(),
        generator_prompt_version=OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V3_VERSION,
        article_schema_version=OFFICIAL_ACCOUNT_ARTICLE_SCHEMA_V2_VERSION,
        media_plan_version=OFFICIAL_ACCOUNT_MEDIA_PLAN_V1_VERSION,
        rule_version=OFFICIAL_ACCOUNT_RULE_V3_VERSION,
        renderer_version=OFFICIAL_ACCOUNT_RENDERER_V5_VERSION,
        style_version=OFFICIAL_ACCOUNT_STYLE_V5_VERSION,
        template_version=OFFICIAL_ACCOUNT_TEMPLATE_V5_VERSION,
        local_adapter_version=OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V3_VERSION,
    )
    result = await DeterministicFakeOfficialAccountArticleGenerator().generate(
        OfficialAccountGenerationRequest(
            run_id=uuid4(),
            source=source,
            identity=configured_identity,
            request_fingerprint=run_request_fingerprint(
                source_fingerprint=source.source_fingerprint,
                generation_mode="fixture",
                identity=configured_identity,
            ),
            max_output_tokens=8_192,
        )
    )
    article = build_article_package(
        draft=result.draft,
        source=source,
        versions=article_version_bundle(configured_identity),
        default_author=configured_identity.default_author,
        body_media_candidate_count=3,
    )
    return source, configured_identity, article


def _generation_request(
    configured_identity: OfficialAccountVersionIdentity,
) -> OfficialAccountGenerationRequest:
    source = fixture_source_snapshot()
    return OfficialAccountGenerationRequest(
        run_id=uuid4(),
        source=source,
        identity=configured_identity,
        request_fingerprint=run_request_fingerprint(
            source_fingerprint=source.source_fingerprint,
            generation_mode="fixture",
            identity=configured_identity,
        ),
        max_output_tokens=8_192,
    )


@pytest.mark.asyncio
async def test_fixture_article_is_stable_strict_and_within_target_length() -> None:
    source, configured_identity, article = await fixture_article()
    repeated_source, _, repeated = await fixture_article()

    assert source.source_fingerprint == repeated_source.source_fingerprint
    assert article.content_fingerprint == repeated.content_fingerprint
    assert article.content_fingerprint == article_package_fingerprint(article)
    assert 1_800 <= article_body_character_count(article) <= 2_600
    assert (
        validate_article_package(
            article,
            source=source,
            default_author=configured_identity.default_author,
            min_characters=configured_identity.min_characters,
            target_min_characters=configured_identity.target_min_characters,
            target_max_characters=configured_identity.target_max_characters,
            max_characters=configured_identity.max_characters,
        )
        == ()
    )
    assert [slot.role for slot in article.media_slots] == ["body", "body", "body", "cover"]
    assert [slot.ordinal for slot in article.media_slots] == [0, 1, 2, 0]
    assert (
        sum(block.kind == "image" for section in article.sections for block in section.blocks) == 3
    )


def test_generation_prompt_v3_remains_byte_compatible() -> None:
    v3 = replace(
        identity(),
        generator_prompt_version=OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V3_VERSION,
        rule_version=OFFICIAL_ACCOUNT_RULE_V3_VERSION,
    )
    prompt = build_generation_prompt(_generation_request(v3))

    assert "首屏先说明主题为什么与家长有关" in prompt
    assert "全文唯一的核心判断" in prompt
    assert "背景语境、核心判断、证据或能力、家庭行动、适用边界与下一步" in prompt
    assert "优先写孩子采取的具体行动和能够看见、记录或比较的证据" in prompt
    assert "具体姓名、学校、对话、课程、比赛或案例只有在受治理证据明确支持时" in prompt
    assert "严禁编造或泛化政策、奖项、升学、录取、效果、规模、排名" in prompt
    assert "绝对AI能力声明" in prompt
    assert "制造焦虑的转化话术、二维码指令、发布指令" in prompt
    assert "不超过三条平静、可执行的家长建议" in prompt
    assert "约60--130个中文字符为软目标" in prompt
    encoded = prompt.encode("utf-8")
    assert len(encoded) == 2_801
    assert sha256(encoded).hexdigest() == (
        "9a64b05ad3134a0329909a53d150bcff18907c2aa02fe7a8f7481c9320da6a43"
    )


def test_generation_prompt_v4_requires_natural_reader_copy() -> None:
    prompt = build_generation_prompt(_generation_request(identity()))

    assert "不能出现脱敏示例、fixture、schema、provider、media plan、测试" in prompt
    assert "来源和治理边界由系统在正文之外展示" in prompt
    assert "首屏先说明主题为什么与家长有关" in prompt
    encoded = prompt.encode("utf-8")
    assert len(encoded) == 3_027
    assert sha256(encoded).hexdigest() == (
        "2a07ca0b9d04369d37954ad0f8b40d9f8969f1f693750367b970b695dd6068dd"
    )


def test_generation_prompt_v1_remains_byte_compatible() -> None:
    legacy = replace(
        identity(),
        generator_prompt_version=OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V1_VERSION,
        rule_version=OFFICIAL_ACCOUNT_RULE_V1_VERSION,
    )
    prompt = build_generation_prompt(_generation_request(legacy)).encode("utf-8")

    assert len(prompt) == 1_562
    assert sha256(prompt).hexdigest() == (
        "e798652018c9624b6df9bc75a27824ee3bf397c0bd13f4a82bf7a4ede9451e86"
    )


def test_generation_prompt_v2_remains_byte_compatible() -> None:
    v2 = replace(
        identity(),
        generator_prompt_version=OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V2_VERSION,
        rule_version=OFFICIAL_ACCOUNT_RULE_V2_VERSION,
    )
    prompt = build_generation_prompt(_generation_request(v2)).encode("utf-8")

    assert len(prompt) == 2_340
    assert sha256(prompt).hexdigest() == (
        "250f2579858a76803055721f4b70b8452be2571b1e2e9ba38777c98f8d985759"
    )


def test_generation_prompt_rejects_mismatched_prompt_and_rule_versions() -> None:
    mismatched_identities = (
        replace(identity(), rule_version=OFFICIAL_ACCOUNT_RULE_V1_VERSION),
        replace(
            identity(),
            generator_prompt_version=OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V2_VERSION,
        ),
        replace(identity(), rule_version=OFFICIAL_ACCOUNT_RULE_V2_VERSION),
    )

    for mismatched in mismatched_identities:
        with pytest.raises(ValueError, match="prompt/rule version bundle is unsupported"):
            build_generation_prompt(_generation_request(mismatched))


@pytest.mark.asyncio
async def test_article_builder_and_validator_reject_mixed_release_identities() -> None:
    source, configured_identity, article = await fixture_article()
    mixed_versions = article.versions.model_copy(
        update={"auditor_prompt_version": "official-account-auditor-unknown"}
    )
    result = await DeterministicFakeOfficialAccountArticleGenerator().generate(
        _generation_request(configured_identity)
    )

    with pytest.raises(ValueError, match="schema/media-plan bundle is unsupported"):
        build_article_package(
            draft=result.draft,
            source=source,
            versions=mixed_versions,
            default_author=configured_identity.default_author,
            body_media_candidate_count=3,
        )

    mixed_article = article.model_copy(update={"versions": mixed_versions})
    codes = {
        issue.code
        for issue in validate_article_package(
            mixed_article,
            source=source,
            default_author=configured_identity.default_author,
            min_characters=configured_identity.min_characters,
            target_min_characters=configured_identity.target_min_characters,
            target_max_characters=configured_identity.target_max_characters,
            max_characters=configured_identity.max_characters,
        )
    }
    assert "article_version_bundle_invalid" in codes


def test_claim_binding_types_are_closed_and_brand_cannot_prove_fact() -> None:
    with pytest.raises(ValidationError):
        GeneratedArticleClaim(
            id="fact-1",
            text="不合法事实",
            kind="external_fact",
            brand_chunk_ids=(uuid4(),),
        )
    with pytest.raises(ValidationError):
        GeneratedArticleClaim(
            id="opinion-1",
            text="不合法观点",
            kind="opinion",
            evidence_ids=(uuid4(),),
        )


@pytest.mark.asyncio
async def test_validation_rejects_unknown_ids_refs_author_and_tampered_fingerprint() -> None:
    source, configured_identity, article = await fixture_article()
    first_section = article.sections[0]
    first_block = first_section.blocks[0]
    assert isinstance(first_block, ArticleParagraphBlock)
    bad_block = first_block.model_copy(update={"claim_refs": ("unknown-claim",)})
    bad_section = first_section.model_copy(
        update={"blocks": (bad_block, *first_section.blocks[1:])}
    )
    external_claim = next(claim for claim in article.claims if claim.kind == "external_fact")
    bad_claim = external_claim.model_copy(update={"evidence_ids": (uuid4(),)})
    bad_claims = tuple(
        bad_claim if item.id == external_claim.id else item for item in article.claims
    )
    tampered = article.model_copy(
        update={
            "author": "未知作者",
            "sections": (bad_section, *article.sections[1:]),
            "claims": bad_claims,
            "content_fingerprint": "f" * 64,
        }
    )

    codes = {
        issue.code
        for issue in validate_article_package(
            tampered,
            source=source,
            default_author=configured_identity.default_author,
            min_characters=configured_identity.min_characters,
            target_min_characters=configured_identity.target_min_characters,
            target_max_characters=configured_identity.target_max_characters,
            max_characters=configured_identity.max_characters,
        )
    }
    assert {
        "article_author_mismatch",
        "article_claim_ref_unknown",
        "article_evidence_unknown",
        "article_source_set_mismatch",
        "article_content_fingerprint_mismatch",
    } <= codes


@pytest.mark.asyncio
async def test_article_package_rejects_extra_fields() -> None:
    _, _, article = await fixture_article()
    payload = article.model_dump(mode="json")
    payload["platform"] = "wechat"
    with pytest.raises(ValidationError):
        type(article).model_validate(payload)


def test_current_media_plan_is_deterministic_and_safely_degrades_live_one_image() -> None:
    assert plan_body_media_slots(section_count=5, candidate_count=5) == (0, 1, 3, 4)
    assert plan_body_media_slots(section_count=5, candidate_count=3) == (0, 2, 4)
    assert plan_body_media_slots(section_count=4, candidate_count=3) == (0, 2, 3)
    assert plan_body_media_slots(section_count=5, candidate_count=1) == (0,)
    assert plan_body_media_slots(
        section_count=5,
        candidate_count=3,
        media_plan_version=OFFICIAL_ACCOUNT_MEDIA_PLAN_V1_VERSION,
    ) == (0, 1, 3)


@pytest.mark.asyncio
async def test_semantic_media_assignment_is_one_to_one_and_heading_weighted() -> None:
    _, _, article = await fixture_article()
    placements = [
        (section_index, block.alt_text)
        for section_index, section in enumerate(article.sections)
        for block in section.blocks
        if block.kind == "image"
    ]

    assert [section_index for section_index, _ in placements] == [0, 2, 3]
    assert [alt_text for _, alt_text in placements] == list(FIXTURE_BODY_ALT_TEXTS)


def test_semantic_media_assignment_uses_stable_candidate_tie_break() -> None:
    candidates = tuple(
        SemanticMediaCandidate(
            candidate_id=candidate_id,
            sha256=checksum,
            semantic_label="通用课堂记录",
            semantic_tags=("不存在的标签",),
            alt_text=f"{candidate_id}的课堂记录",
            caption_text=f"{candidate_id}的课堂记录画面。",
            publication_priority=priority,
        )
        for priority, candidate_id, checksum in (
            (2, "candidate-c", "c" * 64),
            (0, "candidate-a", "a" * 64),
            (1, "candidate-b", "b" * 64),
        )
    )
    sections = tuple(
        ArticleSection(
            heading=f"第{index + 1}节",
            blocks=(ArticleParagraphBlock(kind="paragraph", text="通用正文。"),),
        )
        for index in range(4)
    )

    assignments = assign_semantic_body_media(sections=sections, candidates=candidates)

    assert [item.section_index for item in assignments] == [0, 2, 3]
    assert [item.candidate_id for item in assignments] == [
        "candidate-a",
        "candidate-b",
        "candidate-c",
    ]
    assert [item.reason_code for item in assignments] == [
        "stable_fallback",
        "stable_fallback",
        "stable_fallback",
    ]
