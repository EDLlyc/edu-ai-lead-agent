"""Independent, fail-closed WeCom image supplement after a delivered base package."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, time, timedelta
from hashlib import sha256
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.ports.wecom import WeComDeliveryClient, WeComProviderError
from app.application.services.news_infographic_advisory import prepare_unmarked_advisory_raster
from app.application.services.news_infographic_footer import (
    is_delivery_geometry,
    render_delivery_footer_variants,
)
from app.core.config import Settings
from app.domain.news_infographic import InfographicInputError
from app.domain.value_objects import stable_key
from app.infrastructure.db.models import (
    ContentSlotSelectionModel,
    CopyGenerationRunModel,
    MaterialPackageModel,
    NewsInfographicJobModel,
    WeComDeliveryJobModel,
    WeComDeliveryWindowModel,
    WeComInfographicAttemptModel,
    WeComInfographicSupplementModel,
)
from app.infrastructure.storage.minio_image_store import MinioImageStore
from app.infrastructure.wecom.group_webhook import prepare_group_webhook_image

from .wecom_infographic_quality import (
    ADVISORY_NOTICE_VERSION,
    advisory_copy_warnings_match,
    advisory_gate_warnings_match,
)
from .wecom_news_infographic import _input_from_package, prepare_infographic_group_jpeg


def _day_end_utc(job: NewsInfographicJobModel, timezone: str) -> datetime:
    next_day = job.business_date + timedelta(days=1)
    return datetime.combine(next_day, time.min, tzinfo=ZoneInfo(timezone)).astimezone(UTC)


def _valid_ready_pair(
    poster: NewsInfographicJobModel,
    base: WeComDeliveryJobModel,
    window: WeComDeliveryWindowModel,
    *,
    settings: Settings,
) -> bool:
    quality_mode = poster.quality_mode or "strict"
    if quality_mode != settings.wecom_infographic_review_mode:
        return False
    if quality_mode == "strict":
        quality_ready = (
            poster.ocr_status == "passed"
            and poster.footer_ocr_status == "passed"
            and poster.visual_status == "passed"
        )
    else:
        # Review warnings may be advisory, but a known wrong source footer, missing image or
        # a poster not built under the current (unmarked) notice version is never sendable.
        quality_ready = bool(
            poster.warning_notice_version == ADVISORY_NOTICE_VERSION
            and advisory_gate_warnings_match(
                poster.warning_codes,
                body_ocr_status=poster.ocr_status,
                footer_ocr_status=poster.footer_ocr_status,
                visual_status=poster.visual_status,
            )
            and advisory_copy_warnings_match(
                poster.warning_codes,
                candidate=poster.copy_candidate_snapshot,
                audit=poster.copy_audit_snapshot,
                package_id=str(poster.material_package_id),
                input_fingerprint=poster.input_fingerprint,
            )
            and poster.image_intent_at is not None
            and poster.raw_sha256
            and poster.raw_byte_size
            and poster.raw_media_type in {"image/png", "image/jpeg"}
            and poster.composite_sha256
            and poster.composite_byte_size
            and poster.footer_sha256
            and poster.footer_byte_size
            and poster.policy_fingerprint
        )
    return bool(
        poster.status == "ready"
        and quality_ready
        and poster.delivery_sha256
        and poster.delivery_byte_size
        and poster.delivery_media_type == "image/jpeg"
        and poster.delivery_byte_size <= settings.wecom_group_max_image_bytes
        and is_delivery_geometry((poster.delivery_width, poster.delivery_height))
        and poster.base_job_id == base.id
        and poster.material_package_id == base.material_package_id
        and poster.package_version == base.package_version
        and poster.content_slot_selection_id == base.content_slot_selection_id
        and poster.sequence_ordinal == base.sequence_ordinal
        and poster.recipient_id == base.recipient_id == window.recipient_id == "default"
        and poster.provider == window.provider == "group_webhook"
        and poster.content_slot == window.content_slot
        and poster.business_date == window.business_date
        and base.mode == window.mode == "formal"
        and base.delivery_window_id == window.id
        and base.not_before == window.target_at
        and base.expires_at == window.expires_at
        and base.status == "delivered"
        and base.text_status == "delivered"
        and base.image_status == "delivered"
        and base.completed_at is not None
        and poster.sequence_ordinal <= settings.wecom_infographic_max_ordinal
        and {
            "morning": settings.wecom_infographic_morning_enabled,
            "noon": settings.wecom_infographic_noon_enabled,
            "evening": settings.wecom_infographic_evening_enabled,
        }.get(poster.content_slot, False)
    )


def _valid_source_lineage(
    poster: NewsInfographicJobModel,
    base: WeComDeliveryJobModel,
    window: WeComDeliveryWindowModel,
    package: MaterialPackageModel | None,
    run: CopyGenerationRunModel | None,
    selection: ContentSlotSelectionModel | None,
) -> bool:
    """Refuse a ready image whose duplicated event/run identity drifted."""
    typed_lineage_matches = bool(
        package is not None
        and run is not None
        and selection is not None
        and package.id == poster.material_package_id == base.material_package_id
        and package.package_version == poster.package_version == base.package_version
        and package.request_fingerprint == base.content_fingerprint
        and package.run_id == poster.copy_generation_run_id == run.id
        and run.content_slot_selection_id == poster.content_slot_selection_id == selection.id
        and selection.id == base.content_slot_selection_id
        and selection.ordinal == poster.sequence_ordinal == base.sequence_ordinal
        and selection.selected_event_id == poster.selected_event_id == run.selected_event_id
        and selection.selected_event_version_id
        == poster.selected_event_version_id
        == run.selected_event_version_id
        and selection.business_date
        == poster.business_date
        == run.business_date
        == window.business_date
        and selection.content_slot == poster.content_slot == window.content_slot
        and selection.timezone == run.timezone == window.timezone
    )
    if not typed_lineage_matches or package is None:
        return False
    try:
        return _input_from_package(package).fingerprint == poster.input_fingerprint
    except (InfographicInputError, ValidationError, TypeError, ValueError):
        return False


class WeComInfographicSupplementExecutor:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        client: WeComDeliveryClient,
        image_store: MinioImageStore,
        settings: Settings,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._sessions = session_factory
        self._client = client
        self._store = image_store
        self._settings = settings
        self._clock = clock

    async def reconcile(self, *, limit: int = 24) -> int:
        if not self._settings.wecom_infographic_delivery_enabled:
            return 0
        now = self._clock()
        today = now.astimezone(ZoneInfo(self._settings.business_timezone)).date()
        async with self._sessions() as session, session.begin():
            rows = (
                await session.execute(
                    select(NewsInfographicJobModel, WeComDeliveryJobModel, WeComDeliveryWindowModel)
                    .join(
                        WeComDeliveryJobModel,
                        NewsInfographicJobModel.base_job_id == WeComDeliveryJobModel.id,
                    )
                    .join(
                        WeComDeliveryWindowModel,
                        WeComDeliveryJobModel.delivery_window_id == WeComDeliveryWindowModel.id,
                    )
                    .where(
                        NewsInfographicJobModel.business_date == today,
                        NewsInfographicJobModel.status == "ready",
                        WeComDeliveryJobModel.status == "delivered",
                    )
                    .order_by(
                        WeComDeliveryJobModel.completed_at, NewsInfographicJobModel.sequence_ordinal
                    )
                    .limit(limit)
                )
            ).all()
            created = 0
            for poster, base, window in rows:
                if not _valid_ready_pair(poster, base, window, settings=self._settings):
                    continue
                package = await session.get(MaterialPackageModel, poster.material_package_id)
                run = await session.get(CopyGenerationRunModel, poster.copy_generation_run_id)
                selection = await session.get(
                    ContentSlotSelectionModel, poster.content_slot_selection_id
                )
                if not _valid_source_lineage(poster, base, window, package, run, selection):
                    continue
                assert base.completed_at is not None
                expires = min(
                    window.expires_at,
                    base.completed_at
                    + timedelta(minutes=self._settings.wecom_infographic_append_minutes),
                    _day_end_utc(poster, self._settings.business_timezone),
                )
                if expires <= now:
                    continue
                result = await session.execute(
                    insert(WeComInfographicSupplementModel)
                    .values(
                        id=uuid4(),
                        infographic_job_id=poster.id,
                        base_job_id=base.id,
                        status="queued",
                        next_attempt_at=now,
                        request_fingerprint=stable_key(
                            "wecom-infographic-image-v1",
                            base.id,
                            poster.id,
                            poster.delivery_sha256,
                            poster.policy_fingerprint,
                        ),
                        expires_at=expires,
                    )
                    .on_conflict_do_nothing()
                    .returning(WeComInfographicSupplementModel.id)
                )
                if result.scalar_one_or_none() is not None:
                    created += 1
            return created

    async def execute_next(self, worker_id: str) -> bool:
        if not self._settings.wecom_infographic_delivery_enabled:
            return False
        now = self._clock()
        token = uuid4()
        async with self._sessions() as session, session.begin():
            stale = (
                await session.scalars(
                    select(WeComInfographicSupplementModel)
                    .where(
                        WeComInfographicSupplementModel.status == "running",
                        WeComInfographicSupplementModel.lease_expires_at <= now,
                    )
                    .with_for_update(skip_locked=True)
                    .limit(24)
                )
            ).all()
            for old in stale:
                old.status = "result_unknown"
                old.safe_error_code = "supplement_lease_expired_after_send"
                old.completed_at = now
                old.lease_token = None
                old.lease_owner = None
                old.lease_expires_at = None
                session.add(
                    WeComInfographicAttemptModel(
                        id=uuid4(),
                        supplement_id=old.id,
                        attempt_number=max(1, old.attempt_count),
                        request_fingerprint=old.request_fingerprint,
                        result_state="unknown",
                        safe_response_code="supplement_lease_expired_after_send",
                    )
                )
            expired = (
                await session.scalars(
                    select(WeComInfographicSupplementModel)
                    .where(
                        WeComInfographicSupplementModel.status == "queued",
                        WeComInfographicSupplementModel.expires_at <= now,
                    )
                    .with_for_update(skip_locked=True)
                    .limit(24)
                )
            ).all()
            for old in expired:
                old.status = "expired"
                old.completed_at = now
            await session.flush()
            supplement = await session.scalar(
                select(WeComInfographicSupplementModel)
                .join(
                    WeComDeliveryJobModel,
                    WeComInfographicSupplementModel.base_job_id == WeComDeliveryJobModel.id,
                )
                .where(
                    WeComInfographicSupplementModel.status == "queued",
                    WeComInfographicSupplementModel.next_attempt_at <= now,
                    WeComInfographicSupplementModel.expires_at > now,
                )
                .order_by(
                    WeComDeliveryJobModel.completed_at, WeComDeliveryJobModel.sequence_ordinal
                )
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if supplement is None:
                return False
            supplement.status = "running"
            supplement.attempt_count += 1
            supplement.lease_owner = worker_id
            supplement.lease_token = token
            supplement.lease_expires_at = now + timedelta(
                seconds=self._settings.wecom_lease_seconds
            )
            supplement_id = supplement.id
        try:
            await self._send(supplement_id, token)
        except WeComProviderError as error:
            await self._record_failure(supplement_id, token, error)
        except Exception:
            # A failure after entering the provider boundary may be ambiguous.
            await self._record_unknown(supplement_id, token, "supplement_outcome_unknown")
        return True

    async def _send(self, supplement_id: UUID, token: UUID) -> None:
        async with self._sessions() as session:
            supplement = await session.get(WeComInfographicSupplementModel, supplement_id)
            poster = (
                await session.get(NewsInfographicJobModel, supplement.infographic_job_id)
                if supplement
                else None
            )
            base = (
                await session.get(WeComDeliveryJobModel, supplement.base_job_id)
                if supplement
                else None
            )
            window = (
                await session.get(WeComDeliveryWindowModel, base.delivery_window_id)
                if base and base.delivery_window_id
                else None
            )
            package = (
                await session.get(MaterialPackageModel, poster.material_package_id)
                if poster
                else None
            )
            run = (
                await session.get(CopyGenerationRunModel, poster.copy_generation_run_id)
                if poster
                else None
            )
            selection = (
                await session.get(ContentSlotSelectionModel, poster.content_slot_selection_id)
                if poster
                else None
            )
        if not supplement or not poster or not base or not window:
            await self._record_unknown(supplement_id, token, "supplement_lineage_missing")
            return
        if (
            not _valid_ready_pair(poster, base, window, settings=self._settings)
            or not _valid_source_lineage(poster, base, window, package, run, selection)
            or supplement.request_fingerprint
            != stable_key(
                "wecom-infographic-image-v1",
                base.id,
                poster.id,
                poster.delivery_sha256,
                poster.policy_fingerprint,
            )
            or base.completed_at is None
            or self._clock() >= supplement.expires_at
            or supplement.expires_at > window.expires_at
            or supplement.expires_at
            > base.completed_at + timedelta(minutes=self._settings.wecom_infographic_append_minutes)
            or supplement.expires_at > _day_end_utc(poster, self._settings.business_timezone)
        ):
            await self._record_unknown(supplement_id, token, "supplement_lineage_changed")
            return
        assert poster.delivery_sha256 and poster.delivery_byte_size and poster.delivery_media_type
        body = await self._store.get_content_addressed_bytes(
            media_type=poster.delivery_media_type,
            byte_size=poster.delivery_byte_size,
            sha256=poster.delivery_sha256,
        )
        if sha256(body).hexdigest() != poster.delivery_sha256:
            await self._record_unknown(supplement_id, token, "supplement_image_changed")
            return
        if poster.quality_mode == "advisory":
            # The relaxed OCR/visual verdicts never waive exact source and
            # visible warning pixels. Rebuild from frozen raw + package before
            # the only provider side effect, then demand byte-for-byte JPEG.
            assert package is not None
            assert poster.raw_sha256 and poster.raw_byte_size and poster.raw_media_type
            raw = await self._store.get_content_addressed_bytes(
                media_type=poster.raw_media_type,
                byte_size=poster.raw_byte_size,
                sha256=poster.raw_sha256,
            )
            if len(raw) != poster.raw_byte_size or sha256(raw).hexdigest() != poster.raw_sha256:
                await self._record_unknown(supplement_id, token, "supplement_raw_image_changed")
                return
            warned = prepare_unmarked_advisory_raster(raw)
            if (
                sha256(warned).hexdigest() != poster.composite_sha256
                or len(warned) != poster.composite_byte_size
            ):
                await self._record_unknown(supplement_id, token, "supplement_warning_changed")
                return
            footer = next(
                (
                    candidate
                    for candidate in render_delivery_footer_variants(
                        warned, _input_from_package(package), mode="formal"
                    )
                    if sha256(candidate.image_bytes).hexdigest() == poster.footer_sha256
                    and len(candidate.image_bytes) == poster.footer_byte_size
                ),
                None,
            )
            if footer is None or (
                prepare_infographic_group_jpeg(
                    footer.image_bytes, max_bytes=self._settings.wecom_group_max_image_bytes
                )
                != body
            ):
                await self._record_unknown(
                    supplement_id, token, "supplement_source_or_notice_changed"
                )
                return
        prepared = prepare_group_webhook_image(
            body,
            poster.delivery_media_type,
            max_bytes=self._settings.wecom_group_max_image_bytes,
            max_input_bytes=self._settings.wecom_max_image_bytes,
        )
        if prepared.body != body or prepared.media_type != poster.delivery_media_type:
            await self._record_unknown(supplement_id, token, "supplement_image_reencoded")
            return
        # Re-check durable fencing just before the only side effect. Expiry after this
        # boundary is an ambiguous provider result, not permission to resend.
        async with self._sessions() as session:
            claimed = await session.get(WeComInfographicSupplementModel, supplement_id)
            if (
                claimed is None
                or claimed.lease_token != token
                or claimed.status != "running"
                or claimed.lease_expires_at is None
                or claimed.lease_expires_at <= self._clock()
                or claimed.expires_at <= self._clock()
            ):
                return
        extension = "png" if poster.delivery_media_type == "image/png" else "jpg"
        result = await self._client.send_image_bytes(
            recipient_id="default",
            agent_id=self._settings.wecom_agent_id,
            image_bytes=body,
            media_type=poster.delivery_media_type,
            filename=f"xiaosai-news-{poster.material_package_id}.{extension}",
            request_fingerprint=supplement.request_fingerprint,
        )
        async with self._sessions() as session, session.begin():
            claimed = await session.get(
                WeComInfographicSupplementModel, supplement_id, with_for_update=True
            )
            if (
                claimed is None
                or claimed.lease_token != token
                or claimed.status != "running"
                or claimed.lease_expires_at is None
                or claimed.lease_expires_at <= self._clock()
            ):
                return
            session.add(
                WeComInfographicAttemptModel(
                    id=uuid4(),
                    supplement_id=supplement_id,
                    attempt_number=claimed.attempt_count,
                    request_fingerprint=claimed.request_fingerprint,
                    result_state="succeeded",
                    safe_response_code=getattr(result, "safe_response_code", None),
                    provider_request_id=getattr(result, "provider_request_id", None),
                )
            )
            claimed.status = "delivered"
            claimed.completed_at = self._clock()
            claimed.lease_token = None
            claimed.lease_owner = None
            claimed.lease_expires_at = None

    async def _record_unknown(self, supplement_id: UUID, token: UUID, code: str) -> None:
        await self._record_result(supplement_id, token, state="unknown", code=code)

    async def _record_failure(
        self, supplement_id: UUID, token: UUID, error: WeComProviderError
    ) -> None:
        await self._record_result(
            supplement_id,
            token,
            state="unknown" if error.unknown else "failed",
            code=error.code,
            retryable=error.retryable,
            provider_request_id=error.provider_request_id,
        )

    async def _record_result(
        self,
        supplement_id: UUID,
        token: UUID,
        *,
        state: str,
        code: str,
        retryable: bool = False,
        provider_request_id: str | None = None,
    ) -> None:
        now = self._clock()
        async with self._sessions() as session, session.begin():
            claimed = await session.get(
                WeComInfographicSupplementModel, supplement_id, with_for_update=True
            )
            if claimed is None or claimed.lease_token != token or claimed.status != "running":
                return
            if claimed.lease_expires_at is None or claimed.lease_expires_at <= now:
                # A confirmed provider rejection after the lease has elapsed is no
                # longer a safe automatic retry: another worker may have observed
                # the stale send boundary in the meantime.
                state = "unknown"
                code = "supplement_lease_expired_after_send"
                retryable = False
            session.add(
                WeComInfographicAttemptModel(
                    id=uuid4(),
                    supplement_id=supplement_id,
                    attempt_number=claimed.attempt_count,
                    request_fingerprint=claimed.request_fingerprint,
                    result_state=state,
                    safe_response_code=code,
                    provider_request_id=provider_request_id,
                )
            )
            if state == "unknown":
                claimed.status = "result_unknown"
            elif retryable and claimed.attempt_count < self._settings.wecom_max_attempts:
                delay = min(2**claimed.attempt_count, 30)
                next_at = now + timedelta(seconds=delay)
                claimed.status = "queued" if next_at < claimed.expires_at else "expired"
                claimed.next_attempt_at = next_at
            else:
                claimed.status = "failed"
            claimed.safe_error_code = code
            claimed.completed_at = now if claimed.status != "queued" else None
            claimed.lease_token = None
            claimed.lease_owner = None
            claimed.lease_expires_at = None
