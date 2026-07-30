import math
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from app.domain.event_assignment import (
    EventArticleProfile,
    EventAssignmentPolicy,
    EventCandidateProfile,
    decide_event_assignment,
    evaluate_clustering_labels,
)
from app.domain.governance_enums import EventAssignmentOutcome, FactualCategory

NOW = datetime(2026, 7, 29, 8, 0, tzinfo=UTC)
POLICY = EventAssignmentPolicy(version="event-assignment-v1")


def _vector(similarity: float) -> tuple[float, float]:
    return similarity, math.sqrt(1 - similarity**2)


def _incoming(
    *,
    title: str = "教育部发布人工智能课程指南",
    vector: tuple[float, ...] = (1.0, 0.0),
    entities: frozenset[str] = frozenset({"教育部"}),
    event_time: datetime | None = NOW,
    published_at: datetime = NOW,
) -> EventArticleProfile:
    return EventArticleProfile(
        normalized_article_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        title=title,
        vector=vector,
        simhash_hex="0000000000000000",
        categories=frozenset({FactualCategory.AI_EDUCATION_POLICY}),
        entities=entities,
        event_time=event_time,
        published_at=published_at,
    )


def _candidate(
    event_id: str = "11111111-1111-4111-8111-111111111111",
    *,
    title: str = "教育部发布人工智能课程指南",
    vector: tuple[float, ...] = (1.0, 0.0),
    entities: frozenset[str] = frozenset({"教育部"}),
    event_time: datetime | None = NOW,
    published_at: datetime = NOW,
) -> EventCandidateProfile:
    return EventCandidateProfile(
        event_id=UUID(event_id),
        representative_article_id=UUID(event_id.replace("1", "c").replace("2", "d")),
        representative_title=title,
        vector=vector,
        simhash_hex="0000000000000000",
        categories=frozenset({FactualCategory.AI_EDUCATION_POLICY}),
        entities=entities,
        event_time=event_time,
        representative_published_at=published_at,
        source_diversity=1,
    )


def test_same_event_paraphrase_attaches_to_existing_event() -> None:
    decision = decide_event_assignment(
        _incoming(title="人工智能课程教学指南由教育部发布"),
        (_candidate(),),
        POLICY,
    )

    assert decision.outcome is EventAssignmentOutcome.ASSIGNED_EXISTING
    assert decision.selected_event_id == UUID("11111111-1111-4111-8111-111111111111")
    assert decision.features is not None
    assert decision.features.identity_conflict is False


def test_same_topic_but_different_event_is_kept_separate_by_time() -> None:
    decision = decide_event_assignment(
        _incoming(event_time=NOW + timedelta(days=30), published_at=NOW + timedelta(days=30)),
        (_candidate(),),
        POLICY,
    )

    assert decision.outcome is EventAssignmentOutcome.CREATED_NEW
    assert decision.selected_event_id is None


@pytest.mark.parametrize(
    ("candidate", "incoming", "expected_conflict"),
    (
        (
            _candidate(entities=frozenset({"甲公司"})),
            _incoming(entities=frozenset({"乙公司"})),
            True,
        ),
        (
            _candidate(event_time=NOW - timedelta(days=5)),
            _incoming(),
            False,
        ),
    ),
)
def test_conflicting_entity_or_gray_date_is_routed_to_review(
    candidate: EventCandidateProfile,
    incoming: EventArticleProfile,
    expected_conflict: bool,
) -> None:
    decision = decide_event_assignment(incoming, (candidate,), POLICY)

    assert decision.outcome is EventAssignmentOutcome.REVIEW_REQUIRED
    assert decision.features is not None
    assert decision.features.identity_conflict is expected_conflict


def test_similarity_gray_band_is_routed_to_review() -> None:
    decision = decide_event_assignment(
        _incoming(vector=_vector(0.85)),
        (_candidate(),),
        POLICY,
    )

    assert decision.outcome is EventAssignmentOutcome.REVIEW_REQUIRED


def test_assignment_compares_only_event_representative_and_avoids_transitive_merge() -> None:
    representative_a = _candidate(
        title="A 人工智能课程试点启动",
        vector=_vector(0.75),
        event_time=NOW - timedelta(days=10),
        published_at=NOW - timedelta(days=10),
    )
    incoming_c = _incoming(
        title="C 人工智能课程试点总结",
        vector=(1.0, 0.0),
        event_time=NOW,
    )

    decision = decide_event_assignment(incoming_c, (representative_a,), POLICY)

    assert decision.outcome is EventAssignmentOutcome.CREATED_NEW
    assert decision.selected_event_id is None


def test_equal_scores_use_event_uuid_as_stable_tie_break() -> None:
    lower = _candidate("11111111-1111-4111-8111-111111111111")
    higher = _candidate("22222222-2222-4222-8222-222222222222")

    first = decide_event_assignment(_incoming(), (higher, lower), POLICY)
    second = decide_event_assignment(_incoming(), (lower, higher), POLICY)

    assert first.selected_event_id == lower.event_id
    assert second.selected_event_id == lower.event_id
    assert first.alternatives == second.alternatives


def test_assignment_uses_first_candidate_that_passes_all_attach_gates() -> None:
    conflicting_best = _candidate(
        "11111111-1111-4111-8111-111111111111",
        entities=frozenset({"另一机构"}),
    )
    compatible_second = _candidate(
        "22222222-2222-4222-8222-222222222222",
        title="芯片算力基础设施进展",
        vector=_vector(0.91),
    )

    decision = decide_event_assignment(
        _incoming(),
        (conflicting_best, compatible_second),
        POLICY,
    )

    assert decision.outcome is EventAssignmentOutcome.ASSIGNED_EXISTING
    assert decision.selected_event_id == compatible_second.event_id
    assert decision.alternatives[0].event_id == conflicting_best.event_id


@pytest.mark.parametrize(
    "changes",
    (
        {"attach_time_days": 0},
        {"review_time_days": 0},
        {"attach_time_days": 8, "review_time_days": 7},
    ),
)
def test_assignment_policy_rejects_invalid_time_thresholds(
    changes: dict[str, float],
) -> None:
    with pytest.raises(ValueError, match="time threshold"):
        EventAssignmentPolicy(version="invalid", **changes)


def test_controlled_label_evaluation_reports_quality_and_review_rate() -> None:
    evaluation = evaluate_clustering_labels(
        (
            (True, EventAssignmentOutcome.ASSIGNED_EXISTING),
            (True, EventAssignmentOutcome.REVIEW_REQUIRED),
            (False, EventAssignmentOutcome.CREATED_NEW),
            (False, EventAssignmentOutcome.ASSIGNED_EXISTING),
        )
    )

    assert evaluation.precision == pytest.approx(0.5)
    assert evaluation.recall == pytest.approx(1.0)
    assert evaluation.f1 == pytest.approx(2 / 3)
    assert evaluation.review_rate == pytest.approx(0.25)
    assert evaluation.false_merge_count == 1
