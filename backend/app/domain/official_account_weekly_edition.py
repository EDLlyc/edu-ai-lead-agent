"""Pure weekly schedule and governed three-article role selection."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from typing import Final
from urllib.parse import urlparse
from uuid import UUID
from zoneinfo import ZoneInfo

from app.domain.editorial_relevance import (
    ScienceTechContentSignal,
    ScienceTechEditorialCohort,
)
from app.domain.topic_selection import (
    GOV_CN_YAOWEN_PRIORITY_POLICY,
    MOE_SCIENCE_TOP1_PRIORITY_POLICY,
    TopicCandidate,
    TopicScore,
)

WEEKLY_EDITION_SCHEDULE_VERSION: Final = "official-account-weekly-schedule-v1"
WEEKLY_EDITION_SELECTION_VERSION: Final = "official-account-weekly-selection-v1"
WEEKLY_HOMEPAGE_DISPLAY_POLICY_VERSION: Final = "official-account-weekly-homepage-display-policy-v1"
WEEKLY_HOMEPAGE_OPERATOR_STATE_VERSION: Final = "official-account-weekly-homepage-operator-state-v1"
WEEKLY_HOMEPAGE_OPERATOR_EVENT_VERSION: Final = "official-account-weekly-homepage-operator-event-v1"
WEEKLY_EDITION_TIMEZONE: Final = "Asia/Shanghai"
WEEKLY_EDITION_ROLE_ORDER: Final = (
    "official_anchor",
    "industry_trend",
    "application_case",
)

_AUTHENTICATED_OFFICIAL_POLICIES = frozenset(
    {MOE_SCIENCE_TOP1_PRIORITY_POLICY, GOV_CN_YAOWEN_PRIORITY_POLICY}
)
_OFFICIAL_AUTHORITY_PROJECTIONS = frozenset(
    {
        "stored_government_organization_type",
        "authenticated_topic_priority_policy",
    }
)
_INDUSTRY_SIGNALS = frozenset(
    {
        ScienceTechContentSignal.COMPLETED_PROGRESS,
        ScienceTechContentSignal.CAPITAL_OR_MARKET,
        ScienceTechContentSignal.PRODUCT_OR_SERVICE_RELEASE,
        ScienceTechContentSignal.GENERAL_HARD_TECH,
    }
)
_INDUSTRY_DIRECTIONS = frozenset(
    {
        "ai_theme_robotics_agent_safety_math_3d_hackathon",
        "competition_innovation_talent_pathway",
    }
)
_APPLICATION_DIRECTIONS = frozenset(
    {
        "science_exploration_courses_and_camps",
        "competition_innovation_talent_pathway",
        "ai_theme_robotics_agent_safety_math_3d_hackathon",
    }
)
_APPLICATION_REASONS = frozenset(
    {
        "explicit_science_technology_education",
        "science_ai_topic_with_education_context",
        "science_talent_pathway",
    }
)


class WeeklyArticleRole(StrEnum):
    OFFICIAL_ANCHOR = "official_anchor"
    INDUSTRY_TREND = "industry_trend"
    APPLICATION_CASE = "application_case"

    @property
    def ordinal(self) -> int:
        return {
            WeeklyArticleRole.OFFICIAL_ANCHOR: 1,
            WeeklyArticleRole.INDUSTRY_TREND: 2,
            WeeklyArticleRole.APPLICATION_CASE: 3,
        }[self]


class WeeklySelectionReason(StrEnum):
    OFFICIAL_CURRENT_WINDOW = "official_current_7_day_window"
    OFFICIAL_LOOKBACK = "official_14_day_lookback"
    OFFICIAL_UNAVAILABLE_FALLBACK = "official_source_unavailable_fallback"
    ROLE_AFFINITY = "stored_role_affinity"
    ROLE_AFFINITY_UNAVAILABLE = "role_affinity_unavailable_score_fallback"


class WeeklyHomepageDisplayIntent(StrEnum):
    PINNED_PRIMARY = "pinned_primary"
    STANDARD = "standard"


class WeeklyHomepageCoverPurpose(StrEnum):
    PINNED_LARGE_CARD = "homepage_pinned_large_card_candidate"
    STANDARD_THUMBNAIL = "homepage_standard_thumbnail_candidate"


class WeeklyHomepagePublicationStatus(StrEnum):
    NOT_PUBLISHED = "not_published"
    AWAITING_MANUAL_PIN = "awaiting_manual_pin"
    CONFIRMED = "confirmed"


class WeeklyHomepageOperatorEventKind(StrEnum):
    PUBLICATION_CONFIRMED = "publication_confirmed"
    HOMEPAGE_PIN_CONFIRMED = "homepage_pin_confirmed"


@dataclass(frozen=True, slots=True)
class WeeklyHomepageDisplayPolicy:
    role: WeeklyArticleRole
    display_intent: WeeklyHomepageDisplayIntent
    cover_purpose: WeeklyHomepageCoverPurpose
    source_aspect_ratio_intent: str = "2.35:1"
    crop_ownership: str = "wechat_homepage_system"
    policy_version: str = WEEKLY_HOMEPAGE_DISPLAY_POLICY_VERSION

    def __post_init__(self) -> None:
        if self.policy_version != WEEKLY_HOMEPAGE_DISPLAY_POLICY_VERSION:
            raise ValueError("unsupported weekly homepage display policy")
        if self.source_aspect_ratio_intent != "2.35:1":
            raise ValueError("weekly homepage cover source ratio intent changed")
        if self.crop_ownership != "wechat_homepage_system":
            raise ValueError("weekly homepage crop ownership must remain external")
        is_primary = self.role is WeeklyArticleRole.OFFICIAL_ANCHOR
        if is_primary != (
            self.display_intent is WeeklyHomepageDisplayIntent.PINNED_PRIMARY
            and self.cover_purpose is WeeklyHomepageCoverPurpose.PINNED_LARGE_CARD
        ):
            raise ValueError("weekly homepage official display policy changed")
        if not is_primary and (
            self.display_intent is not WeeklyHomepageDisplayIntent.STANDARD
            or self.cover_purpose is not WeeklyHomepageCoverPurpose.STANDARD_THUMBNAIL
        ):
            raise ValueError("weekly homepage standard display policy changed")


def weekly_homepage_display_policy(role: WeeklyArticleRole) -> WeeklyHomepageDisplayPolicy:
    if role is WeeklyArticleRole.OFFICIAL_ANCHOR:
        return WeeklyHomepageDisplayPolicy(
            role=role,
            display_intent=WeeklyHomepageDisplayIntent.PINNED_PRIMARY,
            cover_purpose=WeeklyHomepageCoverPurpose.PINNED_LARGE_CARD,
        )
    return WeeklyHomepageDisplayPolicy(
        role=role,
        display_intent=WeeklyHomepageDisplayIntent.STANDARD,
        cover_purpose=WeeklyHomepageCoverPurpose.STANDARD_THUMBNAIL,
    )


@dataclass(frozen=True, slots=True)
class WeeklyHomepageOperatorEvent:
    event_id: UUID
    kind: WeeklyHomepageOperatorEventKind
    occurred_at: datetime
    actor_reference: str
    batch_fingerprint: str
    official_article_fingerprint: str
    published_url: str | None = None
    version: str = WEEKLY_HOMEPAGE_OPERATOR_EVENT_VERSION

    def __post_init__(self) -> None:
        if self.version != WEEKLY_HOMEPAGE_OPERATOR_EVENT_VERSION:
            raise ValueError("unsupported weekly homepage operator event")
        if self.occurred_at.utcoffset() is None:
            raise ValueError("weekly homepage operator event time must be timezone-aware")
        if not _is_safe_operator_reference(self.actor_reference):
            raise ValueError("weekly homepage operator reference is invalid")
        if not _is_sha256(self.batch_fingerprint):
            raise ValueError("weekly homepage event batch fingerprint is invalid")
        if not _is_sha256(self.official_article_fingerprint):
            raise ValueError("weekly homepage event official Article fingerprint is invalid")
        if self.kind is WeeklyHomepageOperatorEventKind.PUBLICATION_CONFIRMED:
            if not _is_wechat_publication_url(self.published_url):
                raise ValueError("weekly homepage publication URL is invalid")
        elif self.published_url is not None:
            raise ValueError("weekly homepage pin confirmation cannot carry a publication URL")


@dataclass(frozen=True, slots=True)
class WeeklyHomepageOperatorState:
    batch_fingerprint: str
    official_article_fingerprint: str
    status: WeeklyHomepagePublicationStatus
    events: tuple[WeeklyHomepageOperatorEvent, ...]
    version: str = WEEKLY_HOMEPAGE_OPERATOR_STATE_VERSION

    def __post_init__(self) -> None:
        if self.version != WEEKLY_HOMEPAGE_OPERATOR_STATE_VERSION:
            raise ValueError("unsupported weekly homepage operator state")
        if not _is_sha256(self.batch_fingerprint):
            raise ValueError("weekly homepage state batch fingerprint is invalid")
        if not _is_sha256(self.official_article_fingerprint):
            raise ValueError("weekly homepage state official Article fingerprint is invalid")
        if any(
            item.batch_fingerprint != self.batch_fingerprint
            or item.official_article_fingerprint != self.official_article_fingerprint
            for item in self.events
        ):
            raise ValueError("weekly homepage state event identity changed")
        if len({item.event_id for item in self.events}) != len(self.events):
            raise ValueError("weekly homepage state event IDs must be unique")
        if any(
            current.occurred_at < previous.occurred_at
            for previous, current in zip(self.events, self.events[1:], strict=False)
        ):
            raise ValueError("weekly homepage state event time moved backwards")
        expected = {
            WeeklyHomepagePublicationStatus.NOT_PUBLISHED: (),
            WeeklyHomepagePublicationStatus.AWAITING_MANUAL_PIN: (
                WeeklyHomepageOperatorEventKind.PUBLICATION_CONFIRMED,
            ),
            WeeklyHomepagePublicationStatus.CONFIRMED: (
                WeeklyHomepageOperatorEventKind.PUBLICATION_CONFIRMED,
                WeeklyHomepageOperatorEventKind.HOMEPAGE_PIN_CONFIRMED,
            ),
        }[self.status]
        if tuple(item.kind for item in self.events) != expected:
            raise ValueError("weekly homepage state history is inconsistent")

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            self.version,
            self.batch_fingerprint,
            self.official_article_fingerprint,
            self.status.value,
            tuple(
                (
                    item.version,
                    str(item.event_id),
                    item.kind.value,
                    item.occurred_at.isoformat(),
                    item.actor_reference,
                    item.batch_fingerprint,
                    item.official_article_fingerprint,
                    item.published_url,
                )
                for item in self.events
            ),
        )


def initial_weekly_homepage_operator_state(
    *,
    batch_fingerprint: str,
    official_article_fingerprint: str,
) -> WeeklyHomepageOperatorState:
    return WeeklyHomepageOperatorState(
        batch_fingerprint=batch_fingerprint,
        official_article_fingerprint=official_article_fingerprint,
        status=WeeklyHomepagePublicationStatus.NOT_PUBLISHED,
        events=(),
    )


def apply_weekly_homepage_operator_event(
    state: WeeklyHomepageOperatorState,
    event: WeeklyHomepageOperatorEvent,
) -> WeeklyHomepageOperatorState:
    if (
        event.batch_fingerprint != state.batch_fingerprint
        or event.official_article_fingerprint != state.official_article_fingerprint
    ):
        raise ValueError("weekly homepage operator event identity changed")
    if event.event_id in {item.event_id for item in state.events}:
        raise ValueError("weekly homepage operator event was already applied")
    if state.events and event.occurred_at < state.events[-1].occurred_at:
        raise ValueError("weekly homepage operator event time moved backwards")
    if (
        state.status is WeeklyHomepagePublicationStatus.NOT_PUBLISHED
        and event.kind is WeeklyHomepageOperatorEventKind.PUBLICATION_CONFIRMED
    ):
        status = WeeklyHomepagePublicationStatus.AWAITING_MANUAL_PIN
    elif (
        state.status is WeeklyHomepagePublicationStatus.AWAITING_MANUAL_PIN
        and event.kind is WeeklyHomepageOperatorEventKind.HOMEPAGE_PIN_CONFIRMED
    ):
        status = WeeklyHomepagePublicationStatus.CONFIRMED
    else:
        raise ValueError("weekly homepage operator transition is not allowed")
    return WeeklyHomepageOperatorState(
        batch_fingerprint=state.batch_fingerprint,
        official_article_fingerprint=state.official_article_fingerprint,
        status=status,
        events=(*state.events, event),
    )


def weekly_homepage_operator_state_projection(
    state: WeeklyHomepageOperatorState,
) -> dict[str, object]:
    return {
        "version": state.version,
        "state_fingerprint": state.fingerprint,
        "batch_fingerprint": state.batch_fingerprint,
        "official_article_fingerprint": state.official_article_fingerprint,
        "status": state.status.value,
        "wechat_homepage_ui_owner": "wechat_homepage_system",
        "events": [
            {
                "version": item.version,
                "event_id": str(item.event_id),
                "kind": item.kind.value,
                "occurred_at": item.occurred_at.isoformat(),
                "actor_reference": item.actor_reference,
                "batch_fingerprint": item.batch_fingerprint,
                "official_article_fingerprint": item.official_article_fingerprint,
                "published_url": item.published_url,
            }
            for item in state.events
        ],
    }


def weekly_homepage_operator_state_from_projection(
    payload: object,
) -> WeeklyHomepageOperatorState:
    expected_fields = {
        "version",
        "state_fingerprint",
        "batch_fingerprint",
        "official_article_fingerprint",
        "status",
        "wechat_homepage_ui_owner",
        "events",
    }
    if not isinstance(payload, dict) or set(payload) != expected_fields:
        raise ValueError("weekly homepage operator state projection fields changed")
    string_fields = {
        "version",
        "state_fingerprint",
        "batch_fingerprint",
        "official_article_fingerprint",
        "status",
        "wechat_homepage_ui_owner",
    }
    if any(not isinstance(payload[field], str) for field in string_fields):
        raise ValueError("weekly homepage operator state projection strings are invalid")
    if payload["wechat_homepage_ui_owner"] != "wechat_homepage_system":
        raise ValueError("weekly homepage UI ownership projection changed")
    raw_events = payload["events"]
    if not isinstance(raw_events, list) or len(raw_events) > 2:
        raise ValueError("weekly homepage operator event history is invalid")
    event_fields = {
        "version",
        "event_id",
        "kind",
        "occurred_at",
        "actor_reference",
        "batch_fingerprint",
        "official_article_fingerprint",
        "published_url",
    }
    events: list[WeeklyHomepageOperatorEvent] = []
    for row in raw_events:
        if not isinstance(row, dict) or set(row) != event_fields:
            raise ValueError("weekly homepage operator event projection fields changed")
        required_strings = event_fields - {"published_url"}
        if any(not isinstance(row[field], str) for field in required_strings):
            raise ValueError("weekly homepage operator event projection strings are invalid")
        published_url = row["published_url"]
        if published_url is not None and not isinstance(published_url, str):
            raise ValueError("weekly homepage publication URL projection is invalid")
        events.append(
            WeeklyHomepageOperatorEvent(
                version=str(row["version"]),
                event_id=UUID(str(row["event_id"])),
                kind=WeeklyHomepageOperatorEventKind(str(row["kind"])),
                occurred_at=datetime.fromisoformat(str(row["occurred_at"])),
                actor_reference=str(row["actor_reference"]),
                batch_fingerprint=str(row["batch_fingerprint"]),
                official_article_fingerprint=str(row["official_article_fingerprint"]),
                published_url=published_url,
            )
        )
    state = WeeklyHomepageOperatorState(
        version=str(payload["version"]),
        batch_fingerprint=str(payload["batch_fingerprint"]),
        official_article_fingerprint=str(payload["official_article_fingerprint"]),
        status=WeeklyHomepagePublicationStatus(str(payload["status"])),
        events=tuple(events),
    )
    if payload["state_fingerprint"] != state.fingerprint:
        raise ValueError("weekly homepage operator state fingerprint changed")
    return state


@dataclass(frozen=True, slots=True)
class WeeklyEditionSchedule:
    """One weekly due instant in Asia/Shanghai, separate from daily content slots."""

    weekday: int = 0
    target_time: time = time(hour=9)
    timezone: str = WEEKLY_EDITION_TIMEZONE
    catchup_hours: int = 24
    policy_version: str = WEEKLY_EDITION_SCHEDULE_VERSION

    def __post_init__(self) -> None:
        if self.policy_version != WEEKLY_EDITION_SCHEDULE_VERSION:
            raise ValueError("unsupported weekly edition schedule policy")
        if self.timezone != WEEKLY_EDITION_TIMEZONE:
            raise ValueError("weekly edition timezone must be Asia/Shanghai")
        if not 0 <= self.weekday <= 6:
            raise ValueError("weekly edition weekday must be in [0, 6]")
        if self.target_time.tzinfo is not None:
            raise ValueError("weekly edition target time must be timezone-naive")
        if not 1 <= self.catchup_hours <= 48:
            raise ValueError("weekly edition catch-up must be in [1, 48] hours")

    def scheduled_at(self, week_start: date) -> datetime:
        if week_start.weekday() != 0:
            raise ValueError("weekly edition week_start must be a Monday")
        target_date = week_start + timedelta(days=self.weekday)
        return datetime.combine(
            target_date,
            self.target_time,
            tzinfo=ZoneInfo(self.timezone),
        )

    def as_metadata(self) -> dict[str, object]:
        return {
            "policy_version": self.policy_version,
            "timezone": self.timezone,
            "weekday": self.weekday,
            "target_time": self.target_time.isoformat(timespec="minutes"),
            "catchup_hours": self.catchup_hours,
            "unit": "one_weekly_batch_with_three_independent_articles",
        }

    @property
    def fingerprint(self) -> str:
        return _fingerprint(self.as_metadata())


def week_start_for(moment: datetime, *, timezone: str = WEEKLY_EDITION_TIMEZONE) -> date:
    if moment.tzinfo is None:
        raise ValueError("weekly edition moment must be timezone-aware")
    if timezone != WEEKLY_EDITION_TIMEZONE:
        raise ValueError("weekly edition timezone must be Asia/Shanghai")
    local_date = moment.astimezone(ZoneInfo(timezone)).date()
    return local_date - timedelta(days=local_date.weekday())


def due_weekly_edition_week_start(
    now: datetime,
    *,
    schedule: WeeklyEditionSchedule,
    completed_week_starts: frozenset[date] = frozenset(),
) -> date | None:
    """Return the current due week exactly once when durable completion is absent."""

    week_start = week_start_for(now, timezone=schedule.timezone)
    if week_start in completed_week_starts:
        return None
    local_now = now.astimezone(ZoneInfo(schedule.timezone))
    scheduled_at = schedule.scheduled_at(week_start)
    if scheduled_at <= local_now <= scheduled_at + timedelta(hours=schedule.catchup_hours):
        return week_start
    return None


@dataclass(frozen=True, slots=True)
class WeeklyGovernedCandidate:
    """Stored source authority plus the already-governed immutable score."""

    candidate: TopicCandidate
    score: TopicScore
    organization_type: str
    source_metadata_fingerprint: str

    def __post_init__(self) -> None:
        if self.score.event_id != self.candidate.event_id:
            raise ValueError("weekly candidate score event identity changed")
        if self.score.event_version_id != self.candidate.event_version_id:
            raise ValueError("weekly candidate score event version changed")
        if not self.organization_type.strip() or len(self.organization_type) > 80:
            raise ValueError("weekly candidate organization type is invalid")
        if len(self.source_metadata_fingerprint) != 64 or any(
            char not in "0123456789abcdef" for char in self.source_metadata_fingerprint
        ):
            raise ValueError("weekly candidate source metadata fingerprint is invalid")
        if self.score.topic_priority_policy != self.candidate.topic_priority_policy:
            raise ValueError("weekly candidate priority policy projection changed")

    @property
    def is_governed_eligible(self) -> bool:
        return self.score.eligible and not self.score.veto_codes

    @property
    def official_authority(self) -> str | None:
        if self.organization_type == "government":
            return "stored_government_organization_type"
        if self.candidate.topic_priority_policy in _AUTHENTICATED_OFFICIAL_POLICIES:
            return "authenticated_topic_priority_policy"
        return None


@dataclass(frozen=True, slots=True)
class WeeklyArticleSelection:
    role: WeeklyArticleRole
    event_id: UUID
    event_version_id: UUID
    event_time: datetime
    source_metadata_fingerprint: str
    organization_type: str
    official_authority: str | None
    selection_reason: WeeklySelectionReason
    affinity_reasons: tuple[str, ...]
    governed_total: float
    governed_score_version: str

    def __post_init__(self) -> None:
        if self.event_time.tzinfo is None:
            raise ValueError("weekly selected event time must be timezone-aware")
        if not self.organization_type.strip() or len(self.organization_type) > 80:
            raise ValueError("weekly selected organization type is invalid")
        if len(self.source_metadata_fingerprint) != 64 or any(
            char not in "0123456789abcdef" for char in self.source_metadata_fingerprint
        ):
            raise ValueError("weekly selected source metadata fingerprint is invalid")
        if not self.governed_score_version.strip() or len(self.governed_score_version) > 80:
            raise ValueError("weekly selected governed score version is invalid")
        if not math.isfinite(self.governed_total):
            raise ValueError("weekly selected governed total must be finite")
        if self.official_authority not in _OFFICIAL_AUTHORITY_PROJECTIONS | {None}:
            raise ValueError("weekly selected official authority is invalid")
        if len(set(self.affinity_reasons)) != len(self.affinity_reasons) or any(
            not value.strip() or len(value) > 100 for value in self.affinity_reasons
        ):
            raise ValueError("weekly selected affinity reasons are invalid")
        if self.role is WeeklyArticleRole.OFFICIAL_ANCHOR:
            official_reasons = {
                WeeklySelectionReason.OFFICIAL_CURRENT_WINDOW,
                WeeklySelectionReason.OFFICIAL_LOOKBACK,
            }
            if self.selection_reason not in official_reasons | {
                WeeklySelectionReason.OFFICIAL_UNAVAILABLE_FALLBACK
            }:
                raise ValueError("weekly official selection reason is invalid")
            if self.selection_reason in official_reasons and self.official_authority is None:
                raise ValueError("weekly official selection requires stored source authority")
            if (
                self.selection_reason is WeeklySelectionReason.OFFICIAL_UNAVAILABLE_FALLBACK
                and self.official_authority is not None
            ):
                raise ValueError("weekly official fallback cannot claim official authority")
            if self.affinity_reasons:
                raise ValueError("weekly official selection cannot claim role affinity")
        elif self.selection_reason not in {
            WeeklySelectionReason.ROLE_AFFINITY,
            WeeklySelectionReason.ROLE_AFFINITY_UNAVAILABLE,
        }:
            raise ValueError("weekly non-official role selection reason is invalid")
        elif (self.selection_reason is WeeklySelectionReason.ROLE_AFFINITY) != bool(
            self.affinity_reasons
        ):
            raise ValueError("weekly role affinity reason projection is inconsistent")


@dataclass(frozen=True, slots=True)
class WeeklyEditionSelection:
    week_start: date
    timezone: str
    policy_version: str
    schedule_fingerprint: str
    selected: tuple[WeeklyArticleSelection, WeeklyArticleSelection, WeeklyArticleSelection]

    def __post_init__(self) -> None:
        if self.week_start.weekday() != 0:
            raise ValueError("weekly edition selection week_start must be a Monday")
        if self.timezone != WEEKLY_EDITION_TIMEZONE:
            raise ValueError("weekly edition selection timezone must be Asia/Shanghai")
        if self.policy_version != WEEKLY_EDITION_SELECTION_VERSION:
            raise ValueError("unsupported weekly edition selection policy")
        if len(self.schedule_fingerprint) != 64 or any(
            char not in "0123456789abcdef" for char in self.schedule_fingerprint
        ):
            raise ValueError("weekly edition schedule fingerprint is invalid")
        if tuple(item.role.value for item in self.selected) != WEEKLY_EDITION_ROLE_ORDER:
            raise ValueError("weekly edition role order changed")
        if len({item.event_id for item in self.selected}) != 3:
            raise ValueError("weekly edition cannot repeat an event")
        if len({item.event_version_id for item in self.selected}) != 3:
            raise ValueError("weekly edition cannot repeat an event version")
        if any(item.event_time.tzinfo is None for item in self.selected):
            raise ValueError("weekly edition selected event times must be timezone-aware")

    @property
    def fingerprint(self) -> str:
        return _fingerprint(
            self.policy_version,
            self.week_start.isoformat(),
            self.timezone,
            self.schedule_fingerprint,
            tuple(
                (
                    item.role.value,
                    str(item.event_id),
                    str(item.event_version_id),
                    item.event_time.isoformat(),
                    item.source_metadata_fingerprint,
                    item.organization_type,
                    item.official_authority,
                    item.selection_reason.value,
                    item.affinity_reasons,
                    item.governed_total,
                    item.governed_score_version,
                )
                for item in self.selected
            ),
        )


def select_weekly_articles(
    candidates: tuple[WeeklyGovernedCandidate, ...],
    *,
    week_start: date,
    cutoff: datetime,
    schedule: WeeklyEditionSchedule,
) -> WeeklyEditionSelection:
    """Assign exactly three eligible events without changing governance truth."""

    if cutoff.tzinfo is None:
        raise ValueError("weekly edition cutoff must be timezone-aware")
    if week_start.weekday() != 0:
        raise ValueError("weekly edition week_start must be a Monday")
    if week_start_for(cutoff, timezone=schedule.timezone) != week_start:
        raise ValueError("weekly edition cutoff and week_start disagree")
    event_ids = {item.candidate.event_id for item in candidates}
    version_ids = {item.candidate.event_version_id for item in candidates}
    if len(event_ids) != len(candidates) or len(version_ids) != len(candidates):
        raise ValueError("weekly edition candidates must have distinct event/version identities")

    local_cutoff = cutoff.astimezone(ZoneInfo(schedule.timezone))
    current_floor = local_cutoff - timedelta(days=7)
    lookback_floor = local_cutoff - timedelta(days=14)
    eligible = tuple(
        item
        for item in candidates
        if item.is_governed_eligible
        and lookback_floor
        <= item.candidate.event_time.astimezone(ZoneInfo(schedule.timezone))
        <= local_cutoff
    )
    current = tuple(
        item
        for item in eligible
        if item.candidate.event_time.astimezone(ZoneInfo(schedule.timezone)) >= current_floor
    )
    selected: list[WeeklyArticleSelection] = []
    used: set[UUID] = set()
    official_current = tuple(item for item in current if item.official_authority is not None)
    official_lookback = tuple(item for item in eligible if item.official_authority is not None)
    if not current and not official_lookback:
        raise ValueError("weekly edition has no eligible candidates in the bounded windows")
    if official_current:
        official = min(official_current, key=_governed_ordering_key)
        official_reason = WeeklySelectionReason.OFFICIAL_CURRENT_WINDOW
    elif official_lookback:
        official = min(official_lookback, key=_governed_ordering_key)
        official_reason = WeeklySelectionReason.OFFICIAL_LOOKBACK
    else:
        official = min(current, key=_governed_ordering_key)
        official_reason = WeeklySelectionReason.OFFICIAL_UNAVAILABLE_FALLBACK
    selected.append(
        _project_selection(WeeklyArticleRole.OFFICIAL_ANCHOR, official, official_reason)
    )
    used.add(official.candidate.event_id)

    if len(tuple(item for item in current if item.candidate.event_id not in used)) < 2:
        raise ValueError(
            "weekly edition requires two distinct current-window industry/application candidates"
        )

    for role in (WeeklyArticleRole.INDUSTRY_TREND, WeeklyArticleRole.APPLICATION_CASE):
        remaining = tuple(item for item in current if item.candidate.event_id not in used)
        if not remaining:
            raise ValueError("weekly edition has insufficient distinct eligible candidates")
        ranked = sorted(remaining, key=lambda item: _role_ordering_key(item, role=role))
        chosen = ranked[0]
        affinity_reasons = _role_affinity_reasons(chosen, role=role)
        reason = (
            WeeklySelectionReason.ROLE_AFFINITY
            if affinity_reasons
            else WeeklySelectionReason.ROLE_AFFINITY_UNAVAILABLE
        )
        selected.append(
            _project_selection(
                role,
                chosen,
                reason,
                affinity_reasons=affinity_reasons,
            )
        )
        used.add(chosen.candidate.event_id)

    return WeeklyEditionSelection(
        week_start=week_start,
        timezone=schedule.timezone,
        policy_version=WEEKLY_EDITION_SELECTION_VERSION,
        schedule_fingerprint=schedule.fingerprint,
        selected=(selected[0], selected[1], selected[2]),
    )


def weekly_selection_projection(selection: WeeklyEditionSelection) -> dict[str, object]:
    return {
        "week_start": selection.week_start.isoformat(),
        "timezone": selection.timezone,
        "policy_version": selection.policy_version,
        "schedule_fingerprint": selection.schedule_fingerprint,
        "selection_fingerprint": selection.fingerprint,
        "selected": [
            {
                "role": item.role.value,
                "event_id": str(item.event_id),
                "event_version_id": str(item.event_version_id),
                "event_time": item.event_time.isoformat(),
                "source_metadata_fingerprint": item.source_metadata_fingerprint,
                "organization_type": item.organization_type,
                "official_authority": item.official_authority,
                "selection_reason": item.selection_reason.value,
                "affinity_reasons": list(item.affinity_reasons),
                "governed_total": item.governed_total,
                "governed_score_version": item.governed_score_version,
            }
            for item in selection.selected
        ],
    }


def weekly_selection_from_projection(payload: object) -> WeeklyEditionSelection:
    if not isinstance(payload, dict) or set(payload) != {
        "week_start",
        "timezone",
        "policy_version",
        "schedule_fingerprint",
        "selection_fingerprint",
        "selected",
    }:
        raise ValueError("weekly selection projection fields changed")
    rows = payload["selected"]
    if not isinstance(rows, list) or len(rows) != 3:
        raise ValueError("weekly selection projection requires exactly three rows")
    items: list[WeeklyArticleSelection] = []
    expected_fields = {
        "role",
        "event_id",
        "event_version_id",
        "event_time",
        "source_metadata_fingerprint",
        "organization_type",
        "official_authority",
        "selection_reason",
        "affinity_reasons",
        "governed_total",
        "governed_score_version",
    }
    for row in rows:
        if not isinstance(row, dict) or set(row) != expected_fields:
            raise ValueError("weekly selection row fields changed")
        affinity = row["affinity_reasons"]
        if not isinstance(affinity, list) or not all(isinstance(value, str) for value in affinity):
            raise ValueError("weekly selection affinity reasons are invalid")
        official_authority = row["official_authority"]
        if official_authority is not None and not isinstance(official_authority, str):
            raise ValueError("weekly selection official authority is invalid")
        items.append(
            WeeklyArticleSelection(
                role=WeeklyArticleRole(str(row["role"])),
                event_id=UUID(str(row["event_id"])),
                event_version_id=UUID(str(row["event_version_id"])),
                event_time=datetime.fromisoformat(str(row["event_time"])),
                source_metadata_fingerprint=str(row["source_metadata_fingerprint"]),
                organization_type=str(row["organization_type"]),
                official_authority=official_authority,
                selection_reason=WeeklySelectionReason(str(row["selection_reason"])),
                affinity_reasons=tuple(affinity),
                governed_total=float(str(row["governed_total"])),
                governed_score_version=str(row["governed_score_version"]),
            )
        )
    selection = WeeklyEditionSelection(
        week_start=date.fromisoformat(str(payload["week_start"])),
        timezone=str(payload["timezone"]),
        policy_version=str(payload["policy_version"]),
        schedule_fingerprint=str(payload["schedule_fingerprint"]),
        selected=(items[0], items[1], items[2]),
    )
    if payload["selection_fingerprint"] != selection.fingerprint:
        raise ValueError("weekly selection projection fingerprint changed")
    return selection


def _role_affinity_reasons(
    item: WeeklyGovernedCandidate,
    *,
    role: WeeklyArticleRole,
) -> tuple[str, ...]:
    candidate = item.candidate
    reasons: list[str] = []
    if role is WeeklyArticleRole.INDUSTRY_TREND:
        if (
            candidate.science_tech_editorial_cohort
            is ScienceTechEditorialCohort.FRONTIER_SCIENCE_TECHNOLOGY
        ):
            reasons.append("frontier_science_technology_cohort")
        if set(candidate.science_tech_content_signals) & _INDUSTRY_SIGNALS:
            reasons.append("stored_industry_progress_signal")
        if set(candidate.product_matrix_v2_direction_ids) & _INDUSTRY_DIRECTIONS:
            reasons.append("stored_ai_robotics_direction")
        if candidate.frontier_significance >= 0.7:
            reasons.append("high_frontier_significance")
    elif role is WeeklyArticleRole.APPLICATION_CASE:
        if (
            candidate.science_tech_editorial_cohort
            is ScienceTechEditorialCohort.SCIENCE_TECHNOLOGY_EDUCATION_PRIORITY
        ):
            reasons.append("science_technology_education_cohort")
        if set(candidate.science_tech_editorial_reason_codes) & _APPLICATION_REASONS:
            reasons.append("stored_school_or_practice_reason")
        if set(candidate.product_matrix_v2_direction_ids) & _APPLICATION_DIRECTIONS:
            reasons.append("stored_school_pathway_direction")
    return tuple(reasons)


def _role_ordering_key(
    item: WeeklyGovernedCandidate,
    *,
    role: WeeklyArticleRole,
) -> tuple[int, int, float, float, float, str]:
    affinity = len(_role_affinity_reasons(item, role=role))
    candidate = item.candidate
    return (
        -affinity,
        0 if item.score.priority_applied else 1,
        -item.score.total,
        -candidate.source_trust,
        -candidate.event_time.timestamp(),
        str(candidate.event_id),
    )


def _governed_ordering_key(
    item: WeeklyGovernedCandidate,
) -> tuple[int, float, float, float, str]:
    candidate = item.candidate
    return (
        0 if item.score.priority_applied else 1,
        -item.score.total,
        -candidate.source_trust,
        -candidate.event_time.timestamp(),
        str(candidate.event_id),
    )


def _project_selection(
    role: WeeklyArticleRole,
    item: WeeklyGovernedCandidate,
    reason: WeeklySelectionReason,
    *,
    affinity_reasons: tuple[str, ...] = (),
) -> WeeklyArticleSelection:
    return WeeklyArticleSelection(
        role=role,
        event_id=item.candidate.event_id,
        event_version_id=item.candidate.event_version_id,
        event_time=item.candidate.event_time,
        source_metadata_fingerprint=item.source_metadata_fingerprint,
        organization_type=item.organization_type,
        official_authority=item.official_authority,
        selection_reason=reason,
        affinity_reasons=affinity_reasons,
        governed_total=item.score.total,
        governed_score_version=item.score.scoring_version,
    )


def _fingerprint(*values: object) -> str:
    payload = json.dumps(
        values,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _is_safe_operator_reference(value: str) -> bool:
    return (
        value == value.strip()
        and 1 <= len(value) <= 80
        and value[0].isalnum()
        and all(char.isalnum() or char in "._:-" for char in value)
    )


def _is_wechat_publication_url(value: str | None) -> bool:
    if (
        value is None
        or value != value.strip()
        or len(value) > 500
        or not value.isascii()
        or any(ord(char) < 0x21 or ord(char) > 0x7E for char in value)
    ):
        return False
    try:
        parsed = urlparse(value)
        host_and_port_are_safe = parsed.hostname == "mp.weixin.qq.com" and parsed.port is None
    except ValueError:
        return False
    article_path = (parsed.path.startswith("/s/") and len(parsed.path) > 3) or (
        parsed.path == "/s" and bool(parsed.query)
    )
    return bool(
        parsed.scheme == "https"
        and host_and_port_are_safe
        and parsed.username is None
        and parsed.password is None
        and article_path
        and parsed.params == ""
        and parsed.fragment == ""
    )
