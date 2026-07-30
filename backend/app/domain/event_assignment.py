from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import UUID

from app.domain.governance_enums import EventAssignmentOutcome, FactualCategory
from app.domain.governance_normalization import simhash_distance
from app.domain.governance_semantic import cosine_similarity

_TITLE_TOKEN = re.compile(r"[\u3400-\u9fff]{2}|[a-z0-9]+", re.IGNORECASE)


@dataclass(frozen=True, slots=True)
class EventAssignmentPolicy:
    version: str
    recent_window_days: int = 14
    candidate_limit: int = 20
    attach_similarity: float = 0.90
    review_similarity: float = 0.80
    attach_score: float = 0.80
    review_score: float = 0.65
    attach_time_days: float = 3.0
    review_time_days: float = 7.0
    minimum_category_overlap: float = 0.25
    minimum_entity_overlap: float = 0.25

    def __post_init__(self) -> None:
        if not self.version.strip() or len(self.version) > 80:
            raise ValueError("event assignment policy version must be non-blank and bounded")
        if self.recent_window_days < 1 or self.candidate_limit < 1:
            raise ValueError("event assignment window and candidate limit must be positive")
        thresholds = (
            self.attach_similarity,
            self.review_similarity,
            self.attach_score,
            self.review_score,
            self.minimum_category_overlap,
            self.minimum_entity_overlap,
        )
        if any(not 0 <= threshold <= 1 for threshold in thresholds):
            raise ValueError("event assignment thresholds must be in [0, 1]")
        if self.attach_similarity < self.review_similarity or self.attach_score < self.review_score:
            raise ValueError("attach thresholds must not be weaker than review thresholds")
        if self.attach_time_days <= 0 or self.review_time_days <= 0:
            raise ValueError("event assignment time thresholds must be positive")
        if self.attach_time_days > self.review_time_days:
            raise ValueError("attach time threshold must not be wider than review threshold")

    def as_metadata(self) -> dict[str, float | int | str]:
        return {
            "version": self.version,
            "recent_window_days": self.recent_window_days,
            "candidate_limit": self.candidate_limit,
            "attach_similarity": self.attach_similarity,
            "review_similarity": self.review_similarity,
            "attach_score": self.attach_score,
            "review_score": self.review_score,
            "attach_time_days": self.attach_time_days,
            "review_time_days": self.review_time_days,
            "minimum_category_overlap": self.minimum_category_overlap,
            "minimum_entity_overlap": self.minimum_entity_overlap,
        }


@dataclass(frozen=True, slots=True)
class EventArticleProfile:
    normalized_article_id: UUID
    title: str
    vector: tuple[float, ...]
    simhash_hex: str
    categories: frozenset[FactualCategory]
    entities: frozenset[str]
    event_time: datetime | None
    published_at: datetime

    def __post_init__(self) -> None:
        if not self.title.strip() or not self.vector:
            raise ValueError("event article profile requires title and vector")
        if self.event_time is not None and self.event_time.tzinfo is None:
            raise ValueError("event time must be timezone-aware")
        if self.published_at.tzinfo is None:
            raise ValueError("publication time must be timezone-aware")


@dataclass(frozen=True, slots=True)
class EventCandidateProfile:
    event_id: UUID
    representative_article_id: UUID
    representative_title: str
    vector: tuple[float, ...]
    simhash_hex: str
    categories: frozenset[FactualCategory]
    entities: frozenset[str]
    event_time: datetime | None
    representative_published_at: datetime
    source_diversity: int

    def __post_init__(self) -> None:
        if self.event_time is not None and self.event_time.tzinfo is None:
            raise ValueError("candidate event time must be timezone-aware")
        if self.representative_published_at.tzinfo is None:
            raise ValueError("candidate publication time must be timezone-aware")


@dataclass(frozen=True, slots=True)
class EventAssignmentFeatures:
    embedding_similarity: float
    title_overlap: float
    entity_overlap: float
    category_overlap: float
    event_time_distance_days: float
    time_compatibility: float
    simhash_distance: int
    composite_score: float
    identity_conflict: bool
    entity_gate_required: bool

    def as_metadata(self) -> dict[str, float | int | bool]:
        return {
            "embedding_similarity": round(self.embedding_similarity, 8),
            "title_overlap": round(self.title_overlap, 8),
            "entity_overlap": round(self.entity_overlap, 8),
            "category_overlap": round(self.category_overlap, 8),
            "event_time_distance_days": round(self.event_time_distance_days, 4),
            "time_compatibility": round(self.time_compatibility, 8),
            "simhash_distance": self.simhash_distance,
            "composite_score": round(self.composite_score, 8),
            "identity_conflict": self.identity_conflict,
            "entity_gate_required": self.entity_gate_required,
        }


@dataclass(frozen=True, slots=True)
class EventAssignmentAlternative:
    event_id: UUID
    features: EventAssignmentFeatures

    def as_metadata(self) -> dict[str, object]:
        return {"event_id": str(self.event_id), **self.features.as_metadata()}


@dataclass(frozen=True, slots=True)
class EventAssignmentDecision:
    outcome: EventAssignmentOutcome
    selected_event_id: UUID | None
    features: EventAssignmentFeatures | None
    alternatives: tuple[EventAssignmentAlternative, ...]
    policy_version: str


@dataclass(frozen=True, slots=True)
class ClusteringEvaluation:
    precision: float
    recall: float
    f1: float
    review_rate: float
    false_merge_count: int
    sample_count: int


def event_assignment_features(
    incoming: EventArticleProfile,
    candidate: EventCandidateProfile,
) -> EventAssignmentFeatures:
    embedding_similarity = cosine_similarity(incoming.vector, candidate.vector)
    title_overlap = _jaccard(
        _title_tokens(incoming.title), _title_tokens(candidate.representative_title)
    )
    entity_overlap = _jaccard(incoming.entities, candidate.entities)
    category_overlap = _jaccard(incoming.categories, candidate.categories)
    incoming_time = incoming.event_time or incoming.published_at
    candidate_time = candidate.event_time or candidate.representative_published_at
    event_time_distance_days = (
        abs((incoming_time.astimezone(UTC) - candidate_time.astimezone(UTC)).total_seconds())
        / 86_400
    )
    time_compatibility = max(0.0, 1.0 - event_time_distance_days / 7.0)
    both_have_entities = bool(incoming.entities and candidate.entities)
    identity_conflict = both_have_entities and entity_overlap == 0
    composite_score = (
        0.50 * embedding_similarity
        + 0.15 * title_overlap
        + 0.15 * entity_overlap
        + 0.10 * category_overlap
        + 0.10 * time_compatibility
    )
    return EventAssignmentFeatures(
        embedding_similarity=embedding_similarity,
        title_overlap=title_overlap,
        entity_overlap=entity_overlap,
        category_overlap=category_overlap,
        event_time_distance_days=event_time_distance_days,
        time_compatibility=time_compatibility,
        simhash_distance=simhash_distance(incoming.simhash_hex, candidate.simhash_hex),
        composite_score=composite_score,
        identity_conflict=identity_conflict,
        entity_gate_required=both_have_entities,
    )


def decide_event_assignment(
    incoming: EventArticleProfile,
    candidates: tuple[EventCandidateProfile, ...],
    policy: EventAssignmentPolicy,
) -> EventAssignmentDecision:
    alternatives = tuple(
        sorted(
            (
                EventAssignmentAlternative(
                    event_id=candidate.event_id,
                    features=event_assignment_features(incoming, candidate),
                )
                for candidate in candidates
            ),
            key=lambda alternative: (
                -alternative.features.composite_score,
                -alternative.features.embedding_similarity,
                alternative.event_id.int,
            ),
        )[: policy.candidate_limit]
    )
    if not alternatives:
        return EventAssignmentDecision(
            outcome=EventAssignmentOutcome.CREATED_NEW,
            selected_event_id=None,
            features=None,
            alternatives=(),
            policy_version=policy.version,
        )
    best = alternatives[0]
    selected = next(
        (alternative for alternative in alternatives if _passes_attach(alternative, policy)),
        None,
    )
    if selected is not None:
        outcome = EventAssignmentOutcome.ASSIGNED_EXISTING
    else:
        selected = next(
            (alternative for alternative in alternatives if _passes_review(alternative, policy)),
            None,
        )
        outcome = (
            EventAssignmentOutcome.REVIEW_REQUIRED
            if selected is not None
            else EventAssignmentOutcome.CREATED_NEW
        )
    selected_features = selected.features if selected is not None else best.features
    return EventAssignmentDecision(
        outcome=outcome,
        selected_event_id=(
            selected.event_id
            if selected is not None and outcome is not EventAssignmentOutcome.CREATED_NEW
            else None
        ),
        features=selected_features,
        alternatives=alternatives,
        policy_version=policy.version,
    )


def _passes_attach(
    alternative: EventAssignmentAlternative,
    policy: EventAssignmentPolicy,
) -> bool:
    features = alternative.features
    entity_gate = not features.identity_conflict and (
        features.entity_overlap >= policy.minimum_entity_overlap
        or not features.entity_gate_required
    )
    return (
        features.embedding_similarity >= policy.attach_similarity
        and features.composite_score >= policy.attach_score
        and features.event_time_distance_days <= policy.attach_time_days
        and features.category_overlap >= policy.minimum_category_overlap
        and entity_gate
    )


def _passes_review(
    alternative: EventAssignmentAlternative,
    policy: EventAssignmentPolicy,
) -> bool:
    features = alternative.features
    return (
        features.embedding_similarity >= policy.review_similarity
        and features.composite_score >= policy.review_score
        and features.event_time_distance_days <= policy.review_time_days
        and features.category_overlap > 0
    )


def evaluate_clustering_labels(
    labels: tuple[tuple[bool, EventAssignmentOutcome], ...],
) -> ClusteringEvaluation:
    true_positive = sum(
        expected and outcome is EventAssignmentOutcome.ASSIGNED_EXISTING
        for expected, outcome in labels
    )
    false_positive = sum(
        not expected and outcome is EventAssignmentOutcome.ASSIGNED_EXISTING
        for expected, outcome in labels
    )
    false_negative = sum(
        expected and outcome is EventAssignmentOutcome.CREATED_NEW for expected, outcome in labels
    )
    reviews = sum(outcome is EventAssignmentOutcome.REVIEW_REQUIRED for _, outcome in labels)
    precision = (
        true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
    )
    recall = (
        true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
    )
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return ClusteringEvaluation(
        precision=precision,
        recall=recall,
        f1=f1,
        review_rate=reviews / len(labels) if labels else 0.0,
        false_merge_count=false_positive,
        sample_count=len(labels),
    )


def _title_tokens(value: str) -> frozenset[str]:
    normalized = value.casefold()
    return frozenset(_TITLE_TOKEN.findall(normalized))


def _jaccard(first: frozenset[object], second: frozenset[object]) -> float:
    if not first and not second:
        return 1.0
    if not first or not second:
        return 0.0
    return len(first & second) / len(first | second)
