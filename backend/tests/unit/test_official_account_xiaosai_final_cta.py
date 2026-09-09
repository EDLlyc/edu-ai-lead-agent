"""Independent checks for the frozen Xiaosai footer and explicitly blank QR reserve."""

from __future__ import annotations

import copy
import json
import re
from dataclasses import replace
from hashlib import sha256
from html import unescape
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
from app.domain.official_account_local import ArticlePackage, article_package_fingerprint
from app.domain.official_account_strict_layout import STRICT_LAYOUT_PROJECTION_V2_VERSION
from app.domain.official_account_visual_pipeline import (
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_V4_VERSION as V4,
)
from app.domain.official_account_visual_pipeline import (
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_V5_VERSION as V5,
)
from app.domain.official_account_weekly_edition import WeeklyArticleRole
from app.domain.official_account_xiaosai_footer import XIAOSAI_FOOTER_PATH
from app.infrastructure.official_account_catalog import LocalOfficialAccountCatalogMediaProvider
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
    _without_body_captions,
    _without_context_notices,
)
from test_official_account_strict_prepared import _write, strict_projection  # noqa: F401
from test_official_account_visual_preview import captured  # noqa: F401
from test_official_account_xiaosai_references import make_catalog
from test_visual_assets import _write_manifest
from test_wechat_official_account_draft import _FakeDraftClient


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


@pytest.mark.parametrize(
    "characters", [("xiao-sai",), ("sai-xiansheng",), ("xiao-sai", "sai-xiansheng"), ()]
)
async def test_actual_footer_resolver_requires_frozen_exact_xiaosai_catalog(
    strict_projection,  # noqa: F811
    tmp_path,
    characters,
):
    catalog, manifest, _entries, candidates = make_catalog(tmp_path, [characters])
    article = _catalog_bound_article(strict_projection, candidates[0])
    resolver = OfficialAccountLocalMediaResolver(
        image_asset_manifest=str(manifest), image_store=None
    )
    if characters != ("xiao-sai",):
        with pytest.raises(ValueError, match="approved reference changed"):
            await resolver.read_xiaosai_footer(article)
        return
    footer, body = await resolver.read_xiaosai_footer(article)
    assert footer.role == "footer" and footer.path == XIAOSAI_FOOTER_PATH
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
    resolver = OfficialAccountLocalMediaResolver(
        image_asset_manifest=str(manifest), image_store=None
    )
    with pytest.raises(ValueError, match="character identity changed"):
        await resolver.read_xiaosai_footer(article)


@pytest.fixture
async def final_cta(strict_projection, tmp_path):  # noqa: F811
    """Existing six audited fixtures plus one real synthetic approved catalog reference."""
    _catalog, manifest, _entries, candidates = make_catalog(tmp_path / "brand", [("xiao-sai",)])
    inputs = _inputs(strict_projection)
    article = _catalog_bound_article(strict_projection, candidates[0]).model_copy(
        update={"author": "程岳"}
    )
    inputs["article"] = article.model_copy(
        update={"content_fingerprint": article_package_fingerprint(article)}
    )
    inputs["evidence"] = tuple(
        replace(
            proof,
            prompt_version=V5,
            **(
                {
                    "reference_asset_ref": candidates[0].catalog_asset_ref,
                    "reference_publication_sha256": candidates[0].sha256,
                }
                if proof.ordinal == 0
                else {}
            ),
        )
        for proof in inputs["evidence"]
    )
    inputs["layout_projection_version"] = STRICT_LAYOUT_PROJECTION_V2_VERSION
    resolver = OfficialAccountLocalMediaResolver(
        image_asset_manifest=str(manifest), image_store=None
    )
    footer, content = await resolver.read_xiaosai_footer(inputs["article"])
    inputs["footer"] = footer
    inputs["files"][footer.path] = content
    return inputs, manifest, build_strict_prepared_projection(**inputs)


async def test_actual_prepared_owner_consumer_and_http_keep_one_blank_qr_footer(
    final_cta, tmp_path
):
    inputs, catalog_manifest, projection = final_cta
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

    resolver = Resolver(image_asset_manifest=str(catalog_manifest), image_store=None)
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
    assert html.count("我是程岳") == html.count("二维码待补") == html.count("认识小赛") == 1
    assert html.count("欢迎关注") == 1 and "扫码" not in html
    tail = html[len(_before_signature(html, "程岳")) :]
    assert len(re.findall(r"<img\b", tail)) == 1
    assert "href=" not in tail and "http" not in tail and "<svg" not in tail
    reserve = re.search(r'<section style="[^"]*dashed[^>]*>(.*?)</section>', tail)[1]
    assert re.sub(r"<[^>]*>", "", reserve) == "二维码待补" and "<img" not in reserve
    assert all("qr" not in path.lower() for path in projection.files)
    assert prepared.author == projection.manifest["author"] == "程岳"
    assert len(projection.manifest["visual_evidence"]) == 6
    assert projection.manifest["media"][-1] == inputs["footer"].model_dump(mode="json")
    assert [m.path for m in prepared.body_media] == re.findall(r'<img src="([^"]+)"', html)
    assert prepared.body_media[-1].path == XIAOSAI_FOOTER_PATH
    assert prepared.body_media[-1].body == inputs["files"][XIAOSAI_FOOTER_PATH]
    assert prepared.body_media[-1].body not in [
        m.body for m in (*prepared.body_media[:-1], prepared.cover)
    ]

    historical_inputs = {
        **inputs,
        "footer": None,
        "files": {k: v for k, v in inputs["files"].items() if k != XIAOSAI_FOOTER_PATH},
        "evidence": tuple(replace(p, prompt_version=V4) for p in inputs["evidence"]),
    }
    old_html = (
        build_strict_prepared_projection(**historical_inputs).files["article-body.html"].decode()
    )
    assert _before_signature(html, "程岳") == _before_signature(
        _without_context_notices(_without_body_captions(old_html)), "程岳"
    )
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
    assert uploaded == [m.body for m in prepared.body_media] and len(uploaded) == 7
    payload = payloads[0]
    assert payload["author"] == "程岳" and payload["content"].count("二维码待补") == 1
    assert re.findall(r'<img src="([^"]+)"', payload["content"]) == [
        f"https://mmbiz.qpic.cn/inline-{i}.jpg" for i in range(1, 8)
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
        {"qr_state": "ready"},
        {"purpose": "add-contact"},
        {"sha256": "f" * 64},
    ],
)
async def test_tampered_footer_descriptor_rejects_before_any_client_call(
    final_cta, tmp_path, mutation
):
    _arguments, _manifest, projection = final_cta
    manifest = copy.deepcopy(projection.manifest)
    manifest["media"][-1].update(mutation)
    with pytest.raises(ValueError):
        validate_strict_prepared_projection(manifest, projection.files)
    fake = _FakeDraftClient()
    source = _write(replace(projection, manifest=manifest), tmp_path / "tampered")
    with pytest.raises(WeChatMpDraftPreparationError):
        await WeChatOfficialAccountDraftOnlyService(client=fake).create_draft(source)
    assert not fake.inline_uploads and not fake.thumb_uploads and not fake.drafts


async def test_footer_bytes_and_required_v5_pair_are_not_optional(final_cta, tmp_path):
    inputs, _catalog, projection = final_cta
    changed = {**projection.files, XIAOSAI_FOOTER_PATH: b"not the frozen publication"}
    with pytest.raises(ValueError):
        validate_strict_prepared_projection(projection.manifest, changed)
    fake = _FakeDraftClient()
    source = _write(replace(projection, files=changed), tmp_path / "bad-bytes")
    with pytest.raises(WeChatMpDraftPreparationError):
        await WeChatOfficialAccountDraftOnlyService(client=fake).create_draft(source)
    assert not fake.inline_uploads and not fake.thumb_uploads and not fake.drafts
    without_footer = {**inputs, "footer": None}
    without_footer["files"] = {k: v for k, v in inputs["files"].items() if k != XIAOSAI_FOOTER_PATH}
    with pytest.raises(ValueError, match="footer"):
        build_strict_prepared_projection(**without_footer)
    for evidence in (
        tuple(replace(p, prompt_version=V4) for p in inputs["evidence"]),
        (replace(inputs["evidence"][0], prompt_version=V4), *inputs["evidence"][1:]),
    ):
        with pytest.raises(ValueError):
            build_strict_prepared_projection(**{**inputs, "evidence": evidence})
