from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from app.application.ports.topic_selection import ClaimedTopicSelectionJob
from app.application.services.topic_selection import (
    TopicSelectionExecutor,
    build_topic_scoring_config,
    enqueue_manual_topic_selection,
    reconcile_daily_topic_selection,
)
from app.core.config import Settings
from app.core.errors import ConflictError
from app.domain.editorial_relevance import ScienceTechEditorialCohort
from app.domain.topic_rerank import TopicRerankConfig, TopicRerankOutcome
from app.domain.topic_selection import (
    DEFAULT_TOPIC_SCORING_THRESHOLD,
    DEFAULT_TOPIC_SCORING_VERSION,
    DELIVERED_CONTENT_VETO_RULE_VERSION,
    DELIVERED_HISTORY_TOPIC_SCORING_VERSION,
    HISTORICAL_TOPIC_SCORING_THRESHOLD,
    THRESHOLD_059_TOPIC_SCORING_VERSION,
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
        self.rerank_config = TopicRerankConfig()
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
        self.readiness_cutoff: datetime | None = NOW
        self.enqueue_conflict = False

    async def governed_event_cutoff(
        self, *, business_date: date, timezone: str, now: datetime
    ) -> datetime | None:
        assert business_date
        assert timezone
        assert now.tzinfo is not None
        return self.readiness_cutoff

    async def enqueue(
        self,
        *,
        business_date: date,
        timezone: str,
        config: TopicScoringConfig,
        rerank_config: TopicRerankConfig,
        governed_event_cutoff: datetime,
        trigger: str = "manual",
    ) -> UUID:
        if self.enqueue_conflict:
            raise ConflictError("a different scoring config already owns this date")
        self.enqueued = {
            "business_date": business_date,
            "timezone": timezone,
            "config": config,
            "rerank_config": rerank_config,
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

    async def load_rerank_config(self, run_id: UUID) -> TopicRerankConfig:
        assert run_id == RUN_ID
        return self.rerank_config

    async def load_candidates(self, run_id: UUID) -> tuple[TopicCandidate, ...]:
        assert run_id == RUN_ID
        return self.candidates

    async def persist_decision(
        self,
        *,
        claimed: ClaimedTopicSelectionJob,
        config: TopicScoringConfig,
        decision: DailyTopicDecision,
        rerank_outcome: TopicRerankOutcome,
    ) -> bool:
        assert claimed.run_id == RUN_ID
        assert config == self.config
        assert rerank_outcome.provider == "disabled"
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
        science_education_relevance=1.0,
        science_ai_education_eligible=True,
        science_ai_education_reason_codes=("science_ai_topic_with_education_context",),
        product_matrix_fit=1.0,
        editorial_priority=1.0,
        science_tech_editorial_cohort=(
            ScienceTechEditorialCohort.SCIENCE_TECHNOLOGY_EDUCATION_PRIORITY
        ),
        science_tech_education_relevance=1.0,
        science_tech_editorial_reason_codes=("explicit_science_technology_education",),
        product_matrix_fit_v2=1.0,
    )


@pytest.mark.asyncio
async def test_manual_enqueue_uses_shanghai_business_date_and_preview_config() -> None:
    repository = FakeTopicSelectionRepository()

    run_id = await enqueue_manual_topic_selection(
        repository,
        Settings(_env_file=None),
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
    assert config.version == DEFAULT_TOPIC_SCORING_VERSION
    assert config.threshold == DEFAULT_TOPIC_SCORING_THRESHOLD
    assert config.effective_veto_rule_version == DELIVERED_CONTENT_VETO_RULE_VERSION
    assert config.selection_priority_rule_version == (
        "ministry-education-priority-v4-substantive-science-education"
    )


def test_historical_delivered_scoring_version_keeps_original_threshold() -> None:
    config = build_topic_scoring_config(
        Settings(
            _env_file=None,
            content_scoring_version=DELIVERED_HISTORY_TOPIC_SCORING_VERSION,
            content_selection_priority_rule_version="ministry-education-priority-v3",
        )
    )

    assert config.version == DELIVERED_HISTORY_TOPIC_SCORING_VERSION
    assert config.threshold == HISTORICAL_TOPIC_SCORING_THRESHOLD
    assert config.effective_veto_rule_version == DELIVERED_CONTENT_VETO_RULE_VERSION
    assert config.selection_priority_rule_version == "ministry-education-priority-v3"


def test_historical_point_eight_scoring_version_keeps_point_fifty_nine_threshold() -> None:
    config = build_topic_scoring_config(
        Settings(
            _env_file=None,
            content_scoring_version=THRESHOLD_059_TOPIC_SCORING_VERSION,
            content_selection_priority_rule_version="ministry-education-priority-v3",
        )
    )

    assert config.version == THRESHOLD_059_TOPIC_SCORING_VERSION
    assert config.threshold == DEFAULT_TOPIC_SCORING_THRESHOLD
    assert config.effective_science_tech_editorial_rule_version == "science-tech-editorial-v2"
    assert config.effective_hard_tech_pool_policy_version is None


def test_historical_tiered_scoring_version_keeps_ministry_priority_defaults() -> None:
    config = build_topic_scoring_config(
        Settings(
            _env_file=None,
            content_scoring_version="scoring-v1-preview.6-tiered-science-tech-priority",
            content_selection_priority_rule_version="ministry-education-priority-v3",
        )
    )

    assert config.version == "scoring-v1-preview.6-tiered-science-tech-priority"
    assert config.threshold == HISTORICAL_TOPIC_SCORING_THRESHOLD
    assert config.effective_veto_rule_version == "topic-veto-v3-governed-content"
    assert config.selection_priority_rule_version == "ministry-education-priority-v3"


@pytest.mark.asyncio
async def test_manual_enqueue_rejects_when_governance_is_not_ready() -> None:
    repository = FakeTopicSelectionRepository()
    repository.readiness_cutoff = None

    with pytest.raises(ConflictError, match="governance is not ready"):
        await enqueue_manual_topic_selection(
            repository,
            Settings(),
            business_date=date(2026, 7, 30),
            now=NOW,
        )

    assert repository.enqueued is None


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
async def test_scheduler_skips_a_locked_current_run_without_raising() -> None:
    repository = FakeTopicSelectionRepository()
    repository.enqueue_conflict = True

    run_id = await reconcile_daily_topic_selection(
        repository,
        Settings(content_schedule_hour=7, content_schedule_minute=30),
        now=datetime(2026, 7, 30, 0, 0, tzinfo=UTC),
    )

    assert run_id is None
    assert repository.enqueued is None


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
