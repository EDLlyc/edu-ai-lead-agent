import pytest
from app.domain.science_policy_priority import evaluate_science_policy_priority


@pytest.mark.parametrize(
    ("title", "summary"),
    (
        ("教育部印发中小学人工智能教育行动方案", "推动学校人工智能课程实施。"),
        ("关于推进科学教育的通知", "部署中小学科学教育实验课程。"),
        ("机器人教育实施指南发布", "面向学校机器人课程教学。"),
    ),
)
def test_science_policy_priority_accepts_direct_education_policy_items(
    title: str,
    summary: str,
) -> None:
    result = evaluate_science_policy_priority(title, summary)

    assert result.is_eligible is True
    assert result.reason_code == "science_policy"


@pytest.mark.parametrize(
    ("title", "summary", "reason_code"),
    (
        ("教育部发布中小学科学教育教材通知", "教材编写工作安排。", "science_policy_excluded_item"),
        ("教育部召开人工智能教育研讨会", "会议交流课程经验。", "science_policy_excluded_item"),
        ("教育部发布教育督导通知", "部署年度教育督导工作。", "science_policy_topic_missing"),
        ("中小学人工智能教育课程建设", "学校开展人工智能课程。", "science_policy_action_missing"),
    ),
)
def test_science_policy_priority_rejects_non_policy_or_non_science_education_items(
    title: str,
    summary: str,
    reason_code: str,
) -> None:
    result = evaluate_science_policy_priority(title, summary)

    assert result.is_eligible is False
    assert result.reason_code == reason_code
