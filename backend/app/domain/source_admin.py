# ruff: noqa: RUF001
"""News sources an operator adds in the 运营后台: generic connector settings and their rules.

Code-defined sources (`SOURCE_SEEDS`) keep their reviewed connectors. An operator source uses one
of two generic connectors whose settings live in `source_versions.connector_config`:

- `generic_html_v1`: a list page; article links are recognised by plain "link contains" text or,
  without it, by an article-path heuristic; optional CSS selectors narrow the list area and the
  article body (trafilatura is the fallback).
- `generic_rss_v1`: an RSS/Atom feed; each article page is extracted like HTML.

Every setting is bounded and validated here, and is part of the version fingerprint, so a
change always makes a new immutable source version.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import urlsplit

import soupsieve

from app.core.errors import PolicyRejectedError
from app.core.security import normalize_public_https_url
from app.domain.editorial_relevance import SCIENCE_TECH_EDITORIAL_RULE_VERSION
from app.domain.value_objects import stable_key

GENERIC_HTML_CONNECTOR_KEY = "generic_html_v1"
GENERIC_RSS_CONNECTOR_KEY = "generic_rss_v1"
GENERIC_CONNECTOR_KEYS = frozenset({GENERIC_HTML_CONNECTOR_KEY, GENERIC_RSS_CONNECTOR_KEY})
GENERIC_CONNECTOR_VERSION = "generic-1.0.0"
GENERIC_PARSER_VERSION = "generic-1.0.0"

OPERATOR_RELEVANCE_RULE_VERSION = SCIENCE_TECH_EDITORIAL_RULE_VERSION
OPERATOR_RATE_LIMIT_SECONDS = 3.0
ORGANIZATION_TYPES = (
    "government",
    "education_institution",
    "research_organization",
    "authoritative_media",
)

SourceKind = Literal["html", "rss"]

_MAX_LINK_PATTERNS = 5
_MAX_SELECTORS = 5
_MAX_PATTERN_CHARS = 80
_MAX_SELECTOR_CHARS = 120
_ARTICLE_SUFFIX = re.compile(r"\.(?:s?html?|php|aspx?)$", re.IGNORECASE)
_DATED_PATH = re.compile(r"(?:^|/)20\d{2}(?:[-/]?\d{2}){1,2}(?:/|_|-|$)")


class SourceConfigError(PolicyRejectedError):
    """A source setting broke a rule; the message is shown to the operator."""

    def __init__(self, message: str) -> None:
        super().__init__("source_config_invalid", message)


@dataclass(frozen=True, slots=True)
class GenericConnectorConfig:
    kind: SourceKind
    link_contains: tuple[str, ...] = ()
    content_selectors: tuple[str, ...] = ()
    list_selectors: tuple[str, ...] = ()

    @property
    def connector_key(self) -> str:
        return GENERIC_HTML_CONNECTOR_KEY if self.kind == "html" else GENERIC_RSS_CONNECTOR_KEY

    def to_json(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "link_contains": list(self.link_contains),
            "content_selectors": list(self.content_selectors),
            "list_selectors": list(self.list_selectors),
        }


def _clean_list(values: object, *, label: str, limit: int, max_chars: int) -> tuple[str, ...]:
    if values is None:
        return ()
    if not isinstance(values, list | tuple):
        raise SourceConfigError(f"{label}必须是列表")
    cleaned: list[str] = []
    for raw in values:
        if not isinstance(raw, str):
            raise SourceConfigError(f"{label}只能是文字")
        value = raw.strip()
        if not value:
            continue
        if len(value) > max_chars:
            raise SourceConfigError(f"{label}每项最多 {max_chars} 个字符")
        if value not in cleaned:
            cleaned.append(value)
    if len(cleaned) > limit:
        raise SourceConfigError(f"{label}最多 {limit} 项")
    return tuple(cleaned)


def _check_selectors(selectors: tuple[str, ...], label: str) -> None:
    for selector in selectors:
        try:
            soupsieve.compile(selector)
        except (soupsieve.SelectorSyntaxError, ValueError) as error:
            raise SourceConfigError(f"{label}「{selector}」不是有效的 CSS 选择器") from error


def parse_connector_config(value: object) -> GenericConnectorConfig:
    """Validate a stored or submitted generic connector config."""

    if not isinstance(value, dict):
        raise SourceConfigError("抓取设置格式不对")
    unknown = set(value) - {"kind", "link_contains", "content_selectors", "list_selectors"}
    if unknown:
        raise SourceConfigError(f"不认识的抓取设置：{', '.join(sorted(unknown))}")
    kind = value.get("kind")
    if kind not in ("html", "rss"):
        raise SourceConfigError("类型只能是网页或 RSS")
    link_contains = _clean_list(
        value.get("link_contains"),
        label="文章链接包含",
        limit=_MAX_LINK_PATTERNS,
        max_chars=_MAX_PATTERN_CHARS,
    )
    if any(re.search(r"\s", pattern) for pattern in link_contains):
        raise SourceConfigError("文章链接包含的文字不能有空格")
    content_selectors = _clean_list(
        value.get("content_selectors"),
        label="正文位置",
        limit=_MAX_SELECTORS,
        max_chars=_MAX_SELECTOR_CHARS,
    )
    list_selectors = _clean_list(
        value.get("list_selectors"),
        label="列表位置",
        limit=_MAX_SELECTORS,
        max_chars=_MAX_SELECTOR_CHARS,
    )
    _check_selectors(content_selectors, "正文位置")
    _check_selectors(list_selectors, "列表位置")
    if kind == "rss" and (link_contains or list_selectors):
        raise SourceConfigError("RSS 不需要填文章链接和列表位置")
    return GenericConnectorConfig(
        kind=kind,
        link_contains=link_contains,
        content_selectors=content_selectors,
        list_selectors=list_selectors,
    )


def looks_like_article_path(path: str) -> bool:
    """Heuristic for list pages without "link contains": dated or numbered detail pages."""

    segments = [segment for segment in path.split("/") if segment]
    if not segments:
        return False
    last = segments[-1]
    if _DATED_PATH.search(path) and len(segments) >= 2:
        return True
    return bool(_ARTICLE_SUFFIX.search(last)) and bool(re.search(r"\d{3,}", path))


def link_matches(config: GenericConnectorConfig, url: str) -> bool:
    parts = urlsplit(url)
    target = parts.path + (f"?{parts.query}" if parts.query else "")
    if config.link_contains:
        return any(pattern in target for pattern in config.link_contains)
    return looks_like_article_path(parts.path)


@dataclass(frozen=True, slots=True)
class OperatorSourceDraft:
    display_name: str
    organization_type: str
    tier: Literal["A", "B"]
    entry_url: str
    config: GenericConnectorConfig

    @property
    def host(self) -> str:
        host = urlsplit(self.entry_url).hostname
        assert host is not None
        return host


def build_operator_source_draft(
    *,
    display_name: str,
    organization_type: str,
    tier: str,
    entry_url: str,
    config: object,
) -> OperatorSourceDraft:
    name = display_name.strip()
    if not 2 <= len(name) <= 60:
        raise SourceConfigError("名称要 2-60 个字")
    if organization_type not in ORGANIZATION_TYPES:
        raise SourceConfigError("机构类型不对")
    if tier not in ("A", "B"):
        raise SourceConfigError("可信度只能是 A 或 B")
    try:
        url = normalize_public_https_url(entry_url.strip())
    except PolicyRejectedError as error:
        raise SourceConfigError("网址必须是公开的 https 地址，不能是内网或 IP") from error
    return OperatorSourceDraft(
        display_name=name,
        organization_type=organization_type,
        tier="A" if tier == "A" else "B",
        entry_url=url,
        config=parse_connector_config(config),
    )


def operator_version_fingerprint(
    draft: OperatorSourceDraft, *, robots_status: str, rate_limit_seconds: float
) -> str:
    """Identity of everything that changes how a source is fetched and filtered."""

    payload = {
        "connector_key": draft.config.connector_key,
        "connector_config": draft.config.to_json(),
        "connector_version": GENERIC_CONNECTOR_VERSION,
        "parser_version": GENERIC_PARSER_VERSION,
        "entry_url": draft.entry_url,
        "allowed_hosts": [draft.host],
        "allowed_path_prefixes": ["/"],
        "tier": draft.tier,
        "relevance_rule_version": OPERATOR_RELEVANCE_RULE_VERSION,
        "robots_status": robots_status,
        "rate_limit_seconds": rate_limit_seconds,
    }
    return stable_key(json.dumps(payload, sort_keys=True, ensure_ascii=False))


__all__ = [
    "GENERIC_CONNECTOR_KEYS",
    "GENERIC_CONNECTOR_VERSION",
    "GENERIC_HTML_CONNECTOR_KEY",
    "GENERIC_PARSER_VERSION",
    "GENERIC_RSS_CONNECTOR_KEY",
    "OPERATOR_RATE_LIMIT_SECONDS",
    "OPERATOR_RELEVANCE_RULE_VERSION",
    "ORGANIZATION_TYPES",
    "GenericConnectorConfig",
    "OperatorSourceDraft",
    "SourceConfigError",
    "build_operator_source_draft",
    "link_matches",
    "looks_like_article_path",
    "operator_version_fingerprint",
    "parse_connector_config",
]
