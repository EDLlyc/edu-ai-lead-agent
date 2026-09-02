from types import SimpleNamespace
from typing import cast
from uuid import uuid4

import pytest
from app.application.ports.official_account_local import (
    OfficialAccountGenerationRequest,
    OfficialAccountSourceMedia,
    OfficialAccountVersionIdentity,
)
from app.application.services.official_account_export import _assert_copy_ready_context_rights
from app.application.services.official_account_local import (
    _build_repaired_article_package,
    run_request_fingerprint,
    select_news_context_media,
)
from app.domain.official_account_local import (
    OFFICIAL_ACCOUNT_ARTICLE_SCHEMA_V5_VERSION,
    OFFICIAL_ACCOUNT_ARTICLE_SCHEMA_VERSION,
    OFFICIAL_ACCOUNT_AUDIT_SCHEMA_VERSION,
    OFFICIAL_ACCOUNT_AUDITOR_PROMPT_VERSION,
    OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V5_VERSION,
    OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V7_VERSION,
    OFFICIAL_ACCOUNT_GENERATOR_PROMPT_VERSION,
    OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V6_VERSION,
    OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V7_VERSION,
    OFFICIAL_ACCOUNT_LOCAL_ADAPTER_VERSION,
    OFFICIAL_ACCOUNT_MEDIA_PLAN_V4_VERSION,
    OFFICIAL_ACCOUNT_MEDIA_PLAN_VERSION,
    OFFICIAL_ACCOUNT_NEWS_CONTEXT_SELECTION_VERSION,
    OFFICIAL_ACCOUNT_RENDERER_V8_VERSION,
    OFFICIAL_ACCOUNT_RENDERER_VERSION,
    OFFICIAL_ACCOUNT_RULE_VERSION,
    OFFICIAL_ACCOUNT_STYLE_V8_VERSION,
    OFFICIAL_ACCOUNT_STYLE_VERSION,
    OFFICIAL_ACCOUNT_TEMPLATE_V8_VERSION,
    OFFICIAL_ACCOUNT_TEMPLATE_VERSION,
    OFFICIAL_ACCOUNT_VISUAL_QUERY_VERSION,
    OFFICIAL_ACCOUNT_VISUAL_SELECTOR_VERSION,
    ArticleMediaSelectionItem,
    ArticleMediaSelectionSnapshot,
    ArticleNewsContextMediaItem,
    ArticleNewsContextMediaSnapshot,
    ArticlePackage,
    ArticleParagraphBlock,
    ArticleVersionBundle,
    GeneratedArticleSection,
    SemanticMediaCandidate,
    article_version_bundle_kind,
    assign_deterministic_body_media_v3,
    assign_deterministic_body_media_v4,
    build_article_package,
    validate_article_package,
)
from app.infrastructure.official_account_local import (
    DeterministicFakeOfficialAccountArticleGenerator,
    fixture_source_snapshot,
)


def _v9_versions() -> ArticleVersionBundle:
    return ArticleVersionBundle(
        generator_prompt_version=OFFICIAL_ACCOUNT_GENERATOR_PROMPT_VERSION,
        article_schema_version=OFFICIAL_ACCOUNT_ARTICLE_SCHEMA_V5_VERSION,
        auditor_prompt_version=OFFICIAL_ACCOUNT_AUDITOR_PROMPT_VERSION,
        audit_schema_version=OFFICIAL_ACCOUNT_AUDIT_SCHEMA_VERSION,
        rule_version=OFFICIAL_ACCOUNT_RULE_VERSION,
        renderer_version=OFFICIAL_ACCOUNT_RENDERER_V8_VERSION,
        style_version=OFFICIAL_ACCOUNT_STYLE_V8_VERSION,
        template_version=OFFICIAL_ACCOUNT_TEMPLATE_V8_VERSION,
        local_adapter_version=OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V6_VERSION,
        media_plan_version=OFFICIAL_ACCOUNT_MEDIA_PLAN_VERSION,
        visual_query_version=OFFICIAL_ACCOUNT_VISUAL_QUERY_VERSION,
        visual_selector_version=OFFICIAL_ACCOUNT_VISUAL_SELECTOR_VERSION,
        context_media_plan_version=OFFICIAL_ACCOUNT_NEWS_CONTEXT_SELECTION_VERSION,
    )


def _v10_versions() -> ArticleVersionBundle:
    return _v9_versions().model_copy(
        update={
            "generator_prompt_version": OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V7_VERSION,
            "media_plan_version": OFFICIAL_ACCOUNT_MEDIA_PLAN_V4_VERSION,
            "local_adapter_version": OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V7_VERSION,
        }
    )


def _candidate(index: int, *, alt_text: str) -> OfficialAccountSourceMedia:
    return OfficialAccountSourceMedia(
        source_image_artifact_id=None,
        fixture_id=None,
        source_article_image_id=uuid4(),
        media_type="image/jpeg",
        byte_size=10_000 + index,
        sha256=f"{index + 1:064x}",
        ordinal=index,
        alt_text=alt_text,
        caption_text=f"{alt_text}现场图片",
        candidate_id=f"news-{index}",
        source_page_url="https://source.example/news/article",
        image_url=f"https://source.example/news/image-{index}.jpg",
        rights_status="publish_permission_unverified",
        context_only_not_evidence=True,
        width=1_200,
        height=800,
    )


def _sections() -> tuple[GeneratedArticleSection, ...]:
    return (
        GeneratedArticleSection(
            heading="理解新闻背景",
            blocks=(ArticleParagraphBlock(kind="paragraph", text="先理解事件背景。"),),
        ),
        GeneratedArticleSection(
            heading="火星机器人着陆",
            blocks=(ArticleParagraphBlock(kind="paragraph", text="观察火星地貌。"),),
        ),
        GeneratedArticleSection(
            heading="实验课堂记录",
            blocks=(ArticleParagraphBlock(kind="paragraph", text="学生完成实验并记录。"),),
        ),
    )


def test_v9_is_exact_and_v8_with_context_identity_fails_closed() -> None:
    v9 = _v9_versions()
    assert article_version_bundle_kind(v9) == "v9"
    assert v9.model_dump()["context_media_plan_version"] == (
        OFFICIAL_ACCOUNT_NEWS_CONTEXT_SELECTION_VERSION
    )
    assert (
        article_version_bundle_kind(
            v9.model_copy(
                update={"generator_prompt_version": OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V5_VERSION}
            )
        )
        == "v9"
    )

    v8 = v9.model_copy(
        update={
            "generator_prompt_version": OFFICIAL_ACCOUNT_GENERATOR_PROMPT_V5_VERSION,
            "article_schema_version": OFFICIAL_ACCOUNT_ARTICLE_SCHEMA_VERSION,
            "renderer_version": OFFICIAL_ACCOUNT_RENDERER_VERSION,
            "style_version": OFFICIAL_ACCOUNT_STYLE_VERSION,
            "template_version": OFFICIAL_ACCOUNT_TEMPLATE_VERSION,
            "local_adapter_version": OFFICIAL_ACCOUNT_LOCAL_ADAPTER_VERSION,
            "context_media_plan_version": None,
        }
    )
    assert article_version_bundle_kind(v8) == "v8"
    assert "context_media_plan_version" not in v8.model_dump()
    assert (
        article_version_bundle_kind(
            v8.model_copy(
                update={"generator_prompt_version": OFFICIAL_ACCOUNT_GENERATOR_PROMPT_VERSION}
            )
        )
        is None
    )

    v10 = _v10_versions()
    assert article_version_bundle_kind(v10) == "v10"
    assert (
        article_version_bundle_kind(
            v10.model_copy(update={"media_plan_version": OFFICIAL_ACCOUNT_MEDIA_PLAN_VERSION})
        )
        is None
    )
    assert (
        article_version_bundle_kind(
            v10.model_copy(
                update={"local_adapter_version": OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V6_VERSION}
            )
        )
        is None
    )
    assert (
        article_version_bundle_kind(
            v8.model_copy(
                update={
                    "context_media_plan_version": OFFICIAL_ACCOUNT_NEWS_CONTEXT_SELECTION_VERSION
                }
            )
        )
        is None
    )


def test_news_context_selection_is_deterministic_for_zero_one_or_two_images() -> None:
    sections = _sections()
    empty = select_news_context_media(topic_title="科技教育新闻", sections=sections, candidates=())
    assert empty.status == "not_present"
    assert empty.items == ()

    first = _candidate(0, alt_text="火星机器人着陆")
    single = select_news_context_media(
        topic_title="科技教育新闻", sections=sections, candidates=(first,)
    )
    assert single.status == "partial"
    assert single.items[0].section_index == 1
    assert single.items[0].source_article_image_id == first.source_article_image_id

    second = _candidate(1, alt_text="实验课堂记录")
    selected = select_news_context_media(
        topic_title="科技教育新闻", sections=sections, candidates=(first, second)
    )
    assert selected.status == "ready"
    assert tuple(item.ordinal for item in selected.items) == (0, 1)
    assert tuple(item.section_index for item in selected.items) == (1, 2)
    assert all(item.context_only_not_evidence for item in selected.items)
    assert all(item.rights_status == "publish_permission_unverified" for item in selected.items)


def test_copy_ready_fails_closed_for_unverified_news_context_rights() -> None:
    article = cast(
        ArticlePackage,
        SimpleNamespace(
            news_context_media=SimpleNamespace(
                items=(SimpleNamespace(rights_status="publish_permission_unverified"),)
            )
        ),
    )

    _assert_copy_ready_context_rights(article, mode="review")
    with pytest.raises(ValueError, match="unverified publication rights"):
        _assert_copy_ready_context_rights(article, mode="copy-ready")


@pytest.mark.asyncio
@pytest.mark.parametrize("versions", (_v9_versions(), _v10_versions()), ids=("v9", "v10"))
async def test_news_context_validator_accepts_five_body_slots_and_separate_context_media(
    versions: ArticleVersionBundle,
) -> None:
    source = fixture_source_snapshot()
    identity = OfficialAccountVersionIdentity(
        provider="fake",
        model="official-account-fixture-v1",
        generator_prompt_version=versions.generator_prompt_version,
        article_schema_version=versions.article_schema_version,
        auditor_prompt_version=versions.auditor_prompt_version,
        audit_schema_version=versions.audit_schema_version,
        rule_version=versions.rule_version,
        renderer_version=versions.renderer_version,
        style_version=versions.style_version,
        template_version=versions.template_version,
        local_adapter_version=versions.local_adapter_version,
        default_author="赛先生",
        min_characters=1,
        target_min_characters=1,
        target_max_characters=10_000,
        max_characters=10_000,
        media_plan_version=versions.media_plan_version,
        visual_query_version=versions.visual_query_version,
        visual_selector_version=versions.visual_selector_version,
        context_media_plan_version=versions.context_media_plan_version,
    )
    request = OfficialAccountGenerationRequest(
        run_id=uuid4(),
        source=source,
        identity=identity,
        request_fingerprint=run_request_fingerprint(
            source_fingerprint=source.source_fingerprint,
            generation_mode="fixture",
            identity=identity,
        ),
        max_output_tokens=8_192,
    )
    generated = await DeterministicFakeOfficialAccountArticleGenerator().generate(request)
    expanded_draft = generated.draft.model_copy(
        update={
            "sections": (
                *generated.draft.sections,
                GeneratedArticleSection(
                    heading="把观察留到下一次验证",
                    blocks=(
                        ArticleParagraphBlock(
                            kind="paragraph",
                            text="记录这次判断仍然不确定的地方。下一次再用新的观察继续核对。",
                            claim_refs=(generated.draft.claims[0].id,),
                        ),
                    ),
                ),
                GeneratedArticleSection(
                    heading="让结论保留可以修正的空间",
                    blocks=(
                        ArticleParagraphBlock(
                            kind="paragraph",
                            text="新的证据出现时。再回来看原来的结论是否仍然成立。",
                            claim_refs=(generated.draft.claims[0].id,),
                        ),
                    ),
                ),
            )
        }
    )
    candidates = tuple(
        SemanticMediaCandidate(
            candidate_id=f"{index + 1:016x}",
            sha256=f"{index + 11:064x}",
            semantic_label=f"公司IP场景{index + 1}",
            semantic_tags=(f"场景{index + 1}",),
            alt_text=f"小赛陪伴孩子完成探究步骤{index + 1}",
            caption_text=f"公司IP正文配图{index + 1}",
            publication_priority=index,
        )
        for index in range(5)
    )
    assignments = (
        assign_deterministic_body_media_v4(
            sections=expanded_draft.sections,
            candidates=candidates,
        )
        if versions.media_plan_version == OFFICIAL_ACCOUNT_MEDIA_PLAN_V4_VERSION
        else assign_deterministic_body_media_v3(
            sections=expanded_draft.sections,
            candidates=candidates,
        )
    )
    media_selection = ArticleMediaSelectionSnapshot(
        media_plan_version=versions.media_plan_version,
        visual_query_version=OFFICIAL_ACCOUNT_VISUAL_QUERY_VERSION,
        visual_selector_version=OFFICIAL_ACCOUNT_VISUAL_SELECTOR_VERSION,
        status="semantic_unavailable",
        closed_reason="disabled",
        catalog_version="test-catalog-v1",
        catalog_fingerprint="a" * 64,
        assignments=tuple(
            ArticleMediaSelectionItem(
                ordinal=item.ordinal,
                section_index=item.section_index,
                candidate_ref=item.candidate_id,
                source_checksum=f"{item.ordinal + 101:064x}",
                publication_checksum=item.sha256,
                selection_method=item.selection_method,
                reason_code=item.reason_code,
                similarity_band=item.similarity_band,
            )
            for item in assignments
        ),
    )
    context_media = ArticleNewsContextMediaSnapshot(
        selection_version=OFFICIAL_ACCOUNT_NEWS_CONTEXT_SELECTION_VERSION,
        status="partial",
        items=(
            ArticleNewsContextMediaItem(
                ordinal=0,
                section_index=2,
                source_article_image_id=uuid4(),
                sha256="f" * 64,
                media_type="image/png",
                width=600,
                height=316,
                alt_text="新闻原文中的真空涨落实验示意图",
                caption="新闻原图。仅作上下文说明",
                credit="中国科学院",
                source_page_url="https://www.cas.cn/news/example.html",
                rights_status="publish_permission_unverified",
            ),
        ),
    )
    article = build_article_package(
        draft=expanded_draft,
        source=source,
        versions=versions,
        default_author=identity.default_author,
        body_media_candidate_count=5,
        semantic_media_assignments=assignments,
        media_selection=media_selection,
        news_context_media=context_media,
    )

    issues = validate_article_package(
        article,
        source=source,
        default_author=identity.default_author,
        min_characters=identity.min_characters,
        target_min_characters=identity.target_min_characters,
        target_max_characters=identity.target_max_characters,
        max_characters=identity.max_characters,
    )

    assert issues == ()
    assert tuple(slot.slot_key for slot in article.media_slots) == (
        "body-0",
        "body-1",
        "body-2",
        "body-3",
        "body-4",
        "cover-0",
    )
    assert article.news_context_media == context_media

    repaired = _build_repaired_article_package(
        source_article=article,
        draft=expanded_draft,
        source=source,
        source_media_candidates=tuple(
            OfficialAccountSourceMedia(
                source_image_artifact_id=None,
                fixture_id=f"fixture-{item.candidate_id}",
                media_type="image/png",
                byte_size=1,
                sha256=item.sha256,
                ordinal=index,
                candidate_id=item.candidate_id,
                alt_text=item.alt_text,
                caption_text=item.caption_text,
            )
            for index, item in enumerate(candidates)
        ),
        default_author=identity.default_author,
    )
    assert repaired.news_context_media == context_media
    assert repaired.media_selection == article.media_selection
    assert repaired.media_slots == article.media_slots

    malformed = article.model_copy(update={"media_slots": article.media_slots[1:]})
    malformed_codes = {
        issue.code
        for issue in validate_article_package(
            malformed,
            source=source,
            default_author=identity.default_author,
            min_characters=identity.min_characters,
            target_min_characters=identity.target_min_characters,
            target_max_characters=identity.target_max_characters,
            max_characters=identity.max_characters,
        )
    }
    assert "article_media_slot_invalid" in malformed_codes
