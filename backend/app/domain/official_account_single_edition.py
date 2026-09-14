"""Prospective, date-scoped single drafts; legacy weekly identities are untouched."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from uuid import UUID, uuid5
from zoneinfo import ZoneInfo

from app.domain.official_account_weekly_edition import (
    WeeklyArticleRole,
    WeeklyArticleSelection,
    WeeklyGovernedCandidate,
    WeeklySelectionReason,
    _governed_ordering_key,
    _project_selection,
    _role_affinity_reasons,
)

SINGLE_EDITION_VERSION = "official-account-single-edition-v1"
SINGLE_EDITION_TIMEZONE = "Asia/Shanghai"
_NAMESPACE = UUID("28d0c3e1-0e55-49f7-bdd3-17cec47854c3")


@dataclass(frozen=True, slots=True)
class SingleEditionWindow:
    business_date: date
    prepare_at: datetime
    deliver_at: datetime
    expires_at: datetime


def edition_window(
    day: date, *, prepare_minutes: int = 60, catchup_hours: int = 6
) -> SingleEditionWindow:
    if day.weekday() not in {0, 2, 4}:
        raise ValueError("single edition requires Monday, Wednesday or Friday")
    if not 1 <= prepare_minutes <= 240 or not 1 <= catchup_hours <= 12:
        raise ValueError("single edition window is invalid")
    target = datetime.combine(day, time(10), ZoneInfo(SINGLE_EDITION_TIMEZONE))
    return SingleEditionWindow(
        day,
        (target - timedelta(minutes=prepare_minutes)).astimezone(UTC),
        target.astimezone(UTC),
        (target + timedelta(hours=catchup_hours)).astimezone(UTC),
    )


def due_single_edition(
    now: datetime,
    *,
    minimum_date: date,
    prepare_minutes: int = 60,
    catchup_hours: int = 6,
) -> SingleEditionWindow | None:
    if now.utcoffset() is None:
        raise ValueError("single edition clock must be timezone aware")
    today = now.astimezone(ZoneInfo(SINGLE_EDITION_TIMEZONE)).date()
    if today < minimum_date or today.weekday() not in {0, 2, 4}:
        return None
    window = edition_window(today, prepare_minutes=prepare_minutes, catchup_hours=catchup_hours)
    return window if window.prepare_at <= now < window.expires_at else None


def single_edition_id(account: str, day: date) -> UUID:
    # Deliberately excludes policy/version: a settings change cannot admit a second date.
    return uuid5(_NAMESPACE, f"{account}:{SINGLE_EDITION_TIMEZONE}:{day.isoformat()}")


def select_single_article(
    candidates: tuple[WeeklyGovernedCandidate, ...],
    *,
    cutoff: datetime,
    excluded_events: frozenset[UUID] = frozenset(),
) -> WeeklyArticleSelection | None:
    """Stored priority/score order, without the weekly mandatory role allocation."""
    if cutoff.utcoffset() is None:
        raise ValueError("single edition cutoff must be timezone aware")
    current_floor = cutoff - timedelta(days=7)
    lookback_floor = cutoff - timedelta(days=14)
    eligible = tuple(
        item
        for item in candidates
        if item.is_governed_eligible
        and item.candidate.event_id not in excluded_events
        and lookback_floor <= item.candidate.event_time <= cutoff
    )
    current = tuple(item for item in eligible if item.candidate.event_time >= current_floor)
    pool = current or tuple(item for item in eligible if item.official_authority is not None)
    if not pool:
        return None
    chosen = min(pool, key=_governed_ordering_key)
    if chosen.official_authority is not None:
        role = WeeklyArticleRole.OFFICIAL_ANCHOR
        reason = (
            WeeklySelectionReason.OFFICIAL_CURRENT_WINDOW
            if current
            else WeeklySelectionReason.OFFICIAL_LOOKBACK
        )
    else:
        role = max(
            (WeeklyArticleRole.INDUSTRY_TREND, WeeklyArticleRole.APPLICATION_CASE),
            key=lambda value: len(_role_affinity_reasons(chosen, role=value)),
        )
        reason = (
            WeeklySelectionReason.ROLE_AFFINITY
            if _role_affinity_reasons(chosen, role=role)
            else WeeklySelectionReason.ROLE_AFFINITY_UNAVAILABLE
        )
    return _project_selection(
        role, chosen, reason, affinity_reasons=_role_affinity_reasons(chosen, role=role)
    )
