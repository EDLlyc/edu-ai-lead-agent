"""Read-only 「朋友圈」 records for the exhibit: news → copy → image → WeCom → long image.

Starts from the newest formal WeCom deliveries that reached the group (fully or partly) and
reads the frozen material-package snapshots behind each one, so the exhibit shows exactly what
was sent. Image bytes are not read here; only content-addressed identities for signed refs.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.models import (
    ContentSlotRunModel,
    ContentSlotSelectionModel,
    CopyGenerationRunModel,
    ImageArtifactModel,
    MaterialPackageModel,
    NewsInfographicJobModel,
    WeComDeliveryAttemptModel,
    WeComDeliveryJobModel,
    WeComInfographicSupplementModel,
)

# A full day is at most nine scheduled posts plus human picks; keep the whole day listed.
MOMENT_LIMIT = 12
_SENT_STATUSES = ("delivered", "partial", "delivery_unknown")


@dataclass(frozen=True, slots=True)
class VisitorMomentImage:
    """A content-addressed image in the configured bucket, verified again when served."""

    kind: str  # "generated" | "long"
    row_id: UUID
    media_type: str
    byte_size: int
    sha256: str
    width: int | None
    height: int | None


@dataclass(frozen=True, slots=True)
class VisitorMomentRow:
    job_id: UUID
    event_id: UUID | None
    human_pick: bool
    topic: dict[str, Any]
    copy: dict[str, Any]
    sources: list[dict[str, Any]]
    brand: list[dict[str, Any]]
    validation: dict[str, Any]
    audit: dict[str, Any]
    copy_started_at: datetime | None
    copy_finished_at: datetime | None
    repair_count: int
    delivery_status: str
    text_sent_at: datetime | None
    image_sent_at: datetime | None
    delivered_at: datetime | None
    image: VisitorMomentImage | None
    long_image: VisitorMomentImage | None
    long_image_status: str | None
    long_image_sent_at: datetime | None
    business_date: date | None = None


async def load_moments(session: AsyncSession) -> tuple[VisitorMomentRow, ...]:
    rows = (
        await session.execute(
            select(
                WeComDeliveryJobModel,
                MaterialPackageModel,
                CopyGenerationRunModel,
                ContentSlotRunModel.trigger,
            )
            .join(
                MaterialPackageModel,
                MaterialPackageModel.id == WeComDeliveryJobModel.material_package_id,
            )
            .join(CopyGenerationRunModel, CopyGenerationRunModel.id == MaterialPackageModel.run_id)
            .outerjoin(
                ContentSlotSelectionModel,
                ContentSlotSelectionModel.id == CopyGenerationRunModel.content_slot_selection_id,
            )
            .outerjoin(
                ContentSlotRunModel, ContentSlotRunModel.id == ContentSlotSelectionModel.run_id
            )
            .where(
                WeComDeliveryJobModel.mode == "formal",
                WeComDeliveryJobModel.status.in_(_SENT_STATUSES),
                WeComDeliveryJobModel.include_copy.is_(True),
            )
            .order_by(
                WeComDeliveryJobModel.completed_at.desc().nulls_last(),
                WeComDeliveryJobModel.created_at.desc(),
            )
            .limit(MOMENT_LIMIT)
        )
    ).all()
    if not rows:
        return ()
    job_ids = [row[0].id for row in rows]
    artifact_ids = [row[1].image_artifact_id for row in rows]

    sent: dict[tuple[UUID, str], datetime] = {}
    for job_id, kind, created_at in (
        await session.execute(
            select(
                WeComDeliveryAttemptModel.job_id,
                WeComDeliveryAttemptModel.message_kind,
                WeComDeliveryAttemptModel.created_at,
            )
            .where(
                WeComDeliveryAttemptModel.job_id.in_(job_ids),
                WeComDeliveryAttemptModel.result_state == "succeeded",
            )
            .order_by(WeComDeliveryAttemptModel.created_at)
        )
    ).all():
        sent.setdefault((job_id, kind), created_at)

    artifacts = {
        artifact.id: artifact
        for artifact in await session.scalars(
            select(ImageArtifactModel).where(
                ImageArtifactModel.id.in_(artifact_ids),
                ImageArtifactModel.status == "succeeded",
            )
        )
    }
    infographics = {
        job.base_job_id: job
        for job in await session.scalars(
            select(NewsInfographicJobModel)
            .where(NewsInfographicJobModel.base_job_id.in_(job_ids))
            .order_by(NewsInfographicJobModel.created_at)
        )
    }
    supplements = {
        supplement.infographic_job_id: supplement
        for supplement in await session.scalars(
            select(WeComInfographicSupplementModel).where(
                WeComInfographicSupplementModel.infographic_job_id.in_(
                    [job.id for job in infographics.values()]
                )
            )
        )
    }

    moments: list[VisitorMomentRow] = []
    for job, package, copy_run, trigger in rows:
        artifact = artifacts.get(package.image_artifact_id)
        infographic = infographics.get(job.id)
        supplement = supplements.get(infographic.id) if infographic is not None else None
        moments.append(
            VisitorMomentRow(
                job_id=job.id,
                event_id=copy_run.selected_event_id,
                human_pick=trigger == "human",
                topic=_mapping(package.topic_snapshot),
                copy=_mapping(package.copy_snapshot),
                sources=_records(package.source_snapshot),
                brand=_records(package.brand_snapshot),
                validation=_mapping(package.validation_snapshot),
                audit=_mapping(package.audit_snapshot),
                copy_started_at=copy_run.created_at,
                copy_finished_at=copy_run.completed_at,
                repair_count=int(copy_run.repair_count or 0),
                delivery_status=job.status,
                text_sent_at=sent.get((job.id, "text")),
                image_sent_at=sent.get((job.id, "image")),
                delivered_at=job.completed_at,
                image=_generated_image(artifact),
                long_image=_long_image(infographic),
                long_image_status=infographic.status if infographic is not None else None,
                long_image_sent_at=(
                    supplement.completed_at
                    if supplement is not None and supplement.status == "delivered"
                    else None
                ),
                business_date=copy_run.business_date,
            )
        )
    return tuple(moments)


def _generated_image(artifact: ImageArtifactModel | None) -> VisitorMomentImage | None:
    if artifact is None or artifact.sha256 is None or artifact.byte_size is None:
        return None
    return VisitorMomentImage(
        kind="generated",
        row_id=artifact.id,
        media_type=str(artifact.media_type or ""),
        byte_size=int(artifact.byte_size),
        sha256=artifact.sha256,
        width=artifact.width,
        height=artifact.height,
    )


def _long_image(job: NewsInfographicJobModel | None) -> VisitorMomentImage | None:
    if (
        job is None
        or job.status != "ready"
        or job.delivery_sha256 is None
        or job.delivery_byte_size is None
        or job.delivery_media_type is None
    ):
        return None
    return VisitorMomentImage(
        kind="long",
        row_id=job.id,
        media_type=job.delivery_media_type,
        byte_size=int(job.delivery_byte_size),
        sha256=job.delivery_sha256,
        width=job.delivery_width,
        height=job.delivery_height,
    )


def _mapping(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


def _records(value: object) -> list[dict[str, Any]]:
    return (
        [dict(item) for item in value if isinstance(item, dict)] if isinstance(value, list) else []
    )


__all__ = ["MOMENT_LIMIT", "VisitorMomentImage", "VisitorMomentRow", "load_moments"]
