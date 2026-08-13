from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

SCIENCE_AI_EDUCATION_RULE_VERSION = "science-ai-education-v1"
PRODUCT_MATRIX_FIT_RULE_VERSION = "product-matrix-fit-v1"
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
