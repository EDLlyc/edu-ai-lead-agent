"""`.17` signal: a central-level policy document about science, technology or education.

The headline alone decides. A story qualifies only when a central issuer, a formal policy
document noun and a science/technology/education subject all appear in the same headline, and no
meeting, speech, inspection, diplomacy, trade or personnel marker is present. A headline that
merely contains 国务院 or 科技 therefore never qualifies.
"""

from __future__ import annotations

import re

from app.domain.editorial_relevance import normalize_editorial_text
from app.domain.topic_safety_signals import TopicSignal

NATIONAL_TECH_POLICY_RULE_VERSION = "national-tech-policy-signal-v1"
_TEXT_LIMIT = 600

# Input is NFKC-normalised and casefolded: keep Latin patterns lowercase. Bare 国办/中办 occur
# inside ordinary words (全国办学, 集中办理), so only unambiguous spellings count.
_ISSUER_PATTERN = re.compile(
    r"中共中央|党中央|国务院|中央办公厅|中办\s*、?\s*国办|国办(?:印发|发布|关于|近日)"
)
_DOCUMENT_PATTERN = re.compile(
    r"意见|方案|规划|纲要|行动计划|行动方案|办法|条例|决定|指导意见|若干措施|若干政策|通知"
)
_SUBJECT_PATTERN = re.compile(
    r"新质生产力|科技|科学|创新|人工智能|(?<![a-z0-9])ai(?![a-z0-9])|数字经济|数字中国|数据要素|"
    r"未来产业|战略性新兴产业|集成电路|量子|航天|制造强国|教育|人才"
)
# Meetings, speeches, inspections, diplomacy, trade and personnel items are news about people or
# events, not a policy document, even when a document noun appears ("听取意见").
_EXCLUDED_PATTERN = re.compile(
    r"会议|座谈|会见|会晤|会谈|讲话|考察|调研|致信|贺信|通电话|经贸|磋商|关税|任免|任命|免去"
)


def evaluate_national_tech_policy(title: str | None) -> TopicSignal:
    headline = normalize_editorial_text((title or "")[:_TEXT_LIMIT])
    if not headline:
        return TopicSignal(False, "national_tech_policy_empty_title")
    if _EXCLUDED_PATTERN.search(headline):
        return TopicSignal(False, "national_tech_policy_excluded_item")
    if not _ISSUER_PATTERN.search(headline):
        return TopicSignal(False, "national_tech_policy_issuer_missing")
    if not _DOCUMENT_PATTERN.search(headline):
        return TopicSignal(False, "national_tech_policy_document_missing")
    if not _SUBJECT_PATTERN.search(headline):
        return TopicSignal(False, "national_tech_policy_subject_missing")
    return TopicSignal(True, "national_tech_policy")
