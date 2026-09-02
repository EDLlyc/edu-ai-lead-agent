from __future__ import annotations

from hashlib import sha256
from uuid import UUID, uuid5

from app.application.ports.execution_governance import ExecutionGovernanceRepository
from app.application.ports.official_account_local import (
    ClaimedOfficialAccountRun,
    OfficialAccountArticleGenerator,
    OfficialAccountGenerationRequest,
    OfficialAccountGenerationResult,
    StoredOfficialAccountArticle,
)
from app.application.ports.official_account_reviewer import (
    OfficialAccountReviewer,
    OfficialAccountReviewerRequest,
    OfficialAccountReviewerResult,
    OfficialAccountReviewGovernance,
    OfficialAccountReviewRepository,
    ReviewArtifactBinding,
    ReviewExecutionBinding,
    StoredReviewIntent,
    StoredReviewRecord,
)
from app.application.services.execution_governance import (
    CapabilityGateway,
    CapabilityInvocationBinding,
    CapabilityRegistry,
    ExecutionGovernanceService,
    GovernedCapabilityResult,
)
from app.application.services.official_account_local import generation_request_fingerprint
from app.application.services.official_account_reviewer import (
    brand_context_sha256,
    build_editorial_review_request,
    exact_article_sha256,
    exact_source_sha256,
    review_execution_scope,
    reviewer_argument_bytes,
)
from app.core.errors import AppError, ProviderIdentityMismatchError
from app.domain.execution_governance import (
    DELEGATION_THRESHOLD_PERCENT,
    ArtifactKind,
    ArtifactMetadata,
    BudgetLimits,
    BudgetUsage,
    CapabilityAccess,
    CapabilityDefinition,
    CapabilityRequest,
    ExecutionEventKind,
    ExecutionEventStatus,
    ExecutionIdentity,
    ExecutionRole,
    ExecutionRunStatus,
    GovernanceDeniedError,
    SafeEventDraft,
)
from app.domain.official_account_local import (
    OfficialAccountSourceSnapshot,
    canonical_json,
    fingerprint,
)
from app.domain.official_account_reviewer import (
    REPAIR_POLICY_VERSION,
    REVIEW_POLICY_VERSION,
    REVIEW_REQUEST_SCHEMA_VERSION,
    REVIEW_RUBRIC_VERSION,
    REVIEW_VERDICT_SCHEMA_VERSION,
    validate_review_verdict_binding,
)

_NAMESPACE = UUID("83148a45-3526-44a3-a82f-d1d50c6d064e")
_ROOT_AGENT = "official.review.orchestrator"
_WRITER_AGENT = "official.writer.initial"
_REVIEWER_AGENT = "official.reviewer.r1"
_WRITER_CAPABILITY = "official.article.generate"
_REVIEWER_CAPABILITY = "official.article.review"
_INPUT_NODE = "official.review.inputs"
_INPUT_ARTIFACT_BUDGET_BYTES = 4 * 1024 * 1024


def reviewer_capability_registry(
    *,
    writer_timeout_ms: int,
    reviewer_timeout_ms: int,
) -> CapabilityRegistry:
    return CapabilityRegistry(
        (
            CapabilityDefinition(
                name=_WRITER_CAPABILITY,
                access=CapabilityAccess.BUSINESS_WRITE,
                allowed_roles=frozenset({ExecutionRole.WORKER}),
                timeout_ms=writer_timeout_ms,
                max_argument_bytes=8 * 1024,
                max_result_bytes=1024 * 1024,
            ),
            CapabilityDefinition(
                name=_REVIEWER_CAPABILITY,
                access=CapabilityAccess.CHECK,
                allowed_roles=frozenset({ExecutionRole.REVIEWER}),
                timeout_ms=reviewer_timeout_ms,
                max_argument_bytes=8 * 1024,
                max_result_bytes=256 * 1024,
                artifact_scoped=True,
            ),
        )
    )


def reviewer_root_limits(
    *,
    writer_timeout_ms: int,
    reviewer_timeout_ms: int,
    writer_max_output_tokens: int,
    reviewer_max_output_tokens: int,
) -> BudgetLimits:
    return BudgetLimits(
        elapsed_ms=_root_dimension_limit(writer_timeout_ms, reviewer_timeout_ms),
        model_turns=_root_dimension_limit(1, 1),
        input_tokens=_root_dimension_limit(80_000, 80_000),
        output_tokens=_root_dimension_limit(
            writer_max_output_tokens,
            reviewer_max_output_tokens,
        ),
        tool_calls=_root_dimension_limit(1, 1),
        tool_result_bytes=_root_dimension_limit(1024 * 1024, 256 * 1024),
        artifact_bytes=_root_dimension_limit(
            _INPUT_ARTIFACT_BUDGET_BYTES,
            256 * 1024,
        ),
        max_children=2,
        max_depth=1,
        allow_child_agents=True,
    )


def _root_dimension_limit(writer_ceiling: int, reviewer_ceiling: int) -> int:
    """Leave every Writer worst case below the shared 70% delegation fence."""

    delegation_safe = (
        writer_ceiling * 100 // DELEGATION_THRESHOLD_PERCENT + 1 if writer_ceiling else 0
    )
    return max(writer_ceiling + reviewer_ceiling, delegation_safe)


def _writer_limits(max_output_tokens: int, timeout_ms: int) -> BudgetLimits:
    return BudgetLimits(
        elapsed_ms=timeout_ms,
        model_turns=1,
        input_tokens=80_000,
        output_tokens=max_output_tokens,
        tool_calls=1,
        tool_result_bytes=1024 * 1024,
        artifact_bytes=0,
    )


def _reviewer_limits(max_output_tokens: int, timeout_ms: int) -> BudgetLimits:
    return BudgetLimits(
        elapsed_ms=timeout_ms,
        model_turns=1,
        input_tokens=80_000,
        output_tokens=max_output_tokens,
        tool_calls=1,
        tool_result_bytes=256 * 1024,
        artifact_bytes=256 * 1024,
    )


class PostgresOfficialAccountReviewerGovernance(OfficialAccountReviewGovernance):
    def __init__(
        self,
        *,
        execution_repository: ExecutionGovernanceRepository,
        review_repository: OfficialAccountReviewRepository,
    ) -> None:
        self._execution_repository = execution_repository
        self._review_repository = review_repository
        self._service = ExecutionGovernanceService(execution_repository)

    def _gateway(self, claimed: ClaimedOfficialAccountRun) -> CapabilityGateway:
        return CapabilityGateway(
            repository=self._execution_repository,
            registry=reviewer_capability_registry(
                writer_timeout_ms=claimed.identity.reviewer_writer_timeout_ms,
                reviewer_timeout_ms=claimed.identity.reviewer_timeout_ms,
            ),
        )

    async def govern_generation(
        self,
        *,
        claimed: ClaimedOfficialAccountRun,
        request: OfficialAccountGenerationRequest,
        generator: OfficialAccountArticleGenerator,
    ) -> OfficialAccountGenerationResult:
        self._validate_frozen_budget_identity(claimed)
        if request.max_output_tokens != claimed.identity.reviewer_writer_max_output_tokens:
            raise RuntimeError("governed Writer frozen output budget changed")
        root, root_event = await self._ensure_run(claimed, request.source)
        allocation, start = await self._ensure_child(
            parent=root,
            parent_event_id=root_event,
            agent_id=_WRITER_AGENT,
            role=ExecutionRole.WORKER,
            limits=_writer_limits(
                claimed.identity.reviewer_writer_max_output_tokens,
                claimed.identity.reviewer_writer_timeout_ms,
            ),
            target=_WRITER_CAPABILITY,
        )

        async def handler() -> GovernedCapabilityResult[OfficialAccountGenerationResult]:
            result = await generator.generate(request)
            if (
                result.provider != request.identity.provider
                or result.model != request.identity.model
                or result.request_fingerprint != generation_request_fingerprint(request)
            ):
                raise ProviderIdentityMismatchError()
            result_bytes = len(canonical_json(result.draft).encode("utf-8"))
            return GovernedCapabilityResult(
                value=result,
                result_bytes=result_bytes,
                input_tokens=result.prompt_tokens,
                output_tokens=result.completion_tokens + result.reasoning_tokens,
                model_turns=1,
            )

        try:
            governed = await self._gateway(claimed).invoke(
                CapabilityRequest(
                    identity=allocation,
                    role=ExecutionRole.WORKER,
                    capability_name=_WRITER_CAPABILITY,
                    target_task_id=allocation.task_id,
                    parent_event_id=start,
                    argument_bytes=256,
                    expected_input_tokens=80_000,
                    expected_output_tokens=claimed.identity.reviewer_writer_max_output_tokens,
                    model_turns=1,
                    tool_calls=1,
                ),
                handler,
            )
        except GovernanceDeniedError as error:
            failure = await self._complete_child(
                allocation,
                start,
                _WRITER_CAPABILITY,
                succeeded=False,
            )
            await self._fail_root(root, failure)
            raise AppError(
                "official_account_generation_governance_failed",
                "governed article generation failed",
                503,
                False,
            ) from error
        if governed.execution is None:
            raise RuntimeError("governed Writer completion binding is missing")
        await self._complete_child(
            allocation,
            governed.execution.result_event_id,
            _WRITER_CAPABILITY,
            succeeded=True,
        )
        return governed.value

    async def observe(
        self,
        *,
        claimed: ClaimedOfficialAccountRun,
        source: OfficialAccountSourceSnapshot,
        article: StoredOfficialAccountArticle,
        reviewer: OfficialAccountReviewer,
    ) -> StoredReviewRecord | None:
        self._validate_frozen_budget_identity(claimed)
        frozen_contract_versions = (
            claimed.identity.reviewer_request_schema_version,
            claimed.identity.reviewer_verdict_schema_version,
            claimed.identity.reviewer_rubric_version,
            claimed.identity.reviewer_review_policy_version,
            claimed.identity.reviewer_repair_policy_version,
        )
        if frozen_contract_versions != (
            REVIEW_REQUEST_SCHEMA_VERSION,
            REVIEW_VERDICT_SCHEMA_VERSION,
            REVIEW_RUBRIC_VERSION,
            REVIEW_POLICY_VERSION,
            REPAIR_POLICY_VERSION,
        ):
            raise RuntimeError("official-account Reviewer frozen contract identity changed")
        if (
            reviewer.provider != claimed.identity.reviewer_provider
            or reviewer.model != claimed.identity.reviewer_model
        ):
            raise RuntimeError("official-account Reviewer frozen model identity changed")
        root, root_event = await self._ensure_run(claimed, source)
        input_event = await self._ensure_input_node(root, root_event)
        artifacts = await self._ensure_input_artifacts(
            identity=root,
            parent_event_id=input_event,
            source=source,
            article=article,
        )
        contract = build_editorial_review_request(
            run_id=claimed.run_id,
            article_version_id=article.id,
            article=article.article,
            source=source,
            reviewer_version=claimed.identity.reviewer_version,
            prompt_version=claimed.identity.reviewer_prompt_version,
        )
        intent = await self._review_repository.create_intent(
            claimed=claimed,
            article=article,
            contract=contract,
            artifacts=artifacts,
            provider=reviewer.provider,
            model=reviewer.model,
        )
        if intent.status == "completed":
            record = await self._review_repository.get_record(intent.id)
            if record is None:
                raise RuntimeError("completed official-account review has no record")
            await self._recover_terminal(intent=intent, root=root, record=record)
            return record
        if intent.status == "result_unknown":
            await self._recover_terminal(intent=intent, root=root, record=None)
            return None
        if intent.status == "calling":
            if intent.attempt_number == claimed.attempt_number:
                # A compatible invocation under the same fenced business attempt is still
                # in flight. It must neither call the provider again nor poison the owner.
                return None
            intent = await self._review_repository.mark_result_unknown(
                intent=intent,
                error_code="review_result_unknown",
            )
            await self._recover_terminal(intent=intent, root=root, record=None)
            return None

        reviewer_identity, start = await self._ensure_child(
            parent=root,
            parent_event_id=input_event,
            agent_id=_REVIEWER_AGENT,
            role=ExecutionRole.REVIEWER,
            limits=_reviewer_limits(
                claimed.identity.reviewer_max_output_tokens,
                claimed.identity.reviewer_timeout_ms,
            ),
            target=_REVIEWER_CAPABILITY,
        )
        current_intent = intent

        async def before_handler(binding: CapabilityInvocationBinding) -> None:
            nonlocal current_intent
            current_intent = await self._review_repository.mark_calling(
                intent=current_intent,
                execution=ReviewExecutionBinding(
                    execution_run_id=binding.identity.run_id,
                    task_id=binding.identity.task_id,
                    reviewer_agent_id=binding.identity.agent_id,
                    reviewer_parent_event_id=start,
                    reservation_id=binding.reservation_id,
                    request_event_id=binding.request_event_id,
                ),
            )

        async def handler() -> GovernedCapabilityResult[OfficialAccountReviewerResult]:
            result = await reviewer.review(
                OfficialAccountReviewerRequest(
                    contract=contract,
                    source=source,
                    article=article.article,
                    max_output_tokens=claimed.identity.reviewer_max_output_tokens,
                )
            )
            if result.provider != reviewer.provider or result.model != reviewer.model:
                raise ValueError("Reviewer provider identity changed")
            validate_review_verdict_binding(contract, result.verdict)
            result_bytes = len(result.verdict.model_dump_json().encode("utf-8"))
            return GovernedCapabilityResult(
                value=result,
                result_bytes=result_bytes,
                input_tokens=result.prompt_tokens,
                output_tokens=(
                    None
                    if result.completion_tokens is None or result.reasoning_tokens is None
                    else result.completion_tokens + result.reasoning_tokens
                ),
                model_turns=1,
            )

        request = CapabilityRequest(
            identity=reviewer_identity,
            role=ExecutionRole.REVIEWER,
            capability_name=_REVIEWER_CAPABILITY,
            target_task_id=reviewer_identity.task_id,
            parent_event_id=start,
            argument_bytes=reviewer_argument_bytes(contract),
            artifact_ids=(
                artifacts.article_artifact_id,
                artifacts.source_artifact_id,
                artifacts.brand_artifact_id,
            ),
            expected_input_tokens=80_000,
            expected_output_tokens=claimed.identity.reviewer_max_output_tokens,
            model_turns=1,
            tool_calls=1,
            expected_artifact_bytes=256 * 1024,
        )
        try:
            governed = await self._gateway(claimed).invoke(
                request,
                handler,
                before_handler=before_handler,
            )
        except GovernanceDeniedError:
            if current_intent.status == "calling":
                await self._review_repository.mark_result_unknown(
                    intent=current_intent,
                    error_code="review_result_unknown",
                )
            failure = await self._complete_child(
                reviewer_identity,
                start,
                _REVIEWER_CAPABILITY,
                succeeded=False,
            )
            await self._fail_root(root, failure)
            return None
        if governed.execution is None:
            raise RuntimeError("governed Reviewer completion binding is missing")
        result = governed.value
        review_bytes = canonical_json(result.verdict).encode("utf-8")
        try:
            artifact_event, review_artifact = await self._service.produce_artifact(
                identity=reviewer_identity,
                parent_event_id=governed.execution.result_event_id,
                kind=ArtifactKind.REPORT,
                media_type="application/json",
                byte_size=len(review_bytes),
                sha256=sha256(review_bytes).hexdigest(),
                artifact_id=uuid5(_NAMESPACE, f"{reviewer_identity.run_id}:review-result"),
            )
            record = await self._review_repository.persist_record(
                intent=current_intent,
                result=result,
                execution_artifact_id=review_artifact.artifact_id,
                execution_event_id=artifact_event.event_id,
            )
        except Exception:
            existing = await self._review_repository.get_record(current_intent.id)
            if existing is not None:
                await self._recover_terminal(intent=current_intent, root=root, record=existing)
                return existing
            unknown = await self._review_repository.mark_result_unknown(
                intent=current_intent,
                error_code="review_result_unknown",
            )
            await self._recover_terminal(intent=unknown, root=root, record=None)
            return None
        try:
            finish = await self._complete_child(
                reviewer_identity,
                artifact_event.event_id,
                _REVIEWER_CAPABILITY,
                succeeded=True,
            )
            await self._finish_root(root, finish)
        except Exception:
            await self._recover_terminal(intent=current_intent, root=root, record=record)
        return record

    async def close_without_review(
        self,
        *,
        claimed: ClaimedOfficialAccountRun,
        source: OfficialAccountSourceSnapshot,
    ) -> None:
        root, _ = await self._ensure_run(claimed, source)
        timeline = await self._execution_repository.list_timeline(run_id=root.run_id, limit=200)
        await self._fail_root(root, timeline[-1].event_id)

    async def _recover_terminal(
        self,
        *,
        intent: StoredReviewIntent,
        root: ExecutionIdentity,
        record: StoredReviewRecord | None,
    ) -> None:
        binding = intent.execution_binding
        if binding is None:
            raise RuntimeError("terminal official-account review has no execution binding")
        reviewer = ExecutionIdentity(
            run_id=binding.execution_run_id,
            task_id=binding.task_id,
            agent_id=binding.reviewer_agent_id,
        )
        reservation = await self._execution_repository.get_budget_reservation(
            identity=reviewer,
            reservation_id=binding.reservation_id,
        )
        if reservation is None:
            raise RuntimeError("official-account review reservation is unavailable")
        if not reservation.reconciled:
            await self._execution_repository.reconcile_budget(
                identity=reviewer,
                reservation_id=binding.reservation_id,
                actual=BudgetUsage(
                    model_turns=1,
                    input_tokens=None,
                    output_tokens=None,
                    tool_calls=1,
                ),
            )
        succeeded = record is not None
        parent_event_id = (
            record.execution_event_id if record is not None else binding.request_event_id
        )
        terminal = await self._complete_child(
            reviewer,
            parent_event_id,
            _REVIEWER_CAPABILITY,
            succeeded=succeeded,
        )
        if succeeded:
            await self._finish_root(root, terminal)
        else:
            await self._fail_root(root, terminal)

    async def _ensure_run(
        self,
        claimed: ClaimedOfficialAccountRun,
        source: OfficialAccountSourceSnapshot,
    ) -> tuple[ExecutionIdentity, UUID]:
        run_id, task_id = review_execution_scope(claimed.run_id)
        allocation, root = await self._service.create_run(
            task_id=task_id,
            root_agent_id=_ROOT_AGENT,
            role=ExecutionRole.ORCHESTRATOR,
            limits=reviewer_root_limits(
                writer_timeout_ms=claimed.identity.reviewer_writer_timeout_ms,
                reviewer_timeout_ms=claimed.identity.reviewer_timeout_ms,
                writer_max_output_tokens=(claimed.identity.reviewer_writer_max_output_tokens),
                reviewer_max_output_tokens=claimed.identity.reviewer_max_output_tokens,
            ),
            request_fingerprint=fingerprint(
                "official-account-review-governance-v1",
                claimed.run_id,
                source.source_fingerprint,
                claimed.identity.provider,
                claimed.identity.model,
                claimed.identity.reviewer_mode,
                claimed.identity.reviewer_version,
                claimed.identity.reviewer_prompt_version,
                claimed.identity.reviewer_request_schema_version,
                claimed.identity.reviewer_verdict_schema_version,
                claimed.identity.reviewer_rubric_version,
                claimed.identity.reviewer_review_policy_version,
                claimed.identity.reviewer_repair_policy_version,
                claimed.identity.reviewer_budget_policy_version,
                claimed.identity.reviewer_provider,
                claimed.identity.reviewer_model,
                claimed.identity.reviewer_writer_timeout_ms,
                claimed.identity.reviewer_timeout_ms,
                claimed.identity.reviewer_writer_max_output_tokens,
                claimed.identity.reviewer_max_output_tokens,
            ),
            run_id=run_id,
        )
        return allocation.identity, root.event_id

    @staticmethod
    def _validate_frozen_budget_identity(claimed: ClaimedOfficialAccountRun) -> None:
        identity = claimed.identity
        if identity.reviewer_budget_policy_version != "official-account-review-budget-v1":
            raise RuntimeError("official-account Reviewer frozen budget policy changed")
        if (
            not 1_000 <= identity.reviewer_writer_timeout_ms <= 420_000
            or not 1_000 <= identity.reviewer_timeout_ms <= 420_000
            or not 2_048 <= identity.reviewer_writer_max_output_tokens <= 16_384
            or not 512 <= identity.reviewer_max_output_tokens <= 4_096
        ):
            raise RuntimeError("official-account Reviewer frozen budget limits are invalid")

    async def _ensure_child(
        self,
        *,
        parent: ExecutionIdentity,
        parent_event_id: UUID,
        agent_id: str,
        role: ExecutionRole,
        limits: BudgetLimits,
        target: str,
    ) -> tuple[ExecutionIdentity, UUID]:
        identity = ExecutionIdentity(parent.run_id, parent.task_id, agent_id)
        try:
            existing = await self._execution_repository.get_allocation(identity)
        except GovernanceDeniedError:
            existing = await self._service.allocate_child(
                parent=parent,
                child_agent_id=agent_id,
                role=role,
                limits=limits,
                parent_event_id=parent_event_id,
            )
        if existing.role is not role or existing.limits != limits:
            raise RuntimeError("governed official-account child identity changed")
        timeline = await self._execution_repository.list_timeline(run_id=parent.run_id, limit=200)
        start = next(
            (
                event
                for event in timeline
                if event.identity == identity
                and event.kind is ExecutionEventKind.NODE_STARTED
                and event.target_name == target
            ),
            None,
        )
        if start is None:
            start = await self._service.append_event(
                SafeEventDraft(
                    identity=identity,
                    event_id=uuid5(_NAMESPACE, f"{parent.run_id}:{agent_id}:start"),
                    kind=ExecutionEventKind.NODE_STARTED,
                    status=ExecutionEventStatus.STARTED,
                    parent_event_id=parent_event_id,
                    target_name=target,
                )
            )
        return identity, start.event_id

    async def _ensure_input_node(self, root: ExecutionIdentity, root_event: UUID) -> UUID:
        timeline = await self._execution_repository.list_timeline(run_id=root.run_id, limit=200)
        existing = next(
            (
                event
                for event in timeline
                if event.identity == root
                and event.kind is ExecutionEventKind.NODE_STARTED
                and event.target_name == _INPUT_NODE
            ),
            None,
        )
        if existing is not None:
            return existing.event_id
        event = await self._service.append_event(
            SafeEventDraft(
                identity=root,
                event_id=uuid5(_NAMESPACE, f"{root.run_id}:inputs:start"),
                kind=ExecutionEventKind.NODE_STARTED,
                status=ExecutionEventStatus.STARTED,
                parent_event_id=root_event,
                target_name=_INPUT_NODE,
            )
        )
        return event.event_id

    async def _ensure_input_artifacts(
        self,
        *,
        identity: ExecutionIdentity,
        parent_event_id: UUID,
        source: OfficialAccountSourceSnapshot,
        article: StoredOfficialAccountArticle,
    ) -> ReviewArtifactBinding:
        article_body = canonical_json(article.article).encode("utf-8")
        source_body = canonical_json(source).encode("utf-8")
        brand_body = canonical_json(source.brand_context).encode("utf-8")
        if sum(map(len, (article_body, source_body, brand_body))) > (_INPUT_ARTIFACT_BUDGET_BYTES):
            raise RuntimeError("official-account review input artifacts exceed the frozen budget")
        article_artifact = await self._ensure_artifact(
            identity=identity,
            parent_event_id=parent_event_id,
            label="article",
            kind=ArtifactKind.ARTICLE,
            body=article_body,
            sha256=exact_article_sha256(article.article),
        )
        source_artifact = await self._ensure_artifact(
            identity=identity,
            parent_event_id=parent_event_id,
            label="source",
            kind=ArtifactKind.OTHER,
            body=source_body,
            sha256=exact_source_sha256(source),
        )
        brand_artifact = await self._ensure_artifact(
            identity=identity,
            parent_event_id=parent_event_id,
            label="brand",
            kind=ArtifactKind.OTHER,
            body=brand_body,
            sha256=brand_context_sha256(source),
        )
        return ReviewArtifactBinding(
            article_artifact_id=article_artifact.artifact_id,
            source_artifact_id=source_artifact.artifact_id,
            brand_artifact_id=brand_artifact.artifact_id,
            article_sha256=article_artifact.sha256,
            source_sha256=source_artifact.sha256,
            brand_sha256=brand_artifact.sha256,
        )

    async def _ensure_artifact(
        self,
        *,
        identity: ExecutionIdentity,
        parent_event_id: UUID,
        label: str,
        kind: ArtifactKind,
        body: bytes,
        sha256: str,
    ) -> ArtifactMetadata:
        artifact_id = uuid5(_NAMESPACE, f"{identity.run_id}:input:{label}")
        existing = await self._execution_repository.get_artifact(
            identity=identity,
            artifact_id=artifact_id,
        )
        if existing is not None:
            if (
                existing.identity != identity
                or existing.kind is not kind
                or existing.media_type != "application/json"
                or existing.byte_size != len(body)
                or existing.sha256 != sha256
            ):
                raise RuntimeError("official-account review input artifact changed")
            return existing
        _, artifact = await self._service.produce_artifact(
            identity=identity,
            parent_event_id=parent_event_id,
            kind=kind,
            media_type="application/json",
            byte_size=len(body),
            sha256=sha256,
            artifact_id=artifact_id,
        )
        return artifact

    async def _complete_child(
        self,
        identity: ExecutionIdentity,
        parent_event_id: UUID,
        target: str,
        *,
        succeeded: bool,
    ) -> UUID:
        allocation = await self._execution_repository.get_allocation(identity)
        kind = ExecutionEventKind.NODE_FINISHED if succeeded else ExecutionEventKind.NODE_FAILED
        timeline = await self._execution_repository.list_timeline(run_id=identity.run_id, limit=200)
        event = next(
            (
                candidate
                for candidate in reversed(timeline)
                if candidate.identity == identity
                and candidate.kind is kind
                and candidate.target_name == target
            ),
            None,
        )
        expected_status = ExecutionRunStatus.SUCCEEDED if succeeded else ExecutionRunStatus.FAILED
        if event is None:
            if allocation.status is not ExecutionRunStatus.RUNNING:
                raise RuntimeError("terminal Reviewer allocation has no terminal event")
            event = await self._service.append_event(
                SafeEventDraft(
                    identity=identity,
                    event_id=uuid5(
                        _NAMESPACE,
                        f"{identity.run_id}:{identity.agent_id}:"
                        f"{'finish' if succeeded else 'fail'}",
                    ),
                    kind=kind,
                    status=(
                        ExecutionEventStatus.SUCCEEDED if succeeded else ExecutionEventStatus.FAILED
                    ),
                    parent_event_id=parent_event_id,
                    target_name=target,
                    error_code=None if succeeded else "capability_failed",
                )
            )
        if allocation.status is ExecutionRunStatus.RUNNING:
            await self._execution_repository.complete_allocation(
                identity=identity,
                status=expected_status,
            )
        elif allocation.status is not expected_status:
            raise RuntimeError("Reviewer allocation terminal status changed")
        return event.event_id

    async def _finish_root(self, root: ExecutionIdentity, parent_event_id: UUID) -> None:
        allocation = await self._execution_repository.get_allocation(root)
        if allocation.status is ExecutionRunStatus.SUCCEEDED:
            return
        if allocation.status is not ExecutionRunStatus.RUNNING:
            raise RuntimeError("Reviewer root terminal status changed")
        timeline = await self._execution_repository.list_timeline(run_id=root.run_id, limit=200)
        if not any(event.kind is ExecutionEventKind.RUN_FINISHED for event in timeline):
            await self._service.append_event(
                SafeEventDraft(
                    identity=root,
                    event_id=uuid5(_NAMESPACE, f"{root.run_id}:finish"),
                    kind=ExecutionEventKind.RUN_FINISHED,
                    status=ExecutionEventStatus.SUCCEEDED,
                    parent_event_id=parent_event_id,
                    target_name="official.review",
                )
            )
        await self._execution_repository.complete_allocation(
            identity=root,
            status=ExecutionRunStatus.SUCCEEDED,
        )

    async def _fail_root(self, root: ExecutionIdentity, parent_event_id: UUID) -> None:
        allocation = await self._execution_repository.get_allocation(root)
        if allocation.status is ExecutionRunStatus.FAILED:
            return
        if allocation.status is not ExecutionRunStatus.RUNNING:
            raise RuntimeError("Reviewer root terminal status changed")
        timeline = await self._execution_repository.list_timeline(run_id=root.run_id, limit=200)
        parent = next((event for event in timeline if event.event_id == parent_event_id), None)
        if parent is None:
            raise RuntimeError("Reviewer root failure parent is unavailable")
        if parent.kind not in {
            ExecutionEventKind.NODE_FAILED,
            ExecutionEventKind.BUDGET_DENIED,
            ExecutionEventKind.PERMISSION_DENIED,
        }:
            bridge_start_id = uuid5(_NAMESPACE, f"{root.run_id}:failure:start")
            bridge_start = next(
                (event for event in timeline if event.event_id == bridge_start_id),
                None,
            )
            if bridge_start is None:
                bridge_start = await self._service.append_event(
                    SafeEventDraft(
                        identity=root,
                        event_id=bridge_start_id,
                        kind=ExecutionEventKind.NODE_STARTED,
                        status=ExecutionEventStatus.STARTED,
                        parent_event_id=parent.event_id,
                        target_name="official.review.failure",
                    )
                )
            bridge_failure_id = uuid5(_NAMESPACE, f"{root.run_id}:failure:finish")
            bridge_failure = next(
                (event for event in timeline if event.event_id == bridge_failure_id),
                None,
            )
            if bridge_failure is None:
                bridge_failure = await self._service.append_event(
                    SafeEventDraft(
                        identity=root,
                        event_id=bridge_failure_id,
                        kind=ExecutionEventKind.NODE_FAILED,
                        status=ExecutionEventStatus.FAILED,
                        parent_event_id=bridge_start.event_id,
                        target_name="official.review.failure",
                        error_code="review_unavailable",
                    )
                )
            parent_event_id = bridge_failure.event_id
        if not any(event.kind is ExecutionEventKind.RUN_FAILED for event in timeline):
            await self._service.append_event(
                SafeEventDraft(
                    identity=root,
                    event_id=uuid5(_NAMESPACE, f"{root.run_id}:failed"),
                    kind=ExecutionEventKind.RUN_FAILED,
                    status=ExecutionEventStatus.FAILED,
                    parent_event_id=parent_event_id,
                    target_name="official.review",
                    error_code="review_unavailable",
                )
            )
        await self._execution_repository.complete_allocation(
            identity=root,
            status=ExecutionRunStatus.FAILED,
        )
