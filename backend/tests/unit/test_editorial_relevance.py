import pytest
from app.domain.editorial_relevance import (
    AI_LITERACY_PROJECT,
    AI_THEME_PRACTICE,
    COMPETITION_TALENT,
    EDITORIAL_CONTENT_CHARACTER_LIMIT,
    PRODUCT_MATRIX_FIT_RULE_VERSION,
    SCIENCE_AI_EDUCATION_RULE_VERSION,
    SCIENCE_LITERACY_INQUIRY,
    STUDY_EXPERIENCE,
    SUBJECT_TRANSITION,
    evaluate_product_matrix_fit,
    evaluate_science_ai_education_relevance,
)


@pytest.mark.parametrize(
    ("title", "body"),
    [
        ("全国中小学科学教育工作推进会召开", None),
        ("学校开设人工智能课程, 提升师生AI素养", None),
        ("青少年机器人竞赛启动创新项目", None),
        ("教师带领学生开展化学探究实验", None),
        ("How Schools Are Building AI Literacy in the Classroom", None),
        ("Students Explore Physics Through Inquiry-Based Projects", None),
        ("Summer STEM Education Camp Opens for Teenagers", None),
        ("一项新计划发布", "该计划支持中学生在课堂开展机器人工程项目式学习。"),
    ],
)
def test_science_ai_education_policy_accepts_bilingual_boundary_examples(
    title: str, body: str | None
) -> None:
    result = evaluate_science_ai_education_relevance(title, body)

    assert result.is_eligible is True
    assert 0 < result.score <= 1
    assert result.rule_version == SCIENCE_AI_EDUCATION_RULE_VERSION
    assert result.reason_codes in {
        ("explicit_science_ai_education_phrase",),
        ("science_ai_topic_with_education_context",),
    }


@pytest.mark.parametrize(
    "title",
    [
        "新一代大模型正式发布",
        "AI芯片企业完成新一轮融资",
        "手机厂商推出消费级机器人",
        "Scientists Discover a New Exoplanet",
        "University Scientists Discover a New Exoplanet",
        "学校举办秋季运动会",
        "教育数字化服务平台完成升级",
        "Agent Raises New Funding for Enterprise Software",
        "Deep Learning Model Improves Chip Design",
        "Thai 教育项目启动",
        "A chair education exhibition opens",
    ],
)
def test_science_ai_education_policy_rejects_generic_ai_science_and_education(
    title: str,
) -> None:
    result = evaluate_science_ai_education_relevance(title)

    assert result.is_eligible is False
    assert result.score == 0
    assert result.reason_codes in {
        ("missing_science_ai_topic",),
        ("missing_education_context",),
    }


def test_science_ai_education_policy_is_deterministic_and_bounds_body() -> None:
    body = "普通内容" * EDITORIAL_CONTENT_CHARACTER_LIMIT + "学生人工智能课程"

    first = evaluate_science_ai_education_relevance("通知", body)
    second = evaluate_science_ai_education_relevance("通知", body)

    assert first == second
    assert first.is_eligible is False
    assert first.body_characters_considered == EDITORIAL_CONTENT_CHARACTER_LIMIT
    assert first.body_truncated is True


@pytest.mark.parametrize(
    ("text", "direction"),
    [
        ("小学科学素养与探究式学习课程", SCIENCE_LITERACY_INQUIRY),
        ("数学、物理、化学和生物的理科衔接", SUBJECT_TRANSITION),
        ("面向学生的人工智能素养项目式课程", AI_LITERACY_PROJECT),
        ("具身机器人、RAG和AI安全黑客松", AI_THEME_PRACTICE),
        ("青少年科创竞赛与创新人才培养", COMPETITION_TALENT),
        ("走进高校实验室和大科学装置开展研学", STUDY_EXPERIENCE),
    ],
)
def test_product_matrix_fit_returns_stable_direction_ids(text: str, direction: str) -> None:
    result = evaluate_product_matrix_fit(text)

    assert direction in result.direction_ids
    assert 0 < result.score <= 1
    assert result.rule_version == PRODUCT_MATRIX_FIT_RULE_VERSION


@pytest.mark.parametrize(
    "text",
    [
        "AI Agent工程开发课程",
        "AI\u00d7数学项目式学习",
        "青少年人工智能创业实践",
        "Students learn AI agent engineering through projects",
        "An AI and mathematics learning program",
        "Youth technology entrepreneurship program",
    ],
)
def test_ai_theme_product_direction_covers_all_named_subdirections(text: str) -> None:
    result = evaluate_product_matrix_fit(text)

    assert AI_THEME_PRACTICE in result.direction_ids


def test_product_fit_is_capped_by_distinct_directions_not_keyword_repetition() -> None:
    once = evaluate_product_matrix_fit("人工智能素养项目式课程")
    repeated = evaluate_product_matrix_fit("人工智能素养 " * 100 + "项目式课程")
    broad = evaluate_product_matrix_fit("人工智能素养项目式课程与具身机器人黑客松")

    assert repeated.score == once.score
    assert repeated.direction_ids == once.direction_ids
    assert once.score < broad.score <= 1


def test_zero_product_fit_does_not_change_editorial_eligibility() -> None:
    title = "教育部门发布学校科学教育质量监测指南"

    relevance = evaluate_science_ai_education_relevance(title)
    product = evaluate_product_matrix_fit(title)

    assert relevance.is_eligible is True
    assert product.score == 0
    assert product.direction_ids == ()


def test_ascii_ai_boundaries_reject_embedded_words_but_accept_named_ai_tools() -> None:
    assert evaluate_product_matrix_fit("Thai 素养课程").score == 0
    assert evaluate_product_matrix_fit("Prague science education conference").score == 0
    assert evaluate_science_ai_education_relevance("OpenAI launches tools for teachers").is_eligible
