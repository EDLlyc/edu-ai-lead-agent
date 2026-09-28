"""Typed projection of one business day of production outcomes for the quality report."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True, slots=True)
class SlotRunRow:
    content_slot: str
    status: str
    scoring_version: str | None
    selected_count: int
    unfilled_count: int
    unfilled_reason_codes: tuple[str, ...]
    error_code: str | None


@dataclass(frozen=True, slots=True)
class SelectedTopicRow:
    content_slot: str
    ordinal: int
    title: str
    priority_reason: str | None
    education_policy_level: str | None
    cohort: str | None
    summary: str | None = None
    human_pick: bool = False


@dataclass(frozen=True, slots=True)
class SameTopicPair:
    """Two same-day selections that the same-topic rule would treat as one story."""

    left: str
    right: str


@dataclass(frozen=True, slots=True)
class BrandUsageRow:
    label: str
    runs: int


@dataclass(frozen=True, slots=True)
class BrandStatementRow:
    """One brand statement of an accepted copy; `label` is e.g. "morning#1" when slotted."""

    run_id: str
    business_date: date
    label: str | None
    text: str


@dataclass(frozen=True, slots=True)
class ModelUsage:
    calls: int = 0
    failed_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    average_latency_ms: int | None = None

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens


@dataclass(slots=True)
class QualitySnapshot:
    business_date: date
    timezone: str
    lookback_days: int
    acquisition_runs: int = 0
    acquisition_new_items: int = 0
    acquisition_failed_jobs: int = 0
    acquisition_error_codes: Counter[str] = field(default_factory=Counter)
    acquisition_failed_sources: Counter[str] = field(default_factory=Counter)
    slot_runs: list[SlotRunRow] = field(default_factory=list)
    selected_topics: list[SelectedTopicRow] = field(default_factory=list)
    same_topic_pairs: list[SameTopicPair] = field(default_factory=list)
    copy_status: Counter[str] = field(default_factory=Counter)
    copy_prompt_versions: Counter[str] = field(default_factory=Counter)
    copy_first_pass_accepted: int = 0
    copy_error_codes: Counter[str] = field(default_factory=Counter)
    copy_issue_codes: Counter[str] = field(default_factory=Counter)
    brand_window_accepted_runs: int = 0
    brand_usage: list[BrandUsageRow] = field(default_factory=list)
    brand_statements: list[BrandStatementRow] = field(default_factory=list)
    image_status: Counter[str] = field(default_factory=Counter)
    image_repairs: int = 0
    delivery_status: Counter[str] = field(default_factory=Counter)
    delivery_error_codes: Counter[str] = field(default_factory=Counter)
    infographic_status: Counter[str] = field(default_factory=Counter)
    infographic_error_codes: Counter[str] = field(default_factory=Counter)
    supplement_status: Counter[str] = field(default_factory=Counter)
    official_account_draft_status: Counter[str] = field(default_factory=Counter)
    copy_model_usage: ModelUsage = field(default_factory=ModelUsage)
    governance_model_usage: ModelUsage = field(default_factory=ModelUsage)
