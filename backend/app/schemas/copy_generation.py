from __future__ import annotations

import re
from datetime import date, datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_HASHTAG_TOKEN = re.compile(r"^#[A-Za-z0-9_\u3400-\u9fff]{2,24}$")
_CJK_RANGES = ((0x3400, 0x4DBF), (0x4E00, 0x9FFF))
_EMOJI_RANGES = (
    (0x00A9, 0x00A9),
    (0x00AE, 0x00AE),
    (0x203C, 0x203C),
    (0x2049, 0x2049),
    (0x2122, 0x2122),
    (0x2139, 0x2139),
    (0x2194, 0x21FF),
    (0x2300, 0x23FF),
    (0x25AA, 0x25FF),
    (0x2600, 0x27BF),
    (0x2934, 0x2935),
    (0x2B00, 0x2BFF),
    (0x1F000, 0x1FAFF),
)
_EMOJI_MODIFIER_RANGES = ((0x1F3FB, 0x1F3FF),)
_REGIONAL_INDICATOR_RANGE = (0x1F1E6, 0x1F1FF)
_EMOJI_VARIATION_SELECTORS = frozenset({0xFE0E, 0xFE0F})
_ZERO_WIDTH_JOINER = 0x200D
_NEWS_SOURCE_PREFIX = "新闻来源\uff1a"
_NEWS_LINK_PREFIX = "原文链接\uff1a"


def extract_trailing_hashtags(text: str) -> tuple[str, ...]:
    """Read a bounded hashtag line from the end of a copy without changing the copy."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ()
    tokens = tuple(lines[-1].split())
    if not 1 <= len(tokens) <= 3 or any(
        _HASHTAG_TOKEN.fullmatch(token) is None for token in tokens
    ):
        return ()
    return tokens


def has_non_trailing_hashtags(text: str) -> bool:
    """Return whether a hashtag-like token appears before the final non-empty line."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return any(
        token.startswith("#") and len(token) > 1 for line in lines[:-1] for token in line.split()
    )


def extract_copy_body(text: str) -> str:
    """Return the copy body while excluding a final hashtag candidate line."""
    lines = text.splitlines()
    while lines and not lines[-1].strip():
        lines.pop()
    if lines and _is_hashtag_candidate_line(lines[-1]):
        lines.pop()
    _remove_news_source_footer(lines)
    return "\n".join(lines)


def append_copy_news_source_footer(text: str, *, source_name: str, source_url: str) -> str:
    """Bind a generated copy to its first eligible news source without trusting model text."""
    normalized_name = " ".join(source_name.split())
    normalized_url = source_url.strip()
    if (
        not normalized_name
        or not normalized_url
        or "\n" in normalized_url
        or "\r" in normalized_url
    ):
        raise ValueError("news source footer requires one safe source name and URL")
    hashtags = extract_trailing_hashtags(text)
    if not hashtags:
        return text
    body = extract_copy_body(text).rstrip()
    return "\n".join(
        (
            body,
            "",
            f"{_NEWS_SOURCE_PREFIX}{normalized_name}",
            f"{_NEWS_LINK_PREFIX}{normalized_url}",
            " ".join(hashtags),
        )
    )


def has_copy_news_framing(text: str) -> bool:
    """Require the opening paragraph to identify the copy as news-derived."""
    first_paragraph = "\n".join(extract_copy_paragraphs(text)[:2])
    return any(
        phrase in first_paragraph
        for phrase in ("看到一条新闻", "一则新闻", "新闻消息", "这条新闻", "新闻报道")
    )


def has_copy_news_source_footer(text: str, *, source_name: str, source_url: str) -> bool:
    """Check that the final copy carries the expected evidence-bound source footer."""
    normalized_name = " ".join(source_name.split())
    normalized_url = source_url.strip()
    lines = text.splitlines()
    while lines and not lines[-1].strip():
        lines.pop()
    if lines and _is_hashtag_candidate_line(lines[-1]):
        lines.pop()
    while lines and not lines[-1].strip():
        lines.pop()
    return (
        len(lines) >= 2
        and lines[-2].strip() == f"{_NEWS_SOURCE_PREFIX}{normalized_name}"
        and (lines[-1].strip() == f"{_NEWS_LINK_PREFIX}{normalized_url}")
    )


def extract_copy_paragraphs(text: str) -> tuple[str, ...]:
    """Return body lines, retaining empty lines so format violations are visible."""
    return tuple(extract_copy_body(text).splitlines())


def has_copy_paragraph_format(text: str) -> bool:
    """Accept a readable two- or three-paragraph copy body without line-shape rules."""
    paragraphs = tuple(
        paragraph.strip()
        for paragraph in re.split(r"\n\s*\n", extract_copy_body(text).strip())
        if paragraph.strip()
    )
    return 2 <= len(paragraphs) <= 3


def count_hanzi(text: str) -> int:
    """Count CJK Unified Ideographs without counting punctuation or other symbols."""
    return sum(
        1 for character in text if any(start <= ord(character) <= end for start, end in _CJK_RANGES)
    )


def count_emojis(text: str) -> int:
    """Count emoji display sequences, ignoring variation/modifier/joiner components."""
    count = 0
    index = 0
    while index < len(text):
        codepoint = ord(text[index])
        if not _is_emoji_base(codepoint):
            index += 1
            continue

        count += 1
        index += 1
        index = _consume_emoji_components(text, index)
        if (
            _is_regional_indicator(codepoint)
            and index < len(text)
            and _is_regional_indicator(ord(text[index]))
        ):
            index += 1
        while (
            index + 1 < len(text)
            and ord(text[index]) == _ZERO_WIDTH_JOINER
            and _is_emoji_base(ord(text[index + 1]))
        ):
            index += 2
            index = _consume_emoji_components(text, index)
    return count


def _is_hashtag_candidate_line(line: str) -> bool:
    tokens = line.strip().split()
    return bool(tokens) and all(token.startswith("#") and len(token) > 1 for token in tokens)


def _remove_news_source_footer(lines: list[str]) -> None:
    while lines and not lines[-1].strip():
        lines.pop()
    if (
        len(lines) >= 2
        and lines[-2].strip().startswith(_NEWS_SOURCE_PREFIX)
        and lines[-1].strip().startswith(_NEWS_LINK_PREFIX)
    ):
        lines.pop()
        lines.pop()
    while lines and not lines[-1].strip():
        lines.pop()


def _is_emoji_base(codepoint: int) -> bool:
    return not _is_emoji_modifier(codepoint) and any(
        start <= codepoint <= end for start, end in _EMOJI_RANGES
    )


def _starts_with_emoji(value: str) -> bool:
    value = value.lstrip()
    return bool(value) and _is_emoji_base(ord(value[0]))


def _ends_with_emoji(value: str) -> bool:
    value = value.rstrip()
    index = len(value) - 1
    while index >= 0 and (
        ord(value[index]) in _EMOJI_VARIATION_SELECTORS or _is_emoji_modifier(ord(value[index]))
    ):
        index -= 1
    return index >= 0 and _is_emoji_base(ord(value[index]))


def _is_emoji_modifier(codepoint: int) -> bool:
    return any(start <= codepoint <= end for start, end in _EMOJI_MODIFIER_RANGES)


def _is_regional_indicator(codepoint: int) -> bool:
    start, end = _REGIONAL_INDICATOR_RANGE
    return start <= codepoint <= end


def _consume_emoji_components(text: str, index: int) -> int:
    while index < len(text):
        codepoint = ord(text[index])
        if codepoint in _EMOJI_VARIATION_SELECTORS or _is_emoji_modifier(codepoint):
            index += 1
            continue
        break
    return index


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class DraftClaim(_StrictModel):
    id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")
    text: str = Field(min_length=2, max_length=300)
    kind: Literal["external_fact", "brand_statement", "opinion"]
    evidence_ids: tuple[UUID, ...] = Field(default=(), max_length=8)
    brand_chunk_ids: tuple[UUID, ...] = Field(default=(), max_length=8)

    @field_validator("evidence_ids", "brand_chunk_ids")
    @classmethod
    def binding_ids_must_be_unique(cls, value: tuple[UUID, ...]) -> tuple[UUID, ...]:
        if len(value) != len(set(value)):
            raise ValueError("claim binding IDs must be unique")
        return value


class MaterialDraft(_StrictModel):
    copywriting: str = Field(min_length=1, max_length=1_200)
    parent_takeaway: str = Field(min_length=1, max_length=300)
    interaction: str = Field(min_length=1, max_length=180)
    source_note: str = Field(min_length=1, max_length=500)
    image_prompt: str = Field(min_length=1, max_length=800)
    claims: tuple[DraftClaim, ...] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def claim_ids_must_be_unique(self) -> Self:
        claim_ids = [claim.id for claim in self.claims]
        if len(claim_ids) != len(set(claim_ids)):
            raise ValueError("draft claim IDs must be unique")
        return self


class CopyIssue(_StrictModel):
    code: str = Field(min_length=1, max_length=80, pattern=r"^[a-z][a-z0-9_]*$")
    message: str = Field(min_length=1, max_length=240)
    severity: Literal["warning", "error"] = "error"
    field: str | None = Field(default=None, max_length=80)
    claim_id: str | None = Field(default=None, max_length=80)


class AuditVerdict(_StrictModel):
    accepted: bool
    issues: tuple[CopyIssue, ...] = Field(default=(), max_length=24)

    @model_validator(mode="after")
    def accepted_verdict_has_no_errors(self) -> Self:
        if self.accepted and any(issue.severity == "error" for issue in self.issues):
            raise ValueError("accepted audit cannot contain error issues")
        if not self.accepted and not any(issue.severity == "error" for issue in self.issues):
            raise ValueError("rejected audit requires at least one error issue")
        return self


class CreateCopyGenerationRunRequest(BaseModel):
    business_date: date
    scoring_profile: str = Field(default="preview", min_length=1, max_length=40)


class CopyClaimResponse(BaseModel):
    claim_id: str
    text: str
    kind: Literal["external_fact", "brand_statement", "opinion"]
    evidence_ids: list[UUID]
    brand_chunk_ids: list[UUID]


class CopyDraftResponse(BaseModel):
    id: UUID
    version: int
    repair_of_version_id: UUID | None
    copywriting: str
    parent_takeaway: str
    interaction: str
    source_note: str
    image_prompt: str
    validation_passed: bool
    audit_accepted: bool | None
    claims: list[CopyClaimResponse]
    issues: list[CopyIssue]
    created_at: datetime


class CopyGenerationRunResponse(BaseModel):
    id: UUID
    daily_topic_selection_id: UUID
    business_date: date
    timezone: str
    scoring_profile: str
    decision_kind: Literal["selected", "no_topic"]
    selected_event_id: UUID | None
    selected_event_version_id: UUID | None
    no_topic_code: str | None
    status: Literal[
        "queued",
        "running",
        "no_topic",
        "accepted",
        "review_required",
        "failed",
    ]
    active_draft_version_id: UUID | None
    repair_count: int
    error_code: str | None
    created_at: datetime
    started_at: datetime | None
    completed_at: datetime | None
    status_url: str
    detail_url: str


class CopyGenerationDetailResponse(CopyGenerationRunResponse):
    drafts: list[CopyDraftResponse]
