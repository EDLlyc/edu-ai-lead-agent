from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from app.domain.editorial_relevance import normalize_editorial_text

EDUCATION_POLICY_SIGNAL_RULE_VERSION = "education-policy-signal-v1"
EDUCATION_POLICY_TEXT_LIMIT = 6_000


class EducationPolicyLevel(StrEnum):
    NATIONAL = "national"
    PROVINCIAL = "provincial"


@dataclass(frozen=True, slots=True)
class EducationPolicySignalResult:
    is_signal: bool
    reason_code: str
    level: EducationPolicyLevel | None = None
    rule_version: str = EDUCATION_POLICY_SIGNAL_RULE_VERSION


_QUOTE = r"[\"'\u201c\u201d\u2018\u2019\u300c\u300d]?"

# "教育部门" is a generic local department, and bare "国办"/"中办" also occur inside ordinary
# words such as "全国办学" or "集中办理"; only unambiguous issuer spellings count.
_NATIONAL_ISSUER_PATTERN = re.compile(
    r"中共中央|党中央|国务院|中央办公厅|中办\s*、?\s*国办|国办(?:印发|发布|关于|近日)|"
    r"教育部(?!门)|国家教育|国新办|全国人大|人大常委会|中央教育工作领导小组|"
    r"国家发展改革委|人力资源社会保障部|国家教材委员会|国家语委"
)
_PROVINCE_NAMES = (
    "北京|天津|上海|重庆|河北|山西|辽宁|吉林|黑龙江|江苏|浙江|安徽|福建|江西|山东|河南|"
    "湖北|湖南|广东|海南|四川|贵州|云南|陕西|甘肃|青海|内蒙古|广西|西藏|宁夏|新疆"
)
_PROVINCIAL_ISSUER_PATTERN = re.compile(
    rf"(?:{_PROVINCE_NAMES})"
    r"(?:省|市|自治区|壮族自治区|回族自治区|维吾尔自治区)?"
    r"(?:委|党委|人民政府|政府|政府办公厅|教育厅|教委|教育委员会|教育考试院|招生考试院)"
)

_EDUCATION_POLICY_SUBJECT_PATTERN = re.compile(
    r"教育强国|教育现代化|教育(?:发展)?规划|教育事业|教育(?:综合|评价)?改革|教育公平|"
    rf"{_QUOTE}十五五{_QUOTE}.{{0,12}}教育|教育.{{0,12}}{_QUOTE}十五五{_QUOTE}|"
    r"全国教育(?:工作|大)会|"
    r"高等教育|高校|双一流|一流大学|一流学科|本科教育|研究生教育|学位|"
    r"基础教育|义务教育|学前教育|普通高中|高中阶段|中小学|幼儿园|"
    r"职业教育|职教|产教融合|"
    r"中考|高考|招生考试|考试招生|招生制度|招生政策|强基计划|综合评价招生|"
    r"课程改革|课程标准|课程方案|新课标|教材|课后服务|双减|作业管理|"
    r"教师队伍|教师(?:减负|待遇|培养|编制|资格)|师范教育|"
    r"拔尖创新人才|科学教育|人工智能\s*\+?\s*教育|(?<![a-z0-9])ai\s*教育|"
    r"教育数字化|智慧教育|立德树人|思政课|劳动教育|体育(?:课|中考|教育)|美育|"
    r"心理健康教育|近视防控|校外培训|民办教育|学位供给|教育资源"
)
_POLICY_ACTION_PATTERN = re.compile(
    r"印发|出台|发布|部署|启动|实施|推进|推动|深化|改革|"
    r"意见|方案|规划|纲要|通知|办法|规定|细则|行动计划|指南|条例|决定|"
    r"发布会|答记者问|吹风会|解读|"
    r"重点发力|重点任务|总体要求|目标任务|将重点|力争到\s*20\d\d|到\s*20\d\d\s*年"
)
# Title-only fetch ordering may use the bare word "教育" with an explicit planning/reform action.
_TITLE_PLANNING_ACTION_PATTERN = re.compile(
    rf"未来五年|{_QUOTE}十五五{_QUOTE}|重点发力|总体要求|规划|纲要|改革|意见|方案|部署"
)
_BARE_EDUCATION_PATTERN = re.compile(r"教育(?!部门)")

_MARKETING_PATTERN = re.compile(
    r"培训机构|辅导班|冲刺班|课程报名|招生广告|招生简章|招生咨询|扫码(?:报名|咨询)|"
    r"添加微信|报名优惠|限时报名|志愿填报服务|保录|保过|包过|内部名额|降分录取|百分百录取"
)
_SCORE_LINE_PATTERN = re.compile(r"分数线(?:汇总|大全|排名|预测)|历年分数线|录取分数线")
_DEADLINE_PATTERN = re.compile(r"报名(?:截止|倒计时|最后一天)|最后机会|错过再等一年")
_PERSONNEL_PATTERN = re.compile(r"任免|任命|免去|履新|调任|接任|拟任|任前公示")
_CAMPUS_EVENT_PATTERN = re.compile(
    r"开学典礼|毕业典礼|运动会|校庆|招聘会|宣讲会|迎新|文艺汇演|校园开放日"
)
# Routine exam logistics are education news, but not a policy direction unless a reform or
# policy document is also present in the same title.
_EXAM_LOGISTICS_PATTERN = re.compile(r"报名|准考证|成绩查询|考点|考场|考务|志愿填报")
_EXAM_REFORM_PATTERN = re.compile(r"改革|意见|方案|规划|政策|办法|制度")

# Input is NFKC-normalised, so full-width ! ? ; have already become ASCII.
_SEGMENT_SPLIT_PATTERN = re.compile(r"[。!?;\n]+")


def _title_exclusion(title: str) -> str | None:
    if _PERSONNEL_PATTERN.search(title):
        return "education_policy_personnel_excluded"
    if _CAMPUS_EVENT_PATTERN.search(title):
        return "education_policy_campus_event_excluded"
    if _EXAM_LOGISTICS_PATTERN.search(title) and not _EXAM_REFORM_PATTERN.search(title):
        return "education_policy_exam_logistics_excluded"
    return None


def _text_exclusion(text: str) -> str | None:
    if _MARKETING_PATTERN.search(text):
        return "education_policy_marketing_excluded"
    if _SCORE_LINE_PATTERN.search(text):
        return "education_policy_score_line_excluded"
    if _DEADLINE_PATTERN.search(text):
        return "education_policy_deadline_excluded"
    return None


def _issuer_level(text: str) -> EducationPolicyLevel | None:
    if _NATIONAL_ISSUER_PATTERN.search(text):
        return EducationPolicyLevel.NATIONAL
    if _PROVINCIAL_ISSUER_PATTERN.search(text):
        return EducationPolicyLevel.PROVINCIAL
    return None


def _has_policy_substance(text: str) -> bool:
    return bool(_EDUCATION_POLICY_SUBJECT_PATTERN.search(text)) and bool(
        _POLICY_ACTION_PATTERN.search(text)
    )


def evaluate_education_policy_signal(
    title: str | None,
    summary: str | None,
) -> EducationPolicySignalResult:
    """Recognise a national or provincial education-policy direction from stored text.

    The issuer, an education-policy subject and a policy action must meet in one bounded
    segment (the title or a single summary sentence), or the title itself must carry the
    subject and action while an issuer appears elsewhere. This keeps an incidental ministry
    mention in an unrelated technology story from becoming an education-policy signal.
    """

    normalized_title = normalize_editorial_text((title or "")[:EDUCATION_POLICY_TEXT_LIMIT])
    normalized_summary = normalize_editorial_text((summary or "")[:EDUCATION_POLICY_TEXT_LIMIT])
    if not normalized_title and not normalized_summary:
        return EducationPolicySignalResult(False, "education_policy_empty_text")

    title_exclusion = _title_exclusion(normalized_title)
    if title_exclusion is not None:
        return EducationPolicySignalResult(False, title_exclusion)
    text_exclusion = _text_exclusion(f"{normalized_title}\n{normalized_summary}")
    if text_exclusion is not None:
        return EducationPolicySignalResult(False, text_exclusion)
    if normalized_title and not (
        _EDUCATION_POLICY_SUBJECT_PATTERN.search(normalized_title)
        or _BARE_EDUCATION_PATTERN.search(normalized_title)
        or _issuer_level(normalized_title) is not None
    ):
        # The headline decides what the story is about; a ministry remark inside a technology
        # report does not turn that report into an education-policy direction.
        return EducationPolicySignalResult(False, "education_policy_not_headline_topic")

    segments = [
        segment
        for segment in (
            normalized_title,
            *_SEGMENT_SPLIT_PATTERN.split(normalized_summary),
        )
        if segment.strip()
    ]
    qualifying_levels = [
        level
        for segment in segments
        if _has_policy_substance(segment) and (level := _issuer_level(segment)) is not None
    ]
    if not qualifying_levels and _has_policy_substance(normalized_title):
        qualifying_levels = [
            level for segment in segments if (level := _issuer_level(segment)) is not None
        ]
    if not qualifying_levels:
        has_subject = any(_EDUCATION_POLICY_SUBJECT_PATTERN.search(s) for s in segments)
        has_issuer = any(_issuer_level(s) is not None for s in segments)
        if not has_subject:
            return EducationPolicySignalResult(False, "education_policy_subject_missing")
        if not has_issuer:
            return EducationPolicySignalResult(False, "education_policy_issuer_missing")
        return EducationPolicySignalResult(False, "education_policy_action_missing")

    level = (
        EducationPolicyLevel.NATIONAL
        if EducationPolicyLevel.NATIONAL in qualifying_levels
        else EducationPolicyLevel.PROVINCIAL
    )
    return EducationPolicySignalResult(True, f"education_policy_signal_{level.value}", level)


def is_education_policy_title(title: str | None) -> bool:
    """Lenient title check used only to order which listing items get a detail fetch."""

    normalized = normalize_editorial_text((title or "")[:EDUCATION_POLICY_TEXT_LIMIT])
    if not normalized:
        return False
    if _title_exclusion(normalized) is not None or _text_exclusion(normalized) is not None:
        return False
    has_subject = _EDUCATION_POLICY_SUBJECT_PATTERN.search(normalized) is not None
    has_bare_education = _BARE_EDUCATION_PATTERN.search(normalized) is not None
    if _issuer_level(normalized) is not None and (has_subject or has_bare_education):
        return True
    if has_subject and _POLICY_ACTION_PATTERN.search(normalized):
        return True
    return has_bare_education and _TITLE_PLANNING_ACTION_PATTERN.search(normalized) is not None
