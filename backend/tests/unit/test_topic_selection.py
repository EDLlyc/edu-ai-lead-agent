from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from app.domain.topic_selection import (
    MOE_SCIENCE_TOP1_PRIORITY_POLICY,
    NoTopicCode,
    TopicCandidate,
    TopicScoringConfig,
    TopicVetoCode,
    score_topic_candidate,
    select_daily_topic,
)
from app.infrastructure.db.topic_selection import source_trust_projection

NOW = datetime(2026, 7, 30, 2, 0, tzinfo=UTC)
CONFIG = TopicScoringConfig()


def _candidate(
    event_id: str = "11111111-1111-4111-8111-111111111111",
    **changes: object,
) -> TopicCandidate:
    values: dict[str, object] = {
        "event_id": UUID(event_id),
        "event_version_id": UUID(event_id.replace("1", "a").replace("2", "b")),
        "event_time": NOW - timedelta(hours=6),
        "source_trust": 0.9,
        "source_diversity": 3,
        "ai_relevance": 0.95,
        "parent_relevance": 0.85,
        "communication_potential": 0.8,
    }
    values.update(changes)
    return TopicCandidate(**values)  # type: ignore[arg-type]


def test_preview_config_exposes_versioned_weights_ranges_and_tie_breaks() -> None:
    metadata = CONFIG.as_metadata()

    assert metadata["version"] == "scoring-v1-preview.3-moe-priority"
    assert metadata["veto_rule_version"] == "topic-veto-v1"
    assert metadata["selection_priority_rule_version"] == "source-priority-v1"
    assert sum(CONFIG.positive_weights.values()) == pytest.approx(1.0)
    assert metadata["freshness_window_days"] == 10.0
    assert metadata["tie_break_order"] == [
        "eligible",
        "total",
        "source_trust",
        "event_time",
        "event_id",
    ]
    assert TopicScoringConfig.from_metadata(metadata) == CONFIG


def test_hard_veto_cannot_be_outweighed_by_a_high_numeric_score() -> None:
    decision = select_daily_topic(
        (
            _candidate(
                source_trust=1.0,
                source_diversity=10,
                ai_relevance=1.0,
                parent_relevance=1.0,
                communication_potential=1.0,
                tier_c_only=True,
            ),
        ),
        as_of=NOW,
        config=CONFIG,
    )

    assert decision.is_no_topic is True
    assert decision.no_topic_code is NoTopicCode.ALL_VETOED
    assert decision.scores[0].passes_threshold is True
    assert decision.scores[0].eligible is False
    assert decision.scores[0].veto_codes == (TopicVetoCode.TIER_C_ONLY,)


def test_eligible_ministry_priority_beats_a_higher_scoring_ordinary_candidate() -> None:
    ordinary = _candidate()
    ministry = _candidate(
        event_id="22222222-2222-4222-8222-222222222222",
        source_trust=0.8,
        source_diversity=2,
        ai_relevance=0.6,
        parent_relevance=0.6,
        communication_potential=0.6,
        topic_priority_policy=MOE_SCIENCE_TOP1_PRIORITY_POLICY,
    )

    decision = select_daily_topic((ordinary, ministry), as_of=NOW, config=CONFIG)

    assert decision.selected_event_id == ministry.event_id
    assert decision.scores[0].event_id == ministry.event_id
    assert decision.scores[0].priority_applied is True
    assert decision.scores[0].priority_reason == "eligible_official_ministry_science_source"
    assert decision.scores[0].total < decision.scores[1].total


def test_priority_does_not_rescue_a_vetoed_ministry_candidate() -> None:
    ordinary = _candidate()
    ministry = _candidate(
        event_id="22222222-2222-4222-8222-222222222222",
        topic_priority_policy=MOE_SCIENCE_TOP1_PRIORITY_POLICY,
        tier_c_only=True,
    )

    decision = select_daily_topic((ministry, ordinary), as_of=NOW, config=CONFIG)
    ministry_score = next(score for score in decision.scores if score.event_id == ministry.event_id)

    assert decision.selected_event_id == ordinary.event_id
    assert ministry_score.priority_applied is False
    assert ministry_score.priority_reason == "hard_veto"


def test_priority_does_not_rescue_a_below_threshold_ministry_candidate() -> None:
    ministry = _candidate(
        topic_priority_policy=MOE_SCIENCE_TOP1_PRIORITY_POLICY,
        source_trust=0.1,
        source_diversity=1,
        ai_relevance=0.2,
        parent_relevance=0.1,
        communication_potential=0.1,
        event_time=NOW - timedelta(days=10),
    )

    decision = select_daily_topic((ministry,), as_of=NOW, config=CONFIG)

    assert decision.no_topic_code is NoTopicCode.BELOW_THRESHOLD
    assert decision.scores[0].priority_applied is False
    assert decision.scores[0].priority_reason == "below_threshold"


def test_seven_day_repeat_is_vetoed_but_boundary_is_allowed() -> None:
    repeated = score_topic_candidate(
        _candidate(days_since_last_selection=6),
        as_of=NOW,
        config=CONFIG,
    )
    boundary = score_topic_candidate(
        _candidate(days_since_last_selection=7),
        as_of=NOW,
        config=CONFIG,
    )

    assert TopicVetoCode.REPEATED_WITHIN_WINDOW in repeated.veto_codes
    assert TopicVetoCode.REPEATED_WITHIN_WINDOW not in boundary.veto_codes
    assert repeated.raw_features["days_since_last_selection"] == 6.0


def test_event_older_than_freshness_window_is_transparently_vetoed() -> None:
    stale = score_topic_candidate(
        _candidate(event_time=NOW - timedelta(days=10, seconds=1)),
        as_of=NOW,
        config=CONFIG,
    )
    boundary = score_topic_candidate(
        _candidate(event_time=NOW - timedelta(days=10)),
        as_of=NOW,
        config=CONFIG,
    )

    assert TopicVetoCode.STALE_EVENT in stale.veto_codes
    assert TopicVetoCode.STALE_EVENT not in boundary.veto_codes


def test_below_threshold_candidates_produce_no_topic_without_a_veto() -> None:
    decision = select_daily_topic(
        (
            _candidate(
                source_trust=0.1,
                source_diversity=1,
                ai_relevance=0.2,
                parent_relevance=0.1,
                communication_potential=0.1,
                event_time=NOW - timedelta(days=10),
            ),
        ),
        as_of=NOW,
        config=CONFIG,
    )

    assert decision.no_topic_code is NoTopicCode.BELOW_THRESHOLD
    assert decision.scores[0].veto_codes == ()
    assert decision.scores[0].passes_threshold is False


def test_selection_is_stable_and_uses_documented_tie_breaks() -> None:
    lower_uuid = _candidate("11111111-1111-4111-8111-111111111111")
    higher_uuid = _candidate("22222222-2222-4222-8222-222222222222")

    first = select_daily_topic((higher_uuid, lower_uuid), as_of=NOW, config=CONFIG)
    second = select_daily_topic((lower_uuid, higher_uuid), as_of=NOW, config=CONFIG)

    assert first.selected_event_id == lower_uuid.event_id
    assert second.selected_event_id == lower_uuid.event_id
    assert tuple(score.event_id for score in first.scores) == tuple(
        score.event_id for score in second.scores
    )


def test_score_preserves_raw_normalized_weight_penalty_and_explanation_fields() -> None:
    score = score_topic_candidate(
        _candidate(
            theme_repetition=0.4,
            controversy_risk=0.2,
            marketing_risk=0.1,
        ),
        as_of=NOW,
        config=CONFIG,
    )
    metadata = score.as_metadata()

    assert score.total == pytest.approx(
        sum(score.positive_components.values()) - sum(score.penalty_components.values())
    )
    assert score.raw_features["source_diversity"] == 3.0
    assert score.normalized_features["source_diversity"] == 0.75
    assert metadata["scoring_version"] == "scoring-v1-preview.3-moe-priority"
    assert metadata["veto_codes"] == []
    assert metadata["selection_priority_rule_version"] == "source-priority-v1"
    assert metadata["priority_applied"] is False


def test_empty_candidate_pool_produces_explicit_no_candidates_result() -> None:
    decision = select_daily_topic((), as_of=NOW, config=CONFIG)

    assert decision.no_topic_code is NoTopicCode.NO_CANDIDATES
    assert decision.scores == ()


def test_legacy_config_metadata_remains_byte_for_byte_compatible() -> None:
    legacy_metadata = CONFIG.as_metadata()
    legacy_metadata.pop("selection_priority_rule_version")

    legacy_config = TopicScoringConfig.from_metadata(legacy_metadata)

    assert legacy_config.selection_priority_rule_version is None
    assert legacy_config.as_metadata() == legacy_metadata


def test_source_trust_projection_never_promotes_unknown_or_tier_c_sources() -> None:
    source_a, source_b, source_unknown = uuid4(), uuid4(), uuid4()

    trust, tier_c_only, eligible = source_trust_projection(
        {
            source_a: {"A"},
            source_b: {"B", "C"},
            source_unknown: {"unknown"},
        }
    )
    tier_c_trust, only_tier_c, tier_c_eligible = source_trust_projection({source_b: {"C"}})

    assert trust == pytest.approx((1.0 + 0.75 + 0.0) / 3)
    assert tier_c_only is False
    assert eligible is True
    assert tier_c_trust == 0.0
    assert only_tier_c is True
    assert tier_c_eligible is False


@pytest.mark.parametrize(
    "changes",
    (
        {"threshold": float("nan")},
        {"freshness_window_days": 0},
        {"source_trust_weight": 0.19},
    ),
)
def test_config_rejects_invalid_ranges_or_weight_total(changes: dict[str, object]) -> None:
    with pytest.raises(ValueError):
        TopicScoringConfig(**changes)  # type: ignore[arg-type]
