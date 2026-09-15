"""Versioned readable attribution keeps provenance while current drafts expose no links."""

# ruff: noqa: RUF001, F811 -- Chinese copy and imported pytest fixture names.

from __future__ import annotations

import copy
import json
from dataclasses import replace
from hashlib import sha256
from html import unescape
from typing import Any
from uuid import UUID

import pytest
from app.application.ports.wechat_official_account import WeChatMpDraftPreparationError
from app.application.services.official_account_strict_prepared import (
    StrictPreparedProjection,
    build_strict_prepared_projection,
    validate_strict_prepared_projection,
)
from app.application.services.wechat_official_account_draft import (
    WeChatOfficialAccountDraftOnlyService,
    WeChatOfficialAccountDraftPreparer,
)
from app.domain.official_account_local import (
    ArticlePackage,
    ArticleSourceProjection,
    article_package_fingerprint,
)
from app.domain.official_account_source_presentation import (
    NO_LINK_SOURCE_PRESENTATION_VERSION,
    READABLE_SOURCE_PRESENTATION_VERSION,
    render_readable_sources,
    source_presentation_content_url,
    source_publisher_name,
)
from test_official_account_body_caption_visibility import _inputs
from test_official_account_strict_prepared import _write, strict_projection  # noqa: F401
from test_official_account_visual_preview import captured  # noqa: F401
from test_official_account_xiaosai_final_cta import final_cta  # noqa: F401
from test_wechat_official_account_draft import _FakeDraftClient

_URL = "https://education.news.cn/20260805/fixture/c.html"


def _source(url: str = _URL, name: str = "education.news.cn", ordinal: int = 1):
    return ArticleSourceProjection(evidence_id=UUID(int=ordinal), source_name=name, source_url=url)


@pytest.mark.parametrize(
    ("url", "name", "expected"),
    [
        (_URL, "education.news.cn", "新华网"),
        ("https://EDUCATION.NEWS.CN/article", "domain", "新华网"),
        ("https://www.xinhuanet.com/article", "domain", "新华网"),
        ("https://www.gov.cn/article", "domain", "中国政府网"),
        ("https://www.moe.gov.cn/article", "domain", "教育部网站"),
        ("https://province.gov.cn/article", "省政府网站", "省政府网站"),
        ("https://news.cn.example.com/article", "未识别来源", "未识别来源"),
        ("https://fakenews.cn/article", "未识别来源", "未识别来源"),
        ("https://example.com/news.cn/article", "科学编辑部", "科学编辑部"),
    ],
)
def test_publisher_mapping_is_host_bound_not_a_substring(url, name, expected):
    assert source_publisher_name(_source(url, name)) == expected


def test_duplicate_evidence_is_one_source_without_invented_date_or_original_publisher(
    strict_projection: StrictPreparedProjection,
):
    article = ArticlePackage.model_validate(strict_projection.manifest["article"])
    article = article.model_copy(update={"sources": (_source(), _source(ordinal=2))})
    before = article.model_dump_json()
    html = render_readable_sources(article)
    assert html.count("新闻来源：新华网") == 1
    assert "完整报道见文末“阅读原文”。" in html
    assert all(word not in html for word in ("<a", "查看权威原文", "education.news.cn", "2026"))
    assert "中国青年报" not in html
    assert article.model_dump_json() == before


def test_distinct_same_domain_urls_and_queries_remain_exact_copyable_references(
    strict_projection: StrictPreparedProjection,
):
    article = ArticlePackage.model_validate(strict_projection.manifest["article"])
    other = _URL + "?story=2&view=full"
    third = _URL + "?story=3&title='quoted'"
    article = article.model_copy(
        update={"sources": (_source(), _source(ordinal=2), _source(other), _source(third))}
    )
    html = render_readable_sources(article)
    assert html.count("新华网") == 3
    assert "01 · 新华网" in html and "03 · 新华网" in html
    assert other in unescape(html) and third in unescape(html)
    assert "&amp;" in html and "<a" not in html
    assert html.index("story=2") < html.index("story=3")


def test_source_name_is_escaped(strict_projection: StrictPreparedProjection):
    article = ArticlePackage.model_validate(strict_projection.manifest["article"])
    article = article.model_copy(
        update={"sources": (_source("https://example.com/report", "科学 & <研究>"),)}
    )
    html = render_readable_sources(article)
    assert "科学 &amp; &lt;研究&gt;" in html and "<研究>" not in html


def test_current_no_link_presentation_keeps_names_without_urls_or_read_more(
    strict_projection: StrictPreparedProjection,
):
    article = ArticlePackage.model_validate(strict_projection.manifest["article"])
    other = _URL + "?story=2&view=full"
    article = article.model_copy(
        update={"sources": (_source(), _source(ordinal=2), _source(other, ordinal=3))}
    )
    html = render_readable_sources(article, version=NO_LINK_SOURCE_PRESENTATION_VERSION)
    assert html.count("新华网") == 2
    assert all(
        value not in html
        for value in ("<a", "href=", "http", "阅读原文", "查看原文", "查看权威原文")
    )
    assert source_presentation_content_url(article, NO_LINK_SOURCE_PRESENTATION_VERSION) is None


async def test_new_presentation_rebuild_and_native_target_preserve_legacy(final_cta, tmp_path):
    inputs, legacy = final_cta
    before_files = dict(legacy.files)
    before_manifest = copy.deepcopy(legacy.manifest)
    article = inputs["article"].model_copy(update={"sources": (_source(), _source(ordinal=2))})
    article = article.model_copy(
        update={"content_fingerprint": article_package_fingerprint(article)}
    )
    inputs = {
        **inputs,
        "article": article,
        "source_presentation": READABLE_SOURCE_PRESENTATION_VERSION,
    }
    current = build_strict_prepared_projection(**inputs)
    validate_strict_prepared_projection(current.manifest, current.files)
    source = _write(current, tmp_path / "current")
    prepared = WeChatOfficialAccountDraftPreparer().prepare(source)
    assert prepared.content_source_url == current.manifest["content_source_url"] == _URL
    assert prepared.body_html.count("新闻来源：新华网") == 1
    assert prepared.author == "程岳" and len(prepared.body_media) == 8
    assert current.manifest["article"] == article.model_dump(mode="json")
    assert current.manifest["visual_evidence"] == legacy.manifest["visual_evidence"]
    assert {k: v for k, v in current.files.items() if k != "article-body.html"} == {
        k: v for k, v in legacy.files.items() if k != "article-body.html"
    }
    assert (
        WeChatOfficialAccountDraftPreparer()
        .prepare(replace(source, content_source_url=_URL))
        .content_source_url
        == _URL
    )
    client = _FakeDraftClient()
    with pytest.raises(WeChatMpDraftPreparationError):
        await WeChatOfficialAccountDraftOnlyService(client=client).create_draft(
            replace(source, content_source_url="https://example.com/unrelated")
        )
    assert not client.inline_uploads and not client.thumb_uploads and not client.drafts
    assert legacy.files == before_files and legacy.manifest == before_manifest
    assert "source_presentation_version" not in legacy.manifest
    assert "content_source_url" not in legacy.manifest
    validate_strict_prepared_projection(legacy.manifest, legacy.files)
    assert (
        WeChatOfficialAccountDraftPreparer()
        .prepare(_write(legacy, tmp_path / "legacy"))
        .content_source_url
        is None
    )


async def test_no_link_presentation_binds_absent_native_target(final_cta, tmp_path):
    inputs, _legacy = final_cta
    current = build_strict_prepared_projection(
        **inputs, source_presentation=NO_LINK_SOURCE_PRESENTATION_VERSION
    )
    validate_strict_prepared_projection(current.manifest, current.files)
    source = _write(current, tmp_path / "no-link")
    prepared = WeChatOfficialAccountDraftPreparer().prepare(source)
    assert current.manifest["content_source_url"] is None
    assert prepared.content_source_url is None
    assert all(
        value not in prepared.body_html
        for value in ("href=", "http", "阅读原文", "查看原文", "查看权威原文")
    )

    client = _FakeDraftClient()
    with pytest.raises(WeChatMpDraftPreparationError):
        await WeChatOfficialAccountDraftOnlyService(client=client).create_draft(
            replace(source, content_source_url=_URL)
        )
    assert not client.inline_uploads and not client.thumb_uploads and not client.drafts


@pytest.mark.parametrize("mutation", ["version", "missing_version", "url", "missing_url", "body"])
async def test_resealed_source_changes_fail_before_social_calls(final_cta, tmp_path, mutation):
    inputs, _legacy = final_cta
    current = build_strict_prepared_projection(
        **inputs, source_presentation=READABLE_SOURCE_PRESENTATION_VERSION
    )
    manifest = copy.deepcopy(current.manifest)
    files = dict(current.files)
    if mutation == "version":
        manifest["source_presentation_version"] = "future-unknown"
    elif mutation == "missing_version":
        del manifest["source_presentation_version"]
    elif mutation == "url":
        manifest["content_source_url"] = "https://example.com/another"
    elif mutation == "missing_url":
        del manifest["content_source_url"]
    else:
        files["article-body.html"] = files["article-body.html"].replace(
            "阅读原文".encode(), "虚假原文".encode()
        )
        for item in manifest["files"]:
            if item["path"] == "article-body.html":
                item["sha256"] = sha256(files[item["path"]]).hexdigest()
                item["byte_size"] = len(files[item["path"]])
    identity = {
        k: v for k, v in manifest.items() if k not in {"child_fingerprint", "content_fingerprint"}
    }

    def fingerprint(value: dict[str, Any]) -> str:
        return sha256(
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    manifest["content_fingerprint"] = fingerprint(identity)
    manifest["child_fingerprint"] = fingerprint(
        {**identity, "content_fingerprint": manifest["content_fingerprint"]}
    )
    client = _FakeDraftClient()
    with pytest.raises(WeChatMpDraftPreparationError):
        await WeChatOfficialAccountDraftOnlyService(client=client).create_draft(
            _write(replace(current, manifest=manifest, files=files), tmp_path / mutation)
        )
    assert not client.inline_uploads and not client.thumb_uploads and not client.drafts


def test_legacy_v4_cannot_implicitly_opt_in(strict_projection: StrictPreparedProjection):
    with pytest.raises(ValueError, match="prospective V5"):
        build_strict_prepared_projection(
            **_inputs(strict_projection), source_presentation=READABLE_SOURCE_PRESENTATION_VERSION
        )


@pytest.mark.parametrize(
    "url",
    [
        "https://education.news.cn/invalid path",
        "https://education.news.cn:8443/article",
        "https://education.news.cn/" + "x" * 1024,
    ],
)
async def test_native_source_retains_existing_url_validation(final_cta, tmp_path, url):
    inputs, _legacy = final_cta
    article = inputs["article"].model_copy(update={"sources": (_source(url),)})
    article = article.model_copy(
        update={"content_fingerprint": article_package_fingerprint(article)}
    )
    current = build_strict_prepared_projection(
        **{**inputs, "article": article},
        source_presentation=READABLE_SOURCE_PRESENTATION_VERSION,
    )
    client = _FakeDraftClient()
    with pytest.raises(WeChatMpDraftPreparationError):
        await WeChatOfficialAccountDraftOnlyService(client=client).create_draft(
            _write(current, tmp_path / "invalid-url")
        )
    assert not client.inline_uploads and not client.thumb_uploads and not client.drafts
