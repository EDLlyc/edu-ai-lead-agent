from __future__ import annotations

# ruff: noqa: RUF001
import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from typing import Literal, cast
from uuid import UUID

from app.domain.value_objects import stable_key
from app.schemas.copy_generation import (
    AuditVerdict,
    CopyIssue,
    MaterialDraft,
    count_emojis,
    count_hanzi,
    extract_copy_body,
    extract_trailing_hashtags,
    has_copy_paragraph_format,
    has_non_trailing_hashtags,
)


class CopyRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    NO_TOPIC = "no_topic"
    ACCEPTED = "accepted"
    REVIEW_REQUIRED = "review_required"
    FAILED = "failed"


class CopyJobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    RETRY_SCHEDULED = "retry_scheduled"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class EligibleEvidence:
    evidence_id: UUID
    candidate_id: UUID
    passage_id: UUID
    occurrence_id: UUID
    snapshot_id: UUID
    source_name: str
    source_url: str
    source_tier: str
    published_at: datetime | None
    exact_quote: str

    def __post_init__(self) -> None:
        if self.source_tier not in {"A", "B"}:
            raise ValueError("copy evidence must use an eligible source tier")
        if (
            not self.source_name.strip()
            or not self.source_url.strip()
            or not self.exact_quote.strip()
        ):
            raise ValueError("copy evidence metadata must not be blank")
        if self.published_at is not None and self.published_at.tzinfo is None:
            raise ValueError("evidence publication time must be timezone-aware")


@dataclass(frozen=True, slots=True)
class ActiveBrandContext:
    chunk_id: UUID
    document_id: UUID
    version_id: UUID
    document_title: str
    document_kind: str
    text: str
    tone_tags: tuple[str, ...] = ()
    safety_tags: tuple[str, ...] = ()
    visual_tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            not self.document_title.strip()
            or not self.document_kind.strip()
            or not self.text.strip()
        ):
            raise ValueError("brand context metadata must not be blank")


@dataclass(frozen=True, slots=True)
class LockedTopicContext:
    daily_topic_selection_id: UUID
    topic_selection_run_id: UUID
    business_date: date
    timezone: str
    scoring_profile: str
    decision_kind: str
    selected_event_id: UUID | None
    selected_event_version_id: UUID | None
    no_topic_code: str | None
    title: str | None
    summary: str | None
    evidence: tuple[EligibleEvidence, ...]

    def __post_init__(self) -> None:
        if self.decision_kind == "selected":
            if self.selected_event_id is None or self.selected_event_version_id is None:
                raise ValueError("selected topic requires an event/version pair")
            if not self.title or not self.title.strip():
                raise ValueError("selected topic requires a title")
        elif self.decision_kind == "no_topic":
            if self.selected_event_id is not None or self.selected_event_version_id is not None:
                raise ValueError("no-topic decision cannot carry an event")
            if not self.no_topic_code:
                raise ValueError("no-topic decision requires a reason")
            if self.evidence:
                raise ValueError("no-topic decision cannot carry evidence")
        else:
            raise ValueError("unknown daily topic decision kind")


@dataclass(frozen=True, slots=True)
class CopyVersionBundle:
    pipeline_version: str
    generator_prompt_version: str
    draft_schema_version: str
    auditor_prompt_version: str
    audit_schema_version: str
    rule_version: str
    provider: str
    model: str

    def __post_init__(self) -> None:
        values = (
            self.pipeline_version,
            self.generator_prompt_version,
            self.draft_schema_version,
            self.auditor_prompt_version,
            self.audit_schema_version,
            self.rule_version,
            self.provider,
            self.model,
        )
        if any(not value.strip() or len(value) > 120 for value in values):
            raise ValueError("copy version identifiers must be bounded and non-blank")

    def as_metadata(self) -> dict[str, str]:
        return {
            "pipeline_version": self.pipeline_version,
            "generator_prompt_version": self.generator_prompt_version,
            "draft_schema_version": self.draft_schema_version,
            "auditor_prompt_version": self.auditor_prompt_version,
            "audit_schema_version": self.audit_schema_version,
            "rule_version": self.rule_version,
            "provider": self.provider,
            "model": self.model,
        }

    @classmethod
    def from_metadata(
        cls,
        value: object,
        *,
        expected_fingerprint: str | None = None,
    ) -> CopyVersionBundle:
        if not isinstance(value, Mapping):
            raise ValueError("copy version bundle metadata must be an object")
        metadata = cast(Mapping[object, object], value)
        expected_keys = {
            "pipeline_version",
            "generator_prompt_version",
            "draft_schema_version",
            "auditor_prompt_version",
            "audit_schema_version",
            "rule_version",
            "provider",
            "model",
        }
        if set(metadata) != expected_keys:
            raise ValueError("copy version bundle metadata fields are invalid")

        def required_string(key: str) -> str:
            raw = metadata.get(key)
            if not isinstance(raw, str):
                raise ValueError("copy version bundle metadata values must be strings")
            return raw

        bundle = cls(
            pipeline_version=required_string("pipeline_version"),
            generator_prompt_version=required_string("generator_prompt_version"),
            draft_schema_version=required_string("draft_schema_version"),
            auditor_prompt_version=required_string("auditor_prompt_version"),
            audit_schema_version=required_string("audit_schema_version"),
            rule_version=required_string("rule_version"),
            provider=required_string("provider"),
            model=required_string("model"),
        )
        if expected_fingerprint is not None and bundle.fingerprint != expected_fingerprint:
            raise ValueError("copy version bundle fingerprint does not match the durable run")
        return bundle

    @property
    def fingerprint(self) -> str:
        return stable_key(
            self.pipeline_version,
            self.generator_prompt_version,
            self.draft_schema_version,
            self.auditor_prompt_version,
            self.audit_schema_version,
            self.rule_version,
            self.provider,
            self.model,
        )


_BANNED_MARKETING = (
    "保证提分",
    "确保提分",
    "绝对领先",
    "行业第一",
    "第一品牌",
    "领导品牌",
    "百分之百",
    "100%",
    "保送资格",
    "必然成功",
    "最权威",
)
_ANXIETY = (
    "再不学就晚了",
    "输在起跑线",
    "注定落后",
    "被时代淘汰",
    "落后别人家孩子",
    "错过就来不及",
)
_PROMPT_INJECTION = (
    "忽略之前的指令",
    "忽略系统提示",
    "system prompt",
    "developer message",
    "越过审核",
)
_UNSAFE_IMAGE = (
    "未成年人真人正脸",
    "儿童真实正脸",
    "学生身份证",
    "裸露儿童",
    "血腥",
    "武器伤害",
)
_PUBLISHING = ("自动发布", "代发朋友圈", "登录微信", "点击发布", "发布到朋友圈")
_PHONE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_IDENTITY = re.compile(r"(?<!\d)\d{17}[0-9Xx](?!\d)")
_EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![\w.-])")
_LABELED_PERSONAL_DATA = re.compile(
    r"(?:学生|孩子|未成年人)?姓名[：:]\s*\S{2,20}|"
    r"(?:学校|班级|家庭住址|微信号|邮箱)[：:]\s*\S{2,40}"
)
_PROMPT_CONTROL = re.compile(
    r"</?(?:EVIDENCE|BRAND|REPAIR|PREVIOUS|DRAFT)>|(?:assistant|system|developer)\s*:",
    re.IGNORECASE,
)
_DATE = re.compile(r"20\d{2}年(?:1[0-2]|0?[1-9])月(?:3[01]|[12]\d|0?[1-9])日")
_FACT_LIKE_NUMBER = re.compile(r"(?:\d+(?:\.\d+)?%|20\d{2}年|\d+(?:万|亿|名|项|个))")
_FACT_VERB = re.compile(r"(?:发布|宣布|达到|增长|下降|推出|成立|获得|完成|超过)")
_PROMOTIONAL_SUPERLATIVE = re.compile(
    r"(?:行业|国内|全球|全国|世界)?首个|唯一(?:的)?|遥遥领先|"
    r"(?:行业|全球|全国|世界)(?:最大|最高|最强|第一)"
)
_SENTENCE = re.compile(r"[^。！？!?；;]+[。！？!?；;]?")
_DANGLING_DEPENDENT_CLAUSE = re.compile(
    r"^(?:当|在|进入|完成|经过|随着|如果|为了|通过).{0,60}(?:后|时|中|下|前|以来|之后|之时)$"
)
_SUPPORT_TEXT = re.compile(r"[\W_]+", re.UNICODE)
_NUMBER_TOKEN = re.compile(r"\d+(?:\.\d+)?%?")
_PREVIEW_PROFILES = frozenset({"preview", "preview-v1", "preview-v2"})
_PREVIEW_RULE_VERSIONS = frozenset(
    {
        "preview-v1",
        "preview-v2",
        "preview-v3-length-emoji",
        "preview-v4-length-emoji-advisory",
        "preview-v5-paragraph-emoji-advisory",
        "preview-v6-local-relaxed",
    }
)
_LOCAL_PREVIEW_RULE_VERSION = "preview-v6-local-relaxed"
_PREVIEW_DETERMINISTIC_WARNING_CODES_BY_VERSION = {
    "preview-v1": frozenset(
        {
            "unverified_superlative",
            "incomplete_sentence",
        }
    ),
    "preview-v2": frozenset(
        {
            "unverified_superlative",
            "incomplete_sentence",
            "claim_not_in_copy",
            "source_note_unlinked",
        }
    ),
    "preview-v3-length-emoji": frozenset(
        {
            "unverified_superlative",
            "incomplete_sentence",
            "claim_not_in_copy",
            "source_note_unlinked",
        }
    ),
    "preview-v4-length-emoji-advisory": frozenset(
        {
            "unverified_superlative",
            "incomplete_sentence",
            "claim_not_in_copy",
            "source_note_unlinked",
        }
    ),
    "preview-v5-paragraph-emoji-advisory": frozenset(
        {
            "unverified_superlative",
            "incomplete_sentence",
            "claim_not_in_copy",
            "source_note_unlinked",
        }
    ),
}
_LOCAL_PREVIEW_DETERMINISTIC_HARD_CODES = frozenset(
    {
        "unknown_evidence_id",
        "unknown_brand_chunk_id",
        "unbound_external_fact",
        "brand_as_fact_evidence",
        "evidence_as_brand_binding",
        "unbound_brand_statement",
        "opinion_has_binding",
        "opinion_smuggles_fact",
    }
)
# All visible copy-format misses are advisory and may consume the single bounded repair.
COPY_FORMAT_ADVISORY_CODES = frozenset({"copy_length", "copy_emoji_count", "copy_paragraph_format"})
COPY_FORMAT_REPAIR_CODES = COPY_FORMAT_ADVISORY_CODES
_COPY_ADVISORY_AUDIT_CODES = COPY_FORMAT_ADVISORY_CODES
_PREVIEW_AUDIT_WARNING_CODES = frozenset(
    {
        "brand_fit",
        "brand_tone",
        "tone_mismatch",
        "fluency",
        "copy_fluency",
        "exaggeration",
        "marketing_exaggeration",
        "marketing_expression",
        "promotional_language",
    }
)
_REQUIRED_HASHTAG = "#赛先生科学"


def validate_material_draft(
    draft: MaterialDraft,
    *,
    topic: LockedTopicContext,
    brand_context: tuple[ActiveBrandContext, ...],
    rule_version: str | None = None,
) -> tuple[CopyIssue, ...]:
    """Deterministic authority gate. LLM audit cannot override these issues."""

    issues: list[CopyIssue] = []
    evidence_by_id = {item.evidence_id: item for item in topic.evidence}
    brand_by_id = {item.chunk_id: item for item in brand_context}
    copy_body = extract_copy_body(draft.copywriting)
    hanzi_count = count_hanzi(copy_body)
    if hanzi_count > 300:
        issues.append(
            _issue(
                "copy_length",
                f"朋友圈正文汉字数为{hanzi_count}，目标为不超过300个（不含标签、标点、空格、数字、英文和emoji）",
                field="copywriting",
                severity="warning",
            )
        )
    emoji_count = count_emojis(copy_body)
    if not 6 <= emoji_count <= 12:
        issues.append(
            _issue(
                "copy_emoji_count",
                f"朋友圈正文emoji目标为6到12个，当前为{emoji_count}个",
                field="copywriting",
                severity="warning",
            )
        )
    if not has_copy_paragraph_format(draft.copywriting):
        issues.append(
            _issue(
                "copy_paragraph_format",
                "朋友圈正文主体必须恰好3个自然段，每段恰好2行非空手工文字，段间恰好1个空白行，且每段首尾必须是emoji",
                field="copywriting",
                severity="warning",
            )
        )
    if not 10 <= len(draft.parent_takeaway) <= 180:
        issues.append(
            _issue("parent_takeaway_length", "家长价值应为10到180个字符", field="parent_takeaway")
        )
    if not 5 <= len(draft.interaction) <= 120:
        issues.append(_issue("interaction_length", "互动问题应为5到120个字符", field="interaction"))
    if not 8 <= len(draft.image_prompt) <= 500:
        issues.append(
            _issue("image_prompt_length", "图片提示词应为8到500个字符", field="image_prompt")
        )
    hashtags = extract_trailing_hashtags(draft.copywriting)
    if has_non_trailing_hashtags(draft.copywriting):
        issues.append(
            _issue(
                "hashtag_placement",
                "朋友圈正文标签只能出现在末行",
                field="copywriting",
            )
        )
    if not hashtags:
        issues.append(
            _issue(
                "hashtag_format",
                "朋友圈正文末尾必须单独一行放置2到3个规范标签",
                field="copywriting",
            )
        )
    elif len(hashtags) not in {2, 3}:
        issues.append(
            _issue("hashtag_count", "朋友圈正文末尾必须有2到3个标签", field="copywriting")
        )
    elif hashtags[0] != _REQUIRED_HASHTAG:
        issues.append(
            _issue(
                "required_hashtag",
                "朋友圈正文标签首位必须固定为#赛先生科学",
                field="copywriting",
            )
        )

    all_output = "\n".join(
        (
            draft.copywriting,
            draft.parent_takeaway,
            draft.interaction,
            draft.source_note,
            draft.image_prompt,
        )
    )
    _append_phrase_issues(issues, all_output, _BANNED_MARKETING, "prohibited_marketing")
    _append_phrase_issues(issues, all_output, _ANXIETY, "education_anxiety")
    _append_phrase_issues(issues, all_output, _PROMPT_INJECTION, "prompt_injection_echo")
    _append_phrase_issues(issues, draft.image_prompt, _UNSAFE_IMAGE, "unsafe_image_prompt")
    _append_phrase_issues(issues, all_output, _PUBLISHING, "automatic_publishing")
    if _PROMPT_CONTROL.search(all_output):
        issues.append(_issue("prompt_injection_echo", "文案回显了提示词控制标记"))
    if _PROMOTIONAL_SUPERLATIVE.search(all_output):
        issues.append(
            _issue(
                "unverified_superlative",
                "文案不得直接使用首个、唯一或行业最高级等强宣传表述",
            )
        )
    if _contains_dangling_clause(draft.copywriting):
        issues.append(
            _issue(
                "incomplete_sentence",
                "朋友圈正文包含未完成的条件、时间或场景分句",
                field="copywriting",
            )
        )
    if (
        _PHONE.search(all_output)
        or _IDENTITY.search(all_output)
        or _EMAIL.search(all_output)
        or _LABELED_PERSONAL_DATA.search(all_output)
    ):
        issues.append(_issue("personal_data", "文案不得包含个人联系信息或身份信息"))

    evidence_text = "\n".join(
        [topic.title or "", topic.summary or ""] + [item.exact_quote for item in topic.evidence]
    )
    for date_token in set(_DATE.findall(all_output)):
        if date_token not in evidence_text and date_token != _business_date_zh(topic.business_date):
            issues.append(_issue("unbound_date", "文案日期不在已锁定事实证据中"))

    external_fact_count = 0
    for claim in draft.claims:
        if claim.text not in draft.copywriting:
            issues.append(
                _issue(
                    "claim_not_in_copy",
                    "结构化主张必须出现在朋友圈正文中",
                    claim_id=claim.id,
                )
            )
        if claim.kind == "external_fact":
            external_fact_count += 1
            if not claim.evidence_ids:
                issues.append(
                    _issue("unbound_external_fact", "外部事实缺少证据绑定", claim_id=claim.id)
                )
            for evidence_id in claim.evidence_ids:
                if evidence_id not in evidence_by_id:
                    issues.append(
                        _issue(
                            "unknown_evidence_id",
                            "外部事实引用了本次输入之外的证据",
                            claim_id=claim.id,
                        )
                    )
            bound_evidence = tuple(
                evidence_by_id[evidence_id]
                for evidence_id in claim.evidence_ids
                if evidence_id in evidence_by_id
            )
            if bound_evidence and not _claim_has_minimum_evidence_support(
                claim.text, bound_evidence
            ):
                issues.append(
                    _issue(
                        "evidence_text_mismatch",
                        "外部事实与所绑定证据缺少最低文本支持",
                        claim_id=claim.id,
                    )
                )
            if claim.brand_chunk_ids:
                issues.append(
                    _issue("brand_as_fact_evidence", "品牌资料不能支持外部事实", claim_id=claim.id)
                )
        elif claim.kind == "brand_statement":
            if claim.evidence_ids:
                issues.append(
                    _issue(
                        "evidence_as_brand_binding",
                        "品牌主张不能占用外部事实绑定",
                        claim_id=claim.id,
                    )
                )
            if not claim.brand_chunk_ids:
                issues.append(
                    _issue("unbound_brand_statement", "品牌主张缺少品牌切片绑定", claim_id=claim.id)
                )
            for chunk_id in claim.brand_chunk_ids:
                if chunk_id not in brand_by_id:
                    issues.append(
                        _issue(
                            "unknown_brand_chunk_id",
                            "品牌主张引用了本次输入之外的品牌切片",
                            claim_id=claim.id,
                        )
                    )
        else:
            if claim.evidence_ids or claim.brand_chunk_ids:
                issues.append(
                    _issue("opinion_has_binding", "观点不得伪装为事实或品牌绑定", claim_id=claim.id)
                )
            if _FACT_LIKE_NUMBER.search(claim.text) and _FACT_VERB.search(claim.text):
                issues.append(
                    _issue(
                        "opinion_smuggles_fact",
                        "观点包含可验证事实，应改为外部事实并绑定证据",
                        claim_id=claim.id,
                    )
                )
    if external_fact_count and not draft.source_note.strip():
        issues.append(
            _issue("missing_source_note", "含外部事实的文案必须包含来源说明", field="source_note")
        )
    if external_fact_count and not any(
        evidence.source_name in draft.source_note for evidence in topic.evidence
    ):
        issues.append(
            _issue("source_note_unlinked", "来源说明应标明已绑定的权威来源", field="source_note")
        )
    external_claim_texts = tuple(
        claim.text for claim in draft.claims if claim.kind == "external_fact"
    )
    if _contains_unclaimed_fact_like_sentence(draft.copywriting, external_claim_texts):
        issues.append(
            _issue(
                "unclaimed_external_fact",
                "正文中的可验证数值事实必须进入结构化外部事实主张",
                field="copywriting",
            )
        )
    deduplicated = _deduplicate_issues(issues)
    preview_rule_version = _preview_copy_rule_version(
        scoring_profile=topic.scoring_profile,
        rule_version=rule_version,
    )
    if preview_rule_version is not None:
        warning_codes = _PREVIEW_DETERMINISTIC_WARNING_CODES_BY_VERSION.get(
            preview_rule_version, ()
        )
        deduplicated = [
            issue.model_copy(update={"severity": "warning"})
            if (
                preview_rule_version == _LOCAL_PREVIEW_RULE_VERSION
                and issue.code not in _LOCAL_PREVIEW_DETERMINISTIC_HARD_CODES
            )
            or issue.code in warning_codes
            else issue
            for issue in deduplicated
        ]
    return tuple(deduplicated)


def is_preview_copy_profile(scoring_profile: str) -> bool:
    return scoring_profile.strip().casefold() in _PREVIEW_PROFILES


def is_preview_copy_rule_version(rule_version: str) -> bool:
    return rule_version.strip().casefold() in _PREVIEW_RULE_VERSIONS


def is_local_preview_copy_rule_version(rule_version: str) -> bool:
    return rule_version.strip().casefold() == _LOCAL_PREVIEW_RULE_VERSION


def apply_copy_audit_policy(
    verdict: AuditVerdict,
    *,
    scoring_profile: str | None = None,
    rule_version: str | None = None,
) -> AuditVerdict:
    uses_preview = _uses_preview_copy_policy(
        scoring_profile=scoring_profile,
        rule_version=rule_version,
    )
    uses_local_preview = is_local_preview_copy_rule_version(rule_version or "")
    has_advisory_issue = any(issue.code in _COPY_ADVISORY_AUDIT_CODES for issue in verdict.issues)
    if not uses_preview and not has_advisory_issue:
        return verdict
    issues = tuple(
        issue.model_copy(update={"severity": "warning"})
        if uses_local_preview
        or issue.code in _COPY_ADVISORY_AUDIT_CODES
        or (uses_preview and issue.code in _PREVIEW_AUDIT_WARNING_CODES)
        else issue
        for issue in verdict.issues
    )
    return AuditVerdict(
        accepted=not any(issue.severity == "error" for issue in issues),
        issues=issues,
    )


def _uses_preview_copy_policy(
    *,
    scoring_profile: str | None,
    rule_version: str | None,
) -> bool:
    return (
        _preview_copy_rule_version(
            scoring_profile=scoring_profile,
            rule_version=rule_version,
        )
        is not None
    )


def _preview_copy_rule_version(
    *,
    scoring_profile: str | None,
    rule_version: str | None,
) -> str | None:
    if rule_version is not None:
        candidate = rule_version.strip().casefold()
    else:
        if scoring_profile is None:
            raise ValueError("copy policy requires a rule version or scoring profile")
        profile = scoring_profile.strip().casefold()
        candidate = "preview-v1" if profile == "preview-v1" else "preview-v2"
        if profile not in _PREVIEW_PROFILES:
            return None
    return candidate if candidate in _PREVIEW_RULE_VERSIONS else None


def _issue(
    code: str,
    message: str,
    *,
    field: str | None = None,
    claim_id: str | None = None,
    severity: Literal["warning", "error"] = "error",
) -> CopyIssue:
    return CopyIssue(
        code=code,
        message=message,
        field=field,
        claim_id=claim_id,
        severity=severity,
    )


def _append_phrase_issues(
    issues: list[CopyIssue], text: str, phrases: tuple[str, ...], code: str
) -> None:
    if any(phrase.casefold() in text.casefold() for phrase in phrases):
        issues.append(_issue(code, "文案包含不允许的表达"))


def _business_date_zh(value: date) -> str:
    return f"{value.year}年{value.month}月{value.day}日"


def _contains_dangling_clause(text: str) -> bool:
    for sentence in _SENTENCE.findall(text):
        normalized = sentence.strip().rstrip("。！？!?；;").strip()
        if len(normalized) <= 64 and _DANGLING_DEPENDENT_CLAUSE.fullmatch(normalized):
            return True
    return False


def _claim_has_minimum_evidence_support(
    claim_text: str, evidence: tuple[EligibleEvidence, ...]
) -> bool:
    normalized_claim = _normalize_support_text(claim_text)
    if not normalized_claim:
        return False
    normalized_quotes = tuple(_normalize_support_text(item.exact_quote) for item in evidence)
    if any(normalized_claim in quote for quote in normalized_quotes):
        return True
    claim_numbers = set(_NUMBER_TOKEN.findall(claim_text))
    evidence_numbers = set(_NUMBER_TOKEN.findall("\n".join(item.exact_quote for item in evidence)))
    if not claim_numbers.issubset(evidence_numbers):
        return False
    claim_bigrams = _bigrams(normalized_claim)
    if not claim_bigrams:
        return any(
            normalized_claim in quote or quote in normalized_claim for quote in normalized_quotes
        )
    return any(
        len(claim_bigrams & _bigrams(quote)) / len(claim_bigrams) >= 0.3
        for quote in normalized_quotes
    )


def _normalize_support_text(value: str) -> str:
    return _SUPPORT_TEXT.sub("", value.casefold())


def _bigrams(value: str) -> set[str]:
    return {value[index : index + 2] for index in range(max(0, len(value) - 1))}


def _contains_unclaimed_fact_like_sentence(
    copywriting: str, external_claim_texts: tuple[str, ...]
) -> bool:
    for sentence in _SENTENCE.findall(copywriting):
        normalized = sentence.strip()
        if not _FACT_LIKE_NUMBER.search(normalized):
            continue
        if not any(
            claim_text in normalized or normalized.rstrip("。！？!?；;") in claim_text
            for claim_text in external_claim_texts
        ):
            return True
    return False


def _deduplicate_issues(issues: list[CopyIssue]) -> list[CopyIssue]:
    seen: set[tuple[str, str | None, str | None]] = set()
    result: list[CopyIssue] = []
    for issue in issues:
        key = (issue.code, issue.field, issue.claim_id)
        if key not in seen:
            seen.add(key)
            result.append(issue)
    return result
