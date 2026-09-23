from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from io import BytesIO
from pathlib import Path

import pytest
from app.application.ports.wechat_official_account import (
    WECHAT_MP_MAX_INLINE_IMAGE_BYTES,
    WECHAT_MP_MAX_THUMB_BYTES,
    WeChatDraftArticleRequest,
    WeChatDraftCreated,
    WeChatInlineImage,
    WeChatMpDraftPreparationError,
    WeChatThumbMedia,
)
from app.application.services.official_account_editor_handoff_v2 import (
    write_editor_handoff_v2_artifact,
)
from app.application.services.wechat_official_account_draft import (
    WeChatDraftLocalSource,
    WeChatOfficialAccountDraftOnlyService,
    WeChatOfficialAccountDraftPreparer,
    WeChatPreparedDraft,
    WeChatPreparedMedia,
    _DraftHtmlValidator,
    _hide_generated_context_rights_notice,
    _normalize_inline_image,
)
from app.domain.official_account_editor_handoff import (
    CONTEXT_RIGHTS_NOTICE_TEXT,
    EditorHandoffMediaAsset,
    _image,
)
from app.domain.official_account_strict_layout import (
    STRICT_LAYOUT_PROJECTION_V2_VERSION,
    compact_strict_xiaosai_html,
)
from app.domain.official_account_weekly_edition import WEEKLY_EDITION_ROLE_ORDER
from app.official_account_weekly_edition_demo import (
    build_fixture_children,
    fixture_mobile_validation,
)
from PIL import Image


class _FakeDraftClient:
    def __init__(self) -> None:
        self.inline_uploads: list[tuple[bytes, str, str]] = []
        self.thumb_uploads: list[tuple[bytes, str, str]] = []
        self.drafts: list[WeChatDraftArticleRequest] = []

    async def upload_inline_image(
        self,
        image_bytes: bytes,
        media_type: str,
        filename: str,
    ) -> WeChatInlineImage:
        self.inline_uploads.append((image_bytes, media_type, filename))
        ordinal = len(self.inline_uploads)
        return WeChatInlineImage(url=f"https://mmbiz.qpic.cn/body-{ordinal}.jpg?a=1&b=2")

    async def upload_thumb(
        self,
        image_bytes: bytes,
        media_type: str,
        filename: str,
    ) -> WeChatThumbMedia:
        self.thumb_uploads.append((image_bytes, media_type, filename))
        return WeChatThumbMedia(media_id=f"thumb-{len(self.thumb_uploads)}")

    async def add_draft(self, article: WeChatDraftArticleRequest) -> WeChatDraftCreated:
        self.drafts.append(article)
        return WeChatDraftCreated(media_id=f"draft-{len(self.drafts)}")


def _context_html(ordinal: int) -> str:
    body = b"test-context-image"
    asset = EditorHandoffMediaAsset(
        path=f"assets/context-{ordinal:02d}.jpg",
        role="context",
        ordinal=ordinal,
        media_type="image/jpeg",
        byte_size=len(body),
        sha256=sha256(body).hexdigest(),
        width=100,
        height=100,
        alt_text=f"新闻配图 {ordinal}",
        assigned_section_index=ordinal,
        source_page_url="https://example.org/source",
        caption=f"新闻图片说明 {ordinal}",
        credit="来源署名",
        rights_status="publish_permission_unverified",
        context_only_not_evidence=True,
    )
    return _image(asset, disclose_rights=True)


@pytest.mark.parametrize("compact_v2", [False, True])
def test_wechat_display_omits_only_generated_context_notice(compact_v2: bool) -> None:
    authored = f'<p style="margin:0"><span leaf="">{CONTEXT_RIGHTS_NOTICE_TEXT}</span></p>'
    html = authored + _context_html(0) + _context_html(1)
    if compact_v2:
        html = compact_strict_xiaosai_html(html, version=STRICT_LAYOUT_PROJECTION_V2_VERSION)
    assert html.count(CONTEXT_RIGHTS_NOTICE_TEXT) == 3

    displayed = _hide_generated_context_rights_notice(html)

    assert displayed.count(CONTEXT_RIGHTS_NOTICE_TEXT) == 1
    assert "新闻图片说明 0" in displayed and "新闻图片说明 1" in displayed
    assert displayed.count("来源署名") == 2
    assert displayed.count("<img ") == 2
    assert _hide_generated_context_rights_notice(displayed) == displayed


def test_wechat_display_recognizes_compacted_leaf_and_reordered_notice_style() -> None:
    html = (
        _context_html(0)
        .replace(
            "font-size:11px;color:#B85A00;line-height:1.7;margin:6px 0 0;",
            "margin:6px 0 0;color:#B85A00",
        )
        .replace('<span leaf="">', "<span leaf>")
    )

    displayed = _hide_generated_context_rights_notice(html)

    assert CONTEXT_RIGHTS_NOTICE_TEXT not in displayed
    assert "新闻图片说明 0" in displayed
    assert "来源署名" in displayed
    assert displayed.count("<img ") == 1


@pytest.mark.asyncio
async def test_draft_submission_omits_notice_without_mutating_prepared_artifact() -> None:
    original_html = _context_html(0) + _context_html(1)
    prepared = WeChatPreparedDraft(
        role="official_anchor",
        article_fingerprint="a" * 64,
        content_fingerprint="b" * 64,
        title="测试文章",
        author="程岳",
        digest="摘要",
        content_source_url=None,
        body_html=original_html,
        body_media=tuple(
            WeChatPreparedMedia(
                path=f"assets/context-{ordinal:02d}.jpg",
                media_type="image/jpeg",
                body=b"test-context-image",
                upload_filename=f"context-{ordinal:02d}.jpg",
            )
            for ordinal in range(2)
        ),
        cover=WeChatPreparedMedia(
            path="assets/cover-wide.jpg",
            media_type="image/jpeg",
            body=b"test-cover",
            upload_filename="cover-thumb.jpg",
        ),
        need_open_comment=False,
        only_fans_can_comment=False,
    )
    fake = _FakeDraftClient()
    service = WeChatOfficialAccountDraftOnlyService(client=fake)

    receipt = await service.create_prepared(prepared)

    assert receipt.not_published is True
    assert prepared.body_html == original_html
    assert original_html.count(CONTEXT_RIGHTS_NOTICE_TEXT) == 2
    assert CONTEXT_RIGHTS_NOTICE_TEXT not in fake.drafts[0].content
    assert fake.drafts[0].content.count("来源署名") == 2
    assert fake.drafts[0].content.count("https://mmbiz.qpic.cn/") == 2
    assert len(fake.inline_uploads) == 2


async def _finalized_directories(tmp_path: Path) -> tuple[Path, Path, Path]:
    staged = await build_fixture_children()
    reports = {
        role: fixture_mobile_validation(artifact)
        for role, artifact in zip(WEEKLY_EDITION_ROLE_ORDER, staged, strict=True)
    }
    finalized = await build_fixture_children(browser_validations=reports)
    paths = tuple(
        write_editor_handoff_v2_artifact(artifact, tmp_path / role)
        for role, artifact in zip(WEEKLY_EDITION_ROLE_ORDER, finalized, strict=True)
    )
    return paths  # type: ignore[return-value]


@pytest.mark.asyncio
async def test_weekly_service_prepares_all_local_media_then_creates_independent_drafts(
    tmp_path: Path,
) -> None:
    paths = await _finalized_directories(tmp_path)
    fake = _FakeDraftClient()
    created_at = datetime(2026, 8, 31, 9, tzinfo=UTC)
    service = WeChatOfficialAccountDraftOnlyService(client=fake, clock=lambda: created_at)
    sources = tuple(
        WeChatDraftLocalSource(directory=path, role=role)
        for path, role in zip(paths, WEEKLY_EDITION_ROLE_ORDER, strict=True)
    )
    assert all(
        next(path.glob("assets/cover-wide.*")).stat().st_size > WECHAT_MP_MAX_THUMB_BYTES
        for path in paths
    )
    original_files = {
        path: sha256(path.read_bytes()).hexdigest()
        for directory in paths
        for path in directory.rglob("*")
        if path.is_file()
    }

    receipts = await service.create_weekly_drafts(sources)  # type: ignore[arg-type]

    assert [receipt.role for receipt in receipts] == list(WEEKLY_EDITION_ROLE_ORDER)
    assert [receipt.draft_media_id for receipt in receipts] == [
        "draft-1",
        "draft-2",
        "draft-3",
    ]
    assert all(receipt.not_published is True for receipt in receipts)
    assert all(receipt.created_at == created_at for receipt in receipts)
    assert len(fake.drafts) == 3
    assert len(fake.thumb_uploads) == 3
    assert len({draft.title for draft in fake.drafts}) == 3
    assert all("assets/" not in draft.content for draft in fake.drafts)
    assert all("https://mmbiz.qpic.cn/" in draft.content for draft in fake.drafts)
    assert all("&amp;b=2" in draft.content for draft in fake.drafts)
    assert all(
        len(body) <= WECHAT_MP_MAX_INLINE_IMAGE_BYTES for body, _type, _name in fake.inline_uploads
    )
    assert all(
        media_type == "image/jpeg"
        and filename == "cover-thumb.jpg"
        and len(body) <= WECHAT_MP_MAX_THUMB_BYTES
        for body, media_type, filename in fake.thumb_uploads
    )
    for body, _media_type, _filename in fake.thumb_uploads:
        with Image.open(BytesIO(body)) as opened:
            opened.load()
            assert opened.format == "JPEG"
            assert opened.width * 20 == opened.height * 47
            assert not opened.getexif()
            assert "comment" not in opened.info
    assert {
        path: sha256(path.read_bytes()).hexdigest() for path in original_files
    } == original_files


@pytest.mark.asyncio
async def test_pure_preparer_validates_all_three_without_constructing_a_client(
    tmp_path: Path,
) -> None:
    paths = await _finalized_directories(tmp_path)
    sources = tuple(
        WeChatDraftLocalSource(directory=path, role=role)
        for path, role in zip(paths, WEEKLY_EDITION_ROLE_ORDER, strict=True)
    )

    prepared = WeChatOfficialAccountDraftPreparer().prepare_weekly(sources)  # type: ignore[arg-type]

    assert [item.role for item in prepared] == list(WEEKLY_EDITION_ROLE_ORDER)
    assert len({item.article_fingerprint for item in prepared}) == 3
    assert len({item.content_fingerprint for item in prepared}) == 3


@pytest.mark.asyncio
async def test_third_child_tamper_blocks_every_weekly_provider_call(tmp_path: Path) -> None:
    paths = await _finalized_directories(tmp_path)
    tampered = paths[2] / "assets/body-00.jpg"
    tampered.write_bytes(tampered.read_bytes() + b"tamper")
    fake = _FakeDraftClient()
    service = WeChatOfficialAccountDraftOnlyService(client=fake)
    sources = tuple(
        WeChatDraftLocalSource(directory=path, role=role)
        for path, role in zip(paths, WEEKLY_EDITION_ROLE_ORDER, strict=True)
    )

    with pytest.raises(WeChatMpDraftPreparationError):
        await service.create_weekly_drafts(sources)  # type: ignore[arg-type]

    assert fake.inline_uploads == []
    assert fake.thumb_uploads == []
    assert fake.drafts == []


@pytest.mark.asyncio
async def test_symlinked_media_blocks_before_provider_call(tmp_path: Path) -> None:
    paths = await _finalized_directories(tmp_path)
    target = paths[0] / "assets/body-00.jpg"
    backup = tmp_path / "body-backup.jpg"
    backup.write_bytes(target.read_bytes())
    target.unlink()
    target.symlink_to(backup)
    fake = _FakeDraftClient()
    service = WeChatOfficialAccountDraftOnlyService(client=fake)

    with pytest.raises(WeChatMpDraftPreparationError):
        await service.create_draft(
            WeChatDraftLocalSource(
                directory=paths[0],
                role=WEEKLY_EDITION_ROLE_ORDER[0],
            )
        )

    assert fake.inline_uploads == []
    assert fake.thumb_uploads == []
    assert fake.drafts == []


@pytest.mark.asyncio
async def test_naive_receipt_clock_blocks_before_provider_call(tmp_path: Path) -> None:
    paths = await _finalized_directories(tmp_path)
    fake = _FakeDraftClient()
    service = WeChatOfficialAccountDraftOnlyService(
        client=fake,
        clock=lambda: datetime(2026, 8, 31, 9),
    )

    with pytest.raises(WeChatMpDraftPreparationError):
        await service.create_draft(
            WeChatDraftLocalSource(
                directory=paths[0],
                role=WEEKLY_EDITION_ROLE_ORDER[0],
            )
        )

    assert fake.inline_uploads == []
    assert fake.thumb_uploads == []
    assert fake.drafts == []


@pytest.mark.asyncio
async def test_corrupt_child_zip_is_a_typed_preflight_failure(tmp_path: Path) -> None:
    paths = await _finalized_directories(tmp_path)
    child_zip = next(paths[0].glob("wechat-editor-handoff-v2-*.zip"))
    child_zip.write_bytes(b"not-a-zip")
    fake = _FakeDraftClient()
    service = WeChatOfficialAccountDraftOnlyService(client=fake)

    with pytest.raises(WeChatMpDraftPreparationError):
        await service.create_draft(
            WeChatDraftLocalSource(
                directory=paths[0],
                role=WEEKLY_EDITION_ROLE_ORDER[0],
            )
        )

    assert fake.inline_uploads == []
    assert fake.thumb_uploads == []
    assert fake.drafts == []


def test_html_validator_rejects_external_data_duplicate_and_non_allowlisted_images() -> None:
    invalid_documents = (
        (
            '<section style="margin:0"><img src="https://example.com/a.jpg" '
            'alt="a" style="width:100%"></section>'
        ),
        (
            '<section style="margin:0"><img src="data:image/png;base64,AA" '
            'alt="a" style="width:100%"></section>'
        ),
        (
            '<section style="margin:0"><img src="assets/body-00.jpg" '
            'src="assets/body-01.jpg" alt="a" style="width:100%"></section>'
        ),
        (
            '<section style="background:url(https://example.com/a.jpg)">'
            '<img src="assets/body-00.jpg" alt="a" style="width:100%"></section>'
        ),
        '<script><img src="assets/body-00.jpg" alt="a"></script>',
    )
    for document in invalid_documents:
        validator = _DraftHtmlValidator()
        validator.feed(document)
        validator.close()
        with pytest.raises(ValueError, match="allowlist"):
            validator.finish()


def test_oversized_inline_png_is_deterministically_normalized_without_crop() -> None:
    image = Image.effect_noise((1400, 900), 100).convert("RGB")
    source = BytesIO()
    image.save(source, format="PNG", compress_level=0)
    original = source.getvalue()
    assert len(original) > WECHAT_MP_MAX_INLINE_IMAGE_BYTES

    first = _normalize_inline_image(original)
    repeated = _normalize_inline_image(original)

    assert first == repeated
    assert len(first) <= WECHAT_MP_MAX_INLINE_IMAGE_BYTES
    with Image.open(BytesIO(first)) as opened:
        opened.load()
        assert opened.format == "JPEG"
        assert opened.width * image.height == opened.height * image.width
        assert not opened.getexif()
        assert "comment" not in opened.info
