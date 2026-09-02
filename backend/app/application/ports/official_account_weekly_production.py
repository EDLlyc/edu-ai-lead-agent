"""Typed production input boundary for the weekly official-account workflow."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol
from uuid import UUID

from app.domain.official_account_weekly_edition import (
    WEEKLY_EDITION_ROLE_ORDER,
    WeeklyArticleRole,
    WeeklyEditionSelection,
)

WEEKLY_PRODUCTION_INPUT_VERSION = "official-account-weekly-production-input-v1"


def _fingerprint(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class WeeklyProductionInputItem:
    role: WeeklyArticleRole
    material_package_id: UUID
    event_id: UUID
    event_version_id: UUID
    title: str
    material_request_fingerprint: str
    score_fingerprint: str
    source_metadata_fingerprint: str
    organization_type: str
    official_authority: str | None
    selection_reason: str
    affinity_reasons: tuple[str, ...]
    governed_total: float
    governed_score_version: str

    def __post_init__(self) -> None:
        if not self.title.strip() or len(self.title) > 300:
            raise ValueError("weekly production title is invalid")
        if any(
            len(value) != 64 or any(character not in "0123456789abcdef" for character in value)
            for value in (
                self.material_request_fingerprint,
                self.score_fingerprint,
                self.source_metadata_fingerprint,
            )
        ):
            raise ValueError("weekly production item fingerprints are invalid")
        if not self.organization_type.strip() or len(self.organization_type) > 80:
            raise ValueError("weekly production organization type is invalid")
        if self.official_authority is not None and (
            not self.official_authority.strip() or len(self.official_authority) > 100
        ):
            raise ValueError("weekly production official authority is invalid")
        if not self.selection_reason.strip() or len(self.selection_reason) > 100:
            raise ValueError("weekly production selection reason is invalid")
        if len(set(self.affinity_reasons)) != len(self.affinity_reasons) or any(
            not value.strip() or len(value) > 100 for value in self.affinity_reasons
        ):
            raise ValueError("weekly production affinity reasons are invalid")
        if not math.isfinite(self.governed_total):
            raise ValueError("weekly production governed total is invalid")
        if not self.governed_score_version.strip() or len(self.governed_score_version) > 80:
            raise ValueError("weekly production governed score version is invalid")

    def as_dict(self) -> dict[str, object]:
        return {
            "role": self.role.value,
            "material_package_id": str(self.material_package_id),
            "event_id": str(self.event_id),
            "event_version_id": str(self.event_version_id),
            "title": self.title,
            "material_request_fingerprint": self.material_request_fingerprint,
            "score_fingerprint": self.score_fingerprint,
            "source_metadata_fingerprint": self.source_metadata_fingerprint,
            "organization_type": self.organization_type,
            "official_authority": self.official_authority,
            "selection_reason": self.selection_reason,
            "affinity_reasons": list(self.affinity_reasons),
            "governed_total": self.governed_total,
            "governed_score_version": self.governed_score_version,
        }


@dataclass(frozen=True, slots=True)
class WeeklyProductionInput:
    week_start: date
    cutoff: datetime
    selection: WeeklyEditionSelection
    items: tuple[
        WeeklyProductionInputItem,
        WeeklyProductionInputItem,
        WeeklyProductionInputItem,
    ]
    version: str = WEEKLY_PRODUCTION_INPUT_VERSION

    def __post_init__(self) -> None:
        if self.version != WEEKLY_PRODUCTION_INPUT_VERSION:
            raise ValueError("weekly production input version is unsupported")
        if self.week_start.weekday() != 0:
            raise ValueError("weekly production week start must be a Monday")
        if self.cutoff.tzinfo is None or self.cutoff.utcoffset() is None:
            raise ValueError("weekly production cutoff must be timezone-aware")
        if self.selection.week_start != self.week_start:
            raise ValueError("weekly production selection week changed")
        if tuple(item.role.value for item in self.items) != WEEKLY_EDITION_ROLE_ORDER:
            raise ValueError("weekly production roles must be canonical")
        if len({item.material_package_id for item in self.items}) != 3:
            raise ValueError("weekly production material packages must be distinct")
        if len({item.event_id for item in self.items}) != 3:
            raise ValueError("weekly production events must be distinct")
        for item, selected in zip(self.items, self.selection.selected, strict=True):
            if (
                item.role is not selected.role
                or item.event_id != selected.event_id
                or item.event_version_id != selected.event_version_id
                or item.source_metadata_fingerprint != selected.source_metadata_fingerprint
                or item.organization_type != selected.organization_type
                or item.official_authority != selected.official_authority
                or item.selection_reason != selected.selection_reason.value
                or item.affinity_reasons != selected.affinity_reasons
                or item.governed_total != selected.governed_total
                or item.governed_score_version != selected.governed_score_version
            ):
                raise ValueError("weekly production material binding changed")

    def as_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "week_start": self.week_start.isoformat(),
            "cutoff": self.cutoff.isoformat(),
            "selection_fingerprint": self.selection.fingerprint,
            "items": [item.as_dict() for item in self.items],
        }

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.as_dict())


class WeeklyProductionInputPlanner(Protocol):
    async def plan(
        self,
        *,
        week_start: date,
        cutoff: datetime,
    ) -> WeeklyProductionInput: ...


__all__ = [
    "WEEKLY_PRODUCTION_INPUT_VERSION",
    "WeeklyProductionInput",
    "WeeklyProductionInputItem",
    "WeeklyProductionInputPlanner",
]
