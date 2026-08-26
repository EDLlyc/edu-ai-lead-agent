"""Development-only exact-target selection over the durable governed topic pool."""

from __future__ import annotations

import argparse
import asyncio
import json
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime
from typing import Literal, Protocol
from uuid import UUID

from app.application.ports.topic_selection import ClaimedTopicSelectionJob
from app.application.services.topic_selection import build_topic_scoring_config
from app.core.config import Settings, get_settings
from app.domain.topic_rerank import TopicRerankConfig
from app.domain.topic_selection import (
    DailyTopicDecision,
    TopicCandidate,
    TopicScoringConfig,
    select_daily_topic,
)
from app.infrastructure.db.session import create_engine, create_session_factory
from app.infrastructure.db.topic_selection import PostgresTopicSelectionRepository

LOCAL_EXACT_TARGET_PROFILE = "local_exact_target"
LOCAL_EXACT_TARGET_RULE_VERSION = "local-exact-target-selection-v1"
LOCAL_EXACT_TARGET_THRESHOLD = 0.0
LOCAL_EXACT_TARGET_BOUNDARY = "LOCAL ONLY · exact governed target · not published"


class LocalExactTargetRepository(Protocol):
    async def enqueue(
        self,
        *,
        business_date: date,
        timezone: str,
        config: TopicScoringConfig,
        rerank_config: TopicRerankConfig,
        governed_event_cutoff: datetime,
        trigger: str = "manual",
    ) -> UUID: ...

    async def claim_for_run(
        self,
        *,
        run_id: UUID,
        worker_id: str,
        lease_seconds: int,
        max_attempts: int = 3,
    ) -> ClaimedTopicSelectionJob | None: ...

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


@dataclass(frozen=True, slots=True)
class LocalExactTargetSelectionResult:
    run_id: UUID
    event_id: UUID
    event_version_id: UUID
    scoring_profile: Literal["local_exact_target"]
    rule_version: Literal["local-exact-target-selection-v1"]
    threshold: float
    governed_candidate_count: int
    local_only: Literal[True]
    published: Literal[False]
    provider_call_count: Literal[0]
    boundary_label: str


def local_exact_target_config(settings: Settings) -> TopicScoringConfig:
    """Create the frozen local-acceptance config without changing production defaults."""

    return replace(
        build_topic_scoring_config(settings),
        profile=LOCAL_EXACT_TARGET_PROFILE,
        selection_priority_rule_version=LOCAL_EXACT_TARGET_RULE_VERSION,
        threshold=LOCAL_EXACT_TARGET_THRESHOLD,
    )


def local_exact_target_rerank_config() -> TopicRerankConfig:
    """Disable every model path for an explicit operator selection."""

    return TopicRerankConfig(
        enabled=False,
        provider="disabled",
        model="none",
    )


async def select_local_exact_target(
    repository: LocalExactTargetRepository,
    settings: Settings,
    *,
    event_id: UUID,
    business_date: date,
    now: datetime,
) -> LocalExactTargetSelectionResult:
    if settings.app_env != "development":
        raise RuntimeError("local exact-target selection is development-only")
    if now.tzinfo is None:
        raise ValueError("local exact-target selection time must be timezone-aware")
    config = local_exact_target_config(settings)
    run_id = await repository.enqueue(
        business_date=business_date,
        timezone=settings.business_timezone,
        config=config,
        rerank_config=local_exact_target_rerank_config(),
        governed_event_cutoff=now.astimezone(UTC),
        trigger="manual",
    )
    claimed = await repository.claim_for_run(
        run_id=run_id,
        worker_id="local-exact-target-selection",
        lease_seconds=settings.content_lease_seconds,
        max_attempts=settings.content_max_attempts,
    )
    if claimed is None:
        raise RuntimeError("local exact-target selection run is not claimable")
    candidates = await repository.load_candidates(run_id)
    matches = tuple(candidate for candidate in candidates if candidate.event_id == event_id)
    if len(matches) != 1:
        await repository.fail(claimed=claimed, error_code="exact_target_not_governed")
        raise ValueError("exact target must occur once in the governed candidate pool")
    decision = select_daily_topic(
        matches,
        as_of=claimed.cutoff_at,
        config=config,
    )
    if decision.selected_event_id != event_id or decision.selected_event_version_id is None:
        await repository.fail(claimed=claimed, error_code="exact_target_not_eligible")
        raise ValueError("exact target is not eligible under the local acceptance config")
    if not await repository.persist_decision(
        claimed=claimed,
        config=config,
        decision=decision,
    ):
        raise RuntimeError("local exact-target selection lost its durable lease")
    if not await repository.complete(claimed=claimed):
        raise RuntimeError("local exact-target selection could not complete")
    return LocalExactTargetSelectionResult(
        run_id=run_id,
        event_id=event_id,
        event_version_id=decision.selected_event_version_id,
        scoring_profile=LOCAL_EXACT_TARGET_PROFILE,
        rule_version=LOCAL_EXACT_TARGET_RULE_VERSION,
        threshold=LOCAL_EXACT_TARGET_THRESHOLD,
        governed_candidate_count=len(candidates),
        local_only=True,
        published=False,
        provider_call_count=0,
        boundary_label=LOCAL_EXACT_TARGET_BOUNDARY,
    )


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Select one exact governed event for development-only local acceptance."
    )
    parser.add_argument("--event-id", required=True, type=UUID)
    parser.add_argument("--business-date", required=True, type=date.fromisoformat)
    return parser.parse_args()


async def _run() -> None:
    args = _parse_args()
    settings = get_settings()
    engine = create_engine(settings)
    try:
        result = await select_local_exact_target(
            PostgresTopicSelectionRepository(create_session_factory(engine)),
            settings,
            event_id=args.event_id,
            business_date=args.business_date,
            now=datetime.now(UTC),
        )
        print(json.dumps(asdict(result), ensure_ascii=False, default=str, sort_keys=True))
    finally:
        await engine.dispose()


def main() -> None:
    asyncio.run(_run())


if __name__ == "__main__":
    main()
