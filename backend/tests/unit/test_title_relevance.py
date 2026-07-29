import pytest
from app.domain.title_relevance import (
    TITLE_RELEVANCE_RULE_VERSION,
    evaluate_title_relevance,
    normalize_title,
)


@pytest.mark.parametrize(
    "title",
    [
        "人工智能赋能公共教育服务",
        "科研团队发布多模态学习研究进展",
        "具身智能机器人进入实训课堂",
        "自动驾驶与无人机协同系统发布",
        "脑机接口技术取得新进展",
        "New AGENTIC AI system supports teachers",
        "Large-Language Models for Education",
        "Language Models Support Science Education",
        "智能驾驶进入道路测试新阶段",
        "\uff2e\uff30\uff35 与 \uff21\uff29 芯片协同创新",
        "DeepSeek发布新一代推理模型",
        "ChatGPT launches education mode",
        "Brain\u2013computer interface study advances",
        "Intelligent systems support schools",
        "AI agents support classroom research",
        "深度学习模型提升图像识别效果",
        "多智能体系统协同完成复杂任务",
    ],
)
def test_ai_centered_titles_are_relevant(title: str) -> None:
    result = evaluate_title_relevance(title)

    assert result.is_relevant is True
    assert result.matched_terms
    assert result.rule_version == TITLE_RELEVANCE_RULE_VERSION


def test_normalization_is_unicode_case_and_whitespace_stable() -> None:
    assert normalize_title("  \uff21\uff29\n  Agent  ") == "ai agent"
    assert evaluate_title_relevance("\uff21\uff29 治理通知").matched_terms == (
        "ai",
        "治理",
        "通知",
    )


@pytest.mark.parametrize(
    "title",
    [
        "教育数字化政策发布",
        "文化产业发展规划印发",
        "金融支持实体经济若干措施",
        "城市生活垃圾治理标准发布",
    ],
)
def test_general_policy_words_do_not_accept_an_unrelated_title(title: str) -> None:
    assert evaluate_title_relevance(title).is_relevant is False


@pytest.mark.parametrize(
    "title",
    [
        "量子计算研究取得新突破",
        "商业航天产业加速发展",
        "生物技术助力新药研发",
        "新能源电池实现规模化生产",
    ],
)
def test_other_frontier_technology_is_not_relevant_by_itself(title: str) -> None:
    assert evaluate_title_relevance(title).is_relevant is False


@pytest.mark.parametrize(
    "title",
    [
        "人工智能助力量子计算研究",
        "机器人参与商业航天在轨实验",
        "机器学习推动生物技术研发",
        "AI 算法优化新能源电池管理",
    ],
)
def test_other_frontier_technology_is_relevant_when_explicitly_connected_to_ai(
    title: str,
) -> None:
    assert evaluate_title_relevance(title).is_relevant is True


@pytest.mark.parametrize("title", [None, "", "  \n  "])
def test_missing_titles_are_rejected(title: str | None) -> None:
    result = evaluate_title_relevance(title)

    assert result.is_relevant is False
    assert result.matched_terms == ()


def test_ascii_boundaries_prevent_ai_false_positives() -> None:
    assert evaluate_title_relevance("Paid education services expand").is_relevant is False
    assert evaluate_title_relevance("Daily education policy briefing").is_relevant is False
    assert evaluate_title_relevance("AI policy for education").matched_terms == ("ai", "policy")


@pytest.mark.parametrize(
    "title",
    [
        "Travel agents prepare summer offers",
        "Chemical agent safety standard published",
        "Business Confidence Index (BCI) rises",
        "UAS university admissions update",
        "学校推进学生深度学习实践",
        "智能体育设施服务校园运动",
        "智能体检设备进入社区",
    ],
)
def test_ambiguous_terms_do_not_create_ai_false_positives(title: str) -> None:
    assert evaluate_title_relevance(title).is_relevant is False
