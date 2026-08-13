from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Self
from uuid import UUID

from app.domain.editorial_relevance import (
    PRODUCT_MATRIX_FIT_RULE_VERSION,
    SCIENCE_AI_EDUCATION_RULE_VERSION,
)
from app.domain.science_policy_priority import (
    SCIENCE_POLICY_PRIORITY_RULE_VERSION,
    evaluate_science_policy_priority,
)

DEFAULT_TOPIC_SCORING_VERSION = "scoring-v1-preview.5-science-education-product-fit"
DEFAULT_SELECTION_PRIORITY_RULE_VERSION: str | None = None
SCIENCE_EDUCATION_VETO_RULE_VERSION = "topic-veto-v2-science-ai-education"
LEGACY_TOPIC_VETO_RULE_VERSION = "topic-veto-v1"
MOE_SCIENCE_TOP1_PRIORITY_POLICY = "moe-science-top1-v1"
SOURCE_PRIORITY_RULE_VERSION = "source-priority-v1"


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
    OUTSIDE_SCIENCE_AI_EDUCATION_SCOPE = "outside_science_ai_education_scope"


class NoTopicCode(StrEnum):
    NO_CANDIDATES = "no_candidates"
    ALL_VETOED = "all_vetoed"
    BELOW_THRESHOLD = "below_threshold"


@dataclass(frozen=True, slots=True)
class TopicScoringConfig:
    version: str = DEFAULT_TOPIC_SCORING_VERSION
    profile: str = "preview"
    veto_rule_version: str | None = None
    selection_priority_rule_version: str | None = DEFAULT_SELECTION_PRIORITY_RULE_VERSION
    threshold: float = 0.62
    recent_selection_window_days: int = 7
    freshness_window_days: float = 10.0
    source_diversity_cap: int = 4
    science_ai_education_rule_version: str | None = None
    product_matrix_fit_rule_version: str | None = None
    source_trust_weight: float = 0.20
    source_diversity_weight: float = 0.10
    ai_relevance_weight: float = 0.20
    parent_relevance_weight: float = 0.20
    freshness_weight: float = 0.15
    communication_potential_weight: float = 0.15
    science_education_relevance_weight: float = 0.30
    product_matrix_fit_weight: float = 0.25
    editorial_source_trust_weight: float = 0.15
    editorial_source_diversity_weight: float = 0.10
    editorial_freshness_weight: float = 0.10
    editorial_communication_potential_weight: float = 0.10
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
        if self.veto_rule_version is not None and (
            not self.veto_rule_version.strip() or len(self.veto_rule_version) > 80
        ):
            raise ValueError("topic veto rule version must be non-blank and bounded")
        if self.selection_priority_rule_version is not None and (
            not self.selection_priority_rule_version.strip()
            or len(self.selection_priority_rule_version) > 80
        ):
            raise ValueError("topic selection priority rule version must be non-blank and bounded")
        explicit_editorial_versions = (
            self.science_ai_education_rule_version,
            self.product_matrix_fit_rule_version,
        )
        if any(explicit_editorial_versions) and not all(explicit_editorial_versions):
            raise ValueError("topic editorial rule versions must be configured together")
        if any(
            value is not None and (not value.strip() or len(value) > 80)
            for value in explicit_editorial_versions
        ):
            raise ValueError("topic editorial rule versions must be non-blank and bounded")
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
        if self.uses_editorial_features:
            return MappingProxyType(
                {
                    "science_education_relevance": (self.science_education_relevance_weight),
                    "product_matrix_fit": self.product_matrix_fit_weight,
                    "source_trust": self.editorial_source_trust_weight,
                    "source_diversity": self.editorial_source_diversity_weight,
                    "freshness": self.editorial_freshness_weight,
                    "communication_potential": (self.editorial_communication_potential_weight),
                }
            )
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
    def uses_editorial_features(self) -> bool:
        return (
            self.version == DEFAULT_TOPIC_SCORING_VERSION
            or self.science_ai_education_rule_version is not None
        )

    @property
    def effective_science_ai_education_rule_version(self) -> str | None:
        if not self.uses_editorial_features:
            return None
        return self.science_ai_education_rule_version or SCIENCE_AI_EDUCATION_RULE_VERSION

    @property
    def effective_product_matrix_fit_rule_version(self) -> str | None:
        if not self.uses_editorial_features:
            return None
        return self.product_matrix_fit_rule_version or PRODUCT_MATRIX_FIT_RULE_VERSION

    @property
    def effective_veto_rule_version(self) -> str:
        if self.veto_rule_version is not None:
            return self.veto_rule_version
        return (
            SCIENCE_EDUCATION_VETO_RULE_VERSION
            if self.uses_editorial_features
            else LEGACY_TOPIC_VETO_RULE_VERSION
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
        metadata: dict[str, object] = {
            "version": self.version,
            "profile": self.profile,
            "veto_rule_version": self.effective_veto_rule_version,
            "threshold": self.threshold,
            "recent_selection_window_days": self.recent_selection_window_days,
            "freshness_window_days": self.freshness_window_days,
            "source_diversity_cap": self.source_diversity_cap,
            "positive_weights": dict(self.positive_weights),
            "penalty_weights": dict(self.penalty_weights),
            "tie_break_order": list(self.tie_break_order),
        }
        if self.selection_priority_rule_version is not None:
            metadata["selection_priority_rule_version"] = self.selection_priority_rule_version
        if self.uses_editorial_features:
            metadata["science_ai_education_rule_version"] = (
                self.effective_science_ai_education_rule_version
            )
            metadata["product_matrix_fit_rule_version"] = (
                self.effective_product_matrix_fit_rule_version
            )
        return metadata

    @classmethod
    def from_metadata(cls, metadata: Mapping[str, object]) -> Self:
        positive_weights = _metadata_mapping(metadata, "positive_weights")
        penalty_weights = _metadata_mapping(metadata, "penalty_weights")
        tie_break_value = metadata.get("tie_break_order")
        if not isinstance(tie_break_value, (list, tuple)) or not all(
            isinstance(value, str) for value in tie_break_value
        ):
            raise ValueError("topic scoring tie-break metadata is invalid")
        editorial_features = "science_education_relevance" in positive_weights
        common: dict[str, Any] = {
            "version": _metadata_str(metadata, "version"),
            "profile": _metadata_str(metadata, "profile"),
            "veto_rule_version": _metadata_str(metadata, "veto_rule_version"),
            "selection_priority_rule_version": _metadata_optional_str(
                metadata, "selection_priority_rule_version"
            ),
            "threshold": _metadata_float(metadata, "threshold"),
            "recent_selection_window_days": _metadata_int(metadata, "recent_selection_window_days"),
            "freshness_window_days": _metadata_float(metadata, "freshness_window_days"),
            "source_diversity_cap": _metadata_int(metadata, "source_diversity_cap"),
            "theme_repetition_penalty": _metadata_float(penalty_weights, "theme_repetition"),
            "controversy_risk_penalty": _metadata_float(penalty_weights, "controversy_risk"),
            "marketing_risk_penalty": _metadata_float(penalty_weights, "marketing_risk"),
            "tie_break_order": tuple(tie_break_value),
        }
        if editorial_features:
            return cls(
                **common,
                science_ai_education_rule_version=_metadata_str(
                    metadata, "science_ai_education_rule_version"
                ),
                product_matrix_fit_rule_version=_metadata_str(
                    metadata, "product_matrix_fit_rule_version"
                ),
                science_education_relevance_weight=_metadata_float(
                    positive_weights, "science_education_relevance"
                ),
                product_matrix_fit_weight=_metadata_float(positive_weights, "product_matrix_fit"),
                editorial_source_trust_weight=_metadata_float(positive_weights, "source_trust"),
                editorial_source_diversity_weight=_metadata_float(
                    positive_weights, "source_diversity"
                ),
                editorial_freshness_weight=_metadata_float(positive_weights, "freshness"),
                editorial_communication_potential_weight=_metadata_float(
                    positive_weights, "communication_potential"
                ),
            )
        return cls(
            **common,
            source_trust_weight=_metadata_float(positive_weights, "source_trust"),
            source_diversity_weight=_metadata_float(positive_weights, "source_diversity"),
            ai_relevance_weight=_metadata_float(positive_weights, "ai_relevance"),
            parent_relevance_weight=_metadata_float(positive_weights, "parent_relevance"),
            freshness_weight=_metadata_float(positive_weights, "freshness"),
            communication_potential_weight=_metadata_float(
                positive_weights, "communication_potential"
            ),
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
    science_education_relevance: float = 0.0
    science_ai_education_eligible: bool = False
    science_ai_education_reason_codes: tuple[str, ...] = ()
    product_matrix_fit: float = 0.0
    product_matrix_direction_ids: tuple[str, ...] = ()
    topic_priority_policy: str | None = None
    priority_title: str = ""
    priority_summary: str = ""
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
        if self.topic_priority_policy is not None and (
            not self.topic_priority_policy.strip() or len(self.topic_priority_policy) > 80
        ):
            raise ValueError("topic priority policy must be non-blank and bounded")
        if self.days_since_last_selection is not None and self.days_since_last_selection < 1:
            raise ValueError("days since last selection must be positive")
        if self.source_diversity < 0:
            raise ValueError("source diversity must not be negative")
        bounded_features = (
            self.source_trust,
            self.ai_relevance,
            self.parent_relevance,
            self.communication_potential,
            self.science_education_relevance,
            self.product_matrix_fit,
            self.theme_repetition,
            self.controversy_risk,
            self.marketing_risk,
        )
        if any(not 0 <= value <= 1 or not math.isfinite(value) for value in bounded_features):
            raise ValueError("topic candidate features must be finite and in [0, 1]")
        if any(
            not value.strip() or len(value) > 80 for value in self.science_ai_education_reason_codes
        ):
            raise ValueError("topic relevance reason codes must be non-blank and bounded")
        if any(
            not value.strip() or len(value) > 100 for value in self.product_matrix_direction_ids
        ):
            raise ValueError("topic product directions must be non-blank and bounded")


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
    selection_priority_rule_version: str | None = None
    topic_priority_policy: str | None = None
    priority_applied: bool = False
    priority_reason: str = "not_eligible"
    science_ai_education_rule_version: str | None = None
    product_matrix_fit_rule_version: str | None = None
    science_ai_education_reason_codes: tuple[str, ...] = ()
    product_matrix_direction_ids: tuple[str, ...] = ()
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
            "selection_priority_rule_version": self.selection_priority_rule_version,
            "topic_priority_policy": self.topic_priority_policy,
            "priority_applied": self.priority_applied,
            "priority_reason": self.priority_reason,
            "science_ai_education_rule_version": self.science_ai_education_rule_version,
            "product_matrix_fit_rule_version": self.product_matrix_fit_rule_version,
            "science_ai_education_reason_codes": list(self.science_ai_education_reason_codes),
            "product_matrix_direction_ids": list(self.product_matrix_direction_ids),
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
    common_normalized_features = {
        "source_trust": candidate.source_trust,
        "source_diversity": min(candidate.source_diversity / config.source_diversity_cap, 1.0),
        "freshness": max(0.0, 1.0 - age_days / config.freshness_window_days),
        "communication_potential": candidate.communication_potential,
        "theme_repetition": candidate.theme_repetition,
        "controversy_risk": candidate.controversy_risk,
        "marketing_risk": candidate.marketing_risk,
    }
    common_raw_features = {
        "source_trust": candidate.source_trust,
        "source_diversity": float(candidate.source_diversity),
        "freshness_age_days": age_days,
        "communication_potential": candidate.communication_potential,
        "theme_repetition": candidate.theme_repetition,
        "controversy_risk": candidate.controversy_risk,
        "marketing_risk": candidate.marketing_risk,
    }
    if config.uses_editorial_features:
        normalized_features = {
            **common_normalized_features,
            "science_education_relevance": candidate.science_education_relevance,
            "product_matrix_fit": candidate.product_matrix_fit,
        }
        raw_features = {
            **common_raw_features,
            "science_education_relevance": candidate.science_education_relevance,
            "product_matrix_fit": candidate.product_matrix_fit,
        }
    else:
        normalized_features = {
            **common_normalized_features,
            "ai_relevance": candidate.ai_relevance,
            "parent_relevance": candidate.parent_relevance,
        }
        raw_features = {
            **common_raw_features,
            "ai_relevance": candidate.ai_relevance,
            "parent_relevance": candidate.parent_relevance,
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
    priority_applied, priority_reason = _priority_state(
        candidate,
        veto_codes=veto_codes,
        passes_threshold=passes_threshold,
        config=config,
    )
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
        selection_priority_rule_version=config.selection_priority_rule_version,
        topic_priority_policy=candidate.topic_priority_policy,
        priority_applied=priority_applied,
        priority_reason=priority_reason,
        science_ai_education_rule_version=(config.effective_science_ai_education_rule_version),
        product_matrix_fit_rule_version=config.effective_product_matrix_fit_rule_version,
        science_ai_education_reason_codes=(
            candidate.science_ai_education_reason_codes if config.uses_editorial_features else ()
        ),
        product_matrix_direction_ids=(
            candidate.product_matrix_direction_ids if config.uses_editorial_features else ()
        ),
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
    if config.uses_editorial_features and not candidate.science_ai_education_eligible:
        vetoes.append(TopicVetoCode.OUTSIDE_SCIENCE_AI_EDUCATION_SCOPE)
    return tuple(vetoes)


def _score_sort_key(
    score: TopicScore, candidate: TopicCandidate
) -> tuple[int, float, float, float, int]:
    if score.priority_applied:
        eligibility_group = 0
    elif score.eligible:
        eligibility_group = 1
    elif not score.veto_codes:
        eligibility_group = 2
    else:
        eligibility_group = 3
    return (
        eligibility_group,
        -score.total,
        -score.normalized_features["source_trust"],
        -candidate.event_time.timestamp(),
        candidate.event_id.int,
    )


def _priority_state(
    candidate: TopicCandidate,
    *,
    veto_codes: tuple[TopicVetoCode, ...],
    passes_threshold: bool,
    config: TopicScoringConfig,
) -> tuple[bool, str]:
    if config.selection_priority_rule_version is None:
        return (
            False,
            "source_priority_disabled_for_config"
            if config.uses_editorial_features
            else "selection_priority_rule_unavailable",
        )
    if config.selection_priority_rule_version not in {
        SOURCE_PRIORITY_RULE_VERSION,
        SCIENCE_POLICY_PRIORITY_RULE_VERSION,
    }:
        return False, "unsupported_selection_priority_rule"
    if candidate.topic_priority_policy is None:
        return False, "no_topic_priority_policy"
    if candidate.topic_priority_policy != MOE_SCIENCE_TOP1_PRIORITY_POLICY:
        return False, "unsupported_topic_priority_policy"
    if veto_codes:
        return False, "hard_veto"
    if not passes_threshold:
        return False, "below_threshold"
    if config.selection_priority_rule_version == SOURCE_PRIORITY_RULE_VERSION:
        return True, "eligible_official_ministry_science_source"

    science_policy = evaluate_science_policy_priority(
        candidate.priority_title,
        candidate.priority_summary,
    )
    return science_policy.is_eligible, science_policy.reason_code


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


def _metadata_optional_str(metadata: Mapping[str, object], key: str) -> str | None:
    value = metadata.get(key)
    if value is None:
        return None
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
