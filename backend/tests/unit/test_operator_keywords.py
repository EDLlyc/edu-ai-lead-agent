# ruff: noqa: RUF001
from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest
from app.domain.content_slots import ContentSlot, SlotRankingPolicy, select_slot_topics
from app.domain.editorial_relevance import ScienceTechEditorialCohort
from app.domain.operator_keywords import (
    OPERATOR_FOCUS_BONUS,
    KeywordListError,
    OperatorKeywords,
    build_keyword_lists,
    keyword_diff,
    matched_terms,
)
from app.domain.topic_selection import TopicCandidate, TopicScoringConfig, TopicVetoCode
from app.infrastructure.db.operator_keywords import RecentCandidate, keyword_impact

NOW = datetime(2026, 10, 8, 1, 0, tzinfo=UTC)


def _candidate(suffix: int, *, features: float = 0.8, title: str = "") -> TopicCandidate:
    return TopicCandidate(
        event_id=UUID(f"00000000-0000-4000-8000-{suffix:012d}"),
        event_version_id=UUID(f"10000000-0000-4000-8000-{suffix:012d}"),
        event_time=NOW,
        source_trust=features,
        source_diversity=3,
        ai_relevance=features,
        parent_relevance=features,
        communication_potential=features,
        editorial_priority=features,
        science_tech_editorial_cohort=ScienceTechEditorialCohort.FRONTIER_SCIENCE_TECHNOLOGY,
        science_tech_education_relevance=features,
        frontier_significance=features,
        product_matrix_fit_v2=features,
        priority_title=title or f"候选 {suffix}",
        priority_summary="治理摘要",
    )


def _select(*candidates: TopicCandidate, max_items: int = 1):  # type: ignore[no-untyped-def]
    return select_slot_topics(
        candidates,
        as_of=NOW,
        config=TopicScoringConfig(),
        slot=ContentSlot.NOON,
        policy=SlotRankingPolicy(),
        max_items=max_items,
    )


def test_lists_are_cleaned_deduplicated_and_checked() -> None:
    focus, block, banned = build_keyword_lists(
        focus=[" 人工智能 ", "AI", "ai", "", "机器人  教育"],
        block=["彩票"],
        copy_banned=["保证提分"],
    )
    assert focus == ("人工智能", "AI", "机器人 教育")
    assert block == ("彩票",)
    assert banned == ("保证提分",)

    with pytest.raises(KeywordListError, match="同时在关注词和屏蔽词里：ai"):
        build_keyword_lists(focus=["AI"], block=["ai"], copy_banned=[])
    with pytest.raises(KeywordListError, match="太长"):
        build_keyword_lists(focus=["一" * 21], block=[], copy_banned=[])
    with pytest.raises(KeywordListError, match="最多 200 个"):
        build_keyword_lists(focus=[f"词{i}" for i in range(201)], block=[], copy_banned=[])
    with pytest.raises(KeywordListError, match="只能是文字"):
        build_keyword_lists(focus=[3], block=[], copy_banned=[])


def test_matching_is_a_plain_case_insensitive_substring() -> None:
    assert matched_terms("OpenAI 发布新模型", ("openai", "模型", "芯片")) == ("openai", "模型")
    assert matched_terms("a.b", (".*",)) == ()


def test_diff_lists_added_and_removed_terms_per_list() -> None:
    before = OperatorKeywords(version=1, focus=("人工智能",), block=("彩票",))
    after = OperatorKeywords(version=2, focus=("人工智能", "机器人"), copy_banned=("保证",))
    assert keyword_diff(before, after) == {
        "focus": {"added": ["机器人"], "removed": []},
        "block": {"added": [], "removed": ["彩票"]},
        "copy_banned": {"added": ["保证"], "removed": []},
    }
    assert keyword_diff(None, OperatorKeywords(version=1)) == {}


def test_a_focus_term_moves_an_item_up_but_never_makes_it_eligible() -> None:
    stronger = _candidate(1, features=0.82)
    focused = replace(_candidate(2, features=0.8), operator_focus_terms=("机器人",))

    plain = _select(stronger, _candidate(2, features=0.8))
    assert plain.selected_event_ids == (stronger.event_id,)

    decision = _select(stronger, focused)
    assert decision.selected_event_ids == (focused.event_id,)
    score = next(item for item in decision.scores if item.base.event_id == focused.event_id)
    assert score.operator_focus_bonus == OPERATOR_FOCUS_BONUS
    assert score.operator_focus_terms == ("机器人",)
    # The base score and eligibility are untouched; only the ordering value moves.
    assert score.base.total == next(
        item.base.total for item in plain.scores if item.base.event_id == focused.event_id
    )

    vetoed = replace(
        _candidate(3), operator_focus_terms=("机器人",), prohibited_marketing_risk=True
    )
    assert not _select(vetoed).scores[0].base.eligible
    assert _select(vetoed).selected_event_ids == ()


def test_a_block_term_vetoes_the_item() -> None:
    blocked = replace(_candidate(1, features=0.9), operator_block_terms=("彩票",))
    other = _candidate(2, features=0.6)
    decision = _select(blocked, other)
    assert decision.selected_event_ids == (other.event_id,)
    score = next(item for item in decision.scores if item.base.event_id == blocked.event_id)
    assert TopicVetoCode.OPERATOR_BLOCKED_TERM in score.base.veto_codes
    assert score.operator_block_terms == ("彩票",)


def test_candidates_without_keyword_hits_score_exactly_as_before() -> None:
    first, second = _candidate(1, features=0.7), _candidate(2, features=0.75)
    decision = _select(first, second, max_items=2)
    assert all(score.operator_focus_bonus == 0 for score in decision.scores)
    assert all(
        score.ordering_value == round(score.base.total + score.affinity, 8)
        for score in decision.scores
    )


def test_impact_counts_blocked_and_focused_recent_candidates() -> None:
    candidates = [
        RecentCandidate(UUID(int=1), "彩票中奖新规", "", selected=True),
        RecentCandidate(UUID(int=2), "机器人进课堂", "彩票", selected=False),
        RecentCandidate(UUID(int=3), "机器人比赛", "", selected=False),
        RecentCandidate(UUID(int=4), "量子计算突破", "", selected=False),
    ]
    impact = keyword_impact(candidates, focus=("机器人",), block=("彩票", "赌博"))
    assert impact.candidate_count == 4
    assert [(title, selected) for title, _terms, selected in impact.blocked] == [
        ("彩票中奖新规", True),
        ("机器人进课堂", False),
    ]
    assert impact.per_block_term == {"彩票": 2, "赌博": 0}
    assert impact.focused == (("机器人比赛", ("机器人",)),)
    assert impact.blocked_share == 0.5
