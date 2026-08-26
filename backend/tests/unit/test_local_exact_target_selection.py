from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from app.application.ports.topic_selection import ClaimedTopicSelectionJob
from app.core.config import Settings
from app.domain.editorial_relevance import (
    ScienceTechContentSignal,
    ScienceTechEditorialCohort,
)
from app.domain.topic_selection import DailyTopicDecision, TopicCandidate
from app.local_exact_target_selection import (
    LOCAL_EXACT_TARGET_BOUNDARY,
    LOCAL_EXACT_TARGET_PROFILE,
    LOCAL_EXACT_TARGET_RULE_VERSION,
    select_local_exact_target,
)


def _candidate(event_id: UUID, *, governed: bool = True) -> TopicCandidate:
    return TopicCandidate(
        event_id=event_id,
        event_version_id=uuid4(),
        event_time=datetime.now(UTC) - timedelta(days=1),
        source_trust=1.0,
        source_diversity=1,
        ai_relevance=1.0,
        parent_relevance=0.58,
        communication_potential=0.83,
        editorial_priority=0.82,
        science_tech_editorial_cohort=ScienceTechEditorialCohort.FRONTIER_SCIENCE_TECHNOLOGY,
        frontier_significance=0.82,
        science_tech_editorial_reason_codes=("hard_tech_topic_with_completed_progress",),
        science_tech_content_signals=(ScienceTechContentSignal.COMPLETED_PROGRESS,),
        priority_title="科学家首次利用暗腔实现真空涨落增强超导",
        priority_summary="已治理的科技新闻摘要。",
        governance_resolved=governed,
        has_eligible_evidence=True,
    )


class _Repository:
    def __init__(self, candidates: tuple[TopicCandidate, ...]) -> None:
        self.run_id = uuid4()
        self.job_id = uuid4()
        self.lease_token = uuid4()
        self.candidates = candidates
        self.enqueued = None
        self.persisted: DailyTopicDecision | None = None
        self.completed = False
        self.failure_code: str | None = None

    async def enqueue(self, **kwargs) -> UUID:
        self.enqueued = kwargs
        return self.run_id

    async def claim_for_run(self, **kwargs) -> ClaimedTopicSelectionJob:
        assert kwargs["run_id"] == self.run_id
        return ClaimedTopicSelectionJob(
            job_id=self.job_id,
            run_id=self.run_id,
            attempt_number=1,
            lease_token=self.lease_token,
            business_date=date(2026, 8, 25),
            timezone="Asia/Shanghai",
            cutoff_at=datetime.now(UTC),
        )

    async def load_candidates(self, run_id: UUID) -> tuple[TopicCandidate, ...]:
        assert run_id == self.run_id
        return self.candidates

    async def persist_decision(self, **kwargs) -> bool:
        self.persisted = kwargs["decision"]
        return True

    async def complete(self, **kwargs) -> bool:
        self.completed = True
        return True

    async def fail(self, **kwargs) -> bool:
        self.failure_code = kwargs["error_code"]
        return True


def _settings() -> Settings:
    return Settings(_env_file=None, app_env="development")


@pytest.mark.asyncio
async def test_exact_target_filters_governed_pool_and_persists_without_rerank() -> None:
    target = uuid4()
    repository = _Repository((_candidate(uuid4()), _candidate(target), _candidate(uuid4())))

    result = await select_local_exact_target(
        repository,
        _settings(),
        event_id=target,
        business_date=date(2026, 8, 25),
        now=datetime.now(UTC),
    )

    assert repository.enqueued["config"].profile == LOCAL_EXACT_TARGET_PROFILE
    assert repository.enqueued["config"].selection_priority_rule_version == (
        LOCAL_EXACT_TARGET_RULE_VERSION
    )
    assert repository.enqueued["config"].threshold == 0.0
    assert repository.enqueued["rerank_config"].enabled is False
    assert repository.enqueued["rerank_config"].provider == "disabled"
    assert repository.persisted is not None
    assert len(repository.persisted.scores) == 1
    assert repository.persisted.selected_event_id == target
    assert repository.completed is True
    assert result.local_only is True
    assert result.published is False
    assert result.provider_call_count == 0
    assert result.boundary_label == LOCAL_EXACT_TARGET_BOUNDARY
    assert result.governed_candidate_count == 3


@pytest.mark.asyncio
async def test_exact_target_fails_closed_when_missing_or_ineligible() -> None:
    missing_repository = _Repository((_candidate(uuid4()),))
    with pytest.raises(ValueError, match="must occur once"):
        await select_local_exact_target(
            missing_repository,
            _settings(),
            event_id=uuid4(),
            business_date=date(2026, 8, 25),
            now=datetime.now(UTC),
        )
    assert missing_repository.failure_code == "exact_target_not_governed"

    target = uuid4()
    ineligible_repository = _Repository((_candidate(target, governed=False),))
    with pytest.raises(ValueError, match="not eligible"):
        await select_local_exact_target(
            ineligible_repository,
            _settings(),
            event_id=target,
            business_date=date(2026, 8, 25),
            now=datetime.now(UTC),
        )
    assert ineligible_repository.failure_code == "exact_target_not_eligible"
