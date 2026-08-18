from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from enum import StrEnum
from typing import Literal
from uuid import UUID
from zoneinfo import ZoneInfo

from app.domain.editorial_relevance import ScienceTechEditorialCohort
from app.domain.topic_selection import (
    TopicCandidate,
    TopicScore,
    TopicScoringConfig,
    score_topic_candidate,
)

CONTENT_SLOT_SCHEDULE_POLICY_VERSION = "content-slot-schedule-v1"
DEFAULT_SLOT_RANKING_VERSION: Literal["slot-ranking-v1"] = "slot-ranking-v1"


class ContentSlot(StrEnum):
    MORNING = "morning"
    NOON = "noon"
    EVENING = "evening"

    @property
    def display_name(self) -> str:
        return {
            ContentSlot.MORNING: "科教晨报",
            ContentSlot.NOON: "午间观察",
            ContentSlot.EVENING: "晚间精选",
        }[self]

    @property
    def order(self) -> int:
        return {
            ContentSlot.MORNING: 1,
            ContentSlot.NOON: 2,
            ContentSlot.EVENING: 3,
        }[self]


@dataclass(frozen=True, slots=True)
class ContentSlotSchedule:
    slot: ContentSlot
    enabled: bool
    target_hour: int
    target_minute: int
    prepare_lead_minutes: int = 90
    delivery_late_minutes: int = 60
    max_items: int = 3
    policy_version: str = CONTENT_SLOT_SCHEDULE_POLICY_VERSION

    def __post_init__(self) -> None:
        if not 0 <= self.target_hour <= 23:
            raise ValueError("content slot target hour must be in [0, 23]")
        if not 0 <= self.target_minute <= 59:
            raise ValueError("content slot target minute must be in [0, 59]")
        if not 30 <= self.prepare_lead_minutes <= 180:
            raise ValueError("content slot preparation lead must be in [30, 180] minutes")
        if not 0 <= self.delivery_late_minutes <= 120:
            raise ValueError("content slot delivery lateness must be in [0, 120] minutes")
        if not 1 <= self.max_items <= 3:
            raise ValueError("content slot maximum items must be in [1, 3]")
        if not self.policy_version.strip() or len(self.policy_version) > 80:
            raise ValueError("content slot schedule policy version must be non-blank and bounded")

    @property
    def display_name(self) -> str:
        return self.slot.display_name

    def instants(self, business_date: date, timezone: str) -> ContentSlotInstants:
        zone = ZoneInfo(timezone)
        target = datetime(
            business_date.year,
            business_date.month,
            business_date.day,
            self.target_hour,
            self.target_minute,
            tzinfo=zone,
        )
        return ContentSlotInstants(
            preparation_at=target - timedelta(minutes=self.prepare_lead_minutes),
            target_at=target,
            expires_at=target + timedelta(minutes=self.delivery_late_minutes),
        )

    def as_metadata(self) -> dict[str, object]:
        return {
            "policy_version": self.policy_version,
            "slot": self.slot.value,
            "display_name": self.display_name,
            "target_hour": self.target_hour,
            "target_minute": self.target_minute,
            "prepare_lead_minutes": self.prepare_lead_minutes,
            "delivery_late_minutes": self.delivery_late_minutes,
            "max_items": self.max_items,
        }


@dataclass(frozen=True, slots=True)
class ContentSlotInstants:
    preparation_at: datetime
    target_at: datetime
    expires_at: datetime

    def __post_init__(self) -> None:
        if any(
            value.tzinfo is None for value in (self.preparation_at, self.target_at, self.expires_at)
        ):
            raise ValueError("content slot instants must be timezone-aware")
        if not self.preparation_at < self.target_at <= self.expires_at:
            raise ValueError("content slot instants must be ordered")


def due_content_slot_business_date(
    now: datetime,
    *,
    timezone: str,
    schedule: ContentSlotSchedule,
    catchup_hours: int,
) -> date | None:
    if now.tzinfo is None:
        raise ValueError("content slot reconciliation time must be timezone-aware")
    if catchup_hours < 1:
        raise ValueError("content slot catch-up hours must be positive")
    local_now = now.astimezone(ZoneInfo(timezone))
    # A bounded target can legitimately prepare on the previous calendar day
    # (for example 00:30 with a 90-minute lead). Inspect today and tomorrow so
    # the modulo-24 cron still resolves the intended target business date.
    for business_date in (local_now.date(), local_now.date() + timedelta(days=1)):
        instants = schedule.instants(business_date, timezone)
        catchup_until = min(
            instants.expires_at,
            instants.preparation_at + timedelta(hours=catchup_hours),
        )
        if instants.preparation_at <= local_now <= catchup_until:
            return business_date
    return None


@dataclass(frozen=True, slots=True)
class SlotRankingPolicy:
    version: str = DEFAULT_SLOT_RANKING_VERSION
    maximum_affinity: float = 0.12

    def __post_init__(self) -> None:
        if self.version != DEFAULT_SLOT_RANKING_VERSION:
            raise ValueError("unsupported content slot ranking policy")
        if not 0 <= self.maximum_affinity <= 0.25 or not math.isfinite(self.maximum_affinity):
            raise ValueError("content slot affinity bound is invalid")

    def as_metadata(self) -> dict[str, object]:
        return {
            "version": self.version,
            "maximum_affinity": self.maximum_affinity,
            "signal_source": "stored_governed_editorial_and_product_projections",
            "eligibility_effect": "none",
        }

    @property
    def fingerprint(self) -> str:
        payload = json.dumps(
            self.as_metadata(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
        return hashlib.sha256(payload).hexdigest()


class SlotUnfilledReason(StrEnum):
    NO_CANDIDATES = "no_candidates"
    ALL_VETOED = "all_vetoed"
    BELOW_THRESHOLD = "below_threshold"
    SAME_DAY_ALREADY_SELECTED = "same_day_already_selected"
    INSUFFICIENT_ELIGIBLE_CANDIDATES = "insufficient_eligible_candidates"


@dataclass(frozen=True, slots=True)
class ContentSlotScore:
    base: TopicScore
    slot: ContentSlot
    affinity: float
    affinity_reasons: tuple[str, ...]
    same_day_excluded: bool
    same_day_exclusion_reason: str | None
    ordering_value: float
    final_ordering_key: str
    rank: int | None = None
    deterministic_rank: int | None = None
    selected_ordinal: int | None = None
    rerank_reason_codes: tuple[str, ...] = ()
    rerank_explanation: str | None = None

    def __post_init__(self) -> None:
        if not 0 <= self.affinity <= 0.25 or not math.isfinite(self.affinity):
            raise ValueError("content slot affinity must be finite and bounded")
        if self.same_day_excluded != (self.same_day_exclusion_reason is not None):
            raise ValueError("content slot exclusion state is inconsistent")
        if not math.isfinite(self.ordering_value):
            raise ValueError("content slot ordering value must be finite")


@dataclass(frozen=True, slots=True)
class ContentSlotDecision:
    slot: ContentSlot
    scoring_version: str
    scoring_profile: str
    ranking_policy_version: str
    scores: tuple[ContentSlotScore, ...]
    selected_event_ids: tuple[UUID, ...]
    selected_event_version_ids: tuple[UUID, ...]
    unfilled_count: int
    unfilled_reason_codes: tuple[SlotUnfilledReason, ...]


_NOON_PRODUCT_DIRECTIONS = frozenset(
    {
        "science_exploration_courses_and_camps",
        "ai_theme_robotics_agent_safety_math_3d_hackathon",
        "competition_innovation_talent_pathway",
    }
)
_EVENING_FRONTIER_DIRECTIONS = frozenset(
    {
        "ai_theme_robotics_agent_safety_math_3d_hackathon",
        "competition_innovation_talent_pathway",
    }
)


def slot_affinity(
    candidate: TopicCandidate,
    base_score: TopicScore,
    *,
    slot: ContentSlot,
    policy: SlotRankingPolicy,
) -> tuple[float, tuple[str, ...]]:
    """Derive a bounded ordering-only preference from stored governed projections."""

    signals: list[tuple[str, float]] = []
    reasons = set(candidate.science_tech_editorial_reason_codes)
    directions = set(candidate.product_matrix_v2_direction_ids)
    education_cohort = candidate.science_tech_editorial_cohort in {
        ScienceTechEditorialCohort.SCIENCE_TECHNOLOGY_EDUCATION_PRIORITY,
    }
    if slot is ContentSlot.MORNING:
        if base_score.priority_applied:
            signals.append(("authenticated_ministry_education_priority", 0.12))
        elif education_cohort:
            signals.append(("education_policy_or_science_education", 0.09))
        if reasons & {
            "explicit_science_technology_education",
            "science_ai_topic_with_education_context",
        }:
            signals.append(("stored_education_reason", 0.03))
    elif slot is ContentSlot.NOON:
        if directions & _NOON_PRODUCT_DIRECTIONS:
            signals.append(("school_practice_or_pathway_direction", 0.09))
        if education_cohort:
            signals.append(("education_practice_context", 0.04))
    else:
        if (
            candidate.science_tech_editorial_cohort
            is ScienceTechEditorialCohort.FRONTIER_SCIENCE_TECHNOLOGY
        ):
            signals.append(("frontier_advance", 0.09))
        if directions & _EVENING_FRONTIER_DIRECTIONS:
            signals.append(("robotics_or_frontier_product_direction", 0.05))
        if candidate.frontier_significance >= 0.7:
            signals.append(("high_frontier_significance", 0.03))
    affinity = min(policy.maximum_affinity, round(sum(value for _, value in signals), 8))
    return affinity, tuple(reason for reason, _ in signals)


def select_slot_topics(
    candidates: tuple[TopicCandidate, ...],
    *,
    as_of: datetime,
    config: TopicScoringConfig,
    slot: ContentSlot,
    policy: SlotRankingPolicy,
    max_items: int,
    same_day_selected_event_ids: frozenset[UUID] = frozenset(),
) -> ContentSlotDecision:
    if not 1 <= max_items <= 3:
        raise ValueError("content slot selection limit must be in [1, 3]")
    candidates_by_id = {candidate.event_id: candidate for candidate in candidates}
    if len(candidates_by_id) != len(candidates):
        raise ValueError("content slot candidates must have unique event IDs")

    scored: list[ContentSlotScore] = []
    for candidate in candidates:
        base = score_topic_candidate(candidate, as_of=as_of, config=config)
        affinity, affinity_reasons = slot_affinity(
            candidate,
            base,
            slot=slot,
            policy=policy,
        )
        excluded = candidate.event_id in same_day_selected_event_ids
        ordering_value = round(base.total + affinity, 8)
        base_group = (
            0
            if base.priority_applied and not excluded
            else 1
            if base.eligible and not excluded
            else 2
            if excluded
            else 3
            if not base.veto_codes
            else 4
        )
        final_key = (
            f"{base_group}:"
            f"{-ordering_value:.8f}:{-base.total:.8f}:"
            f"{-base.normalized_features['source_trust']:.8f}:"
            f"{-candidate.event_time.timestamp():.6f}:{candidate.event_id}"
        )
        scored.append(
            ContentSlotScore(
                base=base,
                slot=slot,
                affinity=affinity,
                affinity_reasons=affinity_reasons,
                same_day_excluded=excluded,
                same_day_exclusion_reason=("same_day_already_selected" if excluded else None),
                ordering_value=ordering_value,
                final_ordering_key=final_key,
            )
        )

    def ordering_key(score: ContentSlotScore) -> tuple[int, float, float, float, float, int]:
        candidate = candidates_by_id[score.base.event_id]
        group = (
            0
            if score.base.priority_applied and not score.same_day_excluded
            else 1
            if score.base.eligible and not score.same_day_excluded
            else 2
            if score.same_day_excluded
            else 3
            if not score.base.veto_codes
            else 4
        )
        return (
            group,
            -score.ordering_value,
            -score.base.total,
            -score.base.normalized_features["source_trust"],
            -candidate.event_time.timestamp(),
            candidate.event_id.int,
        )

    ordered = sorted(scored, key=ordering_key)
    selected_indexes = [
        index
        for index, score in enumerate(ordered)
        if score.base.eligible and not score.same_day_excluded
    ][:max_items]
    ordinal_by_index = {index: ordinal for ordinal, index in enumerate(selected_indexes, start=1)}
    ranked = tuple(
        replace(
            score,
            rank=index + 1,
            deterministic_rank=index + 1,
            selected_ordinal=ordinal_by_index.get(index),
        )
        for index, score in enumerate(ordered)
    )
    selected = tuple(score for score in ranked if score.selected_ordinal is not None)
    unfilled_count = max_items - len(selected)
    unfilled_reasons: list[SlotUnfilledReason] = []
    if unfilled_count:
        if not ranked:
            unfilled_reasons.append(SlotUnfilledReason.NO_CANDIDATES)
        else:
            if any(score.same_day_excluded for score in ranked):
                unfilled_reasons.append(SlotUnfilledReason.SAME_DAY_ALREADY_SELECTED)
            if all(score.base.veto_codes for score in ranked):
                unfilled_reasons.append(SlotUnfilledReason.ALL_VETOED)
            elif not any(score.base.eligible for score in ranked):
                unfilled_reasons.append(SlotUnfilledReason.BELOW_THRESHOLD)
            elif len(selected) < max_items:
                unfilled_reasons.append(SlotUnfilledReason.INSUFFICIENT_ELIGIBLE_CANDIDATES)
    return ContentSlotDecision(
        slot=slot,
        scoring_version=config.version,
        scoring_profile=config.profile,
        ranking_policy_version=policy.version,
        scores=ranked,
        selected_event_ids=tuple(score.base.event_id for score in selected),
        selected_event_version_ids=tuple(score.base.event_version_id for score in selected),
        unfilled_count=unfilled_count,
        unfilled_reason_codes=tuple(dict.fromkeys(unfilled_reasons)),
    )
