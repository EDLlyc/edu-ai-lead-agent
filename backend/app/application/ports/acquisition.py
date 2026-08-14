from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol
from uuid import UUID

from app.domain.content_slots import ContentSlot
from app.domain.entities import (
    ExtractedDocument,
    FetchedResponse,
    SnapshotDescriptor,
    SourceProfile,
)
from app.domain.enums import JobStatus, ObservationOutcome, RunTrigger


@dataclass(frozen=True, slots=True)
class ClaimedJob:
    job_id: UUID
    run_id: UUID
    attempt_number: int
    lease_token: UUID
    profile: SourceProfile


@dataclass(frozen=True, slots=True)
class CursorState:
    etag: str | None
    last_modified: str | None
    last_item_id: str | None
    last_published_at: datetime | None


@dataclass(frozen=True, slots=True)
class PersistedCandidate:
    candidate_id: UUID
    outcome: ObservationOutcome


class AcquisitionRepository(Protocol):
    async def enqueue(
        self,
        *,
        trigger: RunTrigger,
        timezone: str,
        acquisition_version: str,
        business_date: date | None = None,
        content_slot: ContentSlot | None = None,
        manual_idempotency_key: str | None = None,
        source_ids: list[UUID] | None = None,
    ) -> tuple[UUID, bool]: ...

    async def claim(self, *, worker_id: str, lease_seconds: int) -> ClaimedJob | None: ...

    async def create_attempt(self, claimed: ClaimedJob) -> UUID: ...

    async def heartbeat(self, *, claimed: ClaimedJob, lease_seconds: int) -> bool: ...

    async def acquire_source_lease(
        self, *, claimed: ClaimedJob, owner: str, lease_seconds: int
    ) -> bool: ...

    async def reserve_source_request_slot(
        self, *, claimed: ClaimedJob, minimum_interval_seconds: float
    ) -> float: ...

    async def release_source_lease(self, claimed: ClaimedJob) -> None: ...

    async def cursor(self, source_version_id: UUID) -> CursorState: ...

    async def save_cursor(
        self,
        *,
        claimed: ClaimedJob,
        source_version_id: UUID,
        etag: str | None,
        last_modified: str | None,
        last_item_id: str | None,
        last_published_at: datetime | None,
    ) -> None: ...

    async def save_snapshot(
        self,
        *,
        claimed: ClaimedJob,
        profile: SourceProfile,
        kind: str,
        response: FetchedResponse,
        stored: SnapshotDescriptor,
    ) -> UUID: ...

    async def save_candidate(
        self,
        *,
        claimed: ClaimedJob,
        profile: SourceProfile,
        document: ExtractedDocument,
        snapshot_id: UUID,
        fetched_at: datetime,
    ) -> PersistedCandidate: ...

    async def observe(
        self,
        *,
        claimed: ClaimedJob,
        source_item_id: str | None,
        outcome: ObservationOutcome,
        snapshot_id: UUID | None = None,
        candidate_id: UUID | None = None,
        http_status: int | None = None,
        error_code: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None: ...

    async def complete_attempt(
        self,
        *,
        claimed: ClaimedJob,
        attempt_id: UUID,
        result: str,
        error_code: str | None,
        byte_count: int,
        item_count: int,
    ) -> None: ...

    async def complete_job(
        self,
        *,
        claimed: ClaimedJob,
        status: JobStatus,
        outcome: str,
        error_code: str | None,
        new_count: int = 0,
        unchanged_count: int = 0,
        duplicate_count: int = 0,
        filtered_count: int = 0,
        byte_count: int = 0,
        retry_at: datetime | None = None,
    ) -> bool: ...


class Fetcher(Protocol):
    async def fetch(
        self,
        url: str,
        profile: SourceProfile,
        *,
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> FetchedResponse: ...


class SnapshotStore(Protocol):
    async def put_immutable(self, body: bytes, media_type: str) -> SnapshotDescriptor: ...
