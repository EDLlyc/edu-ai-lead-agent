# ruff: noqa: RUF001
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest
from app.application.services.topic_selection import build_topic_scoring_config
from app.core.config import Settings
from app.domain.content_slots import ContentSlot, SlotRankingPolicy, select_slot_topics
from app.domain.editorial_relevance import ScienceTechEditorialCohort
from app.domain.education_policy_signal import (
    EDUCATION_POLICY_SIGNAL_RULE_VERSION,
    EducationPolicyLevel,
    evaluate_education_policy_signal,
    is_education_policy_title,
)
from app.domain.topic_selection import (
    EDUCATION_POLICY_TOPIC_SCORING_VERSION,
    GOV_CN_YAOWEN_PRIORITY_POLICY,
    QUALIFIED_AUTHORITATIVE_TOPIC_SCORING_VERSION,
    TopicCandidate,
    TopicScoringConfig,
    score_topic_candidate,
    select_daily_topic,
)

NOW = datetime(2026, 9, 28, 1, 0, tzinfo=UTC)

HIGHER_EDUCATION_REFORM = (
    "中共中央办公厅 国务院办公厅印发《关于分类推进高校改革的意见》",
    "近日，中共中央办公厅、国务院办公厅印发《关于分类推进高校改革的意见》，"
    "对分类推进高校改革作出系统部署。分类不是分层次，而是分赛道。",
)
FIVE_YEAR_PRIORITIES = (
    "未来五年 教育将向六个方面重点发力",
    "国务院新闻办公室举行“开局起步‘十五五’”系列主题新闻发布会。"
    "教育部将重点做好六方面工作：一是全面落实立德树人根本任务。二是办强办优基础教育。",
)
PROVINCIAL_EXAM_REFORM = (
    "浙江省教育厅印发《初中学业水平考试改革实施方案》",
    "浙江省教育厅近日印发方案，自2027年起调整中考科目设置。",
)

NATIONAL_CASES = (
    HIGHER_EDUCATION_REFORM,
    ("高校分类改革正式启动", HIGHER_EDUCATION_REFORM[1]),
    FIVE_YEAR_PRIORITIES,
    (
        "教育部：推动高等教育提质扩容，深化科教产教协同育人",
        "教育部相关负责人介绍，“十五五”时期将推动高等教育提质扩容，分类推进高校改革。",
    ),
)
PROVINCIAL_CASES = (
    PROVINCIAL_EXAM_REFORM,
    ("北京市教委发布新一轮中考改革方案", "北京市教委发布方案，体育中考分值调整。"),
    (
        "广东省人民政府办公厅关于推进义务教育优质均衡发展的意见",
        "广东省政府办公厅印发意见，推进义务教育优质均衡。",
    ),
)
NEGATIVE_CASES = (
    (
        "我国科学家实现量子计算新突破",
        "中国科学技术大学团队实现量子计算突破。教育部表示将推进高校科研成果转化。",
        "education_policy_not_headline_topic",
    ),
    (
        "某培训机构推出中考冲刺班",
        "培训机构推出中考冲刺班，限时报名优惠。",
        "education_policy_marketing_excluded",
    ),
    (
        "北京大学举行2026级本科生开学典礼",
        "北京大学举行开学典礼，教育部有关负责人出席。",
        "education_policy_campus_event_excluded",
    ),
    ("教育部任免通知", "教育部发布任免通知。", "education_policy_personnel_excluded"),
    (
        "2026年全国硕士研究生招生考试报名10月启动",
        "教育部公布2026年考研报名安排。",
        "education_policy_exam_logistics_excluded",
    ),
    ("2026高考录取分数线汇总", "各省录取分数线汇总。", "education_policy_score_line_excluded"),
    (
        "市教育部门开展校园安全检查",
        "市教育部门部署秋季校园安全检查。",
        "education_policy_not_headline_topic",
    ),
)


@pytest.mark.parametrize(("title", "summary"), NATIONAL_CASES)
def test_national_education_policy_is_recognised(title: str, summary: str) -> None:
    result = evaluate_education_policy_signal(title, summary)

    assert result.is_signal
    assert result.level is EducationPolicyLevel.NATIONAL
    assert result.reason_code == "education_policy_signal_national"
    assert result.rule_version == EDUCATION_POLICY_SIGNAL_RULE_VERSION
    assert is_education_policy_title(title)


@pytest.mark.parametrize(("title", "summary"), PROVINCIAL_CASES)
def test_provincial_education_policy_is_recognised(title: str, summary: str) -> None:
    result = evaluate_education_policy_signal(title, summary)

    assert result.is_signal
    assert result.level is EducationPolicyLevel.PROVINCIAL
    assert is_education_policy_title(title)


@pytest.mark.parametrize(("title", "summary", "reason"), NEGATIVE_CASES)
def test_non_policy_education_news_is_not_a_signal(title: str, summary: str, reason: str) -> None:
    result = evaluate_education_policy_signal(title, summary)

    assert not result.is_signal
    assert result.level is None
    assert result.reason_code == reason
    assert not is_education_policy_title(title)


def test_input_is_bounded_and_empty_text_is_not_a_signal() -> None:
    assert evaluate_education_policy_signal(None, None).reason_code == (
        "education_policy_empty_text"
    )
    huge = "教育部印发高校改革意见。" + "无关内容" * 10_000
    assert evaluate_education_policy_signal(huge, huge).is_signal


def _candidate(
    suffix: int,
    title_summary: tuple[str, str] = ("候选新闻", "治理摘要"),
    *,
    total_features: float = 0.4,
    cohort: ScienceTechEditorialCohort = ScienceTechEditorialCohort.OUT_OF_SCOPE,
    priority_policy: str | None = None,
    unverified: bool = False,
) -> TopicCandidate:
    return TopicCandidate(
        event_id=UUID(f"00000000-0000-4000-8000-{suffix:012d}"),
        event_version_id=UUID(f"10000000-0000-4000-8000-{suffix:012d}"),
        event_time=NOW,
        source_trust=total_features,
        source_diversity=1,
        ai_relevance=total_features,
        parent_relevance=total_features,
        communication_potential=total_features,
        editorial_priority=total_features,
        science_tech_editorial_cohort=cohort,
        science_tech_education_relevance=total_features,
        frontier_significance=total_features,
        product_matrix_fit_v2=total_features,
        topic_priority_policy=priority_policy,
        priority_title=title_summary[0],
        priority_summary=title_summary[1],
        unverified=unverified,
    )


def _config(version: str = EDUCATION_POLICY_TOPIC_SCORING_VERSION) -> TopicScoringConfig:
    return build_topic_scoring_config(Settings(_env_file=None, content_scoring_version=version))


def test_default_config_is_v13_built_on_production_v11_identities() -> None:
    config = _config()
    v11 = _config(QUALIFIED_AUTHORITATIVE_TOPIC_SCORING_VERSION)

    assert build_topic_scoring_config(Settings(_env_file=None)).version == (
        EDUCATION_POLICY_TOPIC_SCORING_VERSION
    )
    assert config.has_education_policy_signal
    assert config.has_qualified_authoritative_priority
    assert config.has_broad_hard_tech_pool and config.has_authenticated_ministry_priority
    assert not v11.has_education_policy_signal
    metadata = config.as_metadata()
    assert metadata["education_policy_signal_rule_version"] == EDUCATION_POLICY_SIGNAL_RULE_VERSION
    assert TopicScoringConfig.from_metadata(metadata).as_metadata() == metadata
    before, after = v11.as_metadata(), dict(metadata)
    after.pop("education_policy_signal_rule_version")
    for key in ("version",):
        before.pop(key)
        after.pop(key)
    assert before == after
    assert "education_policy_signal_rule_version" not in v11.as_metadata()


def test_unsupported_education_policy_identity_is_rejected() -> None:
    with pytest.raises(ValueError, match="education policy signal"):
        TopicScoringConfig(
            version=QUALIFIED_AUTHORITATIVE_TOPIC_SCORING_VERSION,
            education_policy_signal_rule_version=EDUCATION_POLICY_SIGNAL_RULE_VERSION,
        )


def test_v13_admits_out_of_scope_education_policy_with_highest_priority() -> None:
    score = score_topic_candidate(
        _candidate(1, HIGHER_EDUCATION_REFORM), as_of=NOW, config=_config()
    )

    assert score.eligible
    assert not score.passes_threshold
    assert score.priority_applied
    assert score.priority_reason == "education_policy_signal_national"
    assert score.threshold_bypass_applied
    assert score.threshold_bypass_reason == "education_policy_signal"
    assert score.education_policy_level is EducationPolicyLevel.NATIONAL
    metadata = score.as_metadata()
    assert metadata["education_policy_signal_rule_version"] == EDUCATION_POLICY_SIGNAL_RULE_VERSION
    assert metadata["education_policy_level"] == "national"


def test_hard_veto_always_beats_education_policy() -> None:
    score = score_topic_candidate(
        _candidate(1, HIGHER_EDUCATION_REFORM, unverified=True), as_of=NOW, config=_config()
    )

    assert not score.eligible
    assert not score.priority_applied
    assert score.education_policy_level is None
    assert score.education_policy_reason == "education_policy_signal_national"


def test_v11_behaviour_and_explanation_are_unchanged() -> None:
    score = score_topic_candidate(
        _candidate(1, HIGHER_EDUCATION_REFORM),
        as_of=NOW,
        config=_config(QUALIFIED_AUTHORITATIVE_TOPIC_SCORING_VERSION),
    )

    assert not score.eligible
    assert not score.priority_applied
    assert not any(key.startswith("education_policy_") for key in score.as_metadata())


def test_daily_order_is_national_then_provincial_then_other_priority_then_ordinary() -> None:
    national = _candidate(1, FIVE_YEAR_PRIORITIES)
    provincial = _candidate(2, PROVINCIAL_EXAM_REFORM)
    # A qualified China Government yaowen science story is priority, but not education policy.
    yaowen = _candidate(
        3,
        ("我国成功发射新一代通信卫星", "运载火箭成功发射新一代通信卫星。"),
        total_features=1.0,
        cohort=ScienceTechEditorialCohort.FRONTIER_SCIENCE_TECHNOLOGY,
        priority_policy=GOV_CN_YAOWEN_PRIORITY_POLICY,
    )
    ordinary = _candidate(
        4,
        ("人形机器人完成新测试", "机器人团队完成测试。"),
        total_features=1.0,
        cohort=ScienceTechEditorialCohort.FRONTIER_SCIENCE_TECHNOLOGY,
    )

    decision = select_daily_topic(
        (ordinary, yaowen, provincial, national), as_of=NOW, config=_config()
    )

    assert [score.event_id for score in decision.scores] == [
        national.event_id,
        provincial.event_id,
        yaowen.event_id,
        ordinary.event_id,
    ]
    assert decision.selected_event_id == national.event_id


def test_education_policy_can_fill_every_slot_ordinal() -> None:
    policies = (
        _candidate(1, HIGHER_EDUCATION_REFORM),
        _candidate(2, FIVE_YEAR_PRIORITIES),
        _candidate(3, PROVINCIAL_EXAM_REFORM),
    )
    frontier = _candidate(
        4,
        ("人形机器人完成新测试", "机器人团队完成测试。"),
        total_features=1.0,
        cohort=ScienceTechEditorialCohort.FRONTIER_SCIENCE_TECHNOLOGY,
    )

    decision = select_slot_topics(
        (frontier, *policies),
        as_of=NOW,
        config=_config(),
        slot=ContentSlot.MORNING,
        policy=SlotRankingPolicy(),
        max_items=3,
    )

    assert set(decision.selected_event_ids) == {candidate.event_id for candidate in policies}
    assert decision.selected_event_ids[-1] == policies[2].event_id
    by_event = {score.base.event_id: score for score in decision.scores}
    assert by_event[policies[0].event_id].final_ordering_key.startswith("-2:")
    assert by_event[policies[2].event_id].final_ordering_key.startswith("-1:")
    assert by_event[frontier.event_id].final_ordering_key.startswith("1:")
    assert "education_policy_signal" in by_event[policies[0].event_id].affinity_reasons


def test_same_day_exclusion_still_applies_to_education_policy() -> None:
    policy = _candidate(1, HIGHER_EDUCATION_REFORM)

    decision = select_slot_topics(
        (policy,),
        as_of=NOW,
        config=_config(),
        slot=ContentSlot.NOON,
        policy=SlotRankingPolicy(),
        max_items=3,
        same_day_selected_event_ids=frozenset({policy.event_id}),
    )

    assert decision.selected_event_ids == ()
    assert replace(decision.scores[0]).final_ordering_key.startswith("2:")
