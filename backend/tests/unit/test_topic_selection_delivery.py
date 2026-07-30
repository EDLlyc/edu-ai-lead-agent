from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from app.application.ports.topic_selection import ClaimedTopicSelectionJob
from app.application.services.topic_selection import (
    TopicSelectionExecutor,
    enqueue_manual_topic_selection,
    reconcile_daily_topic_selection,
)
from app.core.config import Settings
from app.domain.topic_selection import (
    DailyTopicDecision,
    TopicCandidate,
    TopicScoringConfig,
)

NOW = datetime(2026, 7, 30, 1, 0, tzinfo=UTC)
RUN_ID = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
JOB_ID = UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb")
LEASE_TOKEN = UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")


class FakeTopicSelectionRepository:
    def __init__(self, candidates: tuple[TopicCandidate, ...] = ()) -> None:
        self.config = TopicScoringConfig()
        self.candidates = candidates
        self.claimed: ClaimedTopicSelectionJob | None = ClaimedTopicSelectionJob(
            job_id=JOB_ID,
            run_id=RUN_ID,
            attempt_number=1,
            lease_token=LEASE_TOKEN,
            business_date=date(2026, 7, 30),
            timezone="Asia/Shanghai",
            cutoff_at=NOW,
        )
        self.enqueued: dict[str, object] | None = None
        self.persisted: DailyTopicDecision | None = None
        self.completed = False
        self.failed_code: str | None = None

    async def enqueue(
        self,
        *,
        business_date: date,
        timezone: str,
        config: TopicScoringConfig,
        governed_event_cutoff: datetime,
        trigger: str = "manual",
    ) -> UUID:
        self.enqueued = {
            "business_date": business_date,
            "timezone": timezone,
            "config": config,
            "governed_event_cutoff": governed_event_cutoff,
            "trigger": trigger,
        }
        return RUN_ID

    async def claim(
        self, *, worker_id: str, lease_seconds: int, max_attempts: int
    ) -> ClaimedTopicSelectionJob | None:
        assert worker_id
        assert lease_seconds > 0
        assert max_attempts > 0
        claimed, self.claimed = self.claimed, None
        return claimed

    async def heartbeat(self, *, claimed: ClaimedTopicSelectionJob, lease_seconds: int) -> bool:
        return claimed.run_id == RUN_ID and lease_seconds > 0

    async def load_config(self, run_id: UUID) -> TopicScoringConfig:
        assert run_id == RUN_ID
        return self.config

    async def load_candidates(self, run_id: UUID) -> tuple[TopicCandidate, ...]:
        assert run_id == RUN_ID
        return self.candidates

    async def persist_decision(
        self,
        *,
        claimed: ClaimedTopicSelectionJob,
        config: TopicScoringConfig,
        decision: DailyTopicDecision,
    ) -> bool:
        assert claimed.run_id == RUN_ID
        assert config == self.config
        self.persisted = decision
        return True

    async def complete(self, *, claimed: ClaimedTopicSelectionJob) -> bool:
        assert claimed.run_id == RUN_ID
        self.completed = True
        return True

    async def fail(self, *, claimed: ClaimedTopicSelectionJob, error_code: str) -> bool:
        assert claimed.run_id == RUN_ID
        self.failed_code = error_code
        return True


def _candidate() -> TopicCandidate:
    return TopicCandidate(
        event_id=UUID("11111111-1111-4111-8111-111111111111"),
        event_version_id=UUID("22222222-2222-4222-8222-222222222222"),
        event_time=NOW,
        source_trust=1.0,
        source_diversity=4,
        ai_relevance=1.0,
        parent_relevance=1.0,
        communication_potential=1.0,
    )


@pytest.mark.asyncio
async def test_manual_enqueue_uses_shanghai_business_date_and_preview_config() -> None:
    repository = FakeTopicSelectionRepository()

    run_id = await enqueue_manual_topic_selection(
        repository,
        Settings(),
        business_date=None,
        now=NOW,
    )

    assert run_id == RUN_ID
    assert repository.enqueued is not None
    assert repository.enqueued["business_date"] == date(2026, 7, 30)
    assert repository.enqueued["governed_event_cutoff"] == NOW
    assert repository.enqueued["trigger"] == "manual"
    config = repository.enqueued["config"]
    assert isinstance(config, TopicScoringConfig)
    assert config.version == "scoring-v1-preview.1"


@pytest.mark.asyncio
async def test_scheduler_only_enqueues_inside_the_configured_catchup_window() -> None:
    repository = FakeTopicSelectionRepository()
    settings = Settings(content_schedule_hour=7, content_schedule_minute=30)

    before = await reconcile_daily_topic_selection(
        repository,
        settings,
        now=datetime(2026, 7, 29, 23, 0, tzinfo=UTC),
    )
    due = await reconcile_daily_topic_selection(
        repository,
        settings,
        now=datetime(2026, 7, 30, 0, 0, tzinfo=UTC),
    )

    assert before is None
    assert due == RUN_ID
    assert repository.enqueued is not None
    assert repository.enqueued["trigger"] == "scheduled"


@pytest.mark.asyncio
async def test_worker_persists_one_selected_topic_and_completes_the_job() -> None:
    repository = FakeTopicSelectionRepository((_candidate(),))
    executor = TopicSelectionExecutor(repository, Settings())

    assert await executor.execute_next("topic-worker-1") is True

    assert repository.persisted is not None
    assert repository.persisted.selected_event_id == _candidate().event_id
    assert repository.persisted.no_topic_code is None
    assert repository.completed is True
    assert repository.failed_code is None


@pytest.mark.asyncio
async def test_worker_persists_no_topic_and_does_not_invent_a_selection() -> None:
    repository = FakeTopicSelectionRepository()
    executor = TopicSelectionExecutor(repository, Settings())

    assert await executor.execute_next("topic-worker-1") is True

    assert repository.persisted is not None
    assert repository.persisted.is_no_topic is True
    assert repository.persisted.no_topic_code is not None
    assert repository.completed is True
