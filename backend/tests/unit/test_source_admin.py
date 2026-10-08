# ruff: noqa: RUF001
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.core.errors import ParseError
from app.domain.entities import DiscoveredItem, FetchedResponse, SourceProfile
from app.domain.enums import SourceTier
from app.domain.source_admin import (
    GENERIC_HTML_CONNECTOR_KEY,
    GENERIC_RSS_CONNECTOR_KEY,
    SourceConfigError,
    build_operator_source_draft,
    looks_like_article_path,
    operator_version_fingerprint,
    parse_connector_config,
)
from app.infrastructure.ingestion.connectors import get_connector


def _profile(connector_key: str, config: dict[str, object]) -> SourceProfile:
    return SourceProfile(
        source_id=uuid4(),
        source_version_id=uuid4(),
        slug="ops-example",
        display_name="示例教育网",
        organization_type="authoritative_media",
        tier=SourceTier.B,
        connector_key=connector_key,
        entry_url="https://edu.example.cn/news/",
        allowed_hosts=("edu.example.cn",),
        allowed_path_prefixes=("/",),
        connector_version="generic-1.0.0",
        parser_version="generic-1.0.0",
        connector_config=config,
    )


def _response(url: str, body: str, media_type: str = "text/html") -> FetchedResponse:
    data = body.encode("utf-8")
    return FetchedResponse(
        requested_url=url,
        final_url=url,
        status_code=200,
        media_type=media_type,
        body=data,
        sha256="0" * 64,
        fetched_at=datetime(2026, 10, 8, tzinfo=UTC),
        headers={},
    )


def test_config_is_cleaned_bounded_and_selectors_are_compiled() -> None:
    config = parse_connector_config(
        {
            "kind": "html",
            "link_contains": [" /content_ ", "", "/content_"],
            "content_selectors": ["#article"],
        }
    )
    assert config.link_contains == ("/content_",)
    assert config.content_selectors == ("#article",)
    assert config.connector_key == GENERIC_HTML_CONNECTOR_KEY

    for bad, message in [
        ({"kind": "pdf"}, "网页或 RSS"),
        ({"kind": "html", "content_selectors": ["div[["]}, "不是有效的 CSS"),
        ({"kind": "html", "link_contains": ["a b"]}, "不能有空格"),
        ({"kind": "html", "link_contains": [f"/{i}" for i in range(6)]}, "最多 5 项"),
        ({"kind": "rss", "link_contains": ["/a"]}, "RSS 不需要"),
        ({"kind": "html", "script": "x"}, "不认识"),
        ("html", "格式不对"),
    ]:
        with pytest.raises(SourceConfigError, match=message):
            parse_connector_config(bad)


def test_operator_drafts_need_a_public_https_url() -> None:
    draft = build_operator_source_draft(
        display_name=" 示例教育网 ",
        organization_type="authoritative_media",
        tier="B",
        entry_url="https://Edu.Example.cn/news/",
        config={"kind": "rss"},
    )
    assert draft.display_name == "示例教育网"
    assert draft.entry_url == "https://edu.example.cn/news/"
    assert draft.host == "edu.example.cn"
    for url in [
        "http://edu.example.cn/",
        "https://127.0.0.1/",
        "https://localhost/",
        "https://intranet.local/",
        "https://edu.example.cn:8443/",
    ]:
        with pytest.raises(SourceConfigError, match="公开的 https"):
            build_operator_source_draft(
                display_name="示例",
                organization_type="authoritative_media",
                tier="B",
                entry_url=url,
                config={"kind": "rss"},
            )


def test_fingerprint_changes_with_any_fetch_setting() -> None:
    def draft(**changes: object):  # type: ignore[no-untyped-def]
        values: dict[str, object] = {
            "display_name": "示例",
            "organization_type": "authoritative_media",
            "tier": "B",
            "entry_url": "https://edu.example.cn/news/",
            "config": {"kind": "html"},
        }
        values.update(changes)
        return build_operator_source_draft(**values)  # type: ignore[arg-type]

    base = operator_version_fingerprint(draft(), robots_status="allowed", rate_limit_seconds=3.0)
    assert base == operator_version_fingerprint(
        draft(display_name="改了名字"), robots_status="allowed", rate_limit_seconds=3.0
    )
    for changed in [
        draft(tier="A"),
        draft(entry_url="https://edu.example.cn/list/"),
        draft(config={"kind": "html", "link_contains": ["/content_"]}),
    ]:
        assert (
            operator_version_fingerprint(changed, robots_status="allowed", rate_limit_seconds=3.0)
            != base
        )


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("/news/2026-10/08/content_123.htm", True),
        ("/2026/1008/abc.html", True),
        ("/a/20261008/xyz", True),
        ("/news/12345.shtml", True),
        ("/news/", False),
        ("/about.html", False),
        ("/list_2.html", False),
        ("/", False),
    ],
)
def test_article_path_heuristic(path: str, expected: bool) -> None:
    assert looks_like_article_path(path) is expected


LIST_PAGE = """
<html><body>
  <nav><a href="/about.html">关于</a><a href="/news/">新闻</a></nav>
  <div class="list">
    <a href="/news/2026-10/08/content_1001.htm">人工智能走进中小学课堂</a>
    <a href="/news/2026-10/07/content_1000.htm">青少年科学营开营</a>
    <a href="https://ads.example.com/2026/10/08/x.html">外站广告</a>
  </div>
  <div class="side"><a href="/news/2026-10/01/content_900.htm">旧闻</a></div>
</body></html>
"""


def test_generic_html_finds_article_links_by_heuristic_or_pattern() -> None:
    profile = _profile(GENERIC_HTML_CONNECTOR_KEY, {"kind": "html"})
    connector = get_connector(GENERIC_HTML_CONNECTOR_KEY, profile.connector_config)
    items = connector.discover(
        _response("https://edu.example.cn/news/", LIST_PAGE), profile, limit=10
    )
    assert [item.title for item in items] == ["人工智能走进中小学课堂", "青少年科学营开营", "旧闻"]

    narrowed = {"kind": "html", "list_selectors": [".list"], "link_contains": ["content_10"]}
    profile = _profile(GENERIC_HTML_CONNECTOR_KEY, narrowed)
    items = get_connector(GENERIC_HTML_CONNECTOR_KEY, narrowed).discover(
        _response("https://edu.example.cn/news/", LIST_PAGE), profile, limit=10
    )
    assert [item.url for item in items] == [
        "https://edu.example.cn/news/2026-10/08/content_1001.htm",
        "https://edu.example.cn/news/2026-10/07/content_1000.htm",
    ]


def test_generic_html_extracts_the_configured_body() -> None:
    config = {"kind": "html", "content_selectors": [".body"]}
    profile = _profile(GENERIC_HTML_CONNECTOR_KEY, config)
    page = (
        "<html><head><title>人工智能走进中小学课堂_示例教育网</title></head><body>"
        "<div class='nav'>首页 新闻 关于我们</div>"
        f"<div class='body'>{'各地中小学开设人工智能课程，学生动手搭建机器人。' * 6}</div>"
        "<p>发布时间：2026-10-08 09:30</p></body></html>"
    )
    item = DiscoveredItem(
        source_item_id="content_1001.htm",
        url="https://edu.example.cn/news/2026-10/08/content_1001.htm",
        title="人工智能走进中小学课堂",
        published_at=None,
    )
    document = get_connector(GENERIC_HTML_CONNECTOR_KEY, config).extract(
        _response(item.url, page), item, profile
    )
    assert document.title == "人工智能走进中小学课堂"
    assert document.clean_text.startswith("各地中小学开设人工智能课程")
    assert "首页" not in document.clean_text
    assert document.published_at == datetime(2026, 10, 8, 1, 30, tzinfo=UTC)
    assert document.extraction_metadata["selector"] == ".body"


FEED = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><title>示例</title>
  <item><title>科学教育新进展</title><link>https://edu.example.cn/a/20261008/1.html</link>
    <pubDate>Wed, 08 Oct 2026 01:00:00 GMT</pubDate></item>
  <item><title>外站转载</title><link>https://other.example.com/x.html</link></item>
  <item><title>重复</title><link>https://edu.example.cn/a/20261008/1.html</link></item>
  <item><title>没有日期</title><link>https://edu.example.cn/a/20261007/2.html</link></item>
</channel></rss>"""


def test_rss_lists_approved_unique_entries_with_dates() -> None:
    profile = _profile(GENERIC_RSS_CONNECTOR_KEY, {"kind": "rss"})
    items = get_connector(GENERIC_RSS_CONNECTOR_KEY, {"kind": "rss"}).discover(
        _response("https://edu.example.cn/feed.xml", FEED, "application/rss+xml"),
        profile,
        limit=10,
    )
    assert [(item.title, item.published_at) for item in items] == [
        ("科学教育新进展", datetime(2026, 10, 8, 1, 0, tzinfo=UTC)),
        ("没有日期", None),
    ]
    with pytest.raises(ParseError):
        get_connector(GENERIC_RSS_CONNECTOR_KEY, {"kind": "rss"}).discover(
            _response("https://edu.example.cn/feed.xml", "<rss></rss>"), profile, limit=10
        )


def test_generic_keys_refuse_missing_or_mismatched_settings() -> None:
    with pytest.raises(ParseError):
        get_connector(GENERIC_HTML_CONNECTOR_KEY, None)
    with pytest.raises(ParseError):
        get_connector(GENERIC_HTML_CONNECTOR_KEY, {"kind": "rss"})
    with pytest.raises(ParseError):
        get_connector("unknown_v1")
