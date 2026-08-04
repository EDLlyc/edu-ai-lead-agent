from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

FreshnessStatus = Literal["fresh", "stale", "unknown"]

FRESHNESS_RULE_VERSION = "publication-freshness-v1"


@dataclass(frozen=True, slots=True)
class FreshnessDecision:
    status: FreshnessStatus
    reason_code: str
    cutoff_at: datetime
    published_at: datetime | None
    rule_version: str = FRESHNESS_RULE_VERSION

    @property
    def eligible(self) -> bool:
        return self.status == "fresh"


def evaluate_publication_freshness(
    published_at: datetime | None,
    *,
    evaluated_at: datetime,
    max_age_days: int,
) -> FreshnessDecision:
    if evaluated_at.tzinfo is None:
        raise ValueError("freshness evaluation time must be timezone-aware")
    if max_age_days < 1:
        raise ValueError("freshness window must be positive")
    cutoff_at = evaluated_at - timedelta(days=max_age_days)
    if published_at is None:
        return FreshnessDecision("unknown", "freshness_unknown", cutoff_at, None)
    if published_at.tzinfo is None:
        raise ValueError("publication time must be timezone-aware")
    if published_at >= cutoff_at:
        return FreshnessDecision("fresh", "fresh_within_window", cutoff_at, published_at)
    return FreshnessDecision("stale", "stale_beyond_window", cutoff_at, published_at)
