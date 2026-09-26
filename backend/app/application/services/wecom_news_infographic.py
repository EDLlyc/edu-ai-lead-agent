"""Default-off, per-package portrait generation for formal WeCom slot jobs.

The original text/image dispatcher does not wait for or derive success from this worker.
Every paid stage has a committed intent. An interrupted running job is unknown and is
never automatically restarted, even if the image POST was only possibly dispatched.
"""

# ruff: noqa: RUF001 -- Exact Chinese footer labels are part of the OCR contract.

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Protocol
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

from PIL import Image
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.ports.image_generation import (
    ImageGenerationRequest,
    ImageReference,
    validate_image_generation_request_prompt,
)
from app.application.ports.image_validation import (
    ImageQualityAuditRequest,
    ImageTextRecognitionResult,
    PosterRegionRecognitionRequest,
)
from app.application.services.news_infographic import (
    COPY_VERSION,
    EVIDENCE_FIRST_COPY_VERSION,
    GEOMETRY,
    PROMPT_VERSION,
    QUALITY_VERSION,
    CopyVerdict,
    InfographicModels,
    PosterCopy,
    _validate_raster,
    build_copy_audit_prompt,
    build_evidence_first_copy,
    build_image_prompt,
    validate_poster_copy,
)
from app.application.services.news_infographic_advisory import (
    ADVISORY_AUDIT_VERSION,
    ADVISORY_COPY_VERSION,
    ADVISORY_GENERATION_PROMPT_VERSION,
    ADVISORY_IMAGE_PROMPT_VERSION,
    ADVISORY_POLICY_VERSION,
    AdvisoryCopyError,
    advisory_notice_font_sha256,
    build_advisory_audit_prompt,
    build_advisory_generation_prompt,
    build_advisory_image_prompt,
    build_advisory_rich_copy,
    render_advisory_notice,
)
from app.application.services.news_infographic_footer import (
    DELIVERY_FOOTER_VERSION,
    FOOTER_TOP,
    FooterRenderError,
    footer_font_sha256,
    render_exact_source_footer,
    validate_exact_source_footer_layout,
)
from app.application.services.news_infographic_rich_copy import (
    MOMENTS_AUDIT_PROMPT_VERSION,
    MOMENTS_AUDIT_VERSION,
    MOMENTS_LAYOUT_VERSION,
    MOMENTS_PROPOSAL_VERSION,
    MOMENTS_SEED_VERSION,
    MomentsAuditVerdict,
    MomentsPackageBinding,
    RichCopyError,
    build_moments_rich_seed,
)
from app.application.services.news_infographic_text_overlay import (
    OVERLAY_VERSION,
    TextOverlayError,
    preflight_text_overlay_layout,
    render_exact_text_overlay,
    text_overlay_font_sha256,
)
from app.application.services.wecom_infographic_quality import (
    ADVISORY_NOTICE_VERSION,
    normalize_advisory_warnings,
)
from app.core.config import Settings
from app.domain.news_infographic import (
    InfographicInputError,
    ValidatedInfographicInput,
    validate_package_snapshot,
)
from app.domain.value_objects import stable_key
from app.infrastructure.db.models import (
    ContentSlotSelectionModel,
    CopyDraftVersionModel,
    CopyGenerationRunModel,
    MaterialPackageModel,
    NewsInfographicJobModel,
    WeComDeliveryJobModel,
    WeComDeliveryWindowModel,
)
from app.infrastructure.storage.minio_image_store import MinioImageStore
from app.infrastructure.wecom.group_webhook import prepare_group_webhook_image

POLICY_VERSION = "wecom-news-infographic-v8-evidence-first-copy"
_OVERLAY_PROMPT_VERSION = "daily-news-infographic-overlay-prompt-v2-evidence-first-scene"
_POSTER_OCR_VERSION = "poster-region-ocr-v1"
_POSTER_VISUAL_RUBRIC_VERSION = "wecom-news-poster-visual-v2-evidence-first"
_APP_ROOT = Path(__file__).resolve().parents[3]
_REFERENCE_ROOT = _APP_ROOT.parent if _APP_ROOT.name == "backend" else _APP_ROOT
_REFERENCE_PATH = (
    _REFERENCE_ROOT / "private/brand-materials/05-visual-assets/赛先生小赛-携手奔跑.png"
)
_APPROVED_CHARACTER_SHA256 = "471bf408e572a3e0a45ff801a831ba48f135616eceaf995d7413b4f910038623"


def _policy_fingerprint(image_model: str, audit_model: str, *, quality_mode: str = "strict") -> str:
    if quality_mode == "advisory":
        return stable_key(
            ADVISORY_POLICY_VERSION,
            ADVISORY_COPY_VERSION,
            ADVISORY_GENERATION_PROMPT_VERSION,
            MOMENTS_SEED_VERSION,
            MOMENTS_PROPOSAL_VERSION,
            MOMENTS_AUDIT_VERSION,
            MOMENTS_AUDIT_PROMPT_VERSION,
            MOMENTS_LAYOUT_VERSION,
            ADVISORY_AUDIT_VERSION,
            ADVISORY_IMAGE_PROMPT_VERSION,
            ADVISORY_NOTICE_VERSION,
            advisory_notice_font_sha256(),
            DELIVERY_FOOTER_VERSION,
            footer_font_sha256(),
            image_model,
            audit_model,
            "formal-advisory",
        )
    if quality_mode != "strict":
        raise ValueError("unsupported infographic quality mode")
    return stable_key(
        POLICY_VERSION,
        COPY_VERSION,
        EVIDENCE_FIRST_COPY_VERSION,
        PROMPT_VERSION,
        _OVERLAY_PROMPT_VERSION,
        OVERLAY_VERSION,
        _POSTER_OCR_VERSION,
        _POSTER_VISUAL_RUBRIC_VERSION,
        QUALITY_VERSION,
        "generic-line-layout",
        text_overlay_font_sha256(),
        DELIVERY_FOOTER_VERSION,
        footer_font_sha256(),
        image_model,
        audit_model,
        "formal",
    )


def _enabled_slot(settings: Settings, slot: str) -> bool:
    return {
        "morning": settings.wecom_infographic_morning_enabled,
        "noon": settings.wecom_infographic_noon_enabled,
        "evening": settings.wecom_infographic_evening_enabled,
    }.get(slot, False)


def _input_from_package(package: MaterialPackageModel) -> ValidatedInfographicInput:
    """Validate the same snapshots as the local trial, without a loopback HTTP call."""
    return validate_package_snapshot(
        {
            "id": str(package.id),
            "copy_generation_run_id": str(package.run_id),
            "package_version": package.package_version,
            "status": package.status,
            "review_status": package.review_status,
            "topic": package.topic_snapshot,
            "copy": package.copy_snapshot,
            "sources": package.source_snapshot,
            "brand_bindings": package.brand_snapshot,
            "validation": package.validation_snapshot,
            "audit": package.audit_snapshot,
        },
        expected_package_id=package.id,
    )


def _moments_binding_from_accepted_models(
    *,
    case: ValidatedInfographicInput,
    package: MaterialPackageModel,
    run: CopyGenerationRunModel,
    active_draft: CopyDraftVersionModel,
) -> MomentsPackageBinding:
    """Bind the future rich route to its actual active draft, not latest-by-date prose."""
    copy = package.copy_snapshot
    validation = package.validation_snapshot
    audit = package.audit_snapshot
    if (
        not isinstance(copy, dict)
        or not isinstance(validation, dict)
        or not isinstance(audit, dict)
    ):
        raise InfographicInputError("accepted Moments snapshots are invalid")
    if (
        run.id != case.copy_generation_run_id
        or run.active_draft_version_id != case.draft_version_id
        or active_draft.id != run.active_draft_version_id
        or active_draft.run_id != run.id
        or active_draft.version != case.draft_version
        or active_draft.copywriting != case.copywriting
        or active_draft.parent_takeaway != copy.get("parent_takeaway")
        or active_draft.interaction != copy.get("interaction")
        or active_draft.source_note != copy.get("source_note")
        or not active_draft.validation_passed
        or active_draft.audit_accepted is not True
    ):
        raise InfographicInputError("accepted Moments draft differs from material package")
    try:
        binding = MomentsPackageBinding.model_validate(
            {
                "package_id": case.package_id,
                "copy_generation_run_id": case.copy_generation_run_id,
                "package_version": case.package_version,
                "selected_event_id": case.selected_event_id,
                "selected_event_version_id": case.selected_event_version_id,
                "business_date": case.business_date,
                "active_draft_version_id": active_draft.id,
                "source_name": case.source_name,
                "source_url": case.source_url,
                "source_published_at": case.source_published_at,
                "validation_passed": validation.get("passed"),
                "audit_accepted": audit.get("accepted"),
                "validation_fingerprint": validation.get("result_fingerprint"),
                "audit_fingerprint": audit.get("result_fingerprint"),
                "copy_snapshot": copy,
            }
        )
        build_moments_rich_seed(case, binding)
    except (ValidationError, RichCopyError, ValueError, TypeError) as exc:
        raise InfographicInputError("accepted Moments binding is invalid") from exc
    return binding


def _assert_lineage(
    *,
    case: ValidatedInfographicInput,
    package: MaterialPackageModel,
    run: CopyGenerationRunModel,
    selection: ContentSlotSelectionModel,
    base: WeComDeliveryJobModel,
    window: WeComDeliveryWindowModel,
    now: datetime,
    settings: Settings,
) -> None:
    if (
        base.mode != "formal"
        or base.recipient_id != "default"
        or not base.include_copy
        or not base.include_image
        or base.status not in {"queued", "running", "delivered"}
        or base.material_package_id != package.id
        or base.package_version != package.package_version
        or base.content_fingerprint != package.request_fingerprint
        or base.content_slot_selection_id != selection.id
        or base.sequence_ordinal != selection.ordinal
        or base.delivery_window_id != window.id
        or base.not_before != window.target_at
        or base.expires_at != window.expires_at
        or window.provider != "group_webhook"
        or window.recipient_id != base.recipient_id
        or window.mode != base.mode
        or window.content_slot != selection.content_slot
        or window.business_date != selection.business_date
        or window.timezone != selection.timezone
        or run.id != package.run_id
        or run.content_slot_selection_id != selection.id
        or run.business_date != selection.business_date
        or run.timezone != selection.timezone
        or run.selected_event_id != selection.selected_event_id
        or run.selected_event_version_id != selection.selected_event_version_id
        or case.package_id != package.id
        or case.copy_generation_run_id != run.id
        or case.package_version != package.package_version
        or case.business_date != run.business_date
        or case.selected_event_id != run.selected_event_id
        or case.selected_event_version_id != run.selected_event_version_id
        or selection.business_date != now.astimezone(ZoneInfo(settings.business_timezone)).date()
        or selection.ordinal > settings.wecom_infographic_max_ordinal
        or not _enabled_slot(settings, selection.content_slot)
        or window.expires_at <= now
    ):
        raise InfographicInputError("slot infographic lineage is ineligible or inconsistent")


def _assert_job_lineage(
    *,
    job: NewsInfographicJobModel,
    package: MaterialPackageModel,
    run: CopyGenerationRunModel,
    selection: ContentSlotSelectionModel,
    base: WeComDeliveryJobModel,
    window: WeComDeliveryWindowModel,
) -> None:
    """Refuse a drifted durable reservation before any paid provider intent."""
    if (
        job.base_job_id != base.id
        or job.material_package_id != package.id
        or job.copy_generation_run_id != run.id
        or job.content_slot_selection_id != selection.id
        or job.sequence_ordinal != selection.ordinal
        or job.selected_event_id != selection.selected_event_id
        or job.selected_event_version_id != selection.selected_event_version_id
        or job.business_date != selection.business_date
        or job.content_slot != selection.content_slot
        or job.recipient_id != base.recipient_id
        or job.provider != window.provider
        or job.package_version != package.package_version
    ):
        raise InfographicInputError("reserved infographic lineage changed")


def _approved_reference(*, asset_root: Path | None = None) -> tuple[ImageReference, ...]:
    if asset_root is not None and (asset_root.is_symlink() or not asset_root.is_dir()):
        raise InfographicInputError("approved character reference root is unavailable")
    path = (
        _REFERENCE_PATH
        if asset_root is None
        else asset_root / _REFERENCE_PATH.relative_to(_REFERENCE_ROOT)
    )
    if path.is_symlink() or not path.is_file():
        raise InfographicInputError("approved character reference is unavailable")
    try:
        body = path.read_bytes()
    except OSError as exc:
        raise InfographicInputError("approved character reference cannot be read") from exc
    digest = sha256(body).hexdigest()
    if (
        not 6 <= len(body) <= 4 * 1024 * 1024
        or not body.startswith(b"\x89PNG\r\n\x1a\n")
        or digest != _APPROVED_CHARACTER_SHA256
    ):
        raise InfographicInputError("approved character reference is invalid")
    return (
        ImageReference(
            role="approved-characters",
            asset_id="approved-characters",
            filename=path.name,
            sha256=digest,
            image_bytes=body,
            selection_reason="approved Xiaosai character identity",
        ),
    )


def prepare_infographic_group_jpeg(footer_png: bytes, *, max_bytes: int) -> bytes:
    """Materialize the exact 1152x2048 JPEG that OCR and the webhook will see.

    Unlike the generic group adapter this never downscales a poster. OCR and a
    separate phone-width visual gate decide whether any allowed JPEG is legible.
    """
    with Image.open(BytesIO(footer_png)) as opened:
        opened.load()
        if opened.size != GEOMETRY or getattr(opened, "n_frames", 1) != 1:
            raise ValueError("infographic footer has wrong geometry")
        raster = opened.convert("RGB")
    for quality in (92, 88, 84, 80, 76, 72):
        target = BytesIO()
        raster.save(target, format="JPEG", quality=quality, subsampling=0, optimize=False)
        body = target.getvalue()
        if len(body) <= max_bytes:
            prepared = prepare_group_webhook_image(body, "image/jpeg", max_bytes=max_bytes)
            if prepared.body != body or prepared.media_type != "image/jpeg":
                raise ValueError("group adapter would alter reviewed JPEG")
            return body
    raise ValueError("full-resolution infographic JPEG cannot fit the group limit")


@dataclass(frozen=True, slots=True)
class _PosterOcrRegion:
    region_id: str
    image_bytes: bytes
    expected_text: str


def _encode_ocr_crop(image: Image.Image, bounds: tuple[int, int, int, int]) -> bytes:
    target = BytesIO()
    image.crop(bounds).save(target, format="JPEG", quality=95, subsampling=0, optimize=False)
    return target.getvalue()


def _poster_ocr_regions(
    body: bytes, copy: PosterCopy, footer_text: str
) -> tuple[_PosterOcrRegion, ...]:
    """Use content-only, bounded crops decoded from the exact delivery JPEG.

    Generated layout can move. A field outside its guarded crop fails closed; the
    full unchanged JPEG still goes to the independent visual auditor. Regions
    deliberately exclude decorative background text and repeated character badges.
    """
    with Image.open(BytesIO(body)) as opened:
        opened.load()
        if opened.format != "JPEG" or opened.size != GEOMETRY:
            raise ValueError("reviewed infographic JPEG has wrong geometry")
        definitions = (
            ("masthead", (0, 0, 850, 530), "小赛洞察" + copy.title + copy.news_summary),
            ("science", (40, 930, 690, 1250), copy.cards[0].heading + copy.cards[0].body),
            ("learning", (40, 1250, 690, 1540), copy.cards[1].heading + copy.cards[1].body),
            ("brand", (40, 1540, 690, FOOTER_TOP), copy.cards[2].heading + copy.cards[2].body),
            ("footer", (0, FOOTER_TOP, *GEOMETRY), footer_text),
        )
        return tuple(
            _PosterOcrRegion(region_id, _encode_ocr_crop(opened, bounds), expected)
            for region_id, bounds, expected in definitions
        )


def _poster_region_text_matches(
    result: ImageTextRecognitionResult | None, *, fingerprint: str, expected_text: str
) -> bool:
    """Preserve every non-space character while allowing visual line wrapping."""
    if result is None or result.request_fingerprint != fingerprint:
        return False
    observed = "".join("".join(line.split()) for line in result.recognized_lines)
    expected = "".join(expected_text.split())
    return bool(observed and observed == expected)


class _PosterInfographicModels(InfographicModels, Protocol):
    async def recognize_poster_region(
        self, request: PosterRegionRecognitionRequest
    ) -> ImageTextRecognitionResult | None: ...


class NewsInfographicProducer:
    def __init__(
        self,
        *,
        session_factory: async_sessionmaker[AsyncSession],
        image_store: MinioImageStore,
        settings: Settings,
        models: _PosterInfographicModels,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._sessions = session_factory
        self._store = image_store
        self._settings = settings
        self._models = models
        self._clock = clock

    async def reconcile(self, *, limit: int = 24) -> int:
        if not self._settings.wecom_infographic_producer_enabled:
            return 0
        now = self._clock()
        business_date = now.astimezone(ZoneInfo(self._settings.business_timezone)).date()
        try:
            policy = _policy_fingerprint(
                self._models.image_model,
                self._models.copy_model,
                quality_mode=self._settings.wecom_infographic_review_mode,
            )
        except (TextOverlayError, FooterRenderError, AdvisoryCopyError):
            return 0
        async with self._sessions() as session, session.begin():
            rows = (
                await session.execute(
                    select(
                        WeComDeliveryJobModel,
                        MaterialPackageModel,
                        CopyGenerationRunModel,
                        ContentSlotSelectionModel,
                        WeComDeliveryWindowModel,
                    )
                    .join(
                        MaterialPackageModel,
                        WeComDeliveryJobModel.material_package_id == MaterialPackageModel.id,
                    )
                    .join(
                        CopyGenerationRunModel,
                        MaterialPackageModel.run_id == CopyGenerationRunModel.id,
                    )
                    .join(
                        ContentSlotSelectionModel,
                        CopyGenerationRunModel.content_slot_selection_id
                        == ContentSlotSelectionModel.id,
                    )
                    .join(
                        WeComDeliveryWindowModel,
                        WeComDeliveryJobModel.delivery_window_id == WeComDeliveryWindowModel.id,
                    )
                    .where(
                        WeComDeliveryJobModel.mode == "formal",
                        WeComDeliveryJobModel.status.in_(("queued", "running", "delivered")),
                        WeComDeliveryJobModel.include_copy.is_(True),
                        WeComDeliveryJobModel.include_image.is_(True),
                        WeComDeliveryJobModel.sequence_ordinal
                        <= self._settings.wecom_infographic_max_ordinal,
                        ContentSlotSelectionModel.business_date == business_date,
                        WeComDeliveryWindowModel.expires_at > now,
                        WeComDeliveryWindowModel.provider == "group_webhook",
                    )
                    .order_by(
                        WeComDeliveryWindowModel.target_at, WeComDeliveryJobModel.sequence_ordinal
                    )
                    .limit(limit)
                )
            ).all()
            created = 0
            for base, package, run, selection, window in rows:
                try:
                    case = _input_from_package(package)
                    _assert_lineage(
                        case=case,
                        package=package,
                        run=run,
                        selection=selection,
                        base=base,
                        window=window,
                        now=now,
                        settings=self._settings,
                    )
                except (InfographicInputError, ValidationError, ValueError):
                    continue
                # Row lock serializes competing reconcilers. The database unique keys remain
                # the final authority for both base-job and package/policy idempotency.
                existing = await session.scalar(
                    select(NewsInfographicJobModel.id).where(
                        NewsInfographicJobModel.base_job_id == base.id
                    )
                )
                if existing is not None:
                    continue
                from sqlalchemy.dialects.postgresql import insert

                result = await session.execute(
                    insert(NewsInfographicJobModel)
                    .values(
                        id=uuid4(),
                        base_job_id=base.id,
                        material_package_id=package.id,
                        copy_generation_run_id=run.id,
                        content_slot_selection_id=selection.id,
                        sequence_ordinal=selection.ordinal,
                        selected_event_id=selection.selected_event_id,
                        selected_event_version_id=selection.selected_event_version_id,
                        business_date=run.business_date,
                        content_slot=selection.content_slot,
                        recipient_id=base.recipient_id,
                        provider=window.provider,
                        package_version=package.package_version,
                        policy_fingerprint=policy,
                        input_fingerprint=case.fingerprint,
                        quality_mode=self._settings.wecom_infographic_review_mode,
                        warning_codes=(
                            normalize_advisory_warnings(())
                            if self._settings.wecom_infographic_review_mode == "advisory"
                            else []
                        ),
                        warning_notice_version=(
                            ADVISORY_NOTICE_VERSION
                            if self._settings.wecom_infographic_review_mode == "advisory"
                            else None
                        ),
                        status="queued",
                        stage="preflight",
                    )
                    .on_conflict_do_nothing()
                    .returning(NewsInfographicJobModel.id)
                )
                if result.scalar_one_or_none() is not None:
                    created += 1
            return created

    async def execute_next(self, worker_id: str) -> bool:
        if not self._settings.wecom_infographic_producer_enabled:
            return False
        now = self._clock()
        token = uuid4()
        async with self._sessions() as session, session.begin():
            stale = (
                await session.scalars(
                    select(NewsInfographicJobModel)
                    .where(
                        NewsInfographicJobModel.status == "running",
                        NewsInfographicJobModel.lease_expires_at <= now,
                    )
                    .with_for_update(skip_locked=True)
                    .limit(24)
                )
            ).all()
            for old in stale:
                old.status = "result_unknown"
                old.safe_error_code = "production_lease_expired"
                old.completed_at = now
                old.lease_token = None
                old.lease_owner = None
                old.lease_expires_at = None
            expired = (
                await session.scalars(
                    select(NewsInfographicJobModel)
                    .join(
                        WeComDeliveryJobModel,
                        NewsInfographicJobModel.base_job_id == WeComDeliveryJobModel.id,
                    )
                    .where(
                        NewsInfographicJobModel.status == "queued",
                        WeComDeliveryJobModel.expires_at <= now,
                    )
                    .with_for_update(skip_locked=True)
                    .limit(24)
                )
            ).all()
            for old in expired:
                old.status = "expired"
                old.completed_at = now
            job = await session.scalar(
                select(NewsInfographicJobModel)
                .join(
                    WeComDeliveryJobModel,
                    NewsInfographicJobModel.base_job_id == WeComDeliveryJobModel.id,
                )
                .where(
                    NewsInfographicJobModel.status == "queued",
                    NewsInfographicJobModel.quality_mode
                    == self._settings.wecom_infographic_review_mode,
                    WeComDeliveryJobModel.expires_at > now,
                )
                .order_by(
                    WeComDeliveryJobModel.not_before, NewsInfographicJobModel.sequence_ordinal
                )
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if job is None:
                return False
            job.status = "running"
            job.lease_owner = worker_id
            job.lease_token = token
            job.lease_expires_at = now + timedelta(minutes=10)
            job_id = job.id
        stopped = asyncio.Event()
        heartbeat = asyncio.create_task(self._heartbeat(job_id, token, stopped))
        try:
            await self._produce(job_id, token)
        except asyncio.CancelledError:
            raise
        except Exception:
            # The provider may have accepted a call; never replay a claimed job automatically.
            await self._finish(
                job_id, token, status="result_unknown", code="production_stage_unknown"
            )
        finally:
            stopped.set()
            await asyncio.gather(heartbeat, return_exceptions=True)
        return True

    async def _heartbeat(self, job_id: UUID, token: UUID, stopped: asyncio.Event) -> None:
        while not stopped.is_set():
            try:
                await asyncio.wait_for(stopped.wait(), timeout=30)
                return
            except TimeoutError:
                async with self._sessions() as session, session.begin():
                    job = await session.get(NewsInfographicJobModel, job_id, with_for_update=True)
                    if (
                        job is None
                        or job.lease_token != token
                        or job.status != "running"
                        or job.lease_expires_at is None
                        or job.lease_expires_at <= self._clock()
                    ):
                        return
                    job.lease_expires_at = self._clock() + timedelta(minutes=10)

    async def _intent(
        self, job_id: UUID, token: UUID, stage: str, request_fingerprint: str
    ) -> bool:
        now = self._clock()
        async with self._sessions() as session, session.begin():
            job = await session.get(NewsInfographicJobModel, job_id, with_for_update=True)
            if (
                job is None
                or job.lease_token != token
                or job.status != "running"
                or job.lease_expires_at is None
                or job.lease_expires_at <= now
            ):
                return False
            if stage == "image":
                # A transaction-scoped date lock makes the nine-call ceiling durable across
                # all producer processes, including simultaneous morning/noon/evening workers.
                await session.execute(
                    select(func.pg_advisory_xact_lock(9947, job.business_date.toordinal()))
                )
                count = await session.scalar(
                    select(func.count(NewsInfographicJobModel.id)).where(
                        NewsInfographicJobModel.business_date == job.business_date,
                        NewsInfographicJobModel.image_intent_at.is_not(None),
                    )
                )
                if count is None or count >= 9:
                    return False
            field = {
                "copy": "copy_intent_at",
                "audit": "audit_intent_at",
                "image": "image_intent_at",
                "ocr": "ocr_intent_at",
                "footer_ocr": "footer_ocr_intent_at",
                "visual": "visual_intent_at",
            }[stage]
            if getattr(job, field) is not None:
                return False
            setattr(job, field, now)
            setattr(job, f"{stage}_request_fingerprint", request_fingerprint)
            job.stage = stage
            return True

    async def _finish(
        self, job_id: UUID, token: UUID, *, status: str, code: str | None = None
    ) -> None:
        async with self._sessions() as session, session.begin():
            job = await session.get(NewsInfographicJobModel, job_id, with_for_update=True)
            if (
                job is None
                or job.lease_token != token
                or job.status != "running"
                or job.lease_expires_at is None
                or job.lease_expires_at <= self._clock()
            ):
                return
            job.status = status
            job.safe_error_code = code
            job.completed_at = self._clock()
            job.lease_owner = None
            job.lease_token = None
            job.lease_expires_at = None

    async def _produce(self, job_id: UUID, token: UUID) -> None:
        async with self._sessions() as session:
            job = await session.get(NewsInfographicJobModel, job_id)
            if job is None:
                return
            package = await session.get(MaterialPackageModel, job.material_package_id)
            run = await session.get(CopyGenerationRunModel, job.copy_generation_run_id)
            selection = await session.get(ContentSlotSelectionModel, job.content_slot_selection_id)
            base = await session.get(WeComDeliveryJobModel, job.base_job_id)
            window = (
                await session.get(WeComDeliveryWindowModel, base.delivery_window_id)
                if base and base.delivery_window_id
                else None
            )
        if not all((package, run, selection, base, window)):
            await self._finish(job_id, token, status="failed", code="lineage_missing")
            return
        assert package and run and selection and base and window
        try:
            case = _input_from_package(package)
            _assert_lineage(
                case=case,
                package=package,
                run=run,
                selection=selection,
                base=base,
                window=window,
                now=self._clock(),
                settings=self._settings,
            )
            _assert_job_lineage(
                job=job,
                package=package,
                run=run,
                selection=selection,
                base=base,
                window=window,
            )
            if (
                case.fingerprint != job.input_fingerprint
                or job.policy_fingerprint
                != _policy_fingerprint(
                    self._models.image_model,
                    self._models.copy_model,
                    quality_mode=job.quality_mode,
                )
            ):
                raise InfographicInputError("frozen input changed")
            validate_exact_source_footer_layout(case, mode="formal")
            references = _approved_reference()
        except (
            InfographicInputError,
            FooterRenderError,
            TextOverlayError,
            ValidationError,
            ValueError,
            AdvisoryCopyError,
        ):
            await self._finish(job_id, token, status="failed", code="input_preflight_failed")
            return
        if job.quality_mode == "advisory":
            await self._produce_advisory(
                job=job,
                token=token,
                case=case,
                package=package,
                run=run,
                references=references,
            )
            return
        # The first formal policy deliberately uses the same conservative wording for
        # science and non-science news. No reliable typed science-mechanism classifier
        # exists, so an LLM must not quietly upgrade a sparse fact into a mechanism.
        # This is deterministic work, before any paid model intent; failure is final
        # for this poster while the original text/image delivery proceeds unchanged.
        try:
            copy = build_evidence_first_copy(case)
            validate_poster_copy(case, copy)
        except (ValidationError, ValueError):
            await self._finish(job_id, token, status="failed", code="copy_preflight_failed")
            return
        try:
            preflight_text_overlay_layout(copy, use_reviewed_lines=False)
        except TextOverlayError:
            await self._finish(job_id, token, status="failed", code="overlay_preflight_failed")
            return
        audit_prompt = build_copy_audit_prompt(case, copy)
        audit_fingerprint = stable_key(
            POLICY_VERSION,
            EVIDENCE_FIRST_COPY_VERSION,
            case.fingerprint,
            audit_prompt,
            self._models.copy_model,
        )
        if not await self._intent(job_id, token, "audit", audit_fingerprint):
            await self._finish(
                job_id, token, status="result_unknown", code="audit_intent_unavailable"
            )
            return
        verdict = CopyVerdict.model_validate(await self._models.complete_json(audit_prompt))
        if not verdict.accepted or verdict.issues:
            await self._finish(job_id, token, status="failed", code="copy_audit_rejected")
            return
        prompt = validate_image_generation_request_prompt(
            ImageGenerationRequest(
                run_id=job.id,
                draft_version_id=case.draft_version_id,
                prompt=build_image_prompt(case, copy, mode="formal", reserve_text_panels=True),
                request_fingerprint="wecom-infographic-preflight",
                unrestricted_prompt_length=True,
            )
        )
        fingerprint = stable_key(
            POLICY_VERSION,
            case.fingerprint,
            copy.model_dump(mode="json"),
            prompt,
            self._models.image_model,
            *(item.sha256 for item in references),
        )
        if not await self._intent(job_id, token, "image", fingerprint):
            await self._finish(
                job_id, token, status="skipped", code="daily_image_ceiling_or_intent"
            )
            return
        result = await self._models.generate(
            ImageGenerationRequest(
                run_id=job.id,
                draft_version_id=case.draft_version_id,
                prompt=prompt,
                request_fingerprint=fingerprint,
                provider_request_fingerprint=fingerprint,
                references=references,
                reference_mode="multi",
                unrestricted_prompt_length=True,
            )
        )
        if (result.provider, result.model, result.request_fingerprint, result.attempts) != (
            "comfly",
            self._models.image_model,
            fingerprint,
            1,
        ):
            await self._finish(job_id, token, status="failed", code="image_result_identity")
            return
        _validate_raster(result)
        raw = await self._store.put_immutable(result.image_bytes, media_type=result.media_type)
        try:
            composite = render_exact_text_overlay(
                result.image_bytes, case, copy, use_reviewed_lines=False
            )
        except TextOverlayError:
            await self._finish(job_id, token, status="failed", code="overlay_render_failed")
            return
        composite_object = await self._store.put_immutable(
            composite.image_bytes, media_type="image/png"
        )
        footer = render_exact_source_footer(composite.image_bytes, case, mode="formal")
        derived = await self._store.put_immutable(footer.image_bytes, media_type="image/png")
        jpeg = prepare_infographic_group_jpeg(
            footer.image_bytes, max_bytes=self._settings.wecom_group_max_image_bytes
        )
        prepared = prepare_group_webhook_image(
            jpeg,
            "image/jpeg",
            max_bytes=self._settings.wecom_group_max_image_bytes,
            max_input_bytes=self._settings.wecom_max_image_bytes,
        )
        # The adapter must not downscale this accepted portrait. It will receive <=2 MiB
        # pre-encoded bytes and return them unchanged.
        with Image.open(BytesIO(prepared.body)) as opened:
            opened.load()
            if opened.size != GEOMETRY:
                await self._finish(
                    job_id, token, status="failed", code="delivery_geometry_degraded"
                )
                return
        delivered = await self._store.put_immutable(prepared.body, media_type=prepared.media_type)
        async with self._sessions() as session, session.begin():
            locked = await session.get(NewsInfographicJobModel, job_id, with_for_update=True)
            if locked is None or locked.lease_token != token or locked.status != "running":
                return
            locked.raw_sha256, locked.raw_byte_size, locked.raw_media_type = (
                raw.sha256,
                raw.byte_size,
                raw.media_type,
            )
            locked.composite_sha256, locked.composite_byte_size = (
                composite_object.sha256,
                composite_object.byte_size,
            )
            locked.footer_sha256, locked.footer_byte_size = derived.sha256, derived.byte_size
            locked.delivery_sha256, locked.delivery_byte_size = (
                delivered.sha256,
                delivered.byte_size,
            )
            locked.delivery_media_type = delivered.media_type
            locked.delivery_width, locked.delivery_height = GEOMETRY
        footer_text = (
            f"新闻日期：{case.source_date.isoformat()}"
            f"新闻来源：{case.source_name}"
            "原文链接：" + "".join(footer.source_url_lines)
        )
        regions = _poster_ocr_regions(prepared.body, copy, footer_text)
        if not self._models.ocr_enabled or not self._models.visual_audit_enabled:
            await self._finish(job_id, token, status="failed", code="quality_service_unavailable")
            return
        # One committed group intent reserves every deterministic child request
        # before the first body OCR call. A crash makes the entire running job
        # result_unknown; none of these region calls is replayed automatically.
        child_fingerprints = tuple(
            stable_key(
                _POSTER_OCR_VERSION,
                delivered.sha256,
                region.region_id,
                sha256(region.image_bytes).hexdigest(),
                region.expected_text,
            )
            for region in regions
        )
        ocr_fingerprint = stable_key(fingerprint, DELIVERY_FOOTER_VERSION, *child_fingerprints[:-1])
        if not await self._intent(job_id, token, "ocr", ocr_fingerprint):
            await self._finish(
                job_id, token, status="result_unknown", code="ocr_intent_unavailable"
            )
            return
        for region, child_fingerprint in zip(regions[:-1], child_fingerprints[:-1], strict=True):
            ocr = await self._models.recognize_poster_region(
                PosterRegionRecognitionRequest(
                    image_bytes=region.image_bytes,
                    media_type="image/jpeg",
                    region_id=region.region_id,
                    request_fingerprint=child_fingerprint,
                )
            )
            if not _poster_region_text_matches(
                ocr, fingerprint=child_fingerprint, expected_text=region.expected_text
            ):
                await self._finish(job_id, token, status="failed", code="delivery_ocr_failed")
                return
        async with self._sessions() as session, session.begin():
            locked = await session.get(NewsInfographicJobModel, job_id, with_for_update=True)
            if locked is None or locked.lease_token != token:
                return
            locked.ocr_status = "passed"
        footer_region = regions[-1]
        footer_child_fingerprint = child_fingerprints[-1]
        footer_ocr_fingerprint = stable_key(
            fingerprint, DELIVERY_FOOTER_VERSION, footer_child_fingerprint
        )
        if not await self._intent(job_id, token, "footer_ocr", footer_ocr_fingerprint):
            await self._finish(
                job_id, token, status="result_unknown", code="footer_ocr_intent_unavailable"
            )
            return
        footer_ocr = await self._models.recognize_poster_region(
            PosterRegionRecognitionRequest(
                image_bytes=footer_region.image_bytes,
                media_type="image/jpeg",
                region_id=footer_region.region_id,
                request_fingerprint=footer_child_fingerprint,
            )
        )
        if not _poster_region_text_matches(
            footer_ocr,
            fingerprint=footer_child_fingerprint,
            expected_text=footer_region.expected_text,
        ):
            await self._finish(job_id, token, status="failed", code="delivery_footer_ocr_failed")
            return
        async with self._sessions() as session, session.begin():
            locked = await session.get(NewsInfographicJobModel, job_id, with_for_update=True)
            if locked is None or locked.lease_token != token:
                return
            locked.footer_ocr_status = "passed"
        visual_fingerprint = stable_key(
            fingerprint, delivered.sha256, _POSTER_VISUAL_RUBRIC_VERSION
        )
        if not await self._intent(job_id, token, "visual", visual_fingerprint):
            await self._finish(
                job_id, token, status="result_unknown", code="visual_intent_unavailable"
            )
            return
        visual = await self._models.audit_visual(
            ImageQualityAuditRequest(
                image_bytes=prepared.body,
                media_type=prepared.media_type,
                request_fingerprint=visual_fingerprint,
                references=references,
                criteria=(
                    "Exact 1152x2048 portrait Chinese news poster with three readable cards.",
                    "Sai Xiansheng and Xiaosai have consistent identity; every Xiaosai "
                    "has a clear AI chest badge.",
                    "All Chinese news text and exact source/date/URL remain readable "
                    "at phone width.",
                    "No extra model-painted words, numbers or labels outside the "
                    "deterministic text panels, exact footer and AI chest badges.",
                    "Illustration matches this specific news without fabricated facts "
                    "or government endorsement.",
                ),
                prompt_version=_OVERLAY_PROMPT_VERSION,
                rubric_version=_POSTER_VISUAL_RUBRIC_VERSION,
            )
        )
        if (
            visual is None
            or visual.request_fingerprint != visual_fingerprint
            or not visual.accepted
        ):
            await self._finish(job_id, token, status="failed", code="delivery_visual_rejected")
            return
        async with self._sessions() as session, session.begin():
            locked = await session.get(NewsInfographicJobModel, job_id, with_for_update=True)
            if locked is None or locked.lease_token != token:
                return
            locked.visual_status = "passed"
        await self._finish(job_id, token, status="ready")

    async def _produce_advisory(
        self,
        *,
        job: NewsInfographicJobModel,
        token: UUID,
        case: ValidatedInfographicInput,
        package: MaterialPackageModel,
        run: CopyGenerationRunModel,
        references: tuple[ImageReference, ...],
    ) -> None:
        """Forward-only rich branch; negative reviews remain durable warnings.

        The old evidence-first path above is deliberately unchanged. Only
        package/source/recipient, known provider bytes and exact footer remain
        mandatory to create a candidate. A separate send gate owns delivery.
        """
        async with self._sessions() as session:
            active = (
                await session.get(CopyDraftVersionModel, run.active_draft_version_id)
                if run.active_draft_version_id is not None
                else None
            )
        if active is None:
            await self._finish(job.id, token, status="failed", code="moments_draft_missing")
            return
        try:
            binding = _moments_binding_from_accepted_models(
                case=case, package=package, run=run, active_draft=active
            )
            seed = build_moments_rich_seed(case, binding)
            copy_prompt = build_advisory_generation_prompt(case, binding)
        except (InfographicInputError, RichCopyError, ValidationError, ValueError):
            await self._finish(job.id, token, status="failed", code="moments_preflight_failed")
            return
        copy_fingerprint = stable_key(
            ADVISORY_POLICY_VERSION,
            ADVISORY_COPY_VERSION,
            case.fingerprint,
            seed.seed_fingerprint,
            copy_prompt,
            self._models.copy_model,
        )
        if not await self._intent(job.id, token, "copy", copy_fingerprint):
            await self._finish(
                job.id, token, status="result_unknown", code="copy_intent_unavailable"
            )
            return
        raw_draft = await self._models.complete_json(copy_prompt)
        try:
            rich = build_advisory_rich_copy(case, binding, raw_draft)
        except (AdvisoryCopyError, ValidationError, ValueError):
            await self._finish(job.id, token, status="failed", code="rich_copy_unusable")
            return
        warnings = {
            "copy_schema_warning": "copy_deterministic_rejected",
            "copy_binding_warning": "copy_deterministic_rejected",
            "copy_layout_warning": "layout_overflow",
        }
        issue_codes = {warnings[code] for code in rich.warning_codes}
        issue_codes.add("layout_unverified")
        async with self._sessions() as session, session.begin():
            locked = await session.get(NewsInfographicJobModel, job.id, with_for_update=True)
            if locked is None or locked.lease_token != token or locked.status != "running":
                return
            locked.copy_candidate_snapshot = rich.model_dump(mode="json")
            locked.warning_codes = normalize_advisory_warnings(issue_codes)
        audit_prompt = build_advisory_audit_prompt(case, binding, rich)
        audit_fingerprint = stable_key(
            ADVISORY_AUDIT_VERSION,
            case.fingerprint,
            copy_fingerprint,
            audit_prompt,
            self._models.copy_model,
        )
        if not await self._intent(job.id, token, "audit", audit_fingerprint):
            await self._finish(
                job.id, token, status="result_unknown", code="audit_intent_unavailable"
            )
            return
        audit_snapshot: dict[str, object]
        try:
            raw_audit = await self._models.complete_json(audit_prompt)
        except Exception:
            issue_codes.add("copy_audit_unavailable")
            audit_snapshot = {"status": "unavailable", "issues": []}
        else:
            try:
                audit = MomentsAuditVerdict.model_validate(raw_audit)
            except (ValidationError, ValueError, TypeError):
                issue_codes.add("copy_audit_schema_invalid")
                audit_snapshot = {"status": "schema_invalid", "issues": []}
            else:
                audit_snapshot = audit.model_dump(mode="json")
                if not audit.accepted:
                    issue_codes.add("copy_audit_rejected")
                if not audit.brand_bound:
                    issue_codes.add("brand_unverified")
        async with self._sessions() as session, session.begin():
            locked = await session.get(NewsInfographicJobModel, job.id, with_for_update=True)
            if locked is None or locked.lease_token != token or locked.status != "running":
                return
            # Persist the bounded candidate and typed/closed audit observation
            # under the same lease before the paid image reservation.
            locked.copy_audit_snapshot = audit_snapshot
            locked.warning_codes = normalize_advisory_warnings(issue_codes)
        try:
            prompt = validate_image_generation_request_prompt(
                ImageGenerationRequest(
                    run_id=job.id,
                    draft_version_id=case.draft_version_id,
                    prompt=build_advisory_image_prompt(case, rich),
                    request_fingerprint="wecom-infographic-advisory-preflight",
                    unrestricted_prompt_length=True,
                )
            )
        except (AdvisoryCopyError, ValidationError, ValueError):
            await self._finish(job.id, token, status="failed", code="rich_image_prompt_unusable")
            return
        fingerprint = stable_key(
            ADVISORY_POLICY_VERSION,
            case.fingerprint,
            rich.model_dump(mode="json"),
            prompt,
            self._models.image_model,
            *(item.sha256 for item in references),
        )
        if not await self._intent(job.id, token, "image", fingerprint):
            await self._finish(
                job.id, token, status="skipped", code="daily_image_ceiling_or_intent"
            )
            return
        result = await self._models.generate(
            ImageGenerationRequest(
                run_id=job.id,
                draft_version_id=case.draft_version_id,
                prompt=prompt,
                request_fingerprint=fingerprint,
                provider_request_fingerprint=fingerprint,
                references=references,
                reference_mode="multi",
                unrestricted_prompt_length=True,
            )
        )
        if (result.provider, result.model, result.request_fingerprint, result.attempts) != (
            "comfly",
            self._models.image_model,
            fingerprint,
            1,
        ):
            await self._finish(job.id, token, status="failed", code="image_result_identity")
            return
        _validate_raster(result)
        raw = await self._store.put_immutable(result.image_bytes, media_type=result.media_type)
        notice_png = render_advisory_notice(result.image_bytes)
        composite = await self._store.put_immutable(notice_png, media_type="image/png")
        footer = render_exact_source_footer(notice_png, case, mode="formal")
        derived = await self._store.put_immutable(footer.image_bytes, media_type="image/png")
        jpeg = prepare_infographic_group_jpeg(
            footer.image_bytes, max_bytes=self._settings.wecom_group_max_image_bytes
        )
        prepared = prepare_group_webhook_image(
            jpeg,
            "image/jpeg",
            max_bytes=self._settings.wecom_group_max_image_bytes,
            max_input_bytes=self._settings.wecom_max_image_bytes,
        )
        if prepared.body != jpeg or prepared.media_type != "image/jpeg":
            await self._finish(job.id, token, status="failed", code="delivery_bytes_changed")
            return
        with Image.open(BytesIO(jpeg)) as opened:
            opened.load()
            if opened.size != GEOMETRY or opened.format != "JPEG":
                await self._finish(
                    job.id, token, status="failed", code="delivery_geometry_degraded"
                )
                return
        delivered = await self._store.put_immutable(jpeg, media_type="image/jpeg")
        async with self._sessions() as session, session.begin():
            locked = await session.get(NewsInfographicJobModel, job.id, with_for_update=True)
            if locked is None or locked.lease_token != token or locked.status != "running":
                return
            locked.raw_sha256, locked.raw_byte_size, locked.raw_media_type = (
                raw.sha256,
                raw.byte_size,
                raw.media_type,
            )
            locked.composite_sha256, locked.composite_byte_size = (
                composite.sha256,
                composite.byte_size,
            )
            locked.footer_sha256, locked.footer_byte_size = derived.sha256, derived.byte_size
            locked.delivery_sha256, locked.delivery_byte_size = (
                delivered.sha256,
                delivered.byte_size,
            )
            locked.delivery_media_type = delivered.media_type
            locked.delivery_width, locked.delivery_height = GEOMETRY
        # Body OCR has no fixed model-painted card positions; record its absence
        # instead of setting a false pass. The source footer remains exact by
        # construction, and a configured footer OCR disagreement is still hard.
        issue_codes.add("body_ocr_unavailable")
        footer_text = (
            f"新闻日期：{case.source_date.isoformat()}"
            f"新闻来源：{case.source_name}"
            "原文链接：" + "".join(footer.source_url_lines)
        )
        if self._models.ocr_enabled:
            with Image.open(BytesIO(jpeg)) as opened:
                opened.load()
                footer_region = _encode_ocr_crop(opened, (0, FOOTER_TOP, *GEOMETRY))
            footer_fingerprint = stable_key(
                ADVISORY_POLICY_VERSION,
                delivered.sha256,
                sha256(footer_region).hexdigest(),
                footer_text,
            )
            if not await self._intent(job.id, token, "footer_ocr", footer_fingerprint):
                await self._finish(
                    job.id, token, status="result_unknown", code="footer_ocr_intent_unavailable"
                )
                return
            try:
                footer_ocr = await self._models.recognize_poster_region(
                    PosterRegionRecognitionRequest(
                        image_bytes=footer_region,
                        media_type="image/jpeg",
                        region_id="footer",
                        request_fingerprint=footer_fingerprint,
                    )
                )
            except Exception:
                footer_ocr = None
            if footer_ocr is None:
                issue_codes.add("footer_ocr_unavailable")
            elif not _poster_region_text_matches(
                footer_ocr, fingerprint=footer_fingerprint, expected_text=footer_text
            ):
                await self._finish(
                    job.id, token, status="failed", code="delivery_footer_ocr_failed"
                )
                return
            else:
                async with self._sessions() as session, session.begin():
                    locked = await session.get(
                        NewsInfographicJobModel, job.id, with_for_update=True
                    )
                    if locked is None or locked.lease_token != token:
                        return
                    locked.footer_ocr_status = "passed"
        else:
            issue_codes.add("footer_ocr_unavailable")
        if self._models.visual_audit_enabled:
            visual_fingerprint = stable_key(
                ADVISORY_POLICY_VERSION, delivered.sha256, "rich-advisory-visual-v1"
            )
            if not await self._intent(job.id, token, "visual", visual_fingerprint):
                await self._finish(
                    job.id, token, status="result_unknown", code="visual_intent_unavailable"
                )
                return
            try:
                visual = await self._models.audit_visual(
                    ImageQualityAuditRequest(
                        image_bytes=jpeg,
                        media_type="image/jpeg",
                        request_fingerprint=visual_fingerprint,
                        references=references,
                        criteria=(
                            "Three substantial Chinese news, child inquiry and teaching cards.",
                            "Visible AI-generated/unverified warning; exact source footer intact.",
                            "Record clipping, extra painted words and phone readability honestly.",
                        ),
                        prompt_version=ADVISORY_IMAGE_PROMPT_VERSION,
                        rubric_version="rich-advisory-visual-v1",
                    )
                )
            except Exception:
                visual = None
            if visual is None or visual.request_fingerprint != visual_fingerprint:
                issue_codes.add("visual_unavailable")
            elif not visual.accepted:
                issue_codes.add("visual_failed")
                async with self._sessions() as session, session.begin():
                    locked = await session.get(
                        NewsInfographicJobModel, job.id, with_for_update=True
                    )
                    if locked is None or locked.lease_token != token:
                        return
                    locked.visual_status = "failed"
            else:
                async with self._sessions() as session, session.begin():
                    locked = await session.get(
                        NewsInfographicJobModel, job.id, with_for_update=True
                    )
                    if locked is None or locked.lease_token != token:
                        return
                    locked.visual_status = "passed"
        else:
            issue_codes.add("visual_unavailable")
        async with self._sessions() as session, session.begin():
            locked = await session.get(NewsInfographicJobModel, job.id, with_for_update=True)
            if locked is None or locked.lease_token != token or locked.status != "running":
                return
            locked.warning_codes = normalize_advisory_warnings(issue_codes)
            locked.warning_notice_version = ADVISORY_NOTICE_VERSION
        await self._finish(job.id, token, status="ready")
