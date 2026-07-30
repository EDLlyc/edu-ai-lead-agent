from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import pytest
from app.application.ports.governance import (
    EmbeddingRequest,
    FactualAnalysisPassage,
    FactualAnalysisRequest,
    GovernanceCheckpointer,
    GovernanceRepository,
)
from app.application.services import governance_worker as governance_worker_service
from app.application.services.enqueue_governance import enqueue_governance_run
from app.application.services.governance_graph import CompiledGovernanceGraph
from app.application.services.governance_runtime import build_governance_version_bundle
from app.application.services.governance_worker import (
    _finish_heartbeat_task,
    execute_claimed_governance_job,
)
from app.core.config import Settings
from app.core.errors import (
    GovernanceLeaseLostError,
    InvalidProviderOutputError,
    PolicyRejectedError,
    ProviderTimeoutError,
)
from app.domain.governance_entities import (
    ClaimedGovernanceJob,
    GovernanceJobCompletion,
    GovernanceVersionBundle,
)
from app.domain.governance_enums import (
    EmbeddingPurpose,
    GovernanceAttemptResult,
    GovernanceJobStatus,
)
from app.governance_live_smoke import _validate_live_settings
from app.infrastructure.ai.fake import (
    DeterministicFakeEmbeddingModel,
    DeterministicFakeFactualAnalysisModel,
)
from pydantic import SecretStr


def _settings(**updates: object) -> Settings:
    return Settings(_env_file=None, **updates)  # type: ignore[call-arg]


def _analysis_request() -> FactualAnalysisRequest:
    return FactualAnalysisRequest(
        candidate_id=UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"),
        title="人工智能治理平台发布进展",
        published_at=datetime(2026, 7, 29, 9, 0, tzinfo=UTC),
        language="zh-CN",
        passages=(
            FactualAnalysisPassage(
                passage_id=UUID("bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"),
                ordinal=0,
                passage_hash="a" * 64,
                text="人工智能治理平台发布进展, 并公布可核验的实施安排。",
            ),
        ),
        prompt_version="factual-analysis-v1",
        schema_version="factual-analysis-schema-v1",
        taxonomy_version="ai-factual-taxonomy-v1",
        max_output_tokens=1024,
    )


async def test_fake_provider_is_deterministic_fixed_dimension_and_secret_free() -> None:
    analysis_model = DeterministicFakeFactualAnalysisModel(model="fake-chat")
    analysis_first = await analysis_model.analyze(_analysis_request())
    analysis_second = await analysis_model.analyze(_analysis_request())

    assert analysis_first == analysis_second
    assert analysis_first.provider == "fake"
    assert analysis_first.provider_request_id is None
    assert analysis_first.prompt_tokens == analysis_first.completion_tokens == 0

    embedding_model = DeterministicFakeEmbeddingModel(model="fake-embedding")
    near_request = EmbeddingRequest(
        artifact_id=uuid4(),
        purpose=EmbeddingPurpose.NEAR_DUPLICATE,
        input_hash="b" * 64,
        text="同一段受控测试文本",
    )
    near_first = await embedding_model.embed(near_request)
    near_second = await embedding_model.embed(near_request)
    event = await embedding_model.embed(
        EmbeddingRequest(
            artifact_id=near_request.artifact_id,
            purpose=EmbeddingPurpose.EVENT_ASSIGNMENT,
            input_hash=near_request.input_hash,
            text=near_request.text,
        )
    )

    assert near_first == near_second
    assert near_first.dimensions == len(near_first.vector) == 2048
    assert sum(value * value for value in near_first.vector) == pytest.approx(1.0)
    assert near_first.vector != event.vector
    assert near_first.provider_request_id is None
    with pytest.raises(ValueError, match="2048-dimensional"):
        DeterministicFakeEmbeddingModel(model="fake-embedding", dimensions=1024)


class _EnqueueRepository:
    def __init__(self) -> None:
        self.acquisition_calls: list[tuple[UUID, str]] = []
        self.manual_calls: list[tuple[tuple[UUID, ...], str, str]] = []
        self.run_id = uuid4()

    async def create_run_for_acquisition(
        self,
        *,
        acquisition_run_id: UUID,
        bundle: GovernanceVersionBundle,
        timezone: str,
    ) -> UUID:
        self.acquisition_calls.append((acquisition_run_id, bundle.fingerprint))
        return self.run_id

    async def create_manual_run(
        self,
        *,
        candidate_ids: tuple[UUID, ...],
        idempotency_key: str,
        bundle: GovernanceVersionBundle,
        timezone: str,
    ) -> UUID:
        self.manual_calls.append((candidate_ids, idempotency_key, bundle.fingerprint))
        return self.run_id


async def test_enqueue_service_routes_acquisition_and_manual_idempotency() -> None:
    settings = _settings(ai_provider_mode="fake")
    bundle = build_governance_version_bundle(settings)
    repository = _EnqueueRepository()
    acquisition_run_id = uuid4()
    candidate_id = uuid4()

    acquisition_result = await enqueue_governance_run(
        cast(GovernanceRepository, repository),
        settings,
        bundle,
        acquisition_run_id=acquisition_run_id,
        candidate_ids=(),
        idempotency_key=None,
    )
    manual_result = await enqueue_governance_run(
        cast(GovernanceRepository, repository),
        settings,
        bundle,
        acquisition_run_id=None,
        candidate_ids=(candidate_id,),
        idempotency_key="manual-key",
    )

    assert acquisition_result == manual_result == repository.run_id
    assert repository.acquisition_calls == [(acquisition_run_id, bundle.fingerprint)]
    assert repository.manual_calls == [((candidate_id,), "manual-key", bundle.fingerprint)]

    with pytest.raises(PolicyRejectedError, match="cannot include candidate IDs"):
        await enqueue_governance_run(
            cast(GovernanceRepository, repository),
            settings,
            bundle,
            acquisition_run_id=acquisition_run_id,
            candidate_ids=(candidate_id,),
            idempotency_key=None,
        )
    with pytest.raises(PolicyRejectedError, match="Idempotency-Key"):
        await enqueue_governance_run(
            cast(GovernanceRepository, repository),
            settings,
            bundle,
            acquisition_run_id=None,
            candidate_ids=(candidate_id,),
            idempotency_key=None,
        )


class _WorkerRepository:
    def __init__(
        self,
        *,
        completion_succeeds: bool = True,
        lease_lost_before_attempt: bool = False,
        lease_lost_during_attempt_completion: bool = False,
    ) -> None:
        self.attempts: list[dict[str, Any]] = []
        self.completions: list[GovernanceJobCompletion] = []
        self.completion_succeeds = completion_succeeds
        self.lease_lost_before_attempt = lease_lost_before_attempt
        self.lease_lost_during_attempt_completion = lease_lost_during_attempt_completion

    async def create_attempt(self, claimed: ClaimedGovernanceJob, *, stage: str) -> UUID:
        if self.lease_lost_before_attempt:
            raise GovernanceLeaseLostError()
        return UUID("cccccccc-cccc-4ccc-8ccc-cccccccccccc")

    async def heartbeat(self, *, claimed: ClaimedGovernanceJob, lease_seconds: int) -> bool:
        return True

    async def complete_attempt(
        self,
        *,
        claimed: ClaimedGovernanceJob,
        attempt_id: UUID,
        result: GovernanceAttemptResult,
        stage: str,
        error_code: str | None = None,
        safe_metadata: dict[str, Any] | None = None,
    ) -> None:
        if self.lease_lost_during_attempt_completion:
            raise GovernanceLeaseLostError()
        self.attempts.append(
            {
                "result": result,
                "stage": stage,
                "error_code": error_code,
                "safe_metadata": safe_metadata,
            }
        )

    async def complete_job(
        self, *, claimed: ClaimedGovernanceJob, completion: GovernanceJobCompletion
    ) -> bool:
        self.completions.append(completion)
        return self.completion_succeeds


class _Checkpointer:
    def __init__(self, *, exists: bool = False) -> None:
        self.exists = exists
        self.thread_ids: list[str] = []

    async def checkpoint_exists(self, *, thread_id: str) -> bool:
        self.thread_ids.append(thread_id)
        return self.exists


class _Graph:
    def __init__(self, outcome: dict[str, object] | Exception) -> None:
        self.outcome = outcome
        self.inputs: list[object] = []
        self.updates: list[object] = []

    async def aupdate_state(self, config: object, values: object) -> object:
        self.updates.append(values)
        return config

    async def ainvoke(self, input_value: object, config: object) -> dict[str, object]:
        self.inputs.append(input_value)
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


def _claimed_job(*, attempt_number: int = 1) -> ClaimedGovernanceJob:
    settings = _settings(ai_provider_mode="fake")
    return ClaimedGovernanceJob(
        job_id=uuid4(),
        run_id=uuid4(),
        candidate_id=uuid4(),
        attempt_number=attempt_number,
        lease_token=uuid4(),
        input_content_hash="d" * 64,
        idempotency_key="e" * 64,
        version_bundle=build_governance_version_bundle(settings),
    )


async def _execute_worker_case(
    outcome: dict[str, object] | Exception,
    *,
    attempt_number: int = 1,
    checkpoint_exists: bool = False,
    completion_succeeds: bool = True,
    lease_lost_before_attempt: bool = False,
    lease_lost_during_attempt_completion: bool = False,
) -> tuple[_WorkerRepository, _Checkpointer, _Graph]:
    repository = _WorkerRepository(
        completion_succeeds=completion_succeeds,
        lease_lost_before_attempt=lease_lost_before_attempt,
        lease_lost_during_attempt_completion=lease_lost_during_attempt_completion,
    )
    checkpointer = _Checkpointer(exists=checkpoint_exists)
    graph = _Graph(outcome)
    await execute_claimed_governance_job(
        claimed=_claimed_job(attempt_number=attempt_number),
        repository=cast(GovernanceRepository, repository),
        checkpointer=cast(GovernanceCheckpointer, checkpointer),
        graph=cast(CompiledGovernanceGraph, graph),
        settings=_settings(ai_provider_mode="fake"),
    )
    return repository, checkpointer, graph


async def test_worker_completes_success_and_resumes_without_sensitive_metadata() -> None:
    event_id = uuid4()
    repository, checkpointer, graph = await _execute_worker_case(
        {
            "stage": "terminal",
            "assignment_outcome": "created_new",
            "event_id": event_id,
            "source_diversity": 2,
            "source_body": "must not persist",
            "raw_response": "must not persist",
        },
        checkpoint_exists=True,
    )

    assert graph.inputs == [None]
    assert len(graph.updates) == 1
    assert set(cast(dict[str, object], graph.updates[0])) == {
        "job_id",
        "run_id",
        "candidate_id",
        "attempt_number",
        "lease_token",
        "input_content_hash",
        "idempotency_key",
        "version_bundle",
    }
    assert checkpointer.thread_ids[0].startswith("governance-job:")
    assert repository.attempts[0]["result"] is GovernanceAttemptResult.SUCCEEDED
    completion = repository.completions[0]
    assert completion.status is GovernanceJobStatus.SUCCEEDED
    assert completion.safe_metadata == {
        "graph_stage": "terminal",
        "source_count": 2,
        "event_id": str(event_id),
        "assignment_status": "created_new",
    }


@pytest.mark.parametrize(
    ("outcome", "attempt_number", "expected_status", "expected_result", "error_code"),
    [
        (
            {"stage": "review-required-quarantine", "assignment_outcome": "review_required"},
            1,
            GovernanceJobStatus.REVIEW_REQUIRED,
            GovernanceAttemptResult.REVIEW_REQUIRED,
            None,
        ),
        (
            ProviderTimeoutError(),
            1,
            GovernanceJobStatus.RETRY_SCHEDULED,
            GovernanceAttemptResult.RETRY_SCHEDULED,
            "provider_timeout",
        ),
        (
            ProviderTimeoutError(),
            3,
            GovernanceJobStatus.FAILED,
            GovernanceAttemptResult.FAILED,
            "provider_timeout",
        ),
        (
            InvalidProviderOutputError(("malformed_json",)),
            1,
            GovernanceJobStatus.REVIEW_REQUIRED,
            GovernanceAttemptResult.REVIEW_REQUIRED,
            "invalid_provider_output",
        ),
    ],
)
async def test_worker_classifies_review_retry_and_terminal_outcomes(
    outcome: dict[str, object] | Exception,
    attempt_number: int,
    expected_status: GovernanceJobStatus,
    expected_result: GovernanceAttemptResult,
    error_code: str | None,
) -> None:
    repository, _, _ = await _execute_worker_case(outcome, attempt_number=attempt_number)

    assert repository.attempts[0]["result"] is expected_result
    assert repository.attempts[0]["error_code"] == error_code
    completion = repository.completions[0]
    assert completion.status is expected_status
    assert completion.error_code == error_code
    assert (completion.retry_at is not None) is (
        expected_status is GovernanceJobStatus.RETRY_SCHEDULED
    )


async def test_heartbeat_cleanup_does_not_mask_the_completed_job_result() -> None:
    async def fail_heartbeat() -> None:
        raise RuntimeError("database heartbeat failed")

    task = asyncio.create_task(fail_heartbeat())
    await _finish_heartbeat_task(task, claimed=_claimed_job())


async def test_worker_does_not_report_stale_completion_as_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    events: list[str] = []

    class _CapturingLogger:
        def warning(self, event: str, **_: object) -> None:
            events.append(event)

        def info(self, event: str, **_: object) -> None:
            events.append(event)

    monkeypatch.setattr(governance_worker_service, "logger", _CapturingLogger())
    repository, _, _ = await _execute_worker_case(
        {"stage": "terminal", "assignment_outcome": "created_new"},
        completion_succeeds=False,
    )

    assert len(repository.completions) == 1
    assert "governance_job_lease_lost" in events
    assert "governance_job_completed" not in events


@pytest.mark.parametrize(
    ("outcome", "lease_lost_before_attempt", "lease_lost_during_attempt_completion"),
    [
        ({"stage": "terminal", "assignment_outcome": "created_new"}, True, False),
        (RuntimeError("unexpected worker failure"), False, True),
    ],
)
async def test_worker_treats_stale_claim_as_expected_fencing(
    monkeypatch: pytest.MonkeyPatch,
    outcome: dict[str, object] | Exception,
    lease_lost_before_attempt: bool,
    lease_lost_during_attempt_completion: bool,
) -> None:
    events: list[str] = []

    class _CapturingLogger:
        def warning(self, event: str, **_: object) -> None:
            events.append(event)

        def info(self, event: str, **_: object) -> None:
            events.append(event)

    monkeypatch.setattr(governance_worker_service, "logger", _CapturingLogger())

    await _execute_worker_case(
        outcome,
        lease_lost_before_attempt=lease_lost_before_attempt,
        lease_lost_during_attempt_completion=lease_lost_during_attempt_completion,
    )

    assert events == ["governance_job_lease_lost"]


def test_live_smoke_requires_one_explicit_zhipu_secret_boundary() -> None:
    with pytest.raises(SystemExit, match="AI_PROVIDER_MODE=zhipu"):
        _validate_live_settings(_settings(governance_enabled=True, ai_provider_mode="fake"))
    with pytest.raises(SystemExit, match="AI_PLATFORM_API_KEY"):
        _validate_live_settings(
            _settings(
                governance_enabled=True,
                ai_provider_mode="zhipu",
                ai_platform_base_url="https://provider.invalid/v4",
            )
        )
    with pytest.raises(SystemExit, match="GOVERNANCE_ENABLED=true"):
        _validate_live_settings(
            _settings(
                ai_provider_mode="zhipu",
                ai_platform_base_url="https://provider.invalid/v4",
                ai_platform_api_key=SecretStr("local-test-secret"),
            )
        )

    _validate_live_settings(
        _settings(
            governance_enabled=True,
            ai_provider_mode="zhipu",
            ai_platform_base_url="https://provider.invalid/v4",
            ai_platform_api_key=SecretStr("local-test-secret"),
        )
    )
