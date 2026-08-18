from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any, Self
from uuid import UUID

from app.domain.content_slots import ContentSlotDecision, ContentSlotScore
from app.domain.topic_selection import DailyTopicDecision, TopicCandidate, TopicScore

DEFAULT_TOPIC_RERANK_POLICY_VERSION = "topic-rerank-v1"
DEFAULT_TOPIC_RERANK_CANDIDATE_LIMIT = 8
DEFAULT_TOPIC_RERANK_MAX_OUTPUT_TOKENS = 1_024
TOPIC_RERANK_FALLBACK_POLICY = "deterministic_base_order"
TOPIC_RERANK_REASON_CODES = frozenset(
    {
        "communication_value",
        "information_gain",
        "timeliness",
        "audience_relevance",
        "column_fit",
        "insight_potential",
        "topic_diversity",
    }
)


class TopicRerankOutcomeKind(StrEnum):
    APPLIED = "applied"
    SKIPPED = "skipped"
    FALLBACK = "fallback"


class TopicRerankFailureCode(StrEnum):
    PROVIDER_INPUT_LIMIT = "provider_input_limit"
    PROVIDER_AUTHENTICATION_FAILED = "provider_authentication_failed"
    PROVIDER_REQUEST_REJECTED = "provider_request_rejected"
    PROVIDER_RATE_LIMITED = "provider_rate_limited"
    PROVIDER_TIMEOUT = "provider_timeout"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PROVIDER_IDENTITY_MISMATCH = "provider_identity_mismatch"
    INVALID_PROVIDER_OUTPUT = "invalid_provider_output"
    INVALID_PERMUTATION = "invalid_permutation"
    PRIORITY_BARRIER_VIOLATION = "priority_barrier_violation"
    PROVIDER_ERROR = "provider_error"


@dataclass(frozen=True, slots=True)
class TopicRerankConfig:
    enabled: bool = False
    policy_version: str = DEFAULT_TOPIC_RERANK_POLICY_VERSION
    candidate_limit: int = DEFAULT_TOPIC_RERANK_CANDIDATE_LIMIT
    provider: str = "disabled"
    model: str = "none"
    temperature: float = 0.0
    max_output_tokens: int = DEFAULT_TOPIC_RERANK_MAX_OUTPUT_TOKENS
    fallback_policy: str = TOPIC_RERANK_FALLBACK_POLICY

    def __post_init__(self) -> None:
        if not self.policy_version.strip() or len(self.policy_version) > 80:
            raise ValueError("topic rerank policy version must be non-blank and bounded")
        if not 1 <= self.candidate_limit <= DEFAULT_TOPIC_RERANK_CANDIDATE_LIMIT:
            raise ValueError("topic rerank candidate limit must be in [1, 8]")
        if self.provider not in {"disabled", "fake", "zhipu"}:
            raise ValueError("unsupported topic rerank provider")
        if (
            not self.model.strip()
            or len(self.model) > 120
            or any(character.isspace() for character in self.model)
        ):
            raise ValueError("topic rerank model must be a bounded identifier")
        if self.temperature != 0.0 or not math.isfinite(self.temperature):
            raise ValueError("topic rerank temperature must remain zero")
        if not 128 <= self.max_output_tokens <= 4_096:
            raise ValueError("topic rerank output limit must be in [128, 4096]")
        if self.fallback_policy != TOPIC_RERANK_FALLBACK_POLICY:
            raise ValueError("unsupported topic rerank fallback policy")
        if self.enabled and self.provider not in {"fake", "zhipu"}:
            raise ValueError("enabled topic rerank requires fake or zhipu provider")
        if not self.enabled and self.provider != "disabled":
            raise ValueError("disabled topic rerank must use the disabled provider")

    def as_metadata(self) -> dict[str, object]:
        return {
            "enabled": self.enabled,
            "policy_version": self.policy_version,
            "candidate_limit": self.candidate_limit,
            "provider": self.provider,
            "model": self.model,
            "temperature": self.temperature,
            "max_output_tokens": self.max_output_tokens,
            "fallback_policy": self.fallback_policy,
        }

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.as_metadata())

    @classmethod
    def from_metadata(cls, metadata: dict[str, Any]) -> Self:
        expected = {
            "enabled",
            "policy_version",
            "candidate_limit",
            "provider",
            "model",
            "temperature",
            "max_output_tokens",
            "fallback_policy",
        }
        if set(metadata) != expected:
            raise ValueError("topic rerank config snapshot fields are invalid")
        enabled = metadata["enabled"]
        candidate_limit = metadata["candidate_limit"]
        max_output_tokens = metadata["max_output_tokens"]
        temperature = metadata["temperature"]
        if not isinstance(enabled, bool):
            raise ValueError("topic rerank enabled snapshot is invalid")
        if not isinstance(candidate_limit, int) or isinstance(candidate_limit, bool):
            raise ValueError("topic rerank candidate limit snapshot is invalid")
        if not isinstance(max_output_tokens, int) or isinstance(max_output_tokens, bool):
            raise ValueError("topic rerank output limit snapshot is invalid")
        if not isinstance(temperature, (int, float)) or isinstance(temperature, bool):
            raise ValueError("topic rerank temperature snapshot is invalid")
        strings = {
            key: metadata[key] for key in ("policy_version", "provider", "model", "fallback_policy")
        }
        if any(not isinstance(value, str) for value in strings.values()):
            raise ValueError("topic rerank string snapshot fields are invalid")
        return cls(
            enabled=enabled,
            policy_version=strings["policy_version"],
            candidate_limit=candidate_limit,
            provider=strings["provider"],
            model=strings["model"],
            temperature=float(temperature),
            max_output_tokens=max_output_tokens,
            fallback_policy=strings["fallback_policy"],
        )


@dataclass(frozen=True, slots=True)
class TopicRerankCandidate:
    event_id: UUID
    event_version_id: UUID
    deterministic_rank: int
    priority_group: int
    title: str
    summary: str
    event_time: datetime
    rule_total: float
    source_trust: float
    communication_potential: float
    editorial_priority: float
    education_relevance: float
    frontier_significance: float
    product_fit: float
    editorial_reason_codes: tuple[str, ...]
    product_direction_ids: tuple[str, ...]
    controversy_risk: float
    marketing_risk: float
    context: str
    slot_affinity: float | None = None
    slot_affinity_reasons: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if self.deterministic_rank < 1:
            raise ValueError("topic rerank deterministic rank must be positive")
        if self.priority_group not in {0, 1}:
            raise ValueError("topic rerank priority group must be 0 or 1")
        if not self.title.strip() or len(self.title) > 300:
            raise ValueError("topic rerank title must be non-blank and bounded")
        if len(self.summary) > 1_000:
            raise ValueError("topic rerank summary must be bounded")
        if self.event_time.tzinfo is None:
            raise ValueError("topic rerank event time must be timezone-aware")
        if self.context not in {"daily", "morning", "noon", "evening"}:
            raise ValueError("topic rerank context is invalid")
        bounded = (
            self.rule_total,
            self.source_trust,
            self.communication_potential,
            self.editorial_priority,
            self.education_relevance,
            self.frontier_significance,
            self.product_fit,
            self.controversy_risk,
            self.marketing_risk,
        )
        if any(not -1 <= value <= 1 or not math.isfinite(value) for value in bounded):
            raise ValueError("topic rerank numeric projections must be finite and bounded")
        if self.slot_affinity is not None and (
            not 0 <= self.slot_affinity <= 0.25 or not math.isfinite(self.slot_affinity)
        ):
            raise ValueError("topic rerank slot affinity must be finite and bounded")
        if any(not value.strip() or len(value) > 100 for value in self.editorial_reason_codes):
            raise ValueError("topic rerank editorial reasons must be bounded")
        if any(not value.strip() or len(value) > 100 for value in self.product_direction_ids):
            raise ValueError("topic rerank product directions must be bounded")
        if any(not value.strip() or len(value) > 100 for value in self.slot_affinity_reasons):
            raise ValueError("topic rerank slot affinity reasons must be bounded")

    def as_metadata(self) -> dict[str, object]:
        return {
            "event_id": str(self.event_id),
            "event_version_id": str(self.event_version_id),
            "deterministic_rank": self.deterministic_rank,
            "priority_group": self.priority_group,
            "title": self.title,
            "summary": self.summary,
            "event_time": self.event_time.isoformat(),
            "rule_total": self.rule_total,
            "source_trust": self.source_trust,
            "communication_potential": self.communication_potential,
            "editorial_priority": self.editorial_priority,
            "education_relevance": self.education_relevance,
            "frontier_significance": self.frontier_significance,
            "product_fit": self.product_fit,
            "editorial_reason_codes": list(self.editorial_reason_codes),
            "product_direction_ids": list(self.product_direction_ids),
            "controversy_risk": self.controversy_risk,
            "marketing_risk": self.marketing_risk,
            "context": self.context,
            "slot_affinity": self.slot_affinity,
            "slot_affinity_reasons": list(self.slot_affinity_reasons),
        }


@dataclass(frozen=True, slots=True)
class TopicRerankRequest:
    run_id: UUID
    cutoff_at: datetime
    context: str
    policy_version: str
    max_output_tokens: int
    candidates: tuple[TopicRerankCandidate, ...]

    def __post_init__(self) -> None:
        if self.cutoff_at.tzinfo is None:
            raise ValueError("topic rerank cutoff must be timezone-aware")
        if self.context not in {"daily", "morning", "noon", "evening"}:
            raise ValueError("topic rerank request context is invalid")
        if not self.policy_version.strip() or len(self.policy_version) > 80:
            raise ValueError("topic rerank request policy must be bounded")
        if not 128 <= self.max_output_tokens <= 4_096:
            raise ValueError("topic rerank request output limit is invalid")
        if not 1 <= len(self.candidates) <= DEFAULT_TOPIC_RERANK_CANDIDATE_LIMIT:
            raise ValueError("topic rerank request requires 1 to 8 candidates")
        ids = tuple(candidate.event_id for candidate in self.candidates)
        if len(ids) != len(set(ids)):
            raise ValueError("topic rerank request candidate IDs must be unique")
        if tuple(candidate.deterministic_rank for candidate in self.candidates) != tuple(
            sorted(candidate.deterministic_rank for candidate in self.candidates)
        ):
            raise ValueError("topic rerank candidates must preserve deterministic order")
        groups = tuple(candidate.priority_group for candidate in self.candidates)
        if groups != tuple(sorted(groups)):
            raise ValueError("topic rerank candidates must preserve priority barriers")

    def as_metadata(self) -> dict[str, object]:
        return {
            "run_id": str(self.run_id),
            "cutoff_at": self.cutoff_at.isoformat(),
            "context": self.context,
            "policy_version": self.policy_version,
            "max_output_tokens": self.max_output_tokens,
            "candidates": [candidate.as_metadata() for candidate in self.candidates],
        }

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.as_metadata())


@dataclass(frozen=True, slots=True)
class TopicRerankItem:
    event_id: UUID
    ordinal: int
    reason_codes: tuple[str, ...]
    explanation: str

    def __post_init__(self) -> None:
        if self.ordinal < 1:
            raise ValueError("topic rerank ordinal must be positive")
        if not 1 <= len(self.reason_codes) <= 3 or len(set(self.reason_codes)) != len(
            self.reason_codes
        ):
            raise ValueError("topic rerank requires 1 to 3 unique reason codes")
        if any(code not in TOPIC_RERANK_REASON_CODES for code in self.reason_codes):
            raise ValueError("topic rerank reason code is not allowlisted")
        if not self.explanation.strip() or len(self.explanation) > 160:
            raise ValueError("topic rerank explanation must be non-blank and bounded")


@dataclass(frozen=True, slots=True)
class TopicRerankModelResult:
    items: tuple[TopicRerankItem, ...]
    provider: str
    model: str
    prompt_fingerprint: str
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int
    latency_ms: int

    def __post_init__(self) -> None:
        if not self.provider.strip() or len(self.provider) > 40:
            raise ValueError("topic rerank result provider must be bounded")
        if not self.model.strip() or len(self.model) > 120:
            raise ValueError("topic rerank result model must be bounded")
        if len(self.prompt_fingerprint) != 64 or any(
            character not in "0123456789abcdef" for character in self.prompt_fingerprint
        ):
            raise ValueError("topic rerank prompt fingerprint must be SHA-256")
        if (
            min(
                self.prompt_tokens,
                self.completion_tokens,
                self.reasoning_tokens,
                self.latency_ms,
            )
            < 0
        ):
            raise ValueError("topic rerank usage and latency must be non-negative")


@dataclass(frozen=True, slots=True)
class TopicRerankOutcome:
    kind: TopicRerankOutcomeKind
    policy_version: str
    provider: str
    model: str
    candidate_count: int
    base_order: tuple[UUID, ...]
    final_order: tuple[UUID, ...]
    items: tuple[TopicRerankItem, ...] = ()
    failure_code: TopicRerankFailureCode | None = None
    request_fingerprint: str | None = None
    prompt_fingerprint: str | None = None
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    latency_ms: int = 0

    def __post_init__(self) -> None:
        if self.candidate_count < 0 or self.candidate_count > DEFAULT_TOPIC_RERANK_CANDIDATE_LIMIT:
            raise ValueError("topic rerank outcome candidate count is invalid")
        if self.candidate_count != len(self.base_order) or len(self.final_order) != len(
            self.base_order
        ):
            raise ValueError("topic rerank outcome orders do not match candidate count")
        if len(set(self.base_order)) != self.candidate_count:
            raise ValueError("topic rerank outcome orders require unique IDs")
        if set(self.base_order) != set(self.final_order):
            raise ValueError("topic rerank outcome orders must contain the same IDs")
        if self.kind is TopicRerankOutcomeKind.APPLIED and self.failure_code is not None:
            raise ValueError("applied topic rerank cannot have a failure code")
        if self.kind is TopicRerankOutcomeKind.FALLBACK and self.failure_code is None:
            raise ValueError("fallback topic rerank requires a failure code")
        if self.kind is TopicRerankOutcomeKind.SKIPPED and self.failure_code is not None:
            raise ValueError("skipped topic rerank cannot have a failure code")
        if self.kind is not TopicRerankOutcomeKind.APPLIED and self.items:
            raise ValueError("only applied topic rerank may persist model reasons")
        if self.kind is not TopicRerankOutcomeKind.APPLIED and self.final_order != self.base_order:
            raise ValueError("skipped and fallback topic rerank must preserve deterministic order")
        if self.kind is TopicRerankOutcomeKind.APPLIED:
            ordered_items = tuple(sorted(self.items, key=lambda item: item.ordinal))
            if self.candidate_count < 2 or len(ordered_items) != self.candidate_count:
                raise ValueError("applied topic rerank requires reasons for every candidate")
            if tuple(item.ordinal for item in ordered_items) != tuple(
                range(1, self.candidate_count + 1)
            ):
                raise ValueError("applied topic rerank item ordinals must be consecutive")
            if tuple(item.event_id for item in ordered_items) != self.final_order:
                raise ValueError("applied topic rerank reasons must match final order")
        for fingerprint in (self.request_fingerprint, self.prompt_fingerprint):
            if fingerprint is not None and (
                len(fingerprint) != 64
                or any(character not in "0123456789abcdef" for character in fingerprint)
            ):
                raise ValueError("topic rerank outcome fingerprints must be SHA-256")
        if (
            min(
                self.prompt_tokens,
                self.completion_tokens,
                self.reasoning_tokens,
                self.latency_ms,
            )
            < 0
        ):
            raise ValueError("topic rerank outcome usage and latency must be non-negative")

    @property
    def reasons_by_event(self) -> MappingProxyType[UUID, TopicRerankItem]:
        return MappingProxyType({item.event_id: item for item in self.items})


class TopicRerankValidationError(ValueError):
    def __init__(self, failure_code: TopicRerankFailureCode) -> None:
        self.failure_code = failure_code
        super().__init__(failure_code.value)


def skipped_topic_rerank_outcome(
    config: TopicRerankConfig,
    event_ids: tuple[UUID, ...] = (),
) -> TopicRerankOutcome:
    return TopicRerankOutcome(
        kind=TopicRerankOutcomeKind.SKIPPED,
        policy_version=config.policy_version,
        provider=config.provider,
        model=config.model,
        candidate_count=len(event_ids),
        base_order=event_ids,
        final_order=event_ids,
    )


def build_daily_rerank_pool(
    decision: DailyTopicDecision,
    candidates: tuple[TopicCandidate, ...],
    *,
    limit: int,
) -> tuple[TopicRerankCandidate, ...]:
    candidates_by_id = {candidate.event_id: candidate for candidate in candidates}
    scores = tuple(score for score in decision.scores if score.eligible)[:limit]
    return tuple(
        _candidate_projection(
            candidates_by_id[score.event_id],
            score,
            deterministic_rank=_required_rank(score.rank),
            context="daily",
        )
        for score in scores
    )


def build_slot_rerank_pool(
    decision: ContentSlotDecision,
    candidates: tuple[TopicCandidate, ...],
    *,
    limit: int,
) -> tuple[TopicRerankCandidate, ...]:
    candidates_by_id = {candidate.event_id: candidate for candidate in candidates}
    scores = tuple(
        score for score in decision.scores if score.base.eligible and not score.same_day_excluded
    )[:limit]
    return tuple(
        _candidate_projection(
            candidates_by_id[score.base.event_id],
            score.base,
            deterministic_rank=_required_rank(score.rank),
            context=decision.slot.value,
            slot_score=score,
        )
        for score in scores
    )


def validate_topic_rerank_result(
    pool: tuple[TopicRerankCandidate, ...],
    result: TopicRerankModelResult,
) -> tuple[UUID, ...]:
    if len(result.items) != len(pool):
        raise TopicRerankValidationError(TopicRerankFailureCode.INVALID_PERMUTATION)
    ordered_items = tuple(sorted(result.items, key=lambda item: item.ordinal))
    if tuple(item.ordinal for item in ordered_items) != tuple(range(1, len(pool) + 1)):
        raise TopicRerankValidationError(TopicRerankFailureCode.INVALID_PERMUTATION)
    result_ids = tuple(item.event_id for item in ordered_items)
    pool_ids = tuple(candidate.event_id for candidate in pool)
    if len(set(result_ids)) != len(result_ids) or set(result_ids) != set(pool_ids):
        raise TopicRerankValidationError(TopicRerankFailureCode.INVALID_PERMUTATION)
    groups_by_id = {candidate.event_id: candidate.priority_group for candidate in pool}
    result_groups = tuple(groups_by_id[event_id] for event_id in result_ids)
    if result_groups != tuple(sorted(result_groups)):
        raise TopicRerankValidationError(TopicRerankFailureCode.PRIORITY_BARRIER_VIOLATION)
    return result_ids


def apply_daily_topic_rerank(
    decision: DailyTopicDecision,
    outcome: TopicRerankOutcome,
) -> DailyTopicDecision:
    if outcome.kind is not TopicRerankOutcomeKind.APPLIED:
        return _with_daily_deterministic_ranks(decision)
    final_pool = outcome.final_order
    pool_ids = frozenset(final_pool)
    remaining_eligible = tuple(
        score.event_id
        for score in decision.scores
        if score.eligible and score.event_id not in pool_ids
    )
    ineligible = tuple(score.event_id for score in decision.scores if not score.eligible)
    full_order = (*final_pool, *remaining_eligible, *ineligible)
    scores_by_id = {score.event_id: score for score in decision.scores}
    reasons = outcome.reasons_by_event
    ranked = tuple(
        replace(
            scores_by_id[event_id],
            rank=rank,
            deterministic_rank=_required_rank(scores_by_id[event_id].rank),
            rerank_reason_codes=(reasons[event_id].reason_codes if event_id in reasons else ()),
            rerank_explanation=(reasons[event_id].explanation if event_id in reasons else None),
        )
        for rank, event_id in enumerate(full_order, start=1)
    )
    selected = next((score for score in ranked if score.eligible), None)
    return replace(
        decision,
        scores=ranked,
        selected_event_id=selected.event_id if selected is not None else None,
        selected_event_version_id=(selected.event_version_id if selected is not None else None),
    )


def apply_content_slot_rerank(
    decision: ContentSlotDecision,
    outcome: TopicRerankOutcome,
    *,
    max_items: int,
) -> ContentSlotDecision:
    if outcome.kind is not TopicRerankOutcomeKind.APPLIED:
        return _with_slot_deterministic_ranks(decision)
    final_pool = outcome.final_order
    pool_ids = frozenset(final_pool)
    remaining_eligible = tuple(
        score.base.event_id
        for score in decision.scores
        if score.base.eligible
        and not score.same_day_excluded
        and score.base.event_id not in pool_ids
    )
    unavailable = tuple(
        score.base.event_id
        for score in decision.scores
        if not score.base.eligible or score.same_day_excluded
    )
    full_order = (*final_pool, *remaining_eligible, *unavailable)
    scores_by_id = {score.base.event_id: score for score in decision.scores}
    reasons = outcome.reasons_by_event
    selected_ids = tuple((*final_pool, *remaining_eligible)[:max_items])
    ordinal_by_id = {event_id: ordinal for ordinal, event_id in enumerate(selected_ids, start=1)}
    ranked = tuple(
        replace(
            scores_by_id[event_id],
            rank=rank,
            deterministic_rank=_required_rank(scores_by_id[event_id].rank),
            selected_ordinal=ordinal_by_id.get(event_id),
            rerank_reason_codes=(reasons[event_id].reason_codes if event_id in reasons else ()),
            rerank_explanation=(reasons[event_id].explanation if event_id in reasons else None),
        )
        for rank, event_id in enumerate(full_order, start=1)
    )
    selected = tuple(score for score in ranked if score.selected_ordinal is not None)
    return replace(
        decision,
        scores=ranked,
        selected_event_ids=tuple(score.base.event_id for score in selected),
        selected_event_version_ids=tuple(score.base.event_version_id for score in selected),
        unfilled_count=max_items - len(selected),
    )


def _candidate_projection(
    candidate: TopicCandidate,
    score: TopicScore,
    *,
    deterministic_rank: int,
    context: str,
    slot_score: ContentSlotScore | None = None,
) -> TopicRerankCandidate:
    title = candidate.priority_title.strip() or str(candidate.event_id)
    return TopicRerankCandidate(
        event_id=candidate.event_id,
        event_version_id=candidate.event_version_id,
        deterministic_rank=deterministic_rank,
        priority_group=0 if score.priority_applied else 1,
        title=title[:300],
        summary=candidate.priority_summary.strip()[:1_000],
        event_time=candidate.event_time,
        rule_total=score.total,
        source_trust=score.normalized_features["source_trust"],
        communication_potential=candidate.communication_potential,
        editorial_priority=candidate.editorial_priority,
        education_relevance=candidate.science_tech_education_relevance,
        frontier_significance=candidate.frontier_significance,
        product_fit=candidate.product_matrix_fit_v2,
        editorial_reason_codes=candidate.science_tech_editorial_reason_codes[:8],
        product_direction_ids=candidate.product_matrix_v2_direction_ids[:8],
        controversy_risk=candidate.controversy_risk,
        marketing_risk=candidate.marketing_risk,
        context=context,
        slot_affinity=slot_score.affinity if slot_score is not None else None,
        slot_affinity_reasons=(slot_score.affinity_reasons[:8] if slot_score is not None else ()),
    )


def _with_daily_deterministic_ranks(decision: DailyTopicDecision) -> DailyTopicDecision:
    return replace(
        decision,
        scores=tuple(
            replace(score, deterministic_rank=_required_rank(score.rank))
            for score in decision.scores
        ),
    )


def _with_slot_deterministic_ranks(decision: ContentSlotDecision) -> ContentSlotDecision:
    return replace(
        decision,
        scores=tuple(
            replace(score, deterministic_rank=_required_rank(score.rank))
            for score in decision.scores
        ),
    )


def _required_rank(value: int | None) -> int:
    if value is None:
        raise ValueError("topic rerank requires deterministic ranks")
    return value


def _fingerprint(metadata: dict[str, object]) -> str:
    payload = json.dumps(
        metadata, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return hashlib.sha256(payload).hexdigest()
