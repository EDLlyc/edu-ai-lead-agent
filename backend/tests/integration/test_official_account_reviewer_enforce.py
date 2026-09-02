from __future__ import annotations

import asyncio
from dataclasses import asdict, replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from app.application.ports.official_account_local import (
    ClaimedOfficialAccountRun,
    OfficialAccountAuditRequest,
    OfficialAccountAuditResult,
    OfficialAccountGenerationRequest,
    OfficialAccountGenerationResult,
    OfficialAccountRepairRequest,
    OfficialAccountRepairResult,
    StoredOfficialAccountArticle,
)
from app.application.ports.official_account_reviewer import (
    EnforcedRepairOutcome,
    EnforcedReviewOutcome,
    OfficialAccountReviewerRequest,
    OfficialAccountReviewerResult,
    StoredRepairIntent,
    StoredReviewRecord,
)
from app.application.services import official_account_local as local_service
from app.application.services.official_account_local import (
    OfficialAccountLocalExecutor,
    audit_request_fingerprint,
    generation_request_fingerprint,
    repair_request_fingerprint,
    run_request_fingerprint,
)
from app.domain.official_account_local import (
    OfficialAccountSourceSnapshot,
    render_wechat_html,
    validate_article_package,
)
from app.domain.official_account_reviewer import (
    ReviewDecision,
    ReviewIssue,
    ReviewIssueCode,
    ReviewIssueSource,
    ReviewReference,
    ReviewReferenceKind,
    ReviewUnavailableReason,
    build_review_issue,
    build_review_verdict,
    project_repair_directives,
)
from app.infrastructure.db.execution_governance import (
    PostgresExecutionGovernanceRepository,
)
from app.infrastructure.db.models import (
    ExecutionAgentAllocationModel,
    ExecutionBudgetReservationModel,
    OfficialAccountArticleRunModel,
    OfficialAccountArticleVersionModel,
    OfficialAccountRenderVersionModel,
    OfficialAccountRepairRequestModel,
    OfficialAccountReviewRequestModel,
)
from app.infrastructure.db.official_account_local import PostgresOfficialAccountRepository
from app.infrastructure.db.official_account_repair import (
    PostgresOfficialAccountRepairRepository,
)
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
from app.infrastructure.official_account_reviewer_governance import (
    PostgresOfficialAccountReviewerGovernance,
)
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError

from .conftest import IntegrationContext
from .test_official_account_local import _v10_identity

_REPAIRABLE = build_review_issue(
    code=ReviewIssueCode.BRAND_TONE_MISMATCH,
    source=ReviewIssueSource.REVIEWER,
    references=(ReviewReference(kind=ReviewReferenceKind.SECTION, ref="section:00"),),
)
_MANUAL = build_review_issue(
    code=ReviewIssueCode.BRAND_VOICE_AMBIGUOUS,
    source=ReviewIssueSource.REVIEWER,
    references=(ReviewReference(kind=ReviewReferenceKind.SECTION, ref="section:00"),),
)


def _completed_review(outcome: EnforcedReviewOutcome) -> StoredReviewRecord:
    assert outcome.status == "completed"
    assert outcome.record is not None
    return outcome.record


def _provider_completed_repair(
    outcome: EnforcedRepairOutcome,
) -> tuple[OfficialAccountRepairResult, StoredRepairIntent]:
    assert outcome.status == "provider_completed"
    assert outcome.result is not None
    return outcome.result, outcome.intent


class _SequenceLiveReviewer:
    provider = "zhipu"
    model = "reviewer-enforce-test-model"

    def __init__(
        self,
        outcomes: tuple[tuple[ReviewIssue, ...] | ReviewUnavailableReason, ...],
    ) -> None:
        self._outcomes = outcomes
        self.call_count = 0

    async def review(
        self,
        request: OfficialAccountReviewerRequest,
    ) -> OfficialAccountReviewerResult:
        outcome = self._outcomes[self.call_count]
        self.call_count += 1
        issues = outcome if isinstance(outcome, tuple) else ()
        unavailable = outcome if isinstance(outcome, ReviewUnavailableReason) else None
        return OfficialAccountReviewerResult(
            verdict=build_review_verdict(
                request.contract,
                reviewer_issues=issues,
                unavailable_reason=unavailable,
            ),
            provider=self.provider,
            model=self.model,
            provider_request_id=f"reviewer-enforce-{self.call_count}",
            prompt_tokens=10,
            completion_tokens=5,
            reasoning_tokens=0,
            latency_ms=1,
        )


class _LiveRepairer:
    def __init__(self) -> None:
        self.call_count = 0

    async def repair(self, request: OfficialAccountRepairRequest) -> OfficialAccountRepairResult:
        self.call_count += 1
        generated = await DeterministicFakeOfficialAccountArticleGenerator().generate(
            OfficialAccountGenerationRequest(
                run_id=request.run_id,
                source=request.source,
                identity=request.identity,
                request_fingerprint=request.request_fingerprint,
                max_output_tokens=request.max_output_tokens,
            )
        )
        first = generated.draft.sections[0].model_copy(
            update={"heading": "先用温和而清晰的问题保护孩子的科学好奇心"}
        )
        draft = generated.draft.model_copy(
            update={"sections": (first, *generated.draft.sections[1:])}
        )
        return OfficialAccountRepairResult(
            draft=draft,
            provider="zhipu",
            model="reviewer-enforce-test-model",
            request_fingerprint=repair_request_fingerprint(request),
            provider_request_id="repair-enforce-1",
            prompt_tokens=20,
            completion_tokens=10,
            reasoning_tokens=0,
            latency_ms=1,
        )


class _FailingLiveRepairer:
    def __init__(self) -> None:
        self.call_count = 0

    async def repair(self, request: OfficialAccountRepairRequest) -> OfficialAccountRepairResult:
        del request
        self.call_count += 1
        raise RuntimeError("private repair provider failure body")


class _LiveGenerator:
    async def generate(
        self,
        request: OfficialAccountGenerationRequest,
    ) -> OfficialAccountGenerationResult:
        result = await DeterministicFakeOfficialAccountArticleGenerator().generate(request)
        return replace(
            result,
            provider="zhipu",
            model=request.identity.model,
            request_fingerprint=generation_request_fingerprint(request),
        )


class _LiveAuditor:
    async def audit(self, request: OfficialAccountAuditRequest) -> OfficialAccountAuditResult:
        result = await DeterministicFakeOfficialAccountArticleAuditor().audit(request)
        return replace(
            result,
            provider="zhipu",
            model=request.identity.model,
            request_fingerprint=audit_request_fingerprint(request),
        )


class _BlockingLiveRepairer:
    def __init__(self) -> None:
        self.call_count = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def repair(self, request: OfficialAccountRepairRequest) -> OfficialAccountRepairResult:
        self.call_count += 1
        self.started.set()
        await self.release.wait()
        delegate = _LiveRepairer()
        return await delegate.repair(request)


class _BlockingLiveReviewer:
    provider = "zhipu"
    model = "reviewer-enforce-test-model"

    def __init__(self) -> None:
        self.call_count = 0
        self.started = asyncio.Event()
        self.release = asyncio.Event()

    async def review(
        self,
        request: OfficialAccountReviewerRequest,
    ) -> OfficialAccountReviewerResult:
        self.call_count += 1
        self.started.set()
        await self.release.wait()
        return OfficialAccountReviewerResult(
            verdict=build_review_verdict(request.contract, reviewer_issues=()),
            provider=self.provider,
            model=self.model,
            provider_request_id="reviewer-r2-late-result",
            prompt_tokens=10,
            completion_tokens=5,
            reasoning_tokens=0,
            latency_ms=1,
        )


async def _prepare_claim(
    context: IntegrationContext,
    *,
    suffix: str,
) -> tuple[
    PostgresOfficialAccountRepository,
    ClaimedOfficialAccountRun,
]:
    repository = PostgresOfficialAccountRepository(context.session_factory)
    base_identity = _v10_identity(suffix=f"base-{suffix}")
    run, created = await repository.enqueue_fixture(identity=base_identity)
    assert created
    executor = OfficialAccountLocalExecutor(
        repository=repository,
        fixture_generator=DeterministicFakeOfficialAccountArticleGenerator(),
        fixture_auditor=DeterministicFakeOfficialAccountArticleAuditor(),
        live_generator=None,
        live_auditor=None,
        media_adapter=LocalOfficialAccountMediaAdapter(),
        draft_adapter=LocalOfficialAccountDraftAdapter(),
        lease_seconds=60,
        heartbeat_seconds=10,
        max_attempts=3,
        retry_base_seconds=0,
        generation_max_output_tokens=16_384,
        audit_max_output_tokens=1_024,
    )
    assert await executor.execute_next(f"enforce-prepare-{suffix}")
    stored = await repository.get_run(run.id)
    assert stored.status == "ready"

    identity = replace(
        base_identity,
        provider="zhipu",
        model="reviewer-enforce-test-model",
        reviewer_mode="enforce",
        reviewer_provider="zhipu",
        reviewer_model="reviewer-enforce-test-model",
        reviewer_enforce_acknowledgement=True,
        reviewer_calibration_report_sha256="a" * 64,
    )
    lease_token = uuid4()
    async with context.session_factory() as session:
        await session.execute(
            update(OfficialAccountArticleRunModel)
            .where(OfficialAccountArticleRunModel.id == run.id)
            .values(
                status="running",
                current_stage="auditing",
                version_bundle=asdict(identity),
                active_render_version_id=None,
                active_body_media_id=None,
                active_cover_media_id=None,
                active_draft_id=None,
                active_review_record_id=None,
                lease_owner=f"enforce-{suffix}",
                lease_token=lease_token,
                lease_expires_at=datetime.now(UTC) + timedelta(minutes=5),
                completed_at=None,
                error_code=None,
            )
        )
        await session.execute(
            text(
                "DELETE FROM official_account_local_draft_body_media "
                "WHERE draft_id IN (SELECT id FROM official_account_local_drafts WHERE run_id=:run)"
            ),
            {"run": run.id},
        )
        await session.execute(
            text("DELETE FROM official_account_local_drafts WHERE run_id=:run"), {"run": run.id}
        )
        await session.execute(
            text("DELETE FROM official_account_local_media WHERE run_id=:run"), {"run": run.id}
        )
        await session.execute(
            text("DELETE FROM official_account_render_versions WHERE run_id=:run"),
            {"run": run.id},
        )
        await session.execute(
            text(
                "DELETE FROM official_account_article_attempts "
                "WHERE run_id=:run AND stage NOT IN ('generating', 'auditing')"
            ),
            {"run": run.id},
        )
        await session.commit()
    return repository, ClaimedOfficialAccountRun(
        run_id=run.id,
        attempt_number=stored.attempt_count,
        lease_token=lease_token,
        generation_mode="live",
        identity=identity,
        current_stage="auditing",
    )


def _governance(context: IntegrationContext) -> PostgresOfficialAccountReviewerGovernance:
    return PostgresOfficialAccountReviewerGovernance(
        execution_repository=PostgresExecutionGovernanceRepository(context.session_factory),
        review_repository=PostgresOfficialAccountReviewRepository(context.session_factory),
        repair_repository=PostgresOfficialAccountRepairRepository(context.session_factory),
    )


def _enforce_executor(
    context: IntegrationContext,
    *,
    reviewer: _SequenceLiveReviewer | _BlockingLiveReviewer,
    repairer: _LiveRepairer | _FailingLiveRepairer | _BlockingLiveRepairer | None,
) -> OfficialAccountLocalExecutor:
    return OfficialAccountLocalExecutor(
        repository=PostgresOfficialAccountRepository(context.session_factory),
        fixture_generator=DeterministicFakeOfficialAccountArticleGenerator(),
        fixture_auditor=DeterministicFakeOfficialAccountArticleAuditor(),
        live_generator=None,
        live_auditor=_LiveAuditor(),
        media_adapter=LocalOfficialAccountMediaAdapter(),
        draft_adapter=LocalOfficialAccountDraftAdapter(),
        lease_seconds=60,
        heartbeat_seconds=10,
        max_attempts=3,
        retry_base_seconds=0,
        generation_max_output_tokens=16_384,
        audit_max_output_tokens=1_024,
        review_governance=_governance(context),
        live_reviewer=reviewer,
        live_repairer=repairer,
    )


async def _prepare_audited_r2(
    context: IntegrationContext,
    *,
    suffix: str,
) -> tuple[
    PostgresOfficialAccountRepository,
    ClaimedOfficialAccountRun,
    OfficialAccountSourceSnapshot,
    StoredOfficialAccountArticle,
]:
    repository, claimed = await _prepare_claim(context, suffix=suffix)
    source = fixture_source_snapshot(multi_image=True, semantic_media=True)
    article = await repository.get_article(claimed.run_id)
    assert article is not None and article.audit is not None and article.audit.accepted
    governance = _governance(context)
    first_reviewer = _SequenceLiveReviewer(((_REPAIRABLE,),))
    first_review = _completed_review(
        await governance.review_enforced(
            claimed=claimed,
            source=source,
            article=article,
            reviewer=first_reviewer,
        )
    )
    assert first_review is not None and first_review.contract is not None
    directives = project_repair_directives(first_review.contract, first_review.verdict)
    base_fingerprint = run_request_fingerprint(
        source_fingerprint=source.source_fingerprint,
        generation_mode=claimed.generation_mode,
        identity=claimed.identity,
    )
    request = OfficialAccountRepairRequest(
        run_id=claimed.run_id,
        source=source,
        article=article.article,
        directives=directives,
        identity=claimed.identity,
        request_fingerprint=base_fingerprint,
        max_output_tokens=claimed.identity.reviewer_repair_max_output_tokens,
    )
    result, intent = _provider_completed_repair(
        await governance.govern_repair(
            claimed=claimed,
            request=request,
            repairer=_LiveRepairer(),
            source_review=first_review,
        )
    )
    media = await repository.load_source_media_candidates(claimed)
    package = local_service._build_repaired_article_package(
        source_article=article.article,
        draft=result.draft,
        source=source,
        source_media_candidates=media,
        default_author=claimed.identity.default_author,
    )
    validation = validate_article_package(
        package,
        source=source,
        default_author=claimed.identity.default_author,
        min_characters=claimed.identity.min_characters,
        target_min_characters=claimed.identity.target_min_characters,
        target_max_characters=claimed.identity.target_max_characters,
        max_characters=claimed.identity.max_characters,
    )
    repaired = await repository.persist_repaired_article(
        claimed=claimed,
        repair_intent_id=intent.id,
        source_article=article,
        article=package,
        result=result,
        validation_issues=validation,
    )
    assert repaired is not None
    await governance.complete_repair(
        claimed=claimed,
        intent=replace(
            intent,
            status="completed",
            repaired_article_version_id=repaired.id,
        ),
        succeeded=True,
    )
    audit_request = OfficialAccountAuditRequest(
        run_id=claimed.run_id,
        source=source,
        article=repaired.article,
        identity=claimed.identity,
        request_fingerprint=base_fingerprint,
        max_output_tokens=1_024,
    )
    audit = await DeterministicFakeOfficialAccountArticleAuditor().audit(audit_request)
    repaired = await repository.persist_audit(
        claimed=claimed,
        article=repaired,
        result=replace(
            audit,
            provider="zhipu",
            model=claimed.identity.model,
            request_fingerprint=audit_request_fingerprint(audit_request),
        ),
    )
    assert repaired is not None and repaired.audit is not None and repaired.audit.accepted
    return repository, claimed, source, repaired


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.parametrize("final_accepted", (True, False))
async def test_enforce_one_repair_r2_is_terminal_and_active_lineage_is_exact(
    integration_context: IntegrationContext,
    final_accepted: bool,
) -> None:
    repository, claimed = await _prepare_claim(
        integration_context,
        suffix=f"terminal-{final_accepted}",
    )
    source = fixture_source_snapshot(multi_image=True, semantic_media=True)
    article = await repository.get_article(claimed.run_id)
    assert article is not None and article.revision_no == 1 and article.audit is not None
    media = await repository.load_source_media_candidates(claimed)
    reviewer = _SequenceLiveReviewer(((_REPAIRABLE,), () if final_accepted else (_REPAIRABLE,)))
    governance = _governance(integration_context)
    base_fingerprint = run_request_fingerprint(
        source_fingerprint=source.source_fingerprint,
        generation_mode=claimed.generation_mode,
        identity=claimed.identity,
    )
    await governance.govern_generation(
        claimed=claimed,
        request=OfficialAccountGenerationRequest(
            run_id=claimed.run_id,
            source=source,
            identity=claimed.identity,
            request_fingerprint=base_fingerprint,
            max_output_tokens=claimed.identity.reviewer_writer_max_output_tokens,
        ),
        generator=_LiveGenerator(),
    )

    first_review = _completed_review(
        await governance.review_enforced(
            claimed=claimed,
            source=source,
            article=article,
            reviewer=reviewer,
        )
    )
    assert first_review.contract is not None
    directives = project_repair_directives(first_review.contract, first_review.verdict)
    assert directives
    repair_request = OfficialAccountRepairRequest(
        run_id=claimed.run_id,
        source=source,
        article=article.article,
        directives=directives,
        identity=claimed.identity,
        request_fingerprint=base_fingerprint,
        max_output_tokens=claimed.identity.reviewer_repair_max_output_tokens,
    )
    repairer = _LiveRepairer()
    repair_result, repair_intent = _provider_completed_repair(
        await governance.govern_repair(
            claimed=claimed,
            request=repair_request,
            repairer=repairer,
            source_review=first_review,
        )
    )
    repaired_package = local_service._build_repaired_article_package(
        source_article=article.article,
        draft=repair_result.draft,
        source=source,
        source_media_candidates=media,
        default_author=claimed.identity.default_author,
    )
    validation = validate_article_package(
        repaired_package,
        source=source,
        default_author=claimed.identity.default_author,
        min_characters=claimed.identity.min_characters,
        target_min_characters=claimed.identity.target_min_characters,
        target_max_characters=claimed.identity.target_max_characters,
        max_characters=claimed.identity.max_characters,
    )
    stale_claim = replace(claimed, lease_token=uuid4())
    assert (
        await repository.persist_repaired_article(
            claimed=stale_claim,
            repair_intent_id=repair_intent.id,
            source_article=article,
            article=repaired_package,
            result=repair_result,
            validation_issues=validation,
        )
        is None
    )
    assert await repository.get_article_revision(claimed.run_id, 2) is None
    repaired = await repository.persist_repaired_article(
        claimed=claimed,
        repair_intent_id=repair_intent.id,
        source_article=article,
        article=repaired_package,
        result=repair_result,
        validation_issues=validation,
    )
    assert repaired is not None and repaired.revision_no == 2
    await governance.complete_repair(
        claimed=claimed,
        intent=replace(
            repair_intent,
            status="completed",
            repaired_article_version_id=repaired.id,
        ),
        succeeded=True,
    )

    audit_request = OfficialAccountAuditRequest(
        run_id=claimed.run_id,
        source=source,
        article=repaired.article,
        identity=claimed.identity,
        request_fingerprint=base_fingerprint,
        max_output_tokens=1_024,
    )
    audit = await DeterministicFakeOfficialAccountArticleAuditor().audit(audit_request)
    repaired = await repository.persist_audit(
        claimed=claimed,
        article=repaired,
        result=replace(
            audit,
            provider="zhipu",
            model=claimed.identity.model,
            request_fingerprint=audit_request_fingerprint(audit_request),
        ),
    )
    assert repaired is not None and repaired.audit is not None and repaired.audit.accepted
    final_review = _completed_review(
        await governance.review_enforced(
            claimed=claimed,
            source=source,
            article=repaired,
            reviewer=reviewer,
        )
    )
    assert reviewer.call_count == 2
    assert repairer.call_count == 1

    replayed = await repository.persist_repaired_article(
        claimed=claimed,
        repair_intent_id=repair_intent.id,
        source_article=article,
        article=repaired_package,
        result=repair_result,
        validation_issues=validation,
    )
    assert replayed is not None and replayed.id == repaired.id
    async with integration_context.session_factory() as session:
        reservations_before = tuple(
            await session.scalars(
                select(ExecutionBudgetReservationModel).where(
                    ExecutionBudgetReservationModel.task_id == f"official.review:{claimed.run_id}"
                )
            )
        )
    replay_repairer = _LiveRepairer()
    replay_outcome = await governance.govern_repair(
        claimed=claimed,
        request=repair_request,
        repairer=replay_repairer,
        source_review=first_review,
    )
    assert replay_outcome.status == "completed"
    async with integration_context.session_factory() as session:
        reservations_after = tuple(
            await session.scalars(
                select(ExecutionBudgetReservationModel).where(
                    ExecutionBudgetReservationModel.task_id == f"official.review:{claimed.run_id}"
                )
            )
        )
    assert replay_repairer.call_count == 0
    assert len(reservations_before) == len(reservations_after) == 4

    rendered = None
    if final_accepted:
        assert final_review.verdict.decision is ReviewDecision.ACCEPTED
        stale_claim = replace(claimed, lease_token=uuid4())
        assert not await repository.activate_reviewed_article(
            claimed=stale_claim,
            article=repaired,
            review_record_id=final_review.id,
        )
        with pytest.raises(
            RuntimeError,
            match="accepted Reviewer lineage is invalid",
        ):
            await repository.activate_reviewed_article(
                claimed=claimed,
                article=repaired,
                review_record_id=first_review.id,
            )
        assert await repository.activate_reviewed_article(
            claimed=claimed,
            article=repaired,
            review_record_id=final_review.id,
        )
        with pytest.raises(RuntimeError, match="render Article is not active"):
            await repository.persist_render(
                claimed=claimed,
                article=article,
                rendered=render_wechat_html(
                    article.article,
                    renderer_version=claimed.identity.renderer_version,
                    style_version=claimed.identity.style_version,
                    template_version=claimed.identity.template_version,
                ),
            )
        async with integration_context.session_factory() as session:
            with pytest.raises(IntegrityError):
                await session.execute(
                    update(OfficialAccountArticleRunModel)
                    .where(OfficialAccountArticleRunModel.id == claimed.run_id)
                    .values(active_review_record_id=first_review.id)
                )
                await session.commit()
            await session.rollback()
            assert (
                await session.scalar(
                    select(OfficialAccountRenderVersionModel).where(
                        OfficialAccountRenderVersionModel.run_id == claimed.run_id
                    )
                )
                is None
            )
        rendered = await repository.persist_render(
            claimed=claimed,
            article=repaired,
            rendered=render_wechat_html(
                repaired.article,
                renderer_version=claimed.identity.renderer_version,
                style_version=claimed.identity.style_version,
                template_version=claimed.identity.template_version,
            ),
        )
        assert rendered is not None and rendered.article_version_id == repaired.id
        assert rendered.review_record_id == final_review.id
        async with integration_context.session_factory() as session:
            with pytest.raises(IntegrityError):
                await session.execute(
                    update(OfficialAccountArticleRunModel)
                    .where(OfficialAccountArticleRunModel.id == claimed.run_id)
                    .values(active_review_record_id=first_review.id)
                )
                await session.commit()
            await session.rollback()
        assert await repository.get_render(claimed.run_id) == rendered
    else:
        assert final_review.verdict.decision is ReviewDecision.REJECTED
        await repository.require_manual_review(
            claimed=claimed,
            error_code="reviewer_repair_exhausted",
        )
    await governance.complete_enforced(
        claimed=claimed,
        source=source,
        succeeded=final_accepted,
    )

    async with integration_context.session_factory() as session:
        revisions = tuple(
            await session.scalars(
                select(OfficialAccountArticleVersionModel)
                .where(OfficialAccountArticleVersionModel.run_id == claimed.run_id)
                .order_by(OfficialAccountArticleVersionModel.revision_no)
            )
        )
        repair = await session.scalar(
            select(OfficialAccountRepairRequestModel).where(
                OfficialAccountRepairRequestModel.run_id == claimed.run_id
            )
        )
        reviews = tuple(
            await session.scalars(
                select(OfficialAccountReviewRequestModel).where(
                    OfficialAccountReviewRequestModel.run_id == claimed.run_id
                )
            )
        )
        agents = set(
            await session.scalars(
                select(ExecutionAgentAllocationModel.agent_id).where(
                    ExecutionAgentAllocationModel.run_id == reviews[0].execution_run_id
                )
            )
        )
        run = await session.get(OfficialAccountArticleRunModel, claimed.run_id)
        render = await session.scalar(
            select(OfficialAccountRenderVersionModel).where(
                OfficialAccountRenderVersionModel.run_id == claimed.run_id
            )
        )
    assert tuple(item.revision_no for item in revisions) == (1, 2)
    assert revisions[1].repair_of_article_version_id == revisions[0].id
    assert repair is not None and repair.status == "completed"
    assert len(reviews) == 2
    assert {
        "official.writer.initial",
        "official.reviewer.r1",
        "official.writer.repair",
        "official.reviewer.r2",
    } <= agents
    assert run is not None
    assert run.active_article_version_id == (repaired.id if final_accepted else article.id)
    assert run.active_review_record_id == (final_review.id if final_accepted else None)
    async with integration_context.session_factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                update(OfficialAccountRepairRequestModel)
                .where(OfficialAccountRepairRequestModel.id == repair.id)
                .values(source_review_request_id=final_review.request_id)
            )
            await session.commit()
        await session.rollback()
    if final_accepted:
        assert rendered is not None
        assert render is not None and render.article_version_id == repaired.id
        assert render.review_record_id == final_review.id
    else:
        assert render is None

    async with integration_context.session_factory() as session:
        with pytest.raises(IntegrityError):
            await session.execute(
                update(OfficialAccountArticleVersionModel)
                .where(OfficialAccountArticleVersionModel.id == repaired.id)
                .values(revision_no=3)
            )
            await session.commit()
        await session.rollback()


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_repair_provider_exception_is_unknown_and_never_recalled(
    integration_context: IntegrationContext,
) -> None:
    repository, claimed = await _prepare_claim(
        integration_context,
        suffix="repair-provider-failure",
    )
    source = fixture_source_snapshot(multi_image=True, semantic_media=True)
    article = await repository.get_article(claimed.run_id)
    assert article is not None
    governance = _governance(integration_context)
    first_review = _completed_review(
        await governance.review_enforced(
            claimed=claimed,
            source=source,
            article=article,
            reviewer=_SequenceLiveReviewer(((_REPAIRABLE,),)),
        )
    )
    assert first_review.contract is not None
    repair_request = OfficialAccountRepairRequest(
        run_id=claimed.run_id,
        source=source,
        article=article.article,
        directives=project_repair_directives(first_review.contract, first_review.verdict),
        identity=claimed.identity,
        request_fingerprint=run_request_fingerprint(
            source_fingerprint=source.source_fingerprint,
            generation_mode=claimed.generation_mode,
            identity=claimed.identity,
        ),
        max_output_tokens=claimed.identity.reviewer_repair_max_output_tokens,
    )
    failing = _FailingLiveRepairer()
    failed = await governance.govern_repair(
        claimed=claimed,
        request=repair_request,
        repairer=failing,
        source_review=first_review,
    )
    assert failed.status == "result_unknown"
    assert failing.call_count == 1

    retry = _LiveRepairer()
    replayed = await governance.govern_repair(
        claimed=claimed,
        request=repair_request,
        repairer=retry,
        source_review=first_review,
    )
    assert replayed.status == "result_unknown"
    assert retry.call_count == 0
    await repository.require_manual_review(
        claimed=claimed,
        error_code="repair_result_unknown",
    )
    await governance.complete_enforced(claimed=claimed, source=source, succeeded=False)

    async with integration_context.session_factory() as session:
        repair_intent = await session.scalar(
            select(OfficialAccountRepairRequestModel).where(
                OfficialAccountRepairRequestModel.run_id == claimed.run_id
            )
        )
        r2 = await session.scalar(
            select(OfficialAccountArticleVersionModel).where(
                OfficialAccountArticleVersionModel.run_id == claimed.run_id,
                OfficialAccountArticleVersionModel.revision_no == 2,
            )
        )
        r2_agent = await session.scalar(
            select(ExecutionAgentAllocationModel).where(
                ExecutionAgentAllocationModel.task_id == f"official.review:{claimed.run_id}",
                ExecutionAgentAllocationModel.agent_id == "official.reviewer.r2",
            )
        )
        run = await session.get(OfficialAccountArticleRunModel, claimed.run_id)
    assert repair_intent is not None and repair_intent.status == "result_unknown"
    assert repair_intent.error_code == "repair_result_unknown"
    assert r2 is None and r2_agent is None
    assert run is not None and run.status == "review_required"


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_crash_after_repair_commit_recovers_writer_without_provider_recall(
    integration_context: IntegrationContext,
) -> None:
    repository, claimed = await _prepare_claim(
        integration_context,
        suffix="repair-commit-crash",
    )
    source = fixture_source_snapshot(multi_image=True, semantic_media=True)
    article = await repository.get_article(claimed.run_id)
    assert article is not None
    governance = _governance(integration_context)
    first_review = _completed_review(
        await governance.review_enforced(
            claimed=claimed,
            source=source,
            article=article,
            reviewer=_SequenceLiveReviewer(((_REPAIRABLE,),)),
        )
    )
    assert first_review.contract is not None
    directives = project_repair_directives(first_review.contract, first_review.verdict)
    repair_request = OfficialAccountRepairRequest(
        run_id=claimed.run_id,
        source=source,
        article=article.article,
        directives=directives,
        identity=claimed.identity,
        request_fingerprint=run_request_fingerprint(
            source_fingerprint=source.source_fingerprint,
            generation_mode=claimed.generation_mode,
            identity=claimed.identity,
        ),
        max_output_tokens=claimed.identity.reviewer_repair_max_output_tokens,
    )
    repair_result, repair_intent = _provider_completed_repair(
        await governance.govern_repair(
            claimed=claimed,
            request=repair_request,
            repairer=_LiveRepairer(),
            source_review=first_review,
        )
    )
    repaired_package = local_service._build_repaired_article_package(
        source_article=article.article,
        draft=repair_result.draft,
        source=source,
        source_media_candidates=await repository.load_source_media_candidates(claimed),
        default_author=claimed.identity.default_author,
    )
    repaired = await repository.persist_repaired_article(
        claimed=claimed,
        repair_intent_id=repair_intent.id,
        source_article=article,
        article=repaired_package,
        result=repair_result,
        validation_issues=validate_article_package(
            repaired_package,
            source=source,
            default_author=claimed.identity.default_author,
            min_characters=claimed.identity.min_characters,
            target_min_characters=claimed.identity.target_min_characters,
            target_max_characters=claimed.identity.target_max_characters,
            max_characters=claimed.identity.max_characters,
        ),
    )
    assert repaired is not None

    # Simulate process death before complete_repair() closes the governed Writer.
    async with integration_context.session_factory() as session:
        repair_allocation = await session.scalar(
            select(ExecutionAgentAllocationModel).where(
                ExecutionAgentAllocationModel.task_id == f"official.review:{claimed.run_id}",
                ExecutionAgentAllocationModel.agent_id == "official.writer.repair",
            )
        )
    assert repair_allocation is not None and repair_allocation.status == "running"

    replay_reviewer = _SequenceLiveReviewer(((),))
    replay_repairer = _LiveRepairer()
    executor = _enforce_executor(
        integration_context,
        reviewer=replay_reviewer,
        repairer=replay_repairer,
    )
    recovered = await executor._enforce_editorial_review(
        claimed,
        source,
        article,
        source_media_candidates=await repository.load_source_media_candidates(claimed),
    )

    assert recovered is not None and recovered.id == repaired.id
    assert replay_repairer.call_count == 0
    assert replay_reviewer.call_count == 1
    async with integration_context.session_factory() as session:
        repair_allocation = await session.scalar(
            select(ExecutionAgentAllocationModel).where(
                ExecutionAgentAllocationModel.task_id == f"official.review:{claimed.run_id}",
                ExecutionAgentAllocationModel.agent_id == "official.writer.repair",
            )
        )
        root_allocation = await session.scalar(
            select(ExecutionAgentAllocationModel).where(
                ExecutionAgentAllocationModel.task_id == f"official.review:{claimed.run_id}",
                ExecutionAgentAllocationModel.agent_id == "official.review.orchestrator",
            )
        )
        run = await session.get(OfficialAccountArticleRunModel, claimed.run_id)
    assert repair_allocation is not None and repair_allocation.status == "succeeded"
    assert root_allocation is not None and root_allocation.status == "succeeded"
    assert run is not None and run.active_article_version_id == repaired.id
    assert run.active_review_record_id is not None


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.parametrize(
    ("outcome", "decision"),
    (
        ((_MANUAL,), ReviewDecision.MANUAL_REVIEW),
        (ReviewUnavailableReason.PROVIDER_UNAVAILABLE, ReviewDecision.UNAVAILABLE),
    ),
)
async def test_enforce_manual_or_unavailable_never_allocates_repair(
    integration_context: IntegrationContext,
    outcome: tuple[ReviewIssue, ...] | ReviewUnavailableReason,
    decision: ReviewDecision,
) -> None:
    repository, claimed = await _prepare_claim(
        integration_context,
        suffix=f"closed-{decision.value}",
    )
    article = await repository.get_article(claimed.run_id)
    assert article is not None
    source = fixture_source_snapshot(multi_image=True, semantic_media=True)
    reviewer = _SequenceLiveReviewer((outcome,))
    governance = _governance(integration_context)
    record = _completed_review(
        await governance.review_enforced(
            claimed=claimed,
            source=source,
            article=article,
            reviewer=reviewer,
        )
    )
    assert record.verdict.decision is decision
    assert record.contract is not None
    assert project_repair_directives(record.contract, record.verdict) == ()
    await repository.require_manual_review(claimed=claimed, error_code="reviewer_nonrepairable")
    await governance.complete_enforced(claimed=claimed, source=source, succeeded=False)
    async with integration_context.session_factory() as session:
        repair_count = len(
            tuple(
                await session.scalars(
                    select(OfficialAccountRepairRequestModel).where(
                        OfficialAccountRepairRequestModel.run_id == claimed.run_id
                    )
                )
            )
        )
        repair_agent = await session.scalar(
            select(ExecutionAgentAllocationModel).where(
                ExecutionAgentAllocationModel.agent_id == "official.writer.repair",
                ExecutionAgentAllocationModel.task_id == f"official.review:{claimed.run_id}",
            )
        )
    assert reviewer.call_count == 1
    assert repair_count == 0
    assert repair_agent is None


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_enforce_budget_fence_denies_repair_before_provider_without_minting(
    integration_context: IntegrationContext,
) -> None:
    repository, claimed = await _prepare_claim(
        integration_context,
        suffix="repair-budget-denied",
    )
    source = fixture_source_snapshot(multi_image=True, semantic_media=True)
    article = await repository.get_article(claimed.run_id)
    assert article is not None
    governance = _governance(integration_context)
    reviewer = _SequenceLiveReviewer(((_REPAIRABLE,),))
    first_review = _completed_review(
        await governance.review_enforced(
            claimed=claimed,
            source=source,
            article=article,
            reviewer=reviewer,
        )
    )
    assert first_review.contract is not None
    directives = project_repair_directives(first_review.contract, first_review.verdict)
    async with integration_context.session_factory() as session:
        request = await session.get(OfficialAccountReviewRequestModel, first_review.request_id)
        assert request is not None and request.execution_run_id is not None
        root = await session.get(
            ExecutionAgentAllocationModel,
            (
                request.execution_run_id,
                f"official.review:{claimed.run_id}",
                "official.review.orchestrator",
            ),
        )
        assert root is not None
        frozen_limit = root.limit_model_turns
        root.used_model_turns = frozen_limit
        await session.commit()
    repair_request = OfficialAccountRepairRequest(
        run_id=claimed.run_id,
        source=source,
        article=article.article,
        directives=directives,
        identity=claimed.identity,
        request_fingerprint=run_request_fingerprint(
            source_fingerprint=source.source_fingerprint,
            generation_mode=claimed.generation_mode,
            identity=claimed.identity,
        ),
        max_output_tokens=claimed.identity.reviewer_repair_max_output_tokens,
    )
    repairer = _LiveRepairer()
    outcome = await governance.govern_repair(
        claimed=claimed,
        request=repair_request,
        repairer=repairer,
        source_review=first_review,
    )

    assert outcome.status == "denied"
    assert repairer.call_count == 0
    await repository.require_manual_review(
        claimed=claimed,
        error_code="repair_governance_denied",
    )
    await governance.complete_enforced(claimed=claimed, source=source, succeeded=False)
    async with integration_context.session_factory() as session:
        root = await session.get(
            ExecutionAgentAllocationModel,
            (
                request.execution_run_id,
                f"official.review:{claimed.run_id}",
                "official.review.orchestrator",
            ),
        )
        repair_allocation = await session.scalar(
            select(ExecutionAgentAllocationModel).where(
                ExecutionAgentAllocationModel.run_id == request.execution_run_id,
                ExecutionAgentAllocationModel.agent_id == "official.writer.repair",
            )
        )
        run = await session.get(OfficialAccountArticleRunModel, claimed.run_id)
    assert root is not None and root.limit_model_turns == frozen_limit
    assert repair_allocation is None
    assert run is not None and run.status == "review_required"


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_executor_same_attempt_r1_in_flight_does_not_poison_owner(
    integration_context: IntegrationContext,
) -> None:
    repository, claimed = await _prepare_claim(
        integration_context,
        suffix="executor-r1-join",
    )
    source = fixture_source_snapshot(multi_image=True, semantic_media=True)
    article = await repository.get_article(claimed.run_id)
    assert article is not None
    media = await repository.load_source_media_candidates(claimed)
    reviewer = _BlockingLiveReviewer()
    executor = _enforce_executor(
        integration_context,
        reviewer=reviewer,
        repairer=None,
    )
    owner = asyncio.create_task(
        executor._enforce_editorial_review(
            claimed,
            source,
            article,
            source_media_candidates=media,
        )
    )
    await asyncio.wait_for(reviewer.started.wait(), timeout=5)

    assert (
        await executor._enforce_editorial_review(
            claimed,
            source,
            article,
            source_media_candidates=media,
        )
        is None
    )
    async with integration_context.session_factory() as session:
        run = await session.get(OfficialAccountArticleRunModel, claimed.run_id)
        request = await session.scalar(
            select(OfficialAccountReviewRequestModel).where(
                OfficialAccountReviewRequestModel.run_id == claimed.run_id,
                OfficialAccountReviewRequestModel.article_version_id == article.id,
            )
        )
    assert run is not None and run.status == "running"
    assert run.active_review_record_id is None
    assert request is not None and request.status == "calling"

    reviewer.release.set()
    assert await asyncio.wait_for(owner, timeout=5) == article
    assert reviewer.call_count == 1
    async with integration_context.session_factory() as session:
        run = await session.get(OfficialAccountArticleRunModel, claimed.run_id)
    assert run is not None and run.status == "running"
    assert run.active_article_version_id == article.id
    assert run.active_review_record_id is not None


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_executor_same_attempt_repair_in_flight_does_not_poison_owner(
    integration_context: IntegrationContext,
) -> None:
    repository, claimed = await _prepare_claim(
        integration_context,
        suffix="executor-repair-join",
    )
    source = fixture_source_snapshot(multi_image=True, semantic_media=True)
    article = await repository.get_article(claimed.run_id)
    assert article is not None
    media = await repository.load_source_media_candidates(claimed)
    reviewer = _SequenceLiveReviewer(((_REPAIRABLE,), ()))
    repairer = _BlockingLiveRepairer()
    executor = _enforce_executor(
        integration_context,
        reviewer=reviewer,
        repairer=repairer,
    )
    owner = asyncio.create_task(
        executor._enforce_editorial_review(
            claimed,
            source,
            article,
            source_media_candidates=media,
        )
    )
    await asyncio.wait_for(repairer.started.wait(), timeout=5)

    assert (
        await executor._enforce_editorial_review(
            claimed,
            source,
            article,
            source_media_candidates=media,
        )
        is None
    )
    async with integration_context.session_factory() as session:
        run = await session.get(OfficialAccountArticleRunModel, claimed.run_id)
        repair = await session.scalar(
            select(OfficialAccountRepairRequestModel).where(
                OfficialAccountRepairRequestModel.run_id == claimed.run_id
            )
        )
    assert run is not None and run.status == "running"
    assert run.active_review_record_id is None
    assert repair is not None and repair.status == "calling"

    repairer.release.set()
    repaired = await asyncio.wait_for(owner, timeout=5)
    assert repaired is not None and repaired.revision_no == 2
    assert repairer.call_count == 1
    assert reviewer.call_count == 2
    async with integration_context.session_factory() as session:
        run = await session.get(OfficialAccountArticleRunModel, claimed.run_id)
        repair = await session.scalar(
            select(OfficialAccountRepairRequestModel).where(
                OfficialAccountRepairRequestModel.run_id == claimed.run_id
            )
        )
    assert run is not None and run.status == "running"
    assert run.active_article_version_id == repaired.id
    assert run.active_review_record_id is not None
    assert repair is not None and repair.status == "completed"


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_repair_same_attempt_joins_and_later_attempt_becomes_unknown_without_recall(
    integration_context: IntegrationContext,
) -> None:
    repository, claimed = await _prepare_claim(
        integration_context,
        suffix="repair-fence",
    )
    source = fixture_source_snapshot(multi_image=True, semantic_media=True)
    article = await repository.get_article(claimed.run_id)
    assert article is not None
    reviewer = _SequenceLiveReviewer(((_REPAIRABLE,),))
    governance = _governance(integration_context)
    first_review = _completed_review(
        await governance.review_enforced(
            claimed=claimed,
            source=source,
            article=article,
            reviewer=reviewer,
        )
    )
    assert first_review.contract is not None
    directives = project_repair_directives(first_review.contract, first_review.verdict)
    repair_request = OfficialAccountRepairRequest(
        run_id=claimed.run_id,
        source=source,
        article=article.article,
        directives=directives,
        identity=claimed.identity,
        request_fingerprint=run_request_fingerprint(
            source_fingerprint=source.source_fingerprint,
            generation_mode=claimed.generation_mode,
            identity=claimed.identity,
        ),
        max_output_tokens=claimed.identity.reviewer_repair_max_output_tokens,
    )
    owner = _BlockingLiveRepairer()
    owner_task = asyncio.create_task(
        governance.govern_repair(
            claimed=claimed,
            request=repair_request,
            repairer=owner,
            source_review=first_review,
        )
    )
    await asyncio.wait_for(owner.started.wait(), timeout=5)

    same_attempt = _LiveRepairer()
    same_attempt_outcome = await governance.govern_repair(
        claimed=claimed,
        request=repair_request,
        repairer=same_attempt,
        source_review=first_review,
    )
    assert same_attempt_outcome.status == "in_flight"
    assert same_attempt.call_count == 0
    async with integration_context.session_factory() as session:
        repair_reservations_while_calling = tuple(
            await session.scalars(
                select(ExecutionBudgetReservationModel).where(
                    ExecutionBudgetReservationModel.task_id == f"official.review:{claimed.run_id}",
                    ExecutionBudgetReservationModel.agent_id == "official.writer.repair",
                )
            )
        )
    assert len(repair_reservations_while_calling) == 1

    owner.release.set()
    first = await asyncio.wait_for(owner_task, timeout=5)
    assert first.status == "provider_completed" and owner.call_count == 1

    next_lease = uuid4()
    async with integration_context.session_factory() as session:
        await session.execute(
            update(OfficialAccountArticleRunModel)
            .where(OfficialAccountArticleRunModel.id == claimed.run_id)
            .values(
                attempt_count=claimed.attempt_number + 1,
                lease_token=next_lease,
                lease_owner="repair-fence-reclaimer",
                lease_expires_at=datetime.now(UTC) + timedelta(minutes=5),
            )
        )
        await session.commit()
    reclaimed = replace(
        claimed,
        attempt_number=claimed.attempt_number + 1,
        lease_token=next_lease,
    )
    retry = _LiveRepairer()
    reclaimed_outcome = await governance.govern_repair(
        claimed=reclaimed,
        request=repair_request,
        repairer=retry,
        source_review=first_review,
    )
    assert reclaimed_outcome.status == "result_unknown"
    assert retry.call_count == 0
    await repository.require_manual_review(
        claimed=reclaimed,
        error_code="repair_result_unknown",
    )
    await governance.complete_enforced(
        claimed=reclaimed,
        source=source,
        succeeded=False,
    )
    async with integration_context.session_factory() as session:
        intent = await session.scalar(
            select(OfficialAccountRepairRequestModel).where(
                OfficialAccountRepairRequestModel.run_id == claimed.run_id
            )
        )
        revision_two = await session.scalar(
            select(OfficialAccountArticleVersionModel).where(
                OfficialAccountArticleVersionModel.run_id == claimed.run_id,
                OfficialAccountArticleVersionModel.revision_no == 2,
            )
        )
    assert intent is not None and intent.status == "result_unknown"
    assert intent.error_code == "repair_result_unknown"
    assert revision_two is None


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_r2_review_later_attempt_becomes_unknown_and_late_result_is_not_accepted(
    integration_context: IntegrationContext,
) -> None:
    repository, claimed, source, repaired = await _prepare_audited_r2(
        integration_context,
        suffix="r2-review-fence",
    )
    governance = _governance(integration_context)
    owner = _BlockingLiveReviewer()
    owner_task = asyncio.create_task(
        governance.review_enforced(
            claimed=claimed,
            source=source,
            article=repaired,
            reviewer=owner,
        )
    )
    await asyncio.wait_for(owner.started.wait(), timeout=5)

    next_lease = uuid4()
    async with integration_context.session_factory() as session:
        await session.execute(
            update(OfficialAccountArticleRunModel)
            .where(OfficialAccountArticleRunModel.id == claimed.run_id)
            .values(
                attempt_count=claimed.attempt_number + 1,
                lease_token=next_lease,
                lease_owner="r2-review-reclaimer",
                lease_expires_at=datetime.now(UTC) + timedelta(minutes=5),
            )
        )
        await session.commit()
    reclaimed = replace(
        claimed,
        attempt_number=claimed.attempt_number + 1,
        lease_token=next_lease,
    )
    retry = _SequenceLiveReviewer(((),))
    reclaimed_outcome = await governance.review_enforced(
        claimed=reclaimed,
        source=source,
        article=repaired,
        reviewer=retry,
    )
    assert reclaimed_outcome.status == "result_unknown"
    assert retry.call_count == 0

    owner.release.set()
    late_owner_outcome = await asyncio.wait_for(owner_task, timeout=5)
    assert late_owner_outcome.status == "result_unknown"
    assert owner.call_count == 1
    assert await repository.require_manual_review(
        claimed=reclaimed,
        error_code="review_result_unknown",
    )
    await governance.complete_enforced(
        claimed=reclaimed,
        source=source,
        succeeded=False,
    )
    async with integration_context.session_factory() as session:
        r2_request = await session.scalar(
            select(OfficialAccountReviewRequestModel).where(
                OfficialAccountReviewRequestModel.run_id == claimed.run_id,
                OfficialAccountReviewRequestModel.article_version_id == repaired.id,
            )
        )
        r2_reservations = tuple(
            await session.scalars(
                select(ExecutionBudgetReservationModel).where(
                    ExecutionBudgetReservationModel.task_id == f"official.review:{claimed.run_id}",
                    ExecutionBudgetReservationModel.agent_id == "official.reviewer.r2",
                )
            )
        )
        run = await session.get(OfficialAccountArticleRunModel, claimed.run_id)
    assert r2_request is not None and r2_request.status == "result_unknown"
    assert r2_request.error_code == "review_result_unknown"
    assert len(r2_reservations) == 1
    assert run is not None and run.status == "review_required"
    assert run.active_article_version_id != repaired.id
    assert run.active_review_record_id is None
