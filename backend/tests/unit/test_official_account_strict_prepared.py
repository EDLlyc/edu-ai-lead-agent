from __future__ import annotations

import json
from dataclasses import replace
from hashlib import sha256
from html import unescape
from io import BytesIO
from pathlib import Path
from random import Random
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import httpx
import pytest
from app.application.ports.official_account_strict_visual import StrictVisualMediaEvidence
from app.application.ports.wechat_official_account import (
    WECHAT_MP_MAX_INLINE_IMAGE_BYTES,
    WECHAT_MP_MAX_THUMB_BYTES,
    WeChatInlineImage,
    WeChatMpDraftPreparationError,
    WeChatMpInvalidResponseError,
)
from app.application.services.official_account_strict_prepared import (
    StrictPreparedProjection,
    build_strict_prepared_projection,
    validate_strict_prepared_projection,
)
from app.application.services.wechat_official_account_draft import (
    WeChatDraftLocalSource,
    WeChatOfficialAccountDraftOnlyService,
    WeChatOfficialAccountDraftPreparer,
)
from app.domain.official_account_editor_handoff import EditorHandoffMediaAsset, media_asset_path
from app.domain.official_account_local import (
    STRICT_VISUAL_REFERENCE_POLICY_VERSION,
    ArticleImageBlock,
    ArticleNewsContextMediaSnapshot,
    ArticlePackage,
    ArticleParagraphBlock,
    article_package_fingerprint,
    fingerprint,
)
from app.domain.official_account_strict_layout import (
    STRICT_ESCAPED_UPLOAD_URL_MAX_CHARACTERS,
    STRICT_LAYOUT_PROJECTION_V2_VERSION,
    STRICT_LAYOUT_PROJECTION_VERSION,
    StrictLayoutProjectionVersion,
    compact_strict_xiaosai_html,
    strict_escaped_upload_url,
    validate_strict_upload_html_headroom,
)
from app.domain.official_account_upload_media import (
    normalize_official_account_upload_body,
    normalize_official_account_upload_context,
    normalize_official_account_upload_cover,
)
from app.domain.official_account_visual_pipeline import (
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_V4_VERSION,
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_V4_VERSION,
    STRICT_VISUAL_PIPELINE_VERSION,
)
from app.domain.official_account_weekly_edition import WeeklyArticleRole
from app.infrastructure.wechat_official_account.client import WeChatOfficialAccountApiClient
from app.infrastructure.wechat_official_account.prepared_artifacts import (
    PreparedWeeklyDraftArtifactOwner,
    _write_directory,
)
from PIL import Image
from pydantic import SecretStr, TypeAdapter
from test_official_account_visual_preview import _image, captured  # noqa: F401
from test_wechat_official_account_draft import _FakeDraftClient


@pytest.fixture
def strict_projection(captured: tuple[Path, str]) -> StrictPreparedProjection:  # noqa: F811
    root, _manifest_sha = captured
    article = ArticlePackage.model_validate_json((root / "article.json").read_bytes())
    assert article.media_selection is not None
    assert article.news_context_media is not None
    # The borrowed preview fixture uses random UUIDs; strict projection replay needs
    # a fully deterministic synthetic source identity for its literal manifest golden.
    article = article.model_copy(
        update={
            "news_context_media": article.news_context_media.model_copy(
                update={
                    "items": tuple(
                        item.model_copy(
                            update={"source_article_image_id": UUID(int=800 + item.ordinal)}
                        )
                        for item in article.news_context_media.items
                    )
                }
            )
        }
    )
    article = article.model_copy(
        update={
            "media_selection": article.media_selection.model_copy(
                update={"reference_policy_version": STRICT_VISUAL_REFERENCE_POLICY_VERSION},
            )
        }
    )
    # A deliberately short synthetic fixture; production never removes article blocks.
    article = article.model_copy(
        update={
            "sections": tuple(
                section.model_copy(
                    update={
                        "blocks": (
                            *(
                                block
                                for block in section.blocks
                                if isinstance(block, ArticleImageBlock)
                            ),
                            ArticleParagraphBlock(
                                kind="paragraph",
                                text=section.heading + ":观察事实,提出问题,再用实验验证。",
                            ),
                        )
                    }
                )
                for section in article.sections
            )
        }
    )
    article = article.model_copy(
        update={"content_fingerprint": article_package_fingerprint(article)}
    )
    assets: list[EditorHandoffMediaAsset] = []
    evidence: list[StrictVisualMediaEvidence] = []
    files: dict[str, bytes] = {}
    for section_index, section in enumerate(article.sections):
        for block in section.blocks:
            if not isinstance(block, ArticleImageBlock):
                continue
            ordinal = int(block.slot_key.removeprefix("body-"))
            assignment = article.media_selection.assignments[ordinal]
            derivative = normalize_official_account_upload_body(_image(ordinal + 90, (1536, 1024)))
            path = media_asset_path("body", ordinal, "image/jpeg")
            files[path] = derivative.content
            assets.append(
                EditorHandoffMediaAsset(
                    path=path,
                    role="body",
                    ordinal=ordinal,
                    media_type="image/jpeg",
                    byte_size=len(derivative.content),
                    sha256=derivative.sha256,
                    width=1536,
                    height=1024,
                    alt_text=block.alt_text,
                    assigned_section_index=section_index,
                )
            )
            request = f"{ordinal + 100:064x}"
            evidence.append(
                StrictVisualMediaEvidence(
                    role="body",
                    ordinal=ordinal,
                    generated_visual_id=UUID(int=ordinal + 1),
                    generated_plan_request_fingerprint=f"{ordinal + 20:064x}",
                    reference_asset_ref=assignment.candidate_ref,
                    reference_publication_sha256=assignment.publication_checksum,
                    publication_sha256=derivative.source_sha256,
                    upload_sha256=derivative.sha256,
                    upload_policy_version=derivative.policy_version,
                    media_type="image/jpeg",
                    byte_size=derivative.byte_size,
                    width=1536,
                    height=1024,
                    audit_id=UUID(int=ordinal + 100),
                    audit_request_fingerprint=request,
                    audit_record_fingerprint=fingerprint(
                        "official-account-strict-visual-audit-record-v1",
                        request,
                        "accepted",
                        (),
                    ),
                    provider="zhipu",
                    model="glm-5v-turbo",
                    plan_version=OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_V4_VERSION,
                    prompt_version=OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_V4_VERSION,
                    native_output_size="1536x1024",
                )
            )
    originals: dict[int, bytes] = {}
    assert article.news_context_media is not None
    for source in article.news_context_media.items:
        original = (root / "context" / f"{source.ordinal}.png").read_bytes()
        originals[source.ordinal] = original
        derivative = normalize_official_account_upload_context(original)
        path = media_asset_path("context", source.ordinal, derivative.mime_type)
        files[path] = derivative.content
        assets.append(
            EditorHandoffMediaAsset(
                path=path,
                role="context",
                ordinal=source.ordinal,
                media_type=derivative.mime_type,
                byte_size=derivative.byte_size,
                sha256=derivative.sha256,
                width=derivative.width,
                height=derivative.height,
                alt_text=source.alt_text,
                assigned_section_index=source.section_index,
                source_page_url=source.source_page_url,
                caption=source.caption,
                credit=source.credit,
                rights_status=source.rights_status,
                context_only_not_evidence=True,
            )
        )
    cover = normalize_official_account_upload_cover(files["assets/body-00.jpg"])
    cover_path = media_asset_path("cover", 0, "image/jpeg")
    files[cover_path] = cover.content
    assets.append(
        EditorHandoffMediaAsset(
            path=cover_path,
            role="cover",
            ordinal=0,
            media_type="image/jpeg",
            byte_size=cover.byte_size,
            sha256=cover.sha256,
            width=1175,
            height=500,
            alt_text=article.title,
        )
    )
    request = "a" * 64
    evidence.append(
        replace(
            evidence[0],
            role="cover",
            ordinal=0,
            upload_sha256=cover.sha256,
            upload_policy_version=cover.policy_version,
            byte_size=cover.byte_size,
            width=1175,
            height=500,
            audit_id=UUID(int=200),
            audit_request_fingerprint=request,
            audit_record_fingerprint=fingerprint(
                "official-account-strict-visual-audit-record-v1",
                request,
                "accepted",
                (),
            ),
        )
    )
    return build_strict_prepared_projection(
        run_id=UUID(int=10),
        article_version_id=UUID(int=11),
        render_version_id=UUID(int=12),
        role="application_case",
        article=article,
        media=tuple(assets),
        evidence=tuple(evidence),
        files=files,
        context_originals=originals,
    )


def _write(projection: StrictPreparedProjection, directory: Path) -> WeChatDraftLocalSource:
    _write_directory(
        directory,
        files={
            **projection.files,
            "prepared-manifest.json": json.dumps(projection.manifest, ensure_ascii=False).encode(),
        },
    )
    return WeChatDraftLocalSource(directory=directory, role="application_case")


def _reproject_layout(
    projection: StrictPreparedProjection, version: StrictLayoutProjectionVersion
) -> StrictPreparedProjection:
    manifest = projection.manifest
    media = tuple(
        EditorHandoffMediaAsset.model_validate(item)
        for item in manifest["media"]  # type: ignore[union-attr]
    )
    evidence = tuple(
        TypeAdapter(StrictVisualMediaEvidence).validate_python(item)
        for item in manifest["visual_evidence"]  # type: ignore[union-attr]
    )
    return build_strict_prepared_projection(
        run_id=UUID(str(manifest["run_id"])),
        article_version_id=UUID(str(manifest["article_version_id"])),
        render_version_id=UUID(str(manifest["render_version_id"])),
        role=str(manifest["role"]),
        article=ArticlePackage.model_validate(manifest["article"]),
        media=media,
        evidence=evidence,
        files={asset.path: projection.files[asset.path] for asset in media},
        context_originals={
            item["ordinal"]: projection.files[item["source_path"]]
            for item in manifest["context_derivatives"]  # type: ignore[union-attr]
        },
        layout_projection_version=version,
    )


def test_versioned_layout_roundtrip_preserves_article_audits_and_v1_replay(
    strict_projection: StrictPreparedProjection, tmp_path: Path
) -> None:
    old = strict_projection
    # Literal projection generated independently at immutable d272805, not a golden
    # regenerated from this new implementation. It binds the entire old manifest.
    assert (
        old.child_fingerprint == "73747a84d39552e7eaebc28bb914b1b9eb11c74ad7ac9c9d55feeb0ceccf6107"
    )
    assert sha256(old.files["article-body.html"]).hexdigest() == (
        "567c7623f89ad2c26e682aa7f77d67daa9503f8ec588ad31dc678ae3a05e1868"
    )
    assert sha256(
        json.dumps(old.manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest() == ("9cf39f12b95626ddbedfc33ac4b695a870a98e05dc7baf51c920594d3501a862")
    new = _reproject_layout(old, STRICT_LAYOUT_PROJECTION_V2_VERSION)
    assert new.manifest["version"] == old.manifest["version"]
    assert new.manifest["layout_projection_version"] == STRICT_LAYOUT_PROJECTION_V2_VERSION
    assert old.manifest["layout_projection_version"] == STRICT_LAYOUT_PROJECTION_VERSION
    assert new.child_fingerprint != old.child_fingerprint
    assert new.manifest["content_fingerprint"] != old.manifest["content_fingerprint"]
    for name in (
        "article",
        "article_fingerprint",
        "run_id",
        "article_version_id",
        "render_version_id",
        "media",
        "visual_evidence",
        "context_derivatives",
        "renderer",
        "recipe",
        "placements",
        "escaped_upload_url_max_characters",
    ):
        assert new.manifest[name] == old.manifest[name]
    assert {path: body for path, body in new.files.items() if path != "article-body.html"} == {
        path: body for path, body in old.files.items() if path != "article-body.html"
    }
    for projection, directory in ((new, "new-layout"), (old, "old-layout")):
        validate_strict_prepared_projection(projection.manifest, projection.files)
        prepared = WeChatOfficialAccountDraftPreparer().prepare(
            _write(projection, tmp_path / directory)
        )
        assert prepared.body_html.encode() == projection.files["article-body.html"]
        assert prepared.cover.body == old.files["assets/cover-wide.jpg"]
    assert _reproject_layout(new, STRICT_LAYOUT_PROJECTION_VERSION) == old


@pytest.mark.parametrize("change", ["missing", "unknown", "old_version", "body", "leaf"])
def test_v2_full_consumer_rebuild_rejects_tamper_despite_resealed_superficial_hashes(
    strict_projection: StrictPreparedProjection, tmp_path: Path, change: str
) -> None:
    projection = _reproject_layout(strict_projection, STRICT_LAYOUT_PROJECTION_V2_VERSION)
    manifest: dict[str, Any] = json.loads(json.dumps(projection.manifest))
    files = dict(projection.files)
    if change == "missing":
        del manifest["layout_projection_version"]
    elif change == "unknown":
        manifest["layout_projection_version"] = "xiaosai-strict-inline-compact-v999"
    elif change == "old_version":
        manifest["layout_projection_version"] = STRICT_LAYOUT_PROJECTION_VERSION
    else:
        html = files["article-body.html"].decode()
        if change == "body":
            html = html.replace("<span leaf>", "<span leaf>Unapproved", 1)
        else:
            html = html.replace(" leaf", ' leaf="invalid"', 1)
        assert html.encode() != files["article-body.html"]
        files["article-body.html"] = html.encode()
        descriptor = next(item for item in manifest["files"] if item["path"] == "article-body.html")
        descriptor.update(sha256=sha256(html.encode()).hexdigest(), byte_size=len(html.encode()))
    # An attacker can recompute these public hashes; only exact independent projection
    # rebuilding detects a changed frozen version, removed text/leaf or altered HTML.
    del manifest["child_fingerprint"]
    del manifest["content_fingerprint"]

    def canonical(item: object) -> bytes:
        return json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()

    manifest["content_fingerprint"] = sha256(canonical(manifest)).hexdigest()
    manifest["child_fingerprint"] = sha256(canonical(manifest)).hexdigest()
    with pytest.raises(ValueError):
        validate_strict_prepared_projection(manifest, files)
    with pytest.raises(WeChatMpDraftPreparationError):
        WeChatOfficialAccountDraftPreparer().prepare(
            _write(replace(projection, manifest=manifest, files=files), tmp_path / change)
        )


def test_upload_normalizers_have_fixed_geometry_and_bounds() -> None:
    body = _image(92, (1536, 1024))
    normalized = normalize_official_account_upload_body(body)
    assert normalized.content == body
    assert normalized.byte_size <= WECHAT_MP_MAX_INLINE_IMAGE_BYTES
    first = normalize_official_account_upload_cover(body)
    assert first == normalize_official_account_upload_cover(body)
    assert first.byte_size <= WECHAT_MP_MAX_THUMB_BYTES
    assert first.source_sha256 == sha256(body).hexdigest()
    assert first.sha256 != first.source_sha256
    with Image.open(BytesIO(first.content)) as opened:
        assert opened.size == (1175, 500)
        assert not opened.getexif()
    with pytest.raises(ValueError):
        normalize_official_account_upload_body(_image(2, (1024, 1024)))
    with pytest.raises(ValueError):
        normalize_official_account_upload_cover(_image(2, (281, 276)))


def test_oversized_news_original_has_explicit_non_cropping_upload_derivative() -> None:
    raster = Image.frombytes("RGB", (1200, 900), Random(6).randbytes(1200 * 900 * 3))
    buffer = BytesIO()
    raster.save(buffer, format="PNG")
    original = buffer.getvalue()
    assert len(original) > WECHAT_MP_MAX_INLINE_IMAGE_BYTES
    derivative = normalize_official_account_upload_context(original)
    assert derivative.mime_type == "image/jpeg"
    assert derivative.source_sha256 == sha256(original).hexdigest()
    assert derivative.sha256 != derivative.source_sha256
    assert (derivative.width, derivative.height) == (1200, 900)
    assert derivative.byte_size <= WECHAT_MP_MAX_INLINE_IMAGE_BYTES


@pytest.mark.parametrize("context_count", [0, 2])
@pytest.mark.parametrize(
    "layout_version", [STRICT_LAYOUT_PROJECTION_VERSION, STRICT_LAYOUT_PROJECTION_V2_VERSION]
)
def test_strict_context_count_and_provenance_roundtrip(
    strict_projection: StrictPreparedProjection,
    context_count: int,
    layout_version: StrictLayoutProjectionVersion,
) -> None:
    manifest = strict_projection.manifest
    article = ArticlePackage.model_validate(manifest["article"])
    assert article.news_context_media is not None
    first = article.news_context_media.items[0]
    second_original = _image(156, (1004, 620), "PNG")
    context = (
        ()
        if context_count == 0
        else (
            first,
            first.model_copy(
                update={
                    "ordinal": 1,
                    "section_index": 3,
                    "source_article_image_id": UUID(int=870),
                    "sha256": sha256(second_original).hexdigest(),
                    "alt_text": article.sections[3].heading,
                }
            ),
        )
    )
    article = article.model_copy(
        update={
            "news_context_media": ArticleNewsContextMediaSnapshot(
                selection_version=article.news_context_media.selection_version,
                status="not_present" if context_count == 0 else "ready",
                items=context,
            )
        }
    )
    article = article.model_copy(
        update={"content_fingerprint": article_package_fingerprint(article)}
    )
    assets = [
        EditorHandoffMediaAsset.model_validate(item)
        for item in manifest["media"]  # type: ignore[union-attr]
        if item["role"] != "context"
    ]
    files = {asset.path: strict_projection.files[asset.path] for asset in assets}
    originals: dict[int, bytes] = {}
    for source in context:
        original = (
            strict_projection.files["assets/source-context-00.png"]
            if source.ordinal == 0
            else second_original
        )
        originals[source.ordinal] = original
        derivative = normalize_official_account_upload_context(original)
        path = media_asset_path("context", source.ordinal, derivative.mime_type)
        files[path] = derivative.content
        assets.insert(
            -1,
            EditorHandoffMediaAsset(
                path=path,
                role="context",
                ordinal=source.ordinal,
                media_type=derivative.mime_type,
                byte_size=derivative.byte_size,
                sha256=derivative.sha256,
                width=derivative.width,
                height=derivative.height,
                alt_text=source.alt_text,
                assigned_section_index=source.section_index,
                source_page_url=source.source_page_url,
                caption=source.caption,
                credit=source.credit,
                rights_status=source.rights_status,
                context_only_not_evidence=True,
            ),
        )
    proofs = tuple(
        TypeAdapter(StrictVisualMediaEvidence).validate_python(item)
        for item in manifest["visual_evidence"]
    )  # type: ignore[union-attr]
    result = build_strict_prepared_projection(
        run_id=UUID(int=10),
        article_version_id=UUID(int=11),
        render_version_id=UUID(int=12),
        role="application_case",
        article=article,
        media=tuple(assets),
        evidence=proofs,
        files=files,
        context_originals=originals,
        layout_projection_version=layout_version,
    )
    validate_strict_prepared_projection(result.manifest, result.files)
    assert len(result.manifest["context_derivatives"]) == context_count  # type: ignore[arg-type]
    assert len(result.manifest["placements"]) == context_count  # type: ignore[arg-type]


def test_strict_projection_roundtrip_preserves_news_and_final_thumb(
    strict_projection: StrictPreparedProjection,
    tmp_path: Path,
) -> None:
    validate_strict_prepared_projection(strict_projection.manifest, strict_projection.files)
    source = _write(strict_projection, tmp_path / "strict")
    prepared = WeChatOfficialAccountDraftPreparer().prepare(source)
    assert prepared.visual_pipeline_version == STRICT_VISUAL_PIPELINE_VERSION
    assert prepared.cover.body == strict_projection.files["assets/cover-wide.jpg"]
    assert prepared.body_media[0].body == strict_projection.files["assets/body-00.jpg"]
    assert len(prepared.body_media) == 6
    assert (
        strict_projection.files["assets/source-context-00.png"]
        == strict_projection.files["assets/context-00.png"]
    )
    assert "发布权未验证" in prepared.body_html
    assert strict_projection.manifest["mobile_validation"] == "not_run"
    _write(strict_projection, tmp_path / "strict")
    before = (source.directory / "article-body.html").read_bytes()
    with pytest.raises(ValueError):
        _write_directory(source.directory, files={"article-body.html": b"changed"})
    assert (source.directory / "article-body.html").read_bytes() == before


@pytest.mark.parametrize(
    "mode", ["parent_symlink", "nested_manifest", "empty_directory", "duplicate_keys"]
)
def test_strict_child_filesystem_and_json_are_fail_closed(
    strict_projection: StrictPreparedProjection,
    tmp_path: Path,
    mode: str,
) -> None:
    source = _write(strict_projection, tmp_path / "strict")
    if mode == "parent_symlink":
        alias = tmp_path / "alias"
        alias.symlink_to(source.directory.parent, target_is_directory=True)
        source = replace(source, directory=alias / source.directory.name)
    elif mode == "nested_manifest":
        (source.directory / "assets" / "prepared-manifest.json").write_bytes(b"{}")
    elif mode == "empty_directory":
        (source.directory / "unrecognized").mkdir()
    else:
        path = source.directory / "prepared-manifest.json"
        original = path.read_bytes()
        path.write_bytes(b'{"version":"invalid",' + original[1:])
    with pytest.raises(WeChatMpDraftPreparationError):
        WeChatOfficialAccountDraftPreparer().prepare(source)


@pytest.mark.parametrize("field", ["ordinal", "byte_size", "width", "height"])
def test_strict_audit_numeric_fields_never_coerce_bool_or_float(
    strict_projection: StrictPreparedProjection,
    field: str,
) -> None:
    manifest: dict[str, Any] = json.loads(json.dumps(strict_projection.manifest))
    value = manifest["visual_evidence"][0][field]
    manifest["visual_evidence"][0][field] = float(value)
    with pytest.raises(ValueError):
        validate_strict_prepared_projection(manifest, strict_projection.files)


@pytest.mark.parametrize(
    "change",
    [
        "model",
        "plan_version",
        "upload_sha256",
        "audit_record_fingerprint",
        "missing",
        "unknown_field",
        "wrong_version",
        "rights",
        "source",
        "bytes",
        "extra_file",
    ],
)
def test_strict_prepared_tamper_fails_before_social_calls(
    strict_projection: StrictPreparedProjection,
    tmp_path: Path,
    change: str,
) -> None:
    manifest: dict[str, Any] = json.loads(json.dumps(strict_projection.manifest))
    files = dict(strict_projection.files)
    if change in {"model", "plan_version", "upload_sha256", "audit_record_fingerprint"}:
        manifest["visual_evidence"][0][change] = "changed"
    elif change == "missing":
        manifest["visual_evidence"].pop()
    elif change == "unknown_field":
        manifest["visual_evidence"][0]["unknown"] = True
    elif change == "wrong_version":
        manifest["version"] = "unknown"
    elif change == "rights":
        manifest["media"][5]["rights_status"] = None
    elif change == "source":
        files["assets/source-context-00.png"] = _image(999, (1004, 620), "PNG")
    elif change == "bytes":
        files["assets/cover-wide.jpg"] = _image(999, (1175, 500))
    else:
        files["assets/extra.jpg"] = _image(999)
    with pytest.raises(ValueError):
        validate_strict_prepared_projection(manifest, files)
    source = _write(
        replace(strict_projection, manifest=manifest, files=files), tmp_path / f"tamper-{change}"
    )
    with pytest.raises(WeChatMpDraftPreparationError):
        WeChatOfficialAccountDraftPreparer().prepare(source)


@pytest.mark.asyncio
async def test_strict_consumer_uploads_exact_audited_bytes(
    strict_projection: StrictPreparedProjection,
    tmp_path: Path,
) -> None:
    client = _FakeDraftClient()
    service = WeChatOfficialAccountDraftOnlyService(client=client)
    receipt = await service.create_draft(_write(strict_projection, tmp_path / "strict"))
    assert receipt.not_published
    assert client.thumb_uploads[0][0] == strict_projection.files["assets/cover-wide.jpg"]
    assert len(client.inline_uploads) == 6
    assert len(client.drafts) == 1
    assert len(client.drafts[0].content) <= 19_999


@pytest.mark.asyncio
async def test_oversized_strict_provider_url_never_reaches_thumb_or_add_draft(
    strict_projection: StrictPreparedProjection,
    tmp_path: Path,
) -> None:
    class LongUrlClient(_FakeDraftClient):
        async def upload_inline_image(
            self, image_bytes: bytes, media_type: str, filename: str
        ) -> WeChatInlineImage:
            await super().upload_inline_image(image_bytes, media_type, filename)
            return WeChatInlineImage(url="https://mmbiz.qpic.cn/" + "x" * 256)

    client = LongUrlClient()
    service = WeChatOfficialAccountDraftOnlyService(client=client)
    with pytest.raises(WeChatMpInvalidResponseError):
        await service.create_draft(_write(strict_projection, tmp_path / "strict"))
    assert len(client.inline_uploads) == 1
    assert not client.thumb_uploads and not client.drafts


def test_strict_html_url_boundary_counts_escaped_characters() -> None:
    assert STRICT_ESCAPED_UPLOAD_URL_MAX_CHARACTERS == 256
    assert len(strict_escaped_upload_url("x" * 251 + "&")) == 256
    with pytest.raises(ValueError):
        strict_escaped_upload_url("x" * 252 + "&")
    with pytest.raises(ValueError):
        strict_escaped_upload_url("x" * 257)
    validate_strict_upload_html_headroom(
        "<p>" + "x" * 19721 + '</p><img src="assets/a.jpg">', ("assets/a.jpg",)
    )
    with pytest.raises(ValueError):
        validate_strict_upload_html_headroom(
            "<p>" + "x" * 19900 + '</p><img src="assets/a.jpg">', ("assets/a.jpg",)
        )


def test_compaction_keeps_text_and_relative_css_semantics() -> None:
    source = (
        '<section style="font-size:16px;color:#FFFFFF;line-height:1.75">'
        '<p style="font-size:16px;color:#FFFFFF;line-height:1.75">'
        '<span leaf="">原文&amp;不变</span></p></section>'
    )
    result = compact_strict_xiaosai_html(source)
    assert '<p style="">' in result
    assert '<span leaf="">原文&amp;不变</span>' in result
    for property_name, value in (
        ("font-size", "1.5em"),
        ("line-height", "120%"),
        ("font-weight", "bolder"),
    ):
        relative = (
            f'<section style="{property_name}:{value}">'
            f'<p style="{property_name}:{value}">text</p></section>'
        )
        assert compact_strict_xiaosai_html(relative).count(f"{property_name}:{value}") == 2
    assert unescape(result).endswith("原文&不变</span></p></section>")


@pytest.mark.asyncio
async def test_real_prepared_owner_to_http_draft_uses_six_audited_uploads(
    strict_projection: StrictPreparedProjection,
    tmp_path: Path,
) -> None:
    manifest = strict_projection.manifest
    article = ArticlePackage.model_validate(manifest["article"])
    assets = tuple(EditorHandoffMediaAsset.model_validate(item) for item in manifest["media"])  # type: ignore[union-attr]
    proofs = tuple(
        TypeAdapter(StrictVisualMediaEvidence).validate_python(item)
        for item in manifest["visual_evidence"]
    )  # type: ignore[union-attr]
    rows = []
    for asset in assets:
        proof = next(
            (item for item in proofs if (item.role, item.ordinal) == (asset.role, asset.ordinal)),
            None,
        )
        source = (
            article.news_context_media.items[asset.ordinal]
            if asset.role == "context" and article.news_context_media
            else None
        )
        rows.append(
            SimpleNamespace(
                local_media_id=f"local-{asset.role}-{asset.ordinal}",
                source_image_artifact_id=None,
                fixture_id=None,
                role=asset.role,
                ordinal=asset.ordinal,
                media_type=asset.media_type,
                byte_size=asset.byte_size,
                sha256=asset.sha256,
                generated_visual_id=proof.generated_visual_id if proof else None,
                source_article_image_id=source.source_article_image_id if source else None,
                run_id=UUID(int=10),
                render_version_id=UUID(int=12),
                descriptor={
                    "assigned_section_index": asset.assigned_section_index,
                    "alt_text": asset.alt_text,
                    "source_page_url": asset.source_page_url,
                    "caption": asset.caption,
                    "credit": asset.credit,
                    "rights_status": asset.rights_status,
                    "context_only_not_evidence": asset.context_only_not_evidence,
                },
            )
        )
        if asset.role == "body":
            assert asset.assigned_section_index is not None
            section_index = asset.assigned_section_index
            heading = article.sections[section_index].heading
            generated_alt = f"第 {section_index + 1} 节“{heading}”的核心场景插画"
            assert generated_alt != asset.alt_text
            rows[-1].descriptor["alt_text"] = generated_alt

    class Session:
        async def __aenter__(self) -> Session:
            return self

        async def __aexit__(self, *_args: object) -> None:
            return None

    class Resolver:
        async def read_verified_bytes(self, *, session: object, media: Any) -> bytes:
            return strict_projection.files[
                media_asset_path(media.role, media.ordinal, media.media_type)
            ]

    class Repository:
        async def get_run(self, _run_id: UUID) -> SimpleNamespace:
            return SimpleNamespace(
                status="ready",
                generation_mode="live",
                version_bundle={"visual_pipeline_version": STRICT_VISUAL_PIPELINE_VERSION},
            )

        async def get_article(self, _run_id: UUID) -> SimpleNamespace:
            return SimpleNamespace(
                id=UUID(int=11),
                article=article,
                validation_passed=True,
                audit=SimpleNamespace(accepted=True),
            )

        async def get_draft(self, _run_id: UUID) -> SimpleNamespace:
            return SimpleNamespace(state="ready", simulation=True)

        async def get_render(self, _run_id: UUID) -> SimpleNamespace:
            return SimpleNamespace(id=UUID(int=12), article_version_id=UUID(int=11))

        async def load_strict_visual_evidence(
            self, _run_id: UUID
        ) -> tuple[StrictVisualMediaEvidence, ...]:
            return proofs

    class Owner(PreparedWeeklyDraftArtifactOwner):
        async def _load_media_rows(self, _run_id: UUID) -> Any:
            return tuple(rows)

    owner = Owner(
        session_factory=Session,
        resolver=Resolver(),  # type: ignore[arg-type]
        work_root=tmp_path / "work",
        inbox_root=tmp_path / "inbox",
        max_image_bytes=10 * 1024 * 1024,
    )
    owner._repository = Repository()  # type: ignore[assignment]
    artifact = await owner.build_child(run_id=UUID(int=10), role=WeeklyArticleRole.APPLICATION_CASE)
    assert (
        await owner.build_child(run_id=UUID(int=10), role=WeeklyArticleRole.APPLICATION_CASE)
        == artifact
    )
    prepared = owner.validate_child(artifact, role=WeeklyArticleRole.APPLICATION_CASE)
    assert " leaf>" in prepared.body_html
    calls: list[str] = []
    uploaded_bodies: list[bytes] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/cgi-bin/stable_token":
            return httpx.Response(200, json={"access_token": "synthetic-token", "expires_in": 7200})
        if request.url.path == "/cgi-bin/media/uploadimg":
            matches = [item.body for item in prepared.body_media if item.body in request.content]
            assert len(matches) == 1
            uploaded_bodies.extend(matches)
            return httpx.Response(
                200, json={"url": f"https://mmbiz.qpic.cn/test-{len(uploaded_bodies)}.jpg"}
            )
        if request.url.path == "/cgi-bin/material/add_material":
            assert prepared.cover.body in request.content
            return httpx.Response(200, json={"media_id": "synthetic-thumb"})
        assert request.url.path == "/cgi-bin/draft/add"
        payload = json.loads(request.content)
        assert len(payload["articles"]) == 1
        assert payload["articles"][0]["article_type"] == "news"
        assert "assets/" not in payload["articles"][0]["content"]
        return httpx.Response(200, json={"media_id": "synthetic-draft"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as transport:
        client = WeChatOfficialAccountApiClient(
            client=transport,
            app_id=SecretStr("synthetic-app"),
            app_secret=SecretStr("synthetic-secret"),
            timeout_seconds=1,
            max_response_bytes=65536,
        )
        receipt = await WeChatOfficialAccountDraftOnlyService(client=client).create_prepared(
            prepared
        )
    assert receipt.not_published
    assert len(uploaded_bodies) == 6
    assert len(calls) == 9
    assert calls.count("/cgi-bin/draft/add") == 1
