from __future__ import annotations

import re
from dataclasses import dataclass

from app.domain.science_relevance import normalize_science_text

SCIENCE_POLICY_PRIORITY_RULE_VERSION = "science-policy-priority-v2"

_TOPIC_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?:科学|科技|科创).{0,4}(?:教育|课程|教学|课堂|学科)"),
    re.compile(r"(?:人工智能|ai).{0,4}(?:教育|课程|教学|课堂|学科)"),
    re.compile(r"机器人.{0,4}(?:教育|课程|教学|课堂|学科)"),
)
_ACTION_PATTERN = re.compile(r"行动|指南|方案|通知|意见|标准|实施|部署|计划|规划|办法|细则")
_EXCLUDED_ITEM_PATTERN = re.compile(r"教材|教科书|课本|读本|会议|座谈会|研讨会|论坛|发布会")


@dataclass(frozen=True, slots=True)
class SciencePolicyPriorityResult:
    is_eligible: bool
    reason_code: str


def evaluate_science_policy_priority(
    title: str | None,
    summary: str | None,
) -> SciencePolicyPriorityResult:
    """Classify the narrow Ministry science-policy Top 1 priority cohort."""

    normalized_title = normalize_science_text(title)
    normalized_summary = normalize_science_text(summary)
    if _EXCLUDED_ITEM_PATTERN.search(normalized_title) is not None:
        return SciencePolicyPriorityResult(False, "science_policy_excluded_item")

    searchable_text = f"{normalized_title}\n{normalized_summary}"
    if not any(pattern.search(searchable_text) for pattern in _TOPIC_PATTERNS):
        return SciencePolicyPriorityResult(False, "science_policy_topic_missing")
    if _ACTION_PATTERN.search(searchable_text) is None:
        return SciencePolicyPriorityResult(False, "science_policy_action_missing")
    return SciencePolicyPriorityResult(True, "science_policy")
