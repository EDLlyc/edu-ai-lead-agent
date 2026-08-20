from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from app.core.config import Settings
from app.domain.content_slots import (
    ContentSlot,
    ContentSlotSchedule,
    SlotRankingPolicy,
    SlotUnfilledReason,
    due_content_slot_business_date,
    select_slot_topics,
)
from app.domain.editorial_relevance import ScienceTechEditorialCohort
from app.domain.ministry_education_priority import MINISTRY_EDUCATION_PRIORITY_V4_RULE_VERSION
from app.domain.topic_selection import TopicCandidate, TopicScoringConfig
from app.infrastructure.db.content_slots import _validate_content_slot_decision
from pydantic import ValidationError

NOW = datetime(2026, 8, 14, 1, 0, tzinfo=UTC)


def _candidate(
    suffix: int,
    *,
    total_features: float = 1.0,
    cohort: ScienceTechEditorialCohort = (
        ScienceTechEditorialCohort.SCIENCE_TECHNOLOGY_EDUCATION_PRIORITY
    ),
    reasons: tuple[str, ...] = ("explicit_science_technology_education",),
    directions: tuple[str, ...] = (),
    priority_policy: str | None = None,
    veto: bool = False,
    frontier_significance: float | None = None,
) -> TopicCandidate:
    return TopicCandidate(
        event_id=UUID(f"00000000-0000-4000-8000-{suffix:012d}"),
        event_version_id=UUID(f"10000000-0000-4000-8000-{suffix:012d}"),
        event_time=NOW,
        source_trust=total_features,
        source_diversity=4,
        ai_relevance=total_features,
        parent_relevance=total_features,
        communication_potential=total_features,
        editorial_priority=total_features,
        science_tech_editorial_cohort=cohort,
        science_tech_education_relevance=total_features,
        frontier_significance=(
            total_features if frontier_significance is None else frontier_significance
        ),
        science_tech_editorial_reason_codes=reasons,
        product_matrix_fit_v2=total_features,
        product_matrix_v2_direction_ids=directions,
        topic_priority_policy=priority_policy,
        priority_title=("人工智能教育课程实施方案" if priority_policy else f"候选 {suffix}"),
        priority_summary=("推动中小学人工智能课程教学实践。" if priority_policy else "治理摘要"),
        prohibited_marketing_risk=veto,
    )


def test_settings_own_three_default_disabled_slot_schedules() -> None:
    settings = Settings(_env_file=None)

    schedules = settings.content_slot_schedules()

    assert [(item.slot.value, item.display_name) for item in schedules] == [
        ("morning", "科教晨报"),
        ("noon", "午间观察"),
        ("evening", "晚间精选"),
    ]
    assert [(item.target_hour, item.target_minute) for item in schedules] == [
        (7, 30),
        (12, 30),
        (18, 30),
    ]
    assert all(not item.enabled for item in schedules)
    assert settings.content_slot_mode_enabled is False


@pytest.mark.parametrize(
    ("updates", "message"),
    [
        ({"content_slot_prepare_lead_minutes": 29}, "greater than or equal to 30"),
        ({"content_slot_delivery_late_minutes": 121}, "less than or equal to 120"),
        ({"content_slot_max_items": 4}, "less than or equal to 3"),
        ({"wecom_slot_package_gap_seconds": 0}, "greater than or equal to 1"),
    ],
)
def test_slot_setting_bounds(updates: dict[str, int], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        Settings(_env_file=None, **updates)  # type: ignore[arg-type]


def test_slot_mode_requires_the_existing_content_runtime_gate() -> None:
    with pytest.raises(ValidationError, match="content slot mode requires content"):
        Settings(_env_file=None, content_slot_mode_enabled=True)


def test_slot_ranking_version_is_exhaustive_at_configuration_load() -> None:
    with pytest.raises(ValidationError, match="slot-ranking-v1"):
        Settings(_env_file=None, content_slot_ranking_version="slot-ranking-v2")  # type: ignore[arg-type]


def test_schedule_instants_are_aware_and_cross_dst_by_timezone_rules() -> None:
    schedule = ContentSlotSchedule(
        slot=ContentSlot.MORNING,
        enabled=True,
        target_hour=7,
        target_minute=30,
    )

    instants = schedule.instants(date(2026, 3, 8), "America/New_York")

    assert instants.preparation_at.tzinfo is not None
    assert instants.target_at.isoformat() == "2026-03-08T07:30:00-04:00"
    assert instants.expires_at.isoformat() == "2026-03-08T08:30:00-04:00"


def test_due_business_date_uses_preparation_window_not_target_as_generation_start() -> None:
    schedule = ContentSlotSchedule(
        slot=ContentSlot.NOON,
        enabled=True,
        target_hour=12,
        target_minute=30,
    )

    assert (
        due_content_slot_business_date(
            datetime(2026, 8, 14, 2, 59, tzinfo=UTC),
            timezone="Asia/Shanghai",
            schedule=schedule,
            catchup_hours=12,
        )
        is None
    )
    assert due_content_slot_business_date(
        datetime(2026, 8, 14, 3, 0, tzinfo=UTC),
        timezone="Asia/Shanghai",
        schedule=schedule,
        catchup_hours=12,
    ) == date(2026, 8, 14)


def test_due_business_date_resolves_cross_midnight_preparation_to_next_day() -> None:
    schedule = ContentSlotSchedule(
        slot=ContentSlot.MORNING,
        enabled=True,
        target_hour=0,
        target_minute=30,
    )

    assert due_content_slot_business_date(
        datetime(2026, 8, 14, 15, 0, tzinfo=UTC),
        timezone="Asia/Shanghai",
        schedule=schedule,
        catchup_hours=12,
    ) == date(2026, 8, 15)


def test_slot_affinity_changes_only_order_not_base_eligibility_or_total() -> None:
    preferred = _candidate(
        1,
        total_features=0.75,
        directions=("competition_innovation_talent_pathway",),
    )
    higher_base = _candidate(
        2,
        total_features=0.77,
        cohort=ScienceTechEditorialCohort.FRONTIER_SCIENCE_TECHNOLOGY,
        reasons=("qualified_frontier_advance",),
    )

    decision = select_slot_topics(
        (higher_base, preferred),
        as_of=NOW,
        config=TopicScoringConfig(),
        slot=ContentSlot.NOON,
        policy=SlotRankingPolicy(),
        max_items=2,
    )

    assert decision.selected_event_ids == (preferred.event_id, higher_base.event_id)
    by_event = {score.base.event_id: score for score in decision.scores}
    assert by_event[preferred.event_id].base.total < by_event[higher_base.event_id].base.total
    assert by_event[preferred.event_id].base.eligible is True
    assert by_event[preferred.event_id].affinity > 0


@pytest.mark.parametrize(
    ("slot", "preferred", "reason"),
    [
        (
            ContentSlot.MORNING,
            _candidate(11),
            "education_policy_or_science_education",
        ),
        (
            ContentSlot.NOON,
            _candidate(
                12,
                cohort=ScienceTechEditorialCohort.FRONTIER_SCIENCE_TECHNOLOGY,
                reasons=("qualified_frontier_advance",),
                directions=("competition_innovation_talent_pathway",),
            ),
            "school_practice_or_pathway_direction",
        ),
        (
            ContentSlot.EVENING,
            _candidate(
                13,
                cohort=ScienceTechEditorialCohort.FRONTIER_SCIENCE_TECHNOLOGY,
                reasons=("qualified_frontier_advance",),
            ),
            "frontier_advance",
        ),
    ],
)
def test_each_slot_preference_uses_stored_language_independent_signals(
    slot: ContentSlot,
    preferred: TopicCandidate,
    reason: str,
) -> None:
    neutral = _candidate(
        20,
        cohort=(
            ScienceTechEditorialCohort.SCIENCE_TECHNOLOGY_EDUCATION_PRIORITY
            if slot is ContentSlot.EVENING
            else ScienceTechEditorialCohort.FRONTIER_SCIENCE_TECHNOLOGY
        ),
        reasons=("qualified_science_technology_advance",),
        frontier_significance=0.5,
    )

    decision = select_slot_topics(
        (neutral, preferred),
        as_of=NOW,
        config=TopicScoringConfig(),
        slot=slot,
        policy=SlotRankingPolicy(),
        max_items=2,
    )

    assert decision.selected_event_ids[0] == preferred.event_id
    score = next(item for item in decision.scores if item.base.event_id == preferred.event_id)
    assert reason in score.affinity_reasons


def test_affinity_never_rescues_below_threshold_or_vetoed_candidates() -> None:
    below = _candidate(
        1,
        total_features=0.3,
        directions=("competition_innovation_talent_pathway",),
    )
    vetoed = _candidate(
        2,
        directions=("competition_innovation_talent_pathway",),
        veto=True,
    )

    decision = select_slot_topics(
        (below, vetoed),
        as_of=NOW,
        config=TopicScoringConfig(),
        slot=ContentSlot.NOON,
        policy=SlotRankingPolicy(),
        max_items=3,
    )

    assert decision.selected_event_ids == ()
    assert all(not score.base.eligible for score in decision.scores)
    assert SlotUnfilledReason.BELOW_THRESHOLD in decision.unfilled_reason_codes


def test_ministry_priority_is_global_and_same_day_events_are_excluded() -> None:
    ministry = _candidate(
        1,
        total_features=0.3,
        priority_policy="moe-science-top1-v1",
    )
    ordinary = _candidate(2)

    morning = select_slot_topics(
        (ordinary, ministry),
        as_of=NOW,
        config=TopicScoringConfig(
            selection_priority_rule_version=MINISTRY_EDUCATION_PRIORITY_V4_RULE_VERSION
        ),
        slot=ContentSlot.EVENING,
        policy=SlotRankingPolicy(),
        max_items=2,
    )
    later = select_slot_topics(
        (ordinary, ministry),
        as_of=NOW,
        config=TopicScoringConfig(
            selection_priority_rule_version=MINISTRY_EDUCATION_PRIORITY_V4_RULE_VERSION
        ),
        slot=ContentSlot.NOON,
        policy=SlotRankingPolicy(),
        max_items=2,
        same_day_selected_event_ids=frozenset({ministry.event_id}),
    )

    assert morning.selected_event_ids[0] == ministry.event_id
    assert ministry.event_id not in later.selected_event_ids
    excluded = next(score for score in later.scores if score.base.event_id == ministry.event_id)
    assert excluded.base.eligible is True
    assert excluded.same_day_exclusion_reason == "same_day_already_selected"
    assert excluded.final_ordering_key.startswith("2:")


@pytest.mark.parametrize("count", [0, 1, 2, 3])
def test_slot_selects_zero_to_three_without_lowering_quality(count: int) -> None:
    candidates = tuple(_candidate(index + 1) for index in range(count))

    decision = select_slot_topics(
        candidates,
        as_of=NOW,
        config=TopicScoringConfig(),
        slot=ContentSlot.MORNING,
        policy=SlotRankingPolicy(),
        max_items=3,
    )

    assert len(decision.selected_event_ids) == count
    assert decision.unfilled_count == 3 - count
    assert [score.selected_ordinal for score in decision.scores] == list(range(1, count + 1))


def test_slot_ties_are_stable_by_event_id() -> None:
    one, two = _candidate(1), _candidate(2)

    decision = select_slot_topics(
        (two, one),
        as_of=NOW,
        config=TopicScoringConfig(),
        slot=ContentSlot.MORNING,
        policy=SlotRankingPolicy(),
        max_items=3,
    )

    assert decision.selected_event_ids == (one.event_id, two.event_id)


def test_three_slots_converge_to_at_most_nine_distinct_daily_events() -> None:
    candidates = tuple(_candidate(index) for index in range(1, 13))
    selected: set[UUID] = set()

    for slot in ContentSlot:
        decision = select_slot_topics(
            candidates,
            as_of=NOW,
            config=TopicScoringConfig(),
            slot=slot,
            policy=SlotRankingPolicy(),
            max_items=3,
            same_day_selected_event_ids=frozenset(selected),
        )
        assert len(decision.selected_event_ids) == 3
        assert selected.isdisjoint(decision.selected_event_ids)
        selected.update(decision.selected_event_ids)

    assert len(selected) == 9


def test_persistence_validation_rejects_decision_score_lineage_drift() -> None:
    decision = select_slot_topics(
        (_candidate(1), _candidate(2)),
        as_of=NOW,
        config=TopicScoringConfig(),
        slot=ContentSlot.MORNING,
        policy=SlotRankingPolicy(),
        max_items=3,
    )

    assert _validate_content_slot_decision(decision, item_limit=3) == decision.scores

    with pytest.raises(ValueError, match="selected event IDs"):
        _validate_content_slot_decision(
            replace(decision, selected_event_ids=tuple(reversed(decision.selected_event_ids))),
            item_limit=3,
        )
    with pytest.raises(ValueError, match="consecutive stable ranks"):
        _validate_content_slot_decision(
            replace(
                decision,
                scores=(replace(decision.scores[0], rank=2), *decision.scores[1:]),
            ),
            item_limit=3,
        )
