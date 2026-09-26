"""Real PostgreSQL and fake fixed-group tests for the one-shot visible triple path."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta
from hashlib import sha256
from io import BytesIO
from uuid import UUID, uuid4
from zoneinfo import ZoneInfo

import pytest
from app.application.ports.wecom import SendResult, WeComUnknownTimeoutError
from app.application.services.news_infographic_advisory import render_advisory_notice
from app.application.services.news_infographic_footer import render_exact_source_footer
from app.application.services.wecom_infographic_quality import ADVISORY_NOTICE_VERSION
from app.application.services.wecom_infographic_supplement import (
    WeComInfographicSupplementExecutor,
)
from app.application.services.wecom_infographic_test import (
    WeComInfographicVisibleTest,
    fixed_group_fingerprint,
)
from app.application.services.wecom_news_infographic import (
    _input_from_package,
    prepare_infographic_group_jpeg,
)
from app.core.config import Settings
from app.core.errors import ConflictError
from app.infrastructure.db.models import (
    CopyGenerationRunModel,
    ImageArtifactModel,
    MaterialPackageModel,
    NewsInfographicJobModel,
    WeComDeliveryJobModel,
    WeComDeliveryWindowModel,
    WeComInfographicSupplementModel,
    WeComInfographicTestAttemptModel,
    WeComInfographicTestRunModel,
)
from app.infrastructure.storage.minio_image_store import ImageObjectDescriptor, image_content_key
from PIL import Image
from pydantic import SecretStr
from sqlalchemy import select
from tests.unit.test_news_infographic import package_payload

from .conftest import IntegrationContext
from .test_wecom_slot_delivery_concurrency import _seed_slot_delivery_lane


class _Store:
    def __init__(self, blobs: dict[str, bytes], bucket: str) -> None:
        self.blobs = blobs
        self.bucket = bucket

    async def put_immutable(self, body: bytes, *, media_type: str) -> ImageObjectDescriptor:
        digest = sha256(body).hexdigest()
        self.blobs[digest] = body
        return ImageObjectDescriptor(
            bucket=self.bucket,
            object_key=image_content_key(digest, media_type),
            media_type=media_type,
            byte_size=len(body),
            sha256=digest,
        )

    async def get_bytes(self, descriptor: ImageObjectDescriptor) -> bytes:
        return self.blobs[descriptor.sha256]

    async def get_content_addressed_bytes(
        self, *, media_type: str, byte_size: int, sha256: str
    ) -> bytes:
        body = self.blobs[sha256]
        assert len(body) == byte_size
        return body


class _FixedGroup:
    def __init__(self, *, timeout_on: str | None = None) -> None:
        self.calls: list[tuple[str, bytes | str]] = []
        self.timeout_on = timeout_on

    async def send_text(
        self,
        *,
        recipient_id: str,
        agent_id: int | None,
        content: str,
        request_fingerprint: str,
    ) -> SendResult:
        assert recipient_id == "default"
        self.calls.append(("text", content))
        if self.timeout_on == "text":
            raise WeComUnknownTimeoutError()
        return SendResult(response_code=0)

    async def send_image_bytes(
        self,
        *,
        recipient_id: str,
        agent_id: int | None,
        image_bytes: bytes,
        media_type: str,
        filename: str,
        request_fingerprint: str,
    ) -> SendResult:
        assert recipient_id == "default"
        kind = "infographic" if "infographic" in filename else "original"
        self.calls.append((kind, image_bytes))
        if self.timeout_on == kind:
            raise WeComUnknownTimeoutError()
        return SendResult(response_code=0)


def _settings(*, advisory: bool = False, delivery: bool = False) -> Settings:
    return Settings(
        _env_file=None,
        wecom_enabled=True,
        wecom_auto_delivery_enabled=True,
        wecom_delivery_provider="group_webhook",
        wecom_group_webhook_key=SecretStr("synthetic-fixed-group-key"),
        content_enabled=True,
        content_slot_mode_enabled=True,
        content_llm_rerank_enabled=False,
        content_morning_enabled=True,
        wecom_infographic_test_enabled=True,
        wecom_infographic_delivery_enabled=delivery,
        wecom_infographic_review_mode="advisory" if advisory else "strict",
        wecom_infographic_morning_enabled=True,
        wecom_infographic_max_ordinal=3,
        image_ocr_enabled=not advisory,
        image_quality_audit_enabled=not advisory,
    )


def _png(size: tuple[int, int]) -> bytes:
    output = BytesIO()
    Image.new("RGB", size, "#c6e7fa").save(output, format="PNG")
    return output.getvalue()


async def _seed(
    context: IntegrationContext, *, target: datetime, settings: Settings
) -> tuple[UUID, _Store, datetime]:
    window_id, job_ids, business_date, _ = await _seed_slot_delivery_lane(context, target_at=target)
    now = target + timedelta(minutes=2)
    original = _png((1024, 1024))
    raw = _png((1152, 2048))
    original_sha = sha256(original).hexdigest()
    raw_sha = sha256(raw).hexdigest()
    blobs = {original_sha: original, raw_sha: raw}
    async with context.session_factory() as session:
        window = await session.get(WeComDeliveryWindowModel, window_id)
        base = await session.get(WeComDeliveryJobModel, job_ids[0])
        assert window is not None and base is not None
        window.provider = "group_webhook"
        base.status = "delivered"
        base.text_status = "delivered"
        base.image_status = "delivered"
        base.completed_at = now
        package = await session.get(MaterialPackageModel, base.material_package_id)
        assert package is not None
        run = await session.get(CopyGenerationRunModel, package.run_id)
        image = await session.get(ImageArtifactModel, package.image_artifact_id)
        assert run is not None and image is not None
        payload = deepcopy(package_payload())
        payload["id"] = str(package.id)
        payload["copy_generation_run_id"] = str(run.id)
        payload["package_version"] = package.package_version
        payload["status"] = package.status
        payload["review_status"] = package.review_status
        payload["topic"]["selected_event_id"] = str(run.selected_event_id)
        payload["topic"]["selected_event_version_id"] = str(run.selected_event_version_id)
        payload["topic"]["business_date"] = business_date.isoformat()
        payload["copy"]["draft_version_id"] = str(package.draft_version_id)
        payload["copy"]["version"] = 1
        package.topic_snapshot = payload["topic"]
        package.copy_snapshot = payload["copy"]
        package.source_snapshot = payload["sources"]
        package.brand_snapshot = payload["brand_bindings"]
        package.validation_snapshot = payload["validation"]
        package.audit_snapshot = payload["audit"]
        image.bucket = settings.minio_bucket
        image.object_key = image_content_key(original_sha, "image/png")
        image.sha256 = original_sha
        image.byte_size = len(original)
        image.media_type = "image/png"
        case = _input_from_package(package)
        advisory = settings.wecom_infographic_review_mode == "advisory"
        notice = render_advisory_notice(raw) if advisory else raw
        formal = render_exact_source_footer(notice, case, mode="formal")
        formal_jpeg = prepare_infographic_group_jpeg(
            formal.image_bytes, max_bytes=settings.wecom_group_max_image_bytes
        )
        formal_sha = sha256(formal_jpeg).hexdigest()
        blobs[formal_sha] = formal_jpeg
        session.add(
            NewsInfographicJobModel(
                id=uuid4(),
                base_job_id=base.id,
                material_package_id=package.id,
                copy_generation_run_id=run.id,
                content_slot_selection_id=base.content_slot_selection_id,
                sequence_ordinal=base.sequence_ordinal,
                selected_event_id=run.selected_event_id,
                selected_event_version_id=run.selected_event_version_id,
                business_date=business_date,
                content_slot="morning",
                recipient_id="default",
                provider="group_webhook",
                package_version=package.package_version,
                policy_fingerprint="a" * 64,
                input_fingerprint=case.fingerprint,
                status="ready",
                stage="visual",
                raw_sha256=raw_sha,
                raw_byte_size=len(raw),
                raw_media_type="image/png",
                image_intent_at=now if advisory else None,
                composite_sha256=sha256(notice).hexdigest() if advisory else None,
                composite_byte_size=len(notice) if advisory else None,
                footer_sha256=sha256(formal.image_bytes).hexdigest() if advisory else None,
                footer_byte_size=len(formal.image_bytes) if advisory else None,
                delivery_sha256=formal_sha,
                delivery_byte_size=len(formal_jpeg),
                delivery_media_type="image/jpeg",
                delivery_width=1152,
                delivery_height=2048,
                ocr_status="not_checked" if advisory else "passed",
                footer_ocr_status="not_checked" if advisory else "passed",
                visual_status="failed" if advisory else "passed",
                quality_mode="advisory" if advisory else "strict",
                warning_codes=(
                    [
                        "advisory_unverified",
                        "body_ocr_unavailable",
                        "copy_audit_unavailable",
                        "footer_ocr_unavailable",
                        "layout_unverified",
                        "visual_failed",
                    ]
                    if advisory
                    else []
                ),
                warning_notice_version=ADVISORY_NOTICE_VERSION if advisory else None,
                copy_candidate_snapshot=(
                    {
                        "package_id": str(package.id),
                        "input_fingerprint": case.fingerprint,
                        "content_approved": False,
                        "warning_codes": [],
                    }
                    if advisory
                    else None
                ),
                copy_audit_snapshot=({"status": "unavailable", "issues": []} if advisory else None),
            )
        )
        await session.commit()
    return job_ids[0], _Store(blobs, settings.minio_bucket), now


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.parametrize("timeout_on", [None, "text", "original", "infographic"])
async def test_visible_test_is_explicit_same_news_ordered_and_unknown_terminal(
    integration_context: IntegrationContext, timeout_on: str | None
) -> None:
    day = {None: 25, "infographic": 26, "text": 29, "original": 30}[timeout_on]
    target = datetime(2026, 9, day, 7, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    settings = _settings()
    base_id, store, now = await _seed(integration_context, target=target, settings=settings)
    moment = [now]
    group = _FixedGroup(timeout_on=timeout_on)
    service = WeComInfographicVisibleTest(
        session_factory=integration_context.session_factory,
        image_store=store,
        client=group,
        settings=settings,
        clock=lambda: moment[0],
    )
    preflight = await service.preflight(base_id)
    assert preflight["target_fingerprint"] == fixed_group_fingerprint(settings)
    with pytest.raises(ConflictError, match="target fingerprint"):
        await service.prepare(base_id, expected_target_fingerprint="0" * 64)
    run, test_jpeg = await service.prepare(
        base_id, expected_target_fingerprint=fixed_group_fingerprint(settings)
    )
    assert run.status == "prepared" and run.test_artifact_sha256 != run.formal_delivery_sha256
    assert sha256(test_jpeg).hexdigest() == run.test_artifact_sha256
    assert not group.calls
    with pytest.raises(ConflictError, match="approved test artifact"):
        await service.enqueue(
            run.id,
            expected_target_fingerprint=fixed_group_fingerprint(settings),
            approved_artifact_sha256="0" * 64,
        )
    await service.enqueue(
        run.id,
        expected_target_fingerprint=fixed_group_fingerprint(settings),
        approved_artifact_sha256=run.test_artifact_sha256,
    )
    claimed = await asyncio.gather(
        service.execute_next("synthetic-test-worker-1"),
        service.execute_next("synthetic-test-worker-2"),
    )
    assert sorted(claimed) == [False, True]
    assert not await service.execute_next("synthetic-test-worker")
    expected_kinds = ["text", "original", "infographic"]
    if timeout_on is not None:
        expected_kinds = expected_kinds[: expected_kinds.index(timeout_on) + 1]
    assert [kind for kind, _ in group.calls] == expected_kinds
    assert str(group.calls[0][1]).startswith("【测试消息】\n")
    if timeout_on in {None, "infographic"}:
        assert group.calls[2][1] == test_jpeg
    receipt = await service.status(run.id)
    expected = "result_unknown" if timeout_on else "delivered"
    assert receipt["status"] == expected
    expected_attempts = ["succeeded"] * len(expected_kinds)
    if timeout_on is not None:
        expected_attempts[-1] = "unknown"
    assert [item["result_state"] for item in receipt["attempts"]] == expected_attempts
    async with integration_context.session_factory() as session:
        base = await session.get(WeComDeliveryJobModel, base_id)
        assert base is not None and base.status == "delivered"
        assert base.text_status == base.image_status == "delivered"
        poster = await session.get(NewsInfographicJobModel, run.infographic_job_id)
        assert poster is not None and poster.status == "ready"
        assert (
            await session.scalar(
                select(WeComInfographicSupplementModel.id).where(
                    WeComInfographicSupplementModel.base_job_id == base_id
                )
            )
            is None
        )
        test = await session.get(WeComInfographicTestRunModel, run.id)
        assert test is not None and test.status == expected
        attempts = (
            await session.scalars(
                select(WeComInfographicTestAttemptModel).where(
                    WeComInfographicTestAttemptModel.test_run_id == run.id
                )
            )
        ).all()
        assert len(attempts) == len(expected_kinds)


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_advisory_visible_test_requires_same_warning_marked_approved_jpeg(
    integration_context: IntegrationContext,
) -> None:
    target = datetime(2027, 1, 13, 7, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    settings = _settings(advisory=True)
    base_id, store, now = await _seed(integration_context, target=target, settings=settings)
    group = _FixedGroup()
    service = WeComInfographicVisibleTest(
        session_factory=integration_context.session_factory,
        image_store=store,
        client=group,
        settings=settings,
        clock=lambda: now,
    )
    run, test_jpeg = await service.prepare(
        base_id, expected_target_fingerprint=fixed_group_fingerprint(settings)
    )
    assert run.test_artifact_sha256 == sha256(test_jpeg).hexdigest()
    assert run.test_artifact_sha256 != run.formal_delivery_sha256
    with Image.open(BytesIO(test_jpeg)) as opened:
        opened.load()
        assert opened.size == (1152, 2048)
        red, green, blue = opened.getpixel((10, 10))
        assert red > green * 1.5 and red > blue * 1.5
    with pytest.raises(ConflictError, match="approved test artifact"):
        await service.enqueue(
            run.id,
            expected_target_fingerprint=fixed_group_fingerprint(settings),
            approved_artifact_sha256=run.formal_delivery_sha256,
        )
    await service.enqueue(
        run.id,
        expected_target_fingerprint=fixed_group_fingerprint(settings),
        approved_artifact_sha256=run.test_artifact_sha256,
    )
    assert await service.execute_next("synthetic-advisory-fixed-group")
    assert [kind for kind, _ in group.calls] == ["text", "original", "infographic"]
    assert group.calls[2][1] == test_jpeg


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_visible_test_stale_intent_becomes_unknown_without_replay(
    integration_context: IntegrationContext,
) -> None:
    target = datetime(2026, 9, 27, 7, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    settings = _settings()
    base_id, store, now = await _seed(integration_context, target=target, settings=settings)
    moment = [now]
    group = _FixedGroup()
    service = WeComInfographicVisibleTest(
        session_factory=integration_context.session_factory,
        image_store=store,
        client=group,
        settings=settings,
        clock=lambda: moment[0],
    )
    run, _ = await service.prepare(
        base_id, expected_target_fingerprint=fixed_group_fingerprint(settings)
    )
    await service.enqueue(
        run.id,
        expected_target_fingerprint=fixed_group_fingerprint(settings),
        approved_artifact_sha256=run.test_artifact_sha256,
    )
    async with integration_context.session_factory() as session:
        stale = await session.get(WeComInfographicTestRunModel, run.id)
        assert stale is not None
        stale.status = "running"
        stale.text_status = "running"
        stale.lease_owner = "lost-worker"
        stale.lease_token = uuid4()
        stale.lease_expires_at = now - timedelta(seconds=1)
        session.add(
            WeComInfographicTestAttemptModel(
                id=uuid4(),
                test_run_id=run.id,
                message_kind="text",
                request_fingerprint="c" * 64,
                result_state="intent",
            )
        )
        await session.commit()
    assert not await service.execute_next("new-worker")
    assert not group.calls
    receipt = await service.status(run.id)
    assert receipt["status"] == "result_unknown"
    assert receipt["text_status"] == "unknown"
    assert receipt["attempts"][0]["result_state"] == "unknown"


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_visible_test_expired_window_cannot_be_approved(
    integration_context: IntegrationContext,
) -> None:
    target = datetime(2026, 9, 28, 7, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    settings = _settings()
    base_id, store, now = await _seed(integration_context, target=target, settings=settings)
    moment = [now]
    service = WeComInfographicVisibleTest(
        session_factory=integration_context.session_factory,
        image_store=store,
        settings=settings,
        clock=lambda: moment[0],
    )
    run, _ = await service.prepare(
        base_id, expected_target_fingerprint=fixed_group_fingerprint(settings)
    )
    moment[0] += timedelta(minutes=31)
    with pytest.raises(ConflictError, match="window has expired"):
        await service.enqueue(
            run.id,
            expected_target_fingerprint=fixed_group_fingerprint(settings),
            approved_artifact_sha256=run.test_artifact_sha256,
        )
    receipt = await service.status(run.id)
    assert receipt["status"] == "prepared" and receipt["attempts"] == []


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_visible_test_refuses_news_snapshot_changed_after_poster_review(
    integration_context: IntegrationContext,
) -> None:
    target = datetime(2026, 10, 1, 7, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    settings = _settings()
    base_id, store, now = await _seed(integration_context, target=target, settings=settings)
    group = _FixedGroup()
    service = WeComInfographicVisibleTest(
        session_factory=integration_context.session_factory,
        image_store=store,
        client=group,
        settings=settings,
        clock=lambda: now,
    )
    await service.preflight(base_id)
    async with integration_context.session_factory() as session:
        base = await session.get(WeComDeliveryJobModel, base_id)
        assert base is not None
        package = await session.get(MaterialPackageModel, base.material_package_id)
        assert package is not None
        package.topic_snapshot = {**package.topic_snapshot, "title": "另一条新闻"}
        await session.commit()
    with pytest.raises(ConflictError, match="same-news poster"):
        await service.preflight(base_id)
    assert not group.calls


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_visible_test_refuses_changed_formal_reviewed_bytes(
    integration_context: IntegrationContext,
) -> None:
    # Keep this session-scoped DB fixture separate from the producer's Oct 2 case.
    target = datetime(2027, 1, 14, 7, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    settings = _settings()
    base_id, store, now = await _seed(integration_context, target=target, settings=settings)
    group = _FixedGroup()
    service = WeComInfographicVisibleTest(
        session_factory=integration_context.session_factory,
        image_store=store,
        client=group,
        settings=settings,
        clock=lambda: now,
    )
    preflight = await service.preflight(base_id)
    formal_sha = str(preflight["formal_delivery_sha256"])
    store.blobs[formal_sha] = bytes(len(store.blobs[formal_sha]))
    with pytest.raises(ConflictError, match="formal reviewed poster bytes changed"):
        await service.prepare(
            base_id, expected_target_fingerprint=fixed_group_fingerprint(settings)
        )
    assert not group.calls


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.parametrize("tamper_warning", [False, True])
async def test_advisory_supplement_rebuilds_exact_warning_and_source_before_fake_send(
    integration_context: IntegrationContext, tamper_warning: bool
) -> None:
    day = 12 if tamper_warning else 11
    target = datetime(2027, 1, day, 7, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    settings = _settings(advisory=True, delivery=True)
    base_id, store, now = await _seed(integration_context, target=target, settings=settings)
    group = _FixedGroup()
    executor = WeComInfographicSupplementExecutor(
        session_factory=integration_context.session_factory,
        image_store=store,
        client=group,
        settings=settings,
        clock=lambda: now,
    )
    async with integration_context.session_factory() as session:
        poster = await session.scalar(
            select(NewsInfographicJobModel).where(NewsInfographicJobModel.base_job_id == base_id)
        )
        assert poster is not None and poster.delivery_sha256 is not None
        expected = store.blobs[poster.delivery_sha256]
        if tamper_warning:
            poster.composite_sha256 = "f" * 64
            await session.commit()
    assert await executor.reconcile() == 1
    assert await executor.execute_next("synthetic-advisory-supplement")
    async with integration_context.session_factory() as session:
        supplement = await session.scalar(
            select(WeComInfographicSupplementModel).where(
                WeComInfographicSupplementModel.base_job_id == base_id
            )
        )
        assert supplement is not None
        assert supplement.status == ("result_unknown" if tamper_warning else "delivered")
        base = await session.get(WeComDeliveryJobModel, base_id)
        assert base is not None and base.status == "delivered"
    if tamper_warning:
        assert not group.calls
    else:
        assert len(group.calls) == 1 and group.calls[0][1] == expected
