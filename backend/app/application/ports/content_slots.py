from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol
from uuid import UUID

from app.domain.content_slots import (
    ContentSlot,
    ContentSlotDecision,
    ContentSlotSchedule,
    SlotRankingPolicy,
)
from app.domain.topic_rerank import TopicRerankConfig, TopicRerankOutcome
from app.domain.topic_selection import TopicCandidate, TopicScoringConfig


@dataclass(frozen=True, slots=True)
class GovernedSlotLineage:
    acquisition_run_id: UUID
    governance_run_id: UUID
    governed_event_cutoff: datetime


@dataclass(frozen=True, slots=True)
class ClaimedContentSlotJob:
    job_id: UUID
    run_id: UUID
    attempt_number: int
    lease_token: UUID
    business_date: date
    timezone: str
    slot: ContentSlot
    cutoff_at: datetime
    item_limit: int


class ContentSlotRepository(Protocol):
    async def ready_lineage(
        self,
        *,
        business_date: date,
        timezone: str,
        slot: ContentSlot,
        now: datetime,
    ) -> GovernedSlotLineage | None: ...

    async def enqueue(
        self,
        *,
        business_date: date,
        timezone: str,
        schedule: ContentSlotSchedule,
        config: TopicScoringConfig,
        policy: SlotRankingPolicy,
        rerank_config: TopicRerankConfig,
        lineage: GovernedSlotLineage,
        trigger: str,
    ) -> UUID: ...

    async def claim(
        self, *, worker_id: str, lease_seconds: int, max_attempts: int
    ) -> ClaimedContentSlotJob | None: ...

    async def heartbeat(self, *, claimed: ClaimedContentSlotJob, lease_seconds: int) -> bool: ...

    async def load_config(self, run_id: UUID) -> TopicScoringConfig: ...

    async def load_policy(self, run_id: UUID) -> SlotRankingPolicy: ...

    async def load_rerank_config(self, run_id: UUID) -> TopicRerankConfig: ...

    async def load_candidates(self, run_id: UUID) -> tuple[TopicCandidate, ...]: ...

    async def same_day_selected_event_ids(self, run_id: UUID) -> frozenset[UUID]: ...

    async def persist_decision(
        self,
        *,
        claimed: ClaimedContentSlotJob,
        config: TopicScoringConfig,
        policy: SlotRankingPolicy,
        decision: ContentSlotDecision,
        rerank_outcome: TopicRerankOutcome,
    ) -> bool: ...

    async def complete(self, *, claimed: ClaimedContentSlotJob) -> bool: ...

    async def fail(self, *, claimed: ClaimedContentSlotJob, error_code: str) -> bool: ...
