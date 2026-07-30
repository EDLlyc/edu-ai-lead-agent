from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol
from uuid import UUID

from app.domain.topic_selection import DailyTopicDecision, TopicCandidate, TopicScoringConfig


@dataclass(frozen=True, slots=True)
class ClaimedTopicSelectionJob:
    job_id: UUID
    run_id: UUID
    attempt_number: int
    lease_token: UUID
    business_date: date
    timezone: str
    cutoff_at: datetime


class TopicSelectionRepository(Protocol):
    async def enqueue(
        self,
        *,
        business_date: date,
        timezone: str,
        config: TopicScoringConfig,
        governed_event_cutoff: datetime,
        trigger: str = "manual",
    ) -> UUID: ...

    async def claim(
        self, *, worker_id: str, lease_seconds: int, max_attempts: int
    ) -> ClaimedTopicSelectionJob | None: ...

    async def heartbeat(self, *, claimed: ClaimedTopicSelectionJob, lease_seconds: int) -> bool: ...

    async def load_config(self, run_id: UUID) -> TopicScoringConfig: ...

    async def load_candidates(self, run_id: UUID) -> tuple[TopicCandidate, ...]: ...

    async def persist_decision(
        self,
        *,
        claimed: ClaimedTopicSelectionJob,
        config: TopicScoringConfig,
        decision: DailyTopicDecision,
    ) -> bool: ...

    async def complete(self, *, claimed: ClaimedTopicSelectionJob) -> bool: ...

    async def fail(self, *, claimed: ClaimedTopicSelectionJob, error_code: str) -> bool: ...
