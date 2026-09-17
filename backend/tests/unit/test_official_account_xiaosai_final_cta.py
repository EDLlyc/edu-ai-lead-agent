"""Independent checks for the fixed Xiaosai marketing footer and legacy replay."""

from __future__ import annotations

import copy
import json
import re
from dataclasses import replace
from hashlib import sha256
from html import unescape
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from app.application.ports.wechat_official_account import WeChatMpDraftPreparationError
from app.application.services.official_account_strict_prepared import (
    StrictPreparedProjection,
    build_strict_prepared_projection,
    validate_strict_prepared_projection,
)
from app.application.services.wechat_official_account_draft import (
    WeChatOfficialAccountDraftOnlyService,
)
from app.domain.official_account_editor_handoff_v2 import (
    CHENGYUE_HEADER_BODY_SPACER_HTML,
    CHENGYUE_HEADER_BODY_SPACING_VERSION,
)
from app.domain.official_account_local import ArticlePackage, article_package_fingerprint
from app.domain.official_account_source_presentation import CURRENT_SOURCE_PRESENTATION_VERSION
from app.domain.official_account_strict_layout import STRICT_LAYOUT_PROJECTION_V2_VERSION
from app.domain.official_account_upload_media import (
    normalize_official_account_upload_footer,
    normalize_official_account_upload_header,
)
from app.domain.official_account_visual_pipeline import (
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_V4_VERSION as V4,
)
from app.domain.official_account_visual_pipeline import (
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_V5_VERSION as V5,
)
from app.domain.official_account_weekly_edition import WeeklyArticleRole
from app.domain.official_account_xiaosai_footer import (
    CHENGYUE_HEADER_MASTER_SHA256,
    CHENGYUE_HEADER_PATH,
    CHENGYUE_HEADER_PUBLICATION_SHA256,
    LEGACY_XIAOSAI_FOOTER_PATH,
    XIAOSAI_FOOTER_MASTER_SHA256,
    XIAOSAI_FOOTER_PATH,
    XIAOSAI_FOOTER_PUBLICATION_SHA256,
    ChengyueIntroductionHeaderAsset,
    XiaosaiFooterAsset,
    XiaosaiMarketingFooterAsset,
)
from app.infrastructure import official_account_marketing_footer as marketing_footer_module
from app.infrastructure.official_account_catalog import LocalOfficialAccountCatalogMediaProvider
from app.infrastructure.official_account_marketing_footer import (
    load_chengyue_introduction_header,
    load_official_account_marketing_framing,
    load_xiaosai_marketing_footer,
)
from app.infrastructure.official_account_media import OfficialAccountLocalMediaResolver
from app.infrastructure.wechat_official_account.client import WeChatOfficialAccountApiClient
from app.infrastructure.wechat_official_account.prepared_artifacts import (
    PreparedWeeklyDraftArtifactOwner,
)
from pydantic import SecretStr
from test_official_account_body_caption_visibility import (
    CONTEXT_NOTICE,
    _before_signature,
    _inputs,
)
from test_official_account_strict_prepared import _write, strict_projection  # noqa: F401
from test_official_account_visual_preview import captured  # noqa: F401
from test_official_account_xiaosai_references import make_catalog
from test_visual_assets import _write_manifest
from test_wechat_official_account_draft import _FakeDraftClient

_COMPACT_CHENGYUE_HEADER_BODY_SPACER_HTML = (
    '<p style="margin:0;font-size:17px"><span leaf><br></span></p>'
)


def test_historical_v4_keeps_the_exact_pre_footer_artifact(
    strict_projection: StrictPreparedProjection,  # noqa: F811
) -> None:
    assert strict_projection.child_fingerprint == (
        "73747a84d39552e7eaebc28bb914b1b9eb11c74ad7ac9c9d55feeb0ceccf6107"
    )
    assert sha256(strict_projection.files["article-body.html"]).hexdigest() == (
        "567c7623f89ad2c26e682aa7f77d67daa9503f8ec588ad31dc678ae3a05e1868"
    )
    assert "二维码待补" not in strict_projection.files["article-body.html"].decode()
    assert all("footer" not in path for path in strict_projection.files)
    validate_strict_prepared_projection(strict_projection.manifest, strict_projection.files)


def _catalog_bound_article(projection, candidate):
    article = ArticlePackage.model_validate(projection.manifest["article"])
    selection = article.media_selection
    first = selection.assignments[0].model_copy(
        update={
            "candidate_ref": candidate.catalog_asset_ref,
            "source_checksum": candidate.source_master_sha256,
            "publication_checksum": candidate.sha256,
        }
    )
    article = article.model_copy(
        update={
            "media_selection": selection.model_copy(
                update={
                    "catalog_version": candidate.catalog_version,
                    "assignments": (first, *selection.assignments[1:]),
                }
            )
        }
    )
    return article.model_copy(update={"content_fingerprint": article_package_fingerprint(article)})


def _without_current_header(html: str) -> str:
    image_start = html.index(f'<img src="{CHENGYUE_HEADER_PATH}"')
    section_start = html.rfind("<section", 0, image_start)
    section_end = html.index("</section>", image_start) + len("</section>")
    return html[:section_start] + html[section_end:]


@pytest.mark.parametrize(
    "characters", [("xiao-sai",), ("sai-xiansheng",), ("xiao-sai", "sai-xiansheng"), ()]
)
async def test_legacy_footer_provider_requires_frozen_exact_xiaosai_catalog(
    strict_projection,  # noqa: F811
    tmp_path,
    characters,
):
    catalog, manifest, _entries, candidates = make_catalog(tmp_path, [characters])
    article = _catalog_bound_article(strict_projection, candidates[0])
    provider = LocalOfficialAccountCatalogMediaProvider(manifest)
    if characters != ("xiao-sai",):
        with pytest.raises(ValueError, match="approved reference changed"):
            await provider.load_xiaosai_footer(article)
        return
    footer, body = await provider.load_xiaosai_footer(article)
    assert isinstance(footer, XiaosaiFooterAsset)
    assert footer.role == "footer" and footer.path == LEGACY_XIAOSAI_FOOTER_PATH
    assert footer.characters == ("xiao-sai",) and footer.approved
    assert footer.qr_state == "pending"
    assert footer.sha256 == candidates[0].sha256 == sha256(body).hexdigest()
    assert footer.source_master_sha256 == candidates[0].source_master_sha256
    assert footer.catalog_asset_ref == article.media_selection.assignments[0].candidate_ref
    assert body == await catalog.read_publication_bytes(
        catalog_asset_ref=footer.catalog_asset_ref,
        catalog_version=footer.catalog_version,
        source_master_sha256=footer.source_master_sha256,
        publication_sha256=footer.sha256,
    )
    assert footer.sha256 not in {
        sha256(value).hexdigest() for value in strict_projection.files.values()
    }


async def test_footer_catalog_metadata_drift_during_byte_read_is_rejected(
    strict_projection,  # noqa: F811
    tmp_path,
    monkeypatch,
):
    _catalog, manifest, entries, candidates = make_catalog(tmp_path, [("xiao-sai",)])
    article = _catalog_bound_article(strict_projection, candidates[0])
    original = LocalOfficialAccountCatalogMediaProvider.read_publication_bytes

    async def changed(self, **kwargs):
        body = await original(self, **kwargs)
        entries[0]["characters"] = ["sai-xiansheng"]
        _write_manifest(tmp_path, entries)
        return body

    monkeypatch.setattr(LocalOfficialAccountCatalogMediaProvider, "read_publication_bytes", changed)
    provider = LocalOfficialAccountCatalogMediaProvider(manifest)
    with pytest.raises(ValueError, match="character identity changed"):
        await provider.load_xiaosai_footer(article)


async def test_current_framing_resolver_uses_sealed_repo_assets_not_article_assignment(
    strict_projection,  # noqa: F811
):
    article = ArticlePackage.model_validate(strict_projection.manifest["article"])
    resolver = OfficialAccountLocalMediaResolver(image_asset_manifest=None, image_store=None)
    header, header_body, footer, body = await resolver.read_official_account_marketing_framing(
        article
    )
    direct_header, direct_header_body, direct_footer, direct_body = (
        load_official_account_marketing_framing()
    )
    assert header == direct_header == ChengyueIntroductionHeaderAsset()
    assert header_body == direct_header_body
    assert len(header_body) == header.byte_size == 716_140 < 1024 * 1024
    assert sha256(header_body).hexdigest() == CHENGYUE_HEADER_PUBLICATION_SHA256
    assert header.source_master_sha256 == CHENGYUE_HEADER_MASTER_SHA256
    assert footer == direct_footer == XiaosaiMarketingFooterAsset()
    assert body == direct_body
    assert len(body) == footer.byte_size == 383_664 < 1024 * 1024
    assert sha256(body).hexdigest() == XIAOSAI_FOOTER_PUBLICATION_SHA256
    assert footer.source_master_sha256 == XIAOSAI_FOOTER_MASTER_SHA256


def test_packaged_master_reproduces_the_sealed_publication_without_crop() -> None:
    header, header_body = load_chengyue_introduction_header()
    footer, body = load_xiaosai_marketing_footer()
    module_path = marketing_footer_module.__file__
    assert module_path is not None
    asset_root = Path(module_path).resolve().parents[1] / "assets"
    header_master = (asset_root / "chengyue-top-intro-master.png").read_bytes()
    header_derivative = normalize_official_account_upload_header(header_master)
    assert header_derivative.content == header_body
    assert header_derivative.source_sha256 == header.source_master_sha256
    assert header_derivative.sha256 == header.sha256
    assert header_derivative.policy_version == header.derivative_policy_version
    assert (header_derivative.width, header_derivative.height) == (
        header.width,
        header.height,
    )
    master = (asset_root / "xiaosai-marketing-footer-master.png").read_bytes()
    derivative = normalize_official_account_upload_footer(master)
    assert derivative.content == body
    assert derivative.source_sha256 == footer.source_master_sha256
    assert derivative.sha256 == footer.sha256
    assert derivative.policy_version == footer.derivative_policy_version
    assert (derivative.width, derivative.height) == (footer.width, footer.height)


def test_backend_runtime_image_context_includes_the_four_framing_assets() -> None:
    module_path = marketing_footer_module.__file__
    assert module_path is not None
    backend_root = Path(module_path).resolve().parents[2]
    dockerfile = (backend_root / "Dockerfile").read_text(encoding="utf-8")
    dockerignore = (backend_root / ".dockerignore").read_text(encoding="utf-8").splitlines()
    assert "COPY app ./app" in dockerfile
    assert not any(
        line.strip().removeprefix("/").startswith("app/assets")
        for line in dockerignore
        if line.strip() and not line.lstrip().startswith("#")
    )
    assert {path.name for path in (backend_root / "app/assets").iterdir() if path.is_file()} >= {
        "chengyue-top-intro-master.png",
        "chengyue-top-intro.jpg",
        "xiaosai-marketing-footer-master.png",
        "xiaosai-marketing-footer.jpg",
    }


@pytest.mark.parametrize("target_name", ["master", "publication"])
def test_packaged_footer_byte_tamper_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target_name: str
) -> None:
    original_master = marketing_footer_module._MASTER_FILE
    original_publication = marketing_footer_module._PUBLICATION_FILE
    master = tmp_path / "master.png"
    publication = tmp_path / "publication.jpg"
    master.write_bytes(original_master.read_bytes())
    publication.write_bytes(original_publication.read_bytes())
    target = master if target_name == "master" else publication
    target.write_bytes(target.read_bytes() + b"tampered")
    monkeypatch.setattr(marketing_footer_module, "_MASTER_FILE", master)
    monkeypatch.setattr(marketing_footer_module, "_PUBLICATION_FILE", publication)
    with pytest.raises(ValueError, match="packaged bytes changed"):
        load_xiaosai_marketing_footer()


@pytest.mark.parametrize("target_name", ["master", "publication"])
def test_packaged_header_byte_tamper_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, target_name: str
) -> None:
    original_master = marketing_footer_module._HEADER_MASTER_FILE
    original_publication = marketing_footer_module._HEADER_PUBLICATION_FILE
    master = tmp_path / "header-master.png"
    publication = tmp_path / "header-publication.jpg"
    master.write_bytes(original_master.read_bytes())
    publication.write_bytes(original_publication.read_bytes())
    target = master if target_name == "master" else publication
    target.write_bytes(target.read_bytes() + b"tampered")
    monkeypatch.setattr(marketing_footer_module, "_HEADER_MASTER_FILE", master)
    monkeypatch.setattr(marketing_footer_module, "_HEADER_PUBLICATION_FILE", publication)
    with pytest.raises(ValueError, match="packaged bytes changed"):
        load_chengyue_introduction_header()


@pytest.fixture
async def final_cta(strict_projection):  # noqa: F811
    """Existing six audited fixtures plus the sealed approved framing bundle."""
    inputs = _inputs(strict_projection)
    article = inputs["article"].model_copy(update={"author": "程岳"})
    inputs["article"] = article.model_copy(
        update={"content_fingerprint": article_package_fingerprint(article)}
    )
    inputs["evidence"] = tuple(replace(proof, prompt_version=V5) for proof in inputs["evidence"])
    inputs["layout_projection_version"] = STRICT_LAYOUT_PROJECTION_V2_VERSION
    resolver = OfficialAccountLocalMediaResolver(image_asset_manifest=None, image_store=None)
    (
        header,
        header_content,
        footer,
        footer_content,
    ) = await resolver.read_official_account_marketing_framing(inputs["article"])
    inputs["header"] = header
    inputs["footer"] = footer
    inputs["files"][header.path] = header_content
    inputs["files"][footer.path] = footer_content
    return inputs, build_strict_prepared_projection(**inputs)


async def test_actual_prepared_owner_consumer_and_http_keep_fixed_marketing_framing(
    final_cta, tmp_path
):
    inputs, projection = final_cta
    projection = build_strict_prepared_projection(
        **inputs, source_presentation=CURRENT_SOURCE_PRESENTATION_VERSION
    )
    validate_strict_prepared_projection(projection.manifest, projection.files)
    article = inputs["article"]
    # Fake persistence only; exercise the real production owner and real footer resolver.
    rows = []
    for asset in inputs["media"]:
        proof = next(
            (p for p in inputs["evidence"] if (p.role, p.ordinal) == (asset.role, asset.ordinal)),
            None,
        )
        context = (
            article.news_context_media.items[asset.ordinal] if asset.role == "context" else None
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
                sha256=context.sha256 if context else asset.sha256,
                generated_visual_id=proof.generated_visual_id if proof else None,
                source_article_image_id=context.source_article_image_id if context else None,
                run_id=inputs["run_id"],
                render_version_id=inputs["render_version_id"],
                descriptor={
                    key: getattr(asset, key)
                    for key in (
                        "assigned_section_index",
                        "alt_text",
                        "source_page_url",
                        "caption",
                        "credit",
                        "rights_status",
                        "context_only_not_evidence",
                    )
                },
            )
        )

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

    class Resolver(OfficialAccountLocalMediaResolver):
        async def read_verified_bytes(self, *, session, media):
            if media.role == "context":
                return inputs["context_originals"][media.ordinal]
            asset = next(
                a for a in inputs["media"] if (a.role, a.ordinal) == (media.role, media.ordinal)
            )
            return inputs["files"][asset.path]

    resolver = Resolver(image_asset_manifest=None, image_store=None)
    owner = PreparedWeeklyDraftArtifactOwner(
        session_factory=Session,
        resolver=resolver,
        work_root=tmp_path / "work",
        inbox_root=tmp_path / "inbox",
        max_image_bytes=10 * 1024 * 1024,
    )
    owner._repository = SimpleNamespace(
        load_strict_visual_evidence=AsyncMock(return_value=inputs["evidence"]),
        get_render=AsyncMock(
            return_value=SimpleNamespace(
                id=inputs["render_version_id"],
                article_version_id=inputs["article_version_id"],
            )
        ),
    )
    owner._load_media_rows = AsyncMock(return_value=tuple(rows))
    artifact = await owner._build_strict_child(
        run_id=inputs["run_id"],
        role=WeeklyArticleRole.APPLICATION_CASE,
        article=SimpleNamespace(id=inputs["article_version_id"], article=article),
        visual_pipeline_version=inputs["visual_pipeline_version"],
    )
    assert artifact.fingerprint == projection.child_fingerprint
    prepared = owner.validate_child(artifact, role=WeeklyArticleRole.APPLICATION_CASE)
    assert prepared.body_html.encode() == projection.files["article-body.html"]
    html = prepared.body_html
    assert html.count("我是程岳") == 1
    assert "二维码待补" not in html and "认识小赛" not in html and "欢迎关注" not in html
    assert "扫码" not in html
    tail = html[len(_before_signature(html, "程岳")) :]
    assert len(re.findall(r"<img\b", tail)) == 1
    assert "href=" not in tail and "http" not in tail and "<svg" not in tail
    assert '<section style="margin:0"><img ' in tail
    assert re.search(r"(?<!max-)width:100%", tail) is None
    assert tail.endswith("</section></section>")
    assert tail.rfind("<img ") > tail.rfind("我是程岳")
    assert re.fullmatch(r"<img [^>]+></section></section>", tail[tail.index("<img ") :])
    first_image = re.search(r"<img\b[^>]*>", html)
    assert first_image is not None and f'src="{CHENGYUE_HEADER_PATH}"' in first_image[0]
    assert re.sub(r"<[^>]+>", "", html[: first_image.start()]) == ""
    header_section_start = html.rfind("<section", 0, first_image.start())
    header_section_end = html.index("</section>", first_image.end()) + len("</section>")
    assert re.fullmatch(
        r'<section style="margin:0"><img [^>]+></section>',
        html[header_section_start:header_section_end],
    )
    cover_start = html.index("<section", header_section_end)
    assert html[header_section_end:cover_start] == _COMPACT_CHENGYUE_HEADER_BODY_SPACER_HTML
    assert html.count(_COMPACT_CHENGYUE_HEADER_BODY_SPACER_HTML) == 1
    assert CHENGYUE_HEADER_BODY_SPACER_HTML == (
        '<p style="margin:0;font-size:17px;line-height:1.75;"><span leaf=""><br></span></p>'
    )
    assert (
        projection.manifest["header_body_spacing_version"] == CHENGYUE_HEADER_BODY_SPACING_VERSION
    )
    assert all("qr" not in path.lower() for path in projection.files)
    assert prepared.author == projection.manifest["author"] == "程岳"
    assert len(projection.manifest["visual_evidence"]) == 6
    assert projection.manifest["media"][0] == inputs["header"].model_dump(mode="json")
    assert projection.manifest["media"][-1] == inputs["footer"].model_dump(mode="json")
    assert projection.manifest["media"][-1]["version"].endswith("-v2")
    assert projection.manifest["media"][-1]["qr_state"] == "ready"
    local_image_paths = re.findall(r'<img src="([^"]+)"', html)
    assert [m.path for m in prepared.body_media] == local_image_paths
    assert local_image_paths[0] == CHENGYUE_HEADER_PATH
    assert prepared.body_media[0].body == inputs["files"][CHENGYUE_HEADER_PATH]
    assert prepared.body_media[-1].path == XIAOSAI_FOOTER_PATH
    assert prepared.body_media[-1].body == inputs["files"][XIAOSAI_FOOTER_PATH]
    assert prepared.body_media[-1].body not in [
        m.body for m in (*prepared.body_media[:-1], prepared.cover)
    ]

    legacy_header_projection = build_strict_prepared_projection(
        **inputs,
        source_presentation=CURRENT_SOURCE_PRESENTATION_VERSION,
        header_body_spacing=None,
    )
    validate_strict_prepared_projection(
        legacy_header_projection.manifest, legacy_header_projection.files
    )
    legacy_header_html = legacy_header_projection.files["article-body.html"].decode()
    legacy_header_image = legacy_header_html.index(f'<img src="{CHENGYUE_HEADER_PATH}"')
    legacy_header_end = legacy_header_html.index("</section>", legacy_header_image) + len(
        "</section>"
    )
    assert legacy_header_html.startswith("<section", legacy_header_end)
    assert _COMPACT_CHENGYUE_HEADER_BODY_SPACER_HTML not in legacy_header_html
    assert "header_body_spacing_version" not in legacy_header_projection.manifest
    assert sha256(legacy_header_projection.files["article-body.html"]).hexdigest() == (
        "9a0e88f2b2b85492c64dde30cf08e442919cd714710fad875fdc34d5bb853dfd"
    )
    assert legacy_header_projection.child_fingerprint == (
        "1ed5ef768801015b422cc8e1e5d6aad424b0bf5c0ca93cc06bc559e4ae5a3c40"
    )

    historical_inputs = {
        **inputs,
        "header": None,
        "footer": None,
        "files": {
            k: v
            for k, v in inputs["files"].items()
            if k not in {CHENGYUE_HEADER_PATH, XIAOSAI_FOOTER_PATH}
        },
        "evidence": tuple(replace(p, prompt_version=V4) for p in inputs["evidence"]),
    }
    historical_projection = build_strict_prepared_projection(**historical_inputs)
    old_html = historical_projection.files["article-body.html"].decode()
    assert _COMPACT_CHENGYUE_HEADER_BODY_SPACER_HTML not in old_html
    assert len(projection.manifest["files"]) == len(historical_projection.manifest["files"]) + 2
    assert "查看权威原文" in old_html and "查看权威原文" not in html
    assert all(value not in html for value in ("href=", "http", "阅读原文", "查看原文"))
    assert prepared.content_source_url is None
    assert projection.manifest["source_presentation_version"] == CURRENT_SOURCE_PRESENTATION_VERSION
    assert projection.manifest["content_source_url"] is None
    assert CONTEXT_NOTICE not in html
    credits = [m.credit for m in inputs["media"] if m.role == "context"]
    assert credits and all(credit in unescape(html) for credit in credits)
    assert projection.manifest["article"] == article.model_dump(mode="json")

    uploaded, calls, payloads = [], [], []

    def respond(request):
        calls.append(request.url.path)
        if request.url.path == "/cgi-bin/stable_token":
            return httpx.Response(200, json={"access_token": "synthetic-token", "expires_in": 7200})
        if request.url.path == "/cgi-bin/media/uploadimg":
            expected = prepared.body_media[len(uploaded)]
            assert expected.body in request.content
            assert expected.upload_filename.encode() in request.content
            uploaded.append(expected.body)
            return httpx.Response(
                200, json={"url": f"https://mmbiz.qpic.cn/inline-{len(uploaded)}.jpg"}
            )
        if request.url.path == "/cgi-bin/material/add_material":
            assert prepared.cover.body in request.content
            return httpx.Response(200, json={"media_id": "synthetic-thumb"})
        assert request.url.path == "/cgi-bin/draft/add"
        payloads.append(json.loads(request.content)["articles"][0])
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
    assert receipt.not_published and calls.count("/cgi-bin/draft/add") == 1
    assert uploaded == [m.body for m in prepared.body_media] and len(uploaded) == 8
    payload = payloads[0]
    assert "content_source_url" not in payload
    assert payload["author"] == "程岳" and "二维码待补" not in payload["content"]
    assert re.findall(r'<img src="([^"]+)"', payload["content"]) == [
        f"https://mmbiz.qpic.cn/inline-{i}.jpg" for i in range(1, 9)
    ]
    replacement_urls = {
        media.path: f"https://mmbiz.qpic.cn/inline-{index}.jpg"
        for index, media in enumerate(prepared.body_media, 1)
    }
    assert payload["content"] == re.sub(
        r'<img src="([^"]+)"',
        lambda m: f'<img src="{replacement_urls[m[1]]}"',
        html,
    )
    assert all(credit in unescape(payload["content"]) for credit in credits)


async def test_unknown_header_body_spacing_version_is_rejected(
    final_cta,
) -> None:
    _inputs, projection = final_cta
    manifest = copy.deepcopy(projection.manifest)
    manifest["header_body_spacing_version"] = "unsupported-header-spacing"

    with pytest.raises(ValueError, match="header body spacing version is unsupported"):
        validate_strict_prepared_projection(manifest, projection.files)


@pytest.mark.parametrize(
    "mutation",
    [
        {"catalog_asset_ref": "f" * 16},
        {"source_master_sha256": "f" * 64},
        {"catalog_version": "unrelated"},
        {"role": "context"},
        {"path": "assets/qr.jpg"},
        {"characters": ["sai-xiansheng"]},
        {"characters": ["xiao-sai", "sai-xiansheng"]},
        {"qr_state": "pending"},
        {"purpose": "add-contact"},
        {"source_master_byte_size": 1},
        {"derivative_policy_version": "unversioned"},
        {"sha256": "f" * 64},
    ],
)
async def test_tampered_footer_descriptor_rejects_before_any_client_call(
    final_cta, tmp_path, mutation
):
    _arguments, projection = final_cta
    manifest = copy.deepcopy(projection.manifest)
    manifest["media"][-1].update(mutation)
    with pytest.raises(ValueError):
        validate_strict_prepared_projection(manifest, projection.files)
    fake = _FakeDraftClient()
    source = _write(replace(projection, manifest=manifest), tmp_path / "tampered")
    with pytest.raises(WeChatMpDraftPreparationError):
        await WeChatOfficialAccountDraftOnlyService(client=fake).create_draft(source)
    assert not fake.inline_uploads and not fake.thumb_uploads and not fake.drafts


@pytest.mark.parametrize(
    "mutation",
    [
        {"role": "context"},
        {"path": "assets/unrelated.jpg"},
        {"purpose": "article-cover"},
        {"source_master_byte_size": 1},
        {"derivative_policy_version": "unversioned"},
        {"sha256": "f" * 64},
    ],
)
async def test_tampered_header_descriptor_rejects_before_any_client_call(
    final_cta, tmp_path, mutation
):
    _arguments, projection = final_cta
    manifest = copy.deepcopy(projection.manifest)
    manifest["media"][0].update(mutation)
    with pytest.raises(ValueError):
        validate_strict_prepared_projection(manifest, projection.files)
    fake = _FakeDraftClient()
    source = _write(replace(projection, manifest=manifest), tmp_path / "tampered-header")
    with pytest.raises(WeChatMpDraftPreparationError):
        await WeChatOfficialAccountDraftOnlyService(client=fake).create_draft(source)
    assert not fake.inline_uploads and not fake.thumb_uploads and not fake.drafts


@pytest.mark.parametrize("path", [CHENGYUE_HEADER_PATH, XIAOSAI_FOOTER_PATH])
async def test_framing_bytes_are_not_optional(final_cta, tmp_path, path):
    _inputs_value, projection = final_cta
    changed = {**projection.files, path: b"not the frozen publication"}
    with pytest.raises(ValueError):
        validate_strict_prepared_projection(projection.manifest, changed)
    fake = _FakeDraftClient()
    source = _write(replace(projection, files=changed), tmp_path / "bad-bytes")
    with pytest.raises(WeChatMpDraftPreparationError):
        await WeChatOfficialAccountDraftOnlyService(client=fake).create_draft(source)
    assert not fake.inline_uploads and not fake.thumb_uploads and not fake.drafts


@pytest.mark.parametrize("missing", ["header", "footer", "both"])
def test_current_v5_framing_pair_is_required(final_cta, missing):
    inputs, _projection = final_cta
    changed = {**inputs}
    changed["files"] = dict(inputs["files"])
    if missing in {"header", "both"}:
        changed["header"] = None
        changed["files"].pop(CHENGYUE_HEADER_PATH)
    if missing in {"footer", "both"}:
        changed["footer"] = None
        changed["files"].pop(XIAOSAI_FOOTER_PATH)
    with pytest.raises(ValueError, match="framing"):
        build_strict_prepared_projection(**changed)


@pytest.mark.parametrize(
    "mutation",
    [
        "missing_header",
        "missing_footer",
        "duplicate_header",
        "duplicate_footer",
        "reordered_header",
        "reordered_footer",
    ],
)
async def test_missing_duplicate_or_reordered_framing_rejects_before_client_call(
    final_cta, tmp_path, mutation
):
    _inputs_value, projection = final_cta
    manifest = copy.deepcopy(projection.manifest)
    if mutation == "missing_header":
        manifest["media"].pop(0)
    elif mutation == "missing_footer":
        manifest["media"].pop()
    elif mutation == "duplicate_header":
        manifest["media"].insert(0, copy.deepcopy(manifest["media"][0]))
    elif mutation == "duplicate_footer":
        manifest["media"].append(copy.deepcopy(manifest["media"][-1]))
    elif mutation == "reordered_header":
        manifest["media"][0], manifest["media"][1] = (
            manifest["media"][1],
            manifest["media"][0],
        )
    else:
        manifest["media"][-1], manifest["media"][-2] = (
            manifest["media"][-2],
            manifest["media"][-1],
        )
    with pytest.raises(ValueError):
        validate_strict_prepared_projection(manifest, projection.files)
    fake = _FakeDraftClient()
    source = _write(replace(projection, manifest=manifest), tmp_path / f"framing-{mutation}")
    with pytest.raises(WeChatMpDraftPreparationError):
        await WeChatOfficialAccountDraftOnlyService(client=fake).create_draft(source)
    assert not fake.inline_uploads and not fake.thumb_uploads and not fake.drafts


async def test_footer_bytes_and_required_legacy_v5_pair_are_not_optional(final_cta):
    inputs, _projection = final_cta
    without_footer = {**inputs, "footer": None}
    without_footer["files"] = {k: v for k, v in inputs["files"].items() if k != XIAOSAI_FOOTER_PATH}
    with pytest.raises(ValueError, match="framing"):
        build_strict_prepared_projection(**without_footer)
    for evidence in (
        tuple(replace(p, prompt_version=V4) for p in inputs["evidence"]),
        (replace(inputs["evidence"][0], prompt_version=V4), *inputs["evidence"][1:]),
    ):
        with pytest.raises(ValueError):
            build_strict_prepared_projection(**{**inputs, "evidence": evidence})
