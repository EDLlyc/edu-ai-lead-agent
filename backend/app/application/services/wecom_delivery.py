from __future__ import annotations

import asyncio
import time
from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import and_, exists, func, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import aliased
from sqlalchemy.sql import Select

from app.application.ports.wecom import (
    WECOM_MIN_IMAGE_BYTES,
    WeComDeliveryClient,
    WeComProviderError,
)
from app.core.config import Settings
from app.core.errors import AppError, ConflictError, NotFoundError
from app.domain.image_generation import image_checksum, image_content_key
from app.domain.value_objects import stable_key
from app.infrastructure.db.models import (
    CopyGenerationRunModel,
    ImageArtifactModel,
    MaterialPackageModel,
    WeComDeliveryAttemptModel,
    WeComDeliveryJobModel,
)
from app.infrastructure.storage.minio_image_store import ImageObjectDescriptor, MinioImageStore

logger = structlog.get_logger()

_DELIVERED = "delivered"
_SKIPPED = "skipped"
_PENDING = "pending"
_RUNNING = "running"
_FAILED = "failed"
_UNKNOWN = "unknown"
_REVIEW_REQUIRED_PACKAGE_STATUSES = ("completed",)
_DIRECT_PACKAGE_STATUSES = ("awaiting_manual_use", "completed")
_AUTO_DELIVERY_SKIP_CACHE_SIZE = 1024


@dataclass(frozen=True, slots=True)
class ClaimedWeComDelivery:
    job_id: UUID
    package_id: UUID
    lease_token: UUID
    attempt_number: int
    recipient_id: str
    mode: str
    include_copy: bool
    include_image: bool


async def enqueue_wecom_delivery(
    *,
    session: AsyncSession,
    package_id: UUID,
    recipient_id: str,
    mode: str,
    include_copy: bool,
    include_image: bool,
    settings: Settings,
) -> WeComDeliveryJobModel:
    _ensure_delivery_configured(settings)
    if recipient_id != "default":
        raise ConflictError("recipient is not configured")
    if not include_copy and not include_image:
        raise ConflictError("at least one message kind must be selected")
    if mode not in {"test", "formal"}:
        raise ConflictError("unsupported WeCom delivery mode")

    package = await session.get(MaterialPackageModel, package_id)
    if package is None:
        raise NotFoundError("material package")
    if package.status not in _delivery_package_statuses(settings):
        raise ConflictError("material package is not ready for WeCom delivery")
    if package.review_status == "rejected":
        raise ConflictError("material package was rejected")
    if settings.wecom_require_review_before_send and package.review_status != "approved":
        raise ConflictError("material package must be approved before WeCom delivery")
    image = await session.get(ImageArtifactModel, package.image_artifact_id)
    if image is None:
        raise NotFoundError("image artifact")
    if include_image and image.status != "succeeded":
        raise ConflictError("material package image is not available")
    if not settings.wecom_require_review_before_send:
        _ensure_direct_delivery_quality(
            package=package,
            image=image,
            include_image=include_image,
            settings=settings,
        )

    content_fingerprint = package.request_fingerprint
    request_fingerprint = stable_key(
        _delivery_fingerprint_namespace(settings),
        package.id,
        recipient_id,
        mode,
        package.package_version,
        content_fingerprint,
        include_copy,
        include_image,
    )
    existing = await session.scalar(
        select(WeComDeliveryJobModel)
        .where(WeComDeliveryJobModel.request_fingerprint == request_fingerprint)
        .with_for_update()
    )
    if existing is not None:
        return existing

    job = WeComDeliveryJobModel(
        id=uuid4(),
        material_package_id=package.id,
        recipient_id=recipient_id,
        mode=mode,
        package_version=package.package_version,
        content_fingerprint=content_fingerprint,
        request_fingerprint=request_fingerprint,
        include_copy=include_copy,
        include_image=include_image,
        status="queued",
        text_status=_PENDING if include_copy else _SKIPPED,
        image_status=_PENDING if include_image else _SKIPPED,
        attempt_count=0,
        next_attempt_at=datetime.now(UTC),
    )
    session.add(job)
    try:
        await session.commit()
    except IntegrityError:
        await session.rollback()
        existing = cast(
            WeComDeliveryJobModel | None,
            await session.scalar(
                select(WeComDeliveryJobModel).where(
                    WeComDeliveryJobModel.request_fingerprint == request_fingerprint
                )
            ),
        )
        if existing is None:
            raise
        return existing
    await session.refresh(job)
    return job


async def retry_wecom_delivery(
    *, session: AsyncSession, delivery_id: UUID, settings: Settings
) -> WeComDeliveryJobModel:
    _ensure_delivery_configured(settings)
    job = await session.scalar(
        select(WeComDeliveryJobModel)
        .where(WeComDeliveryJobModel.id == delivery_id)
        .with_for_update()
    )
    if job is None:
        raise NotFoundError("WeCom delivery")
    if job.status not in {"failed", "partial", "delivery_unknown"}:
        raise ConflictError("only failed or unknown WeCom deliveries can be retried")

    if job.include_copy and job.text_status != _DELIVERED:
        job.text_status = _PENDING
    if job.include_image and job.image_status != _DELIVERED:
        job.image_status = _PENDING
    job.status = "queued"
    job.attempt_count = 0
    job.next_attempt_at = datetime.now(UTC)
    job.last_error_code = None
    job.lease_owner = None
    job.lease_token = None
    job.lease_expires_at = None
    job.heartbeat_at = None
    job.completed_at = None
    await session.commit()
    await session.refresh(job)
    return job


def build_wecom_text(package: MaterialPackageModel, *, mode: str, max_bytes: int) -> str:
    copy_snapshot = package.copy_snapshot if isinstance(package.copy_snapshot, dict) else {}
    copywriting = _safe_text(copy_snapshot.get("copywriting"))
    if not copywriting:
        raise ConflictError("material package copywriting is empty")
    prefix = "【测试消息】\n" if mode == "test" else ""
    content = f"{prefix}{copywriting}"
    encoded = content.encode("utf-8")
    if len(encoded) > max_bytes:
        raise ConflictError("material package copywriting exceeds WeCom text limit")
    return content


class WeComDeliveryExecutor:
    """Claim durable WeCom jobs and perform provider calls outside DB transactions."""

    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        client: WeComDeliveryClient,
        image_store: MinioImageStore,
        settings: Settings,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._session_factory = session_factory
        self._client = client
        self._image_store = image_store
        self._settings = settings
        self._clock = clock
        self._auto_delivery_skip_states: OrderedDict[str, tuple[str, ...]] = OrderedDict()

    async def reconcile_auto_deliveries(self, *, limit: int = 20) -> int:
        if not self._settings.wecom_auto_delivery_enabled:
            return 0
        business_date = self._clock().astimezone(ZoneInfo(self._settings.business_timezone)).date()
        async with self._session_factory() as session:
            packages = tuple(
                (
                    await session.scalars(
                        _auto_delivery_candidate_statement(
                            settings=self._settings,
                            business_date=business_date,
                            limit=limit,
                        )
                    )
                ).all()
            )
        created = 0
        for package in packages:
            async with self._session_factory() as session:
                try:
                    await enqueue_wecom_delivery(
                        session=session,
                        package_id=package.id,
                        recipient_id="default",
                        mode="formal",
                        include_copy=True,
                        include_image=True,
                        settings=self._settings,
                    )
                except (ConflictError, NotFoundError) as error:
                    self._log_auto_delivery_skip(package, error)
                else:
                    created += 1
        return created

    def _log_auto_delivery_skip(
        self, package: MaterialPackageModel, error: ConflictError | NotFoundError
    ) -> None:
        package_id = str(package.id)
        readiness_state = _auto_delivery_readiness_state(package)
        skip_state = (error.code, *readiness_state)
        if self._auto_delivery_skip_states.get(package_id) == skip_state:
            return
        self._auto_delivery_skip_states[package_id] = skip_state
        self._auto_delivery_skip_states.move_to_end(package_id)
        if len(self._auto_delivery_skip_states) > _AUTO_DELIVERY_SKIP_CACHE_SIZE:
            self._auto_delivery_skip_states.popitem(last=False)
        logger.info(
            "wecom_auto_delivery_skipped",
            package_id=package_id,
            error_code=error.code,
            readiness_state=stable_key("wecom-auto-readiness-v1", *readiness_state),
        )

    async def execute_next(self, worker_id: str) -> bool:
        claimed = await self._claim(worker_id)
        if claimed is None:
            return False
        stop = asyncio.Event()
        lease_lost = asyncio.Event()
        heartbeat = asyncio.create_task(self._heartbeat_loop(claimed, stop, lease_lost))
        try:
            self._ensure_lease(lease_lost)
            if claimed.include_copy and not await self._is_delivered(claimed, "text"):
                await self._deliver_text(claimed, lease_lost)
            self._ensure_lease(lease_lost)
            if claimed.include_image and not await self._is_delivered(claimed, "image"):
                await self._deliver_image(claimed, lease_lost)
            await self._finish_success(claimed)
        except asyncio.CancelledError:
            raise
        except WeComProviderError as error:
            await self._finish_provider_failure(claimed, error)
        except AppError as error:
            await self._finish_local_failure(claimed, error.code)
        except Exception:
            await self._finish_provider_failure(
                claimed,
                WeComProviderError("wecom_provider_unavailable", retryable=True),
            )
        finally:
            stop.set()
            await asyncio.gather(heartbeat, return_exceptions=True)
        return True

    async def _deliver_text(self, claimed: ClaimedWeComDelivery, lease_lost: asyncio.Event) -> None:
        async with self._session_factory() as session:
            package = await session.get(MaterialPackageModel, claimed.package_id)
        if package is None:
            raise NotFoundError("material package")
        content = build_wecom_text(
            package,
            mode=claimed.mode,
            max_bytes=wecom_text_limit(self._settings),
        )
        self._ensure_lease(lease_lost)
        request_fingerprint = _child_request_fingerprint(claimed.job_id, "text")
        started = time.monotonic()
        result = await self._client.send_text(
            recipient_id=wecom_delivery_recipient_id(self._settings),
            agent_id=self._settings.wecom_agent_id,
            content=content,
            request_fingerprint=request_fingerprint,
        )
        await self._record_child(
            claimed,
            message_kind="text",
            result_state="succeeded",
            safe_response_code=getattr(result, "safe_response_code", None),
            provider_request_id=getattr(result, "provider_request_id", None),
            latency_ms=_elapsed_ms(started),
        )

    async def _deliver_image(
        self, claimed: ClaimedWeComDelivery, lease_lost: asyncio.Event
    ) -> None:
        async with self._session_factory() as session:
            package = await session.get(MaterialPackageModel, claimed.package_id)
            if package is None:
                raise NotFoundError("material package")
            image = await session.get(ImageArtifactModel, package.image_artifact_id)
        if image is None or image.status != "succeeded":
            raise ConflictError("material package image is not available")
        descriptor = _image_descriptor(image=image, settings=self._settings)
        media_type = descriptor.media_type
        body = await self._image_store.get_bytes(descriptor)
        _validate_wecom_image_body(
            body,
            media_type=media_type,
            expected_size=descriptor.byte_size,
            expected_sha256=descriptor.sha256,
            max_bytes=self._settings.wecom_max_image_bytes,
        )
        self._ensure_lease(lease_lost)
        request_fingerprint = _child_request_fingerprint(claimed.job_id, "image")
        started = time.monotonic()
        result = await self._client.send_image_bytes(
            recipient_id=wecom_delivery_recipient_id(self._settings),
            agent_id=self._settings.wecom_agent_id,
            image_bytes=body,
            media_type=media_type,
            filename=(
                f"sai-xiansheng-{claimed.package_id}."
                f"{'png' if media_type == 'image/png' else 'jpg'}"
            ),
            request_fingerprint=request_fingerprint,
        )
        await self._record_child(
            claimed,
            message_kind="image",
            result_state="succeeded",
            safe_response_code=getattr(result, "safe_response_code", None),
            provider_request_id=getattr(result, "provider_request_id", None),
            latency_ms=_elapsed_ms(started),
        )

    async def _claim(self, worker_id: str) -> ClaimedWeComDelivery | None:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            job = await session.scalar(
                select(WeComDeliveryJobModel)
                .where(
                    or_(
                        and_(
                            WeComDeliveryJobModel.status == "queued",
                            WeComDeliveryJobModel.next_attempt_at <= now,
                        ),
                        and_(
                            WeComDeliveryJobModel.status == "running",
                            or_(
                                WeComDeliveryJobModel.lease_expires_at.is_(None),
                                WeComDeliveryJobModel.lease_expires_at <= now,
                            ),
                        ),
                    )
                )
                .order_by(WeComDeliveryJobModel.created_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
            if job is None:
                return None
            if job.attempt_count >= self._settings.wecom_max_attempts:
                job.status = "failed"
                job.last_error_code = "wecom_max_attempts_exhausted"
                job.completed_at = now
                _clear_lease(job)
                await session.commit()
                return None
            lease_token = uuid4()
            job.status = "running"
            job.attempt_count += 1
            job.lease_owner = worker_id
            job.lease_token = lease_token
            job.lease_expires_at = now + timedelta(seconds=self._settings.wecom_lease_seconds)
            job.heartbeat_at = now
            job.started_at = job.started_at or now
            job.last_error_code = None
            await session.commit()
            return ClaimedWeComDelivery(
                job_id=job.id,
                package_id=job.material_package_id,
                lease_token=lease_token,
                attempt_number=job.attempt_count,
                recipient_id=job.recipient_id,
                mode=job.mode,
                include_copy=job.include_copy,
                include_image=job.include_image,
            )

    async def _record_child(
        self,
        claimed: ClaimedWeComDelivery,
        *,
        message_kind: str,
        result_state: str,
        safe_response_code: str | None,
        provider_request_id: str | None,
        latency_ms: int,
    ) -> None:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            job = await session.scalar(
                select(WeComDeliveryJobModel)
                .where(
                    WeComDeliveryJobModel.id == claimed.job_id,
                    WeComDeliveryJobModel.lease_token == claimed.lease_token,
                    WeComDeliveryJobModel.status == "running",
                    WeComDeliveryJobModel.lease_expires_at >= now,
                )
                .with_for_update()
            )
            if job is None:
                raise ConflictError("WeCom delivery lease was lost")
            request_fingerprint = _child_request_fingerprint(claimed.job_id, message_kind)
            session.add(
                WeComDeliveryAttemptModel(
                    id=uuid4(),
                    job_id=job.id,
                    message_kind=message_kind,
                    attempt_number=claimed.attempt_number,
                    request_fingerprint=request_fingerprint,
                    provider_request_id=_bounded(provider_request_id, 200),
                    safe_response_code=_bounded(safe_response_code, 80),
                    result_state=result_state,
                    latency_ms=max(0, latency_ms),
                )
            )
            if message_kind == "text":
                job.text_status = _DELIVERED
            else:
                job.image_status = _DELIVERED
            await session.commit()

    async def _finish_success(self, claimed: ClaimedWeComDelivery) -> None:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            job = await session.scalar(
                select(WeComDeliveryJobModel)
                .where(
                    WeComDeliveryJobModel.id == claimed.job_id,
                    WeComDeliveryJobModel.lease_token == claimed.lease_token,
                )
                .with_for_update()
            )
            if job is None:
                return
            if job.text_status in {_DELIVERED, _SKIPPED} and job.image_status in {
                _DELIVERED,
                _SKIPPED,
            }:
                job.status = "delivered"
                job.completed_at = now
            else:
                job.status = "partial"
            _clear_lease(job)
            await session.commit()

    async def _finish_provider_failure(
        self, claimed: ClaimedWeComDelivery, error: WeComProviderError
    ) -> None:
        await self._finish_failure(
            claimed,
            error_code=error.code,
            retryable=bool(error.retryable),
            unknown=bool(error.unknown),
            provider_request_id=getattr(error, "provider_request_id", None),
            safe_response_code=_safe_provider_response_code(error),
        )

    async def _finish_local_failure(self, claimed: ClaimedWeComDelivery, error_code: str) -> None:
        await self._finish_failure(claimed, error_code=error_code, retryable=False, unknown=False)

    async def _finish_failure(
        self,
        claimed: ClaimedWeComDelivery,
        *,
        error_code: str,
        retryable: bool,
        unknown: bool,
        provider_request_id: str | None = None,
        safe_response_code: str | None = None,
    ) -> None:
        now = datetime.now(UTC)
        async with self._session_factory() as session:
            job = await session.scalar(
                select(WeComDeliveryJobModel)
                .where(
                    WeComDeliveryJobModel.id == claimed.job_id,
                    WeComDeliveryJobModel.lease_token == claimed.lease_token,
                )
                .with_for_update()
            )
            if job is None:
                return
            kind = _current_message_kind(job)
            if kind is not None:
                state = _UNKNOWN if unknown else _FAILED
                request_fingerprint = _child_request_fingerprint(job.id, kind)
                session.add(
                    WeComDeliveryAttemptModel(
                        id=uuid4(),
                        job_id=job.id,
                        message_kind=kind,
                        attempt_number=claimed.attempt_number,
                        request_fingerprint=request_fingerprint,
                        provider_request_id=_bounded(provider_request_id, 200),
                        safe_response_code=_bounded(safe_response_code or error_code, 80),
                        result_state="unknown" if unknown else "failed",
                        latency_ms=0,
                    )
                )
                if kind == "text":
                    job.text_status = state
                else:
                    job.image_status = state
            job.last_error_code = _bounded(error_code, 80)
            can_retry = (
                retryable and not unknown and job.attempt_count < self._settings.wecom_max_attempts
            )
            if unknown:
                job.status = "delivery_unknown"
                job.completed_at = now
            elif can_retry:
                job.status = "queued"
                job.next_attempt_at = now + timedelta(
                    seconds=min(30 * (2 ** max(0, job.attempt_count - 1)), 300)
                )
            else:
                job.status = "partial" if _has_delivered_child(job) else "failed"
                job.completed_at = now
            _clear_lease(job)
            await session.commit()

    async def _is_delivered(self, claimed: ClaimedWeComDelivery, kind: str) -> bool:
        async with self._session_factory() as session:
            job = await session.get(WeComDeliveryJobModel, claimed.job_id)
            if job is None:
                return False
            return (job.text_status if kind == "text" else job.image_status) == _DELIVERED

    async def _heartbeat_loop(
        self,
        claimed: ClaimedWeComDelivery,
        stop: asyncio.Event,
        lease_lost: asyncio.Event,
    ) -> None:
        while not stop.is_set():
            try:
                await asyncio.wait_for(stop.wait(), timeout=self._settings.wecom_heartbeat_seconds)
            except TimeoutError:
                now = datetime.now(UTC)
                try:
                    async with self._session_factory() as session:
                        result = cast(
                            CursorResult[object],
                            await session.execute(
                                update(WeComDeliveryJobModel)
                                .where(
                                    WeComDeliveryJobModel.id == claimed.job_id,
                                    WeComDeliveryJobModel.lease_token == claimed.lease_token,
                                    WeComDeliveryJobModel.status == "running",
                                    WeComDeliveryJobModel.lease_expires_at >= now,
                                )
                                .values(
                                    heartbeat_at=now,
                                    lease_expires_at=now
                                    + timedelta(seconds=self._settings.wecom_lease_seconds),
                                )
                            ),
                        )
                        if not result.rowcount:
                            await session.rollback()
                            lease_lost.set()
                            return
                        await session.commit()
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    logger.warning(
                        "wecom_delivery_heartbeat_failed",
                        delivery_id=str(claimed.job_id),
                        exception_type=type(error).__name__,
                    )
                    lease_lost.set()
                    return

    @staticmethod
    def _ensure_lease(lease_lost: asyncio.Event) -> None:
        if lease_lost.is_set():
            raise ConflictError("WeCom delivery lease was lost")


def _auto_delivery_candidate_statement(
    *, settings: Settings, business_date: date, limit: int
) -> Select[tuple[MaterialPackageModel]]:
    """Select only today's packages that can reach the enqueue guard on this poll.

    The enqueue service remains the race-safe authority.  This query only keeps durable jobs and
    deterministic direct-mode vetoes out of the two-second reconciliation loop.  The copy run's
    typed business date prevents old valid packages from being re-sent after a deployment.
    """

    delivered_package = aliased(MaterialPackageModel)
    delivered_run = aliased(CopyGenerationRunModel)
    formal_delivery_exists = (
        select(1)
        .select_from(WeComDeliveryJobModel)
        .join(
            delivered_package,
            delivered_package.id == WeComDeliveryJobModel.material_package_id,
        )
        .join(
            delivered_run,
            delivered_run.id == delivered_package.run_id,
        )
        .where(
            delivered_run.business_date == business_date,
            WeComDeliveryJobModel.mode == "formal",
        )
        .exists()
    )
    statement = (
        select(MaterialPackageModel)
        .join(
            CopyGenerationRunModel,
            CopyGenerationRunModel.id == MaterialPackageModel.run_id,
        )
        .where(
            CopyGenerationRunModel.business_date == business_date,
            MaterialPackageModel.status.in_(_delivery_package_statuses(settings)),
            ~exists().where(WeComDeliveryJobModel.material_package_id == MaterialPackageModel.id),
            ~formal_delivery_exists,
        )
    )
    if settings.wecom_require_review_before_send:
        return (
            statement.where(MaterialPackageModel.review_status == "approved")
            .order_by(MaterialPackageModel.created_at)
            .limit(limit)
        )

    image_sha256 = ImageArtifactModel.sha256
    expected_png_key = func.concat(
        "generated-images/sha256/",
        func.substr(image_sha256, 1, 2),
        "/",
        image_sha256,
        ".png",
    )
    expected_jpeg_key = func.concat(
        "generated-images/sha256/",
        func.substr(image_sha256, 1, 2),
        "/",
        image_sha256,
        ".jpg",
    )
    image_audit_ready = or_(
        ImageArtifactModel.audit_snapshot.contains({"configured": False}),
        and_(
            ImageArtifactModel.audit_snapshot.contains({"configured": True}),
            ImageArtifactModel.audit_snapshot.contains({"passed": True}),
        ),
    )
    statement = statement.join(
        ImageArtifactModel,
        ImageArtifactModel.id == MaterialPackageModel.image_artifact_id,
    ).where(
        MaterialPackageModel.review_status != "rejected",
        MaterialPackageModel.validation_snapshot.contains({"passed": True}),
        MaterialPackageModel.audit_snapshot.contains({"accepted": True}),
        ImageArtifactModel.status == "succeeded",
        ImageArtifactModel.validation_snapshot.contains({"configured": True}),
        ImageArtifactModel.validation_snapshot.contains({"passed": True}),
        image_audit_ready,
        ImageArtifactModel.bucket == settings.minio_bucket,
        ImageArtifactModel.media_type.in_(
            (
                "image/png",
                "image/jpeg",
            )
        ),
        ImageArtifactModel.byte_size >= WECOM_MIN_IMAGE_BYTES,
        ImageArtifactModel.byte_size <= settings.wecom_max_image_bytes,
        image_sha256.op("~")(r"^[0-9a-f]{64}$"),
        ImageArtifactModel.storage_metadata.contains(
            {"access": "private", "immutable": True, "content_addressed": True}
        ),
        or_(
            and_(
                ImageArtifactModel.media_type == "image/png",
                ImageArtifactModel.object_key == expected_png_key,
            ),
            and_(
                ImageArtifactModel.media_type == "image/jpeg",
                ImageArtifactModel.object_key == expected_jpeg_key,
            ),
        ),
    )
    return statement.order_by(MaterialPackageModel.created_at).limit(limit)


def _auto_delivery_readiness_state(package: MaterialPackageModel) -> tuple[str, ...]:
    """Return only bounded, non-content fields used to deduplicate race-skip logs."""

    return (
        _bounded_state_value(getattr(package, "status", None)),
        _bounded_state_value(getattr(package, "review_status", None)),
        _snapshot_state(getattr(package, "validation_snapshot", None), "passed"),
        _snapshot_state(getattr(package, "audit_snapshot", None), "accepted"),
        _bounded_state_value(getattr(package, "image_artifact_id", None)),
    )


def _snapshot_state(snapshot: object, field: str) -> str:
    if not isinstance(snapshot, dict) or field not in snapshot:
        return "missing"
    value = snapshot[field]
    if value is True:
        return "true"
    if value is False:
        return "false"
    return "other"


def _bounded_state_value(value: object) -> str:
    if value is None:
        return "missing"
    normalized = str(value).strip()
    return normalized[:80] if normalized else "empty"


def _ensure_delivery_configured(settings: Settings) -> None:
    if not settings.wecom_enabled:
        raise ConflictError("WeCom delivery is disabled")
    if settings.wecom_delivery_provider == "group_webhook":
        if settings.wecom_group_webhook_key is None:
            raise ConflictError("WeCom group webhook is not configured")
        return
    if not settings.wecom_default_recipient_id:
        raise ConflictError("WeCom default recipient is not configured")


def wecom_recipient_is_configured(settings: Settings) -> bool:
    """Return whether the safe logical default recipient can be exposed by the API."""

    if not settings.wecom_enabled:
        return False
    if settings.wecom_delivery_provider == "group_webhook":
        return settings.wecom_group_webhook_key is not None
    return bool(settings.wecom_default_recipient_id)


def wecom_delivery_recipient_id(settings: Settings) -> str:
    """Return the provider-facing recipient while keeping group mode logical-only."""

    if settings.wecom_delivery_provider == "group_webhook":
        return "default"
    return settings.wecom_default_recipient_id


def wecom_text_limit(settings: Settings) -> int:
    if settings.wecom_delivery_provider == "group_webhook":
        return settings.wecom_group_max_text_bytes
    return settings.wecom_max_text_bytes


def _delivery_fingerprint_namespace(settings: Settings) -> str:
    """Keep legacy self-built fingerprints while isolating the new provider route."""

    if settings.wecom_delivery_provider == "group_webhook":
        return "wecom-delivery-group-v1"
    return "wecom-delivery-v1"


def _delivery_package_statuses(settings: Settings) -> tuple[str, ...]:
    if settings.wecom_require_review_before_send:
        return _REVIEW_REQUIRED_PACKAGE_STATUSES
    return _DIRECT_PACKAGE_STATUSES


def _ensure_direct_delivery_quality(
    *,
    package: MaterialPackageModel,
    image: ImageArtifactModel,
    include_image: bool,
    settings: Settings,
) -> None:
    copy_validation = getattr(package, "validation_snapshot", None)
    if not isinstance(copy_validation, dict) or copy_validation.get("passed") is not True:
        raise ConflictError("material package copy validation has not passed")
    copy_audit = getattr(package, "audit_snapshot", None)
    if not isinstance(copy_audit, dict) or copy_audit.get("accepted") is not True:
        raise ConflictError("material package copy audit has not been accepted")
    if not include_image:
        return

    image_validation = getattr(image, "validation_snapshot", None)
    if (
        not isinstance(image_validation, dict)
        or image_validation.get("configured") is not True
        or image_validation.get("passed") is not True
    ):
        raise ConflictError("material package image validation has not passed")
    _image_descriptor(image=image, settings=settings)
    image_audit = getattr(image, "audit_snapshot", None)
    if not isinstance(image_audit, dict):
        raise ConflictError("material package image audit is unavailable")
    audit_configured = image_audit.get("configured")
    if not isinstance(audit_configured, bool):
        raise ConflictError("material package image audit is unavailable")
    if audit_configured and image_audit.get("passed") is not True:
        raise ConflictError("material package image audit has not been accepted")


def _image_descriptor(*, image: ImageArtifactModel, settings: Settings) -> ImageObjectDescriptor:
    values = {
        "bucket": getattr(image, "bucket", None),
        "object_key": getattr(image, "object_key", None),
        "media_type": getattr(image, "media_type", None),
        "byte_size": getattr(image, "byte_size", None),
        "sha256": getattr(image, "sha256", None),
    }
    if (
        any(
            not isinstance(value, str) or not value.strip()
            for field, value in values.items()
            if field in {"bucket", "object_key", "media_type", "sha256"}
        )
        or values["byte_size"] is None
    ):
        raise ConflictError("material package image metadata is incomplete")

    bucket = cast(str, values["bucket"])
    object_key = cast(str, values["object_key"])
    media_type = cast(str, values["media_type"])
    byte_size = values["byte_size"]
    sha256 = cast(str, values["sha256"])
    if media_type not in {"image/png", "image/jpeg"}:
        raise ConflictError("WeCom image upload supports only PNG or JPEG")
    if (
        isinstance(byte_size, bool)
        or not isinstance(byte_size, int)
        or byte_size < WECOM_MIN_IMAGE_BYTES
        or byte_size > settings.wecom_max_image_bytes
    ):
        raise ConflictError("material package image metadata has an invalid size")
    if len(sha256) != 64 or any(character not in "0123456789abcdef" for character in sha256):
        raise ConflictError("material package image metadata has an invalid checksum")
    if bucket != settings.minio_bucket or object_key != image_content_key(sha256, media_type):
        raise ConflictError("material package image metadata is not private and content-addressed")
    storage_metadata = getattr(image, "storage_metadata", None)
    if not isinstance(storage_metadata, dict) or any(
        not isinstance(storage_metadata.get(field), type(expected))
        or storage_metadata.get(field) != expected
        for field, expected in (
            ("access", "private"),
            ("immutable", True),
            ("content_addressed", True),
        )
    ):
        raise ConflictError("material package image storage metadata is invalid")
    return ImageObjectDescriptor(
        bucket=bucket,
        object_key=object_key,
        media_type=media_type,
        byte_size=byte_size,
        sha256=sha256,
    )


def _clear_lease(job: WeComDeliveryJobModel) -> None:
    job.lease_owner = None
    job.lease_token = None
    job.lease_expires_at = None
    job.heartbeat_at = None


def _current_message_kind(job: WeComDeliveryJobModel) -> str | None:
    if job.include_copy and job.text_status not in {_DELIVERED, _SKIPPED}:
        return "text"
    if job.include_image and job.image_status not in {_DELIVERED, _SKIPPED}:
        return "image"
    return None


def _has_delivered_child(job: WeComDeliveryJobModel) -> bool:
    return job.text_status == _DELIVERED or job.image_status == _DELIVERED


def _safe_text(value: object) -> str:
    return value.strip() if isinstance(value, str) else ""


def _bounded(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    normalized = value.strip()
    return normalized[:limit] if normalized else None


def _safe_provider_response_code(error: WeComProviderError) -> str:
    response_code = error.safe_response_code
    return str(response_code) if response_code is not None else error.code


def _elapsed_ms(started: float) -> int:
    return int(max(0.0, time.monotonic() - started) * 1000)


def _child_request_fingerprint(job_id: UUID, message_kind: str) -> str:
    """Keep the provider request identity stable across bounded retry attempts."""

    return stable_key("wecom-child-v1", job_id, message_kind)


def _validate_wecom_image_body(
    body: bytes,
    *,
    media_type: str,
    expected_size: int,
    expected_sha256: str,
    max_bytes: int,
) -> None:
    if len(body) != expected_size or len(body) < WECOM_MIN_IMAGE_BYTES or len(body) > max_bytes:
        raise ConflictError("material package image size does not match metadata")
    if image_checksum(body) != expected_sha256:
        raise ConflictError("material package image checksum does not match metadata")
    signature = {
        "image/png": b"\x89PNG\r\n\x1a\n",
        "image/jpeg": b"\xff\xd8\xff",
    }.get(media_type)
    if signature is None or not body.startswith(signature):
        raise ConflictError("material package image bytes do not match its media type")
