# ruff: noqa: RUF001
from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from app.domain.topic_selection import TopicCandidate
from evals.selection_replay.metrics import (
    ReplayPick,
    cross_day_repeats,
    same_day_same_topic_pairs,
    slot_changes,
    summarize,
    topic_match_kind,
)
from evals.selection_replay.runner import _with_replay_history, parse_variant

DAY = date(2026, 9, 20)


def _pick(
    title: str,
    *,
    day: int = 0,
    slot: str = "morning",
    ordinal: int = 1,
    event_id: UUID | None = None,
    reason: str | None = None,
    summary: str | None = None,
    embedding: tuple[float, ...] | None = None,
    passes: bool = True,
) -> ReplayPick:
    return ReplayPick(
        business_date=DAY + timedelta(days=day),
        slot=slot,
        ordinal=ordinal,
        event_id=event_id or uuid4(),
        title=title,
        summary=summary,
        total=0.5,
        passes_threshold=passes,
        priority_reason=reason,
        embedding=embedding,
    )


def test_match_kind_prefers_the_strongest_clause() -> None:
    shared = uuid4()
    assert topic_match_kind(_pick("甲", event_id=shared), _pick("乙", event_id=shared)) == (
        "same_event"
    )
    assert (
        topic_match_kind(_pick("甲", embedding=(1.0, 0.0)), _pick("乙", embedding=(0.9, 0.1)))
        == "similar_article"
    )
    assert topic_match_kind(_pick("世界技能大赛开幕"), _pick("世界技能大赛闭幕")) == (
        "title_phrase"
    )
    assert topic_match_kind(_pick("火箭发射成功"), _pick("大熊猫赴美")) is None


def test_repeats_and_same_day_pairs_are_classified() -> None:
    event = uuid4()
    picks = [
        _pick("望宇登月服研制已攻克数十项关键技术", event_id=event),
        _pick("望宇登月服研制已攻克数十项关键技术", day=7, event_id=event),
        _pick("世界技能大赛标准引领职教课堂", day=7, slot="noon"),
        _pick("用技能为青春加冕——第48届世界技能大赛中国代表团", day=7, slot="noon", ordinal=2),
        _pick("大熊猫赴美", day=20),
    ]

    repeats = cross_day_repeats(picks)
    pairs = same_day_same_topic_pairs(picks)

    assert [kind for kind, _earlier, _later in repeats] == ["same_event"]
    assert [kind for kind, _left, _right in pairs] == ["title_phrase"]
    # Beyond the 14-day window nothing counts as a repeat.
    assert cross_day_repeats([picks[0], _pick(picks[0].title, day=15, event_id=event)]) == []


def test_summary_counts_the_operator_rules() -> None:
    picks = [
        _pick("李强会见吉尔吉斯斯坦总理", reason="qualified_government_yaowen_priority"),
        _pick("习近平就发展先进制造业作出重要指示", reason="qualified_government_yaowen_priority"),
        _pick("男子编造谣言，已被刑拘", summary="警方通报", passes=False),
        _pick("研究揭示溶剂占据调控分子筛微孔催化扩散机制"),
        _pick("教育部印发意见", reason="education_policy_signal_national"),
    ]

    summary = summarize(picks)

    assert summary["picks"] == 5
    assert summary["gov_yaowen_priority"] == 2
    assert len(summary["gov_yaowen_priority_off_topic"]) == 1
    assert summary["education_policy"] == 1
    assert len(summary["negative_incident"]) == 1
    assert len(summary["specialised_research"]) == 1
    assert summary["below_threshold"] == 1


def test_slot_changes_list_removed_and_added_titles() -> None:
    before = [_pick("金砖会晤讲话"), _pick("望宇登月服", ordinal=2)]
    after = [_pick("望宇登月服", ordinal=1), _pick("朱雀三号着陆", ordinal=2)]

    assert slot_changes(before, after) == [("09-20 早间", ["金砖会晤讲话"], ["朱雀三号着陆"])]


def test_replay_history_keeps_pre_range_production_and_uses_own_picks_inside() -> None:
    def candidate(event: UUID, days: int | None) -> TopicCandidate:
        return TopicCandidate(
            event_id=event,
            event_version_id=uuid4(),
            event_time=datetime(2026, 9, 25, tzinfo=UTC),
            source_trust=1.0,
            source_diversity=1,
            ai_relevance=0.0,
            parent_relevance=0.0,
            communication_potential=0.5,
            days_since_last_selection=days,
        )

    old, in_range, mine, today = uuid4(), uuid4(), uuid4(), uuid4()
    business_date = date(2026, 9, 25)
    adjusted = _with_replay_history(
        (candidate(old, 10), candidate(in_range, 2), candidate(mine, None), candidate(today, None)),
        business_date=business_date,
        start=date(2026, 9, 19),
        last_picked={mine: date(2026, 9, 21), today: business_date},
    )

    assert [item.days_since_last_selection for item in adjusted] == [10, None, 4, None]


def test_variant_parsing() -> None:
    variant = parse_variant("v15=scoring-x+slot-y")
    assert (variant.name, variant.scoring_version, variant.slot_ranking_version) == (
        "v15",
        "scoring-x",
        "slot-y",
    )
    with pytest.raises(Exception, match="NAME=SCORING_VERSION"):
        parse_variant("v15")
