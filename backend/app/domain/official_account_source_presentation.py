"""Versioned source attribution for historical and current WeChat draft bodies."""

# ruff: noqa: RUF001 -- Chinese editorial punctuation is intentional.

from __future__ import annotations

from html import escape
from typing import Final, Literal
from urllib.parse import urlsplit

from app.domain.official_account_local import ArticlePackage, ArticleSourceProjection

READABLE_SOURCE_PRESENTATION_VERSION: Final = "wechat-source-presentation-v1-readable"
NO_LINK_SOURCE_PRESENTATION_VERSION: Final = "wechat-source-presentation-v2-no-links"
CURRENT_SOURCE_PRESENTATION_VERSION: Final = NO_LINK_SOURCE_PRESENTATION_VERSION
SourcePresentationVersion = Literal[
    "wechat-source-presentation-v1-readable",
    "wechat-source-presentation-v2-no-links",
]


def source_presentation_version(value: object) -> SourcePresentationVersion | None:
    """Missing is the literal historical renderer, never the current default."""
    if value is None:
        return None
    if type(value) is str and value == READABLE_SOURCE_PRESENTATION_VERSION:
        return READABLE_SOURCE_PRESENTATION_VERSION
    if type(value) is str and value == NO_LINK_SOURCE_PRESENTATION_VERSION:
        return NO_LINK_SOURCE_PRESENTATION_VERSION
    raise ValueError("source presentation version is unsupported")


def source_publisher_name(source: ArticleSourceProjection) -> str:
    """Identify a publisher, not an authority tier or an unrecorded original outlet."""
    hostname = (urlsplit(source.source_url).hostname or "").casefold()
    for domain, name in (("news.cn", "新华网"), ("xinhuanet.com", "新华网")):
        if hostname == domain or hostname.endswith("." + domain):
            return name
    exact_names = {
        "gov.cn": "中国政府网",
        "www.gov.cn": "中国政府网",
        "moe.gov.cn": "教育部网站",
        "www.moe.gov.cn": "教育部网站",
    }
    if hostname in exact_names:
        return exact_names[hostname]
    # Unknown domains are not promoted merely because they contain a known suffix.
    return source.source_name


def source_presentation_content_url(
    article: ArticlePackage, version: SourcePresentationVersion
) -> str | None:
    """Bind the old native target while making the current no-link policy explicit."""
    normalized_version = source_presentation_version(version)
    if normalized_version == READABLE_SOURCE_PRESENTATION_VERSION:
        return article.sources[0].source_url
    return None


def render_readable_sources(
    article: ArticlePackage,
    *,
    version: SourcePresentationVersion = READABLE_SOURCE_PRESENTATION_VERSION,
) -> str:
    """Render deduplicated attribution without changing historical V1 bytes."""
    normalized_version = source_presentation_version(version)
    unique: dict[str, ArticleSourceProjection] = {}
    for source in article.sources:
        unique.setdefault(source.source_url, source)
    rows: list[str] = []
    for index, source in enumerate(unique.values()):
        prefix = "新闻来源：" if len(unique) == 1 else f"{index + 1:02d} · "
        label = prefix + source_publisher_name(source)
        rows.append(
            '<p style="font-size:13px;color:#26364A;line-height:1.7;margin:0 0 8px;">'
            f'<span leaf="">{escape(label, quote=False)}</span></p>'
        )
        if normalized_version == READABLE_SOURCE_PRESENTATION_VERSION and index > 0:
            # WeChat strips external anchors. Other references stay exact, copyable
            # URLs, not dead "view source" labels or invented article titles.
            rows.append(
                '<p style="font-size:11px;color:#607086;line-height:1.7;'
                'margin:0 0 8px;word-break:break-all;">'
                f'<span leaf="">{escape(source.source_url, quote=False)}</span></p>'
            )
    hint = None
    if normalized_version == READABLE_SOURCE_PRESENTATION_VERSION:
        hint = (
            "完整报道见文末“阅读原文”。"
            if len(unique) == 1
            else "第一条来源见文末“阅读原文”，其余来源可复制网址查看。"
        )
    # Registered Xiaosai information-card component; no external stylesheet/link.
    return (
        '<section style="margin:28px 20px;padding:12px 16px;background:#F3FBFF;'
        'border-radius:8px;border:1px solid #C7DDEF;">'
        + "".join(rows)
        + (
            '<p style="font-size:13px;color:#26364A;margin:0;line-height:1.7;">'
            f'<span leaf="">{hint}</span></p>'
            if hint is not None
            else ""
        )
        + "</section>"
    )
