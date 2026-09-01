from __future__ import annotations

# ruff: noqa: RUF001 -- Chinese punctuation is intentional in bounded selection explanations.
import re
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from typing import Literal, cast
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.ports.image_validation import (
    IMAGE_QUALITY_AUDIT_PROMPT_VERSION,
    IMAGE_QUALITY_AUDITOR_VERSION,
)
from app.application.ports.official_account_local import (
    ClaimedOfficialAccountRun,
    OfficialAccountAuditResult,
    OfficialAccountDraftResult,
    OfficialAccountGeneratedVisualEvalResult,
    OfficialAccountGeneratedVisualPlan,
    OfficialAccountGeneratedVisualResult,
    OfficialAccountGenerationResult,
    OfficialAccountMediaResult,
    OfficialAccountSourceMedia,
    OfficialAccountVersionIdentity,
    StoredOfficialAccountArticle,
    StoredOfficialAccountGeneratedVisual,
    StoredOfficialAccountGeneratedVisualEval,
    StoredOfficialAccountManualReview,
    StoredOfficialAccountRender,
    generated_visual_eval_record_fingerprint,
)
from app.application.services.official_account_local import (
    generated_visual_eval_request_fingerprint,
    manual_review_request_fingerprint,
    run_request_fingerprint,
)
from app.core.errors import ConflictError, NotFoundError, OfficialAccountLeaseLostError
from app.domain.image_provider_input import IMAGE_REFERENCE_INPUT_V2
from app.domain.image_quality_eval import (
    IMAGE_EVAL_DECISION_POLICY_VERSION,
    IMAGE_EVAL_RUBRIC_VERSION,
    ImageEvalDecisionKind,
    ImageEvalIssueCode,
    ImageEvalObservation,
    active_image_eval_rubric,
    decide_image_eval_batch,
)
from app.domain.official_account_local import (
    OFFICIAL_ACCOUNT_FIXTURE_ID,
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_OUTPUT_PROFILE_VERSION,
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_V1_VERSION,
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_V2_VERSION,
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_VERSION,
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_V1_VERSION,
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_V2_VERSION,
    OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_VERSION,
    OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V3_VERSION,
    OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V4_VERSION,
    OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V6_VERSION,
    OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V7_VERSION,
    OFFICIAL_ACCOUNT_LOCAL_ADAPTER_VERSION,
    OFFICIAL_ACCOUNT_MEDIA_PLAN_V1_VERSION,
    OFFICIAL_ACCOUNT_MEDIA_PLAN_V2_VERSION,
    OFFICIAL_ACCOUNT_MEDIA_PLAN_V4_VERSION,
    OFFICIAL_ACCOUNT_MEDIA_PLAN_VERSION,
    ArticlePackage,
    ArticleValidationIssue,
    OfficialAccountAuditVerdict,
    OfficialAccountBrandContext,
    OfficialAccountEvidence,
    OfficialAccountSourceSnapshot,
    RenderedOfficialAccountHtml,
    article_version_bundle_kind,
    fingerprint,
)
from app.infrastructure.db.models import (
    ImageArtifactModel,
    MaterialPackageModel,
    MaterialPackageSourceImageModel,
    OfficialAccountArticleAttemptModel,
    OfficialAccountArticleContextImageModel,
    OfficialAccountArticleRunModel,
    OfficialAccountArticleVersionModel,
    OfficialAccountGeneratedVisualEvalModel,
    OfficialAccountGeneratedVisualModel,
    OfficialAccountLocalDraftBodyMediaModel,
    OfficialAccountLocalDraftModel,
    OfficialAccountLocalMediaModel,
    OfficialAccountManualReviewModel,
    OfficialAccountRenderVersionModel,
    SourceArticleImageModel,
    SourceSnapshotModel,
)
from app.infrastructure.official_account_local import (
    FIXTURE_BODY_ALT_TEXTS,
    FIXTURE_BODY_CAPTIONS,
    FIXTURE_BODY_IMAGE_BYTE_SIZES,
    FIXTURE_BODY_IMAGE_LABELS,
    FIXTURE_BODY_IMAGE_SHA256S,
    FIXTURE_BODY_PUBLICATION_BYTE_SIZES,
    FIXTURE_BODY_PUBLICATION_MEDIA_TYPE,
    FIXTURE_BODY_PUBLICATION_SHA256S,
    FIXTURE_BODY_SEMANTIC_TAGS,
    FIXTURE_IMAGE_BYTE_SIZE,
    FIXTURE_IMAGE_MEDIA_TYPE,
    FIXTURE_IMAGE_SHA256,
    fixture_source_snapshot,
)

_SAFE_ERROR = re.compile(r"^[a-z][a-z0-9_.-]{0,79}$")
_TERMINAL_STATUSES = frozenset({"review_required", "ready", "failed", "result_unknown"})
_ADAPTER_V7_ATTEMPT_STRIDE = 100
_ADAPTER_V7_CONTEXT_OFFSET = 20
_ADAPTER_V7_FAILURE_OFFSET = 90
_ARTICLE_ARTIFACT_VERSION_BY_FAMILY: dict[str, int] = {
    "v1": 1,
    "v2": 1,
    "v3": 1,
    "v4": 1,
    "v5": 2,
    "v6": 3,
    "v7": 4,
    "v8": 5,
    "v9": 6,
    "v10": 6,
}


def _adapter_v7_staging_attempt_ordinal(
    *,
    attempt_number: int,
    role: Literal["body", "context", "failure"],
    ordinal: int = 0,
) -> int:
    if attempt_number < 1:
        raise ValueError("official-account attempt number must be positive")
    base = attempt_number * _ADAPTER_V7_ATTEMPT_STRIDE
    if role == "body" and 0 <= ordinal <= 4:
        return base + ordinal
    if role == "context" and 0 <= ordinal <= 1:
        return base + _ADAPTER_V7_CONTEXT_OFFSET + ordinal
    if role == "failure" and ordinal == 0:
        return base + _ADAPTER_V7_FAILURE_OFFSET
    raise ValueError("official-account adapter v7 attempt ordinal is invalid")


def _article_artifact_version(article: ArticlePackage) -> int:
    family = article_version_bundle_kind(article.versions)
    if family is None:
        raise ValueError("official-account article version bundle is unsupported")
    return _ARTICLE_ARTIFACT_VERSION_BY_FAMILY[family]


class PostgresOfficialAccountRepository:
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def enqueue_fixture(
        self,
        *,
        identity: OfficialAccountVersionIdentity,
    ) -> tuple[OfficialAccountArticleRunModel, bool]:
        source = fixture_source_snapshot(
            multi_image=identity.media_plan_version
            in {
                OFFICIAL_ACCOUNT_MEDIA_PLAN_V1_VERSION,
                OFFICIAL_ACCOUNT_MEDIA_PLAN_V2_VERSION,
                OFFICIAL_ACCOUNT_MEDIA_PLAN_VERSION,
                OFFICIAL_ACCOUNT_MEDIA_PLAN_V4_VERSION,
            },
            semantic_media=identity.media_plan_version
            in {
                OFFICIAL_ACCOUNT_MEDIA_PLAN_V2_VERSION,
                OFFICIAL_ACCOUNT_MEDIA_PLAN_VERSION,
                OFFICIAL_ACCOUNT_MEDIA_PLAN_V4_VERSION,
            },
        )
        return await self._enqueue(
            material_package_id=None,
            fixture_id=OFFICIAL_ACCOUNT_FIXTURE_ID,
            generation_mode="fixture",
            source=source,
            identity=identity,
        )

    async def enqueue_material_package(
        self,
        *,
        material_package_id: UUID,
        identity: OfficialAccountVersionIdentity,
    ) -> tuple[OfficialAccountArticleRunModel, bool]:
        async with self._session_factory() as session:
            package = await session.get(MaterialPackageModel, material_package_id)
            if package is None:
                raise NotFoundError("material package")
            image = await session.get(ImageArtifactModel, package.image_artifact_id)
            if image is None:
                raise ConflictError("material package image is unavailable")
            source = material_package_source_snapshot(package, image)
        return await self._enqueue(
            material_package_id=material_package_id,
            fixture_id=None,
            generation_mode="live",
            source=source,
            identity=identity,
        )

    async def _enqueue(
        self,
        *,
        material_package_id: UUID | None,
        fixture_id: str | None,
        generation_mode: Literal["fixture", "live"],
        source: OfficialAccountSourceSnapshot,
        identity: OfficialAccountVersionIdentity,
    ) -> tuple[OfficialAccountArticleRunModel, bool]:
        request_fingerprint = run_request_fingerprint(
            source_fingerprint=source.source_fingerprint,
            generation_mode=generation_mode,
            identity=identity,
        )
        run_id = uuid4()
        statement = (
            insert(OfficialAccountArticleRunModel)
            .values(
                id=run_id,
                material_package_id=material_package_id,
                fixture_id=fixture_id,
                generation_mode=generation_mode,
                source_fingerprint=source.source_fingerprint,
                request_fingerprint=request_fingerprint,
                provider=identity.provider,
                model=identity.model,
                version_bundle=_identity_payload(identity),
                status="queued",
                current_stage="queued",
                error_retryable=False,
            )
            .on_conflict_do_nothing(constraint="uq_official_account_article_runs_request")
            .returning(OfficialAccountArticleRunModel.id)
        )
        async with self._session_factory() as session:
            inserted_id = await session.scalar(statement)
            await session.commit()
            stored_id = inserted_id
            created = inserted_id is not None
            if stored_id is None:
                stored_id = await session.scalar(
                    select(OfficialAccountArticleRunModel.id).where(
                        OfficialAccountArticleRunModel.request_fingerprint == request_fingerprint
                    )
                )
            if stored_id is None:
                raise RuntimeError("official-account idempotent enqueue did not resolve a run")
            run = await session.get(OfficialAccountArticleRunModel, stored_id)
            if run is None:
                raise RuntimeError("official-account enqueued run is unavailable")
            return run, created

    async def list_runs(self, *, limit: int) -> tuple[OfficialAccountArticleRunModel, ...]:
        async with self._session_factory() as session:
            return tuple(
                (
                    await session.scalars(
                        select(OfficialAccountArticleRunModel)
                        .order_by(OfficialAccountArticleRunModel.created_at.desc())
                        .limit(limit)
                    )
                ).all()
            )

    async def get_run(self, run_id: UUID) -> OfficialAccountArticleRunModel:
        async with self._session_factory() as session:
            run = await session.get(OfficialAccountArticleRunModel, run_id)
            if run is None:
                raise NotFoundError("official-account article run")
            return run

    async def get_manual_review(
        self,
        run_id: UUID,
    ) -> StoredOfficialAccountManualReview | None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(OfficialAccountManualReviewModel).where(
                    OfficialAccountManualReviewModel.run_id == run_id
                )
            )
            return _stored_manual_review(row) if row is not None else None

    async def get_generated_visual(
        self,
        *,
        run_id: UUID,
        ordinal: int,
    ) -> StoredOfficialAccountGeneratedVisual | None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(OfficialAccountGeneratedVisualModel).where(
                    OfficialAccountGeneratedVisualModel.run_id == run_id,
                    OfficialAccountGeneratedVisualModel.ordinal == ordinal,
                )
            )
            return _stored_generated_visual(row) if row is not None else None

    async def list_generated_visuals(
        self,
        *,
        run_id: UUID,
    ) -> tuple[StoredOfficialAccountGeneratedVisual, ...]:
        async with self._session_factory() as session:
            rows = (
                await session.scalars(
                    select(OfficialAccountGeneratedVisualModel)
                    .where(OfficialAccountGeneratedVisualModel.run_id == run_id)
                    .order_by(OfficialAccountGeneratedVisualModel.ordinal)
                )
            ).all()
            return tuple(_stored_generated_visual(row) for row in rows)

    async def list_generated_visual_evals(
        self,
        *,
        run_id: UUID,
    ) -> tuple[StoredOfficialAccountGeneratedVisualEval, ...]:
        async with self._session_factory() as session:
            rows = (
                await session.scalars(
                    select(OfficialAccountGeneratedVisualEvalModel)
                    .where(OfficialAccountGeneratedVisualEvalModel.run_id == run_id)
                    .order_by(OfficialAccountGeneratedVisualEvalModel.generated_visual_id)
                )
            ).all()
            return tuple(_stored_generated_visual_eval(row) for row in rows)

    async def create_generated_visual_intent(
        self,
        *,
        claimed: ClaimedOfficialAccountRun,
        plan: OfficialAccountGeneratedVisualPlan,
    ) -> StoredOfficialAccountGeneratedVisual | None:
        _validate_generated_visual_plan(plan)
        async with self._session_factory() as session:
            run = await _locked_fenced_run(session, claimed)
            if run is None:
                return None
            if (
                plan.run_id != run.id
                or plan.article_version_id != run.active_article_version_id
                or plan.render_version_id != run.active_render_version_id
            ):
                raise RuntimeError("generated visual plan does not match the active run artifacts")
            existing = await session.scalar(
                select(OfficialAccountGeneratedVisualModel).where(
                    OfficialAccountGeneratedVisualModel.render_version_id == plan.render_version_id,
                    OfficialAccountGeneratedVisualModel.ordinal == plan.ordinal,
                )
            )
            if existing is not None:
                _assert_generated_visual_plan(existing, plan)
                return _stored_generated_visual(existing)
            row = OfficialAccountGeneratedVisualModel(
                id=uuid4(),
                run_id=plan.run_id,
                article_version_id=plan.article_version_id,
                render_version_id=plan.render_version_id,
                ordinal=plan.ordinal,
                section_index=plan.section_index,
                block_index=plan.block_index,
                block_kind=plan.block_kind,
                block_fingerprint=plan.block_fingerprint,
                reference_asset_ref=plan.reference_asset_ref,
                reference_catalog_version=plan.reference_catalog_version,
                reference_source_checksum=plan.reference_source_checksum,
                reference_publication_checksum=plan.reference_publication_checksum,
                reference_input_version=plan.reference_input_version,
                reference_input_checksum=plan.reference_input_checksum,
                selection_method=plan.selection_method,
                similarity_band=plan.similarity_band,
                request_fingerprint=plan.request_fingerprint,
                plan_version=plan.plan_version,
                prompt_version=plan.prompt_version,
                output_profile_version=plan.output_profile_version,
                provider=plan.provider,
                model=plan.model,
                status="generating",
                media_type=None,
                byte_size=None,
                sha256=None,
                width=None,
                height=None,
                error_code=None,
                completed_at=None,
            )
            session.add(row)
            run.current_stage = "generating_body_visuals"
            run.updated_at = datetime.now(UTC)
            await session.commit()
            return _stored_generated_visual(row)

    async def persist_generated_visual(
        self,
        *,
        claimed: ClaimedOfficialAccountRun,
        plan: OfficialAccountGeneratedVisualPlan,
        result: OfficialAccountGeneratedVisualResult,
        eval_result: OfficialAccountGeneratedVisualEvalResult | None = None,
    ) -> StoredOfficialAccountGeneratedVisual | None:
        _validate_generated_visual_plan(plan)
        if eval_result is not None and eval_result.publication_sha256 != result.sha256:
            raise ValueError("generated visual eval is not bound to the final result hash")
        if eval_result is not None and (
            eval_result.evaluator_version != IMAGE_QUALITY_AUDITOR_VERSION
            or eval_result.audit_prompt_version != IMAGE_QUALITY_AUDIT_PROMPT_VERSION
            or eval_result.rubric_version != IMAGE_EVAL_RUBRIC_VERSION
            or eval_result.decision_policy_version != IMAGE_EVAL_DECISION_POLICY_VERSION
        ):
            raise ValueError("generated visual eval versions are not current")
        async with self._session_factory() as session:
            run = await _locked_fenced_run(session, claimed)
            if run is None:
                return None
            row = await session.scalar(
                select(OfficialAccountGeneratedVisualModel)
                .where(
                    OfficialAccountGeneratedVisualModel.render_version_id == plan.render_version_id,
                    OfficialAccountGeneratedVisualModel.ordinal == plan.ordinal,
                )
                .with_for_update()
            )
            if row is None:
                raise RuntimeError("generated visual intent is missing")
            _assert_generated_visual_plan(row, plan)
            if eval_result is not None:
                if plan.reference_input_checksum is None:
                    raise ValueError("generated visual eval requires a normalized reference hash")
                expected_eval_fingerprint = generated_visual_eval_request_fingerprint(
                    generated_visual_id=row.id,
                    plan_request_fingerprint=plan.request_fingerprint,
                    publication_sha256=result.sha256,
                    reference_input_checksum=plan.reference_input_checksum,
                )
                if eval_result.request_fingerprint != expected_eval_fingerprint:
                    raise ValueError("generated visual eval request fingerprint changed")
            if row.status == "ready":
                return _stored_generated_visual(row)
            if row.status != "generating":
                raise RuntimeError("generated visual cannot accept a late result")
            row.status = "ready"
            row.media_type = result.media_type
            row.byte_size = result.byte_size
            row.sha256 = result.sha256
            row.width = result.width
            row.height = result.height
            row.error_code = None
            row.completed_at = datetime.now(UTC)
            if eval_result is not None:
                # No ORM relationship is allowed for this immutable child. Flush the parent's
                # final SHA first so PostgreSQL can enforce the composite visual/run/SHA fence
                # when the child insert follows in the same transaction.
                await session.flush()
                expected_subject_ref = f"generated-visual:{row.id}"
                if any(
                    observation.subject_ref != expected_subject_ref
                    for observation in eval_result.observations
                ):
                    raise ValueError("generated visual eval subject identity changed")
                record_fingerprint = generated_visual_eval_record_fingerprint(
                    generated_visual_id=row.id,
                    run_id=row.run_id,
                    result=eval_result,
                )
                session.add(
                    OfficialAccountGeneratedVisualEvalModel(
                        id=uuid4(),
                        generated_visual_id=row.id,
                        run_id=row.run_id,
                        publication_sha256=eval_result.publication_sha256,
                        decision=eval_result.decision.decision.value,
                        hard_gate_passed=eval_result.decision.hard_gate_passed,
                        manual_review_required=(eval_result.decision.manual_review_required),
                        evaluator_version=eval_result.evaluator_version,
                        audit_prompt_version=eval_result.audit_prompt_version,
                        rubric_version=eval_result.rubric_version,
                        decision_policy_version=eval_result.decision_policy_version,
                        request_fingerprint=eval_result.request_fingerprint,
                        record_fingerprint=record_fingerprint,
                        provider=eval_result.provider,
                        model=eval_result.model,
                        issue_codes=list(eval_result.issue_codes),
                        observation_snapshot=[
                            observation.model_dump(mode="json")
                            for observation in eval_result.observations
                        ],
                        completed_at=row.completed_at,
                    )
                )
            run.current_stage = "staging_body_media"
            run.updated_at = row.completed_at
            session.add(
                OfficialAccountArticleAttemptModel(
                    id=uuid4(),
                    run_id=run.id,
                    article_version_id=plan.article_version_id,
                    stage="generating_body_visuals",
                    capability="visual_generation",
                    ordinal=claimed.attempt_number * 10 + plan.ordinal,
                    status="succeeded",
                    request_fingerprint=plan.request_fingerprint,
                    provider=plan.provider,
                    model=plan.model,
                    provider_request_id=None,
                    prompt_tokens=0,
                    completion_tokens=0,
                    reasoning_tokens=0,
                    latency_ms=0,
                    validation_corrections=0,
                    error_code=None,
                    safe_metadata={
                        "ordinal": plan.ordinal,
                        "section_index": plan.section_index,
                        "selection_method": plan.selection_method,
                        "media_type": result.media_type,
                        "byte_size": result.byte_size,
                        **(
                            {"image_eval_decision": eval_result.decision.decision.value}
                            if eval_result is not None
                            else {}
                        ),
                    },
                    completed_at=row.completed_at,
                )
            )
            await session.commit()
            return _stored_generated_visual(row)

    async def fail_generated_visual(
        self,
        *,
        claimed: ClaimedOfficialAccountRun,
        plan: OfficialAccountGeneratedVisualPlan,
        error_code: str,
        result_unknown: bool = False,
    ) -> bool:
        _validate_generated_visual_plan(plan)
        safe_error = _safe_error(error_code)
        async with self._session_factory() as session:
            run = await _locked_fenced_run(session, claimed)
            if run is None:
                return False
            row = await session.scalar(
                select(OfficialAccountGeneratedVisualModel)
                .where(
                    OfficialAccountGeneratedVisualModel.render_version_id == plan.render_version_id,
                    OfficialAccountGeneratedVisualModel.ordinal == plan.ordinal,
                )
                .with_for_update()
            )
            if row is None:
                return False
            _assert_generated_visual_plan(row, plan)
            if row.status != "generating":
                return row.status in {"failed", "result_unknown"}
            now = datetime.now(UTC)
            row.status = "result_unknown" if result_unknown else "failed"
            row.error_code = safe_error
            row.completed_at = now
            session.add(
                OfficialAccountArticleAttemptModel(
                    id=uuid4(),
                    run_id=run.id,
                    article_version_id=plan.article_version_id,
                    stage="generating_body_visuals",
                    capability="visual_generation",
                    ordinal=claimed.attempt_number * 10 + plan.ordinal,
                    status="failed",
                    request_fingerprint=plan.request_fingerprint,
                    provider=plan.provider,
                    model=plan.model,
                    provider_request_id=None,
                    prompt_tokens=0,
                    completion_tokens=0,
                    reasoning_tokens=0,
                    latency_ms=0,
                    validation_corrections=0,
                    error_code=safe_error,
                    safe_metadata={
                        "ordinal": plan.ordinal,
                        "section_index": plan.section_index,
                        "selection_method": plan.selection_method,
                        "result_unknown": result_unknown,
                    },
                    completed_at=now,
                )
            )
            await session.commit()
            return True

    async def record_manual_review(
        self,
        *,
        run_id: UUID,
        decision: Literal["approved", "rejected"],
        reviewer_label: str,
        note: str | None,
    ) -> tuple[StoredOfficialAccountManualReview, bool]:
        request_fingerprint = manual_review_request_fingerprint(
            run_id=run_id,
            decision=decision,
            reviewer_label=reviewer_label,
            note=note,
        )
        async with self._session_factory() as session:
            run = await session.scalar(
                select(OfficialAccountArticleRunModel)
                .where(OfficialAccountArticleRunModel.id == run_id)
                .with_for_update()
            )
            if run is None:
                raise NotFoundError("official-account article run")
            if run.status != "ready" or run.active_draft_id is None:
                raise ConflictError("only a ready local draft can receive manual review")
            draft = await session.get(OfficialAccountLocalDraftModel, run.active_draft_id)
            if (
                draft is None
                or draft.run_id != run.id
                or draft.state != "ready"
                or not draft.simulation
            ):
                raise ConflictError("ready local draft lineage is incomplete")
            existing = await session.scalar(
                select(OfficialAccountManualReviewModel).where(
                    OfficialAccountManualReviewModel.run_id == run.id
                )
            )
            if existing is not None:
                if existing.request_fingerprint != request_fingerprint:
                    raise ConflictError("manual review is final and cannot be changed")
                return _stored_manual_review(existing), False
            row = OfficialAccountManualReviewModel(
                id=uuid4(),
                run_id=run.id,
                decision=decision,
                reviewer_label=reviewer_label,
                note=note,
                request_fingerprint=request_fingerprint,
            )
            session.add(row)
            await session.flush()
            await session.refresh(row)
            await session.commit()
            return _stored_manual_review(row), True

    async def get_article(self, run_id: UUID) -> StoredOfficialAccountArticle | None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(OfficialAccountArticleVersionModel).where(
                    OfficialAccountArticleVersionModel.run_id == run_id
                )
            )
            return _stored_article(row) if row is not None else None

    async def get_render(self, run_id: UUID) -> StoredOfficialAccountRender | None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(OfficialAccountRenderVersionModel).where(
                    OfficialAccountRenderVersionModel.run_id == run_id
                )
            )
            return _stored_render(row) if row is not None else None

    async def get_media(
        self,
        run_id: UUID,
        role: Literal["body", "cover", "context"],
        ordinal: int = 0,
    ) -> tuple[UUID, OfficialAccountMediaResult] | None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(OfficialAccountLocalMediaModel).where(
                    OfficialAccountLocalMediaModel.run_id == run_id,
                    OfficialAccountLocalMediaModel.role == role,
                    OfficialAccountLocalMediaModel.ordinal == ordinal,
                    OfficialAccountLocalMediaModel.status == "ready",
                )
            )
            return (row.id, _media_result(row)) if row is not None else None

    async def list_media(
        self,
        run_id: UUID,
        role: Literal["body", "cover", "context"] | None = None,
    ) -> tuple[tuple[UUID, OfficialAccountMediaResult], ...]:
        conditions = [
            OfficialAccountLocalMediaModel.run_id == run_id,
            OfficialAccountLocalMediaModel.status == "ready",
        ]
        if role is not None:
            conditions.append(OfficialAccountLocalMediaModel.role == role)
        async with self._session_factory() as session:
            rows = (
                await session.scalars(
                    select(OfficialAccountLocalMediaModel)
                    .where(*conditions)
                    .order_by(
                        OfficialAccountLocalMediaModel.role,
                        OfficialAccountLocalMediaModel.ordinal,
                    )
                )
            ).all()
            return tuple((row.id, _media_result(row)) for row in rows)

    async def get_draft(self, run_id: UUID) -> OfficialAccountLocalDraftModel | None:
        async with self._session_factory() as session:
            row = await session.scalar(
                select(OfficialAccountLocalDraftModel).where(
                    OfficialAccountLocalDraftModel.run_id == run_id
                )
            )
            return row

    async def claim(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
        max_attempts: int,
    ) -> ClaimedOfficialAccountRun | None:
        if max_attempts < 1:
            raise ValueError("official-account max attempts must be positive")
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            run = await session.scalar(
                select(OfficialAccountArticleRunModel)
                .where(
                    (
                        (OfficialAccountArticleRunModel.status == "queued")
                        & (OfficialAccountArticleRunModel.available_at <= now)
                    )
                    | (
                        (OfficialAccountArticleRunModel.status == "running")
                        & (OfficialAccountArticleRunModel.lease_expires_at < now)
                    ),
                )
                .order_by(
                    OfficialAccountArticleRunModel.available_at,
                    OfficialAccountArticleRunModel.created_at,
                )
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if run is None:
                return None
            token = uuid4()
            run.attempt_count += 1
            run.status = "running"
            run.current_stage = _resume_stage(run)
            run.lease_owner = worker_id[:200]
            run.lease_token = token
            run.lease_expires_at = now + timedelta(seconds=lease_seconds)
            run.heartbeat_at = now
            run.started_at = run.started_at or now
            run.completed_at = None
            run.updated_at = now
            run.error_code = None
            run.error_retryable = False
            identity = _identity_from_bundle(run.version_bundle)
            claimed = ClaimedOfficialAccountRun(
                run_id=run.id,
                attempt_number=run.attempt_count,
                lease_token=token,
                generation_mode=cast(Literal["fixture", "live"], run.generation_mode),
                identity=identity,
                current_stage=run.current_stage,
            )
            await session.commit()
            return claimed

    async def heartbeat(
        self,
        *,
        claimed: ClaimedOfficialAccountRun,
        lease_seconds: int,
    ) -> bool:
        async with self._session_factory() as session:
            run = await _locked_fenced_run(session, claimed)
            if run is None:
                return False
            now = datetime.now(UTC)
            run.heartbeat_at = now
            run.lease_expires_at = now + timedelta(seconds=lease_seconds)
            run.updated_at = now
            await session.commit()
            return True

    async def load_source(
        self,
        claimed: ClaimedOfficialAccountRun,
    ) -> OfficialAccountSourceSnapshot:
        async with self._session_factory() as session:
            run = await session.get(OfficialAccountArticleRunModel, claimed.run_id)
            _assert_read_lease(run, claimed)
            if run is None:
                raise OfficialAccountLeaseLostError()
            if run.generation_mode == "fixture":
                source = fixture_source_snapshot(
                    multi_image=(
                        claimed.identity.media_plan_version
                        in {
                            OFFICIAL_ACCOUNT_MEDIA_PLAN_V1_VERSION,
                            OFFICIAL_ACCOUNT_MEDIA_PLAN_V2_VERSION,
                            OFFICIAL_ACCOUNT_MEDIA_PLAN_VERSION,
                            OFFICIAL_ACCOUNT_MEDIA_PLAN_V4_VERSION,
                        }
                    ),
                    semantic_media=(
                        claimed.identity.media_plan_version
                        in {
                            OFFICIAL_ACCOUNT_MEDIA_PLAN_V2_VERSION,
                            OFFICIAL_ACCOUNT_MEDIA_PLAN_VERSION,
                            OFFICIAL_ACCOUNT_MEDIA_PLAN_V4_VERSION,
                        }
                    ),
                )
            else:
                if run.material_package_id is None:
                    raise RuntimeError("live official-account run has no material package")
                package = await session.get(MaterialPackageModel, run.material_package_id)
                if package is None:
                    raise ConflictError("source material package is unavailable")
                image = await session.get(ImageArtifactModel, package.image_artifact_id)
                if image is None:
                    raise ConflictError("source material image is unavailable")
                source = material_package_source_snapshot(package, image)
            if source.source_fingerprint != run.source_fingerprint:
                raise ConflictError("official-account source fingerprint changed")
            return source

    async def load_source_media(
        self,
        claimed: ClaimedOfficialAccountRun,
    ) -> OfficialAccountSourceMedia:
        async with self._session_factory() as session:
            run = await session.get(OfficialAccountArticleRunModel, claimed.run_id)
            _assert_read_lease(run, claimed)
            if run is None:
                raise OfficialAccountLeaseLostError()
            if run.generation_mode == "fixture":
                return OfficialAccountSourceMedia(
                    source_image_artifact_id=None,
                    fixture_id=OFFICIAL_ACCOUNT_FIXTURE_ID,
                    media_type=FIXTURE_IMAGE_MEDIA_TYPE,
                    byte_size=FIXTURE_IMAGE_BYTE_SIZE,
                    sha256=FIXTURE_IMAGE_SHA256,
                )
            if run.material_package_id is None:
                raise RuntimeError("live official-account run has no source")
            package = await session.get(MaterialPackageModel, run.material_package_id)
            image = (
                await session.get(ImageArtifactModel, package.image_artifact_id)
                if package is not None
                else None
            )
            if (
                image is None
                or image.status != "succeeded"
                or image.media_type is None
                or image.byte_size is None
                or image.sha256 is None
            ):
                raise ConflictError("source material image metadata is incomplete")
            return OfficialAccountSourceMedia(
                source_image_artifact_id=image.id,
                fixture_id=None,
                media_type=image.media_type,
                byte_size=image.byte_size,
                sha256=image.sha256,
            )

    async def load_source_media_candidates(
        self,
        claimed: ClaimedOfficialAccountRun,
    ) -> tuple[OfficialAccountSourceMedia, ...]:
        if claimed.identity.media_plan_version not in {
            OFFICIAL_ACCOUNT_MEDIA_PLAN_V1_VERSION,
            OFFICIAL_ACCOUNT_MEDIA_PLAN_V2_VERSION,
            OFFICIAL_ACCOUNT_MEDIA_PLAN_VERSION,
            OFFICIAL_ACCOUNT_MEDIA_PLAN_V4_VERSION,
        }:
            return (await self.load_source_media(claimed),)
        async with self._session_factory() as session:
            run = await session.get(OfficialAccountArticleRunModel, claimed.run_id)
            _assert_read_lease(run, claimed)
            if run is None:
                raise OfficialAccountLeaseLostError()
            if run.generation_mode == "fixture":
                semantic_media = claimed.identity.media_plan_version in {
                    OFFICIAL_ACCOUNT_MEDIA_PLAN_V2_VERSION,
                    OFFICIAL_ACCOUNT_MEDIA_PLAN_VERSION,
                    OFFICIAL_ACCOUNT_MEDIA_PLAN_V4_VERSION,
                }
                checksums = (
                    FIXTURE_BODY_PUBLICATION_SHA256S
                    if semantic_media
                    else FIXTURE_BODY_IMAGE_SHA256S
                )
                byte_sizes = (
                    FIXTURE_BODY_PUBLICATION_BYTE_SIZES
                    if semantic_media
                    else FIXTURE_BODY_IMAGE_BYTE_SIZES
                )
                return tuple(
                    OfficialAccountSourceMedia(
                        source_image_artifact_id=None,
                        fixture_id=OFFICIAL_ACCOUNT_FIXTURE_ID,
                        media_type=(
                            FIXTURE_BODY_PUBLICATION_MEDIA_TYPE
                            if semantic_media
                            else FIXTURE_IMAGE_MEDIA_TYPE
                        ),
                        byte_size=byte_sizes[ordinal],
                        sha256=checksum,
                        ordinal=ordinal,
                        semantic_label=FIXTURE_BODY_IMAGE_LABELS[ordinal],
                        selection_reason=(
                            "semantic_section_assignment"
                            if semantic_media
                            else "仓库内已审核原创 fixture；按观察、验证、复盘语义稳定排序"
                        ),
                        candidate_id=(
                            checksum[:16]
                            if claimed.identity.media_plan_version
                            in {
                                OFFICIAL_ACCOUNT_MEDIA_PLAN_VERSION,
                                OFFICIAL_ACCOUNT_MEDIA_PLAN_V4_VERSION,
                            }
                            else f"fixture-publication-{checksum}"
                            if semantic_media
                            else ""
                        ),
                        semantic_tags=(
                            FIXTURE_BODY_SEMANTIC_TAGS[ordinal] if semantic_media else ()
                        ),
                        alt_text=(FIXTURE_BODY_ALT_TEXTS[ordinal] if semantic_media else ""),
                        caption_text=(FIXTURE_BODY_CAPTIONS[ordinal] if semantic_media else ""),
                        publication_priority=ordinal,
                        catalog_version=(
                            "official-account-fixture-catalog-v1"
                            if claimed.identity.media_plan_version
                            in {
                                OFFICIAL_ACCOUNT_MEDIA_PLAN_VERSION,
                                OFFICIAL_ACCOUNT_MEDIA_PLAN_V4_VERSION,
                            }
                            else None
                        ),
                        source_master_sha256=(
                            FIXTURE_BODY_IMAGE_SHA256S[ordinal]
                            if claimed.identity.media_plan_version
                            in {
                                OFFICIAL_ACCOUNT_MEDIA_PLAN_VERSION,
                                OFFICIAL_ACCOUNT_MEDIA_PLAN_V4_VERSION,
                            }
                            else None
                        ),
                    )
                    for ordinal, checksum in enumerate(checksums)
                )
            if run.material_package_id is None:
                raise RuntimeError("live official-account run has no source")
            package = await session.get(MaterialPackageModel, run.material_package_id)
            image = (
                await session.get(ImageArtifactModel, package.image_artifact_id)
                if package is not None
                else None
            )
            if (
                image is None
                or image.status != "succeeded"
                or image.media_type is None
                or image.byte_size is None
                or image.sha256 is None
            ):
                raise ConflictError("source material image metadata is incomplete")
            return (
                OfficialAccountSourceMedia(
                    source_image_artifact_id=image.id,
                    fixture_id=None,
                    media_type=image.media_type,
                    byte_size=image.byte_size,
                    sha256=image.sha256,
                    ordinal=0,
                    semantic_label="素材包已审核主图",
                    selection_reason="当前素材包仅暴露一张已审核图片，按安全降级使用单图",
                    candidate_id=(
                        f"image-artifact-{image.id}"
                        if claimed.identity.media_plan_version
                        in {
                            OFFICIAL_ACCOUNT_MEDIA_PLAN_V2_VERSION,
                            OFFICIAL_ACCOUNT_MEDIA_PLAN_VERSION,
                            OFFICIAL_ACCOUNT_MEDIA_PLAN_V4_VERSION,
                        }
                        else ""
                    ),
                    semantic_tags=(
                        ("主题", "家庭", "教育")
                        if claimed.identity.media_plan_version
                        in {
                            OFFICIAL_ACCOUNT_MEDIA_PLAN_V2_VERSION,
                            OFFICIAL_ACCOUNT_MEDIA_PLAN_VERSION,
                            OFFICIAL_ACCOUNT_MEDIA_PLAN_V4_VERSION,
                        }
                        else ()
                    ),
                    alt_text=(
                        "与文章主题相关的已审核素材图片"
                        if claimed.identity.media_plan_version
                        in {
                            OFFICIAL_ACCOUNT_MEDIA_PLAN_V2_VERSION,
                            OFFICIAL_ACCOUNT_MEDIA_PLAN_VERSION,
                            OFFICIAL_ACCOUNT_MEDIA_PLAN_V4_VERSION,
                        }
                        else ""
                    ),
                    caption_text=(
                        "图片来自本次素材包中已经通过审核的视觉素材。"
                        if claimed.identity.media_plan_version
                        in {
                            OFFICIAL_ACCOUNT_MEDIA_PLAN_V2_VERSION,
                            OFFICIAL_ACCOUNT_MEDIA_PLAN_VERSION,
                            OFFICIAL_ACCOUNT_MEDIA_PLAN_V4_VERSION,
                        }
                        else ""
                    ),
                ),
            )

    async def load_news_context_candidates(
        self,
        claimed: ClaimedOfficialAccountRun,
    ) -> tuple[OfficialAccountSourceMedia, ...]:
        async with self._session_factory() as session:
            run = await session.get(OfficialAccountArticleRunModel, claimed.run_id)
            _assert_read_lease(run, claimed)
            if run is None:
                raise OfficialAccountLeaseLostError()
            if run.generation_mode == "fixture":
                return ()
            if run.material_package_id is None:
                raise RuntimeError("live official-account run has no material package")
            rows = tuple(
                (
                    await session.execute(
                        select(
                            MaterialPackageSourceImageModel,
                            SourceArticleImageModel,
                            SourceSnapshotModel,
                        )
                        .join(
                            SourceArticleImageModel,
                            SourceArticleImageModel.id
                            == MaterialPackageSourceImageModel.source_article_image_id,
                        )
                        .join(
                            SourceSnapshotModel,
                            SourceSnapshotModel.id == SourceArticleImageModel.image_snapshot_id,
                        )
                        .where(
                            MaterialPackageSourceImageModel.package_id == run.material_package_id,
                            SourceArticleImageModel.status == "ready",
                        )
                        .order_by(MaterialPackageSourceImageModel.ordinal)
                    )
                ).tuples()
            )
            candidates: list[OfficialAccountSourceMedia] = []
            for link, image, snapshot in rows:
                if (
                    image.image_snapshot_id != snapshot.id
                    or snapshot.kind != "image"
                    or image.sha256 is None
                    or image.media_type is None
                    or image.byte_size is None
                    or image.width is None
                    or image.height is None
                    or image.final_image_url is None
                    or image.sha256 != snapshot.sha256
                    or image.media_type != snapshot.media_type
                    or image.byte_size != snapshot.byte_size
                    or image.rights_status != "publish_permission_unverified"
                ):
                    raise ConflictError("source news image snapshot metadata changed")
                candidates.append(
                    OfficialAccountSourceMedia(
                        source_image_artifact_id=None,
                        fixture_id=None,
                        source_article_image_id=image.id,
                        media_type=image.media_type,
                        byte_size=image.byte_size,
                        sha256=image.sha256,
                        ordinal=link.ordinal,
                        semantic_label="新闻原图",
                        selection_reason="evidence_snapshot_lineage_v1",
                        candidate_id=str(image.id),
                        alt_text=image.alt_text or image.caption or "新闻原图",
                        caption_text=image.caption or "",
                        credit=image.credit,
                        source_page_url=image.source_page_url,
                        image_url=image.final_image_url,
                        rights_status=image.rights_status,
                        context_only_not_evidence=True,
                        width=image.width,
                        height=image.height,
                    )
                )
            return tuple(candidates)

    async def persist_article(
        self,
        *,
        claimed: ClaimedOfficialAccountRun,
        article: ArticlePackage,
        result: OfficialAccountGenerationResult,
        validation_issues: tuple[ArticleValidationIssue, ...],
    ) -> StoredOfficialAccountArticle | None:
        async with self._session_factory() as session:
            run = await _locked_fenced_run(session, claimed)
            if run is None:
                return None
            existing = await session.scalar(
                select(OfficialAccountArticleVersionModel).where(
                    OfficialAccountArticleVersionModel.run_id == run.id
                )
            )
            if existing is not None:
                return _stored_article(existing)
            article_id = uuid4()
            validation_snapshot = {
                "passed": not any(issue.severity == "error" for issue in validation_issues),
                "issues": [issue.model_dump(mode="json") for issue in validation_issues],
                "rule_version": claimed.identity.rule_version,
            }
            article_row = OfficialAccountArticleVersionModel(
                id=article_id,
                run_id=run.id,
                version=_article_artifact_version(article),
                article_payload=_article_payload(article),
                content_fingerprint=article.content_fingerprint,
                provider=result.provider,
                model=result.model,
                generator_request_fingerprint=result.request_fingerprint,
                generator_provider_request_id=result.provider_request_id,
                audit_request_fingerprint=None,
                audit_provider_request_id=None,
                prompt_version=claimed.identity.generator_prompt_version,
                schema_version=claimed.identity.article_schema_version,
                audit_prompt_version=claimed.identity.auditor_prompt_version,
                audit_schema_version=claimed.identity.audit_schema_version,
                rule_version=claimed.identity.rule_version,
                validation_snapshot=validation_snapshot,
                audit_snapshot={"status": "pending", "accepted": None, "issue_codes": []},
                prompt_tokens=result.prompt_tokens,
                completion_tokens=result.completion_tokens,
                reasoning_tokens=result.reasoning_tokens,
                latency_ms=result.latency_ms,
            )
            session.add(article_row)
            await session.flush()
            if article.news_context_media is not None:
                if run.material_package_id is None:
                    if article.news_context_media.items:
                        raise RuntimeError("fixture article cannot bind source-news context media")
                else:
                    session.add_all(
                        OfficialAccountArticleContextImageModel(
                            id=uuid4(),
                            run_id=run.id,
                            material_package_id=run.material_package_id,
                            article_version_id=article_id,
                            source_article_image_id=item.source_article_image_id,
                            ordinal=item.ordinal,
                            section_index=item.section_index,
                            selection_version=article.news_context_media.selection_version,
                            alt_text=item.alt_text,
                            caption=item.caption,
                            credit=item.credit,
                            source_page_url=item.source_page_url,
                            rights_status=item.rights_status,
                            context_only_not_evidence=True,
                            sha256=item.sha256,
                        )
                        for item in article.news_context_media.items
                    )
            session.add(
                OfficialAccountArticleAttemptModel(
                    id=uuid4(),
                    run_id=run.id,
                    article_version_id=article_id,
                    stage="generating",
                    capability="generation",
                    ordinal=claimed.attempt_number,
                    status="succeeded",
                    request_fingerprint=result.request_fingerprint,
                    provider=result.provider,
                    model=result.model,
                    provider_request_id=result.provider_request_id,
                    prompt_tokens=result.prompt_tokens,
                    completion_tokens=result.completion_tokens,
                    reasoning_tokens=result.reasoning_tokens,
                    latency_ms=result.latency_ms,
                    validation_corrections=result.validation_corrections,
                    error_code=None,
                    safe_metadata={
                        "validation_issue_codes": [issue.code for issue in validation_issues],
                        "content_fingerprint": article.content_fingerprint,
                    },
                    completed_at=datetime.now(UTC),
                )
            )
            run.active_article_version_id = article_id
            if validation_snapshot["passed"]:
                run.current_stage = "auditing"
            else:
                _finish_terminal(
                    run,
                    status="review_required",
                    error_code="article_validation_failed",
                )
            run.updated_at = datetime.now(UTC)
            await session.commit()
            return _stored_article(article_row)

    async def persist_audit(
        self,
        *,
        claimed: ClaimedOfficialAccountRun,
        article: StoredOfficialAccountArticle,
        result: OfficialAccountAuditResult,
    ) -> StoredOfficialAccountArticle | None:
        async with self._session_factory() as session:
            run = await _locked_fenced_run(session, claimed)
            if run is None:
                return None
            row = await session.get(OfficialAccountArticleVersionModel, article.id)
            if row is None or row.run_id != run.id:
                raise RuntimeError("official-account audit article lineage is invalid")
            if row.audit_snapshot.get("status") != "pending":
                return _stored_article(row)
            now = datetime.now(UTC)
            row.audit_request_fingerprint = result.request_fingerprint
            row.audit_provider_request_id = result.provider_request_id
            row.audit_snapshot = {
                "status": "accepted" if result.verdict.accepted else "rejected",
                "accepted": result.verdict.accepted,
                "issue_codes": list(result.verdict.issue_codes),
                "claim_ids": list(result.verdict.claim_ids),
                "rule_version": claimed.identity.rule_version,
            }
            row.prompt_tokens += result.prompt_tokens
            row.completion_tokens += result.completion_tokens
            row.reasoning_tokens += result.reasoning_tokens
            row.latency_ms += result.latency_ms
            row.audited_at = now
            session.add(
                OfficialAccountArticleAttemptModel(
                    id=uuid4(),
                    run_id=run.id,
                    article_version_id=row.id,
                    stage="auditing",
                    capability="audit",
                    ordinal=claimed.attempt_number,
                    status="succeeded",
                    request_fingerprint=result.request_fingerprint,
                    provider=result.provider,
                    model=result.model,
                    provider_request_id=result.provider_request_id,
                    prompt_tokens=result.prompt_tokens,
                    completion_tokens=result.completion_tokens,
                    reasoning_tokens=result.reasoning_tokens,
                    latency_ms=result.latency_ms,
                    validation_corrections=result.validation_corrections,
                    error_code=None,
                    safe_metadata={
                        "accepted": result.verdict.accepted,
                        "issue_codes": list(result.verdict.issue_codes),
                        "claim_ids": list(result.verdict.claim_ids),
                    },
                    completed_at=now,
                )
            )
            if result.verdict.accepted:
                run.current_stage = "rendering"
            else:
                _finish_terminal(run, status="review_required", error_code="article_audit_rejected")
            run.updated_at = now
            await session.commit()
            return _stored_article(row)

    async def persist_render(
        self,
        *,
        claimed: ClaimedOfficialAccountRun,
        article: StoredOfficialAccountArticle,
        rendered: RenderedOfficialAccountHtml,
    ) -> StoredOfficialAccountRender | None:
        async with self._session_factory() as session:
            run = await _locked_fenced_run(session, claimed)
            if run is None:
                return None
            existing = await session.scalar(
                select(OfficialAccountRenderVersionModel).where(
                    OfficialAccountRenderVersionModel.run_id == run.id
                )
            )
            if existing is not None:
                return _stored_render(existing)
            row = OfficialAccountRenderVersionModel(
                id=uuid4(),
                run_id=run.id,
                article_version_id=article.id,
                canonical_html=rendered.canonical_html,
                render_fingerprint=rendered.render_fingerprint,
                renderer_version=rendered.renderer_version,
                style_version=rendered.style_version,
                template_version=rendered.template_version,
                byte_size=len(rendered.canonical_html.encode("utf-8")),
            )
            session.add(row)
            await session.flush()
            run.active_render_version_id = row.id
            run.current_stage = "staging_body_media"
            run.updated_at = datetime.now(UTC)
            _add_workflow_attempt(
                session,
                claimed=claimed,
                stage="rendering",
                request_fingerprint=rendered.render_fingerprint,
                safe_metadata={"byte_size": row.byte_size},
            )
            await session.commit()
            return _stored_render(row)

    async def persist_media(
        self,
        *,
        claimed: ClaimedOfficialAccountRun,
        render: StoredOfficialAccountRender,
        source_media: OfficialAccountSourceMedia,
        request_fingerprint: str,
        result: OfficialAccountMediaResult,
    ) -> tuple[UUID, OfficialAccountMediaResult] | None:
        async with self._session_factory() as session:
            run = await _locked_fenced_run(session, claimed)
            if run is None:
                return None
            body_mismatch = result.role == "body" and (
                not 0 <= result.ordinal <= 4
                or result.ordinal != source_media.ordinal
                or result.sha256 != source_media.sha256
                or result.media_type != source_media.media_type
                or result.byte_size != source_media.byte_size
            )
            if (
                result.role not in {"body", "cover", "context"}
                or (result.role == "cover" and result.ordinal != 0)
                or (result.role == "context" and not 0 <= result.ordinal <= 1)
                or body_mismatch
            ):
                raise RuntimeError(
                    "official-account staged media does not match its planned source"
                )
            if source_media.generated_visual_id is not None:
                generated = await session.get(
                    OfficialAccountGeneratedVisualModel, source_media.generated_visual_id
                )
                if (
                    result.role != "body"
                    or generated is None
                    or generated.run_id != run.id
                    or generated.render_version_id != render.id
                    or generated.ordinal != result.ordinal
                    or generated.status != "ready"
                    or generated.media_type != result.media_type
                    or generated.byte_size != result.byte_size
                    or generated.sha256 != result.sha256
                ):
                    raise RuntimeError("generated visual media lineage is invalid")
            elif source_media.source_article_image_id is not None:
                context_image = await session.get(
                    SourceArticleImageModel, source_media.source_article_image_id
                )
                context_plan = await session.scalar(
                    select(OfficialAccountArticleContextImageModel).where(
                        OfficialAccountArticleContextImageModel.run_id == run.id,
                        OfficialAccountArticleContextImageModel.source_article_image_id
                        == source_media.source_article_image_id,
                        OfficialAccountArticleContextImageModel.ordinal == result.ordinal,
                    )
                )
                if (
                    result.role != "context"
                    or context_image is None
                    or context_plan is None
                    or context_image.status != "ready"
                    or context_image.sha256 != result.sha256
                    or context_image.media_type != result.media_type
                    or context_image.byte_size != result.byte_size
                    or context_plan.sha256 != result.sha256
                ):
                    raise RuntimeError("source-news context media lineage is invalid")
            elif source_media.source_image_artifact_id is None and source_media.fixture_id is None:
                raise RuntimeError("official-account media source lineage is incomplete")
            existing = await session.scalar(
                select(OfficialAccountLocalMediaModel).where(
                    OfficialAccountLocalMediaModel.run_id == run.id,
                    OfficialAccountLocalMediaModel.role == result.role,
                    OfficialAccountLocalMediaModel.ordinal == result.ordinal,
                )
            )
            if existing is not None:
                return existing.id, _media_result(existing)
            row = OfficialAccountLocalMediaModel(
                id=uuid4(),
                run_id=run.id,
                render_version_id=render.id,
                source_image_artifact_id=source_media.source_image_artifact_id,
                fixture_id=source_media.fixture_id,
                generated_visual_id=source_media.generated_visual_id,
                source_article_image_id=source_media.source_article_image_id,
                role=result.role,
                ordinal=result.ordinal,
                request_fingerprint=request_fingerprint,
                local_media_id=result.local_media_id,
                media_type=result.media_type,
                byte_size=result.byte_size,
                sha256=result.sha256,
                descriptor={
                    "access": "controlled_local_api",
                    "role": result.role,
                    "ordinal": result.ordinal,
                    "source_kind": "fixture"
                    if source_media.fixture_id == OFFICIAL_ACCOUNT_FIXTURE_ID
                    else "approved_catalog"
                    if source_media.catalog_asset_ref is not None
                    else "generated_visual"
                    if source_media.generated_visual_id is not None
                    else "source_news"
                    if source_media.source_article_image_id is not None
                    else "image_artifact",
                    **(
                        {
                            "semantic_label": source_media.semantic_label,
                            "alt_text": source_media.alt_text,
                            "assigned_section_index": source_media.assigned_section_index,
                            "score_band": source_media.score_band,
                            "selection_reason_code": source_media.selection_reason_code,
                            "selection_method": source_media.selection_method,
                            "similarity_band": source_media.similarity_band,
                            **(
                                {
                                    "catalog_asset_ref": source_media.catalog_asset_ref,
                                    "catalog_version": source_media.catalog_version,
                                    "source_master_sha256": source_media.source_master_sha256,
                                }
                                if source_media.catalog_asset_ref is not None
                                else {}
                            ),
                        }
                        if source_media.selection_reason_code is not None
                        else {}
                    ),
                    **(
                        {
                            "semantic_label": "新闻原图",
                            "alt_text": source_media.alt_text,
                            "assigned_section_index": source_media.assigned_section_index,
                            "source_page_url": source_media.source_page_url,
                            "caption": source_media.caption_text or None,
                            "credit": source_media.credit,
                            "rights_status": source_media.rights_status,
                            "context_only_not_evidence": True,
                        }
                        if source_media.source_article_image_id is not None
                        else {}
                    ),
                },
                status="ready",
                error_code=None,
            )
            session.add(row)
            await session.flush()
            if result.role == "body":
                if result.ordinal == 0:
                    run.active_body_media_id = row.id
                run.current_stage = "staging_body_media"
                stage = "staging_body_media"
            elif result.role == "context":
                run.current_stage = "staging_body_media"
                stage = "staging_body_media"
            else:
                run.active_cover_media_id = row.id
                run.current_stage = "creating_local_draft"
                stage = "staging_cover"
            run.updated_at = datetime.now(UTC)
            adapter_version = run.version_bundle.get("local_adapter_version")
            stage_ordinal = (
                _adapter_v7_staging_attempt_ordinal(
                    attempt_number=claimed.attempt_number,
                    role=cast(Literal["body", "context"], result.role),
                    ordinal=result.ordinal,
                )
                if adapter_version == OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V7_VERSION
                and result.role in {"body", "context"}
                else claimed.attempt_number * 10 + result.ordinal
                if (
                    result.role == "body"
                    and adapter_version
                    in {
                        OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V3_VERSION,
                        OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V4_VERSION,
                        OFFICIAL_ACCOUNT_LOCAL_ADAPTER_VERSION,
                        OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V6_VERSION,
                    }
                )
                or result.role == "context"
                else None
            )
            _add_workflow_attempt(
                session,
                claimed=claimed,
                stage=stage,
                request_fingerprint=request_fingerprint,
                ordinal=stage_ordinal,
                safe_metadata={
                    "role": result.role,
                    "ordinal": result.ordinal,
                    "local_media_id": result.local_media_id,
                },
            )
            await session.commit()
            return row.id, _media_result(row)

    async def persist_draft(
        self,
        *,
        claimed: ClaimedOfficialAccountRun,
        render: StoredOfficialAccountRender,
        body_media_id: UUID,
        body_media_ids: tuple[UUID, ...],
        cover_media_id: UUID,
        request_fingerprint: str,
        result: OfficialAccountDraftResult,
    ) -> OfficialAccountLocalDraftModel | None:
        async with self._session_factory() as session:
            run = await _locked_fenced_run(session, claimed)
            if run is None:
                return None
            existing = await session.scalar(
                select(OfficialAccountLocalDraftModel).where(
                    OfficialAccountLocalDraftModel.run_id == run.id
                )
            )
            if existing is not None:
                return existing
            if not body_media_ids or body_media_ids[0] != body_media_id or len(body_media_ids) > 5:
                raise RuntimeError("official-account draft body media lineage is invalid")
            body_rows = (
                await session.scalars(
                    select(OfficialAccountLocalMediaModel)
                    .where(
                        OfficialAccountLocalMediaModel.id.in_(body_media_ids),
                        OfficialAccountLocalMediaModel.run_id == run.id,
                        OfficialAccountLocalMediaModel.render_version_id == render.id,
                        OfficialAccountLocalMediaModel.role == "body",
                        OfficialAccountLocalMediaModel.status == "ready",
                    )
                    .order_by(OfficialAccountLocalMediaModel.ordinal)
                )
            ).all()
            cover_row = await session.get(OfficialAccountLocalMediaModel, cover_media_id)
            if (
                tuple(item.id for item in body_rows) != body_media_ids
                or tuple(item.ordinal for item in body_rows) != tuple(range(len(body_media_ids)))
                or len({item.sha256 for item in body_rows}) != len(body_rows)
                or cover_row is None
                or cover_row.run_id != run.id
                or cover_row.render_version_id != render.id
                or cover_row.role != "cover"
                or cover_row.ordinal != 0
                or cover_row.status != "ready"
            ):
                raise RuntimeError("official-account draft media roles or ordinals are incomplete")
            resolved_fingerprint = fingerprint(
                render.render_fingerprint,
                request_fingerprint,
                result.resolved_html,
            )
            row = OfficialAccountLocalDraftModel(
                id=uuid4(),
                run_id=run.id,
                render_version_id=render.id,
                body_media_id=body_media_id,
                cover_media_id=cover_media_id,
                request_fingerprint=request_fingerprint,
                local_draft_id=result.local_draft_id,
                resolved_html=result.resolved_html,
                resolved_fingerprint=resolved_fingerprint,
                simulation=True,
                state="ready",
                error_code=None,
            )
            session.add(row)
            await session.flush()
            for ordinal, media_id in enumerate(body_media_ids):
                session.add(
                    OfficialAccountLocalDraftBodyMediaModel(
                        draft_id=row.id,
                        ordinal=ordinal,
                        run_id=run.id,
                        body_media_id=media_id,
                    )
                )
            await session.flush()
            now = datetime.now(UTC)
            run.active_draft_id = row.id
            run.status = "ready"
            run.current_stage = "ready"
            run.completed_at = now
            run.updated_at = now
            run.error_code = None
            run.error_retryable = False
            _clear_lease(run)
            _add_workflow_attempt(
                session,
                claimed=claimed,
                stage="creating_local_draft",
                request_fingerprint=request_fingerprint,
                safe_metadata={
                    "local_draft_id": result.local_draft_id,
                    "simulation": True,
                    "body_media_count": len(body_media_ids),
                },
            )
            await session.commit()
            return row

    async def fail(
        self,
        *,
        claimed: ClaimedOfficialAccountRun,
        error_code: str,
        retryable: bool,
        retry_base_seconds: int,
        max_attempts: int,
        result_unknown: bool = False,
        safe_metadata: dict[str, object] | None = None,
    ) -> bool:
        safe_error = _safe_error(error_code)
        async with self._session_factory() as session:
            run = await _locked_fenced_run(session, claimed)
            if run is None:
                return False
            now = datetime.now(UTC)
            stage = run.current_stage
            if result_unknown:
                run.status = "result_unknown"
                run.current_stage = "result_unknown"
                run.completed_at = now
                run.error_retryable = False
            elif retryable and run.attempt_count < max_attempts:
                run.status = "queued"
                run.available_at = now + timedelta(
                    seconds=retry_base_seconds * (2 ** max(0, run.attempt_count - 1))
                )
                run.completed_at = None
                run.error_retryable = True
            else:
                run.status = "failed"
                run.current_stage = "failed"
                run.completed_at = now
                run.error_retryable = retryable
            run.error_code = safe_error
            run.updated_at = now
            _clear_lease(run)
            adapter_version = run.version_bundle.get("local_adapter_version")
            session.add(
                OfficialAccountArticleAttemptModel(
                    id=uuid4(),
                    run_id=run.id,
                    article_version_id=run.active_article_version_id,
                    stage=stage,
                    capability="workflow",
                    ordinal=(
                        _adapter_v7_staging_attempt_ordinal(
                            attempt_number=claimed.attempt_number,
                            role="failure",
                        )
                        if stage == "staging_body_media"
                        and adapter_version == OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V7_VERSION
                        else claimed.attempt_number * 10 + 9
                        if stage == "staging_body_media"
                        and adapter_version
                        in {
                            OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V3_VERSION,
                            OFFICIAL_ACCOUNT_LOCAL_ADAPTER_V4_VERSION,
                            OFFICIAL_ACCOUNT_LOCAL_ADAPTER_VERSION,
                        }
                        else claimed.attempt_number
                    ),
                    status="failed",
                    request_fingerprint=fingerprint(
                        run.request_fingerprint,
                        stage,
                        claimed.attempt_number,
                        safe_error,
                    ),
                    provider=run.provider if stage in {"generating", "auditing"} else None,
                    model=run.model if stage in {"generating", "auditing"} else None,
                    provider_request_id=None,
                    prompt_tokens=0,
                    completion_tokens=0,
                    reasoning_tokens=0,
                    latency_ms=0,
                    validation_corrections=0,
                    error_code=safe_error,
                    safe_metadata=safe_metadata or {},
                    completed_at=now,
                )
            )
            await session.commit()
            return True

    async def retry(self, *, run_id: UUID, max_attempts: int) -> OfficialAccountArticleRunModel:
        del max_attempts
        async with self._session_factory() as session:
            run = await session.scalar(
                select(OfficialAccountArticleRunModel)
                .where(OfficialAccountArticleRunModel.id == run_id)
                .with_for_update()
            )
            if run is None:
                raise NotFoundError("official-account article run")
            if run.status != "failed" or not run.error_retryable:
                raise ConflictError("official-account run is not retryable")
            now = datetime.now(UTC)
            run.status = "queued"
            run.current_stage = _resume_stage(run)
            run.available_at = now
            run.error_code = None
            run.error_retryable = False
            run.completed_at = None
            run.updated_at = now
            _clear_lease(run)
            await session.commit()
            return run


def material_package_source_snapshot(
    package: MaterialPackageModel,
    image: ImageArtifactModel,
) -> OfficialAccountSourceSnapshot:
    _assert_material_eligible(package, image)
    evidence_by_id: dict[UUID, OfficialAccountEvidence] = {}
    try:
        for item in package.source_snapshot:
            evidence_id = UUID(str(item["evidence_binding_id"]))
            source_url = str(item["source_url"])
            host = urlsplit(source_url).hostname or "权威来源"
            evidence_by_id[evidence_id] = OfficialAccountEvidence(
                evidence_id=evidence_id,
                source_url=source_url,
                source_name=host[:200],
                source_tier=(
                    str(item["source_tier"])[:40] if item.get("source_tier") is not None else None
                ),
                exact_quote=str(item["exact_quote"]),
            )
        brand_by_id: dict[UUID, OfficialAccountBrandContext] = {}
        for item in package.brand_snapshot:
            brand_id = UUID(str(item["brand_chunk_id"]))
            brand_by_id[brand_id] = OfficialAccountBrandContext(
                brand_chunk_id=brand_id,
                document_title=str(item["document_title"]),
                text=str(item["text"]),
                tone_tags=tuple(str(value)[:80] for value in item.get("tone_tags", [])),
                safety_tags=tuple(str(value)[:80] for value in item.get("safety_tags", [])),
            )
    except (KeyError, TypeError, ValueError, ValidationError):
        raise ConflictError("material package source snapshot is invalid") from None
    if not evidence_by_id or not brand_by_id:
        raise ConflictError("material package requires factual and brand bindings")
    title = package.topic_snapshot.get("title")
    summary = package.topic_snapshot.get("summary")
    existing_copy = package.copy_snapshot.get("copywriting")
    if not all(
        isinstance(value, str) and value.strip() for value in (title, summary, existing_copy)
    ):
        raise ConflictError("material package topic or copy snapshot is incomplete")
    source_fingerprint = fingerprint(
        "official-account-material-source-v1",
        package.id,
        package.package_version,
        package.request_fingerprint,
        package.topic_snapshot,
        package.copy_snapshot,
        package.source_snapshot,
        [
            {
                "brand_chunk_id": str(item.brand_chunk_id),
                "document_title": item.document_title,
                "text": item.text,
                "tone_tags": item.tone_tags,
                "safety_tags": item.safety_tags,
            }
            for item in brand_by_id.values()
        ],
        package.validation_snapshot,
        package.audit_snapshot,
        package.review_status,
        image.id,
        image.sha256,
        image.validation_snapshot,
        image.audit_snapshot,
    )
    return OfficialAccountSourceSnapshot(
        source_kind="material_package",
        source_id=str(package.id),
        source_fingerprint=source_fingerprint,
        material_package_id=package.id,
        source_image_artifact_id=image.id,
        topic_title=cast(str, title),
        topic_summary=cast(str, summary),
        existing_copy=cast(str, existing_copy),
        evidence=tuple(sorted(evidence_by_id.values(), key=lambda item: str(item.evidence_id))),
        brand_context=tuple(
            sorted(brand_by_id.values(), key=lambda item: str(item.brand_chunk_id))
        ),
        inherited_quality={
            "copy_validation_passed": True,
            "copy_audit_accepted": True,
            "image_validation_passed": True,
            "image_audit_status": str(image.audit_snapshot.get("status", "unknown")),
            "manual_review_status": package.review_status,
        },
    )


def _assert_material_eligible(
    package: MaterialPackageModel,
    image: ImageArtifactModel,
) -> None:
    if package.status not in {"ready", "awaiting_manual_use", "completed"}:
        raise ConflictError("material package is not ready for local article generation")
    if package.review_status == "rejected":
        raise ConflictError("rejected material package is not eligible")
    if package.validation_snapshot.get("passed") is not True:
        raise ConflictError("material package copy validation did not pass")
    if package.audit_snapshot.get("accepted") is not True:
        raise ConflictError("material package copy audit was not accepted")
    if image.status != "succeeded" or image.validation_snapshot.get("passed") is not True:
        raise ConflictError("material package image validation did not pass")
    image_audit = image.audit_snapshot
    if image_audit.get("configured") is True and image_audit.get("status") not in {
        "accepted",
        "not_applicable",
    }:
        raise ConflictError("material package image audit was not accepted")
    if any(value is None for value in (image.media_type, image.byte_size, image.sha256)):
        raise ConflictError("material package image metadata is incomplete")


async def _locked_fenced_run(
    session: AsyncSession,
    claimed: ClaimedOfficialAccountRun,
) -> OfficialAccountArticleRunModel | None:
    run = await session.scalar(
        select(OfficialAccountArticleRunModel)
        .where(OfficialAccountArticleRunModel.id == claimed.run_id)
        .with_for_update()
    )
    if (
        run is None
        or run.status != "running"
        or run.lease_token != claimed.lease_token
        or run.attempt_count != claimed.attempt_number
    ):
        return None
    return run


def _assert_read_lease(
    run: OfficialAccountArticleRunModel | None,
    claimed: ClaimedOfficialAccountRun,
) -> None:
    if (
        run is None
        or run.status != "running"
        or run.lease_token != claimed.lease_token
        or run.attempt_count != claimed.attempt_number
    ):
        raise OfficialAccountLeaseLostError()


def _resume_stage(run: OfficialAccountArticleRunModel) -> str:
    if run.active_article_version_id is None:
        return "generating"
    if run.active_render_version_id is None:
        return "auditing" if run.current_stage == "auditing" else "rendering"
    if run.active_body_media_id is None:
        return "staging_body_media"
    if (
        run.version_bundle.get("media_plan_version")
        in {
            OFFICIAL_ACCOUNT_MEDIA_PLAN_V1_VERSION,
            OFFICIAL_ACCOUNT_MEDIA_PLAN_V2_VERSION,
            OFFICIAL_ACCOUNT_MEDIA_PLAN_VERSION,
            OFFICIAL_ACCOUNT_MEDIA_PLAN_V4_VERSION,
        }
        and run.active_cover_media_id is None
    ):
        return "staging_body_media"
    if run.active_cover_media_id is None:
        return "staging_cover"
    if run.active_draft_id is None:
        return "creating_local_draft"
    return "ready"


def _identity_from_bundle(bundle: dict[str, object]) -> OfficialAccountVersionIdentity:
    try:
        return OfficialAccountVersionIdentity(
            provider=cast(Literal["fake", "zhipu"], bundle["provider"]),
            model=str(bundle["model"]),
            generator_prompt_version=str(bundle["generator_prompt_version"]),
            article_schema_version=str(bundle["article_schema_version"]),
            auditor_prompt_version=str(bundle["auditor_prompt_version"]),
            audit_schema_version=str(bundle["audit_schema_version"]),
            rule_version=str(bundle["rule_version"]),
            renderer_version=str(bundle["renderer_version"]),
            style_version=str(bundle["style_version"]),
            template_version=str(bundle["template_version"]),
            local_adapter_version=str(bundle["local_adapter_version"]),
            default_author=str(bundle["default_author"]),
            min_characters=_bundle_integer(bundle, "min_characters"),
            target_min_characters=_bundle_integer(bundle, "target_min_characters"),
            target_max_characters=_bundle_integer(bundle, "target_max_characters"),
            max_characters=_bundle_integer(bundle, "max_characters"),
            media_plan_version=(
                str(bundle["media_plan_version"])
                if bundle.get("media_plan_version") is not None
                else None
            ),
            visual_query_version=(
                str(bundle["visual_query_version"])
                if bundle.get("visual_query_version") is not None
                else None
            ),
            visual_selector_version=(
                str(bundle["visual_selector_version"])
                if bundle.get("visual_selector_version") is not None
                else None
            ),
            generated_visual_plan_version=(
                str(bundle["generated_visual_plan_version"])
                if bundle.get("generated_visual_plan_version") is not None
                else None
            ),
            generated_visual_prompt_version=(
                str(bundle["generated_visual_prompt_version"])
                if bundle.get("generated_visual_prompt_version") is not None
                else None
            ),
            context_media_plan_version=(
                str(bundle["context_media_plan_version"])
                if bundle.get("context_media_plan_version") is not None
                else None
            ),
        )
    except (KeyError, TypeError, ValueError):
        raise RuntimeError("official-account run version bundle is invalid") from None


def _identity_payload(identity: OfficialAccountVersionIdentity) -> dict[str, object]:
    payload = asdict(identity)
    if payload.get("context_media_plan_version") is None:
        payload.pop("context_media_plan_version", None)
    return payload


def _bundle_integer(bundle: dict[str, object], key: str) -> int:
    value = bundle[key]
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError(f"official-account version field {key} must be an integer")
    return value


def _stored_article(row: OfficialAccountArticleVersionModel) -> StoredOfficialAccountArticle:
    try:
        article = ArticlePackage.model_validate(row.article_payload)
        issues = tuple(
            ArticleValidationIssue.model_validate(item)
            for item in row.validation_snapshot.get("issues", [])
        )
        audit = (
            OfficialAccountAuditVerdict(
                accepted=bool(row.audit_snapshot["accepted"]),
                issue_codes=tuple(row.audit_snapshot.get("issue_codes", [])),
                claim_ids=tuple(row.audit_snapshot.get("claim_ids", [])),
            )
            if row.audit_snapshot.get("status") in {"accepted", "rejected"}
            else None
        )
    except (KeyError, TypeError, ValueError, ValidationError):
        raise RuntimeError("stored official-account article is invalid") from None
    return StoredOfficialAccountArticle(
        id=row.id,
        article=article,
        validation_issues=issues,
        audit=audit,
        provider_request_id=row.generator_provider_request_id,
        prompt_tokens=row.prompt_tokens,
        completion_tokens=row.completion_tokens,
        reasoning_tokens=row.reasoning_tokens,
        latency_ms=row.latency_ms,
        created_at=row.created_at,
    )


def _article_payload(article: ArticlePackage) -> dict[str, object]:
    payload = article.model_dump(mode="json")
    versions = payload.get("versions")
    if isinstance(versions, dict) and versions.get("context_media_plan_version") is None:
        versions.pop("context_media_plan_version", None)
    if payload.get("news_context_media") is None:
        payload.pop("news_context_media", None)
    return payload


def _stored_render(row: OfficialAccountRenderVersionModel) -> StoredOfficialAccountRender:
    return StoredOfficialAccountRender(
        id=row.id,
        article_version_id=row.article_version_id,
        canonical_html=row.canonical_html,
        render_fingerprint=row.render_fingerprint,
    )


def _stored_manual_review(
    row: OfficialAccountManualReviewModel,
) -> StoredOfficialAccountManualReview:
    return StoredOfficialAccountManualReview(
        id=row.id,
        run_id=row.run_id,
        decision=cast(Literal["approved", "rejected"], row.decision),
        reviewer_label=row.reviewer_label,
        note=row.note,
        request_fingerprint=row.request_fingerprint,
        reviewed_at=row.reviewed_at,
    )


def _stored_generated_visual(
    row: OfficialAccountGeneratedVisualModel,
) -> StoredOfficialAccountGeneratedVisual:
    try:
        plan = OfficialAccountGeneratedVisualPlan(
            run_id=row.run_id,
            article_version_id=row.article_version_id,
            render_version_id=row.render_version_id,
            ordinal=row.ordinal,
            section_index=row.section_index,
            block_index=row.block_index,
            block_kind=cast(
                Literal["paragraph", "bullet_list", "quote", "callout"] | None,
                row.block_kind,
            ),
            block_fingerprint=row.block_fingerprint,
            reference_asset_ref=row.reference_asset_ref,
            reference_catalog_version=row.reference_catalog_version,
            reference_source_checksum=row.reference_source_checksum,
            reference_publication_checksum=row.reference_publication_checksum,
            reference_input_version=row.reference_input_version,
            reference_input_checksum=row.reference_input_checksum,
            selection_method=cast(
                Literal["deterministic_tag", "multimodal_embedding"], row.selection_method
            ),
            similarity_band=cast(
                Literal["very_high", "high", "medium", "low"] | None, row.similarity_band
            ),
            request_fingerprint=row.request_fingerprint,
            plan_version=row.plan_version,
            prompt_version=row.prompt_version,
            output_profile_version=row.output_profile_version,
            provider=cast(Literal["fake", "toapis", "comfly"], row.provider),
            model=row.model,
        )
        _validate_generated_visual_plan(plan)
        status = cast(Literal["generating", "ready", "failed", "result_unknown"], row.status)
        output_values = (row.media_type, row.byte_size, row.sha256, row.width, row.height)
        if status == "ready":
            if (
                any(value is None for value in output_values)
                or row.error_code is not None
                or row.completed_at is None
            ):
                raise ValueError("generated visual result is incomplete")
        elif status == "generating":
            if (
                any(value is not None for value in output_values)
                or row.error_code is not None
                or row.completed_at is not None
            ):
                raise ValueError("generated visual intent state is invalid")
        elif status in {"failed", "result_unknown"}:
            if (
                any(value is not None for value in output_values)
                or row.error_code is None
                or row.completed_at is None
            ):
                raise ValueError("generated visual failure state is incomplete")
        else:
            raise ValueError("generated visual status is invalid")
    except (TypeError, ValueError):
        raise RuntimeError("stored official-account generated visual is invalid") from None
    return StoredOfficialAccountGeneratedVisual(
        id=row.id,
        plan=plan,
        status=status,
        media_type=row.media_type,
        byte_size=row.byte_size,
        sha256=row.sha256,
        width=row.width,
        height=row.height,
        error_code=row.error_code,
        created_at=row.created_at,
        completed_at=row.completed_at,
    )


def _stored_generated_visual_eval(
    row: OfficialAccountGeneratedVisualEvalModel,
) -> StoredOfficialAccountGeneratedVisualEval:
    try:
        observations = tuple(
            ImageEvalObservation.model_validate(item) for item in row.observation_snapshot
        )
        active_rubric = active_image_eval_rubric()
        replay_observations = tuple(
            observation.model_copy(update={"rubric_version": active_rubric.rubric_version})
            for observation in observations
        )
        replayed_decision = decide_image_eval_batch(replay_observations, active_rubric)
        stored_decision = ImageEvalDecisionKind(row.decision)
        stored_reason_codes = tuple(ImageEvalIssueCode(code) for code in row.issue_codes)
        if (
            row.rubric_version == IMAGE_EVAL_RUBRIC_VERSION
            and row.decision_policy_version == IMAGE_EVAL_DECISION_POLICY_VERSION
        ):
            decision = replayed_decision
            if (
                decision.decision is not stored_decision
                or decision.hard_gate_passed is not row.hard_gate_passed
                or decision.manual_review_required is not row.manual_review_required
                or decision.reason_codes != stored_reason_codes
            ):
                raise ValueError("stored generated visual eval decision changed")
        else:
            # Historical version identifiers remain readable so handoff can project them as
            # local-inspection evidence. Their aggregate is fingerprinted but is never promoted
            # to a current accepted audit claim.
            decision = replayed_decision.model_copy(
                update={
                    "decision": stored_decision,
                    "hard_gate_passed": row.hard_gate_passed,
                    "manual_review_required": row.manual_review_required,
                    "decision_policy_version": row.decision_policy_version,
                    "reason_codes": stored_reason_codes,
                }
            )
        result = OfficialAccountGeneratedVisualEvalResult(
            publication_sha256=row.publication_sha256,
            evaluator_version=row.evaluator_version,
            audit_prompt_version=row.audit_prompt_version,
            rubric_version=row.rubric_version,
            decision_policy_version=row.decision_policy_version,
            request_fingerprint=row.request_fingerprint,
            provider=row.provider,
            model=row.model,
            observations=observations,
            decision=decision,
        )
        stored = StoredOfficialAccountGeneratedVisualEval(
            id=row.id,
            generated_visual_id=row.generated_visual_id,
            run_id=row.run_id,
            record_fingerprint=row.record_fingerprint,
            result=result,
            completed_at=row.completed_at,
        )
    except (TypeError, ValueError, ValidationError):
        raise RuntimeError("stored official-account generated visual eval is invalid") from None
    return stored


def _validate_generated_visual_plan(plan: OfficialAccountGeneratedVisualPlan) -> None:
    is_v1 = (
        plan.plan_version == OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_V1_VERSION
        and plan.prompt_version == OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_V1_VERSION
        and plan.block_index is None
        and plan.block_kind is None
        and plan.block_fingerprint is None
        and plan.reference_input_version is None
        and plan.reference_input_checksum is None
        and plan.output_profile_version is None
    )
    is_publication = (
        (
            plan.plan_version == OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_V2_VERSION
            and plan.prompt_version == OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_V2_VERSION
        )
        or (
            plan.plan_version == OFFICIAL_ACCOUNT_GENERATED_VISUAL_PLAN_VERSION
            and plan.prompt_version == OFFICIAL_ACCOUNT_GENERATED_VISUAL_PROMPT_VERSION
        )
    ) and (
        plan.block_index is not None
        and 0 <= plan.block_index <= 12
        and plan.block_kind in {"paragraph", "bullet_list", "quote", "callout"}
        and plan.block_fingerprint is not None
        and len(plan.block_fingerprint) == 64
        and all(character in "0123456789abcdef" for character in plan.block_fingerprint)
        and plan.reference_input_version == IMAGE_REFERENCE_INPUT_V2
        and plan.reference_input_checksum is not None
        and len(plan.reference_input_checksum) == 64
        and all(character in "0123456789abcdef" for character in plan.reference_input_checksum)
        and plan.output_profile_version == OFFICIAL_ACCOUNT_GENERATED_VISUAL_OUTPUT_PROFILE_VERSION
    )
    if (
        not 0 <= plan.ordinal <= 4
        or not 0 <= plan.section_index <= 6
        or len(plan.reference_asset_ref) != 16
        or any(character not in "0123456789abcdef" for character in plan.reference_asset_ref)
        or len(plan.reference_source_checksum) != 64
        or len(plan.reference_publication_checksum) != 64
        or any(
            character not in "0123456789abcdef"
            for character in (plan.reference_source_checksum + plan.reference_publication_checksum)
        )
        or not plan.reference_catalog_version
        or plan.selection_method not in {"deterministic_tag", "multimodal_embedding"}
        or (plan.selection_method == "multimodal_embedding" and plan.similarity_band is None)
        or (plan.selection_method == "deterministic_tag" and plan.similarity_band is not None)
        or len(plan.request_fingerprint) != 64
        or any(character not in "0123456789abcdef" for character in plan.request_fingerprint)
        or not (is_v1 or is_publication)
        or plan.provider not in {"fake", "toapis", "comfly"}
        or not plan.model
    ):
        raise ValueError("official-account generated visual plan is invalid")


def _assert_generated_visual_plan(
    row: OfficialAccountGeneratedVisualModel,
    plan: OfficialAccountGeneratedVisualPlan,
) -> None:
    stored = _stored_generated_visual(row).plan
    if stored != plan:
        raise RuntimeError("official-account generated visual plan changed")


def _media_result(row: OfficialAccountLocalMediaModel) -> OfficialAccountMediaResult:
    score_band = row.descriptor.get("score_band")
    similarity_band = row.descriptor.get("similarity_band")
    selection_method = row.descriptor.get("selection_method")
    return OfficialAccountMediaResult(
        local_media_id=row.local_media_id,
        role=cast(Literal["body", "cover", "context"], row.role),
        ordinal=row.ordinal,
        media_url=f"/api/v1/official-account-local/media/{row.local_media_id}",
        media_type=row.media_type,
        byte_size=row.byte_size,
        sha256=row.sha256,
        semantic_label=(
            str(row.descriptor["semantic_label"])
            if row.descriptor.get("semantic_label") is not None
            else None
        ),
        assigned_section_index=(
            int(row.descriptor["assigned_section_index"])
            if row.descriptor.get("assigned_section_index") is not None
            else None
        ),
        score_band=(
            cast(Literal["heading", "body", "fallback"], score_band)
            if score_band in {"heading", "body", "fallback"}
            else None
        ),
        selection_reason_code=(
            str(row.descriptor["selection_reason_code"])
            if row.descriptor.get("selection_reason_code") is not None
            else None
        ),
        selection_method=(
            cast(Literal["deterministic_tag", "multimodal_embedding"], selection_method)
            if selection_method in {"deterministic_tag", "multimodal_embedding"}
            else None
        ),
        similarity_band=(
            cast(Literal["very_high", "high", "medium", "low"], similarity_band)
            if similarity_band in {"very_high", "high", "medium", "low"}
            else None
        ),
        alt_text=(
            str(row.descriptor["alt_text"]) if row.descriptor.get("alt_text") is not None else None
        ),
        provenance_kind=(
            str(row.descriptor["source_kind"])
            if row.descriptor.get("source_kind") is not None
            else None
        ),
        source_page_url=(
            str(row.descriptor["source_page_url"])
            if row.descriptor.get("source_page_url") is not None
            else None
        ),
        caption=(
            str(row.descriptor["caption"]) if row.descriptor.get("caption") is not None else None
        ),
        credit=(
            str(row.descriptor["credit"]) if row.descriptor.get("credit") is not None else None
        ),
        rights_status=(
            str(row.descriptor["rights_status"])
            if row.descriptor.get("rights_status") is not None
            else None
        ),
        context_only_not_evidence=(row.descriptor.get("context_only_not_evidence") is True),
    )


def _add_workflow_attempt(
    session: AsyncSession,
    *,
    claimed: ClaimedOfficialAccountRun,
    stage: str,
    request_fingerprint: str,
    safe_metadata: dict[str, object],
    ordinal: int | None = None,
) -> None:
    session.add(
        OfficialAccountArticleAttemptModel(
            id=uuid4(),
            run_id=claimed.run_id,
            article_version_id=None,
            stage=stage,
            capability="workflow",
            ordinal=ordinal or claimed.attempt_number,
            status="succeeded",
            request_fingerprint=request_fingerprint,
            provider=None,
            model=None,
            provider_request_id=None,
            prompt_tokens=0,
            completion_tokens=0,
            reasoning_tokens=0,
            latency_ms=0,
            validation_corrections=0,
            error_code=None,
            safe_metadata=safe_metadata,
            completed_at=datetime.now(UTC),
        )
    )


def _finish_terminal(
    run: OfficialAccountArticleRunModel,
    *,
    status: Literal["review_required", "failed", "result_unknown"],
    error_code: str,
) -> None:
    now = datetime.now(UTC)
    run.status = status
    run.current_stage = status
    run.error_code = _safe_error(error_code)
    run.error_retryable = False
    run.completed_at = now
    _clear_lease(run)


def _clear_lease(run: OfficialAccountArticleRunModel) -> None:
    run.lease_owner = None
    run.lease_token = None
    run.lease_expires_at = None
    run.heartbeat_at = None


def _safe_error(value: str) -> str:
    return value if _SAFE_ERROR.fullmatch(value) is not None else "official_account_failed"
