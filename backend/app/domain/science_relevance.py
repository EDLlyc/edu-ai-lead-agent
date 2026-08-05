from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

SCIENCE_RELEVANCE_RULE_VERSION = "moe-science-v1"
SCIENCE_CONTENT_CHARACTER_LIMIT = 6_000

_SCIENCE_TERMS: tuple[str, ...] = (
    "科学",
    "科技",
    "科创",
    "人工智能",
    "AI",
    "机器人",
    "天文",
    "航天",
    "航空航天",
    "物理",
    "化学",
    "生物",
    "实验",
    "科普",
    "科学探究",
    "科学教育",
    "工程",
    "创新",
    "探究",
)


@dataclass(frozen=True, slots=True)
class ScienceRelevanceResult:
    is_relevant: bool
    matched_title_terms: tuple[str, ...]
    matched_content_terms: tuple[str, ...]
    matched_terms: tuple[str, ...]
    rule_version: str = SCIENCE_RELEVANCE_RULE_VERSION
    content_characters_considered: int = 0
    content_truncated: bool = False


def normalize_science_text(value: str | None) -> str:
    if not value:
        return ""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(normalized.split())


def _term_pattern(term: str) -> re.Pattern[str]:
    normalized_term = normalize_science_text(term)
    if normalized_term.isascii():
        return re.compile(rf"(?<![a-z0-9]){re.escape(normalized_term)}(?![a-z0-9])")
    return re.compile(re.escape(normalized_term))


_TERM_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (term, _term_pattern(term)) for term in _SCIENCE_TERMS
)


def evaluate_moe_science_relevance(
    title: str | None,
    content: str | None,
    *,
    content_limit: int = SCIENCE_CONTENT_CHARACTER_LIMIT,
) -> ScienceRelevanceResult:
    if content_limit < 1:
        raise ValueError("science relevance content limit must be positive")
    normalized_title = normalize_science_text(title)
    normalized_content = normalize_science_text(content)
    considered_content = normalized_content[:content_limit]
    title_terms = tuple(
        term for term, pattern in _TERM_PATTERNS if pattern.search(normalized_title) is not None
    )
    content_terms = tuple(
        term for term, pattern in _TERM_PATTERNS if pattern.search(considered_content) is not None
    )
    matched_terms = tuple(dict.fromkeys((*title_terms, *content_terms)))
    return ScienceRelevanceResult(
        is_relevant=bool(matched_terms),
        matched_title_terms=title_terms,
        matched_content_terms=content_terms,
        matched_terms=matched_terms,
        content_characters_considered=len(considered_content),
        content_truncated=len(normalized_content) > len(considered_content),
    )


def evaluate_science_relevance(
    title: str | None,
    content: str | None,
    *,
    content_limit: int = SCIENCE_CONTENT_CHARACTER_LIMIT,
) -> ScienceRelevanceResult:
    """Evaluate the versioned bounded science taxonomy used by the Ministry source."""

    return evaluate_moe_science_relevance(title, content, content_limit=content_limit)
