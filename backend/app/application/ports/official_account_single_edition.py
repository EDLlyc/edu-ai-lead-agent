"""Frozen inputs and leased progress for one scheduled, unpublished draft."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol
from uuid import UUID

from app.application.ports.official_account_local import OfficialAccountVersionIdentity
from app.application.ports.official_account_weekly_production import WeeklyProductionInputItem
from app.domain.official_account_single_edition import SingleEditionWindow
from app.domain.official_account_weekly_dag import WeeklyDagArtifact


@dataclass(frozen=True, slots=True)
class SingleEdition:
    id: UUID
    account: str
    business_date: date
    prepare_at: datetime
    deliver_at: datetime
    expires_at: datetime
    identity: OfficialAccountVersionIdentity
    max_attempts: int
    retry_base_seconds: int
    status: str
    attempts: dict[str, int]
    available_at: datetime
    lease_token: UUID | None = None
    selection_artifact: WeeklyDagArtifact | None = None
    material_package_id: UUID | None = None
    event_id: UUID | None = None
    article_run_id: UUID | None = None
    prepared_artifact: WeeklyDagArtifact | None = None
    role: str | None = None
    article_fingerprint: str | None = None
    content_fingerprint: str | None = None
    receipt_fingerprint: str | None = None
    error_code: str | None = None


class SingleEditionRepository(Protocol):
    async def admit(
        self,
        *,
        account: str,
        window: SingleEditionWindow,
        identity: OfficialAccountVersionIdentity,
        max_attempts: int,
        retry_base_seconds: int,
        now: datetime,
    ) -> SingleEdition | None: ...

    async def claim(
        self,
        *,
        account: str,
        delivery: bool,
        now: datetime,
        lease_seconds: int,
    ) -> SingleEdition | None: ...

    async def heartbeat(
        self, edition: SingleEdition, *, now: datetime, lease_seconds: int
    ) -> bool: ...

    async def save(self, edition: SingleEdition, *, now: datetime) -> bool: ...

    async def excluded_events(self, account: str) -> frozenset[UUID]: ...

    async def select(
        self,
        edition: SingleEdition,
        item: WeeklyProductionInputItem,
        artifact: WeeklyDagArtifact,
        *,
        now: datetime,
    ) -> bool: ...

    async def reserve_article(self, edition: SingleEdition, *, now: datetime) -> bool: ...


class SingleEditionPlanner(Protocol):
    async def plan_single(
        self, *, cutoff: datetime, excluded_events: frozenset[UUID]
    ) -> WeeklyProductionInputItem | None: ...
