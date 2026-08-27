from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, Protocol
from urllib.parse import urljoin, urlsplit, urlunsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import trafilatura
from bs4 import BeautifulSoup, Tag

from app.core.errors import ParseError, PolicyRejectedError
from app.core.security import validate_allowlist
from app.domain.entities import (
    DiscoveredItem,
    ExtractedDocument,
    FetchedResponse,
    SourceImageReference,
    SourceProfile,
)

SOURCE_IMAGE_EXTRACTION_VERSION = "source-image-extractor-v1"
_SOURCE_IMAGE_LIMIT = 5
_IMAGE_FILE_SUFFIXES = (".jpg", ".jpeg", ".png", ".webp")
_NON_EDITORIAL_IMAGE_HINTS = (
    "avatar",
    "badge",
    "banner",
    "icon",
    "logo",
    "nav",
    "qr",
    "qrcode",
    "share",
    "sprite",
    "tracking",
)


class SourceConnector(Protocol):
    def discover(
        self, response: FetchedResponse, profile: SourceProfile, *, limit: int
    ) -> list[DiscoveredItem]: ...

    def extract(
        self,
        response: FetchedResponse,
        item: DiscoveredItem,
        profile: SourceProfile,
    ) -> ExtractedDocument: ...


def _canonical_url(value: str) -> str:
    parts = urlsplit(value)
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path, "", ""))


def _decode(response: FetchedResponse) -> str:
    for encoding in ("utf-8", "gb18030"):
        try:
            return response.body.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise ParseError("source response encoding is unsupported")


def _parse_datetime(value: str | None, timezone: str) -> datetime | None:
    if not value:
        return None
    normalized = value.strip().replace("年", "-").replace("月", "-").replace("日", "")
    match = re.search(
        r"(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})(?:[ T](\d{1,2}):(\d{2}))?", normalized
    )
    if not match:
        return None
    year, month, day, hour, minute = match.groups()
    try:
        source_timezone = ZoneInfo(timezone)
    except ZoneInfoNotFoundError as error:
        raise ParseError("source timezone is invalid") from error
    local_time = datetime(
        int(year), int(month), int(day), int(hour or 0), int(minute or 0), tzinfo=source_timezone
    )
    return local_time.astimezone(UTC)


def _approved_discovered_url(value: str, profile: SourceProfile) -> str | None:
    try:
        return validate_allowlist(
            value,
            allowed_hosts=profile.allowed_hosts,
            allowed_path_prefixes=profile.allowed_path_prefixes,
            allow_http_fallback=profile.allow_http_fallback,
        )
    except PolicyRejectedError:
        return None


def _extract_title(soup: BeautifulSoup) -> str | None:
    for selector in ("meta[property='og:title']", "meta[name='ArticleTitle']"):
        node = soup.select_one(selector)
        if isinstance(node, Tag) and node.get("content"):
            return str(node.get("content")).strip()
    navigation_titles = {"全部导航", "导航", "首页"}
    for heading in soup.find_all("h1"):
        title = heading.get_text(" ", strip=True)
        if title and title not in navigation_titles:
            return title
    if soup.title:
        return soup.title.get_text(" ", strip=True).split("_")[0].strip()
    return None


def _bounded_text(value: str | None, limit: int) -> str | None:
    normalized = " ".join((value or "").split())
    return normalized[:limit] or None


def _image_url_from_node(node: Tag) -> str | None:
    for attribute in ("data-src", "data-original", "data-lazy-src", "src"):
        value = str(node.get(attribute) or "").strip()
        if value:
            return value
    srcset = str(node.get("srcset") or "").strip()
    if srcset:
        return srcset.split(",", 1)[0].strip().split(" ", 1)[0]
    return None


def _approved_source_image_url(
    raw_url: str,
    *,
    detail_url: str,
    profile: SourceProfile,
) -> str | None:
    candidate = urljoin(detail_url, raw_url.strip())
    parts = urlsplit(candidate)
    detail_parts = urlsplit(detail_url)
    if (
        parts.query
        or parts.fragment
        or parts.hostname is None
        or detail_parts.hostname is None
        or parts.hostname.rstrip(".").casefold() != detail_parts.hostname.rstrip(".").casefold()
        or parts.path.casefold().endswith((".svg", ".gif"))
    ):
        return None
    try:
        approved = validate_allowlist(
            candidate,
            allowed_hosts=profile.allowed_hosts,
            allowed_path_prefixes=profile.allowed_path_prefixes,
            allow_http_fallback=False,
        )
    except PolicyRejectedError:
        return None
    approved_parts = urlsplit(approved)
    if approved_parts.scheme != "https" or approved_parts.query:
        return None
    return urlunsplit((approved_parts.scheme, approved_parts.netloc, approved_parts.path, "", ""))


def _looks_editorial_image(node: Tag, raw_url: str) -> bool:
    identity = " ".join(
        str(node.get(attribute) or "") for attribute in ("class", "id", "alt", "title")
    ).casefold()
    path = urlsplit(raw_url).path.casefold()
    if any(hint in identity or hint in path for hint in _NON_EDITORIAL_IMAGE_HINTS):
        return False
    try:
        width = int(str(node.get("width") or "0").removesuffix("px"))
        height = int(str(node.get("height") or "0").removesuffix("px"))
    except ValueError:
        width = height = 0
    if width and height and (width < 240 or height < 135):
        return False
    return not path or path.endswith(_IMAGE_FILE_SUFFIXES) or "." not in path.rsplit("/", 1)[-1]


def _figure_metadata(node: Tag) -> tuple[str | None, str | None]:
    figure = node.find_parent("figure")
    caption_node = figure.find("figcaption") if isinstance(figure, Tag) else None
    caption = _bounded_text(
        caption_node.get_text(" ", strip=True) if isinstance(caption_node, Tag) else None,
        300,
    )
    credit = None
    for candidate in (
        figure.select_one("[class*='credit'], [class*='source'], [class*='author']")
        if isinstance(figure, Tag)
        else None,
        node.find_next_sibling(class_=re.compile(r"credit|source|author", re.I)),
    ):
        if isinstance(candidate, Tag):
            credit = _bounded_text(candidate.get_text(" ", strip=True), 200)
            if credit:
                break
    return caption, credit


def _extract_source_images(
    *,
    soup: BeautifulSoup,
    content_root: Tag | None,
    detail_url: str,
    profile: SourceProfile,
) -> tuple[SourceImageReference, ...]:
    candidates: list[tuple[str, str, str | None, str | None, str | None]] = []
    og_image = soup.select_one("meta[property='og:image'], meta[name='og:image']")
    if isinstance(og_image, Tag) and og_image.get("content"):
        candidates.append((str(og_image.get("content")), "lead", None, None, None))
    if content_root is not None:
        for node in content_root.find_all("img"):
            if not isinstance(node, Tag):
                continue
            raw_url = _image_url_from_node(node)
            if raw_url is None or not _looks_editorial_image(node, raw_url):
                continue
            caption, credit = _figure_metadata(node)
            candidates.append(
                (
                    raw_url,
                    "body",
                    _bounded_text(str(node.get("alt") or ""), 200),
                    caption,
                    credit,
                )
            )
    references: list[SourceImageReference] = []
    seen: set[str] = set()
    for raw_url, role, alt_text, caption, credit in candidates:
        approved = _approved_source_image_url(
            raw_url,
            detail_url=detail_url,
            profile=profile,
        )
        if approved is None or approved in seen:
            continue
        seen.add(approved)
        references.append(
            SourceImageReference(
                image_url=approved,
                source_page_url=detail_url,
                ordinal=len(references),
                role=role,
                alt_text=alt_text,
                caption=caption,
                credit=credit,
            )
        )
        if len(references) >= _SOURCE_IMAGE_LIMIT:
            break
    return tuple(references)


class GovernmentJsonConnector:
    def __init__(self, *, reject_query: bool = False) -> None:
        self._reject_query = reject_query

    def discover(
        self, response: FetchedResponse, profile: SourceProfile, *, limit: int
    ) -> list[DiscoveredItem]:
        try:
            payload = json.loads(_decode(response))
        except json.JSONDecodeError as error:
            raise ParseError("government policy list is invalid JSON") from error
        records = _find_policy_records(payload)
        items: list[DiscoveredItem] = []
        for record in records:
            raw_url = str(record.get("URL") or record.get("url") or "").strip()
            if not raw_url:
                continue
            resolved_url = urljoin(response.final_url, raw_url)
            resolved_parts = urlsplit(resolved_url)
            if self._reject_query and (resolved_parts.query or resolved_parts.fragment):
                continue
            candidate_url = _canonical_url(resolved_url)
            url = _approved_discovered_url(candidate_url, profile)
            if url is None:
                continue
            title = str(record.get("TITLE") or record.get("title") or "").strip() or None
            item_id = urlsplit(url).path.rstrip("/").rsplit("/", 1)[-1]
            items.append(
                DiscoveredItem(
                    source_item_id=item_id,
                    url=url,
                    title=title,
                    published_at=_parse_datetime(
                        str(record.get("DOCRELPUBTIME") or record.get("date") or ""),
                        profile.timezone,
                    ),
                )
            )
            if len(items) >= limit:
                break
        if not items:
            raise ParseError("government policy list contains no supported items")
        return items

    def extract(
        self,
        response: FetchedResponse,
        item: DiscoveredItem,
        profile: SourceProfile,
    ) -> ExtractedDocument:
        return HtmlConnector(lambda _url: True, (".pages_content", ".article", "main")).extract(
            response, item, profile
        )


def _find_policy_records(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list) and all(isinstance(item, dict) for item in value):
        records = [item for item in value if isinstance(item, dict)]
        if any("URL" in item or "url" in item for item in records):
            return records
    if isinstance(value, dict):
        for item in value.values():
            records = _find_policy_records(item)
            if records:
                return records
    return []


class HtmlConnector:
    def __init__(
        self,
        link_filter: Callable[[str], bool],
        content_selectors: tuple[str, ...],
        *,
        discovery_selectors: tuple[str, ...] = (),
        published_at_from_url: Callable[[str, str], datetime | None] | None = None,
        sort_discovered_by_published_at: bool = False,
        prefer_detail_published_at: bool = False,
        use_trafilatura_fallback: bool = True,
        discovery_anchor_filter: Callable[[Tag], bool] | None = None,
    ) -> None:
        self._link_filter = link_filter
        self._content_selectors = content_selectors
        self._discovery_selectors = discovery_selectors
        self._published_at_from_url = published_at_from_url
        self._sort_discovered_by_published_at = sort_discovered_by_published_at
        self._prefer_detail_published_at = prefer_detail_published_at
        self._use_trafilatura_fallback = use_trafilatura_fallback
        self._discovery_anchor_filter = discovery_anchor_filter

    def _discovery_anchors(self, soup: BeautifulSoup) -> Iterable[Tag]:
        if not self._discovery_selectors:
            return soup.find_all("a", href=True)
        return (
            anchor
            for selector in self._discovery_selectors
            for root in soup.select(selector)
            for anchor in root.find_all("a", href=True)
        )

    def discover(
        self, response: FetchedResponse, profile: SourceProfile, *, limit: int
    ) -> list[DiscoveredItem]:
        soup = BeautifulSoup(_decode(response), "html.parser")
        item_indexes: dict[str, int] = {}
        items: list[DiscoveredItem] = []
        for anchor in self._discovery_anchors(soup):
            if self._discovery_anchor_filter is not None and not self._discovery_anchor_filter(
                anchor
            ):
                continue
            href = str(anchor.get("href"))
            candidate_url = _canonical_url(urljoin(response.final_url, href))
            url = _approved_discovered_url(candidate_url, profile)
            if url is None:
                continue
            parts = urlsplit(url)
            if not self._link_filter(url):
                continue
            item_id = parts.path.rstrip("/").rsplit("/", 1)[-1]
            title = anchor.get_text(" ", strip=True) or None
            parent_text = anchor.parent.get_text(" ", strip=True) if anchor.parent else ""
            published_at = _parse_datetime(parent_text, profile.timezone)
            if published_at is None and self._published_at_from_url is not None:
                published_at = self._published_at_from_url(url, profile.timezone)
            existing_index = item_indexes.get(url)
            if existing_index is not None:
                existing = items[existing_index]
                items[existing_index] = replace(
                    existing,
                    title=existing.title or title,
                    published_at=existing.published_at or published_at,
                )
            elif self._sort_discovered_by_published_at or len(items) < limit:
                item_indexes[url] = len(items)
                items.append(
                    DiscoveredItem(
                        source_item_id=item_id,
                        url=url,
                        title=title,
                        published_at=published_at,
                    )
                )
            if (
                not self._sort_discovered_by_published_at
                and len(items) >= limit
                and all(item.title for item in items)
            ):
                break
        if not items:
            raise ParseError("source list contains no approved article links")
        if self._sort_discovered_by_published_at:
            earliest = datetime.min.replace(tzinfo=UTC)
            items.sort(key=lambda item: item.published_at or earliest, reverse=True)
        return items[:limit]

    def extract(
        self,
        response: FetchedResponse,
        item: DiscoveredItem,
        profile: SourceProfile,
    ) -> ExtractedDocument:
        html = _decode(response)
        soup = BeautifulSoup(html, "html.parser")
        title = _extract_title(soup) or item.title
        selected_text: str | None = None
        selected_selector: str | None = None
        selected_root: Tag | None = None
        for selector in self._content_selectors:
            node = soup.select_one(selector)
            if node is not None:
                text = node.get_text("\n", strip=True)
                if len(text) >= 80:
                    selected_text = text
                    selected_selector = selector
                    selected_root = node
                    break
        if selected_text is None and self._use_trafilatura_fallback:
            selected_text = trafilatura.extract(
                html,
                include_comments=False,
                include_tables=False,
                favor_precision=True,
                output_format="txt",
            )
        if not title or not selected_text or len(selected_text.strip()) < 80:
            raise ParseError("article title or body is missing after extraction")
        published = None if self._prefer_detail_published_at else item.published_at
        if published is None:
            candidates = [
                str(node.get("content") or "")
                for node in soup.select(
                    "meta[property='article:published_time'], "
                    "meta[name='PubDate'], meta[name='publishdate']"
                )
                if isinstance(node, Tag)
            ]
            page_text = soup.get_text(" ", strip=True)[:2000]
            published = next(
                (
                    parsed
                    for value in [*candidates, page_text]
                    if (parsed := _parse_datetime(value, profile.timezone))
                ),
                None,
            )
        published = published or item.published_at
        canonical_node = soup.select_one("link[rel='canonical']")
        canonical = item.url
        if isinstance(canonical_node, Tag) and canonical_node.get("href"):
            candidate = _canonical_url(urljoin(response.final_url, str(canonical_node.get("href"))))
            approved = _approved_discovered_url(candidate, profile)
            if approved is not None:
                canonical = approved
        return ExtractedDocument(
            source_item_id=item.source_item_id,
            original_url=item.url,
            canonical_url=canonical,
            title=title.strip(),
            clean_text=selected_text.strip(),
            published_at=published,
            language=profile.language,
            parser_version=profile.parser_version,
            extraction_metadata={
                "method": "selector" if selected_selector else "trafilatura",
                "selector": selected_selector,
                "character_count": len(selected_text.strip()),
            },
            source_images=_extract_source_images(
                soup=soup,
                content_root=selected_root,
                detail_url=response.final_url,
                profile=profile,
            ),
        )


def _path_matches(pattern: str) -> Callable[[str], bool]:
    compiled = re.compile(pattern)
    return lambda url: bool(compiled.search(urlsplit(url).path))


STDAILY_DATED_ARTICLE_PATH = r"^/web/(?:[^/]+/)?20\d{2}-\d{2}/\d{2}/content_\d+\.html$"
MOE_DATED_ARTICLE_PATH = r"^/jyb_xwfb/(?:[^/]+/)+20\d{4}/t20\d{6}_\d+\.html$"
XINHUA_EDUCATION_ARTICLE_PATH = r"^/20\d{6}/[0-9a-fA-F]{32}/c\.html$"
CAST_SCIENCE_ARTICLE_PATH = r"^/(?:kp|xw)/(?:[^/]+/){1,6}art/20\d{2}/art_[0-9a-fA-F]{32}\.html$"
EDSURGE_NEWS_ARTICLE_PATH = r"^/news/20\d{2}-\d{2}-\d{2}-[a-z0-9][a-z0-9-]*$"


def _stdaily_published_at_from_url(url: str, timezone: str) -> datetime | None:
    match = re.search(r"/(20\d{2}-\d{2})/(\d{2})/content_\d+\.html$", urlsplit(url).path)
    if match is None:
        return None
    return _parse_datetime(f"{match.group(1)}-{match.group(2)}", timezone)


def _moe_published_at_from_url(url: str, timezone: str) -> datetime | None:
    match = re.search(r"/t(20\d{6})_\d+\.html$", urlsplit(url).path)
    if match is None:
        return None
    value = match.group(1)
    return _parse_datetime(f"{value[:4]}-{value[4:6]}-{value[6:]}", timezone)


def _xinhua_education_published_at_from_url(url: str, timezone: str) -> datetime | None:
    match = re.search(r"/(20\d{6})/[0-9a-fA-F]{32}/c\.html$", urlsplit(url).path)
    if match is None:
        return None
    value = match.group(1)
    return _parse_datetime(f"{value[:4]}-{value[4:6]}-{value[6:]}", timezone)


def _edsurge_published_at_from_url(url: str, timezone: str) -> datetime | None:
    match = re.search(r"/news/(20\d{2}-\d{2}-\d{2})-", urlsplit(url).path)
    return _parse_datetime(match.group(1), timezone) if match is not None else None


def _not_sponsored(anchor: Tag) -> bool:
    current: Tag | None = anchor
    for _ in range(4):
        if current is None:
            break
        if current.name in {"main", "section", "body", "html"}:
            break
        text = current.get_text(" ", strip=True).casefold()
        class_value = current.get("class")
        labels = (
            " ".join(str(value) for value in class_value)
            if isinstance(class_value, list)
            else str(class_value or "")
        ).casefold()
        if any(
            marker in f"{labels} {text}"
            for marker in ("sponsored", "advertorial", "partner content")
        ):
            return False
        current = current.parent if isinstance(current.parent, Tag) else None
    return True


CONNECTORS: dict[str, SourceConnector] = {
    "gov_cn_policy_v1": GovernmentJsonConnector(),
    "gov_cn_yaowen_v1": GovernmentJsonConnector(reject_query=True),
    "bnu_news_v1": HtmlConnector(
        _path_matches(r"/[0-9a-fA-F]{32}\.htm$"), (".article", ".content", "main")
    ),
    "cas_research_v1": HtmlConnector(
        _path_matches(r"\.shtml$"),
        (".trs_editor_view", ".TRS_Editor", ".content", "article", "main"),
    ),
    "sensetime_news_v1": HtmlConnector(
        _path_matches(r"/cn/news/\d+/?$"), ("article", ".news-detail", ".content", "main")
    ),
    "xinhua_tech_v1": HtmlConnector(
        _path_matches(r"/c\.html$"), ("#detail", ".main-aticle", "article", "main")
    ),
    "gmw_education_v1": HtmlConnector(
        _path_matches(r"content_\d+\.htm$"), ("#article_inbox", ".u-mainText", "article", "main")
    ),
    "stdaily_tech_v1": HtmlConnector(
        _path_matches(STDAILY_DATED_ARTICLE_PATH),
        (".article-content", ".content", "article", "main"),
        discovery_selectors=(".listKjxw",),
        published_at_from_url=_stdaily_published_at_from_url,
        sort_discovered_by_published_at=True,
        prefer_detail_published_at=True,
    ),
    "chinanews_education_v1": HtmlConnector(
        _path_matches(r"\.shtml$"), (".left_zw", ".content", "article", "main")
    ),
    "moe_news_v1": HtmlConnector(
        _path_matches(MOE_DATED_ARTICLE_PATH),
        (".TRS_Editor",),
        discovery_selectors=("#one_con1",),
        published_at_from_url=_moe_published_at_from_url,
        prefer_detail_published_at=True,
        use_trafilatura_fallback=False,
    ),
    "xinhua_education_v1": HtmlConnector(
        _path_matches(XINHUA_EDUCATION_ARTICLE_PATH),
        ("#detail", ".main-aticle", ".article", "article", "main"),
        published_at_from_url=_xinhua_education_published_at_from_url,
        prefer_detail_published_at=True,
    ),
    "cast_science_education_v1": HtmlConnector(
        _path_matches(CAST_SCIENCE_ARTICLE_PATH),
        (".TRS_Editor", ".article-content", ".content", "article", "main"),
        discovery_selectors=("main", ".main", ".content", ".kp-list"),
        prefer_detail_published_at=True,
        use_trafilatura_fallback=False,
    ),
    "edsurge_ai_education_v1": HtmlConnector(
        _path_matches(EDSURGE_NEWS_ARTICLE_PATH),
        ("article", ".article-body", ".body-copy", "main"),
        discovery_selectors=(
            "main",
            ".coverage-area",
            ".articles",
        ),
        published_at_from_url=_edsurge_published_at_from_url,
        prefer_detail_published_at=True,
        discovery_anchor_filter=_not_sponsored,
    ),
}


def get_connector(connector_key: str) -> SourceConnector:
    try:
        return CONNECTORS[connector_key]
    except KeyError as error:
        raise ParseError("source connector version is not installed") from error
