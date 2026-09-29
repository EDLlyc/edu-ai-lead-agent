# ruff: noqa: RUF001
from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from app.application.services.topic_selection import build_topic_scoring_config
from app.core.config import Settings
from app.domain.content_slots import (
    SAME_TOPIC_DEDUP_SLOT_RANKING_VERSION,
    SAME_TOPIC_EXCLUSION_REASON,
    STRICT_HEADLINE_SLOT_RANKING_VERSION,
    ContentSlot,
    SlotRankingPolicy,
    TopicFingerprint,
    is_same_topic,
    select_slot_topics,
)
from app.domain.editorial_relevance import ScienceTechEditorialCohort
from app.domain.topic_selection import TopicCandidate

NOW = datetime(2026, 9, 28, 10, 0, tzinfo=UTC)


def _vector(cosine_to_base: float) -> tuple[float, ...]:
    """Unit vector with the requested cosine to (1, 0, 0...)."""
    return (cosine_to_base, math.sqrt(1 - cosine_to_base**2), 0.0)


BASE = (1.0, 0.0, 0.0)


def _fp(event: int, title: str, vector: tuple[float, ...] | None = None) -> TopicFingerprint:
    return TopicFingerprint(event_id=UUID(int=event), title=title, embedding=vector)


@pytest.mark.parametrize(
    ("left", "right", "same"),
    (
        # 2026-09-28 evening: 同一项高校分类改革 (cos 0.678 in production embeddings).
        (
            _fp(1, "中共中央办公厅 国务院办公厅印发《关于分类推进高校改革的意见》", BASE),
            _fp(2, "教育部：建立分类评价机制 推进各类高校特色发展", _vector(0.678)),
            True,
        ),
        # 2026-09-28 noon: both about 世界技能大赛 (cos only 0.596, caught by the headline).
        (
            _fp(3, "世界技能大赛标准引领职教课堂 技能人才培养提质进行时", BASE),
            _fp(4, "用技能为青春加冕——第48届世界技能大赛中国代表团创历史最好成绩", _vector(0.596)),
            True,
        ),
        # Shared column prefix is not a topic.
        (
            _fp(5, "【“十五五”开好局起好步】锚定蓝图 加快建设教育强国"),
            _fp(6, "【“十五五”开好局起好步】融合升级 新型工业化提速"),
            False,
        ),
        # Two different CAS chemistry papers (cos 0.647) stay distinct.
        (
            _fp(7, "研究揭示溶剂占据调控分子筛微孔催化扩散机制", BASE),
            _fp(8, "研究揭示氧化锰表面羟基和氧空位增强一氧化碳吸附协同机制", _vector(0.647)),
            False,
        ),
    ),
)
def test_same_topic_rule_on_real_headlines(
    left: TopicFingerprint, right: TopicFingerprint, same: bool
) -> None:
    assert is_same_topic(left, right) is same
    assert is_same_topic(right, left) is same


def _candidate(event: int, title: str, total: float) -> TopicCandidate:
    return TopicCandidate(
        event_id=UUID(int=event),
        event_version_id=UUID(int=1000 + event),
        event_time=NOW - timedelta(hours=event),
        source_trust=total,
        source_diversity=2,
        ai_relevance=0.0,
        parent_relevance=0.0,
        communication_potential=total,
        editorial_priority=total,
        science_tech_editorial_cohort=ScienceTechEditorialCohort.FRONTIER_SCIENCE_TECHNOLOGY,
        frontier_significance=total,
        product_matrix_fit_v2=total,
        priority_title=title,
        priority_summary=title,
    )


def _select(policy: SlotRankingPolicy, **kwargs: object):  # type: ignore[no-untyped-def]
    candidates = (
        _candidate(1, "世界技能大赛中国代表团创历史最好成绩", 0.9),
        _candidate(2, "世界技能大赛标准引领职教课堂", 0.8),
        _candidate(3, "望宇登月服研制已攻克数十项关键技术", 0.7),
        _candidate(4, "全球最大打桩船启航赴巴西", 0.6),
    )
    return select_slot_topics(
        candidates,
        as_of=NOW,
        config=build_topic_scoring_config(Settings(_env_file=None)),
        slot=ContentSlot.NOON,
        policy=policy,
        max_items=3,
        **kwargs,  # type: ignore[arg-type]
    )


def test_v2_keeps_one_story_per_topic_and_fills_with_the_next_topic() -> None:
    decision = _select(SlotRankingPolicy(version=SAME_TOPIC_DEDUP_SLOT_RANKING_VERSION))

    assert decision.selected_event_ids == (UUID(int=1), UUID(int=3), UUID(int=4))
    excluded = {score.base.event_id: score for score in decision.scores}[UUID(int=2)]
    assert excluded.same_day_excluded
    assert excluded.same_day_exclusion_reason == SAME_TOPIC_EXCLUSION_REASON


def test_v2_excludes_a_topic_already_pushed_earlier_the_same_day() -> None:
    earlier = (_fp(99, "望宇登月服研制取得新突破", None),)
    decision = _select(
        SlotRankingPolicy(version=SAME_TOPIC_DEDUP_SLOT_RANKING_VERSION),
        same_day_selected_topics=earlier,
    )

    assert UUID(int=3) not in decision.selected_event_ids
    assert decision.selected_event_ids == (UUID(int=1), UUID(int=4))


def test_v1_is_unchanged_and_ignores_topics() -> None:
    decision = _select(SlotRankingPolicy())

    assert decision.selected_event_ids == (UUID(int=1), UUID(int=2), UUID(int=3))
    assert SlotRankingPolicy().as_metadata() == {
        "version": "slot-ranking-v1",
        "maximum_affinity": 0.12,
        "signal_source": "stored_governed_editorial_and_product_projections",
        "eligibility_effect": "none",
    }
    v2 = SlotRankingPolicy(version=SAME_TOPIC_DEDUP_SLOT_RANKING_VERSION).as_metadata()
    assert v2["same_topic_similarity_threshold"] == 0.66
    assert v2["same_topic_title_overlap_chars"] == 5


@pytest.mark.parametrize(
    ("left", "right"),
    (
        (
            "张国清出席第五届北斗规模应用国际峰会开幕式并致辞",
            "李强出席2026年世界技能大会开幕式并致辞",
        ),
        ("8000亿元新型政策性金融工具资金加快投放", "前8个月全国完成水利建设投资近7000亿元"),
        (
            "北京师范大学党委理论学习中心组：系统性重塑师范育人新范式",
            "国际爱护动物基金会一行访问北京师范大学",
        ),
        (
            "中共中央办公厅 国务院办公厅印发《关于分类推进高校改革的意见》",
            "中共中央办公厅 国务院办公厅 中央军委办公厅印发《退役军人服务和保障“十五五”规划》",
        ),
    ),
)
def test_v3_headline_ignores_boilerplate_that_v2_matched(left: str, right: str) -> None:
    assert is_same_topic(_fp(1, left), _fp(2, right))
    assert not is_same_topic(_fp(1, left), _fp(2, right), strict_headline=True)


def test_v3_still_dedups_real_same_topic_headlines_and_is_the_default() -> None:
    policy = SlotRankingPolicy(version=STRICT_HEADLINE_SLOT_RANKING_VERSION)
    decision = _select(policy)

    assert policy.dedups_same_topic and policy.strict_headline
    assert decision.selected_event_ids == (UUID(int=1), UUID(int=3), UUID(int=4))
    assert policy.as_metadata()["same_topic_headline_rule"] == "headline-boilerplate-stripped-v1"
    assert (
        "same_topic_headline_rule"
        not in SlotRankingPolicy(version=SAME_TOPIC_DEDUP_SLOT_RANKING_VERSION).as_metadata()
    )
    assert Settings(_env_file=None).content_slot_ranking_version == (
        STRICT_HEADLINE_SLOT_RANKING_VERSION
    )


def test_v3_keeps_two_different_opening_ceremony_stories_on_one_day() -> None:
    candidates = (
        _candidate(1, "张国清出席第五届北斗规模应用国际峰会开幕式并致辞", 0.9),
        _candidate(2, "李强出席2026年世界技能大会开幕式并致辞", 0.8),
    )

    def select(version: str) -> tuple[UUID, ...]:
        return select_slot_topics(
            candidates,
            as_of=NOW,
            config=build_topic_scoring_config(Settings(_env_file=None)),
            slot=ContentSlot.NOON,
            policy=SlotRankingPolicy(version=version),
            max_items=3,
        ).selected_event_ids

    assert select(SAME_TOPIC_DEDUP_SLOT_RANKING_VERSION) == (UUID(int=1),)
    assert select(STRICT_HEADLINE_SLOT_RANKING_VERSION) == (UUID(int=1), UUID(int=2))
