# ruff: noqa: RUF001 -- Full-width Chinese punctuation is intentional exhibit copy.
"""「朋友圈」 exhibit projection: what was sent, and how each production step produced it."""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
from collections.abc import Iterable, Mapping
from datetime import date
from typing import Any, Literal, cast
from urllib.parse import urlsplit

from pydantic import ValidationError

from app.core.errors import ConflictError, NotFoundError
from app.infrastructure.db.visitor_moments import VisitorMomentImage, VisitorMomentRow
from app.schemas.visitor_display import VisitorDisplayMoment, VisitorMomentImageRef

_LOGGER = logging.getLogger(__name__)
MOMENT_ASSET_PREFIX = "vm1_"
_ASSET_DOMAIN = b"edu-ai-visitor-display-moment-asset-v1\0"
_KEY_DOMAIN = b"edu-ai-visitor-display-moment-v1\0"
ALLOWED_MOMENT_MEDIA_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
_SLOTS = frozenset({"morning", "noon", "evening"})
_DELIVERY: Mapping[str, Literal["delivered", "partial", "unknown"]] = {
    "delivered": "delivered",
    "partial": "partial",
    "delivery_unknown": "unknown",
}
_COPY_LIMIT = 2_400

# Writing checks that were flagged but let through (warnings on the sent draft).
_CHECK_LABELS: Mapping[str, str] = {
    "unverified_superlative": "新闻里的最高级说法",
    "source_note_unlinked": "来源说明与原文对齐",
    "copy_length": "字数",
    "copy_emoji_count": "表情数量",
    "copy_fluency": "语句通顺",
    "fluency": "语句通顺",
    "wordiness": "表达啰嗦",
    "readability": "家长读得懂",
    "parent_readability": "家长读得懂",
    "plain_language": "说人话",
    "technical_jargon": "专业术语",
    "education_anxiety": "避免制造焦虑",
    "tone_mismatch": "语气",
    "brand_tone": "品牌语气",
    "brand_fit": "品牌契合",
    "hashtag_count": "话题标签数量",
    "hashtag_format": "话题标签格式",
    "incomplete_sentence": "句子完整",
    "copy_paragraph_format": "分段格式",
    "copy_news_framing": "新闻表述",
}


def moment_key(row: VisitorMomentRow) -> str:
    return "vmk_" + hashlib.sha256(_KEY_DOMAIN + row.job_id.bytes).hexdigest()[:24]


def moment_asset_ref(*, secret: str, image: VisitorMomentImage) -> str:
    message = _ASSET_DOMAIN + "\0".join(
        (image.kind, str(image.row_id), image.sha256, image.media_type, str(image.byte_size))
    ).encode("utf-8")
    digest = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).digest()
    return MOMENT_ASSET_PREFIX + base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def resolve_moment_asset(
    *, secret: str, asset_ref: str, rows: Iterable[VisitorMomentRow]
) -> VisitorMomentImage:
    """Only images of the currently shown posts resolve; everything else is not found."""
    if not asset_ref.startswith(MOMENT_ASSET_PREFIX) or len(asset_ref) != 47:
        raise NotFoundError("visitor display asset")
    matches = [
        image
        for row in rows
        for image in (row.image, row.long_image)
        if image is not None
        and image.media_type in ALLOWED_MOMENT_MEDIA_TYPES
        and hmac.compare_digest(moment_asset_ref(secret=secret, image=image), asset_ref)
    ]
    if not matches:
        raise NotFoundError("visitor display asset")
    if len(matches) != 1:
        raise ConflictError("visitor display asset reference is ambiguous")
    return matches[0]


def image_signature_matches(media_type: str, body: bytes) -> bool:
    if media_type == "image/jpeg":
        return body.startswith(b"\xff\xd8\xff")
    if media_type == "image/png":
        return body.startswith(b"\x89PNG\r\n\x1a\n")
    if media_type == "image/webp":
        return len(body) >= 12 and body[:4] == b"RIFF" and body[8:12] == b"WEBP"
    return False


def project_moments(rows: Iterable[VisitorMomentRow], *, secret: str) -> list[VisitorDisplayMoment]:
    moments: list[VisitorDisplayMoment] = []
    for row in rows:
        try:
            moment = _project(row, secret=secret)
        except (ValidationError, ValueError, TypeError) as error:
            # One malformed historical package must not hide the others.
            _LOGGER.warning("visitor moment skipped: %s", type(error).__name__)
            continue
        if moment is not None:
            moments.append(moment)
    return moments


def _project(row: VisitorMomentRow, *, secret: str) -> VisitorDisplayMoment | None:
    topic = row.topic
    slot = topic.get("content_slot")
    text = row.copy.get("copywriting")
    title = topic.get("title")
    if slot not in _SLOTS or not isinstance(text, str) or not text.strip():
        return None
    if not isinstance(title, str) or not title.strip():
        return None
    business_date = cast("date", topic.get("business_date") or row.business_date)
    score = _mapping(topic.get("score"))
    source_url = _first_https(row.sources)
    ordinal = topic.get("ordinal")
    return VisitorDisplayMoment(
        key=moment_key(row),
        business_date=business_date,
        slot=slot,
        ordinal=ordinal if isinstance(ordinal, int) and 1 <= ordinal <= 3 else None,
        human_pick=row.human_pick,
        title=" ".join(title.split())[:200],
        source_host=(urlsplit(source_url).hostname or None) if source_url else None,
        source_url=source_url,
        selection_reason=_selection_reason(row.human_pick, score),
        score=_number(score.get("total")),
        threshold=_number(score.get("threshold")),
        brand_angles=_brand_angles(row.brand),
        copy_text=text.strip()[:_COPY_LIMIT],
        copy_started_at=row.copy_started_at,
        copy_finished_at=row.copy_finished_at,
        repair_count=min(max(row.repair_count, 0), 10),
        checks=_checks(row.validation, row.audit),
        image=_image_ref(row.image, secret=secret),
        delivery=_DELIVERY.get(row.delivery_status, "unknown"),
        text_sent_at=row.text_sent_at,
        image_sent_at=row.image_sent_at,
        long_image=_image_ref(row.long_image, secret=secret),
        long_image_state=_long_image_state(row),
        long_image_sent_at=row.long_image_sent_at,
    )


def _selection_reason(human_pick: bool, score: Mapping[str, Any]) -> str:
    if human_pick:
        return "运营在展厅人工审核后加推"
    explanation = _mapping(score.get("explanation"))
    level = explanation.get("education_policy_level")
    reason = explanation.get("priority_reason")
    cohort = explanation.get("science_tech_editorial_cohort")
    if level == "national":
        return "国家教育政策风向，最高优先级"
    if level == "provincial":
        return "省级教育政策风向，优先入选"
    if isinstance(reason, str) and reason.startswith("ministry_"):
        return "教育部科学教育新闻，优先入选"
    if reason == "qualified_government_yaowen_priority":
        return "政府网科技教育要闻，优先入选"
    if cohort == "science_technology_education_priority":
        return "科学教育相关，综合得分过线"
    if cohort == "frontier_science_technology":
        return "前沿科技新闻，综合得分过线"
    return "综合得分过线"


def _brand_angles(brand: Iterable[Mapping[str, Any]]) -> list[str]:
    angles: list[str] = []
    for chunk in brand:
        title = chunk.get("document_title")
        if isinstance(title, str) and title.strip():
            label = " ".join(title.split())[:40]
            if label not in angles:
                angles.append(label)
    return angles[:3]


def _checks(*snapshots: Mapping[str, Any]) -> list[str]:
    labels: list[str] = []
    for snapshot in snapshots:
        issues = snapshot.get("issues")
        for issue in issues if isinstance(issues, list) else []:
            if not isinstance(issue, dict) or issue.get("severity") != "warning":
                continue
            label = _CHECK_LABELS.get(str(issue.get("code")), "其他写作提示")
            if label not in labels:
                labels.append(label)
    return labels[:6]


def _image_ref(image: VisitorMomentImage | None, *, secret: str) -> VisitorMomentImageRef | None:
    if image is None or image.media_type not in ALLOWED_MOMENT_MEDIA_TYPES:
        return None
    return VisitorMomentImageRef(
        ref=moment_asset_ref(secret=secret, image=image),
        width=image.width if image.width and image.width > 0 else None,
        height=image.height if image.height and image.height > 0 else None,
    )


def _long_image_state(
    row: VisitorMomentRow,
) -> Literal["sent", "ready", "making", "failed", "none"]:
    if row.long_image_sent_at is not None:
        return "sent"
    status = row.long_image_status
    if status is None or status == "skipped":
        return "none"
    if status == "ready":
        return "ready"
    if status in {"queued", "running"}:
        return "making"
    return "failed"


def _first_https(sources: Iterable[Mapping[str, Any]]) -> str | None:
    for source in sources:
        url = source.get("source_url")
        if isinstance(url, str) and url.startswith("https://") and len(url) <= 2_048:
            parts = urlsplit(url)
            if parts.hostname and parts.username is None and parts.password is None:
                return url
    return None


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


__all__ = [
    "ALLOWED_MOMENT_MEDIA_TYPES",
    "MOMENT_ASSET_PREFIX",
    "image_signature_matches",
    "moment_asset_ref",
    "moment_key",
    "project_moments",
    "resolve_moment_asset",
]
