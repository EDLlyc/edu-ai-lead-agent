from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.application.services.content_slots import enqueue_manual_content_slot
from app.core.config import Settings
from app.core.errors import PolicyRejectedError
from app.core.security import normalize_https_url
from app.domain.content_slots import ContentSlot
from app.infrastructure.db.content_slots import (
    ContentSlotRunProjection,
    ContentSlotScoreProjection,
    PostgresContentSlotRepository,
    get_content_slot_run,
    list_content_slot_runs_for_date,
    list_content_slot_scores,
)
from app.infrastructure.db.models import (
    ContentSlotRunModel,
    ContentSlotSelectionModel,
    CopyGenerationRunModel,
    MaterialPackageModel,
    WeComDeliveryJobModel,
)
from app.schemas.content_slots import (
    ContentEditionResponse,
    ContentEditionSelectionResponse,
    ContentEditionSlotResponse,
    ContentEditionSourceResponse,
    ContentSlotRunResponse,
    ContentSlotScoreListResponse,
    ContentSlotScoreResponse,
    CreateContentSlotRunRequest,
)

router = APIRouter(tags=["content-slots"])


@router.post(
    "/content-slot-runs",
    response_model=ContentSlotRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_content_slot_run(
    payload: CreateContentSlotRunRequest,
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ContentSlotRunResponse:
    settings: Settings = request.app.state.settings
    repository = PostgresContentSlotRepository(request.app.state.session_factory)
    run_id = await enqueue_manual_content_slot(
        repository,
        settings,
        business_date=payload.business_date,
        slot=ContentSlot(payload.content_slot),
        now=datetime.now(UTC),
    )
    projected = _run_response(await get_content_slot_run(session, run_id))
    response.headers["Location"] = projected.status_url
    return projected


@router.get("/content-slot-runs/{run_id}", response_model=ContentSlotRunResponse)
async def read_content_slot_run(
    run_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ContentSlotRunResponse:
    return _run_response(await get_content_slot_run(session, run_id))


@router.get("/content-slot-runs/{run_id}/scores", response_model=ContentSlotScoreListResponse)
async def read_content_slot_scores(
    run_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ContentSlotScoreListResponse:
    rows = await list_content_slot_scores(session, run_id)
    return ContentSlotScoreListResponse(
        items=[_score_response(row) for row in rows], count=len(rows)
    )


@router.get("/content-editions/{business_date}", response_model=ContentEditionResponse)
async def read_content_edition(
    business_date: date,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
    profile: Annotated[str, Query(min_length=1, max_length=40)] = "preview",
) -> ContentEditionResponse:
    settings: Settings = request.app.state.settings
    now = datetime.now(UTC)
    projections = await list_content_slot_runs_for_date(
        session,
        business_date=business_date,
        timezone=settings.business_timezone,
        scoring_profile=profile,
    )
    latest_by_slot: dict[ContentSlot, ContentSlotRunProjection] = {}
    for run_projection in projections:
        slot = ContentSlot(run_projection.run.content_slot)
        current = latest_by_slot.get(slot)
        if current is None or run_projection.run.created_at > current.run.created_at:
            latest_by_slot[slot] = run_projection
    slots = []
    for schedule in settings.content_slot_schedules():
        projection = latest_by_slot.get(schedule.slot)
        instants = schedule.instants(business_date, settings.business_timezone)
        selections = (
            [
                await _selection_response(
                    session,
                    item.selection.id,
                    item.title,
                    item.event_time,
                    expires_at=projection.run.expires_at,
                    now=now,
                )
                for item in projection.selections
            ]
            if projection is not None
            else []
        )
        slots.append(
            ContentEditionSlotResponse(
                content_slot=cast(Any, schedule.slot.value),
                display_name=schedule.display_name,
                enabled=settings.content_slot_mode_enabled and schedule.enabled,
                target_at=instants.target_at,
                expires_at=instants.expires_at,
                state=_edition_slot_state(
                    settings=settings,
                    enabled=schedule.enabled,
                    projection=projection,
                    selection_states=tuple(item.state for item in selections),
                    expires_at=instants.expires_at,
                    now=now,
                ),
                run_id=projection.run.id if projection is not None else None,
                run_status=projection.run.status if projection is not None else None,
                item_limit=(projection.run.item_limit if projection else schedule.max_items),
                selected_count=projection.run.selected_count if projection else 0,
                unfilled_count=(projection.run.unfilled_count if projection else 0),
                unfilled_reason_codes=(
                    list(projection.run.unfilled_reason_codes) if projection else []
                ),
                error_code=projection.run.error_code if projection else None,
                selections=selections,
                run_url=(f"/api/v1/content-slot-runs/{projection.run.id}" if projection else None),
            )
        )
    return ContentEditionResponse(
        business_date=business_date,
        timezone=settings.business_timezone,
        scoring_profile=profile,
        slot_mode_enabled=settings.content_slot_mode_enabled,
        slots=slots,
    )


async def _selection_response(
    session: AsyncSession,
    selection_id: UUID,
    title: str,
    event_time: datetime | None,
    *,
    expires_at: datetime,
    now: datetime,
) -> ContentEditionSelectionResponse:
    if now.tzinfo is None or expires_at.tzinfo is None:
        raise ValueError("content edition projection instants must be timezone-aware")
    selection = await session.get(ContentSlotSelectionModel, selection_id)
    if selection is None:
        raise RuntimeError("content slot selection disappeared during projection")
    copy_run = await session.scalar(
        select(CopyGenerationRunModel)
        .where(CopyGenerationRunModel.content_slot_selection_id == selection.id)
        .order_by(CopyGenerationRunModel.created_at.desc())
        .limit(1)
    )
    package = (
        await session.scalar(
            select(MaterialPackageModel)
            .where(MaterialPackageModel.run_id == copy_run.id)
            .order_by(MaterialPackageModel.package_version.desc())
            .limit(1)
        )
        if copy_run is not None
        else None
    )
    delivery = (
        await session.scalar(
            select(WeComDeliveryJobModel)
            .where(
                WeComDeliveryJobModel.material_package_id == package.id,
                WeComDeliveryJobModel.mode == "formal",
            )
            .order_by(WeComDeliveryJobModel.created_at.desc())
            .limit(1)
        )
        if package is not None
        else None
    )
    state = _selection_state(
        copy_status=copy_run.status if copy_run else None,
        package_status=package.status if package else None,
        delivery_status=delivery.status if delivery else None,
        window_expired=now >= expires_at,
    )
    return ContentEditionSelectionResponse(
        selection_id=selection.id,
        ordinal=selection.ordinal,
        event_id=selection.selected_event_id,
        event_version_id=selection.selected_event_version_id,
        title=title,
        event_time=event_time,
        source_links=_safe_source_links(package.source_snapshot if package else None),
        copy_generation_run_id=copy_run.id if copy_run else None,
        copy_status=copy_run.status if copy_run else None,
        material_package_id=package.id if package else None,
        material_package_status=package.status if package else None,
        delivery_id=delivery.id if delivery else None,
        delivery_status=delivery.status if delivery else None,
        state=cast(Any, state),
        copy_url=(f"/api/v1/copy-generation-runs/{copy_run.id}/detail" if copy_run else None),
        material_package_url=(f"/api/v1/material-packages/{package.id}" if package else None),
        delivery_url=(f"/api/v1/wecom-deliveries/{delivery.id}" if delivery else None),
    )


def _safe_source_links(value: object) -> list[ContentEditionSourceResponse]:
    if not isinstance(value, list):
        return []
    links: list[ContentEditionSourceResponse] = []
    seen: set[str] = set()
    for item in value:
        if not isinstance(item, dict):
            continue
        url = item.get("source_url")
        if not isinstance(url, str):
            continue
        try:
            safe_url = normalize_https_url(url)
        except (PolicyRejectedError, UnicodeError, ValueError):
            continue
        if safe_url in seen:
            continue
        seen.add(safe_url)
        links.append(ContentEditionSourceResponse(source_name="原文来源", title=None, url=safe_url))
    return links


def _selection_state(
    *,
    copy_status: str | None,
    package_status: str | None,
    delivery_status: str | None,
    window_expired: bool,
) -> str:
    if delivery_status == "delivered":
        return "delivered"
    if delivery_status == "delivery_unknown":
        return "delivery_unknown"
    if delivery_status == "delivery_window_expired":
        return "expired"
    if delivery_status in {"failed", "partial", "cancelled"}:
        return "failed"
    if delivery_status == "running":
        return "ready"
    if delivery_status == "queued":
        return "expired" if window_expired else "ready"
    if package_status in {"failed", "rejected"} or copy_status in {
        "failed",
        "review_required",
    }:
        return "failed"
    if window_expired:
        return "expired"
    if package_status in {"ready", "awaiting_manual_use", "completed"}:
        return "ready"
    return "preparing"


def _edition_slot_state(
    *,
    settings: Settings,
    enabled: bool,
    projection: ContentSlotRunProjection | None,
    selection_states: tuple[str, ...],
    expires_at: datetime,
    now: datetime,
) -> Any:
    if not settings.content_slot_mode_enabled or not enabled:
        return "disabled"
    if projection is None:
        return "expired" if now >= expires_at else "missing"
    if projection.run.status == "failed":
        return "failed"
    if projection.run.status in {"queued", "running"}:
        return "expired" if now >= projection.run.expires_at else "preparing"
    if any(state == "preparing" for state in selection_states):
        return "expired" if now >= projection.run.expires_at else "preparing"
    if selection_states and all(state == "expired" for state in selection_states):
        return "expired"
    return "ready"


def _run_response(run: ContentSlotRunModel) -> ContentSlotRunResponse:
    slot = ContentSlot(run.content_slot)
    return ContentSlotRunResponse(
        id=run.id,
        trigger=cast(Any, run.trigger),
        business_date=run.business_date,
        timezone=run.timezone,
        content_slot=cast(Any, slot.value),
        display_name=slot.display_name,
        scoring_profile=run.scoring_profile,
        acquisition_run_id=run.acquisition_run_id,
        governance_run_id=run.governance_run_id,
        governed_event_cutoff=run.governed_event_cutoff,
        config_fingerprint=run.config_fingerprint,
        slot_policy_version=run.slot_policy_version,
        slot_policy_fingerprint=run.slot_policy_fingerprint,
        preparation_at=run.preparation_at,
        target_at=run.target_at,
        expires_at=run.expires_at,
        item_limit=run.item_limit,
        status=cast(Any, run.status),
        total_scores=run.total_scores,
        eligible_scores=run.eligible_scores,
        selected_count=run.selected_count,
        unfilled_count=run.unfilled_count,
        unfilled_reason_codes=list(run.unfilled_reason_codes),
        error_code=run.error_code,
        created_at=run.created_at,
        started_at=run.started_at,
        completed_at=run.completed_at,
        status_url=f"/api/v1/content-slot-runs/{run.id}",
        scores_url=f"/api/v1/content-slot-runs/{run.id}/scores",
    )


def _score_response(row: ContentSlotScoreProjection) -> ContentSlotScoreResponse:
    score = row.score
    return ContentSlotScoreResponse(
        id=score.id,
        run_id=score.run_id,
        event_id=score.event_id,
        event_version_id=score.event_version_id,
        event_title=row.event_title,
        event_time=row.event_time,
        total=score.total,
        threshold=score.threshold,
        passes_threshold=score.passes_threshold,
        eligible=score.eligible,
        veto_codes=list(score.veto_codes),
        slot_affinity=score.slot_affinity,
        slot_affinity_reasons=list(score.slot_affinity_reasons),
        same_day_excluded=score.same_day_excluded,
        same_day_exclusion_reason=score.same_day_exclusion_reason,
        final_ordering_value=score.final_ordering_value,
        final_ordering_key=score.final_ordering_key,
        rank=score.rank,
        selected_ordinal=score.selected_ordinal,
        explanation=dict(score.explanation),
    )
