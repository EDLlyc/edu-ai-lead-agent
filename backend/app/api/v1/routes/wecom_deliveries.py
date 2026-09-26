from __future__ import annotations

from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.dependencies import get_session
from app.application.services.wecom_delivery import (
    enqueue_wecom_delivery,
    retry_wecom_delivery,
    wecom_recipient_is_configured,
)
from app.core.errors import NotFoundError
from app.infrastructure.db.models import (
    NewsInfographicJobModel,
    WeComDeliveryJobModel,
    WeComInfographicAttemptModel,
    WeComInfographicSupplementModel,
)
from app.schemas.wecom_delivery import (
    WeComDeliveryCreateRequest,
    WeComDeliveryResponse,
    WeComInfographicAttemptResponse,
    WeComInfographicStatusResponse,
    WeComRecipientListResponse,
    WeComRecipientResponse,
)

router = APIRouter(tags=["wecom-deliveries"])


@router.get("/wecom/recipients", response_model=WeComRecipientListResponse)
async def list_wecom_recipients(request: Request) -> WeComRecipientListResponse:
    settings = request.app.state.settings
    if not wecom_recipient_is_configured(settings):
        return WeComRecipientListResponse(items=[], count=0)
    item = WeComRecipientResponse(
        id="default",
        display_name=settings.wecom_default_recipient_name,
        enabled=True,
    )
    return WeComRecipientListResponse(items=[item], count=1)


@router.post(
    "/material-packages/{package_id}/wecom-deliveries",
    response_model=WeComDeliveryResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
async def create_wecom_delivery(
    package_id: UUID,
    payload: WeComDeliveryCreateRequest,
    request: Request,
    response: Response,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> WeComDeliveryResponse:
    job = await enqueue_wecom_delivery(
        session=session,
        package_id=package_id,
        recipient_id=payload.recipient_id,
        mode=payload.mode,
        include_copy=payload.include_copy,
        include_image=payload.include_image,
        settings=request.app.state.settings,
    )
    response.headers["Location"] = f"/api/v1/wecom-deliveries/{job.id}"
    return _response(job)


@router.get("/wecom-deliveries/{delivery_id}", response_model=WeComDeliveryResponse)
async def read_wecom_delivery(
    delivery_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> WeComDeliveryResponse:
    job = await session.get(WeComDeliveryJobModel, delivery_id)
    if job is None:
        raise NotFoundError("WeCom delivery")
    return _response(job)


@router.get(
    "/wecom-deliveries/{delivery_id}/infographic",
    response_model=WeComInfographicStatusResponse,
)
async def read_wecom_infographic_status(
    delivery_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> WeComInfographicStatusResponse:
    """Expose only lineage, checksum, gate and outcome codes; no private assets."""
    base = await session.get(WeComDeliveryJobModel, delivery_id)
    if base is None:
        raise NotFoundError("WeCom delivery")
    poster = await session.scalar(
        select(NewsInfographicJobModel).where(NewsInfographicJobModel.base_job_id == delivery_id)
    )
    supplement = (
        await session.scalar(
            select(WeComInfographicSupplementModel).where(
                WeComInfographicSupplementModel.base_job_id == delivery_id
            )
        )
        if poster is not None
        else None
    )
    attempts = (
        (
            await session.scalars(
                select(WeComInfographicAttemptModel)
                .where(WeComInfographicAttemptModel.supplement_id == supplement.id)
                .order_by(WeComInfographicAttemptModel.attempt_number)
                .limit(20)
            )
        ).all()
        if supplement is not None
        else []
    )
    return WeComInfographicStatusResponse(
        base_job_id=base.id,
        base_status=cast(Any, base.status),
        infographic_job_id=poster.id if poster else None,
        infographic_status=poster.status if poster else None,
        infographic_safe_error_code=poster.safe_error_code if poster else None,
        quality_mode=cast(Any, poster.quality_mode) if poster else None,
        warning_codes=poster.warning_codes if poster else [],
        warning_notice_version=poster.warning_notice_version if poster else None,
        content_slot_selection_id=poster.content_slot_selection_id if poster else None,
        sequence_ordinal=poster.sequence_ordinal if poster else None,
        business_date=poster.business_date.isoformat() if poster else None,
        content_slot=poster.content_slot if poster else None,
        package_version=poster.package_version if poster else None,
        delivery_sha256=poster.delivery_sha256 if poster else None,
        delivery_byte_size=poster.delivery_byte_size if poster else None,
        delivery_width=poster.delivery_width if poster else None,
        delivery_height=poster.delivery_height if poster else None,
        ocr_status=poster.ocr_status if poster else None,
        footer_ocr_status=poster.footer_ocr_status if poster else None,
        visual_status=poster.visual_status if poster else None,
        supplement_id=supplement.id if supplement else None,
        supplement_status=supplement.status if supplement else None,
        supplement_safe_error_code=supplement.safe_error_code if supplement else None,
        supplement_attempt_count=supplement.attempt_count if supplement else 0,
        supplement_expires_at=supplement.expires_at if supplement else None,
        attempts=[
            WeComInfographicAttemptResponse(
                attempt_number=item.attempt_number,
                result_state=cast(Any, item.result_state),
                safe_response_code=item.safe_response_code,
                created_at=item.created_at,
            )
            for item in attempts
        ],
    )


@router.post("/wecom-deliveries/{delivery_id}/retry", response_model=WeComDeliveryResponse)
async def retry_wecom_delivery_route(
    delivery_id: UUID,
    request: Request,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> WeComDeliveryResponse:
    job = await retry_wecom_delivery(
        session=session,
        delivery_id=delivery_id,
        settings=request.app.state.settings,
    )
    return _response(job)


def _response(job: WeComDeliveryJobModel) -> WeComDeliveryResponse:
    return WeComDeliveryResponse(
        id=job.id,
        material_package_id=job.material_package_id,
        delivery_window_id=job.delivery_window_id,
        content_slot_selection_id=job.content_slot_selection_id,
        sequence_ordinal=job.sequence_ordinal,
        not_before=job.not_before,
        expires_at=job.expires_at,
        recipient_id=job.recipient_id,
        mode=cast(Any, job.mode),
        package_version=job.package_version,
        status=cast(Any, job.status),
        text_status=cast(Any, job.text_status),
        image_status=cast(Any, job.image_status),
        include_copy=job.include_copy,
        include_image=job.include_image,
        attempt_count=job.attempt_count,
        last_error_code=job.last_error_code,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
        retry_url=f"/api/v1/wecom-deliveries/{job.id}/retry",
    )
