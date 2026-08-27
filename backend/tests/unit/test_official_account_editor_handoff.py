from __future__ import annotations

import json
from datetime import UTC, datetime
from io import BytesIO
from types import SimpleNamespace
from typing import Any, Literal, cast
from unittest.mock import AsyncMock
from uuid import UUID
from zipfile import ZipFile

import pytest
from app.application.ports.official_account_local import (
    OfficialAccountMediaResult,
    StoredOfficialAccountManualReview,
)
from app.application.services.official_account_editor_handoff import (
    OfficialAccountEditorHandoffService,
    _build_artifact,
)
from app.application.services.official_account_local import manual_review_request_fingerprint
from app.domain.official_account_editor_handoff import (
    EditorHandoffMediaAsset,
    media_asset_path,
    render_editor_handoff_body,
    run_editor_handoff_preflight,
)
from app.domain.official_account_local import fingerprint, render_wechat_html
from app.infrastructure.official_account_local import (
    FIXTURE_BODY_ALT_TEXTS,
    FIXTURE_BODY_CAPTIONS,
    FIXTURE_BODY_PUBLICATION_BYTE_SIZES,
    FIXTURE_BODY_PUBLICATION_MEDIA_TYPE,
    FIXTURE_BODY_PUBLICATION_SHA256S,
    FIXTURE_COVER_PUBLICATION_BYTE_SIZE,
    FIXTURE_COVER_PUBLICATION_MEDIA_TYPE,
    FIXTURE_COVER_PUBLICATION_SHA256,
    fixture_media_path,
)
from PIL import Image
from tests.unit.test_official_account_article import fixture_article


async def _artifact():
    _source, _identity, article = await fixture_article()
    media: list[tuple[OfficialAccountMediaResult, bytes]] = []
    section_indexes = tuple(
        section_index
        for section_index, section in enumerate(article.sections)
        for block in section.blocks
        if block.kind == "image"
    )
    for ordinal, (checksum, byte_size) in enumerate(
        zip(
            FIXTURE_BODY_PUBLICATION_SHA256S,
            FIXTURE_BODY_PUBLICATION_BYTE_SIZES,
            strict=True,
        )
    ):
        body = fixture_media_path(role="body", checksum=checksum).read_bytes()
        media.append(
            (
                OfficialAccountMediaResult(
                    local_media_id=f"local-body-{ordinal}",
                    role="body",
                    ordinal=ordinal,
                    media_url=f"/api/v1/official-account-local/media/local-body-{ordinal}",
                    media_type=FIXTURE_BODY_PUBLICATION_MEDIA_TYPE,
                    byte_size=byte_size,
                    sha256=checksum,
                    alt_text=FIXTURE_BODY_ALT_TEXTS[ordinal],
                    caption=FIXTURE_BODY_CAPTIONS[ordinal],
                    assigned_section_index=section_indexes[ordinal],
                    provenance_kind="fixture",
                ),
                body,
            )
        )
    cover = fixture_media_path(role="cover", checksum=FIXTURE_COVER_PUBLICATION_SHA256).read_bytes()
    assert len(cover) == FIXTURE_COVER_PUBLICATION_BYTE_SIZE
    media.append(
        (
            OfficialAccountMediaResult(
                local_media_id="local-cover-0",
                role="cover",
                ordinal=0,
                media_url="/api/v1/official-account-local/media/local-cover-0",
                media_type=FIXTURE_COVER_PUBLICATION_MEDIA_TYPE,
                byte_size=len(cover),
                sha256=FIXTURE_COVER_PUBLICATION_SHA256,
                provenance_kind="fixture",
            ),
            cover,
        )
    )
    review = StoredOfficialAccountManualReview(
        id=UUID("22222222-2222-4222-8222-222222222222"),
        run_id=UUID("11111111-1111-4111-8111-111111111111"),
        decision="approved",
        reviewer_label="内容审核",
        note="已逐项复核。",
        request_fingerprint=manual_review_request_fingerprint(
            run_id=UUID("11111111-1111-4111-8111-111111111111"),
            decision="approved",
            reviewer_label="内容审核",
            note="已逐项复核。",
        ),
        reviewed_at=datetime(2026, 8, 27, 9, 0, tzinfo=UTC),
    )
    return _build_artifact(
        run_id=review.run_id,
        run_request_fingerprint="a" * 64,
        article=article,
        review=review,
        draft_resolved_fingerprint="d" * 64,
        media=tuple(media),
        eligibility_checks=(),
    )


@pytest.mark.asyncio
async def test_editor_handoff_is_gzh_compatible_deterministic_and_safe() -> None:
    artifact = await _artifact()
    repeated = await _artifact()

    body = artifact.body_html.decode("utf-8")
    assert body.startswith("<section ")
    assert body.endswith("</section>")
    assert "<html" not in body
    assert "<script" not in body
    assert "<style" not in body
    assert "<button" not in body
    assert "<div" not in body
    assert '<span leaf="">' in body
    assert "/api/" not in body
    assert "assets/body-00.jpg" in body
    assert artifact.preflight.passed is True
    assert artifact.preflight.blocking_codes == ()
    assert artifact.preflight.warning_codes == ("mobile_browser_validation_not_run",)
    assert artifact.fingerprint == repeated.fingerprint
    assert artifact.body_html == repeated.body_html
    assert artifact.zip_bytes == repeated.zip_bytes
    assert artifact.zip_sha256 == repeated.zip_sha256

    manifest = json.loads(artifact.files["manifest.json"])
    assert manifest["published"] is False
    assert manifest["copy_ready"] is True
    assert manifest["identity"]["renderer_version"].endswith("gzh-xiaosai")
    assert all(not item["path"].startswith("/") for item in manifest["files"])
    with ZipFile(BytesIO(artifact.zip_bytes)) as archive:
        assert archive.testzip() is None
        assert all(".." not in name.split("/") for name in archive.namelist())
        assert all(not name.startswith("/") for name in archive.namelist())


@pytest.mark.asyncio
async def test_unverified_context_image_is_retained_as_nonblocking_warning() -> None:
    base = await _artifact()
    _source, _identity, article = await fixture_article()
    sample = next(item for item in base.media if item.role == "body")
    context = EditorHandoffMediaAsset(
        path=media_asset_path("context", 0, sample.media_type),
        role="context",
        ordinal=0,
        media_type=sample.media_type,
        byte_size=sample.byte_size,
        sha256="f" * 64,
        width=sample.width,
        height=sample.height,
        alt_text="新闻现场上下文图片",
        assigned_section_index=0,
        source_page_url="https://example.com/news",
        credit="权威新闻来源",
        rights_status="publish_permission_unverified",
        context_only_not_evidence=True,
    )
    media = (*base.media, context)
    rendered = render_editor_handoff_body(article=article, media=media)
    preview = f'<main id="copy-root">{rendered.body_html}</main>'
    report = run_editor_handoff_preflight(
        body_html=rendered.body_html,
        preview_html=preview,
        media=media,
        approved=True,
    )

    assert report.passed is True
    assert "assets/context-00.jpg" in rendered.body_html
    assert "发布权未验证" in rendered.body_html
    assert "context_image_rights_unverified_direct_use" in report.warning_codes
    assert "context_image_rights_unverified_direct_use" not in report.blocking_codes


@pytest.mark.asyncio
async def test_direct_use_context_is_preserved_in_the_bundle_without_relabeling() -> None:
    from tests.unit.test_official_account_export import _news_context_bundle_input

    bundle = await _news_context_bundle_input()
    review = StoredOfficialAccountManualReview(
        id=UUID("22222222-2222-4222-8222-222222222222"),
        run_id=bundle.run_id,
        decision="approved",
        reviewer_label="内容审核",
        note="已逐项复核。",
        request_fingerprint="e" * 64,
        reviewed_at=datetime(2026, 8, 27, 9, 0, tzinfo=UTC),
    )
    artifact = _build_artifact(
        run_id=bundle.run_id,
        run_request_fingerprint=bundle.request_fingerprint,
        article=bundle.article,
        review=review,
        draft_resolved_fingerprint=bundle.resolved_fingerprint,
        media=tuple(
            zip(
                (*bundle.body_media_items, *bundle.context_media_items, bundle.cover_media),
                (*bundle.body_bytes_items, *bundle.context_bytes_items, bundle.cover_bytes),
                strict=True,
            )
        ),
        eligibility_checks=(),
    )

    rights = json.loads(artifact.files["rights.json"])
    context = next(item for item in artifact.media if item.role == "context")
    assert artifact.preflight.passed is True
    assert "context_image_rights_unverified_direct_use" in artifact.preflight.warning_codes
    assert context.rights_status == "publish_permission_unverified"
    assert context.context_only_not_evidence is True
    assert context.source_page_url == bundle.context_media_items[0].source_page_url
    assert rights["items"][0]["rights_status"] == "publish_permission_unverified"
    assert "licensed" not in artifact.files["rights.json"].decode("utf-8").lower()
    assert "assets/context-00.png" in artifact.body_html.decode("utf-8")


@pytest.mark.asyncio
async def test_preview_body_tampering_fails_closed() -> None:
    artifact = await _artifact()
    body = artifact.body_html.decode("utf-8")
    report = run_editor_handoff_preflight(
        body_html=body,
        preview_html=f'<main id="copy-root">{body}tampered</main>',
        media=artifact.media,
        approved=True,
    )

    assert report.passed is False
    assert "preview_body_exact_match" in report.blocking_codes


@pytest.mark.asyncio
async def test_preflight_rejects_multiple_roots_duplicate_images_and_nonallowlisted_css() -> None:
    artifact = await _artifact()
    body = artifact.body_html.decode("utf-8")
    first_image = next(item for item in artifact.media if item.role == "body")
    duplicate_image = (
        f'<img src="{first_image.path}" alt="重复图片" '
        'style="max-width:100%;height:auto;display:block;margin:0 auto;">'
    )
    duplicate_body = body.removesuffix("</section>") + duplicate_image + "</section>"
    duplicate_report = run_editor_handoff_preflight(
        body_html=duplicate_body,
        preview_html=f'<main id="copy-root">{duplicate_body}</main>',
        media=artifact.media,
        approved=True,
    )
    assert "controlled_relative_images" in duplicate_report.blocking_codes

    extra_root = body + '<section style="margin:0;"><span leaf="">额外根</span></section>'
    root_report = run_editor_handoff_preflight(
        body_html=extra_root,
        preview_html=f'<main id="copy-root">{extra_root}</main>',
        media=artifact.media,
        approved=True,
    )
    assert "pure_section_fragment" in root_report.blocking_codes

    unsafe_style = body.replace("max-width:677px;", "cursor:pointer;max-width:677px;", 1)
    style_report = run_editor_handoff_preflight(
        body_html=unsafe_style,
        preview_html=f'<main id="copy-root">{unsafe_style}</main>',
        media=artifact.media,
        approved=True,
    )
    assert "wechat_markup_allowlist" in style_report.blocking_codes


def test_renderer_escapes_dangerous_article_text() -> None:
    async def render() -> str:
        _source, _identity, article = await fixture_article()
        first = article.sections[0]
        paragraph = first.blocks[0].model_copy(update={"text": '<script>alert("x")</script>'})
        changed = article.model_copy(
            update={
                "sections": (
                    first.model_copy(update={"blocks": (paragraph, *first.blocks[1:])}),
                    *article.sections[1:],
                )
            }
        )
        assets = []
        for ordinal, (checksum, byte_size) in enumerate(
            zip(
                FIXTURE_BODY_PUBLICATION_SHA256S,
                FIXTURE_BODY_PUBLICATION_BYTE_SIZES,
                strict=True,
            )
        ):
            body = fixture_media_path(role="body", checksum=checksum).read_bytes()
            with Image.open(BytesIO(body)) as image:
                width, height = image.size
            assets.append(
                EditorHandoffMediaAsset(
                    path=media_asset_path("body", ordinal, "image/jpeg"),
                    role="body",
                    ordinal=ordinal,
                    media_type="image/jpeg",
                    byte_size=byte_size,
                    sha256=checksum,
                    width=width,
                    height=height,
                    alt_text="正文配图",
                )
            )
        return render_editor_handoff_body(article=changed, media=tuple(assets)).body_html

    import asyncio

    body = asyncio.run(render())
    assert "<script>" not in body
    assert "&lt;" in body
    assert "&gt;" in body


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("run_status", "review_decision", "expected_code"),
    [
        ("failed", "approved", "run_ready"),
        ("result_unknown", "approved", "run_ready"),
        ("ready", None, "immutable_review_pending"),
        ("ready", "rejected", "immutable_review_rejected"),
    ],
)
async def test_service_blocks_nonapproved_or_nonready_state_before_media_access(
    run_status: str,
    review_decision: str | None,
    expected_code: str,
) -> None:
    _source, _identity, article = await fixture_article()
    run_id = UUID("11111111-1111-4111-8111-111111111111")
    article_id = UUID("33333333-3333-4333-8333-333333333333")
    rendered = render_wechat_html(article)
    render_fingerprint = rendered.render_fingerprint
    draft_request_fingerprint = "c" * 64
    resolved_html = "<section>immutable draft</section>"
    review = None
    if review_decision is not None:
        review = StoredOfficialAccountManualReview(
            id=UUID("22222222-2222-4222-8222-222222222222"),
            run_id=run_id,
            decision=cast(Literal["approved", "rejected"], review_decision),
            reviewer_label="内容审核",
            note="已逐项复核。",
            request_fingerprint=manual_review_request_fingerprint(
                run_id=run_id,
                decision=cast(Literal["approved", "rejected"], review_decision),
                reviewer_label="内容审核",
                note="已逐项复核。",
            ),
            reviewed_at=datetime(2026, 8, 27, 9, 0, tzinfo=UTC),
        )
    repository = SimpleNamespace(
        get_run=AsyncMock(
            return_value=SimpleNamespace(status=run_status, request_fingerprint="a" * 64)
        ),
        get_article=AsyncMock(
            return_value=SimpleNamespace(
                id=article_id,
                article=article,
                validation_passed=True,
                audit=SimpleNamespace(accepted=True),
            )
        ),
        get_render=AsyncMock(
            return_value=SimpleNamespace(
                article_version_id=article_id,
                canonical_html=rendered.canonical_html,
                render_fingerprint=render_fingerprint,
            )
        ),
        get_draft=AsyncMock(
            return_value=SimpleNamespace(
                state="ready",
                simulation=True,
                request_fingerprint=draft_request_fingerprint,
                resolved_html=resolved_html,
                resolved_fingerprint=fingerprint(
                    render_fingerprint,
                    draft_request_fingerprint,
                    resolved_html,
                ),
            )
        ),
        get_manual_review=AsyncMock(return_value=review),
    )
    service = OfficialAccountEditorHandoffService(
        session_factory=cast(Any, object()),
        resolver=cast(Any, object()),
    )
    service._repository = cast(Any, repository)
    service._load_media_rows = AsyncMock(side_effect=AssertionError("media must not be read"))

    inspection = await service.inspect(run_id)

    assert inspection.state == "blocked"
    assert expected_code in inspection.blocking_codes
    service._load_media_rows.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tamper", "expected_code"),
    [
        ("draft", "draft_fingerprint_valid"),
        ("review", "review_fingerprint_valid"),
        ("render_lineage", "render_article_lineage_valid"),
        ("render_fingerprint", "render_fingerprint_valid"),
    ],
)
async def test_service_fails_closed_on_immutable_lineage_tampering(
    tamper: str,
    expected_code: str,
) -> None:
    _source, _identity, article = await fixture_article()
    run_id = UUID("11111111-1111-4111-8111-111111111111")
    article_id = UUID("33333333-3333-4333-8333-333333333333")
    rendered = render_wechat_html(article)
    render_fingerprint = rendered.render_fingerprint
    draft_request_fingerprint = "c" * 64
    resolved_html = "<section>immutable draft</section>"
    review_fingerprint = manual_review_request_fingerprint(
        run_id=run_id,
        decision="approved",
        reviewer_label="内容审核",
        note="已逐项复核。",
    )
    repository = SimpleNamespace(
        get_run=AsyncMock(
            return_value=SimpleNamespace(status="ready", request_fingerprint="a" * 64)
        ),
        get_article=AsyncMock(
            return_value=SimpleNamespace(
                id=article_id,
                article=article,
                validation_passed=True,
                audit=SimpleNamespace(accepted=True),
            )
        ),
        get_render=AsyncMock(
            return_value=SimpleNamespace(
                article_version_id=(
                    UUID("44444444-4444-4444-8444-444444444444")
                    if tamper == "render_lineage"
                    else article_id
                ),
                canonical_html=(
                    rendered.canonical_html + "tampered"
                    if tamper == "render_fingerprint"
                    else rendered.canonical_html
                ),
                render_fingerprint=render_fingerprint,
            )
        ),
        get_draft=AsyncMock(
            return_value=SimpleNamespace(
                state="ready",
                simulation=True,
                request_fingerprint=draft_request_fingerprint,
                resolved_html=resolved_html,
                resolved_fingerprint=(
                    "0" * 64
                    if tamper == "draft"
                    else fingerprint(render_fingerprint, draft_request_fingerprint, resolved_html)
                ),
            )
        ),
        get_manual_review=AsyncMock(
            return_value=StoredOfficialAccountManualReview(
                id=UUID("22222222-2222-4222-8222-222222222222"),
                run_id=run_id,
                decision="approved",
                reviewer_label="内容审核",
                note="已逐项复核。",
                request_fingerprint="0" * 64 if tamper == "review" else review_fingerprint,
                reviewed_at=datetime(2026, 8, 27, 9, 0, tzinfo=UTC),
            )
        ),
    )
    service = OfficialAccountEditorHandoffService(
        session_factory=cast(Any, object()),
        resolver=cast(Any, object()),
    )
    service._repository = cast(Any, repository)
    service._load_media_rows = AsyncMock(side_effect=AssertionError("media must not be read"))

    inspection = await service.inspect(run_id)

    assert inspection.state == "blocked"
    assert expected_code in inspection.blocking_codes
    service._load_media_rows.assert_not_awaited()
