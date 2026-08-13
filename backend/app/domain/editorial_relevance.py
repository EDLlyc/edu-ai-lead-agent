from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum

SCIENCE_AI_EDUCATION_RULE_VERSION = "science-ai-education-v1"
PRODUCT_MATRIX_FIT_RULE_VERSION = "product-matrix-fit-v1"
SCIENCE_TECH_EDITORIAL_RULE_VERSION = "science-tech-editorial-v2"
PRODUCT_MATRIX_FIT_V2_RULE_VERSION = "product-matrix-fit-v2-science-pathways"
EDITORIAL_CONTENT_CHARACTER_LIMIT = 6_000


def normalize_editorial_text(value: str | None) -> str:
    """Normalize untrusted editorial text without changing its factual content."""

    if not value:
        return ""
    normalized = unicodedata.normalize("NFKC", value).casefold()
    normalized = re.sub(r"[\u2010-\u2015_-]+", "-", normalized)
    return " ".join(normalized.split())


def _ascii_term(expression: str) -> re.Pattern[str]:
    return re.compile(rf"(?<![a-z0-9])(?:{expression})(?![a-z0-9])")


_EXPLICIT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("科学教育", re.compile(r"科学教育|科技教育|科创教育")),
    ("science education", _ascii_term(r"science[\s-]+education")),
    (
        "人工智能教育",
        re.compile(r"人工智能教育|(?<![a-z0-9])ai\s*教育|智能教育"),
    ),
    ("ai education", _ascii_term(r"(?:ai|artificial[\s-]+intelligence)[\s-]+education")),
    ("科学素养", re.compile(r"科学素养|科技素养")),
    ("science literacy", _ascii_term(r"science[\s-]+literacy")),
    ("人工智能素养", re.compile(r"人工智能素养|(?<![a-z0-9])ai\s*素养")),
    ("ai literacy", _ascii_term(r"(?:ai|artificial[\s-]+intelligence)[\s-]+literacy")),
    ("stem education", _ascii_term(r"(?:stem|steam)[\s-]+(?:education|learning|curriculum)")),
    ("STEM教育", re.compile(r"(?:stem|steam)\s*(?:教育|课程|学习|课堂)")),
    ("科学探究", re.compile(r"科学探究|探究式科学|科学实践")),
    ("inquiry science", _ascii_term(r"(?:inquiry[\s-]+based[\s-]+science|science[\s-]+inquiry)")),
    ("青少年科创", re.compile(r"青少年.{0,8}(?:科创|科技创新|科学竞赛|机器人竞赛)")),
    (
        "youth science practice",
        _ascii_term(
            r"(?:youth|student|children(?:'s)?)[\s-]+(?:science|stem|robotics?)[\s-]+"
            r"(?:competition|camp|project|program|programme)"
        ),
    ),
)

_TOPIC_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("科学", re.compile(r"科学|科技|科创|科普")),
    (
        "人工智能",
        re.compile(
            r"人工智能|(?<![a-z0-9])ai(?![a-z0-9])|机器学习|大模型|"
            r"生成式\s*ai|(?<![a-z0-9])(?:openai|chatgpt)(?![a-z0-9])"
        ),
    ),
    ("机器人", re.compile(r"机器人|具身智能")),
    ("工程", re.compile(r"工程|3d\s*打印|编程|算法")),
    ("理科", re.compile(r"数学|物理|化学|生物|天文|航天")),
    ("science", _ascii_term(r"scien(?:ce|tific)|stem|steam")),
    (
        "artificial intelligence",
        _ascii_term(
            r"ai|artificial[\s-]+intelligence|machine[\s-]+learning|"
            r"generative[\s-]+ai|large[\s-]+language[\s-]+models?|llms?"
        ),
    ),
    ("robotics", _ascii_term(r"robotics?|embodied[\s-]+(?:ai|intelligence)")),
    ("engineering", _ascii_term(r"engineering|coding|programming|3d[\s-]+printing")),
    ("science subject", _ascii_term(r"mathematics|maths?|physics|chemistry|biology|astronomy")),
)

_CONTEXT_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("教育", re.compile(r"教育|教学|课堂|课程|学科")),
    ("学习者", re.compile(r"学生|青少年|儿童|孩子|中小学生|大学生")),
    ("教师", re.compile(r"教师|老师|师生|教研")),
    ("实践", re.compile(r"探究|实践|项目式|实验课|竞赛|夏令营|科学营|研学|社团")),
    (
        "education",
        _ascii_term(r"education|educational|curriculum|classroom"),
    ),
    ("learner", _ascii_term(r"students?|learners?|pupils?|children|youth|teenagers?")),
    ("teacher", _ascii_term(r"teachers?|educators?|instructors?")),
    (
        "practice",
        _ascii_term(
            r"project[\s-]+based|inquiry[\s-]+based|competition|hackathon|"
            r"science[\s-]+camp|study[\s-]+tour|field[\s-]+trip"
        ),
    ),
)


def _matches(text: str, patterns: tuple[tuple[str, re.Pattern[str]], ...]) -> tuple[str, ...]:
    return tuple(label for label, pattern in patterns if pattern.search(text) is not None)


def _has_nearby_pattern_pair(
    text: str,
    left_patterns: tuple[tuple[str, re.Pattern[str]], ...],
    right_patterns: tuple[tuple[str, re.Pattern[str]], ...],
    *,
    max_gap: int,
) -> bool:
    """Require two governed signals to occur in the same bounded text neighborhood."""

    left_matches = tuple(
        match for _label, pattern in left_patterns for match in pattern.finditer(text)
    )
    right_matches = tuple(
        match for _label, pattern in right_patterns for match in pattern.finditer(text)
    )
    return any(
        max(0, right.start() - left.end(), left.start() - right.end()) <= max_gap
        for left in left_matches
        for right in right_matches
    )


@dataclass(frozen=True, slots=True)
class ScienceAiEducationResult:
    is_eligible: bool
    score: float
    reason_codes: tuple[str, ...]
    matched_title_explicit_terms: tuple[str, ...]
    matched_body_explicit_terms: tuple[str, ...]
    matched_title_topic_terms: tuple[str, ...]
    matched_body_topic_terms: tuple[str, ...]
    matched_title_context_terms: tuple[str, ...]
    matched_body_context_terms: tuple[str, ...]
    body_characters_considered: int
    body_truncated: bool
    rule_version: str = SCIENCE_AI_EDUCATION_RULE_VERSION

    @property
    def matched_title_terms(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                (
                    *self.matched_title_explicit_terms,
                    *self.matched_title_topic_terms,
                    *self.matched_title_context_terms,
                )
            )
        )

    @property
    def matched_body_terms(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                (
                    *self.matched_body_explicit_terms,
                    *self.matched_body_topic_terms,
                    *self.matched_body_context_terms,
                )
            )
        )


def evaluate_science_ai_education_relevance(
    title: str | None,
    body: str | None = None,
    *,
    body_limit: int = EDITORIAL_CONTENT_CHARACTER_LIMIT,
) -> ScienceAiEducationResult:
    if body_limit < 1:
        raise ValueError("editorial relevance body limit must be positive")

    normalized_title = normalize_editorial_text(title)
    normalized_body = normalize_editorial_text(body)
    considered_body = normalized_body[:body_limit]
    title_explicit = _matches(normalized_title, _EXPLICIT_PATTERNS)
    body_explicit = _matches(considered_body, _EXPLICIT_PATTERNS)
    title_topics = _matches(normalized_title, _TOPIC_PATTERNS)
    body_topics = _matches(considered_body, _TOPIC_PATTERNS)
    title_context = _matches(normalized_title, _CONTEXT_PATTERNS)
    body_context = _matches(considered_body, _CONTEXT_PATTERNS)

    explicit = bool(title_explicit or body_explicit)
    has_topic = bool(title_topics or body_topics)
    has_context = bool(title_context or body_context)
    eligible = explicit or (has_topic and has_context)
    if explicit:
        reasons = ("explicit_science_ai_education_phrase",)
    elif eligible:
        reasons = ("science_ai_topic_with_education_context",)
    elif not normalized_title and not considered_body:
        reasons = ("empty_text",)
    elif not has_topic:
        reasons = ("missing_science_ai_topic",)
    else:
        reasons = ("missing_education_context",)

    if not eligible:
        score = 0.0
    else:
        score = 0.78 if explicit else 0.58
        score += min(0.12, 0.04 * len(set((*title_topics, *body_topics))))
        score += min(0.10, 0.04 * len(set((*title_context, *body_context))))
        if title_explicit:
            score += 0.05
        score = min(1.0, round(score, 4))

    return ScienceAiEducationResult(
        is_eligible=eligible,
        score=score,
        reason_codes=reasons,
        matched_title_explicit_terms=title_explicit,
        matched_body_explicit_terms=body_explicit,
        matched_title_topic_terms=title_topics,
        matched_body_topic_terms=body_topics,
        matched_title_context_terms=title_context,
        matched_body_context_terms=body_context,
        body_characters_considered=len(considered_body),
        body_truncated=len(normalized_body) > len(considered_body),
    )


class ScienceTechEditorialCohort(StrEnum):
    SCIENCE_TECHNOLOGY_EDUCATION_PRIORITY = "science_technology_education_priority"
    FRONTIER_SCIENCE_TECHNOLOGY = "frontier_science_technology"
    OUT_OF_SCOPE = "out_of_scope"


_SCIENCE_TALENT_PATHWAY_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "white_list_competition_pathway",
        re.compile(r"白名单赛(?:事)?|白名单竞赛|全国性竞赛活动名单|全国中小学生竞赛"),
    ),
    (
        "technology_specialty_student_pathway",
        re.compile(r"科技特长生|科技特长培养|科技特长发展"),
    ),
    ("strong_foundation_pathway", re.compile(r"强基计划|基础学科拔尖人才")),
    (
        "comprehensive_evaluation_pathway",
        re.compile(
            r"(?:教育|高校|招生|录取|升学).{0,8}综评|"
            r"综评.{0,8}(?:招生|录取|选拔|入学)|"
            r"综合评价(?:招生|录取|选拔|入学)"
        ),
    ),
    (
        "white_list_competition_pathway",
        _ascii_term(r"(?:official|national)[\s-]+(?:student[\s-]+)?competition[\s-]+list"),
    ),
    (
        "technology_specialty_student_pathway",
        _ascii_term(r"science[\s-]+and[\s-]+technology[\s-]+specialty[\s-]+students?"),
    ),
    (
        "strong_foundation_pathway",
        _ascii_term(r"strong[\s-]+foundation[\s-]+plan"),
    ),
    (
        "comprehensive_evaluation_pathway",
        _ascii_term(r"comprehensive[\s-]+evaluation[\s-]+admissions?"),
    ),
)

_PATHWAY_SUBSTANCE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "pathway_policy_or_rule",
        re.compile(
            r"政策|规则|办法|资格|名单|认定|调整|改革|实施|部署|通知|指南|"
            r"选拔|培养|招生政策|招生办法|录取机制|考核|试点|实践|成果|启动|发布"
        ),
    ),
    (
        "pathway_policy_or_rule",
        _ascii_term(
            r"policy|rules?|eligibility|official[\s-]+list|implementation|reform|"
            r"selection|admissions?[\s-]+policy|assessment|pilot|launched?"
        ),
    ),
)

_EDUCATION_EXCLUSION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "training_or_admissions_marketing",
        re.compile(
            r"培训机构|辅导班|冲刺班|课程报名|招生广告|招生简章|招生咨询|"
            r"扫码(?:报名|咨询)|添加微信|报名优惠|限时报名|志愿填报服务"
        ),
    ),
    (
        "guaranteed_admission_claim",
        re.compile(r"保录|保过|包过|内部名额|降分录取|百分百录取|确保录取"),
    ),
    (
        "score_line_aggregation",
        re.compile(r"分数线(?:汇总|大全|排名)|录取分数线(?:汇总|预测)|历年分数线"),
    ),
    (
        "deadline_only_reminder",
        re.compile(r"报名(?:截止|倒计时|最后一天)|最后机会|错过再等一年"),
    ),
    (
        "unverified_official_status",
        re.compile(r"网传|所谓白名单|号称.{0,8}白名单|宣称.{0,8}白名单"),
    ),
    (
        "education_funding_or_commercial_activity",
        re.compile(
            r"融资|募资|估值|股价|财报|营收|市场份额|市场规模|商业化|"
            r"付费用户|招商|加盟"
        ),
    ),
    (
        "education_ordinary_company_announcement",
        re.compile(r"签署协议|战略合作|品牌升级|渠道合作"),
    ),
    (
        "training_or_admissions_marketing",
        _ascii_term(r"tutoring|coaching|enrol+ment[\s-]+offer|admissions?[\s-]+consulting"),
    ),
    (
        "guaranteed_admission_claim",
        _ascii_term(r"guaranteed[\s-]+admission|guaranteed[\s-]+pass"),
    ),
    (
        "education_funding_or_commercial_activity",
        _ascii_term(
            r"funding|financing|valuation|revenue|market[\s-]+size|"
            r"commerciali[sz]ation|paid[\s-]+users?"
        ),
    ),
    (
        "education_ordinary_company_announcement",
        _ascii_term(r"strategic[\s-]+partnership|brand[\s-]+upgrade"),
    ),
)

_FRONTIER_TOPIC_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "artificial_intelligence",
        re.compile(
            r"人工智能|大模型|机器学习|深度学习|神经网络|生成式\s*ai|"
            r"(?<![a-z0-9])(?:ai|llms?)(?![a-z0-9])"
        ),
    ),
    ("robotics_embodied_intelligence", re.compile(r"机器人|具身智能|人形机器人")),
    ("aerospace_astronomy", re.compile(r"航天|航空|卫星|火箭|空间站|天文|行星|宇宙")),
    ("quantum_science", re.compile(r"量子|量子计算|量子通信")),
    (
        "physical_life_material_energy_science",
        re.compile(r"物理|化学|生物|生命科学|基因|蛋白质|新材料|超导|新能源|核聚变|储能"),
    ),
    (
        "artificial_intelligence",
        _ascii_term(
            r"artificial[\s-]+intelligence|machine[\s-]+learning|deep[\s-]+learning|"
            r"neural[\s-]+networks?|large[\s-]+language[\s-]+models?|llms?"
        ),
    ),
    (
        "robotics_embodied_intelligence",
        _ascii_term(r"robotics?|humanoid[\s-]+robots?|embodied[\s-]+(?:ai|intelligence)"),
    ),
    (
        "aerospace_astronomy",
        _ascii_term(r"aerospace|spacecraft|satellites?|astronomy|exoplanets?"),
    ),
    (
        "quantum_science",
        _ascii_term(r"quantum(?:[\s-]+(?:computing|communication|science|research))?"),
    ),
    (
        "physical_life_material_energy_science",
        _ascii_term(
            r"physics|chemistry|biology|genomics?|proteins?|materials?[\s-]+science|"
            r"superconductors?|fusion[\s-]+energy|energy[\s-]+storage"
        ),
    ),
)

_FRONTIER_PROGRESS_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "substantive_breakthrough",
        re.compile(r"重大突破|实现突破|突破性|攻克|里程碑|刷新.{0,8}(?:纪录|记录)"),
    ),
    (
        "first_achievement",
        re.compile(
            r"(?:首次|首个|首创|世界第一|全球首).{0,16}"
            r"(?:实现|完成|发现|观测|验证|研制|开发|发射|攻克|突破|证实|"
            r"达到|创下|刷新|展示)"
        ),
    ),
    (
        "research_discovery_or_result",
        re.compile(r"新发现|发现.{0,12}(?:机制|现象|物种|行星)|科研成果|研究成果|研究表明"),
    ),
    (
        "demonstrated_engineering_advance",
        re.compile(
            r"研制成功|成功研制|成功开发|成功发射|成功实现|成功验证|完成验证|"
            r"证实|观测到|性能提升|新方法|新机制|新算法|"
            r"(?:取得|实现).{0,6}技术进展|关键技术进展"
        ),
    ),
    (
        "substantive_breakthrough",
        _ascii_term(r"breakthrough|milestone|record[\s-]+setting|major[\s-]+advance"),
    ),
    (
        "first_achievement",
        _ascii_term(
            r"first(?:[\s-]+ever)?[\s-]+(?:demonstration|achievement|discovery|"
            r"successful|verified|validated|developed|observed)"
        ),
    ),
    (
        "research_discovery_or_result",
        _ascii_term(r"discover(?:y|ed|s)?|research[\s-]+(?:finds?|result)|study[\s-]+finds?"),
    ),
    (
        "demonstrated_engineering_advance",
        _ascii_term(
            r"successfully[\s-]+(?:developed|demonstrated|launched|validated)|"
            r"new[\s-]+(?:method|mechanism|algorithm)|performance[\s-]+gain"
        ),
    ),
)

_FRONTIER_EXCLUSION_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "funding_or_market_activity",
        re.compile(
            r"融资|募资|估值|股价|涨停|资本市场|财报|营收|市场份额|"
            r"算力(?:市场|规模|需求|供给|价格|租赁|中心|集群)"
        ),
    ),
    (
        "consumer_or_sales_promotion",
        re.compile(
            r"促销|预售|开售|销量|消费级|手机新品|ai\s*手机|人工智能手机|"
            r"智能手机|平板电脑|笔记本电脑|智能家电|可穿戴|购物节|"
            r"发布会|论坛举行|峰会开幕|展会亮相|免费开放|开放试用|订阅优惠"
        ),
    ),
    (
        "ordinary_company_announcement",
        re.compile(
            r"签署协议|战略合作|成立公司|品牌升级|招聘|渠道合作|"
            r"(?:公司|企业|品牌).{0,16}(?:发布|推出|上线|亮相).{0,16}"
            r"(?:产品|平台|应用|app|服务|功能|版本)"
        ),
    ),
    (
        "funding_or_market_activity",
        _ascii_term(
            r"funding|financing|valuation|share[\s-]+price|stock[\s-]+market|revenue|"
            r"compute[\s-]+(?:market|capacity|cluster|demand|supply|rental)|"
            r"gpu[\s-]+cluster|data[\s-]+cent(?:er|re)"
        ),
    ),
    (
        "consumer_or_sales_promotion",
        _ascii_term(
            r"preorder|on[\s-]+sale|consumer[\s-]+(?:device|app)|sales[\s-]+promotion|"
            r"smartphones?|mobile[\s-]+apps?|wearables?|laptops?|free[\s-]+trial"
        ),
    ),
    (
        "ordinary_company_announcement",
        _ascii_term(
            r"strategic[\s-]+partnership|brand[\s-]+upgrade|hiring|"
            r"(?:company|startup|brand).{0,24}(?:launch(?:es|ed)?|unveil(?:s|ed)?|"
            r"release(?:s|d)?).{0,24}(?:product|platform|app|service|feature|version)"
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class ScienceTechEditorialResult:
    is_candidate: bool
    cohort: ScienceTechEditorialCohort
    editorial_priority_score: float
    education_relevance_score: float
    frontier_significance_score: float
    reason_codes: tuple[str, ...]
    matched_title_education_terms: tuple[str, ...]
    matched_body_education_terms: tuple[str, ...]
    matched_title_topic_terms: tuple[str, ...]
    matched_body_topic_terms: tuple[str, ...]
    matched_title_progress_terms: tuple[str, ...]
    matched_body_progress_terms: tuple[str, ...]
    matched_title_exclusion_terms: tuple[str, ...]
    matched_body_exclusion_terms: tuple[str, ...]
    body_characters_considered: int
    body_truncated: bool
    rule_version: str = SCIENCE_TECH_EDITORIAL_RULE_VERSION


def evaluate_science_tech_editorial_relevance(
    title: str | None,
    body: str | None = None,
    *,
    body_limit: int = EDITORIAL_CONTENT_CHARACTER_LIMIT,
) -> ScienceTechEditorialResult:
    """Classify education priority and substantive frontier advances for v2 runs."""

    if body_limit < 1:
        raise ValueError("editorial relevance body limit must be positive")
    normalized_title = normalize_editorial_text(title)
    normalized_body = normalize_editorial_text(body)
    considered_body = normalized_body[:body_limit]

    legacy_education = evaluate_science_ai_education_relevance(
        normalized_title,
        considered_body,
        body_limit=body_limit,
    )
    title_explicit = _matches(normalized_title, _EXPLICIT_PATTERNS)
    body_explicit = _matches(considered_body, _EXPLICIT_PATTERNS)
    title_pathways = _matches(normalized_title, _SCIENCE_TALENT_PATHWAY_PATTERNS)
    body_pathways = _matches(considered_body, _SCIENCE_TALENT_PATHWAY_PATTERNS)
    title_substance = _matches(normalized_title, _PATHWAY_SUBSTANCE_PATTERNS)
    body_substance = _matches(considered_body, _PATHWAY_SUBSTANCE_PATTERNS)
    title_education_exclusions = _matches(normalized_title, _EDUCATION_EXCLUSION_PATTERNS)
    body_education_exclusions = _matches(considered_body, _EDUCATION_EXCLUSION_PATTERNS)
    pathway_reasons = tuple(dict.fromkeys((*title_pathways, *body_pathways)))
    pathway_has_substance = _has_nearby_pattern_pair(
        normalized_title,
        _SCIENCE_TALENT_PATHWAY_PATTERNS,
        _PATHWAY_SUBSTANCE_PATTERNS,
        max_gap=32,
    ) or _has_nearby_pattern_pair(
        considered_body,
        _SCIENCE_TALENT_PATHWAY_PATTERNS,
        _PATHWAY_SUBSTANCE_PATTERNS,
        max_gap=32,
    )
    education_excluded = bool(title_education_exclusions or body_education_exclusions)
    pathway_eligible = bool(pathway_reasons) and pathway_has_substance and not education_excluded

    education_terms = tuple(
        dict.fromkeys((*legacy_education.matched_title_terms, *title_pathways, *title_substance))
    )
    body_education_terms = tuple(
        dict.fromkeys((*legacy_education.matched_body_terms, *body_pathways, *body_substance))
    )
    legacy_eligible = legacy_education.is_eligible and not education_excluded
    if legacy_eligible or pathway_eligible:
        if title_explicit or body_explicit:
            education_score = 1.0
            primary_reason = "explicit_science_technology_education"
        elif pathway_eligible:
            education_score = 0.94
            primary_reason = "science_talent_pathway_with_substance"
        else:
            education_score = 0.88
            primary_reason = "science_technology_topic_with_education_context"
        reasons = tuple(dict.fromkeys((primary_reason, *pathway_reasons)))
        return ScienceTechEditorialResult(
            is_candidate=True,
            cohort=ScienceTechEditorialCohort.SCIENCE_TECHNOLOGY_EDUCATION_PRIORITY,
            editorial_priority_score=education_score,
            education_relevance_score=education_score,
            frontier_significance_score=0.0,
            reason_codes=reasons,
            matched_title_education_terms=education_terms,
            matched_body_education_terms=body_education_terms,
            matched_title_topic_terms=legacy_education.matched_title_topic_terms,
            matched_body_topic_terms=legacy_education.matched_body_topic_terms,
            matched_title_progress_terms=(),
            matched_body_progress_terms=(),
            matched_title_exclusion_terms=title_education_exclusions,
            matched_body_exclusion_terms=body_education_exclusions,
            body_characters_considered=len(considered_body),
            body_truncated=len(normalized_body) > len(considered_body),
        )

    title_frontier_topics = _matches(normalized_title, _FRONTIER_TOPIC_PATTERNS)
    body_frontier_topics = _matches(considered_body, _FRONTIER_TOPIC_PATTERNS)
    title_progress = _matches(normalized_title, _FRONTIER_PROGRESS_PATTERNS)
    body_progress = _matches(considered_body, _FRONTIER_PROGRESS_PATTERNS)
    title_frontier_exclusions = _matches(normalized_title, _FRONTIER_EXCLUSION_PATTERNS)
    body_frontier_exclusions = _matches(considered_body, _FRONTIER_EXCLUSION_PATTERNS)
    frontier_excluded = bool(
        title_education_exclusions
        or body_education_exclusions
        or title_frontier_exclusions
        or body_frontier_exclusions
    )
    has_frontier_topic = bool(title_frontier_topics or body_frontier_topics)
    has_frontier_progress = bool(title_progress or body_progress)
    if has_frontier_topic and has_frontier_progress and not frontier_excluded:
        frontier_score = min(
            0.82,
            round(
                0.68
                + 0.04 * len(set((*title_frontier_topics, *body_frontier_topics)))
                + 0.03 * len(set((*title_progress, *body_progress))),
                4,
            ),
        )
        return ScienceTechEditorialResult(
            is_candidate=True,
            cohort=ScienceTechEditorialCohort.FRONTIER_SCIENCE_TECHNOLOGY,
            editorial_priority_score=frontier_score,
            education_relevance_score=0.0,
            frontier_significance_score=frontier_score,
            reason_codes=("frontier_topic_with_substantive_progress",),
            matched_title_education_terms=education_terms,
            matched_body_education_terms=body_education_terms,
            matched_title_topic_terms=title_frontier_topics,
            matched_body_topic_terms=body_frontier_topics,
            matched_title_progress_terms=title_progress,
            matched_body_progress_terms=body_progress,
            matched_title_exclusion_terms=title_frontier_exclusions,
            matched_body_exclusion_terms=body_frontier_exclusions,
            body_characters_considered=len(considered_body),
            body_truncated=len(normalized_body) > len(considered_body),
        )

    exclusion_terms = tuple(
        dict.fromkeys(
            (
                *title_education_exclusions,
                *body_education_exclusions,
                *title_frontier_exclusions,
                *body_frontier_exclusions,
            )
        )
    )
    if not normalized_title and not considered_body:
        reasons = ("empty_text",)
    elif pathway_reasons and education_excluded:
        reasons = ("science_talent_pathway_excluded", *exclusion_terms)
    elif legacy_education.is_eligible and education_excluded:
        reasons = ("science_technology_education_excluded", *exclusion_terms)
    elif pathway_reasons and not pathway_has_substance:
        reasons = ("science_talent_pathway_missing_substance", *pathway_reasons)
    elif frontier_excluded:
        reasons = ("frontier_commercial_or_marketing_excluded", *exclusion_terms)
    elif not has_frontier_topic:
        reasons = ("missing_science_technology_topic",)
    else:
        reasons = ("missing_substantive_frontier_progress",)
    return ScienceTechEditorialResult(
        is_candidate=False,
        cohort=ScienceTechEditorialCohort.OUT_OF_SCOPE,
        editorial_priority_score=0.0,
        education_relevance_score=0.0,
        frontier_significance_score=0.0,
        reason_codes=tuple(dict.fromkeys(reasons)),
        matched_title_education_terms=education_terms,
        matched_body_education_terms=body_education_terms,
        matched_title_topic_terms=title_frontier_topics,
        matched_body_topic_terms=body_frontier_topics,
        matched_title_progress_terms=title_progress,
        matched_body_progress_terms=body_progress,
        matched_title_exclusion_terms=tuple(
            dict.fromkeys((*title_education_exclusions, *title_frontier_exclusions))
        ),
        matched_body_exclusion_terms=tuple(
            dict.fromkeys((*body_education_exclusions, *body_frontier_exclusions))
        ),
        body_characters_considered=len(considered_body),
        body_truncated=len(normalized_body) > len(considered_body),
    )


SCIENCE_LITERACY_INQUIRY = "science_literacy_inquiry"
SUBJECT_TRANSITION = "subject_transition_math_physics_chemistry_biology"
AI_LITERACY_PROJECT = "ai_literacy_project_learning"
AI_THEME_PRACTICE = "ai_theme_robotics_agent_safety_math_3d_hackathon"
COMPETITION_TALENT = "competition_innovation_talent_pathway"
STUDY_EXPERIENCE = "study_tour_camp_university_lab_industry"

_PRODUCT_DIRECTION_PATTERNS: tuple[tuple[str, tuple[re.Pattern[str], ...]], ...] = (
    (
        SCIENCE_LITERACY_INQUIRY,
        (
            re.compile(r"科学素养|科学探究|探究式|做中学|小学科学|科学启蒙"),
            _ascii_term(r"science[\s-]+literacy|science[\s-]+inquiry|inquiry[\s-]+learning"),
        ),
    ),
    (
        SUBJECT_TRANSITION,
        (
            re.compile(r"理科衔接|小初衔接|初高衔接|数学.{0,8}(?:物理|化学|生物)|物理.{0,8}化学"),
            _ascii_term(
                r"subject[\s-]+transition|math(?:ematics)?.{0,24}(?:physics|chemistry|biology)"
            ),
        ),
    ),
    (
        AI_LITERACY_PROJECT,
        (
            re.compile(
                r"人工智能素养|(?<![a-z0-9])ai\s*素养|"
                r"人工智能.{0,10}项目式|(?<![a-z0-9])ai.{0,10}项目式"
            ),
            _ascii_term(r"ai[\s-]+literacy|artificial[\s-]+intelligence.{0,24}project[\s-]+based"),
        ),
    ),
    (
        AI_THEME_PRACTICE,
        (
            re.compile(
                r"具身机器人|具身智能|智能体.{0,8}(?:开发|项目|课程)|"
                r"(?<![a-z0-9])ai\s*agent.{0,8}(?:工程|开发|项目|课程)|"
                r"(?<![a-z0-9])(?:rag|llms?)(?![a-z0-9])|"
                r"(?<![a-z0-9])ai\s*安全|"
                r"(?:人工智能|(?<![a-z0-9])ai)(?:\s*[x\u00d7]\s*|.{0,6})数学|"
                r"(?:人工智能|(?<![a-z0-9])ai|科技).{0,8}创业|"
                r"3d\s*打印|黑客松"
            ),
            _ascii_term(
                r"embodied[\s-]+robotics?|agentic[\s-]+ai|"
                r"ai[\s-]+agents?.{0,24}(?:engineering|development|projects?|courses?)|"
                r"rag|llms?|ai[\s-]+safety|"
                r"(?:ai|artificial[\s-]+intelligence).{0,16}math(?:ematics)?|"
                r"3d[\s-]+printing|hackathon|entrepreneurship"
            ),
        ),
    ),
    (
        COMPETITION_TALENT,
        (
            re.compile(r"科创竞赛|科技竞赛|机器人竞赛|创新项目|人才培养|人才发展"),
            _ascii_term(
                r"science[\s-]+competition|robotics?[\s-]+competition|innovation[\s-]+project|talent[\s-]+pathway"
            ),
        ),
    ),
    (
        STUDY_EXPERIENCE,
        (
            re.compile(
                r"研学|科学营|夏令营|大科学装置|高校.{0,8}(?:实验室|参访)|科技企业.{0,8}(?:参访|研学)"
            ),
            _ascii_term(
                r"study[\s-]+tour|science[\s-]+camp|university[\s-]+lab|research[\s-]+laboratory|science[\s-]+facility|industry[\s-]+visit"
            ),
        ),
    ),
)


@dataclass(frozen=True, slots=True)
class ProductMatrixFitResult:
    score: float
    direction_ids: tuple[str, ...]
    matched_title_direction_ids: tuple[str, ...]
    matched_body_direction_ids: tuple[str, ...]
    reason_codes: tuple[str, ...]
    body_characters_considered: int
    body_truncated: bool
    rule_version: str = PRODUCT_MATRIX_FIT_RULE_VERSION


def evaluate_product_matrix_fit(
    title: str | None,
    body: str | None = None,
    *,
    body_limit: int = EDITORIAL_CONTENT_CHARACTER_LIMIT,
) -> ProductMatrixFitResult:
    if body_limit < 1:
        raise ValueError("product matrix body limit must be positive")
    normalized_title = normalize_editorial_text(title)
    normalized_body = normalize_editorial_text(body)
    considered_body = normalized_body[:body_limit]

    title_directions = tuple(
        direction
        for direction, patterns in _PRODUCT_DIRECTION_PATTERNS
        if any(pattern.search(normalized_title) is not None for pattern in patterns)
    )
    body_directions = tuple(
        direction
        for direction, patterns in _PRODUCT_DIRECTION_PATTERNS
        if any(pattern.search(considered_body) is not None for pattern in patterns)
    )
    directions = tuple(dict.fromkeys((*title_directions, *body_directions)))
    reasons: tuple[str, ...]
    if not directions:
        score = 0.0
        reasons = ("no_product_matrix_direction",)
    else:
        # One direction carries the primary fit. Only distinct directions add breadth, so
        # repeating a keyword cannot inflate the score.
        score = min(1.0, round(0.62 + 0.095 * (len(directions) - 1), 4))
        if title_directions:
            score = min(1.0, round(score + 0.05, 4))
        reasons = ("matched_product_matrix_direction",)
    return ProductMatrixFitResult(
        score=score,
        direction_ids=directions,
        matched_title_direction_ids=title_directions,
        matched_body_direction_ids=body_directions,
        reason_codes=reasons,
        body_characters_considered=len(considered_body),
        body_truncated=len(normalized_body) > len(considered_body),
    )


def evaluate_product_matrix_fit_v2(
    title: str | None,
    body: str | None = None,
    *,
    body_limit: int = EDITORIAL_CONTENT_CHARACTER_LIMIT,
) -> ProductMatrixFitResult:
    """Retain product v1 directions while adding science-talent pathway reasons."""

    if body_limit < 1:
        raise ValueError("product matrix body limit must be positive")
    normalized_title = normalize_editorial_text(title)
    normalized_body = normalize_editorial_text(body)
    considered_body = normalized_body[:body_limit]
    v1 = evaluate_product_matrix_fit(
        normalized_title,
        considered_body,
        body_limit=body_limit,
    )
    title_pathways = _matches(normalized_title, _SCIENCE_TALENT_PATHWAY_PATTERNS)
    body_pathways = _matches(considered_body, _SCIENCE_TALENT_PATHWAY_PATTERNS)
    pathway_reasons = tuple(dict.fromkeys((*title_pathways, *body_pathways)))
    title_directions = tuple(
        dict.fromkeys(
            (
                *v1.matched_title_direction_ids,
                *((COMPETITION_TALENT,) if title_pathways else ()),
            )
        )
    )
    body_directions = tuple(
        dict.fromkeys(
            (
                *v1.matched_body_direction_ids,
                *((COMPETITION_TALENT,) if body_pathways else ()),
            )
        )
    )
    directions = tuple(dict.fromkeys((*title_directions, *body_directions)))
    reasons: tuple[str, ...]
    if not directions:
        score = 0.0
        reasons = ("no_product_matrix_direction",)
    else:
        score = min(1.0, round(0.62 + 0.095 * (len(directions) - 1), 4))
        if title_directions:
            score = min(1.0, round(score + 0.05, 4))
        reasons = tuple(dict.fromkeys(("matched_product_matrix_direction", *pathway_reasons)))
    return ProductMatrixFitResult(
        score=score,
        direction_ids=directions,
        matched_title_direction_ids=title_directions,
        matched_body_direction_ids=body_directions,
        reason_codes=reasons,
        body_characters_considered=len(considered_body),
        body_truncated=len(normalized_body) > len(considered_body),
        rule_version=PRODUCT_MATRIX_FIT_V2_RULE_VERSION,
    )
