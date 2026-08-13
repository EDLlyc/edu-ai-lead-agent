import pytest
from app.domain.editorial_relevance import (
    AI_LITERACY_PROJECT,
    AI_THEME_PRACTICE,
    COMPETITION_TALENT,
    EDITORIAL_CONTENT_CHARACTER_LIMIT,
    PRODUCT_MATRIX_FIT_RULE_VERSION,
    PRODUCT_MATRIX_FIT_V2_RULE_VERSION,
    SCIENCE_AI_EDUCATION_RULE_VERSION,
    SCIENCE_LITERACY_INQUIRY,
    SCIENCE_TECH_EDITORIAL_RULE_VERSION,
    STUDY_EXPERIENCE,
    SUBJECT_TRANSITION,
    ScienceTechEditorialCohort,
    evaluate_product_matrix_fit,
    evaluate_product_matrix_fit_v2,
    evaluate_science_ai_education_relevance,
    evaluate_science_tech_editorial_relevance,
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


@pytest.mark.parametrize(
    ("title", "reason"),
    [
        ("教育部发布全国中小学生白名单赛事调整名单", "white_list_competition_pathway"),
        ("多地完善科技特长生培养和认定规则", "technology_specialty_student_pathway"),
        ("强基计划选拔机制迎来改革", "strong_foundation_pathway"),
        ("高校综合评价招生政策明确考核办法", "comprehensive_evaluation_pathway"),
        ("Strong Foundation Plan eligibility rules are updated", "strong_foundation_pathway"),
    ],
)
def test_editorial_v2_accepts_governed_science_talent_pathways(
    title: str,
    reason: str,
) -> None:
    result = evaluate_science_tech_editorial_relevance(title)

    assert result.is_candidate is True
    assert result.cohort is ScienceTechEditorialCohort.SCIENCE_TECHNOLOGY_EDUCATION_PRIORITY
    assert result.education_relevance_score >= 0.88
    assert reason in result.reason_codes
    assert result.rule_version == SCIENCE_TECH_EDITORIAL_RULE_VERSION


@pytest.mark.parametrize(
    "title",
    [
        "强基计划冲刺班限时报名,保录名校",
        "科技特长生培训机构招生简章,扫码咨询",
        "综评历年分数线汇总大全",
        "网传某比赛成为白名单赛事",
        "白名单赛报名截止倒计时最后一天",
    ],
)
def test_editorial_v2_does_not_rescue_pathway_marketing_or_unverified_claims(
    title: str,
) -> None:
    result = evaluate_science_tech_editorial_relevance(title)

    assert result.is_candidate is False
    assert result.cohort is ScienceTechEditorialCohort.OUT_OF_SCOPE
    assert result.editorial_priority_score == 0
    assert result.reason_codes[0].endswith("excluded")


@pytest.mark.parametrize(
    "title",
    [
        "我国人形机器人完成首次复杂地形自主作业验证",
        "人工智能新算法刷新多项推理纪录",
        "科研团队发现新型超导材料机制",
        "Scientists Discover a New Exoplanet",
        "Quantum researchers demonstrate a major breakthrough",
    ],
)
def test_editorial_v2_accepts_substantive_frontier_advances(title: str) -> None:
    result = evaluate_science_tech_editorial_relevance(title)

    assert result.is_candidate is True
    assert result.cohort is ScienceTechEditorialCohort.FRONTIER_SCIENCE_TECHNOLOGY
    assert 0 < result.frontier_significance_score < 0.88
    assert result.reason_codes == ("frontier_topic_with_substantive_progress",)


@pytest.mark.parametrize(
    "title",
    [
        "人工智能企业完成新一轮融资",
        "机器人品牌发布消费级新品促销计划",
        "AI算力市场规模持续增长",
        "新一代大模型正式发布",
        "科技公司签署战略合作协议",
        "人工智能改变未来",
        "企业年度综评制度改革",
    ],
)
def test_editorial_v2_rejects_generic_frontier_business_or_missing_progress(title: str) -> None:
    result = evaluate_science_tech_editorial_relevance(title)

    assert result.is_candidate is False
    assert result.cohort is ScienceTechEditorialCohort.OUT_OF_SCOPE


@pytest.mark.parametrize(
    "title",
    [
        "新材料行业发展论坛举行",
        "某公司首次发布AI产品",
        "AI手机首次搭载新算法",
        "AI算力集群首次突破万卡规模",
        "人工智能首次免费开放试用",
        "机器人发布会首次亮相",
        "AI startup unveils its first consumer app",
        "First-ever AI smartphone launches this week",
    ],
)
def test_editorial_v2_rejects_keyword_only_product_compute_and_event_progress(
    title: str,
) -> None:
    result = evaluate_science_tech_editorial_relevance(title)

    assert result.is_candidate is False
    assert result.cohort is ScienceTechEditorialCohort.OUT_OF_SCOPE


@pytest.mark.parametrize(
    "title",
    [
        "科技教育公司完成新一轮融资",
        "人工智能教育市场规模持续增长",
        "Science education startup completes funding round",
    ],
)
def test_editorial_v2_rejects_financing_even_with_an_explicit_education_phrase(
    title: str,
) -> None:
    result = evaluate_science_tech_editorial_relevance(title)

    assert result.is_candidate is False
    assert result.reason_codes[0] == "science_technology_education_excluded"


def test_editorial_v2_requires_pathway_substance_near_the_pathway_signal() -> None:
    result = evaluate_science_tech_editorial_relevance(
        "强基计划今日热点",
        "某消费品牌发布普通产品版本,市场活动同步启动。",
    )

    assert result.is_candidate is False
    assert result.reason_codes[0] == "science_talent_pathway_missing_substance"


def test_editorial_v2_gives_education_precedence_over_frontier() -> None:
    result = evaluate_science_tech_editorial_relevance("学生在人工智能课程中验证新算法并实现突破")

    assert result.cohort is ScienceTechEditorialCohort.SCIENCE_TECHNOLOGY_EDUCATION_PRIORITY
    assert result.education_relevance_score > result.frontier_significance_score


def test_editorial_v2_is_deterministic_and_enforces_body_character_boundary() -> None:
    body = "普通内容" * EDITORIAL_CONTENT_CHARACTER_LIMIT + "人工智能新算法取得重大突破"

    first = evaluate_science_tech_editorial_relevance("新闻", body)
    second = evaluate_science_tech_editorial_relevance("新闻", body)

    assert first == second
    assert first.is_candidate is False
    assert first.body_characters_considered == EDITORIAL_CONTENT_CHARACTER_LIMIT
    assert first.body_truncated is True


@pytest.mark.parametrize(
    ("title", "reason"),
    [
        ("全国中小学生白名单赛事名单发布", "white_list_competition_pathway"),
        ("科技特长生培养规则调整", "technology_specialty_student_pathway"),
        ("强基计划选拔机制改革", "strong_foundation_pathway"),
        ("综合评价招生政策调整", "comprehensive_evaluation_pathway"),
    ],
)
def test_product_matrix_v2_adds_stable_pathway_reasons(title: str, reason: str) -> None:
    result = evaluate_product_matrix_fit_v2(title)

    assert result.rule_version == PRODUCT_MATRIX_FIT_V2_RULE_VERSION
    assert result.direction_ids == (COMPETITION_TALENT,)
    assert reason in result.reason_codes


def test_product_matrix_v2_keeps_v1_caps_and_does_not_inflate_repeated_pathways() -> None:
    once = evaluate_product_matrix_fit_v2("强基计划选拔机制")
    repeated = evaluate_product_matrix_fit_v2("强基计划 " * 100 + "选拔机制")
    v1 = evaluate_product_matrix_fit("人工智能素养项目式课程")
    v2 = evaluate_product_matrix_fit_v2("人工智能素养项目式课程")

    assert repeated.score == once.score
    assert repeated.direction_ids == once.direction_ids
    assert v2.score == v1.score
    assert v2.direction_ids == v1.direction_ids
