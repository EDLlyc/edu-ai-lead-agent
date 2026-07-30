from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Self
from uuid import UUID


class TopicVetoCode(StrEnum):
    UNRESOLVED_GOVERNANCE = "unresolved_governance"
    INELIGIBLE_EVIDENCE = "ineligible_evidence"
    TIER_C_ONLY = "tier_c_only"
    UNVERIFIED = "unverified"
    UNSUITABLE_NEGATIVE_INCIDENT = "unsuitable_negative_incident"
    PRIVACY_LEGAL_SAFETY_UNCERTAIN = "privacy_legal_safety_uncertain"
    PROHIBITED_MARKETING_RISK = "prohibited_marketing_risk"
    REPEATED_WITHIN_WINDOW = "repeated_within_window"
    STALE_EVENT = "stale_event"


class NoTopicCode(StrEnum):
    NO_CANDIDATES = "no_candidates"
    ALL_VETOED = "all_vetoed"
    BELOW_THRESHOLD = "below_threshold"


@dataclass(frozen=True, slots=True)
class TopicScoringConfig:
    version: str = "scoring-v1-preview.1"
    profile: str = "preview"
    veto_rule_version: str = "topic-veto-v1"
    threshold: float = 0.62
    recent_selection_window_days: int = 7
    freshness_window_days: float = 14.0
    source_diversity_cap: int = 4
    source_trust_weight: float = 0.20
    source_diversity_weight: float = 0.10
    ai_relevance_weight: float = 0.20
    parent_relevance_weight: float = 0.20
    freshness_weight: float = 0.15
    communication_potential_weight: float = 0.15
    theme_repetition_penalty: float = 0.15
    controversy_risk_penalty: float = 0.10
    marketing_risk_penalty: float = 0.15
    tie_break_order: tuple[str, ...] = (
        "eligible",
        "total",
        "source_trust",
        "event_time",
        "event_id",
    )

    def __post_init__(self) -> None:
        if not self.version.strip() or len(self.version) > 80:
            raise ValueError("topic scoring version must be non-blank and bounded")
        if not self.profile.strip() or len(self.profile) > 40:
            raise ValueError("topic scoring profile must be non-blank and bounded")
        if not self.veto_rule_version.strip() or len(self.veto_rule_version) > 80:
            raise ValueError("topic veto rule version must be non-blank and bounded")
        if not -1 <= self.threshold <= 1 or not math.isfinite(self.threshold):
            raise ValueError("topic scoring threshold must be finite and in [-1, 1]")
        if self.recent_selection_window_days < 1:
            raise ValueError("recent selection window must be positive")
        if self.freshness_window_days <= 0 or not math.isfinite(self.freshness_window_days):
            raise ValueError("freshness window must be finite and positive")
        if self.source_diversity_cap < 1:
            raise ValueError("source diversity cap must be positive")

        positive_weights = self.positive_weights
        penalty_weights = self.penalty_weights
        if any(
            not 0 <= value <= 1 or not math.isfinite(value) for value in positive_weights.values()
        ):
            raise ValueError("positive topic weights must be finite and in [0, 1]")
        if not math.isclose(sum(positive_weights.values()), 1.0, abs_tol=1e-9):
            raise ValueError("positive topic weights must sum to 1")
        if any(
            not 0 <= value <= 1 or not math.isfinite(value) for value in penalty_weights.values()
        ):
            raise ValueError("topic penalties must be finite and in [0, 1]")
        if self.tie_break_order != (
            "eligible",
            "total",
            "source_trust",
            "event_time",
            "event_id",
        ):
            raise ValueError("unsupported topic tie-break order")

    @property
    def positive_weights(self) -> Mapping[str, float]:
        return MappingProxyType(
            {
                "source_trust": self.source_trust_weight,
                "source_diversity": self.source_diversity_weight,
                "ai_relevance": self.ai_relevance_weight,
                "parent_relevance": self.parent_relevance_weight,
                "freshness": self.freshness_weight,
                "communication_potential": self.communication_potential_weight,
            }
        )

    @property
    def penalty_weights(self) -> Mapping[str, float]:
        return MappingProxyType(
            {
                "theme_repetition": self.theme_repetition_penalty,
                "controversy_risk": self.controversy_risk_penalty,
                "marketing_risk": self.marketing_risk_penalty,
            }
        )

    def as_metadata(self) -> dict[str, object]:
        return {
            "version": self.version,
            "profile": self.profile,
            "veto_rule_version": self.veto_rule_version,
            "threshold": self.threshold,
            "recent_selection_window_days": self.recent_selection_window_days,
            "freshness_window_days": self.freshness_window_days,
            "source_diversity_cap": self.source_diversity_cap,
            "positive_weights": dict(self.positive_weights),
            "penalty_weights": dict(self.penalty_weights),
            "tie_break_order": list(self.tie_break_order),
        }

    @classmethod
    def from_metadata(cls, metadata: Mapping[str, object]) -> Self:
        positive_weights = _metadata_mapping(metadata, "positive_weights")
        penalty_weights = _metadata_mapping(metadata, "penalty_weights")
        tie_break_value = metadata.get("tie_break_order")
        if not isinstance(tie_break_value, (list, tuple)) or not all(
            isinstance(value, str) for value in tie_break_value
        ):
            raise ValueError("topic scoring tie-break metadata is invalid")
        return cls(
            version=_metadata_str(metadata, "version"),
            profile=_metadata_str(metadata, "profile"),
            veto_rule_version=_metadata_str(metadata, "veto_rule_version"),
            threshold=_metadata_float(metadata, "threshold"),
            recent_selection_window_days=_metadata_int(metadata, "recent_selection_window_days"),
            freshness_window_days=_metadata_float(metadata, "freshness_window_days"),
            source_diversity_cap=_metadata_int(metadata, "source_diversity_cap"),
            source_trust_weight=_metadata_float(positive_weights, "source_trust"),
            source_diversity_weight=_metadata_float(positive_weights, "source_diversity"),
            ai_relevance_weight=_metadata_float(positive_weights, "ai_relevance"),
            parent_relevance_weight=_metadata_float(positive_weights, "parent_relevance"),
            freshness_weight=_metadata_float(positive_weights, "freshness"),
            communication_potential_weight=_metadata_float(
                positive_weights, "communication_potential"
            ),
            theme_repetition_penalty=_metadata_float(penalty_weights, "theme_repetition"),
            controversy_risk_penalty=_metadata_float(penalty_weights, "controversy_risk"),
            marketing_risk_penalty=_metadata_float(penalty_weights, "marketing_risk"),
            tie_break_order=tuple(tie_break_value),
        )


@dataclass(frozen=True, slots=True)
class TopicCandidate:
    event_id: UUID
    event_version_id: UUID
    event_time: datetime
    source_trust: float
    source_diversity: int
    ai_relevance: float
    parent_relevance: float
    communication_potential: float
    theme_repetition: float = 0.0
    controversy_risk: float = 0.0
    marketing_risk: float = 0.0
    governance_resolved: bool = True
    has_eligible_evidence: bool = True
    tier_c_only: bool = False
    unverified: bool = False
    unsuitable_negative_incident: bool = False
    privacy_legal_safety_uncertain: bool = False
    prohibited_marketing_risk: bool = False
    days_since_last_selection: int | None = None

    def __post_init__(self) -> None:
        if self.event_time.tzinfo is None:
            raise ValueError("topic event time must be timezone-aware")
        if self.days_since_last_selection is not None and self.days_since_last_selection < 1:
            raise ValueError("days since last selection must be positive")
        if self.source_diversity < 0:
            raise ValueError("source diversity must not be negative")
        bounded_features = (
            self.source_trust,
            self.ai_relevance,
            self.parent_relevance,
            self.communication_potential,
            self.theme_repetition,
            self.controversy_risk,
            self.marketing_risk,
        )
        if any(not 0 <= value <= 1 or not math.isfinite(value) for value in bounded_features):
            raise ValueError("topic candidate features must be finite and in [0, 1]")


@dataclass(frozen=True, slots=True)
class TopicScore:
    event_id: UUID
    event_version_id: UUID
    scoring_version: str
    scoring_profile: str
    raw_features: Mapping[str, float]
    normalized_features: Mapping[str, float]
    weights: Mapping[str, float]
    penalty_weights: Mapping[str, float]
    positive_components: Mapping[str, float]
    penalty_components: Mapping[str, float]
    total: float
    threshold: float
    passes_threshold: bool
    eligible: bool
    veto_codes: tuple[TopicVetoCode, ...]
    rank: int | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw_features", MappingProxyType(dict(self.raw_features)))
        object.__setattr__(
            self,
            "normalized_features",
            MappingProxyType(dict(self.normalized_features)),
        )
        object.__setattr__(self, "weights", MappingProxyType(dict(self.weights)))
        object.__setattr__(
            self,
            "penalty_weights",
            MappingProxyType(dict(self.penalty_weights)),
        )
        object.__setattr__(
            self,
            "positive_components",
            MappingProxyType(dict(self.positive_components)),
        )
        object.__setattr__(
            self,
            "penalty_components",
            MappingProxyType(dict(self.penalty_components)),
        )

    def as_metadata(self) -> dict[str, object]:
        return {
            "event_id": str(self.event_id),
            "event_version_id": str(self.event_version_id),
            "scoring_version": self.scoring_version,
            "scoring_profile": self.scoring_profile,
            "raw_features": dict(self.raw_features),
            "normalized_features": dict(self.normalized_features),
            "weights": dict(self.weights),
            "penalty_weights": dict(self.penalty_weights),
            "positive_components": dict(self.positive_components),
            "penalty_components": dict(self.penalty_components),
            "total": self.total,
            "threshold": self.threshold,
            "passes_threshold": self.passes_threshold,
            "eligible": self.eligible,
            "veto_codes": [code.value for code in self.veto_codes],
            "rank": self.rank,
        }


@dataclass(frozen=True, slots=True)
class DailyTopicDecision:
    scoring_version: str
    scoring_profile: str
    scores: tuple[TopicScore, ...]
    selected_event_id: UUID | None
    selected_event_version_id: UUID | None
    no_topic_code: NoTopicCode | None

    @property
    def is_no_topic(self) -> bool:
        return self.selected_event_id is None


def score_topic_candidate(
    candidate: TopicCandidate,
    *,
    as_of: datetime,
    config: TopicScoringConfig,
) -> TopicScore:
    if as_of.tzinfo is None:
        raise ValueError("topic scoring time must be timezone-aware")

    age_days = max(0.0, (as_of - candidate.event_time).total_seconds() / 86_400)
    normalized_features = {
        "source_trust": candidate.source_trust,
        "source_diversity": min(candidate.source_diversity / config.source_diversity_cap, 1.0),
        "ai_relevance": candidate.ai_relevance,
        "parent_relevance": candidate.parent_relevance,
        "freshness": max(0.0, 1.0 - age_days / config.freshness_window_days),
        "communication_potential": candidate.communication_potential,
        "theme_repetition": candidate.theme_repetition,
        "controversy_risk": candidate.controversy_risk,
        "marketing_risk": candidate.marketing_risk,
    }
    raw_features = {
        "source_trust": candidate.source_trust,
        "source_diversity": float(candidate.source_diversity),
        "ai_relevance": candidate.ai_relevance,
        "parent_relevance": candidate.parent_relevance,
        "freshness_age_days": age_days,
        "communication_potential": candidate.communication_potential,
        "theme_repetition": candidate.theme_repetition,
        "controversy_risk": candidate.controversy_risk,
        "marketing_risk": candidate.marketing_risk,
    }
    if candidate.days_since_last_selection is not None:
        raw_features["days_since_last_selection"] = float(candidate.days_since_last_selection)
    positive_components = {
        name: normalized_features[name] * weight for name, weight in config.positive_weights.items()
    }
    penalty_components = {
        name: normalized_features[name] * weight for name, weight in config.penalty_weights.items()
    }
    total = round(sum(positive_components.values()) - sum(penalty_components.values()), 8)
    veto_codes = _veto_codes(candidate, as_of=as_of, config=config)
    passes_threshold = total >= config.threshold
    return TopicScore(
        event_id=candidate.event_id,
        event_version_id=candidate.event_version_id,
        scoring_version=config.version,
        scoring_profile=config.profile,
        raw_features=raw_features,
        normalized_features=normalized_features,
        weights=config.positive_weights,
        penalty_weights=config.penalty_weights,
        positive_components=positive_components,
        penalty_components=penalty_components,
        total=total,
        threshold=config.threshold,
        passes_threshold=passes_threshold,
        eligible=not veto_codes and passes_threshold,
        veto_codes=veto_codes,
    )


def select_daily_topic(
    candidates: tuple[TopicCandidate, ...],
    *,
    as_of: datetime,
    config: TopicScoringConfig,
) -> DailyTopicDecision:
    scored = tuple(
        score_topic_candidate(candidate, as_of=as_of, config=config) for candidate in candidates
    )
    candidates_by_id = {candidate.event_id: candidate for candidate in candidates}
    ordered = tuple(
        sorted(
            scored,
            key=lambda score: _score_sort_key(score, candidates_by_id[score.event_id]),
        )
    )
    ranked = tuple(replace(score, rank=index) for index, score in enumerate(ordered, start=1))
    selected = next((score for score in ranked if score.eligible), None)
    if selected is not None:
        return DailyTopicDecision(
            scoring_version=config.version,
            scoring_profile=config.profile,
            scores=ranked,
            selected_event_id=selected.event_id,
            selected_event_version_id=selected.event_version_id,
            no_topic_code=None,
        )

    if not ranked:
        no_topic_code = NoTopicCode.NO_CANDIDATES
    elif all(score.veto_codes for score in ranked):
        no_topic_code = NoTopicCode.ALL_VETOED
    else:
        no_topic_code = NoTopicCode.BELOW_THRESHOLD
    return DailyTopicDecision(
        scoring_version=config.version,
        scoring_profile=config.profile,
        scores=ranked,
        selected_event_id=None,
        selected_event_version_id=None,
        no_topic_code=no_topic_code,
    )


def _veto_codes(
    candidate: TopicCandidate,
    *,
    as_of: datetime,
    config: TopicScoringConfig,
) -> tuple[TopicVetoCode, ...]:
    vetoes: list[TopicVetoCode] = []
    if not candidate.governance_resolved:
        vetoes.append(TopicVetoCode.UNRESOLVED_GOVERNANCE)
    if not candidate.has_eligible_evidence:
        vetoes.append(TopicVetoCode.INELIGIBLE_EVIDENCE)
    if candidate.tier_c_only:
        vetoes.append(TopicVetoCode.TIER_C_ONLY)
    if candidate.unverified:
        vetoes.append(TopicVetoCode.UNVERIFIED)
    if candidate.unsuitable_negative_incident:
        vetoes.append(TopicVetoCode.UNSUITABLE_NEGATIVE_INCIDENT)
    if candidate.privacy_legal_safety_uncertain:
        vetoes.append(TopicVetoCode.PRIVACY_LEGAL_SAFETY_UNCERTAIN)
    if candidate.prohibited_marketing_risk:
        vetoes.append(TopicVetoCode.PROHIBITED_MARKETING_RISK)
    if candidate.days_since_last_selection is not None:
        if candidate.days_since_last_selection < config.recent_selection_window_days:
            vetoes.append(TopicVetoCode.REPEATED_WITHIN_WINDOW)
    age_days = (as_of - candidate.event_time).total_seconds() / 86_400
    if age_days > config.freshness_window_days:
        vetoes.append(TopicVetoCode.STALE_EVENT)
    return tuple(vetoes)


def _score_sort_key(
    score: TopicScore, candidate: TopicCandidate
) -> tuple[int, float, float, float, int]:
    if score.eligible:
        eligibility_group = 0
    elif not score.veto_codes:
        eligibility_group = 1
    else:
        eligibility_group = 2
    return (
        eligibility_group,
        -score.total,
        -score.normalized_features["source_trust"],
        -candidate.event_time.timestamp(),
        candidate.event_id.int,
    )


def _metadata_mapping(metadata: Mapping[str, object], key: str) -> Mapping[str, object]:
    value = metadata.get(key)
    if not isinstance(value, Mapping):
        raise ValueError(f"topic scoring {key} metadata is invalid")
    return value


def _metadata_str(metadata: Mapping[str, object], key: str) -> str:
    value = metadata.get(key)
    if not isinstance(value, str):
        raise ValueError(f"topic scoring {key} metadata is invalid")
    return value


def _metadata_float(metadata: Mapping[str, object], key: str) -> float:
    value = metadata.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"topic scoring {key} metadata is invalid")
    return float(value)


def _metadata_int(metadata: Mapping[str, object], key: str) -> int:
    value = metadata.get(key)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"topic scoring {key} metadata is invalid")
    return value
