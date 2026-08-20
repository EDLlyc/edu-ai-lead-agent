from __future__ import annotations

import re
from dataclasses import dataclass

from app.domain.editorial_relevance import (
    ScienceTechContentSignal,
    ScienceTechEditorialCohort,
)
from app.domain.science_policy_priority import evaluate_science_policy_priority
from app.domain.science_relevance import normalize_science_text

MINISTRY_EDUCATION_PRIORITY_V3_RULE_VERSION = "ministry-education-priority-v3"
MINISTRY_EDUCATION_PRIORITY_V4_RULE_VERSION = (
    "ministry-education-priority-v4-substantive-science-education"
)
# Historical public alias. Keep it pinned to v3 so imports used by immutable .6-.9
# snapshots cannot silently change when the current policy advances.
MINISTRY_EDUCATION_PRIORITY_RULE_VERSION = MINISTRY_EDUCATION_PRIORITY_V3_RULE_VERSION
MOE_SCIENCE_TOP1_PRIORITY_POLICY = "moe-science-top1-v1"

_SCIENCE_EDUCATION_TOPIC_PATTERN = re.compile(
    r"科学教育|科技教育|科创教育|科学素养|科技素养|科创人才|科技人才|"
    r"基础学科拔尖人才|stem\s*教育|steam\s*教育|"
    r"(?:人工智能|(?<![a-z0-9])ai(?![a-z0-9])|机器人|编程|航天|天文|物理|化学|生物)"
    r".{0,12}(?:教育|课程|教学|课堂|教师|学生|青少年|人才培养|科学普及|科普|进校园)"
)
_POLICY_ARTIFACT_PATTERN = re.compile(
    r"政策|专项行动|行动方案|行动计划|指南|方案|通知|意见|标准|规划|办法|细则|"
    r"改革方案|试点方案"
)
_TEACHING_OR_PRACTICE_PATTERN = re.compile(
    r"(?:科学|科技|科创|人工智能|(?<![a-z0-9])ai(?![a-z0-9])|机器人|编程|"
    r"stem|steam|航天|天文|物理|化学|生物)"
    r".{0,16}(?:课程|教学|课堂|实践|实验|项目式|平台|基地|素养|竞赛|研学|进校园|科普)"
    r"|(?:课程|教学|课堂|实践|实验|项目式|平台|基地|竞赛|研学)"
    r".{0,16}(?:科学|科技|科创|人工智能|(?<![a-z0-9])ai(?![a-z0-9])|机器人|编程|"
    r"stem|steam|航天|天文|物理|化学|生物)"
)
_TALENT_DEVELOPMENT_PATTERN = re.compile(
    r"(?:科学|科技|科创|人工智能|机器人|基础学科).{0,16}"
    r"(?:人才|教师|学生|青少年).{0,10}(?:培养|培训|选拔|发展|成长)"
    r"|(?:人才|教师|学生|青少年).{0,10}(?:培养|培训|选拔|发展|成长)"
    r".{0,16}(?:科学|科技|科创|人工智能|机器人|基础学科)"
)
_PROMOTION_PATTERN = re.compile(
    r"培训机构|辅导班|冲刺班|招生广告|招生简章|招生咨询|课程报名|报名优惠|"
    r"限时报名|扫码(?:报名|咨询)|添加微信|保录|保过|包过|招商|加盟"
)
_HOMONYM_PATTERN = re.compile(r"彩票|体彩|足球|篮球|体育赛事|消费券|购物节|促销")
_EVENT_WRAPPER_PATTERN = re.compile(r"会议|座谈会|研讨会|论坛|发布会|交流会|活动举行")


@dataclass(frozen=True, slots=True)
class MinistryEducationPriorityResult:
    is_eligible: bool
    reason_code: str
    rule_version: str = MINISTRY_EDUCATION_PRIORITY_RULE_VERSION


def evaluate_ministry_education_priority(
    *,
    topic_priority_policy: str | None,
    editorial_cohort: ScienceTechEditorialCohort,
) -> MinistryEducationPriorityResult:
    """Compose authenticated Ministry policy metadata with the governed v2 cohort."""

    if topic_priority_policy is None:
        return MinistryEducationPriorityResult(False, "no_topic_priority_policy")
    if topic_priority_policy != MOE_SCIENCE_TOP1_PRIORITY_POLICY:
        return MinistryEducationPriorityResult(False, "unsupported_topic_priority_policy")
    if editorial_cohort is not ScienceTechEditorialCohort.SCIENCE_TECHNOLOGY_EDUCATION_PRIORITY:
        return MinistryEducationPriorityResult(False, "ministry_education_topic_missing")
    return MinistryEducationPriorityResult(True, "ministry_education_priority")


def evaluate_substantive_ministry_education_priority(
    *,
    topic_priority_policy: str | None,
    editorial_cohort: ScienceTechEditorialCohort,
    title: str | None,
    summary: str | None,
    content_signals: tuple[ScienceTechContentSignal, ...] = (),
) -> MinistryEducationPriorityResult:
    """Apply v4 only to substantive, authenticated science-education content."""

    def result(is_eligible: bool, reason_code: str) -> MinistryEducationPriorityResult:
        return MinistryEducationPriorityResult(
            is_eligible,
            reason_code,
            rule_version=MINISTRY_EDUCATION_PRIORITY_V4_RULE_VERSION,
        )

    if topic_priority_policy is None:
        return result(False, "no_topic_priority_policy")
    if topic_priority_policy != MOE_SCIENCE_TOP1_PRIORITY_POLICY:
        return result(False, "unsupported_topic_priority_policy")
    if editorial_cohort is not ScienceTechEditorialCohort.SCIENCE_TECHNOLOGY_EDUCATION_PRIORITY:
        return result(False, "ministry_education_topic_missing")

    normalized_title = normalize_science_text(title)
    normalized_summary = normalize_science_text(summary)
    searchable_text = f"{normalized_title}\n{normalized_summary}"
    if _PROMOTION_PATTERN.search(searchable_text) is not None:
        return result(False, "ministry_science_education_promotion_excluded")
    if _HOMONYM_PATTERN.search(searchable_text) is not None:
        return result(False, "ministry_science_education_homonym_excluded")
    if _SCIENCE_EDUCATION_TOPIC_PATTERN.search(searchable_text) is None:
        if (
            ScienceTechContentSignal.EVENT_OR_CONFERENCE in content_signals
            or _EVENT_WRAPPER_PATTERN.search(normalized_title) is not None
        ):
            return result(False, "ministry_science_education_event_only")
        return result(False, "ministry_science_education_substance_missing")

    science_policy = evaluate_science_policy_priority(title, summary)
    is_event_wrapper = (
        ScienceTechContentSignal.EVENT_OR_CONFERENCE in content_signals
        or _EVENT_WRAPPER_PATTERN.search(normalized_title) is not None
    )
    has_policy_action = (
        science_policy.is_eligible and not is_event_wrapper
    ) or _POLICY_ARTIFACT_PATTERN.search(searchable_text) is not None
    has_teaching_or_practice = _TEACHING_OR_PRACTICE_PATTERN.search(searchable_text) is not None
    has_talent_development = _TALENT_DEVELOPMENT_PATTERN.search(searchable_text) is not None
    if has_policy_action:
        return result(True, "ministry_science_education_policy_action")
    if has_teaching_or_practice:
        return result(True, "ministry_science_education_teaching_practice")
    if has_talent_development:
        return result(True, "ministry_science_education_talent_development")
    if is_event_wrapper:
        return result(False, "ministry_science_education_event_only")
    return result(False, "ministry_science_education_substance_missing")
