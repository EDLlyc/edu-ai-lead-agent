# ruff: noqa: RUF001 -- Chinese punctuation is intentional in reader-facing export assertions.

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
from uuid import UUID, uuid4
from zipfile import ZipFile

import pytest
from app.application.ports.official_account_local import (
    OfficialAccountMediaRequest,
    OfficialAccountMediaResult,
    StoredOfficialAccountManualReview,
)
from app.application.services.official_account_export import (
    ReviewBundleInput,
    export_fixture_review_bundle,
    export_live_local_review_bundle,
    run_wechat_draft_preflight,
)
from app.domain.official_account_local import (
    OFFICIAL_ACCOUNT_ARTICLE_SCHEMA_V5_VERSION,
    OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V1_VERSION,
    OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V2_VERSION,
    OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V3_VERSION,
    OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V4_VERSION,
    OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V6_VERSION,
    OFFICIAL_ACCOUNT_LOCAL_ADAPTER_VERSION,
    OFFICIAL_ACCOUNT_NEWS_CONTEXT_SELECTION_VERSION,
    OFFICIAL_ACCOUNT_RENDERER_V8_VERSION,
    OFFICIAL_ACCOUNT_STYLE_V8_VERSION,
    OFFICIAL_ACCOUNT_TEMPLATE_V8_VERSION,
    ArticleNewsContextMediaItem,
    ArticleNewsContextMediaSnapshot,
    OfficialAccountAuditVerdict,
    article_version_bundle_kind,
    fingerprint,
    render_wechat_html,
    resolve_body_media_placeholder,
    resolve_body_media_placeholders,
    resolve_context_media_placeholders,
)
from app.infrastructure.official_account_local import (
    FIXTURE_BODY_IMAGE_BYTE_SIZES,
    FIXTURE_BODY_IMAGE_SHA256S,
    FIXTURE_BODY_PUBLICATION_BYTE_SIZES,
    FIXTURE_BODY_PUBLICATION_MEDIA_TYPE,
    FIXTURE_BODY_PUBLICATION_SHA256S,
    FIXTURE_COVER_BYTE_SIZE,
    FIXTURE_COVER_MEDIA_TYPE,
    FIXTURE_COVER_PUBLICATION_BYTE_SIZE,
    FIXTURE_COVER_PUBLICATION_MEDIA_TYPE,
    FIXTURE_COVER_PUBLICATION_SHA256,
    FIXTURE_COVER_SHA256,
    FIXTURE_IMAGE_BYTE_SIZE,
    FIXTURE_IMAGE_MEDIA_TYPE,
    FIXTURE_IMAGE_SHA256,
    LocalOfficialAccountMediaAdapter,
    fixture_body_image_path,
    fixture_body_publication_path,
    fixture_cover_path,
    fixture_cover_publication_path,
    fixture_image_path,
)
from PIL import Image
from test_official_account_article import (
    fixture_article,
    historical_fixture_article,
    historical_multi_fixture_article,
)
from test_official_account_worker import (
    _CountingSemanticRanker,
    _current_identity,
    _executor,
    _MemoryRepository,
)


async def _bundle_input() -> ReviewBundleInput:
    _, _, article = await historical_fixture_article()
    rendered = render_wechat_html(article)
    adapter = LocalOfficialAccountMediaAdapter()
    render_id = uuid4()
    run_id = UUID("439ffce7-5a11-46f5-818b-0800dcc28a98")
    body = await adapter.stage(
        OfficialAccountMediaRequest(
            run_id=run_id,
            render_version_id=render_id,
            source_image_artifact_id=None,
            fixture_id="official-account-article-v1",
            role="body",
            ordinal=0,
            source_sha256=FIXTURE_IMAGE_SHA256,
            media_type=FIXTURE_IMAGE_MEDIA_TYPE,
            byte_size=FIXTURE_IMAGE_BYTE_SIZE,
            local_adapter_version=OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V2_VERSION,
            request_fingerprint="1" * 64,
        )
    )
    cover = await adapter.stage(
        OfficialAccountMediaRequest(
            run_id=run_id,
            render_version_id=render_id,
            source_image_artifact_id=None,
            fixture_id="official-account-article-v1",
            role="cover",
            ordinal=0,
            source_sha256=FIXTURE_IMAGE_SHA256,
            media_type=FIXTURE_IMAGE_MEDIA_TYPE,
            byte_size=FIXTURE_IMAGE_BYTE_SIZE,
            local_adapter_version=OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V2_VERSION,
            request_fingerprint="2" * 64,
        )
    )
    resolved_html = resolve_body_media_placeholder(rendered.canonical_html, body.media_url)
    return ReviewBundleInput(
        run_id=run_id,
        run_status="ready",
        request_fingerprint="3" * 64,
        generation_mode="fixture",
        simulation=True,
        article=article,
        validation_issues=(),
        audit=OfficialAccountAuditVerdict(accepted=True),
        resolved_html=resolved_html,
        draft_request_fingerprint="4" * 64,
        resolved_fingerprint=fingerprint(rendered.render_fingerprint, "4" * 64, resolved_html),
        render_fingerprint=rendered.render_fingerprint,
        body_media=body,
        cover_media=cover,
        body_bytes=fixture_image_path().read_bytes(),
        cover_bytes=fixture_cover_path().read_bytes(),
    )


async def _multi_bundle_input() -> ReviewBundleInput:
    _, _, article = await historical_multi_fixture_article()
    rendered = render_wechat_html(article)
    adapter = LocalOfficialAccountMediaAdapter()
    render_id = uuid4()
    run_id = UUID("539ffce7-5a11-46f5-818b-0800dcc28a98")
    bodies = tuple(
        [
            await adapter.stage(
                OfficialAccountMediaRequest(
                    run_id=run_id,
                    render_version_id=render_id,
                    source_image_artifact_id=None,
                    fixture_id="official-account-article-v1",
                    role="body",
                    ordinal=ordinal,
                    source_sha256=checksum,
                    media_type=FIXTURE_IMAGE_MEDIA_TYPE,
                    byte_size=byte_size,
                    local_adapter_version=OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V3_VERSION,
                    request_fingerprint=f"{ordinal + 1}" * 64,
                )
            )
            for ordinal, (checksum, byte_size) in enumerate(
                zip(FIXTURE_BODY_IMAGE_SHA256S, FIXTURE_BODY_IMAGE_BYTE_SIZES, strict=True)
            )
        ]
    )
    cover = await adapter.stage(
        OfficialAccountMediaRequest(
            run_id=run_id,
            render_version_id=render_id,
            source_image_artifact_id=None,
            fixture_id="official-account-article-v1",
            role="cover",
            ordinal=0,
            source_sha256=FIXTURE_BODY_IMAGE_SHA256S[0],
            media_type=FIXTURE_IMAGE_MEDIA_TYPE,
            byte_size=FIXTURE_BODY_IMAGE_BYTE_SIZES[0],
            local_adapter_version=OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V3_VERSION,
            request_fingerprint="4" * 64,
        )
    )
    resolved_html = resolve_body_media_placeholders(
        rendered.canonical_html,
        tuple((body.ordinal, body.media_url) for body in bodies),
    )
    body_bytes = tuple(fixture_body_image_path(ordinal).read_bytes() for ordinal in range(3))
    return ReviewBundleInput(
        run_id=run_id,
        run_status="ready",
        request_fingerprint="5" * 64,
        generation_mode="fixture",
        simulation=True,
        article=article,
        validation_issues=(),
        audit=OfficialAccountAuditVerdict(accepted=True),
        resolved_html=resolved_html,
        draft_request_fingerprint="6" * 64,
        resolved_fingerprint=fingerprint(rendered.render_fingerprint, "6" * 64, resolved_html),
        render_fingerprint=rendered.render_fingerprint,
        body_media=bodies[0],
        cover_media=cover,
        body_bytes=body_bytes[0],
        cover_bytes=fixture_cover_path().read_bytes(),
        body_media_items=bodies,
        body_bytes_items=body_bytes,
    )


async def _semantic_bundle_input(
    *,
    manual_review: StoredOfficialAccountManualReview | None = None,
) -> ReviewBundleInput:
    _, _, article = await fixture_article()
    rendered = render_wechat_html(article)
    adapter = LocalOfficialAccountMediaAdapter()
    render_id = uuid4()
    run_id = UUID("639ffce7-5a11-46f5-818b-0800dcc28a98")
    bodies = tuple(
        [
            await adapter.stage(
                OfficialAccountMediaRequest(
                    run_id=run_id,
                    render_version_id=render_id,
                    source_image_artifact_id=None,
                    fixture_id="official-account-article-v1",
                    role="body",
                    ordinal=ordinal,
                    source_sha256=checksum,
                    media_type=FIXTURE_BODY_PUBLICATION_MEDIA_TYPE,
                    byte_size=byte_size,
                    local_adapter_version=OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V4_VERSION,
                    request_fingerprint=f"{ordinal + 1}" * 64,
                )
            )
            for ordinal, (checksum, byte_size) in enumerate(
                zip(
                    FIXTURE_BODY_PUBLICATION_SHA256S,
                    FIXTURE_BODY_PUBLICATION_BYTE_SIZES,
                    strict=True,
                )
            )
        ]
    )
    cover = await adapter.stage(
        OfficialAccountMediaRequest(
            run_id=run_id,
            render_version_id=render_id,
            source_image_artifact_id=None,
            fixture_id="official-account-article-v1",
            role="cover",
            ordinal=0,
            source_sha256=FIXTURE_BODY_PUBLICATION_SHA256S[0],
            media_type=FIXTURE_BODY_PUBLICATION_MEDIA_TYPE,
            byte_size=FIXTURE_BODY_PUBLICATION_BYTE_SIZES[0],
            local_adapter_version=OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V4_VERSION,
            request_fingerprint="4" * 64,
        )
    )
    resolved_html = resolve_body_media_placeholders(
        rendered.canonical_html,
        tuple((body.ordinal, body.media_url) for body in bodies),
    )
    body_bytes = tuple(fixture_body_publication_path(i).read_bytes() for i in range(3))
    return ReviewBundleInput(
        run_id=run_id,
        run_status="ready",
        request_fingerprint="5" * 64,
        generation_mode="fixture",
        simulation=True,
        article=article,
        validation_issues=(),
        audit=OfficialAccountAuditVerdict(accepted=True),
        resolved_html=resolved_html,
        draft_request_fingerprint="6" * 64,
        resolved_fingerprint=fingerprint(rendered.render_fingerprint, "6" * 64, resolved_html),
        render_fingerprint=rendered.render_fingerprint,
        body_media=bodies[0],
        cover_media=cover,
        body_bytes=body_bytes[0],
        cover_bytes=fixture_cover_publication_path().read_bytes(),
        body_media_items=bodies,
        body_bytes_items=body_bytes,
        manual_review=manual_review,
    )


async def _multimodal_bundle_input() -> ReviewBundleInput:
    repository = _MemoryRepository(identity=_current_identity())
    ranker = _CountingSemanticRanker()
    assert await _executor(repository, media_semantic_ranker=ranker).execute_next("fixture-worker")
    assert repository.article is not None
    assert repository.article.audit == OfficialAccountAuditVerdict(accepted=True)
    assert repository.render is not None
    assert repository.draft is not None
    body_media = tuple(
        result
        for (role, _ordinal), (_media_id, result) in sorted(repository.media.items())
        if role == "body"
    )
    cover_media = repository.media[("cover", 0)][1]
    body_bytes = tuple(fixture_body_publication_path(i).read_bytes() for i in range(3))
    cover_bytes = fixture_cover_publication_path().read_bytes()
    draft_request_fingerprint = "9" * 64
    return ReviewBundleInput(
        run_id=repository.run_id,
        run_status="ready",
        request_fingerprint="8" * 64,
        generation_mode="fixture",
        simulation=True,
        article=repository.article.article,
        validation_issues=repository.article.validation_issues,
        audit=repository.article.audit,
        resolved_html=repository.draft.resolved_html,
        draft_request_fingerprint=draft_request_fingerprint,
        resolved_fingerprint=fingerprint(
            repository.render.render_fingerprint,
            draft_request_fingerprint,
            repository.draft.resolved_html,
        ),
        render_fingerprint=repository.render.render_fingerprint,
        body_media=body_media[0],
        cover_media=cover_media,
        body_bytes=body_bytes[0],
        cover_bytes=cover_bytes,
        body_media_items=body_media,
        body_bytes_items=body_bytes,
    )


async def _news_context_bundle_input(
    *,
    alt_text: str = "暗腔实验装置新闻原图",
    caption: str | None = "科学家利用暗腔开展超导实验",
    cover_bytes: bytes | None = None,
) -> ReviewBundleInput:
    base = await _multimodal_bundle_input()
    context_bytes = fixture_cover_path().read_bytes()
    context_sha256 = sha256(context_bytes).hexdigest()
    context_item = ArticleNewsContextMediaItem(
        ordinal=0,
        section_index=0,
        source_article_image_id=uuid4(),
        sha256=context_sha256,
        media_type="image/png",
        width=1923,
        height=818,
        alt_text=alt_text,
        caption=caption,
        credit="中国科学院",
        source_page_url="https://www.cas.cn/syky/202608/t20260821_5099999.shtml",
        rights_status="publish_permission_unverified",
        context_only_not_evidence=True,
    )
    versions = base.article.versions.model_copy(
        update={
            "article_schema_version": OFFICIAL_ACCOUNT_ARTICLE_SCHEMA_V5_VERSION,
            "renderer_version": OFFICIAL_ACCOUNT_RENDERER_V8_VERSION,
            "style_version": OFFICIAL_ACCOUNT_STYLE_V8_VERSION,
            "template_version": OFFICIAL_ACCOUNT_TEMPLATE_V8_VERSION,
            "local_adapter_version": OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V6_VERSION,
            "context_media_plan_version": OFFICIAL_ACCOUNT_NEWS_CONTEXT_SELECTION_VERSION,
        }
    )
    article = base.article.model_copy(
        update={
            "versions": versions,
            "news_context_media": ArticleNewsContextMediaSnapshot(
                selection_version=OFFICIAL_ACCOUNT_NEWS_CONTEXT_SELECTION_VERSION,
                status="partial",
                items=(context_item,),
            ),
        }
    )
    rendered = render_wechat_html(article)
    resolved_html = resolve_context_media_placeholders(
        resolve_body_media_placeholders(
            rendered.canonical_html,
            tuple((item.ordinal, item.media_url) for item in base.body_media_items),
        ),
        ((0, "/api/v1/official-account-local/media/context-test"),),
    )
    context_media = OfficialAccountMediaResult(
        local_media_id="context-test",
        role="context",
        ordinal=0,
        media_url="/api/v1/official-account-local/media/context-test",
        media_type="image/png",
        byte_size=len(context_bytes),
        sha256=context_sha256,
        assigned_section_index=0,
        alt_text=context_item.alt_text,
        provenance_kind="persisted_source_snapshot",
        source_page_url=context_item.source_page_url,
        caption=context_item.caption,
        credit=context_item.credit,
        rights_status=context_item.rights_status,
        context_only_not_evidence=True,
    )
    draft_fingerprint = "a" * 64
    cover_media = base.cover_media
    if cover_bytes is not None:
        cover_media = replace(
            cover_media,
            media_type="image/png",
            byte_size=len(cover_bytes),
            sha256=sha256(cover_bytes).hexdigest(),
        )
    return replace(
        base,
        generation_mode="live",
        article=article,
        resolved_html=resolved_html,
        draft_request_fingerprint=draft_fingerprint,
        resolved_fingerprint=fingerprint(
            rendered.render_fingerprint,
            draft_fingerprint,
            resolved_html,
        ),
        render_fingerprint=rendered.render_fingerprint,
        cover_media=cover_media,
        cover_bytes=cover_bytes if cover_bytes is not None else base.cover_bytes,
        context_media_items=(context_media,),
        context_bytes_items=(context_bytes,),
    )


@pytest.mark.asyncio
async def test_conservative_preflight_is_local_versioned_and_keeps_review_pending() -> None:
    bundle = await _bundle_input()

    report = run_wechat_draft_preflight(
        article=bundle.article,
        resolved_html=bundle.resolved_html,
        body_media=bundle.body_media,
        cover_media=bundle.cover_media,
        body_dimensions=(1024, 1024),
        cover_dimensions=(1923, 818),
    )

    assert report.passed is True
    assert report.rule_version == "wechat-draft-preflight-v1"
    assert report.policy_status == "conservative_unverified"
    assert report.manual_review_status == "pending"
    assert report.editorially_approved is False
    assert report.mobile_screenshot_status == "not_run"
    by_code = {item.code: item for item in report.records}
    assert by_code["title_conservative_limit"].source_status == (
        "conservative_public_reference_unverified_by_account"
    )
    assert by_code["body_cover_bytes_distinct"].passed is True
    assert by_code["manual_editorial_review_pending"].severity == "warning"
    assert by_code["mobile_screenshot_not_run"].observed == "not_run"
    assert by_code["body_media_reference_controlled"].observed == (
        "controlled_local_media_reference"
    )
    assert "/api/" not in report.model_dump_json()


@pytest.mark.asyncio
async def test_v9_live_local_export_keeps_body_images_and_adds_snapshot_context(
    tmp_path,
) -> None:
    bundle = await _news_context_bundle_input()

    result = export_live_local_review_bundle(bundle, output_directory=tmp_path)

    assert result.preflight.passed is True
    article_body = (result.bundle_directory / "article-body.html").read_text(encoding="utf-8")
    assert article_body.count('src="assets/body-') == len(bundle.body_media_items)
    assert article_body.count('src="assets/context-') == 1
    assert 'src="assets/context-00.png"' in article_body
    assert "/api/" not in article_body
    assert (result.bundle_directory / "assets/context-00.png").read_bytes() == (
        bundle.context_bytes_items[0]
    )

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["bundle_version"] == (
        "official-account-live-local-review-bundle-v3-news-context-export-polish"
    )
    assert manifest["export_presentation"] == {
        "context_boundary": "context_only_not_evidence",
        "context_display_sources": ["persisted_source"],
        "context_display_version": "official-account-context-display-fallback-v1",
        "cover_derivative_applied": False,
        "cover_derivative_version": ("official-account-cover-export-derivative-v1-top-biased"),
        "runtime_article_immutable": True,
        "runtime_render_immutable": True,
        "version": "official-account-news-context-export-polish-v1",
    }
    assert len(manifest["media"]["body_images"]) == len(bundle.body_media_items)
    assert manifest["media"]["context_images"] == [
        {
            "alt_text": "暗腔实验装置新闻原图",
            "assigned_section_index": 0,
            "byte_size": len(bundle.context_bytes_items[0]),
            "caption": "科学家利用暗腔开展超导实验",
            "context_only_not_evidence": True,
            "credit": "中国科学院",
            "display_text_source": "persisted_source",
            "display_text_version": "official-account-context-display-fallback-v1",
            "dimensions": {"height": 818, "width": 1923},
            "media_type": "image/png",
            "ordinal": 0,
            "path": "assets/context-00.png",
            "rights_status": "publish_permission_unverified",
            "role": "context",
            "sha256": sha256(bundle.context_bytes_items[0]).hexdigest(),
            "source_page_url": ("https://www.cas.cn/syky/202608/t20260821_5099999.shtml"),
        }
    ]
    exported_cover = (result.bundle_directory / manifest["media"]["cover"]["path"]).read_bytes()
    assert exported_cover == bundle.cover_bytes
    assert manifest["media"]["cover"]["sha256"] == bundle.cover_media.sha256
    assert manifest["media"]["cover"]["export_derivative"]["applied"] is False
    article_json = json.loads(
        (result.bundle_directory / "article.json").read_text(encoding="utf-8")
    )
    assert "source_article_image_id" not in json.dumps(article_json)
    sources = json.loads((result.bundle_directory / "sources.json").read_text(encoding="utf-8"))
    assert sources["news_context_media"][0]["source_page_url"].startswith("https://")
    assert sources["news_context_media"][0]["context_only_not_evidence"] is True
    assert sources["news_context_media"][0]["display_text_source"] == "persisted_source"
    assert "暗腔实验装置新闻原图" in article_body
    assert "科学家利用暗腔开展超导实验" in article_body
    preflight_by_code = {item.code: item for item in result.preflight.records}
    assert preflight_by_code["context_0_media_type_allowlisted"].passed is True
    assert preflight_by_code["context_0_media_local_byte_limit"].passed is True
    assert preflight_by_code["context_image_dimensions_readable"].passed is True


@pytest.mark.asyncio
async def test_v9_live_local_export_derives_square_cover_and_generic_cas_display_text(
    tmp_path,
) -> None:
    square = Image.new("RGB", (1024, 1024), (35, 142, 91))
    square.paste((205, 48, 48), (0, 0, 1024, 240))
    square.paste((35, 142, 91), (0, 240, 1024, 760))
    square.paste((45, 86, 180), (0, 760, 1024, 1024))
    encoded = BytesIO()
    square.save(encoded, format="PNG")
    source_cover = encoded.getvalue()
    bundle = await _news_context_bundle_input(
        alt_text="新闻原图",
        caption=None,
        cover_bytes=source_cover,
    )

    result = export_live_local_review_bundle(bundle, output_directory=tmp_path)
    repeated = export_live_local_review_bundle(bundle, output_directory=tmp_path)

    assert repeated.reused is True
    assert repeated.zip_sha256 == result.zip_sha256
    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    cover_manifest = manifest["media"]["cover"]
    cover_path = result.bundle_directory / cover_manifest["path"]
    derived_cover = cover_path.read_bytes()
    assert derived_cover != source_cover
    assert cover_manifest["dimensions"] == {"width": 1024, "height": 436}
    assert cover_manifest["byte_size"] == len(derived_cover)
    assert cover_manifest["sha256"] == sha256(derived_cover).hexdigest()
    assert cover_manifest["export_derivative"] == {
        "applied": True,
        "crop_box": {"bottom": 632, "left": 0, "right": 1024, "top": 196},
        "crop_policy": "top_biased_one_third_or_centered_horizontal",
        "source_byte_size": len(source_cover),
        "source_media_type": "image/png",
        "source_sha256": sha256(source_cover).hexdigest(),
        "target_ratio": "2.35:1",
        "version": "official-account-cover-export-derivative-v1-top-biased",
    }
    with Image.open(cover_path) as image:
        assert image.size == (1024, 436)
        assert image.getpixel((10, 0)) == (205, 48, 48)
        assert image.getexif() == {}

    title = bundle.article.title
    heading = bundle.article.sections[0].heading
    expected_alt = f"新闻上下文图片：{title}；对应章节：{heading}"
    expected_caption = f"新闻上下文 · {title} · 对应章节：{heading}（仅作上下文参考，非事实证据）"
    article_body = (result.bundle_directory / "article-body.html").read_text(encoding="utf-8")
    preview = (result.bundle_directory / "preview.html").read_text(encoding="utf-8")
    assert expected_alt in article_body
    assert expected_caption in article_body
    assert "发布权限未验证 · 仅作上下文参考，非事实证据" in article_body
    assert expected_alt in preview
    assert expected_caption in preview
    assert "新闻原图" not in article_body
    assert article_body.count('src="assets/body-') == len(bundle.body_media_items)
    assert article_body.count('src="assets/context-00.png"') == 1
    assert "/api/" not in article_body

    context_manifest = manifest["media"]["context_images"][0]
    assert context_manifest["alt_text"] == expected_alt
    assert context_manifest["caption"] == expected_caption
    assert context_manifest["display_text_source"] == "export_semantic_fallback"
    sources = json.loads((result.bundle_directory / "sources.json").read_text(encoding="utf-8"))
    assert sources["news_context_media"][0]["alt_text"] == expected_alt
    assert sources["news_context_media"][0]["caption"] == expected_caption
    assert sources["news_context_media"][0]["context_only_not_evidence"] is True
    immutable_article = json.loads(
        (result.bundle_directory / "article.json").read_text(encoding="utf-8")
    )
    immutable_context = immutable_article["article"]["news_context_media"]["items"][0]
    assert immutable_context["alt_text"] == "新闻原图"
    assert immutable_context["caption"] is None
    assert immutable_article["export_presentation"]["runtime_article_immutable"] is True
    readme = (result.bundle_directory / "README.md").read_text(encoding="utf-8")
    assert "`article.json` 仍保存不可变运行时 Article 快照" in readme

    preflight_by_code = {item.code: item for item in result.preflight.records}
    assert preflight_by_code["cover_wide_ratio_advisory"].passed is True
    assert preflight_by_code["cover_media_local_byte_limit"].observed == len(derived_cover)
    file_manifest = next(
        item for item in manifest["files"] if item["path"] == cover_manifest["path"]
    )
    assert file_manifest["byte_size"] == len(derived_cover)
    assert file_manifest["sha256"] == sha256(derived_cover).hexdigest()


@pytest.mark.asyncio
async def test_preflight_rejects_executable_markup_and_uncontrolled_media() -> None:
    bundle = await _bundle_input()
    unsafe_html = bundle.resolved_html.replace(
        "</section>",
        '<script src="https://example.invalid/x.js"></script></section>',
        1,
    ).replace(bundle.body_media.media_url, "https://example.invalid/body.png")

    report = run_wechat_draft_preflight(
        article=bundle.article,
        resolved_html=unsafe_html,
        body_media=bundle.body_media,
        cover_media=bundle.cover_media,
        body_dimensions=(1024, 1024),
        cover_dimensions=(1923, 818),
    )

    assert report.passed is False
    failed_codes = {item.code for item in report.records if item.severity == "error"}
    assert "html_executable_markup_absent" in failed_codes
    assert "html_allowlisted_shape" in failed_codes
    assert "body_media_reference_controlled" in failed_codes


@pytest.mark.asyncio
async def test_export_creates_atomic_idempotent_review_bundle_and_verified_zip(tmp_path) -> None:
    bundle = await _bundle_input()

    first = export_fixture_review_bundle(bundle, output_directory=tmp_path)
    second = export_fixture_review_bundle(bundle, output_directory=tmp_path)

    assert first.reused is False
    assert second.reused is True
    assert first.bundle_directory == second.bundle_directory
    assert first.zip_sha256 == second.zip_sha256
    files = {
        path.relative_to(first.bundle_directory).as_posix()
        for path in first.bundle_directory.rglob("*")
        if path.is_file()
    }
    assert files == {
        "README.md",
        "article-body.html",
        "article.json",
        "article.md",
        "assets/body-00.png",
        "assets/cover-wide.png",
        "manifest.json",
        "preflight.json",
        "preview.html",
        "review.json",
        "sources.json",
        first.zip_path.name,
    }
    manifest = json.loads(first.manifest_path.read_text(encoding="utf-8"))
    assert manifest["manual_review_status"] == "pending"
    assert manifest["editorially_approved"] is False
    assert manifest["mobile_screenshot_status"] == "not_run"
    assert manifest["media"]["body"]["sha256"] == FIXTURE_IMAGE_SHA256
    assert manifest["media"]["cover"]["sha256"] == FIXTURE_COVER_SHA256
    assert first.zip_path.stat().st_size > 0
    with ZipFile(first.zip_path) as archive:
        assert all(
            not name.startswith("/") and ".." not in name.split("/") for name in archive.namelist()
        )
        assert any(name.endswith("/manifest.json") for name in archive.namelist())
    article_body = (first.bundle_directory / "article-body.html").read_text(encoding="utf-8")
    assert "NOT EDITORIALLY APPROVED" in article_body
    assert "/api/" not in article_body
    assert 'src="assets/body-00.png"' in article_body
    article_markdown = (first.bundle_directory / "article.md").read_text(encoding="utf-8")
    assert "## 给家长的三句话" in article_markdown
    assert "## 资料来源与适用边界" in article_markdown
    assert "> **家庭实践**" in article_markdown
    sources = json.loads((first.bundle_directory / "sources.json").read_text(encoding="utf-8"))
    assert sources["fixture_source_policy"].endswith("wechat-html-renderer-v4")
    assert (first.bundle_directory / "assets/body-00.png").stat().st_size == FIXTURE_IMAGE_BYTE_SIZE
    assert (first.bundle_directory / "assets/cover-wide.png").stat().st_size == (
        FIXTURE_COVER_BYTE_SIZE
    )
    for path in first.bundle_directory.rglob("*"):
        if path.is_file() and path.suffix != ".png":
            assert b"/api/" not in path.read_bytes()


@pytest.mark.asyncio
async def test_multi_image_export_writes_exact_ordered_tree_and_rewrites_every_url(
    tmp_path,
) -> None:
    bundle = await _multi_bundle_input()

    first = export_fixture_review_bundle(bundle, output_directory=tmp_path)
    repeated = export_fixture_review_bundle(bundle, output_directory=tmp_path)

    assert first.reused is False
    assert repeated.reused is True
    files = {
        path.relative_to(first.bundle_directory).as_posix()
        for path in first.bundle_directory.rglob("*")
        if path.is_file()
    }
    assert {f"assets/body-{ordinal:02d}.png" for ordinal in range(3)} <= files
    assert not any(name.startswith("assets/body-03") for name in files)
    manifest = json.loads(first.manifest_path.read_text(encoding="utf-8"))
    assert [item["sha256"] for item in manifest["media"]["body_images"]] == list(
        FIXTURE_BODY_IMAGE_SHA256S
    )
    assert manifest["media"]["body"] == manifest["media"]["body_images"][0]
    article_body = (first.bundle_directory / "article-body.html").read_text(encoding="utf-8")
    assert all(f'src="assets/body-{ordinal:02d}.png"' in article_body for ordinal in range(3))
    assert "/api/" not in article_body
    for ordinal, expected_hash in enumerate(FIXTURE_BODY_IMAGE_SHA256S):
        data = (first.bundle_directory / f"assets/body-{ordinal:02d}.png").read_bytes()
        assert sha256(data).hexdigest() == expected_hash


@pytest.mark.asyncio
async def test_semantic_review_export_uses_jpeg_derivatives_and_stays_non_publishable(
    tmp_path,
) -> None:
    bundle = await _semantic_bundle_input()

    result = export_fixture_review_bundle(bundle, output_directory=tmp_path)

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["bundle_version"] == "official-account-review-bundle-v3-editorial"
    assert manifest["manual_review_status"] == "pending"
    assert manifest["copy_ready"] is False
    assert manifest["blocking_label"] == "NOT READY FOR PUBLICATION"
    assert [item["path"] for item in manifest["media"]["body_images"]] == [
        "assets/body-00.jpg",
        "assets/body-01.jpg",
        "assets/body-02.jpg",
    ]
    assert [item["sha256"] for item in manifest["media"]["body_images"]] == list(
        FIXTURE_BODY_PUBLICATION_SHA256S
    )
    assert all(
        item["media_type"] == FIXTURE_BODY_PUBLICATION_MEDIA_TYPE
        and item["dimensions"] == {"width": 1536, "height": 1024}
        for item in manifest["media"]["body_images"]
    )
    assert manifest["media"]["cover"] == {
        "byte_size": FIXTURE_COVER_PUBLICATION_BYTE_SIZE,
        "dimensions": {"height": 818, "width": 1923},
        "media_type": FIXTURE_COVER_PUBLICATION_MEDIA_TYPE,
        "ordinal": 0,
        "path": "assets/cover-wide.jpg",
        "role": "cover",
        "sha256": FIXTURE_COVER_PUBLICATION_SHA256,
    }
    article_body = (result.bundle_directory / "article-body.html").read_text(encoding="utf-8")
    assert "NOT READY FOR PUBLICATION" in article_body
    assert all(f'src="assets/body-{ordinal:02d}.jpg"' in article_body for ordinal in range(3))


@pytest.mark.asyncio
async def test_multimodal_review_export_binds_safe_selection_snapshot(tmp_path) -> None:
    bundle = await _multimodal_bundle_input()
    assert article_version_bundle_kind(bundle.article.versions) == "v8"

    result = export_fixture_review_bundle(bundle, output_directory=tmp_path)

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["bundle_version"] == "official-account-review-bundle-v4-multimodal-media"
    assert manifest["media_selection"] == bundle.article.media_selection.model_dump(mode="json")
    serialized_manifest = json.dumps(manifest, ensure_ascii=False)
    assert "catalog_asset_id" not in serialized_manifest
    assert "relative_path" not in serialized_manifest
    assert "/root/" not in serialized_manifest
    assert manifest["copy_ready"] is False
    assert manifest["manual_review_status"] == "pending"


@pytest.mark.asyncio
async def test_live_local_export_is_explicitly_distinct_and_remains_review_only(tmp_path) -> None:
    fixture_bundle = await _multimodal_bundle_input()
    source_cover = replace(
        fixture_bundle.cover_media,
        media_type=FIXTURE_COVER_MEDIA_TYPE,
        byte_size=FIXTURE_COVER_BYTE_SIZE,
        sha256=FIXTURE_COVER_SHA256,
    )
    live_bundle = replace(
        fixture_bundle,
        generation_mode="live",
        cover_media=source_cover,
        cover_bytes=fixture_cover_path().read_bytes(),
    )

    with pytest.raises(ValueError, match="fixture simulations"):
        export_fixture_review_bundle(live_bundle, output_directory=tmp_path / "default")

    result = export_live_local_review_bundle(live_bundle, output_directory=tmp_path / "live")

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["bundle_version"] == "official-account-live-local-review-bundle-v1"
    assert manifest["export_scope"] == "live_local"
    assert manifest["local_only"] is True
    assert manifest["published"] is False
    assert manifest["copy_ready"] is False
    assert manifest["manual_review_status"] == "pending"
    assert manifest["blocking_label"] == "LOCAL ONLY · 未同步公众号"
    assert [item["path"] for item in manifest["media"]["body_images"]] == [
        "assets/body-00.jpg",
        "assets/body-01.jpg",
        "assets/body-02.jpg",
    ]
    assert manifest["media"]["cover"]["path"] == "assets/cover-wide.png"
    article_body = (result.bundle_directory / "article-body.html").read_text(encoding="utf-8")
    assert "LOCAL ONLY · 未同步公众号" in article_body
    assert "NOT READY FOR PUBLICATION" not in article_body
    assert all(f'src="assets/body-{ordinal:02d}.jpg"' in article_body for ordinal in range(3))
    assert "/api/" not in article_body
    readme = (result.bundle_directory / "README.md").read_text(encoding="utf-8")
    assert "真实文章本地审阅导出" in readme
    assert "Copy ready: `false`" in readme
    with ZipFile(result.zip_path) as archive:
        assert f"{result.bundle_directory.name}/assets/cover-wide.png" in archive.namelist()

    mismatched_source_cover = replace(live_bundle, cover_bytes=live_bundle.cover_bytes[:-1])
    mismatch_root = tmp_path / "mismatch"
    with pytest.raises(ValueError, match="cover media bytes"):
        export_live_local_review_bundle(mismatched_source_cover, output_directory=mismatch_root)
    assert not mismatch_root.exists()


@pytest.mark.asyncio
async def test_copy_ready_export_requires_approval_and_has_separate_immutable_identity(
    tmp_path,
) -> None:
    pending = await _semantic_bundle_input()
    rejected = replace(
        pending,
        manual_review=StoredOfficialAccountManualReview(
            id=uuid4(),
            run_id=pending.run_id,
            decision="rejected",
            reviewer_label="内容审核",
            note="需要补充来源边界。",
            request_fingerprint="7" * 64,
            reviewed_at=datetime(2026, 8, 23, 9, 0, tzinfo=UTC),
        ),
    )
    approved = replace(
        pending,
        manual_review=StoredOfficialAccountManualReview(
            id=uuid4(),
            run_id=pending.run_id,
            decision="approved",
            reviewer_label="内容审核",
            note="已逐项复核。",
            request_fingerprint="8" * 64,
            reviewed_at=datetime(2026, 8, 23, 9, 30, tzinfo=UTC),
        ),
    )

    with pytest.raises(ValueError, match="approved manual review"):
        export_fixture_review_bundle(pending, output_directory=tmp_path, mode="copy-ready")
    with pytest.raises(ValueError, match="approved manual review"):
        export_fixture_review_bundle(rejected, output_directory=tmp_path, mode="copy-ready")

    review_result = export_fixture_review_bundle(pending, output_directory=tmp_path)
    copy_result = export_fixture_review_bundle(
        approved,
        output_directory=tmp_path,
        mode="copy-ready",
    )
    repeated = export_fixture_review_bundle(
        approved,
        output_directory=tmp_path,
        mode="copy-ready",
    )

    assert review_result.bundle_directory != copy_result.bundle_directory
    assert copy_result.reused is False
    assert repeated.reused is True
    assert copy_result.zip_sha256 == repeated.zip_sha256
    manifest = json.loads(copy_result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["copy_ready"] is True
    assert manifest["editorially_approved"] is True
    assert manifest["manual_review_status"] == "approved"
    assert manifest["fingerprints"]["manual_review"] == "8" * 64
    assert manifest["manual_review"]["reviewer_label"] == "内容审核"
    preflight = json.loads(
        (copy_result.bundle_directory / "preflight.json").read_text(encoding="utf-8")
    )
    manual_record = next(
        item for item in preflight["records"] if item["field"] == "manual_review_status"
    )
    assert manual_record["code"] == "manual_editorial_review_approved"
    assert manual_record["observed"] == "approved"
    assert manual_record["passed"] is True
    article_body = (copy_result.bundle_directory / "article-body.html").read_text(encoding="utf-8")
    assert "NOT READY FOR PUBLICATION" not in article_body
    assert "人工审稿状态" not in article_body


@pytest.mark.asyncio
async def test_export_refuses_mismatched_existing_target_and_media_bytes(tmp_path) -> None:
    bundle = await _bundle_input()
    result = export_fixture_review_bundle(bundle, output_directory=tmp_path)
    (result.bundle_directory / "README.md").write_text("tampered", encoding="utf-8")

    with pytest.raises(FileExistsError, match="different or incomplete"):
        export_fixture_review_bundle(bundle, output_directory=tmp_path)

    invalid = replace(bundle, cover_bytes=bundle.cover_bytes[:-1])
    with pytest.raises(ValueError, match="cover media bytes"):
        export_fixture_review_bundle(invalid, output_directory=tmp_path / "other")

    extra_result = export_fixture_review_bundle(bundle, output_directory=tmp_path / "extra")
    (extra_result.bundle_directory / "unexpected.txt").write_text("extra", encoding="utf-8")
    with pytest.raises(FileExistsError, match="different or incomplete"):
        export_fixture_review_bundle(bundle, output_directory=tmp_path / "extra")

    wrong_fingerprint = replace(bundle, resolved_fingerprint="0" * 64)
    with pytest.raises(ValueError, match="immutable lineage"):
        export_fixture_review_bundle(wrong_fingerprint, output_directory=tmp_path / "fingerprint")


@pytest.mark.asyncio
async def test_export_rejects_mixed_versions_and_media_type_signature_drift(tmp_path) -> None:
    bundle = await _semantic_bundle_input()
    mixed_versions = bundle.article.versions.model_copy(
        update={"article_schema_version": "official-account-article-schema-unknown"}
    )
    mixed_article = bundle.article.model_copy(update={"versions": mixed_versions})
    with pytest.raises(ValueError, match="version identity is unsupported"):
        export_fixture_review_bundle(
            replace(bundle, article=mixed_article),
            output_directory=tmp_path / "mixed",
        )

    wrong_body = replace(bundle.body_media, media_type="image/png")
    wrong_items = (wrong_body, *bundle.body_media_items[1:])
    with pytest.raises(ValueError, match="media type does not match"):
        export_fixture_review_bundle(
            replace(bundle, body_media=wrong_body, body_media_items=wrong_items),
            output_directory=tmp_path / "media-type",
        )


def test_fixture_cover_metadata_matches_generated_asset() -> None:
    cover = fixture_cover_path().read_bytes()

    assert len(cover) == FIXTURE_COVER_BYTE_SIZE
    assert sha256(cover).hexdigest() == FIXTURE_COVER_SHA256
    assert FIXTURE_COVER_MEDIA_TYPE == "image/png"


def test_publication_derivatives_are_pinned_smaller_and_metadata_stripped() -> None:
    for ordinal, (derivative_hash, derivative_size, master_size) in enumerate(
        zip(
            FIXTURE_BODY_PUBLICATION_SHA256S,
            FIXTURE_BODY_PUBLICATION_BYTE_SIZES,
            FIXTURE_BODY_IMAGE_BYTE_SIZES,
            strict=True,
        )
    ):
        path = fixture_body_publication_path(ordinal)
        body = path.read_bytes()
        assert len(body) == derivative_size < master_size
        assert sha256(body).hexdigest() == derivative_hash
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            assert image.size == (1536, 1024)
            assert set(image.info) <= {"jfif", "jfif_density", "jfif_unit", "jfif_version"}
            assert image.getexif() == {}

    cover = fixture_cover_publication_path()
    cover_body = cover.read_bytes()
    assert len(cover_body) == FIXTURE_COVER_PUBLICATION_BYTE_SIZE < FIXTURE_COVER_BYTE_SIZE
    assert sha256(cover_body).hexdigest() == FIXTURE_COVER_PUBLICATION_SHA256
    with Image.open(cover) as image:
        image.verify()
    with Image.open(cover) as image:
        assert image.size == (1923, 818)
        assert set(image.info) <= {"jfif", "jfif_density", "jfif_unit", "jfif_version"}
        assert image.getexif() == {}


@pytest.mark.asyncio
async def test_legacy_adapter_keeps_historical_fixture_cover_bytes() -> None:
    adapter = LocalOfficialAccountMediaAdapter()
    legacy_cover = await adapter.stage(
        OfficialAccountMediaRequest(
            run_id=uuid4(),
            render_version_id=uuid4(),
            source_image_artifact_id=None,
            fixture_id="official-account-article-v1",
            role="cover",
            ordinal=0,
            source_sha256=FIXTURE_IMAGE_SHA256,
            media_type=FIXTURE_IMAGE_MEDIA_TYPE,
            byte_size=FIXTURE_IMAGE_BYTE_SIZE,
            local_adapter_version=OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V1_VERSION,
            request_fingerprint="5" * 64,
        )
    )

    assert legacy_cover.sha256 == FIXTURE_IMAGE_SHA256
    assert legacy_cover.byte_size == FIXTURE_IMAGE_BYTE_SIZE


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "adapter_version",
    [OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V1_VERSION, OFFICIAL_ACCOUNT_LOCAL_ADAPTER_VERSION],
)
async def test_material_cover_bytes_are_unchanged_across_local_adapter_versions(
    adapter_version: str,
) -> None:
    adapter = LocalOfficialAccountMediaAdapter()
    material_cover = await adapter.stage(
        OfficialAccountMediaRequest(
            run_id=uuid4(),
            render_version_id=uuid4(),
            source_image_artifact_id=uuid4(),
            fixture_id=None,
            role="cover",
            ordinal=0,
            source_sha256="a" * 64,
            media_type="image/webp",
            byte_size=12_345,
            local_adapter_version=adapter_version,
            request_fingerprint="6" * 64,
        )
    )

    assert material_cover.sha256 == "a" * 64
    assert material_cover.media_type == "image/webp"
    assert material_cover.byte_size == 12_345
