from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from app.application.ports.official_account_local import (
    ClaimedOfficialAccountRun,
    OfficialAccountArticleAuditor,
    OfficialAccountArticleGenerator,
    OfficialAccountAuditRequest,
    OfficialAccountAuditResult,
)
from app.application.ports.official_account_reviewer import (
    OfficialAccountReviewer,
    OfficialAccountReviewerRequest,
    OfficialAccountReviewerResult,
    ReviewArtifactBinding,
)
from app.application.services.official_account_local import (
    OfficialAccountLocalExecutor,
    audit_request_fingerprint,
)
from app.application.services.official_account_reviewer import (
    brand_context_sha256,
    exact_article_sha256,
    exact_source_sha256,
)
from app.domain.official_account_local import OfficialAccountAuditVerdict, canonical_json
from app.domain.official_account_reviewer import (
    ReviewIssueCode,
    ReviewIssueSource,
    ReviewReference,
    ReviewReferenceKind,
    ReviewRequest,
    ReviewUnavailableReason,
    build_review_issue,
    build_review_request,
)
from app.infrastructure.db.execution_governance import (
    PostgresExecutionGovernanceRepository,
)
from app.infrastructure.db.models import (
    ExecutionAgentAllocationModel,
    ExecutionArtifactModel,
    ExecutionBudgetReservationModel,
    ExecutionGovernedRunModel,
    ExecutionTraceEventModel,
    OfficialAccountArticleRunModel,
    OfficialAccountReviewRecordModel,
    OfficialAccountReviewRequestModel,
)
from app.infrastructure.db.official_account_local import PostgresOfficialAccountRepository
from app.infrastructure.db.official_account_reviewer import (
    PostgresOfficialAccountReviewRepository,
)
from app.infrastructure.official_account_local import (
    DeterministicFakeOfficialAccountArticleAuditor,
    DeterministicFakeOfficialAccountArticleGenerator,
    LocalOfficialAccountDraftAdapter,
    LocalOfficialAccountMediaAdapter,
    fixture_source_snapshot,
)
from app.infrastructure.official_account_reviewer import (
    DeterministicFakeOfficialAccountReviewer,
)
from app.infrastructure.official_account_reviewer_governance import (
    PostgresOfficialAccountReviewerGovernance,
)
from sqlalchemy import delete, select, update

from .conftest import IntegrationContext
from .test_official_account_local import _identity


@pytest_asyncio.fixture(loop_scope="session")
async def _synthetic_claim_cleanup(
    integration_context: IntegrationContext,
) -> AsyncIterator[None]:
    try:
        yield
    finally:
        async with integration_context.session_factory() as session:
            await session.execute(
                update(OfficialAccountArticleRunModel)
                .where(OfficialAccountArticleRunModel.lease_owner == "review-recovery-worker")
                .values(
                    status="ready",
                    lease_owner=None,
                    lease_token=None,
                    lease_expires_at=None,
                    heartbeat_at=None,
                )
            )
            await session.commit()


def _executor(
    context: IntegrationContext,
    reviewer: OfficialAccountReviewer,
    *,
    generator: OfficialAccountArticleGenerator | None = None,
    auditor: OfficialAccountArticleAuditor | None = None,
) -> tuple[
    OfficialAccountLocalExecutor,
    PostgresOfficialAccountReviewerGovernance,
    PostgresOfficialAccountReviewRepository,
]:
    execution_repository = PostgresExecutionGovernanceRepository(context.session_factory)
    review_repository = PostgresOfficialAccountReviewRepository(context.session_factory)
    governance = PostgresOfficialAccountReviewerGovernance(
        execution_repository=execution_repository,
        review_repository=review_repository,
    )
    return (
        OfficialAccountLocalExecutor(
            repository=PostgresOfficialAccountRepository(context.session_factory),
            fixture_generator=generator or DeterministicFakeOfficialAccountArticleGenerator(),
            fixture_auditor=auditor or DeterministicFakeOfficialAccountArticleAuditor(),
            live_generator=None,
            live_auditor=None,
            media_adapter=LocalOfficialAccountMediaAdapter(),
            draft_adapter=LocalOfficialAccountDraftAdapter(),
            lease_seconds=60,
            heartbeat_seconds=10,
            max_attempts=3,
            retry_base_seconds=0,
            generation_max_output_tokens=8_192,
            audit_max_output_tokens=1_024,
            review_governance=governance,
            fixture_reviewer=reviewer,
        ),
        governance,
        review_repository,
    )


_MANUAL_ISSUE = build_review_issue(
    code=ReviewIssueCode.BRAND_VOICE_AMBIGUOUS,
    source=ReviewIssueSource.REVIEWER,
    references=(ReviewReference(kind=ReviewReferenceKind.SECTION, ref="section:00"),),
)
_REJECTED_ISSUE = build_review_issue(
    code=ReviewIssueCode.BRAND_TONE_MISMATCH,
    source=ReviewIssueSource.REVIEWER,
    references=(ReviewReference(kind=ReviewReferenceKind.SECTION, ref="section:00"),),
)


class _ReasoningReviewer(DeterministicFakeOfficialAccountReviewer):
    async def review(
        self,
        request: OfficialAccountReviewerRequest,
    ) -> OfficialAccountReviewerResult:
        return replace(
            await super().review(request),
            prompt_tokens=7,
            completion_tokens=5,
            reasoning_tokens=3,
        )


class _FailingReviewer(DeterministicFakeOfficialAccountReviewer):
    async def review(
        self,
        request: OfficialAccountReviewerRequest,
    ) -> OfficialAccountReviewerResult:
        self.call_count += 1
        raise RuntimeError("private provider failure body")


class _SlowReviewer(DeterministicFakeOfficialAccountReviewer):
    async def review(
        self,
        request: OfficialAccountReviewerRequest,
    ) -> OfficialAccountReviewerResult:
        self.call_count += 1
        await asyncio.sleep(2)
        return await super().review(request)


class _BlockingReviewer(DeterministicFakeOfficialAccountReviewer):
    def __init__(self) -> None:
        super().__init__()
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.entered_count = 0

    async def review(
        self,
        request: OfficialAccountReviewerRequest,
    ) -> OfficialAccountReviewerResult:
        self.entered_count += 1
        self.started.set()
        await self.release.wait()
        return await super().review(request)


class _RejectingHardAuditor(DeterministicFakeOfficialAccountArticleAuditor):
    async def audit(self, request: OfficialAccountAuditRequest) -> OfficialAccountAuditResult:
        result = await super().audit(request)
        return replace(
            result,
            verdict=OfficialAccountAuditVerdict(
                accepted=False,
                issue_codes=("privacy_risk",),
            ),
            request_fingerprint=audit_request_fingerprint(request),
        )


class _IdentityDriftGenerator(DeterministicFakeOfficialAccountArticleGenerator):
    def __init__(self) -> None:
        super().__init__()
        self.call_count = 0

    async def generate(self, request):  # type: ignore[no-untyped-def]
        self.call_count += 1
        return replace(await super().generate(request), model="spoofed-model")


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.parametrize(
    ("label", "issues", "unavailable_reason", "expected_decision"),
    (
        ("accepted", (), None, "accepted"),
        ("manual", (_MANUAL_ISSUE,), None, "manual_review"),
        ("rejected", (_REJECTED_ISSUE,), None, "rejected"),
        (
            "unavailable",
            (),
            ReviewUnavailableReason.PROVIDER_UNAVAILABLE,
            "unavailable",
        ),
    ),
)
async def test_observe_persists_all_closed_verdicts_without_changing_ready_behavior(
    integration_context: IntegrationContext,
    label: str,
    issues: tuple,
    unavailable_reason: ReviewUnavailableReason | None,
    expected_decision: str,
) -> None:
    repository = PostgresOfficialAccountRepository(integration_context.session_factory)
    identity = replace(
        _identity(suffix=f"review-observe-{label}"),
        reviewer_mode="observe",
    )
    run, created = await repository.enqueue_fixture(identity=identity)
    assert created is True
    reviewer = DeterministicFakeOfficialAccountReviewer(
        issues=issues,
        unavailable_reason=unavailable_reason,
    )
    executor, _, review_repository = _executor(integration_context, reviewer)

    assert await executor.execute_next(f"review-observe-{label}-worker") is True
    stored_run = await repository.get_run(run.id)
    article = await repository.get_article(run.id)
    assert stored_run.status == "ready"
    assert article is not None and article.audit is not None and article.audit.accepted
    assert reviewer.call_count == 1

    async with integration_context.session_factory() as session:
        request = await session.scalar(
            select(OfficialAccountReviewRequestModel).where(
                OfficialAccountReviewRequestModel.run_id == run.id
            )
        )
        assert request is not None
        record = await session.scalar(
            select(OfficialAccountReviewRecordModel).where(
                OfficialAccountReviewRecordModel.request_id == request.id
            )
        )
        assert record is not None
        assert request.status == "completed"
        assert record.decision == expected_decision
        assert request.execution_run_id is not None
        allocations = tuple(
            await session.scalars(
                select(ExecutionAgentAllocationModel).where(
                    ExecutionAgentAllocationModel.run_id == request.execution_run_id
                )
            )
        )
        reservations = tuple(
            await session.scalars(
                select(ExecutionBudgetReservationModel).where(
                    ExecutionBudgetReservationModel.run_id == request.execution_run_id
                )
            )
        )
        review_artifact = await session.get(
            ExecutionArtifactModel,
            record.execution_artifact_id,
        )
        timeline = tuple(
            await session.scalars(
                select(ExecutionTraceEventModel).where(
                    ExecutionTraceEventModel.run_id == request.execution_run_id
                )
            )
        )

    assert {(item.agent_id, item.role, item.status) for item in allocations} == {
        ("official.review.orchestrator", "orchestrator", "succeeded"),
        ("official.writer.initial", "worker", "succeeded"),
        ("official.reviewer.r1", "reviewer", "succeeded"),
    }
    assert len(reservations) == 2
    assert all(item.status == "reconciled" for item in reservations)
    assert request.reservation_id in {item.id for item in reservations}
    assert request.request_event_id in {item.id for item in timeline}
    assert review_artifact is not None
    persisted = await review_repository.get_record(request.id)
    assert persisted is not None
    review_bytes = canonical_json(persisted.verdict).encode("utf-8")
    assert review_artifact.byte_size == len(review_bytes)
    assert review_artifact.sha256 == sha256(review_bytes).hexdigest()

    source = fixture_source_snapshot()
    assert request.article_sha256 == exact_article_sha256(article.article)
    assert request.source_sha256 == exact_source_sha256(source)
    assert request.brand_sha256 == brand_context_sha256(source)
    safe_trace = canonical_json([item.as_dict() for item in _safe_events(timeline)])
    for private_value in (
        article.article.title,
        source.evidence[0].exact_quote,
        source.brand_context[0].text,
        "REVIEW_INPUT",
    ):
        assert private_value not in safe_trace


def _safe_events(events: tuple[ExecutionTraceEventModel, ...]):
    from app.domain.execution_governance import (
        ExecutionEventKind,
        ExecutionEventStatus,
        ExecutionIdentity,
        SafeExecutionEvent,
    )

    return tuple(
        SafeExecutionEvent(
            identity=ExecutionIdentity(event.run_id, event.task_id, event.agent_id),
            event_id=event.id,
            seq_no=event.seq_no,
            kind=ExecutionEventKind(event.kind),
            status=ExecutionEventStatus(event.status),
            parent_event_id=event.parent_event_id,
            artifact_id=event.artifact_id,
            target_name=event.target_name,
            provider_name=event.provider_name,
            model_name=event.model_name,
            error_code=event.error_code,
            duration_ms=event.duration_ms,
            model_turns=event.model_turns,
            input_tokens=event.input_tokens,
            output_tokens=event.output_tokens,
            tool_calls=event.tool_calls,
            result_bytes=event.result_bytes,
        )
        for event in events
    )


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_off_has_zero_reviewer_rows_calls_and_allocations(
    integration_context: IntegrationContext,
) -> None:
    repository = PostgresOfficialAccountRepository(integration_context.session_factory)
    identity = _identity(suffix="review-off-zero-drift")
    run, created = await repository.enqueue_fixture(identity=identity)
    assert created is True
    reviewer = DeterministicFakeOfficialAccountReviewer()
    executor, _, _ = _executor(integration_context, reviewer)

    assert await executor.execute_next("review-off-zero-drift-worker") is True
    assert (await repository.get_run(run.id)).status == "ready"
    assert reviewer.call_count == 0
    async with integration_context.session_factory() as session:
        stored = await session.get(OfficialAccountArticleRunModel, run.id)
        request = await session.scalar(
            select(OfficialAccountReviewRequestModel.id).where(
                OfficialAccountReviewRequestModel.run_id == run.id
            )
        )
        governed = await session.scalar(
            select(ExecutionGovernedRunModel.id).where(
                ExecutionGovernedRunModel.task_id == f"official.review:{run.id}"
            )
        )
    assert stored is not None
    assert not any(key.startswith("reviewer_") for key in stored.version_bundle)
    assert request is None
    assert governed is None


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_observe_identity_ignores_enforce_only_configuration(
    integration_context: IntegrationContext,
) -> None:
    repository = PostgresOfficialAccountRepository(integration_context.session_factory)
    base = replace(
        _identity(suffix="review-observe-enforce-config-drift"),
        reviewer_mode="observe",
    )
    changed = replace(
        base,
        reviewer_repair_timeout_ms=420_000,
        reviewer_repair_max_output_tokens=2_048,
        reviewer_enforce_policy_version="official-account-review-enforce-shadow-v999",
        reviewer_enforce_acknowledgement=True,
        reviewer_calibration_report_sha256="f" * 64,
    )

    first, created = await repository.enqueue_fixture(identity=base)
    replay, replay_created = await repository.enqueue_fixture(identity=changed)

    assert created is True
    assert replay_created is False
    assert replay.id == first.id
    assert replay.request_fingerprint == first.request_fingerprint
    assert not {
        "reviewer_repair_timeout_ms",
        "reviewer_repair_max_output_tokens",
        "reviewer_enforce_policy_version",
        "reviewer_enforce_acknowledgement",
        "reviewer_calibration_report_sha256",
    }.intersection(first.version_bundle)
    async with integration_context.session_factory() as session:
        await session.execute(
            delete(OfficialAccountArticleRunModel).where(
                OfficialAccountArticleRunModel.id == first.id
            )
        )
        await session.commit()


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_legacy_hard_auditor_rejection_skips_editorial_reviewer_and_preserves_gate(
    integration_context: IntegrationContext,
) -> None:
    repository = PostgresOfficialAccountRepository(integration_context.session_factory)
    identity = replace(
        _identity(suffix="review-hard-gate-rejected"),
        reviewer_mode="observe",
    )
    run, created = await repository.enqueue_fixture(identity=identity)
    assert created is True
    reviewer = DeterministicFakeOfficialAccountReviewer()
    executor, _, _ = _executor(
        integration_context,
        reviewer,
        auditor=_RejectingHardAuditor(),
    )

    assert await executor.execute_next("review-hard-gate-worker") is True
    stored_run = await repository.get_run(run.id)
    article = await repository.get_article(run.id)
    assert stored_run.status == "review_required"
    assert article is not None and article.audit is not None
    assert article.audit.accepted is False
    assert article.audit.issue_codes == ("privacy_risk",)
    assert await repository.get_render(run.id) is None
    assert reviewer.call_count == 0

    async with integration_context.session_factory() as session:
        requests = tuple(
            await session.scalars(
                select(OfficialAccountReviewRequestModel).where(
                    OfficialAccountReviewRequestModel.run_id == run.id
                )
            )
        )
        execution_run = await session.scalar(
            select(ExecutionGovernedRunModel).where(
                ExecutionGovernedRunModel.task_id == f"official.review:{run.id}"
            )
        )
        assert execution_run is not None
        allocations = tuple(
            await session.scalars(
                select(ExecutionAgentAllocationModel).where(
                    ExecutionAgentAllocationModel.run_id == execution_run.id
                )
            )
        )
    assert requests == ()
    assert execution_run.status == "failed"
    assert {(item.agent_id, item.status) for item in allocations} == {
        ("official.review.orchestrator", "failed"),
        ("official.writer.initial", "succeeded"),
    }


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.parametrize(
    ("label", "reviewer", "reviewer_timeout_ms"),
    (
        ("exception", _FailingReviewer(), 180_000),
        ("timeout", _SlowReviewer(), 1_000),
    ),
)
async def test_real_reviewer_failure_is_result_unknown_nonblocking_and_reconciled_once(
    integration_context: IntegrationContext,
    label: str,
    reviewer: DeterministicFakeOfficialAccountReviewer,
    reviewer_timeout_ms: int,
) -> None:
    repository = PostgresOfficialAccountRepository(integration_context.session_factory)
    identity = replace(
        _identity(suffix=f"review-real-{label}"),
        reviewer_mode="observe",
        reviewer_timeout_ms=reviewer_timeout_ms,
    )
    run, created = await repository.enqueue_fixture(identity=identity)
    assert created is True
    executor, _, _ = _executor(integration_context, reviewer)

    assert await executor.execute_next(f"review-real-{label}-worker") is True
    assert (await repository.get_run(run.id)).status == "ready"
    assert await repository.get_render(run.id) is not None
    assert reviewer.call_count == 1
    assert await executor.execute_next(f"review-real-{label}-retry") is False
    assert reviewer.call_count == 1

    async with integration_context.session_factory() as session:
        request = await session.scalar(
            select(OfficialAccountReviewRequestModel).where(
                OfficialAccountReviewRequestModel.run_id == run.id
            )
        )
        assert request is not None and request.reservation_id is not None
        record = await session.scalar(
            select(OfficialAccountReviewRecordModel).where(
                OfficialAccountReviewRecordModel.request_id == request.id
            )
        )
        reservation = await session.get(
            ExecutionBudgetReservationModel,
            request.reservation_id,
        )
        allocations = tuple(
            await session.scalars(
                select(ExecutionAgentAllocationModel).where(
                    ExecutionAgentAllocationModel.run_id == request.execution_run_id
                )
            )
        )
        failure_events = tuple(
            await session.scalars(
                select(ExecutionTraceEventModel).where(
                    ExecutionTraceEventModel.run_id == request.execution_run_id,
                    ExecutionTraceEventModel.agent_id == "official.reviewer.r1",
                    ExecutionTraceEventModel.kind == "node_failed",
                )
            )
        )
    assert request.status == "result_unknown"
    assert request.error_code == "review_result_unknown"
    assert record is None
    assert reservation is not None and reservation.status == "reconciled"
    assert reservation.actual_model_turns == 1
    assert reservation.actual_input_tokens is None
    assert reservation.actual_output_tokens is None
    assert reservation.actual_tool_calls == 1
    assert {(item.agent_id, item.status) for item in allocations} == {
        ("official.review.orchestrator", "failed"),
        ("official.writer.initial", "succeeded"),
        ("official.reviewer.r1", "failed"),
    }
    assert len(failure_events) == 1
    assert failure_events[0].status == "failed"
    assert failure_events[0].error_code == (
        "capability_timeout" if label == "timeout" else "capability_failed"
    )


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_compatible_concurrent_observe_joins_calling_intent_without_recall_or_poisoning(
    integration_context: IntegrationContext,
) -> None:
    repository = PostgresOfficialAccountRepository(integration_context.session_factory)
    identity = replace(
        _identity(suffix="review-compatible-inflight"),
        reviewer_mode="observe",
    )
    run, created = await repository.enqueue_fixture(identity=identity)
    assert created is True
    reviewer = _BlockingReviewer()
    executor, governance, _ = _executor(integration_context, reviewer)
    owner = asyncio.create_task(executor.execute_next("review-compatible-owner"))
    await asyncio.wait_for(reviewer.started.wait(), timeout=5)

    article = await repository.get_article(run.id)
    assert article is not None and article.audit is not None and article.audit.accepted
    async with integration_context.session_factory() as session:
        business_run = await session.get(OfficialAccountArticleRunModel, run.id)
        assert business_run is not None and business_run.lease_token is not None
        claimed = ClaimedOfficialAccountRun(
            run_id=run.id,
            attempt_number=business_run.attempt_count,
            lease_token=business_run.lease_token,
            generation_mode="fixture",
            identity=identity,
            current_stage=business_run.current_stage,
        )

    try:
        joined = await asyncio.wait_for(
            governance.observe(
                claimed=claimed,
                source=fixture_source_snapshot(),
                article=article,
                reviewer=reviewer,
            ),
            timeout=5,
        )
        assert joined is None
        assert reviewer.entered_count == 1
        assert reviewer.call_count == 0
    finally:
        reviewer.release.set()
    assert await asyncio.wait_for(owner, timeout=10) is True
    assert reviewer.entered_count == 1
    assert reviewer.call_count == 1
    assert (await repository.get_run(run.id)).status == "ready"
    async with integration_context.session_factory() as session:
        request = await session.scalar(
            select(OfficialAccountReviewRequestModel).where(
                OfficialAccountReviewRequestModel.run_id == run.id
            )
        )
        assert request is not None
        records = tuple(
            await session.scalars(
                select(OfficialAccountReviewRecordModel).where(
                    OfficialAccountReviewRecordModel.request_id == request.id
                )
            )
        )
    assert request.status == "completed"
    assert len(records) == 1


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_writer_identity_drift_fails_governed_node_before_success_is_recorded(
    integration_context: IntegrationContext,
) -> None:
    repository = PostgresOfficialAccountRepository(integration_context.session_factory)
    identity = replace(
        _identity(suffix="review-writer-identity-drift"),
        reviewer_mode="observe",
    )
    run, created = await repository.enqueue_fixture(identity=identity)
    assert created is True
    generator = _IdentityDriftGenerator()
    reviewer = DeterministicFakeOfficialAccountReviewer()
    executor, _, _ = _executor(
        integration_context,
        reviewer,
        generator=generator,
    )

    assert await executor.execute_next("review-writer-identity-worker") is True
    assert generator.call_count == 1
    assert reviewer.call_count == 0
    assert (await repository.get_run(run.id)).status == "failed"
    async with integration_context.session_factory() as session:
        execution_run = await session.scalar(
            select(ExecutionGovernedRunModel).where(
                ExecutionGovernedRunModel.task_id == f"official.review:{run.id}"
            )
        )
        assert execution_run is not None
        writer = await session.scalar(
            select(ExecutionAgentAllocationModel).where(
                ExecutionAgentAllocationModel.run_id == execution_run.id,
                ExecutionAgentAllocationModel.agent_id == "official.writer.initial",
            )
        )
        succeeded_results = tuple(
            await session.scalars(
                select(ExecutionTraceEventModel).where(
                    ExecutionTraceEventModel.run_id == execution_run.id,
                    ExecutionTraceEventModel.agent_id == "official.writer.initial",
                    ExecutionTraceEventModel.kind == "model_result",
                    ExecutionTraceEventModel.status == "succeeded",
                )
            )
        )
    assert execution_run.status == "failed"
    assert writer is not None and writer.status == "failed"
    assert succeeded_results == ()


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_reviewer_reasoning_tokens_are_reconciled_as_real_output_usage(
    integration_context: IntegrationContext,
) -> None:
    repository = PostgresOfficialAccountRepository(integration_context.session_factory)
    identity = replace(
        _identity(suffix="review-reasoning-usage"),
        reviewer_mode="observe",
    )
    run, created = await repository.enqueue_fixture(identity=identity)
    assert created is True
    reviewer = _ReasoningReviewer()
    executor, _, _ = _executor(integration_context, reviewer)
    assert await executor.execute_next("review-reasoning-usage-worker") is True

    async with integration_context.session_factory() as session:
        request = await session.scalar(
            select(OfficialAccountReviewRequestModel).where(
                OfficialAccountReviewRequestModel.run_id == run.id
            )
        )
        assert request is not None and request.reservation_id is not None
        reservation = await session.get(
            ExecutionBudgetReservationModel,
            request.reservation_id,
        )
        record = await session.scalar(
            select(OfficialAccountReviewRecordModel).where(
                OfficialAccountReviewRecordModel.request_id == request.id
            )
        )
    assert reservation is not None and reservation.status == "reconciled"
    assert reservation.actual_input_tokens == 7
    assert reservation.actual_output_tokens == 8
    assert record is not None
    assert record.completion_tokens == 5
    assert record.reasoning_tokens == 3


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.parametrize(
    ("label", "identity_changes", "reviewer_model"),
    (
        ("model", {}, "changed-reviewer-model"),
        (
            "contract",
            {"reviewer_rubric_version": "official-account-editorial-rubric-v999"},
            "official-account-fixture-v1",
        ),
    ),
)
async def test_frozen_reviewer_identity_tamper_never_reaches_reviewer_provider(
    integration_context: IntegrationContext,
    label: str,
    identity_changes: dict[str, str],
    reviewer_model: str,
) -> None:
    repository = PostgresOfficialAccountRepository(integration_context.session_factory)
    identity = replace(
        _identity(suffix=f"review-tamper-{label}"),
        reviewer_mode="observe",
        **identity_changes,
    )
    run, created = await repository.enqueue_fixture(identity=identity)
    assert created is True
    reviewer = DeterministicFakeOfficialAccountReviewer(model=reviewer_model)
    executor, _, _ = _executor(integration_context, reviewer)

    assert await executor.execute_next(f"review-tamper-{label}-worker") is True
    assert (await repository.get_run(run.id)).status == "ready"
    assert reviewer.call_count == 0
    async with integration_context.session_factory() as session:
        requests = await session.scalar(
            select(OfficialAccountReviewRequestModel.id).where(
                OfficialAccountReviewRequestModel.run_id == run.id
            )
        )
        reviewer_allocation = await session.scalar(
            select(ExecutionAgentAllocationModel.agent_id).where(
                ExecutionAgentAllocationModel.task_id == f"official.review:{run.id}",
                ExecutionAgentAllocationModel.agent_id == "official.reviewer.r1",
            )
        )
        allocation_statuses = tuple(
            await session.scalars(
                select(ExecutionAgentAllocationModel.status).where(
                    ExecutionAgentAllocationModel.task_id == f"official.review:{run.id}"
                )
            )
        )
    assert requests is None
    assert reviewer_allocation is None
    assert allocation_statuses
    assert "running" not in allocation_statuses


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.usefixtures("_synthetic_claim_cleanup")
async def test_review_intent_concurrent_replay_and_artifact_or_version_tamper_fail_closed(
    integration_context: IntegrationContext,
) -> None:
    repository = PostgresOfficialAccountRepository(integration_context.session_factory)
    base_identity = _identity(suffix="review-intent-concurrent-cross-scope")
    first_identity = replace(
        base_identity,
        reviewer_mode="observe",
    )
    second_identity = replace(
        base_identity,
        reviewer_mode="observe",
        reviewer_max_output_tokens=2_049,
    )
    first_run, first_created = await repository.enqueue_fixture(identity=first_identity)
    second_run, second_created = await repository.enqueue_fixture(identity=second_identity)
    assert first_created is True and second_created is True
    first_reviewer = DeterministicFakeOfficialAccountReviewer()
    second_reviewer = DeterministicFakeOfficialAccountReviewer()
    first_executor, _, review_repository = _executor(integration_context, first_reviewer)
    second_executor, _, _ = _executor(integration_context, second_reviewer)
    assert await first_executor.execute_next("review-intent-concurrent-first-worker") is True
    assert await second_executor.execute_next("review-intent-concurrent-second-worker") is True
    first_article = await repository.get_article(first_run.id)
    second_article = await repository.get_article(second_run.id)
    assert first_article is not None and second_article is not None
    assert exact_article_sha256(first_article.article) == exact_article_sha256(
        second_article.article
    )
    claimed = await _reopen_business_lease(
        integration_context,
        run_id=first_run.id,
        identity=first_identity,
    )

    async with integration_context.session_factory() as session:
        first = await session.scalar(
            select(OfficialAccountReviewRequestModel).where(
                OfficialAccountReviewRequestModel.run_id == first_run.id
            )
        )
        second = await session.scalar(
            select(OfficialAccountReviewRequestModel).where(
                OfficialAccountReviewRequestModel.run_id == second_run.id
            )
        )
        assert first is not None and second is not None
        contract = first.request_snapshot
        first_artifacts = ReviewArtifactBinding(
            article_artifact_id=first.article_artifact_id,
            source_artifact_id=first.source_artifact_id,
            brand_artifact_id=first.brand_artifact_id,
            article_sha256=first.article_sha256,
            source_sha256=first.source_sha256,
            brand_sha256=first.brand_sha256,
        )
        cross_run_artifacts = ReviewArtifactBinding(
            article_artifact_id=second.article_artifact_id,
            source_artifact_id=second.source_artifact_id,
            brand_artifact_id=second.brand_artifact_id,
            article_sha256=second.article_sha256,
            source_sha256=second.source_sha256,
            brand_sha256=second.brand_sha256,
        )
        assert first_artifacts.article_sha256 == cross_run_artifacts.article_sha256
        assert first_artifacts.source_sha256 == cross_run_artifacts.source_sha256
        assert first_artifacts.brand_sha256 == cross_run_artifacts.brand_sha256
    parsed_contract = ReviewRequest.model_validate(contract)
    replayed = await asyncio.gather(
        *(
            review_repository.create_intent(
                claimed=claimed,
                article=first_article,
                contract=parsed_contract,
                artifacts=first_artifacts,
                provider=first_reviewer.provider,
                model=first_reviewer.model,
            )
            for _ in range(6)
        )
    )
    assert {item.id for item in replayed} == {first.id}

    with pytest.raises(ValueError, match="contract and artifact SHA differ"):
        await review_repository.create_intent(
            claimed=claimed,
            article=first_article,
            contract=parsed_contract,
            artifacts=replace(first_artifacts, article_sha256="0" * 64),
            provider=first_reviewer.provider,
            model=first_reviewer.model,
        )
    changed_version = build_review_request(
        request_id=parsed_contract.request_id,
        identity=parsed_contract.identity,
        reviewer_version=parsed_contract.reviewer_version,
        prompt_version="official-account-reviewer-prompt-v999",
    )
    with pytest.raises(RuntimeError, match="intent replay changed"):
        await review_repository.create_intent(
            claimed=claimed,
            article=first_article,
            contract=changed_version,
            artifacts=first_artifacts,
            provider=first_reviewer.provider,
            model=first_reviewer.model,
        )
    with pytest.raises(RuntimeError, match="cross execution scope"):
        await review_repository.create_intent(
            claimed=claimed,
            article=first_article,
            contract=parsed_contract,
            artifacts=cross_run_artifacts,
            provider=first_reviewer.provider,
            model=first_reviewer.model,
        )
    assert first_reviewer.call_count == 1


async def _reopen_business_lease(
    context: IntegrationContext,
    *,
    run_id: UUID,
    identity,
    increment_attempt: bool = False,
) -> ClaimedOfficialAccountRun:
    lease_token = uuid4()
    async with context.session_factory() as session:
        run = await session.get(OfficialAccountArticleRunModel, run_id)
        assert run is not None
        if increment_attempt:
            run.attempt_count += 1
        run.status = "running"
        run.lease_owner = "review-recovery-worker"
        run.lease_token = lease_token
        # Direct repository replay below intentionally holds a synthetic business claim.
        # Keep it alive for the session so a later executor cannot steal this row merely
        # because an earlier PostgreSQL regression took more than one minute.
        run.lease_expires_at = datetime.now(UTC) + timedelta(days=1)
        run.heartbeat_at = datetime.now(UTC)
        await session.commit()
        return ClaimedOfficialAccountRun(
            run_id=run.id,
            attempt_number=run.attempt_count,
            lease_token=lease_token,
            generation_mode="fixture",
            identity=identity,
            current_stage=run.current_stage,
        )


async def _remove_review_terminals(
    context: IntegrationContext,
    execution_run_id: UUID,
) -> None:
    async with context.session_factory() as session:
        await session.execute(
            delete(ExecutionTraceEventModel).where(
                ExecutionTraceEventModel.run_id == execution_run_id,
                ExecutionTraceEventModel.kind.in_(("run_finished", "run_failed")),
            )
        )
        await session.execute(
            delete(ExecutionTraceEventModel).where(
                ExecutionTraceEventModel.run_id == execution_run_id,
                ExecutionTraceEventModel.agent_id == "official.reviewer.r1",
                ExecutionTraceEventModel.kind.in_(("node_finished", "node_failed")),
            )
        )
        allocations = tuple(
            await session.scalars(
                select(ExecutionAgentAllocationModel).where(
                    ExecutionAgentAllocationModel.run_id == execution_run_id,
                    ExecutionAgentAllocationModel.agent_id.in_(
                        ("official.review.orchestrator", "official.reviewer.r1")
                    ),
                )
            )
        )
        for allocation in allocations:
            allocation.status = "running"
            allocation.completed_at = None
        root = next(item for item in allocations if item.agent_id == "official.review.orchestrator")
        reviewer = next(item for item in allocations if item.agent_id == "official.reviewer.r1")
        root.reserved_elapsed_ms += reviewer.limit_elapsed_ms
        root.reserved_model_turns += reviewer.limit_model_turns
        root.reserved_input_tokens += reviewer.limit_input_tokens
        root.reserved_output_tokens += reviewer.limit_output_tokens
        root.reserved_tool_calls += reviewer.limit_tool_calls
        root.reserved_tool_result_bytes += reviewer.limit_tool_result_bytes
        root.reserved_artifact_bytes += reviewer.limit_artifact_bytes
        root.reserved_child_count += 1
        root.used_elapsed_ms -= reviewer.used_elapsed_ms
        root.used_model_turns -= reviewer.used_model_turns
        assert root.used_input_tokens is not None and reviewer.used_input_tokens is not None
        assert root.used_output_tokens is not None and reviewer.used_output_tokens is not None
        root.used_input_tokens -= reviewer.used_input_tokens
        root.used_output_tokens -= reviewer.used_output_tokens
        root.used_tool_calls -= reviewer.used_tool_calls
        root.used_tool_result_bytes -= reviewer.used_tool_result_bytes
        root.used_artifact_bytes -= reviewer.used_artifact_bytes
        root.used_child_count -= 1
        governed = await session.get(ExecutionGovernedRunModel, execution_run_id)
        assert governed is not None
        governed.status = "running"
        governed.completed_at = None
        await session.commit()


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.parametrize("boundary", ("completed", "calling"))
@pytest.mark.usefixtures("_synthetic_claim_cleanup")
async def test_replay_terminally_recovers_reviewer_and_root_allocations_without_recall(
    integration_context: IntegrationContext,
    boundary: str,
) -> None:
    repository = PostgresOfficialAccountRepository(integration_context.session_factory)
    identity = replace(
        _identity(suffix=f"review-recovery-{boundary}"),
        reviewer_mode="observe",
    )
    run, created = await repository.enqueue_fixture(identity=identity)
    assert created is True
    reviewer = DeterministicFakeOfficialAccountReviewer()
    executor, governance, _ = _executor(integration_context, reviewer)
    assert await executor.execute_next(f"review-recovery-{boundary}-worker") is True
    article = await repository.get_article(run.id)
    assert article is not None

    async with integration_context.session_factory() as session:
        request = await session.scalar(
            select(OfficialAccountReviewRequestModel).where(
                OfficialAccountReviewRequestModel.run_id == run.id
            )
        )
        assert request is not None and request.execution_run_id is not None
        execution_run_id = request.execution_run_id
        if boundary == "calling":
            await session.execute(
                delete(OfficialAccountReviewRecordModel).where(
                    OfficialAccountReviewRecordModel.request_id == request.id
                )
            )
            request.status = "calling"
            request.completed_at = None
        await session.commit()
    await _remove_review_terminals(integration_context, execution_run_id)
    claimed = await _reopen_business_lease(
        integration_context,
        run_id=run.id,
        identity=identity,
        increment_attempt=boundary == "calling",
    )

    recovered = await governance.observe(
        claimed=claimed,
        source=fixture_source_snapshot(),
        article=article,
        reviewer=reviewer,
    )
    assert reviewer.call_count == 1
    assert (recovered is not None) is (boundary == "completed")
    async with integration_context.session_factory() as session:
        request = await session.scalar(
            select(OfficialAccountReviewRequestModel).where(
                OfficialAccountReviewRequestModel.run_id == run.id
            )
        )
        assert request is not None
        allocations = tuple(
            await session.scalars(
                select(ExecutionAgentAllocationModel).where(
                    ExecutionAgentAllocationModel.run_id == execution_run_id,
                    ExecutionAgentAllocationModel.agent_id.in_(
                        ("official.review.orchestrator", "official.reviewer.r1")
                    ),
                )
            )
        )
        terminal_kinds = tuple(
            await session.scalars(
                select(ExecutionTraceEventModel.kind).where(
                    ExecutionTraceEventModel.run_id == execution_run_id,
                    ExecutionTraceEventModel.kind.in_(
                        ("node_finished", "node_failed", "run_finished", "run_failed")
                    ),
                )
            )
        )
    expected_status = "succeeded" if boundary == "completed" else "failed"
    assert {item.status for item in allocations} == {expected_status}
    assert request.status == ("completed" if boundary == "completed" else "result_unknown")
    if boundary == "completed":
        assert terminal_kinds.count("node_finished") == 2
        assert terminal_kinds.count("node_failed") == 0
        assert terminal_kinds.count("run_finished") == 1
    else:
        assert terminal_kinds.count("node_finished") == 1
        assert terminal_kinds.count("node_failed") == 1
        assert terminal_kinds.count("run_failed") == 1
