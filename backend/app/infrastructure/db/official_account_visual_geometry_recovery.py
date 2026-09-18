"""One-time recovery for a proved V3 image-dimension rejection.

This is deliberately narrower than normal retry handling: it cannot repair a
provider-unknown result, alter article/render inputs, or create a new edition.
It records a closed authorization before queueing the already-failed run and a
separate consumption record immediately before the one extra provider call.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, date, datetime
from typing import Annotated, Any, Literal, cast
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.ports.official_account_local import (
    ClaimedOfficialAccountRun,
    OfficialAccountGeneratedVisualPlan,
)
from app.application.ports.official_account_strict_visual import StrictGeneratedVisualClaim
from app.core.errors import ImageGenerationFailure
from app.domain.official_account_local import fingerprint
from app.domain.official_account_visual_pipeline import (
    NATIVE_TOLERANT_OUTPUT_GEOMETRY_POLICY,
    RESILIENT_VISUAL_PIPELINE_VERSION,
)
from app.infrastructure.db.models import (
    OfficialAccountArticleAttemptModel as Attempt,
)
from app.infrastructure.db.models import (
    OfficialAccountArticleRunModel as Run,
)
from app.infrastructure.db.models import (
    OfficialAccountArticleVersionModel as Article,
)
from app.infrastructure.db.models import (
    OfficialAccountGeneratedVisualModel as Visual,
)
from app.infrastructure.db.models import (
    OfficialAccountLocalDraftModel as LocalDraft,
)
from app.infrastructure.db.models import (
    OfficialAccountRenderVersionModel as Render,
)
from app.infrastructure.db.models import (
    OfficialAccountSingleEditionModel as Edition,
)
from app.infrastructure.db.models import (
    WeChatOfficialAccountDraftItemModel as DraftItem,
)

AUTH_STAGE = "visual_geometry_recovery_authorized"
CONSUMED_STAGE = "visual_geometry_recovery_consumed"
# ArticleAttempt.stage is a closed VARCHAR(40) operational identifier.
RUN_SCOPE_AUTH_STAGE = "visual_geometry_scope_authorized"
RUN_SCOPE_CONSUMED_STAGE = "visual_geometry_scope_consumed"
RECOVERY_VERSION: Literal["single-visual-geometry-recovery-v1"] = (
    "single-visual-geometry-recovery-v1"
)
RUN_SCOPE_VERSION: Literal["single-run-visual-geometry-scope-v1"] = (
    "single-run-visual-geometry-scope-v1"
)
RECOVERY_PHYSICAL_ATTEMPT_NUMBER: Literal[4] = 4
_RECOVERY_ATTEMPT_BASE = 201
SHANGHAI = ZoneInfo("Asia/Shanghai")
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class GeometryRecoveryTarget(BaseModel):
    """Every durable identity is supplied explicitly; there is no discovery mode."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    edition_id: UUID
    run_id: UUID
    article_version_id: UUID
    visual_id: UUID
    business_date: date


class GeometryRecoveryAuthorization(GeometryRecoveryTarget):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal["single-visual-geometry-recovery-v1"] = RECOVERY_VERSION
    account_fingerprint: Sha256
    render_version_id: UUID
    visual_ordinal: Annotated[int, Field(strict=True, ge=0, le=4)]
    logical_request_fingerprint: Sha256
    prior_attempt_ids: tuple[UUID, UUID, UUID]
    prior_attempt_fingerprints: tuple[Sha256, Sha256, Sha256]
    original_run_bundle_fingerprint: Sha256
    preserved_content_fingerprint: Sha256
    snapshot_fingerprint: Sha256
    authorized_run_attempt_count: Annotated[int, Field(strict=True, ge=1, le=5)]
    authorized_at: datetime
    retry_expires_at: datetime

    @model_validator(mode="after")
    def _closed_authority(self) -> GeometryRecoveryAuthorization:
        if (
            any(value.utcoffset() is None for value in (self.authorized_at, self.retry_expires_at))
            or not self.authorized_at < self.retry_expires_at
            or self.authorized_at.astimezone(SHANGHAI).date() != self.business_date
            or self.retry_expires_at.astimezone(SHANGHAI).date() != self.business_date
        ):
            raise ValueError("visual_geometry_recovery_authority_invalid")
        return self

    @property
    def authorization_fingerprint(self) -> str:
        return fingerprint(RECOVERY_VERSION, self.model_dump(mode="json"))

    @property
    def provider_request_fingerprint(self) -> str:
        return fingerprint(
            "single-visual-geometry-recovery-provider-request-v1",
            self.authorization_fingerprint,
            self.logical_request_fingerprint,
            RECOVERY_PHYSICAL_ATTEMPT_NUMBER,
        )


class GeometryRecoveryConsumption(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal["single-visual-geometry-recovery-consumed-v1"] = (
        "single-visual-geometry-recovery-consumed-v1"
    )
    authorization_fingerprint: Sha256
    provider_request_fingerprint: Sha256
    visual_id: UUID
    physical_attempt_number: Literal[4] = RECOVERY_PHYSICAL_ATTEMPT_NUMBER
    output_geometry_policy: Literal["native-tolerant-v1"] = NATIVE_TOLERANT_OUTPUT_GEOMETRY_POLICY
    lease_token: UUID
    run_attempt_number: Annotated[int, Field(strict=True, ge=2, le=6)]


class GeometryRecoveryRunScopeAuthorization(GeometryRecoveryTarget):
    """One bounded execution claim may use tolerant decoding for the remaining body slots."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal["single-run-visual-geometry-scope-v1"] = RUN_SCOPE_VERSION
    root_authorization_fingerprint: Sha256
    account_fingerprint: Sha256
    render_version_id: UUID
    original_run_bundle_fingerprint: Sha256
    preserved_content_fingerprint: Sha256
    eligible_visual_ordinals: tuple[Annotated[int, Field(ge=0, le=4)], ...]
    authorized_at: datetime
    retry_expires_at: datetime

    @model_validator(mode="after")
    def _closed_scope(self) -> GeometryRecoveryRunScopeAuthorization:
        if (
            not self.eligible_visual_ordinals
            or tuple(sorted(set(self.eligible_visual_ordinals))) != self.eligible_visual_ordinals
            or any(
                value.utcoffset() is None for value in (self.authorized_at, self.retry_expires_at)
            )
            or not self.authorized_at < self.retry_expires_at
            or self.authorized_at.astimezone(SHANGHAI).date() != self.business_date
            or self.retry_expires_at.astimezone(SHANGHAI).date() != self.business_date
        ):
            raise ValueError("visual_geometry_recovery_scope_invalid")
        return self

    @property
    def authorization_fingerprint(self) -> str:
        return fingerprint(RUN_SCOPE_VERSION, self.model_dump(mode="json"))

    def provider_request_fingerprint(self, plan: OfficialAccountGeneratedVisualPlan) -> str:
        return fingerprint(
            "single-run-visual-geometry-scope-provider-request-v1",
            self.authorization_fingerprint,
            plan.request_fingerprint,
            plan.ordinal,
        )


class GeometryRecoveryRunScopeConsumption(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal["single-run-visual-geometry-scope-consumed-v1"] = (
        "single-run-visual-geometry-scope-consumed-v1"
    )
    authorization_fingerprint: Sha256
    lease_token: UUID
    run_attempt_number: Annotated[int, Field(strict=True, ge=1, le=8)]


def geometry_recovery_attempt_ordinal(slot_ordinal: int) -> int:
    if not 0 <= slot_ordinal <= 4:
        raise ValueError("geometry recovery visual ordinal is invalid")
    return _RECOVERY_ATTEMPT_BASE + slot_ordinal


def _require(condition: bool) -> None:
    if not condition:
        raise ValueError("visual_geometry_recovery_precondition_failed")


async def _workflow_record(session: AsyncSession, run_id: UUID, stage: str) -> Attempt | None:
    return cast(
        Attempt | None,
        await session.scalar(
            select(Attempt).where(
                Attempt.run_id == run_id, Attempt.stage == stage, Attempt.ordinal == 1
            )
        ),
    )


def _authorization(row: Attempt) -> GeometryRecoveryAuthorization:
    value = GeometryRecoveryAuthorization.model_validate(row.safe_metadata)
    _require(
        row.capability == "workflow"
        and row.status == "succeeded"
        and row.run_id == value.run_id
        and row.article_version_id == value.article_version_id
        and row.request_fingerprint == value.authorization_fingerprint
    )
    return value


def _snapshot_fingerprint(
    *,
    edition: Edition,
    run: Run,
    visual: Visual,
    article: Article,
    render: Render,
    attempts: tuple[Attempt, ...],
) -> str:
    """Persist only a digest of immutable boundary fields, never article/provider bodies."""

    return fingerprint(
        "single-visual-geometry-recovery-snapshot-v1",
        {
            "edition": {
                "id": str(edition.id),
                "status": edition.status,
                "business_date": edition.business_date.isoformat(),
                "article_run_id": str(edition.article_run_id),
                "expires_at": edition.expires_at.isoformat(),
                "prepared": edition.prepared_artifact is not None,
                "receipt": edition.receipt_fingerprint,
            },
            "run": {
                "id": str(run.id),
                "status": run.status,
                "attempt_count": run.attempt_count,
                "active_article_version_id": str(run.active_article_version_id),
                "active_render_version_id": str(run.active_render_version_id),
                "active_draft_id": str(run.active_draft_id),
                "version_bundle": run.version_bundle,
            },
            "visual": {
                "id": str(visual.id),
                "status": visual.status,
                "ordinal": visual.ordinal,
                "request_fingerprint": visual.request_fingerprint,
                "error_code": visual.error_code,
                "render_version_id": str(visual.render_version_id),
            },
            "article": {
                "id": str(article.id),
                "content_fingerprint": article.content_fingerprint,
                "validation_passed": article.validation_snapshot.get("passed") is True,
                "audit_accepted": article.audit_snapshot.get("accepted") is True,
            },
            "render": {"id": str(render.id), "fingerprint": render.render_fingerprint},
            "attempts": [
                {
                    "id": str(item.id),
                    "ordinal": item.ordinal,
                    "status": item.status,
                    "request_fingerprint": item.request_fingerprint,
                    "error_code": item.error_code,
                    "safe_metadata": item.safe_metadata,
                }
                for item in attempts
            ],
        },
    )


def _preserved_content(article: Article, render: Render) -> str:
    return fingerprint(
        "single-visual-geometry-recovery-content-v1",
        article.id,
        article.content_fingerprint,
        article.validation_snapshot,
        article.audit_snapshot,
        render.id,
        render.render_fingerprint,
    )


def _bundle_fingerprint(bundle: dict[str, Any]) -> str:
    return fingerprint("single-visual-geometry-recovery-bundle-v1", bundle)


async def _dimension_attempts(
    session: AsyncSession, *, run: Run, visual: Visual
) -> tuple[Attempt, Attempt, Attempt]:
    """Require precisely the three proven V3 geometry failures, in their fixed slots."""

    from app.application.ports.official_account_strict_visual import (
        RESILIENT_VISUAL_MAX_PHYSICAL_ATTEMPTS,
        resilient_visual_attempt_ordinal,
        resilient_visual_provider_request_fingerprint,
    )

    rows = tuple(
        (
            await session.scalars(
                select(Attempt)
                .where(
                    Attempt.run_id == run.id,
                    Attempt.article_version_id == visual.article_version_id,
                    Attempt.stage == "generating_body_visuals",
                    Attempt.capability == "visual_generation",
                    Attempt.ordinal.in_(
                        tuple(
                            resilient_visual_attempt_ordinal(visual.ordinal, number)
                            for number in range(1, RESILIENT_VISUAL_MAX_PHYSICAL_ATTEMPTS + 1)
                        )
                    ),
                )
                .order_by(Attempt.ordinal)
            )
        ).all()
    )
    _require(len(rows) == RESILIENT_VISUAL_MAX_PHYSICAL_ATTEMPTS)
    for number, item in enumerate(rows, start=1):
        failure = ImageGenerationFailure.from_safe_metadata(item.safe_metadata.get("image_failure"))
        _require(
            item.ordinal == resilient_visual_attempt_ordinal(visual.ordinal, number)
            and item.status == "failed"
            and item.error_code == "image_output_invalid"
            and item.provider_request_id is None
            and item.request_fingerprint
            == resilient_visual_provider_request_fingerprint(
                visual.request_fingerprint, number, policy=RESILIENT_VISUAL_PIPELINE_VERSION
            )
            and item.safe_metadata.get("visual_pipeline_version")
            == RESILIENT_VISUAL_PIPELINE_VERSION
            and item.safe_metadata.get("logical_request_fingerprint") == visual.request_fingerprint
            and item.safe_metadata.get("physical_attempt_number") == number
            and failure is not None
            and failure.error_code == "image_output_invalid"
            and failure.disposition == "terminal"
            and failure.reason == "image_dimensions_invalid"
        )
    return cast(tuple[Attempt, Attempt, Attempt], rows)


def _new_record(
    auth: GeometryRecoveryAuthorization | GeometryRecoveryRunScopeAuthorization,
    *,
    stage: str,
    request_fingerprint: str,
    metadata: dict[str, Any],
    now: datetime,
) -> Attempt:
    return Attempt(
        id=uuid4(),
        run_id=auth.run_id,
        article_version_id=auth.article_version_id,
        stage=stage,
        capability="workflow",
        ordinal=1,
        status="succeeded",
        request_fingerprint=request_fingerprint,
        safe_metadata=metadata,
        created_at=now,
        completed_at=now,
    )


async def authorize_visual_geometry_recovery(
    session: AsyncSession,
    *,
    target: GeometryRecoveryTarget,
    now: datetime,
    apply: bool = False,
) -> GeometryRecoveryAuthorization:
    """Plan/apply exactly one V3 dimension recovery without touching article text or drafts."""

    from app.infrastructure.db.official_account_local import _frozen_retry_policy

    edition = await session.scalar(
        select(Edition).where(Edition.id == target.edition_id).with_for_update()
    )
    run = await session.scalar(select(Run).where(Run.id == target.run_id).with_for_update())
    visual = await session.scalar(
        select(Visual).where(Visual.id == target.visual_id).with_for_update()
    )
    _require(edition is not None and run is not None and visual is not None)
    assert edition is not None and run is not None and visual is not None
    prior = await _workflow_record(session, target.run_id, AUTH_STAGE)
    if prior is not None:
        authorized = _authorization(prior)
        _require(all(getattr(authorized, field) == value for field, value in target))
        return authorized
    _require(
        now.utcoffset() is not None
        and now.astimezone(SHANGHAI).date() == target.business_date
        and edition.business_date == target.business_date
        and edition.article_run_id == run.id == visual.run_id
        and edition.material_package_id == run.material_package_id
        and run.version_bundle.get("visual_pipeline_version") == RESILIENT_VISUAL_PIPELINE_VERSION
        and run.status == "failed"
        and visual.status == "failed"
        and visual.error_code == "image_output_invalid"
        and edition.status == "failed"
        and edition.lease_token is None
        and edition.lease_expires_at is None
        and run.lease_token is None
        and run.lease_expires_at is None
        and run.lease_owner is None
        and run.active_article_version_id == target.article_version_id == visual.article_version_id
        and run.active_render_version_id == visual.render_version_id
        and run.active_draft_id is None
        and edition.prepared_artifact is None
        and edition.receipt_fingerprint is None
        and edition.article_fingerprint is None
        and edition.content_fingerprint is None
        and edition.event_id is not None
    )
    local_draft = await session.scalar(
        select(LocalDraft.id).where(LocalDraft.run_id == run.id).limit(1)
    )
    draft_item = await session.scalar(
        select(DraftItem.job_id)
        .where(
            or_(
                DraftItem.source_ref == str(run.id),
                DraftItem.source_ref == str(edition.id),
                DraftItem.source_fingerprint == run.source_fingerprint,
            )
        )
        .limit(1)
    )
    _require(local_draft is None and draft_item is None)
    article = await session.get(Article, target.article_version_id)
    render = await session.get(Render, visual.render_version_id)
    _require(
        article is not None
        and render is not None
        and article.run_id == run.id
        and render.run_id == run.id
        and render.article_version_id == article.id
        and article.validation_snapshot.get("passed") is True
        and article.audit_snapshot.get("accepted") is True
    )
    assert article is not None and render is not None
    maximum, _delay, retry_expires_at = _frozen_retry_policy(
        run.version_bundle.get("execution_retry_policy")
    )
    _require(
        maximum >= run.attempt_count + 1
        and retry_expires_at == edition.expires_at
        and now < retry_expires_at
    )
    attempts = await _dimension_attempts(session, run=run, visual=visual)
    _require(
        await session.scalar(
            select(Attempt.id).where(
                Attempt.run_id == run.id,
                Attempt.stage == "generating_body_visuals",
                Attempt.ordinal == geometry_recovery_attempt_ordinal(visual.ordinal),
            )
        )
        is None
    )
    auth = GeometryRecoveryAuthorization(
        **target.model_dump(),
        account_fingerprint=edition.account_fingerprint,
        render_version_id=render.id,
        visual_ordinal=visual.ordinal,
        logical_request_fingerprint=visual.request_fingerprint,
        prior_attempt_ids=cast(tuple[UUID, UUID, UUID], tuple(item.id for item in attempts)),
        prior_attempt_fingerprints=cast(
            tuple[str, str, str], tuple(item.request_fingerprint for item in attempts)
        ),
        original_run_bundle_fingerprint=_bundle_fingerprint(run.version_bundle),
        preserved_content_fingerprint=_preserved_content(article, render),
        snapshot_fingerprint=_snapshot_fingerprint(
            edition=edition,
            run=run,
            visual=visual,
            article=article,
            render=render,
            attempts=attempts,
        ),
        authorized_run_attempt_count=run.attempt_count,
        authorized_at=now,
        retry_expires_at=retry_expires_at,
    )
    if not apply:
        return auth
    session.add(
        _new_record(
            auth,
            stage=AUTH_STAGE,
            request_fingerprint=auth.authorization_fingerprint,
            metadata=auth.model_dump(mode="json"),
            now=now,
        )
    )
    # This only requeues the frozen run at its already-completed visual stage.
    # The existing article/render IDs are retained and the edition is not cloned.
    run.status = "queued"
    run.current_stage = "generating_body_visuals"
    run.available_at = now
    run.completed_at = None
    run.error_code = None
    run.error_retryable = False
    run.updated_at = now
    edition.status = "generating"
    edition.error_code = None
    edition.available_at = now
    edition.updated_at = now
    return auth


async def claim_authorized_visual_geometry_recovery(
    session: AsyncSession,
    run: Run,
    claimed: ClaimedOfficialAccountRun,
    row: Visual,
    plan: OfficialAccountGeneratedVisualPlan,
) -> StrictGeneratedVisualClaim | None:
    """Consume the one closed authorization while the caller holds run/visual locks."""

    from app.infrastructure.db.official_account_local import (
        _assert_generated_visual_plan,
        _frozen_retry_policy,
        _stored_generated_visual,
    )

    auth_row = await _workflow_record(session, run.id, AUTH_STAGE)
    if auth_row is None or await _workflow_record(session, run.id, CONSUMED_STAGE) is not None:
        return None
    auth = _authorization(auth_row)
    now = datetime.now(UTC)
    _assert_generated_visual_plan(row, plan)
    edition = await session.scalar(
        select(Edition).where(Edition.id == auth.edition_id).with_for_update()
    )
    article = await session.get(Article, auth.article_version_id)
    render = await session.get(Render, auth.render_version_id)
    _require(edition is not None and article is not None and render is not None)
    assert edition is not None and article is not None and render is not None
    maximum, _delay, retry_expires_at = _frozen_retry_policy(
        run.version_bundle.get("execution_retry_policy")
    )
    local_draft = await session.scalar(
        select(LocalDraft.id).where(LocalDraft.run_id == run.id).limit(1)
    )
    draft_item = await session.scalar(
        select(DraftItem.job_id)
        .where(
            or_(
                DraftItem.source_ref == str(run.id),
                DraftItem.source_ref == str(auth.edition_id),
                DraftItem.source_fingerprint == run.source_fingerprint,
            )
        )
        .limit(1)
    )
    _require(
        row.id == auth.visual_id
        and row.status == "failed"
        and row.error_code == "image_output_invalid"
        and run.id == claimed.run_id == auth.run_id
        and run.status == "running"
        and run.lease_token == claimed.lease_token
        and run.lease_expires_at is not None
        and run.lease_expires_at > now
        and run.attempt_count == claimed.attempt_number == auth.authorized_run_attempt_count + 1
        and run.version_bundle.get("visual_pipeline_version") == RESILIENT_VISUAL_PIPELINE_VERSION
        and retry_expires_at == auth.retry_expires_at
        and now < auth.retry_expires_at
        and edition.article_run_id == run.id
        and edition.status == "generating"
        and edition.prepared_artifact is None
        and edition.receipt_fingerprint is None
        and run.active_draft_id is None
        and local_draft is None
        and draft_item is None
        and (run.active_article_version_id, run.active_render_version_id)
        == (auth.article_version_id, auth.render_version_id)
        and (
            row.run_id,
            row.article_version_id,
            row.render_version_id,
            row.ordinal,
            row.request_fingerprint,
        )
        == (
            auth.run_id,
            auth.article_version_id,
            auth.render_version_id,
            auth.visual_ordinal,
            auth.logical_request_fingerprint,
        )
        and _bundle_fingerprint(run.version_bundle) == auth.original_run_bundle_fingerprint
        and _preserved_content(article, render) == auth.preserved_content_fingerprint
        and maximum >= claimed.attempt_number
    )
    attempts = await _dimension_attempts(session, run=run, visual=row)
    _require(
        tuple(item.id for item in attempts) == auth.prior_attempt_ids
        and tuple(item.request_fingerprint for item in attempts) == auth.prior_attempt_fingerprints
    )
    consumption = GeometryRecoveryConsumption(
        authorization_fingerprint=auth.authorization_fingerprint,
        provider_request_fingerprint=auth.provider_request_fingerprint,
        visual_id=row.id,
        lease_token=claimed.lease_token,
        run_attempt_number=claimed.attempt_number,
    )
    session.add(
        _new_record(
            auth,
            stage=CONSUMED_STAGE,
            request_fingerprint=auth.provider_request_fingerprint,
            metadata=consumption.model_dump(mode="json"),
            now=now,
        )
    )
    row.status = "generating"
    row.error_code = None
    row.completed_at = None
    row.intent_lease_token = claimed.lease_token
    row.intent_attempt_number = claimed.attempt_number
    run.current_stage = "generating_body_visuals"
    return StrictGeneratedVisualClaim(
        "newly_claimed",
        _stored_generated_visual(row),
        provider_request_fingerprint=auth.provider_request_fingerprint,
        physical_attempt_number=RECOVERY_PHYSICAL_ATTEMPT_NUMBER,
        output_geometry_policy=NATIVE_TOLERANT_OUTPUT_GEOMETRY_POLICY,
    )


async def assert_authorized_geometry_recovery_physical_attempt(
    session: AsyncSession,
    *,
    run: Run,
    plan: OfficialAccountGeneratedVisualPlan,
    physical_attempt_number: int,
    provider_request_fingerprint: str,
) -> None:
    """Fence success/failure persistence to the consumed fourth attempt exactly once."""

    _require(physical_attempt_number == RECOVERY_PHYSICAL_ATTEMPT_NUMBER)
    auth_row = await _workflow_record(session, run.id, AUTH_STAGE)
    consumed_row = await _workflow_record(session, run.id, CONSUMED_STAGE)
    _require(auth_row is not None and consumed_row is not None)
    assert auth_row is not None and consumed_row is not None
    auth = _authorization(auth_row)
    consumed = GeometryRecoveryConsumption.model_validate(consumed_row.safe_metadata)
    _require(
        consumed_row.capability == "workflow"
        and consumed_row.status == "succeeded"
        and consumed_row.article_version_id == auth.article_version_id
        and consumed_row.request_fingerprint == auth.provider_request_fingerprint
        and consumed.authorization_fingerprint == auth.authorization_fingerprint
        and consumed.provider_request_fingerprint == auth.provider_request_fingerprint
        and consumed.visual_id == auth.visual_id
        and consumed.physical_attempt_number == RECOVERY_PHYSICAL_ATTEMPT_NUMBER
        and consumed.output_geometry_policy == NATIVE_TOLERANT_OUTPUT_GEOMETRY_POLICY
        and plan.run_id == auth.run_id
        and plan.article_version_id == auth.article_version_id
        and plan.render_version_id == auth.render_version_id
        and plan.ordinal == auth.visual_ordinal
        and plan.request_fingerprint == auth.logical_request_fingerprint
        and provider_request_fingerprint == auth.provider_request_fingerprint
    )


async def authorized_geometry_recovery_in_flight(
    session: AsyncSession,
    *,
    run: Run,
    claimed: ClaimedOfficialAccountRun,
    row: Visual,
    plan: OfficialAccountGeneratedVisualPlan,
) -> StrictGeneratedVisualClaim | None:
    """Return the one consumed fourth call to concurrent observers, never a new call."""

    from app.infrastructure.db.official_account_local import _stored_generated_visual

    auth_row = await _workflow_record(session, run.id, AUTH_STAGE)
    consumed_row = await _workflow_record(session, run.id, CONSUMED_STAGE)
    if auth_row is None or consumed_row is None:
        return None
    auth = _authorization(auth_row)
    consumed = GeometryRecoveryConsumption.model_validate(consumed_row.safe_metadata)
    _require(
        row.id == auth.visual_id
        and row.status == "generating"
        and run.id == claimed.run_id == auth.run_id
        and row.intent_lease_token == claimed.lease_token == consumed.lease_token
        and row.intent_attempt_number == claimed.attempt_number == consumed.run_attempt_number
        and consumed.authorization_fingerprint == auth.authorization_fingerprint
        and consumed.provider_request_fingerprint == auth.provider_request_fingerprint
        and consumed.visual_id == row.id
        and consumed.physical_attempt_number == RECOVERY_PHYSICAL_ATTEMPT_NUMBER
        and consumed.output_geometry_policy == NATIVE_TOLERANT_OUTPUT_GEOMETRY_POLICY
        and plan.request_fingerprint == auth.logical_request_fingerprint
        and plan.ordinal == auth.visual_ordinal
    )
    return StrictGeneratedVisualClaim(
        "in_flight",
        _stored_generated_visual(row),
        provider_request_fingerprint=auth.provider_request_fingerprint,
        physical_attempt_number=RECOVERY_PHYSICAL_ATTEMPT_NUMBER,
        output_geometry_policy=NATIVE_TOLERANT_OUTPUT_GEOMETRY_POLICY,
    )


async def authorize_visual_geometry_run_scope(
    session: AsyncSession,
    *,
    target: GeometryRecoveryTarget,
    now: datetime,
    apply: bool = False,
) -> GeometryRecoveryRunScopeAuthorization:
    """Authorize one further run claim for remaining slots after the root recovery succeeded."""

    from app.infrastructure.db.official_account_local import _frozen_retry_policy

    edition = await session.scalar(
        select(Edition).where(Edition.id == target.edition_id).with_for_update()
    )
    run = await session.scalar(select(Run).where(Run.id == target.run_id).with_for_update())
    root = await session.scalar(
        select(Visual).where(Visual.id == target.visual_id).with_for_update()
    )
    _require(edition is not None and run is not None and root is not None)
    assert edition is not None and run is not None and root is not None
    prior = await _workflow_record(session, run.id, RUN_SCOPE_AUTH_STAGE)
    if prior is not None:
        scope = GeometryRecoveryRunScopeAuthorization.model_validate(prior.safe_metadata)
        _require(all(getattr(scope, field) == value for field, value in target))
        return scope
    root_auth_row = await _workflow_record(session, run.id, AUTH_STAGE)
    root_consumed_row = await _workflow_record(session, run.id, CONSUMED_STAGE)
    _require(root_auth_row is not None and root_consumed_row is not None)
    assert root_auth_row is not None and root_consumed_row is not None
    root_auth = _authorization(root_auth_row)
    root_consumed = GeometryRecoveryConsumption.model_validate(root_consumed_row.safe_metadata)
    _require(
        now.utcoffset() is not None
        and now.astimezone(SHANGHAI).date() == target.business_date
        and edition.business_date == target.business_date
        and edition.article_run_id == run.id == root.run_id
        and run.version_bundle.get("visual_pipeline_version") == RESILIENT_VISUAL_PIPELINE_VERSION
        and run.status == "failed"
        and edition.status == "failed"
        and run.lease_token is None
        and run.lease_expires_at is None
        and run.lease_owner is None
        and edition.lease_token is None
        and edition.lease_expires_at is None
        and run.active_article_version_id == target.article_version_id == root.article_version_id
        and run.active_render_version_id == root.render_version_id
        and run.active_draft_id is None
        and edition.prepared_artifact is None
        and edition.receipt_fingerprint is None
        and edition.article_fingerprint is None
        and edition.content_fingerprint is None
        and root.status == "ready"
        and root.id == root_auth.visual_id == root_consumed.visual_id == target.visual_id
        and root_auth.run_id == target.run_id
        and root_consumed.authorization_fingerprint == root_auth.authorization_fingerprint
        and root_consumed.output_geometry_policy == NATIVE_TOLERANT_OUTPUT_GEOMETRY_POLICY
    )
    article = await session.get(Article, target.article_version_id)
    render = await session.get(Render, root.render_version_id)
    _require(
        article is not None
        and render is not None
        and article.run_id == run.id
        and render.run_id == run.id
        and article.validation_snapshot.get("passed") is True
        and article.audit_snapshot.get("accepted") is True
    )
    assert article is not None and render is not None
    _maximum, _delay, retry_expires_at = _frozen_retry_policy(
        run.version_bundle.get("execution_retry_policy")
    )
    _require(retry_expires_at == edition.expires_at and now < retry_expires_at)
    # Provider visual retries are internal to the root-recovery run claim.  Bind the
    # follow-up scope to that exact consumed claim instead of mistaking its three
    # physical visual attempts for three separate article-run attempts.
    _require(
        run.attempt_count
        == root_consumed.run_attempt_number
        == root_auth.authorized_run_attempt_count + 1
    )
    local_draft = await session.scalar(
        select(LocalDraft.id).where(LocalDraft.run_id == run.id).limit(1)
    )
    draft_item = await session.scalar(
        select(DraftItem.job_id)
        .where(
            or_(
                DraftItem.source_ref == str(run.id),
                DraftItem.source_ref == str(edition.id),
                DraftItem.source_fingerprint == run.source_fingerprint,
            )
        )
        .limit(1)
    )
    _require(local_draft is None and draft_item is None)
    visuals = tuple(
        (
            await session.scalars(
                select(Visual).where(Visual.run_id == run.id).order_by(Visual.ordinal)
            )
        ).all()
    )
    by_ordinal = {item.ordinal: item for item in visuals}
    _require(root.ordinal in by_ordinal and by_ordinal[root.ordinal].status == "ready")
    remaining = tuple(
        ordinal
        for ordinal in range(5)
        if ordinal != root.ordinal
        and (by_ordinal.get(ordinal) is None or by_ordinal[ordinal].status != "ready")
    )
    _require(bool(remaining))
    for ordinal in remaining:
        row = by_ordinal.get(ordinal)
        if row is None:
            continue
        _require(row.status == "failed" and row.error_code == "image_output_invalid")
        await _dimension_attempts(session, run=run, visual=row)
    scope = GeometryRecoveryRunScopeAuthorization(
        **target.model_dump(),
        root_authorization_fingerprint=root_auth.authorization_fingerprint,
        account_fingerprint=edition.account_fingerprint,
        render_version_id=render.id,
        original_run_bundle_fingerprint=_bundle_fingerprint(run.version_bundle),
        preserved_content_fingerprint=_preserved_content(article, render),
        eligible_visual_ordinals=remaining,
        authorized_at=now,
        retry_expires_at=retry_expires_at,
    )
    if not apply:
        return scope
    session.add(
        _new_record(
            scope,
            stage=RUN_SCOPE_AUTH_STAGE,
            request_fingerprint=scope.authorization_fingerprint,
            metadata=scope.model_dump(mode="json"),
            now=now,
        )
    )
    run.status = "queued"
    run.current_stage = "generating_body_visuals"
    run.available_at = now
    run.completed_at = None
    run.error_code = None
    run.error_retryable = False
    run.updated_at = now
    edition.status = "generating"
    edition.error_code = None
    edition.available_at = now
    edition.updated_at = now
    return scope


async def pending_authorized_visual_geometry_run_scope(
    session: AsyncSession, *, run: Run, now: datetime
) -> GeometryRecoveryRunScopeAuthorization | None:
    """Return only an unconsumed scope that may bypass one frozen run claim limit."""

    auth_row = await _workflow_record(session, run.id, RUN_SCOPE_AUTH_STAGE)
    if (
        auth_row is None
        or await _workflow_record(session, run.id, RUN_SCOPE_CONSUMED_STAGE) is not None
    ):
        return None
    scope = GeometryRecoveryRunScopeAuthorization.model_validate(auth_row.safe_metadata)
    _require(
        auth_row.capability == "workflow"
        and auth_row.status == "succeeded"
        and auth_row.request_fingerprint == scope.authorization_fingerprint
        and scope.run_id == run.id
        and run.status == "queued"
        and run.version_bundle.get("visual_pipeline_version") == RESILIENT_VISUAL_PIPELINE_VERSION
        and _bundle_fingerprint(run.version_bundle) == scope.original_run_bundle_fingerprint
        and now < scope.retry_expires_at
    )
    return scope


async def consume_authorized_visual_geometry_run_scope(
    session: AsyncSession,
    *,
    scope: GeometryRecoveryRunScopeAuthorization,
    run: Run,
    lease_token: UUID,
    now: datetime,
) -> None:
    _require(run.id == scope.run_id and run.attempt_count >= 1 and run.lease_token == lease_token)
    consumption = GeometryRecoveryRunScopeConsumption(
        authorization_fingerprint=scope.authorization_fingerprint,
        lease_token=lease_token,
        run_attempt_number=run.attempt_count,
    )
    session.add(
        _new_record(
            scope,
            stage=RUN_SCOPE_CONSUMED_STAGE,
            request_fingerprint=scope.authorization_fingerprint,
            metadata=consumption.model_dump(mode="json"),
            now=now,
        )
    )


async def active_authorized_visual_geometry_run_scope(
    session: AsyncSession,
    *,
    run: Run,
    claimed: ClaimedOfficialAccountRun,
    plan: OfficialAccountGeneratedVisualPlan,
) -> GeometryRecoveryRunScopeAuthorization | None:
    auth_row = await _workflow_record(session, run.id, RUN_SCOPE_AUTH_STAGE)
    consumed_row = await _workflow_record(session, run.id, RUN_SCOPE_CONSUMED_STAGE)
    if auth_row is None or consumed_row is None:
        return None
    scope = GeometryRecoveryRunScopeAuthorization.model_validate(auth_row.safe_metadata)
    consumed = GeometryRecoveryRunScopeConsumption.model_validate(consumed_row.safe_metadata)
    if plan.ordinal not in scope.eligible_visual_ordinals:
        return None
    _require(
        scope.run_id == run.id == claimed.run_id == plan.run_id
        and plan.article_version_id == scope.article_version_id
        and plan.render_version_id == scope.render_version_id
        and consumed.authorization_fingerprint == scope.authorization_fingerprint
        and consumed.lease_token == claimed.lease_token == run.lease_token
        and consumed.run_attempt_number == claimed.attempt_number == run.attempt_count
        and datetime.now(UTC) < scope.retry_expires_at
    )
    return scope


async def assert_authorized_visual_geometry_run_scope_attempt(
    session: AsyncSession,
    *,
    run: Run,
    plan: OfficialAccountGeneratedVisualPlan,
    physical_attempt_number: int,
    provider_request_fingerprint: str,
) -> bool:
    """Accept a scoped physical marker only when its run-wide authority is active."""

    if physical_attempt_number != RECOVERY_PHYSICAL_ATTEMPT_NUMBER:
        return False
    auth_row = await _workflow_record(session, run.id, RUN_SCOPE_AUTH_STAGE)
    consumed_row = await _workflow_record(session, run.id, RUN_SCOPE_CONSUMED_STAGE)
    if auth_row is None or consumed_row is None:
        return False
    scope = GeometryRecoveryRunScopeAuthorization.model_validate(auth_row.safe_metadata)
    consumed = GeometryRecoveryRunScopeConsumption.model_validate(consumed_row.safe_metadata)
    _require(
        scope.run_id == run.id == plan.run_id
        and plan.article_version_id == scope.article_version_id
        and plan.render_version_id == scope.render_version_id
        and plan.ordinal in scope.eligible_visual_ordinals
        and consumed.authorization_fingerprint == scope.authorization_fingerprint
        and provider_request_fingerprint == scope.provider_request_fingerprint(plan)
        and datetime.now(UTC) < scope.retry_expires_at
    )
    return True


async def _main(target: GeometryRecoveryTarget, apply: bool, run_scope: bool = False) -> None:
    from app.core.config import get_settings
    from app.infrastructure.db.session import create_engine, create_session_factory

    settings = get_settings()
    engine = create_engine(settings)
    sessions = create_session_factory(engine)
    try:
        async with sessions() as session, session.begin():
            auth = (
                await authorize_visual_geometry_run_scope(
                    session, target=target, now=datetime.now(UTC), apply=apply
                )
                if run_scope
                else await authorize_visual_geometry_recovery(
                    session, target=target, now=datetime.now(UTC), apply=apply
                )
            )
        print(
            json.dumps(
                {
                    "mode": "apply" if apply else "plan",
                    "scope": "remaining-run-visuals" if run_scope else "single-visual",
                    "authorization": auth.model_dump(mode="json"),
                },
                ensure_ascii=False,
            )
        )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="One authorized V3 image-dimension recovery; never creates a draft or publishes"
    )
    parser.add_argument("--edition-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--article-version-id", required=True)
    parser.add_argument("--visual-id", required=True)
    parser.add_argument("--business-date", required=True)
    parser.add_argument("--apply", action="store_true", help="persist the exact one-time recovery")
    parser.add_argument(
        "--run-scope",
        action="store_true",
        help="authorize one bounded tolerant execution for remaining body visual slots",
    )
    values = parser.parse_args()
    try:
        asyncio.run(
            _main(
                GeometryRecoveryTarget(
                    edition_id=values.edition_id,
                    run_id=values.run_id,
                    article_version_id=values.article_version_id,
                    visual_id=values.visual_id,
                    business_date=values.business_date,
                ),
                values.apply,
                values.run_scope,
            )
        )
    except Exception:
        # Never expose database/config/provider data in an operator shell receipt.
        raise SystemExit("visual_geometry_recovery_operator_failed") from None
