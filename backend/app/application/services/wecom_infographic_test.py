"""Explicit, one-shot triple test for one current-date formal news package.

This path owns its own durable intent/attempt rows. It never mutates the formal
base delivery, infographic job, or formal supplement. The CLI only prepares and
queues; the existing independent WeCom dispatcher owns all provider sends.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from hashlib import sha256
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.ports.wecom import WeComDeliveryClient, WeComProviderError
from app.application.services.news_infographic_advisory import prepare_unmarked_advisory_raster
from app.application.services.news_infographic_footer import (
    render_delivery_footer_variants,
    render_exact_source_footer,
    validate_exact_source_footer_layout,
)
from app.application.services.wecom_delivery import (
    _image_descriptor,
    _validate_wecom_image_body,
    build_wecom_text,
    wecom_text_limit,
)
from app.application.services.wecom_infographic_supplement import _valid_ready_pair
from app.application.services.wecom_news_infographic import (
    _assert_lineage,
    _input_from_package,
    prepare_infographic_group_jpeg,
)
from app.core.config import Settings
from app.core.errors import ConflictError, NotFoundError
from app.domain.news_infographic import ValidatedInfographicInput
from app.domain.value_objects import stable_key
from app.infrastructure.db.models import (
    ContentSlotSelectionModel,
    CopyGenerationRunModel,
    ImageArtifactModel,
    MaterialPackageModel,
    NewsInfographicJobModel,
    WeComDeliveryJobModel,
    WeComDeliveryWindowModel,
    WeComInfographicTestAttemptModel,
    WeComInfographicTestRunModel,
)
from app.infrastructure.storage.minio_image_store import MinioImageStore
from app.infrastructure.wecom.group_webhook import prepare_group_webhook_image

_POLICY = "wecom-infographic-visible-triple-test-v1"
_KINDS = ("text", "original", "infographic")


def fixed_group_fingerprint(settings: Settings) -> str:
    """A non-secret confirmation identifier for the one configured webhook key."""
    if (
        not settings.wecom_infographic_test_enabled
        or settings.wecom_delivery_provider != "group_webhook"
        or settings.wecom_group_webhook_key is None
    ):
        raise ConflictError("visible infographic test is not enabled for the fixed group")
    secret = settings.wecom_group_webhook_key.get_secret_value()
    if not secret:
        raise ConflictError("fixed group webhook is unavailable")
    return stable_key(_POLICY, "fixed-group", secret)


@dataclass(frozen=True)
class _Context:
    base: WeComDeliveryJobModel
    poster: NewsInfographicJobModel
    package: MaterialPackageModel
    image: ImageArtifactModel
    window: WeComDeliveryWindowModel
    case: ValidatedInfographicInput


async def _context(
    session: AsyncSession, base_id: UUID, *, settings: Settings, now: datetime
) -> _Context:
    base = await session.get(WeComDeliveryJobModel, base_id)
    if base is None:
        raise NotFoundError("formal WeCom delivery")
    poster = await session.scalar(
        select(NewsInfographicJobModel).where(NewsInfographicJobModel.base_job_id == base_id)
    )
    package = await session.get(MaterialPackageModel, base.material_package_id)
    run = await session.get(CopyGenerationRunModel, package.run_id) if package else None
    selection = (
        await session.get(ContentSlotSelectionModel, run.content_slot_selection_id)
        if run and run.content_slot_selection_id
        else None
    )
    window = (
        await session.get(WeComDeliveryWindowModel, base.delivery_window_id)
        if base.delivery_window_id
        else None
    )
    image = (
        await session.get(ImageArtifactModel, package.image_artifact_id)
        if package and package.image_artifact_id
        else None
    )
    if not all((poster, package, run, selection, window, image)):
        raise ConflictError("visible test requires complete formal news lineage")
    assert poster and package and run and selection and window and image
    case = _input_from_package(package)
    try:
        _assert_lineage(
            case=case,
            package=package,
            run=run,
            selection=selection,
            base=base,
            window=window,
            now=now,
            settings=settings,
        )
        validate_exact_source_footer_layout(case, mode="test")
    except (ValueError, TypeError) as exc:
        raise ConflictError("visible test formal news lineage is ineligible") from exc
    if (
        not _valid_ready_pair(poster, base, window, settings=settings)
        or poster.copy_generation_run_id != run.id
        or poster.selected_event_id != run.selected_event_id
        or poster.selected_event_version_id != run.selected_event_version_id
        or poster.business_date != run.business_date
        or poster.input_fingerprint != case.fingerprint
        or poster.raw_sha256 is None
        or poster.raw_byte_size is None
        or poster.raw_media_type not in {"image/png", "image/jpeg"}
        or image.status != "succeeded"
    ):
        raise ConflictError(
            "visible test requires one reviewed same-news poster and original image"
        )
    return _Context(base, poster, package, image, window, case)


def _test_expiry(context: _Context, *, settings: Settings, now: datetime) -> datetime:
    tomorrow = context.poster.business_date + timedelta(days=1)
    day_end = datetime.combine(
        tomorrow, time.min, tzinfo=ZoneInfo(settings.business_timezone)
    ).astimezone(UTC)
    expires = min(context.window.expires_at, day_end, now + timedelta(minutes=30))
    if expires <= now + timedelta(minutes=1):
        raise ConflictError("visible test window is too close to expiry")
    return expires


@dataclass(frozen=True)
class _Materials:
    text: str
    original_bytes: bytes
    original_media_type: str
    original_sha256: str
    original_delivery_sha256: str
    test_bytes: bytes
    formal_delivery_sha256: str


async def _materials(
    context: _Context, *, store: MinioImageStore, settings: Settings
) -> _Materials:
    poster = context.poster
    assert poster.raw_sha256 and poster.raw_byte_size and poster.raw_media_type
    raw = await store.get_content_addressed_bytes(
        media_type=poster.raw_media_type,
        byte_size=poster.raw_byte_size,
        sha256=poster.raw_sha256,
    )
    if len(raw) != poster.raw_byte_size or sha256(raw).hexdigest() != poster.raw_sha256:
        raise ConflictError("reviewed poster source checksum changed")
    # Formal and visible-test variants must carry the same deterministic
    # warning pixels. The test variant then gets its separate exact test footer.
    if poster.quality_mode == "advisory":
        notice_raster = prepare_unmarked_advisory_raster(raw)
        if poster.composite_sha256 != sha256(
            notice_raster
        ).hexdigest() or poster.composite_byte_size != len(notice_raster):
            raise ConflictError("advisory warning raster changed")
    else:
        notice_raster = raw
    formal_footer = render_exact_source_footer(notice_raster, context.case, mode="formal")
    if poster.quality_mode == "advisory":
        # Posters produced before footer-v6 still verify against their own footer version.
        matched = next(
            (
                candidate
                for candidate in render_delivery_footer_variants(
                    notice_raster, context.case, mode="formal"
                )
                if poster.footer_sha256 == sha256(candidate.image_bytes).hexdigest()
                and poster.footer_byte_size == len(candidate.image_bytes)
            ),
            None,
        )
        if matched is None:
            raise ConflictError("advisory formal footer changed")
        formal_footer = matched
    formal_body = prepare_infographic_group_jpeg(
        formal_footer.image_bytes, max_bytes=settings.wecom_group_max_image_bytes
    )
    if (
        poster.delivery_sha256 != sha256(formal_body).hexdigest()
        or poster.delivery_byte_size != len(formal_body)
        or poster.delivery_media_type != "image/jpeg"
    ):
        raise ConflictError("formal reviewed poster no longer matches its frozen source")
    reviewed_formal = await store.get_content_addressed_bytes(
        media_type="image/jpeg",
        byte_size=len(formal_body),
        sha256=poster.delivery_sha256,
    )
    if reviewed_formal != formal_body:
        raise ConflictError("formal reviewed poster bytes changed")
    footer = render_exact_source_footer(notice_raster, context.case, mode="test")
    test_body = prepare_infographic_group_jpeg(
        footer.image_bytes, max_bytes=settings.wecom_group_max_image_bytes
    )
    if not test_body or len(test_body) > settings.wecom_group_max_image_bytes:
        raise ConflictError("test poster exceeds fixed group image bound")
    test_prepared = prepare_group_webhook_image(
        test_body,
        "image/jpeg",
        max_bytes=settings.wecom_group_max_image_bytes,
        max_input_bytes=settings.wecom_max_image_bytes,
    )
    if test_prepared.body != test_body or test_prepared.media_type != "image/jpeg":
        raise ConflictError("test poster would be re-encoded after approval")
    descriptor = _image_descriptor(image=context.image, settings=settings)
    original = await store.get_bytes(descriptor)
    _validate_wecom_image_body(
        original,
        media_type=descriptor.media_type,
        expected_size=descriptor.byte_size,
        expected_sha256=descriptor.sha256,
        max_bytes=settings.wecom_max_image_bytes,
    )
    original_prepared = prepare_group_webhook_image(
        original,
        descriptor.media_type,
        max_bytes=settings.wecom_group_max_image_bytes,
        max_input_bytes=settings.wecom_max_image_bytes,
    )
    text = build_wecom_text(context.package, mode="test", max_bytes=wecom_text_limit(settings))
    if not text.startswith("【测试消息】\n"):
        raise ConflictError("visible test copy marker is missing")
    assert poster.delivery_sha256
    return _Materials(
        text=text,
        original_bytes=original,
        original_media_type=descriptor.media_type,
        original_sha256=descriptor.sha256,
        original_delivery_sha256=sha256(original_prepared.body).hexdigest(),
        test_bytes=test_body,
        formal_delivery_sha256=poster.delivery_sha256,
    )


class WeComInfographicVisibleTest:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        image_store: MinioImageStore,
        settings: Settings,
        client: WeComDeliveryClient | None = None,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._sessions = session_factory
        self._store = image_store
        self._settings = settings
        self._client = client
        self._clock = clock

    async def preflight(self, formal_base_job_id: UUID) -> dict[str, str | int]:
        target = fixed_group_fingerprint(self._settings)
        now = self._clock()
        async with self._sessions() as session:
            context = await _context(session, formal_base_job_id, settings=self._settings, now=now)
        _test_expiry(context, settings=self._settings, now=now)
        return {
            "formal_base_job_id": str(context.base.id),
            "infographic_job_id": str(context.poster.id),
            "material_package_id": str(context.package.id),
            "content_slot_selection_id": str(context.poster.content_slot_selection_id),
            "business_date": context.poster.business_date.isoformat(),
            "content_slot": context.poster.content_slot,
            "sequence_ordinal": context.poster.sequence_ordinal,
            "formal_delivery_sha256": context.poster.delivery_sha256 or "",
            "target_fingerprint": target,
        }

    async def prepare(
        self, formal_base_job_id: UUID, *, expected_target_fingerprint: str
    ) -> tuple[WeComInfographicTestRunModel, bytes]:
        target = fixed_group_fingerprint(self._settings)
        if expected_target_fingerprint != target:
            raise ConflictError("fixed group target fingerprint changed")
        now = self._clock()
        async with self._sessions() as session:
            context = await _context(session, formal_base_job_id, settings=self._settings, now=now)
        expires = _test_expiry(context, settings=self._settings, now=now)
        materials = await _materials(context, store=self._store, settings=self._settings)
        test_sha = sha256(materials.test_bytes).hexdigest()
        stored = await self._store.put_immutable(materials.test_bytes, media_type="image/jpeg")
        if (stored.sha256, stored.byte_size, stored.media_type) != (
            test_sha,
            len(materials.test_bytes),
            "image/jpeg",
        ):
            raise ConflictError("test poster storage descriptor changed")
        async with self._sessions() as session, session.begin():
            existing = await session.scalar(
                select(WeComInfographicTestRunModel).where(
                    WeComInfographicTestRunModel.formal_base_job_id == formal_base_job_id
                )
            )
            if existing is not None:
                if (
                    existing.target_fingerprint != target
                    or existing.test_artifact_sha256 != test_sha
                    or existing.infographic_job_id != context.poster.id
                ):
                    raise ConflictError("a different visible test is already reserved")
                return existing, materials.test_bytes
            run_id = uuid4()
            result = await session.execute(
                insert(WeComInfographicTestRunModel)
                .values(
                    id=run_id,
                    formal_base_job_id=context.base.id,
                    infographic_job_id=context.poster.id,
                    material_package_id=context.package.id,
                    content_slot_selection_id=context.poster.content_slot_selection_id,
                    sequence_ordinal=context.poster.sequence_ordinal,
                    business_date=context.poster.business_date,
                    content_slot=context.poster.content_slot,
                    package_version=context.package.package_version,
                    target_fingerprint=target,
                    formal_delivery_sha256=materials.formal_delivery_sha256,
                    test_artifact_sha256=test_sha,
                    test_artifact_byte_size=len(materials.test_bytes),
                    text_sha256=sha256(materials.text.encode("utf-8")).hexdigest(),
                    original_image_sha256=materials.original_sha256,
                    original_delivery_sha256=materials.original_delivery_sha256,
                    status="prepared",
                    text_status="pending",
                    original_status="pending",
                    infographic_status="pending",
                    expires_at=expires,
                )
                .on_conflict_do_nothing()
                .returning(WeComInfographicTestRunModel.id)
            )
            created_id = result.scalar_one_or_none()
            if created_id is None:
                raise ConflictError("visible test was reserved concurrently; inspect its status")
            run = await session.get(WeComInfographicTestRunModel, created_id)
            assert run is not None
            return run, materials.test_bytes

    async def enqueue(
        self,
        test_run_id: UUID,
        *,
        expected_target_fingerprint: str,
        approved_artifact_sha256: str,
    ) -> WeComInfographicTestRunModel:
        target = fixed_group_fingerprint(self._settings)
        now = self._clock()
        if expected_target_fingerprint != target:
            raise ConflictError("fixed group target fingerprint changed")
        async with self._sessions() as session:
            test = await session.get(WeComInfographicTestRunModel, test_run_id)
            if test is None:
                raise NotFoundError("visible infographic test")
            if test.status != "prepared" or test.approved_at is not None:
                raise ConflictError("visible test is not available for first approval")
            if (
                test.target_fingerprint != target
                or test.test_artifact_sha256 != approved_artifact_sha256
            ):
                raise ConflictError("approved test artifact or group target does not match")
            if now >= test.expires_at:
                raise ConflictError("visible test window has expired")
            context = await _context(
                session, test.formal_base_job_id, settings=self._settings, now=now
            )
        materials = await _materials(context, store=self._store, settings=self._settings)
        self._assert_materials(test, context, materials)
        stored = await self._store.get_content_addressed_bytes(
            media_type="image/jpeg",
            byte_size=test.test_artifact_byte_size,
            sha256=test.test_artifact_sha256,
        )
        if stored != materials.test_bytes:
            raise ConflictError("approved test poster bytes changed")
        async with self._sessions() as session, session.begin():
            locked = await session.get(
                WeComInfographicTestRunModel, test_run_id, with_for_update=True
            )
            if locked is None or locked.status != "prepared" or now >= locked.expires_at:
                raise ConflictError("visible test approval state changed")
            locked.status = "queued"
            locked.approved_at = now
            return locked

    @staticmethod
    def _assert_materials(
        test: WeComInfographicTestRunModel, context: _Context, materials: _Materials
    ) -> None:
        if (
            test.formal_base_job_id != context.base.id
            or test.infographic_job_id != context.poster.id
            or test.material_package_id != context.package.id
            or test.content_slot_selection_id != context.poster.content_slot_selection_id
            or test.sequence_ordinal != context.poster.sequence_ordinal
            or test.business_date != context.poster.business_date
            or test.content_slot != context.poster.content_slot
            or test.package_version != context.package.package_version
            or test.formal_delivery_sha256 != materials.formal_delivery_sha256
            or test.test_artifact_sha256 != sha256(materials.test_bytes).hexdigest()
            or test.test_artifact_byte_size != len(materials.test_bytes)
            or test.text_sha256 != sha256(materials.text.encode("utf-8")).hexdigest()
            or test.original_image_sha256 != materials.original_sha256
            or test.original_delivery_sha256 != materials.original_delivery_sha256
        ):
            raise ConflictError("visible test same-news material identity changed")

    async def status(self, test_run_id: UUID) -> dict[str, object]:
        async with self._sessions() as session:
            test = await session.get(WeComInfographicTestRunModel, test_run_id)
            if test is None:
                raise NotFoundError("visible infographic test")
            attempts = (
                await session.scalars(
                    select(WeComInfographicTestAttemptModel)
                    .where(WeComInfographicTestAttemptModel.test_run_id == test_run_id)
                    .order_by(WeComInfographicTestAttemptModel.created_at)
                )
            ).all()
            return {
                "test_run_id": str(test.id),
                "formal_base_job_id": str(test.formal_base_job_id),
                "infographic_job_id": str(test.infographic_job_id),
                "material_package_id": str(test.material_package_id),
                "content_slot_selection_id": str(test.content_slot_selection_id),
                "business_date": test.business_date.isoformat(),
                "content_slot": test.content_slot,
                "sequence_ordinal": test.sequence_ordinal,
                "package_version": test.package_version,
                "target_fingerprint": test.target_fingerprint,
                "test_artifact_sha256": test.test_artifact_sha256,
                "formal_delivery_sha256": test.formal_delivery_sha256,
                "original_delivery_sha256": test.original_delivery_sha256,
                "text_sha256": test.text_sha256,
                "status": test.status,
                "text_status": test.text_status,
                "original_status": test.original_status,
                "infographic_status": test.infographic_status,
                "safe_error_code": test.safe_error_code,
                "approved_at": test.approved_at.isoformat() if test.approved_at else None,
                "expires_at": test.expires_at.isoformat(),
                "completed_at": test.completed_at.isoformat() if test.completed_at else None,
                "attempts": [
                    {
                        "message_kind": item.message_kind,
                        "result_state": item.result_state,
                        "request_fingerprint": item.request_fingerprint,
                        "safe_response_code": item.safe_response_code,
                    }
                    for item in attempts
                ],
            }

    async def execute_next(self, worker_id: str) -> bool:
        if not self._settings.wecom_infographic_test_enabled or self._client is None:
            return False
        now = self._clock()
        token = uuid4()
        async with self._sessions() as session, session.begin():
            stale = (
                await session.scalars(
                    select(WeComInfographicTestRunModel)
                    .where(
                        WeComInfographicTestRunModel.status == "running",
                        or_(
                            WeComInfographicTestRunModel.lease_expires_at.is_(None),
                            WeComInfographicTestRunModel.lease_expires_at <= now,
                        ),
                    )
                    .with_for_update(skip_locked=True)
                    .limit(10)
                )
            ).all()
            for old in stale:
                old.status = "result_unknown"
                old.safe_error_code = "visible_test_lease_expired"
                old.completed_at = now
                old.lease_token = None
                old.lease_owner = None
                old.lease_expires_at = None
                for kind in _KINDS:
                    if getattr(old, f"{kind}_status") == "running":
                        setattr(old, f"{kind}_status", "unknown")
                        attempt = await session.scalar(
                            select(WeComInfographicTestAttemptModel).where(
                                WeComInfographicTestAttemptModel.test_run_id == old.id,
                                WeComInfographicTestAttemptModel.message_kind == kind,
                            )
                        )
                        if attempt is not None:
                            attempt.result_state = "unknown"
                            attempt.safe_response_code = "visible_test_lease_expired"
                            attempt.completed_at = now
            expired = (
                await session.scalars(
                    select(WeComInfographicTestRunModel)
                    .where(
                        WeComInfographicTestRunModel.status == "queued",
                        WeComInfographicTestRunModel.expires_at <= now,
                    )
                    .with_for_update(skip_locked=True)
                    .limit(10)
                )
            ).all()
            for old in expired:
                old.status = "expired"
                old.completed_at = now
            await session.flush()
            test = await session.scalar(
                select(WeComInfographicTestRunModel)
                .where(
                    WeComInfographicTestRunModel.status == "queued",
                    WeComInfographicTestRunModel.approved_at.is_not(None),
                    WeComInfographicTestRunModel.business_date
                    == now.astimezone(ZoneInfo(self._settings.business_timezone)).date(),
                    WeComInfographicTestRunModel.expires_at > now,
                )
                .order_by(WeComInfographicTestRunModel.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if test is None:
                return False
            test.status = "running"
            test.lease_token = token
            test.lease_owner = worker_id
            test.lease_expires_at = now + timedelta(minutes=10)
            test_id = test.id
        try:
            await self._send_sequence(test_id, token)
        except WeComProviderError as exc:
            await self._finish_error(test_id, token, exc.code, unknown=exc.unknown)
        except Exception:
            await self._finish_error(test_id, token, "visible_test_outcome_unknown", unknown=True)
        return True

    async def _send_sequence(self, test_id: UUID, token: UUID) -> None:
        assert self._client is not None
        now = self._clock()
        target = fixed_group_fingerprint(self._settings)
        async with self._sessions() as session:
            test = await session.get(WeComInfographicTestRunModel, test_id)
            if test is None or test.target_fingerprint != target or now >= test.expires_at:
                raise ConflictError("visible test target or window changed")
            context = await _context(
                session, test.formal_base_job_id, settings=self._settings, now=now
            )
        materials = await _materials(context, store=self._store, settings=self._settings)
        self._assert_materials(test, context, materials)
        delivered = await self._store.get_content_addressed_bytes(
            media_type="image/jpeg",
            byte_size=test.test_artifact_byte_size,
            sha256=test.test_artifact_sha256,
        )
        if delivered != materials.test_bytes:
            raise ConflictError("visible test approved image changed")
        for kind in _KINDS:
            fingerprint = stable_key(
                _POLICY,
                test.id,
                kind,
                test.target_fingerprint,
                {
                    "text": test.text_sha256,
                    "original": test.original_delivery_sha256,
                    "infographic": test.test_artifact_sha256,
                }[kind],
            )
            if not await self._intent(test_id, token, kind, fingerprint):
                raise ConflictError("visible test send intent is unavailable")
            if kind == "text":
                result = await self._client.send_text(
                    recipient_id="default",
                    agent_id=self._settings.wecom_agent_id,
                    content=materials.text,
                    request_fingerprint=fingerprint,
                )
            else:
                extension = (
                    "png"
                    if kind == "original" and materials.original_media_type == "image/png"
                    else "jpg"
                )
                result = await self._client.send_image_bytes(
                    recipient_id="default",
                    agent_id=self._settings.wecom_agent_id,
                    image_bytes=(materials.original_bytes if kind == "original" else delivered),
                    media_type=(
                        materials.original_media_type if kind == "original" else "image/jpeg"
                    ),
                    filename=f"xiaosai-visible-test-{test.id}-{kind}.{extension}",
                    request_fingerprint=fingerprint,
                )
            if not await self._record_success(test_id, token, kind, result):
                return
        async with self._sessions() as session, session.begin():
            test = await session.get(WeComInfographicTestRunModel, test_id, with_for_update=True)
            if test is None or test.lease_token != token or test.status != "running":
                return
            if all(getattr(test, f"{kind}_status") == "delivered" for kind in _KINDS):
                test.status = "delivered"
                test.completed_at = self._clock()
                test.lease_token = None
                test.lease_owner = None
                test.lease_expires_at = None

    async def _intent(self, test_id: UUID, token: UUID, kind: str, fingerprint: str) -> bool:
        now = self._clock()
        async with self._sessions() as session, session.begin():
            test = await session.get(WeComInfographicTestRunModel, test_id, with_for_update=True)
            if (
                test is None
                or test.status != "running"
                or test.lease_token != token
                or test.lease_expires_at is None
                or test.lease_expires_at <= now
                or test.expires_at <= now
                or test.target_fingerprint != fixed_group_fingerprint(self._settings)
                or getattr(test, f"{kind}_status") != "pending"
            ):
                return False
            previous = _KINDS[: _KINDS.index(kind)]
            if any(getattr(test, f"{prior}_status") != "delivered" for prior in previous):
                return False
            base = await session.get(WeComDeliveryJobModel, test.formal_base_job_id)
            poster = await session.get(NewsInfographicJobModel, test.infographic_job_id)
            window = (
                await session.get(WeComDeliveryWindowModel, base.delivery_window_id)
                if base and base.delivery_window_id
                else None
            )
            if (
                base is None
                or poster is None
                or window is None
                or not _valid_ready_pair(poster, base, window, settings=self._settings)
                or now >= window.expires_at
                or poster.delivery_sha256 != test.formal_delivery_sha256
            ):
                return False
            session.add(
                WeComInfographicTestAttemptModel(
                    id=uuid4(),
                    test_run_id=test_id,
                    message_kind=kind,
                    request_fingerprint=fingerprint,
                    result_state="intent",
                )
            )
            setattr(test, f"{kind}_status", "running")
            return True

    async def _record_success(self, test_id: UUID, token: UUID, kind: str, result: object) -> bool:
        async with self._sessions() as session, session.begin():
            test = await session.get(WeComInfographicTestRunModel, test_id, with_for_update=True)
            if test is None or test.lease_token != token or test.status != "running":
                return False
            attempt = await session.scalar(
                select(WeComInfographicTestAttemptModel).where(
                    WeComInfographicTestAttemptModel.test_run_id == test_id,
                    WeComInfographicTestAttemptModel.message_kind == kind,
                )
            )
            if attempt is None or attempt.result_state != "intent":
                return False
            attempt.result_state = "succeeded"
            code = getattr(result, "safe_response_code", None)
            attempt.safe_response_code = str(code)[:80] if code is not None else None
            request_id = getattr(result, "provider_request_id", None)
            attempt.provider_request_id = str(request_id)[:200] if request_id is not None else None
            attempt.completed_at = self._clock()
            setattr(test, f"{kind}_status", "delivered")
            return True

    async def _finish_error(self, test_id: UUID, token: UUID, code: str, *, unknown: bool) -> None:
        now = self._clock()
        async with self._sessions() as session, session.begin():
            test = await session.get(WeComInfographicTestRunModel, test_id, with_for_update=True)
            if test is None or test.lease_token != token or test.status != "running":
                return
            for kind in _KINDS:
                if getattr(test, f"{kind}_status") != "running":
                    continue
                setattr(test, f"{kind}_status", "unknown" if unknown else "failed")
                attempt = await session.scalar(
                    select(WeComInfographicTestAttemptModel).where(
                        WeComInfographicTestAttemptModel.test_run_id == test_id,
                        WeComInfographicTestAttemptModel.message_kind == kind,
                    )
                )
                if attempt is not None and attempt.result_state == "intent":
                    attempt.result_state = "unknown" if unknown else "failed"
                    attempt.safe_response_code = code[:80]
                    attempt.completed_at = now
                break
            test.status = "result_unknown" if unknown else "failed"
            test.safe_error_code = code[:80]
            test.completed_at = now
            test.lease_token = None
            test.lease_owner = None
            test.lease_expires_at = None
