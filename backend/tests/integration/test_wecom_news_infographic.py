"""Real PostgreSQL coverage for independent per-news poster and supplement jobs."""

# ruff: noqa: RUF001 -- Exact Chinese footer labels are part of the OCR contract.

from __future__ import annotations

from collections.abc import Awaitable, Callable
from copy import deepcopy
from datetime import date, datetime, timedelta
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from app.api.v1.routes.wecom_deliveries import read_wecom_infographic_status
from app.application.ports.image_generation import ImageGenerationRequest, ImageGenerationResult
from app.application.ports.image_validation import (
    ImageQualityAuditRequest,
    ImageQualityAuditResult,
    ImageTextRecognitionRequest,
    ImageTextRecognitionResult,
    PosterRegionRecognitionRequest,
)
from app.application.ports.wecom import SendResult, WeComTransientError, WeComUnknownTimeoutError
from app.application.services import wecom_news_infographic as wecom_news_infographic_service
from app.application.services.news_infographic import build_evidence_first_copy
from app.application.services.news_infographic_advisory import (
    ADVISORY_AUDIT_VERSION,
    ADVISORY_GENERATION_PROMPT_VERSION,
    prepare_unmarked_advisory_raster,
)
from app.application.services.news_infographic_footer import (
    TRIM_MARGIN,
    render_exact_source_footer,
    validate_exact_source_footer_layout,
)
from app.application.services.news_infographic_text_overlay import TextOverlayError
from app.application.services.wecom_infographic_supplement import (
    WeComInfographicSupplementExecutor,
    _valid_ready_pair,
    _valid_source_lineage,
)
from app.application.services.wecom_news_infographic import (
    NewsInfographicProducer,
    _approved_reference,
    _assert_lineage,
    _input_from_package,
    prepare_infographic_group_jpeg,
)
from app.core.config import Settings
from app.domain.news_infographic import validate_package_snapshot
from app.domain.value_objects import stable_key
from app.infrastructure.db.models import (
    ContentSlotSelectionModel,
    CopyDraftVersionModel,
    CopyGenerationRunModel,
    MaterialPackageModel,
    NewsInfographicJobModel,
    WeComDeliveryJobModel,
    WeComDeliveryWindowModel,
    WeComInfographicAttemptModel,
    WeComInfographicSupplementModel,
)
from app.infrastructure.storage.minio_image_store import ImageObjectDescriptor
from PIL import Image, ImageDraw
from pydantic import SecretStr
from sqlalchemy import func, select
from tests.unit.test_news_infographic import URL, package_payload

from .conftest import IntegrationContext
from .test_wecom_slot_delivery_concurrency import _add_delivery_variant, _seed_slot_delivery_lane


def _bind_valid_package_snapshot(
    package: MaterialPackageModel,
    run: CopyGenerationRunModel,
    business_date: date,
    *,
    fact_text: str = "教育部介绍科学课探究的相关内容。",
) -> None:
    payload = _evidence_ready_payload(fact_text)
    payload["id"] = str(package.id)
    payload["copy_generation_run_id"] = str(package.run_id)
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


def _evidence_ready_payload(
    fact_text: str = "教育部介绍科学课探究的相关内容。",
) -> dict[str, object]:
    payload = deepcopy(package_payload())
    payload["copy"]["claims"][0]["text"] = fact_text
    payload["sources"][0]["claim_text"] = fact_text
    payload["sources"][0]["exact_quote"] = fact_text
    return payload


class _Objects:
    def __init__(self, bodies: dict[str, bytes]) -> None:
        self.bodies = bodies

    async def put_immutable(self, body: bytes, *, media_type: str) -> ImageObjectDescriptor:
        digest = sha256(body).hexdigest()
        self.bodies[digest] = body
        return ImageObjectDescriptor(
            bucket="test",
            object_key=f"test/{digest}",
            media_type=media_type,
            byte_size=len(body),
            sha256=digest,
        )

    async def get_content_addressed_bytes(
        self, *, media_type: str, byte_size: int, sha256: str
    ) -> bytes:
        assert media_type in {"image/png", "image/jpeg"}
        assert len(self.bodies[sha256]) == byte_size
        return self.bodies[sha256]


class _Group:
    def __init__(self, *, timeout_at: int | None = None) -> None:
        self.messages: list[bytes] = []
        self.timeout_at = timeout_at

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
        assert recipient_id == "default" and media_type == "image/jpeg"
        assert len(request_fingerprint) == 64 and filename.endswith(".jpg")
        self.messages.append(image_bytes)
        if len(self.messages) == self.timeout_at:
            raise WeComUnknownTimeoutError()
        return SendResult(response_code=0)


class _TransientGroup(_Group):
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
        self.messages.append(image_bytes)
        if len(self.messages) == 1:
            raise WeComTransientError()
        return SendResult(response_code=0)


class _Models:
    copy_model = "fake-copy-v1"
    image_model = "gpt-image-2.5-sunburst"
    ocr_enabled = True
    visual_audit_enabled = True

    def __init__(self) -> None:
        self.image_requests: list[ImageGenerationRequest] = []
        self.ocr_requests: list[PosterRegionRecognitionRequest] = []
        self.visual_requests: list[ImageQualityAuditRequest] = []
        self.before_ocr: Callable[[PosterRegionRecognitionRequest], Awaitable[None]] | None = None
        self.copy = build_evidence_first_copy(validate_package_snapshot(_evidence_ready_payload()))

    async def complete_json(self, prompt: str) -> dict[str, object]:
        assert "逐句检查" in prompt, "production must not call the copy model"
        return {"accepted": True, "issues": []}

    async def generate(self, request: ImageGenerationRequest) -> ImageGenerationResult:
        self.image_requests.append(request)
        stream = BytesIO()
        poster = Image.new("RGB", (1152, 2048), "#d3e6f5")
        # Like the real model: cards end above the bottom band it was asked to keep blank.
        ImageDraw.Draw(poster).rectangle((40, 900, 1111, 1799), fill="#5b6fd6")
        poster.save(stream, format="PNG")
        return ImageGenerationResult(
            provider="comfly",
            model=self.image_model,
            request_fingerprint=request.request_fingerprint,
            provider_task_id=None,
            provider_upload_id=None,
            image_bytes=stream.getvalue(),
            media_type="image/png",
            width=1152,
            height=2048,
            attempts=1,
        )

    async def recognize(self, request: ImageTextRecognitionRequest) -> ImageTextRecognitionResult:
        raise AssertionError("production poster must use the poster-specific OCR contract")

    async def recognize_poster_region(
        self, request: PosterRegionRecognitionRequest
    ) -> ImageTextRecognitionResult:
        if self.before_ocr is not None:
            await self.before_ocr(request)
        self.ocr_requests.append(request)
        lines = {
            "masthead": ("小赛洞察", self.copy.title, self.copy.news_summary),
            "science": (self.copy.cards[0].heading, self.copy.cards[0].body),
            "learning": (self.copy.cards[1].heading, self.copy.cards[1].body),
            "brand": (self.copy.cards[2].heading, self.copy.cards[2].body),
            "footer": (),
        }[request.region_id]
        if request.region_id == "footer":
            # Footer text is deterministic, but the fake has no package snapshot;
            # its real bytes are checked separately in the footer unit tests.
            # Footer v6 draws no text: the band must read back blank.
            lines = ()
        return ImageTextRecognitionResult(
            recognized_lines=lines,
            request_fingerprint=request.request_fingerprint,
        )

    async def audit_visual(self, request: ImageQualityAuditRequest) -> ImageQualityAuditResult:
        self.visual_requests.append(request)
        return ImageQualityAuditResult(
            accepted=True,
            request_fingerprint=request.request_fingerprint,
        )


def _settings(*, max_ordinal: int = 3, morning: bool = True, noon: bool = False) -> Settings:
    return Settings(
        _env_file=None,
        wecom_enabled=True,
        wecom_auto_delivery_enabled=True,
        wecom_delivery_provider="group_webhook",
        wecom_group_webhook_key=SecretStr("synthetic-integration-key"),
        content_enabled=True,
        content_slot_mode_enabled=True,
        content_llm_rerank_enabled=False,
        content_morning_enabled=True,
        content_noon_enabled=True,
        wecom_infographic_producer_enabled=True,
        wecom_infographic_delivery_enabled=True,
        wecom_infographic_morning_enabled=morning,
        wecom_infographic_noon_enabled=noon,
        wecom_infographic_max_ordinal=max_ordinal,
        image_ocr_enabled=True,
        image_quality_audit_enabled=True,
    )


def _jpeg(index: int) -> bytes:
    image = Image.new("RGB", (1152, 2048), (20 * index, 90 + index, 170))
    stream = BytesIO()
    image.save(stream, format="PNG")
    return prepare_infographic_group_jpeg(stream.getvalue(), max_bytes=2 * 1024 * 1024)


def _install_synthetic_reference(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    approved_reference = tmp_path / "approved-reference.png"
    Image.new("RGB", (8, 8), "white").save(approved_reference)
    monkeypatch.setattr(wecom_news_infographic_service, "_REFERENCE_PATH", approved_reference)
    monkeypatch.setattr(
        wecom_news_infographic_service,
        "_APPROVED_CHARACTER_SHA256",
        sha256(approved_reference.read_bytes()).hexdigest(),
    )


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.parametrize("audit_shape", ["rejected", "invalid", "copy_model_down"])
async def test_advisory_rich_poster_persists_warnings_and_sends_exact_marked_jpeg(
    integration_context: IntegrationContext,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    audit_shape: str,
) -> None:
    """A bad content verdict does not veto v11, but identity and bytes still bind.

    Since the resilient advisory copy (v14) an unavailable copy model does not either: the
    poster keeps the exact fact and brand statement with neutral wording.
    """
    _install_synthetic_reference(monkeypatch, tmp_path)
    target = datetime(
        2026,
        10,
        {"rejected": 13, "invalid": 14, "copy_model_down": 15}[audit_shape],
        7,
        30,
        tzinfo=ZoneInfo("Asia/Shanghai"),
    )
    now = target + timedelta(minutes=2)
    window_id, job_ids, business_date, _ = await _seed_slot_delivery_lane(
        integration_context, target_at=target
    )
    fact = "科学课里的动手探究要求孩子先观察、提问和记录。"
    async with integration_context.session_factory() as session:
        window = await session.get(WeComDeliveryWindowModel, window_id)
        assert window is not None
        window.provider = "group_webhook"
        base = await session.get(WeComDeliveryJobModel, job_ids[0])
        assert base is not None
        package = await session.get(MaterialPackageModel, base.material_package_id)
        assert package is not None
        run = await session.get(CopyGenerationRunModel, package.run_id)
        assert run is not None and run.active_draft_version_id is not None
        _bind_valid_package_snapshot(package, run, business_date, fact_text=fact)
        copy = deepcopy(package.copy_snapshot)
        copy["prompt_version"] = "moments-generator-v19-exact-claim-span"
        copy["copywriting"] = (
            f"小赛洞察：{fact}\n赛先生鼓励孩子提问。\n"
            f"新闻来源：教育部科学新闻\n原文链接：{URL}\n#赛先生科学"
        )
        copy["parent_takeaway"] = "陪孩子围绕新闻提出问题，再一起查找原文依据。"
        copy["interaction"] = "你会请孩子先观察什么，再记录哪些猜想？"
        copy["source_note"] = f"教育部科学新闻 {URL}"
        package.copy_snapshot = copy
        active = await session.get(CopyDraftVersionModel, run.active_draft_version_id)
        assert active is not None
        active.copywriting = copy["copywriting"]
        active.parent_takeaway = copy["parent_takeaway"]
        active.interaction = copy["interaction"]
        active.source_note = copy["source_note"]
        await session.commit()

    class AdvisoryModels(_Models):
        def __init__(self) -> None:
            super().__init__()
            self.prompts: list[str] = []

        async def complete_json(self, prompt: str) -> dict[str, object]:
            self.prompts.append(prompt)
            if prompt.startswith(ADVISORY_GENERATION_PROMPT_VERSION):
                if audit_shape == "copy_model_down":
                    raise RuntimeError("infographic chat transport outcome unknown")
                return {
                    "top": "科学课里的动手探究启发我们先分清新闻原句和自己的推断。",
                    "news": "科学课里的动手探究意味着所有孩子都能在100小时内成为科学家。",
                    "child": "和孩子一起圈出报道原句，记录一个猜想，再查证哪里仍缺证据。",
                    "brand": "借科学课里的动手探究，赛先生会请孩子比较自己的解释和原文。",
                }
            assert prompt.startswith(ADVISORY_AUDIT_VERSION)
            if audit_shape != "rejected":
                return {"accepted": False, "issues": ["unsupported_assertion"]}
            return {
                "schema_version": "daily-news-infographic-moments-rich-audit-v1",
                "fact_bound": True,
                "brand_bound": True,
                "editorial_distinct": True,
                "child_specific": True,
                "non_redundant": True,
                "no_unsupported_assertions": False,
                "no_exaggerated_outcomes": False,
                "accepted": False,
                "issues": ["unsupported_assertion", "exaggerated_outcome"],
            }

        async def audit_visual(self, request: ImageQualityAuditRequest) -> ImageQualityAuditResult:
            self.visual_requests.append(request)
            return ImageQualityAuditResult(
                accepted=False, request_fingerprint=request.request_fingerprint
            )

    settings = _settings(max_ordinal=1).model_copy(
        update={"wecom_infographic_review_mode": "advisory"}
    )
    blobs: dict[str, bytes] = {}
    models = AdvisoryModels()
    producer = NewsInfographicProducer(
        session_factory=integration_context.session_factory,
        image_store=_Objects(blobs),
        models=models,
        settings=settings,
        clock=lambda: now,
    )
    assert await producer.reconcile() == 1
    assert await producer.execute_next("advisory-fake-producer")
    async with integration_context.session_factory() as session:
        poster = await session.scalar(
            select(NewsInfographicJobModel).where(NewsInfographicJobModel.base_job_id == job_ids[0])
        )
        assert poster is not None
        assert poster.status == "ready", (poster.status, poster.safe_error_code)
        assert poster.quality_mode == "advisory"
        assert poster.copy_intent_at and poster.audit_intent_at and poster.image_intent_at
        assert len(models.prompts) == 2 and len(models.image_requests) == 1
        assert poster.copy_candidate_snapshot is not None
        if audit_shape == "copy_model_down":
            assert poster.copy_candidate_snapshot["news_body"] == (
                fact + "值得追问的是，这件事和我们的生活有什么关系？"
            )
            assert "layout_overflow" in poster.warning_codes
        else:
            assert "100小时" in poster.copy_candidate_snapshot["news_body"]
        assert poster.copy_audit_snapshot is not None
        if audit_shape == "rejected":
            assert poster.copy_audit_snapshot["accepted"] is False
        else:
            assert poster.copy_audit_snapshot["status"] == "schema_invalid"
        assert {
            "advisory_unverified",
            "layout_unverified",
            "body_ocr_unavailable",
            "visual_failed",
            "copy_audit_rejected" if audit_shape == "rejected" else "copy_audit_schema_invalid",
            # Footer v6 carries no text, so the advisory footer OCR is recorded as unchecked.
            "footer_ocr_unavailable",
        } <= set(poster.warning_codes)
        assert poster.ocr_status == "not_checked"
        assert poster.visual_status == "failed"
        assert poster.footer_ocr_status == "not_checked"
        assert poster.raw_sha256 and poster.composite_sha256 and poster.footer_sha256
        assert poster.delivery_sha256 and poster.delivery_byte_size
        package = await session.get(MaterialPackageModel, base.material_package_id)
        assert package is not None
        case = _input_from_package(package)
        marked = prepare_unmarked_advisory_raster(blobs[poster.raw_sha256])
        assert sha256(marked).hexdigest() == poster.composite_sha256
        formal = render_exact_source_footer(marked, case, mode="formal", trim=True)
        assert sha256(formal.image_bytes).hexdigest() == poster.footer_sha256
        expected = prepare_infographic_group_jpeg(
            formal.image_bytes, max_bytes=settings.wecom_group_max_image_bytes
        )
        assert sha256(expected).hexdigest() == poster.delivery_sha256
        assert blobs[poster.delivery_sha256] == expected
        with Image.open(BytesIO(expected)) as image:
            image.load()
            # The blank bottom band is trimmed to the side margin below the last card.
            assert image.size == (1152, 1800 + TRIM_MARGIN)
            assert (poster.delivery_width, poster.delivery_height) == image.size
            top_pixel = image.getpixel((5, 5))
            assert isinstance(top_pixel, tuple)
            # No painted warning banner since advisory-notice-v2: the top stays the image itself.
            assert not top_pixel[0] > top_pixel[1] * 2
        base = await session.get(WeComDeliveryJobModel, job_ids[0])
        assert base is not None
        base.status = "delivered"
        base.text_status = "delivered"
        base.image_status = "delivered"
        base.completed_at = now
        await session.commit()

    async with integration_context.session_factory() as session:
        poster = await session.scalar(
            select(NewsInfographicJobModel).where(NewsInfographicJobModel.base_job_id == job_ids[0])
        )
        base = await session.get(WeComDeliveryJobModel, job_ids[0])
        window = await session.get(WeComDeliveryWindowModel, window_id)
        assert poster is not None and base is not None and window is not None
        package = await session.get(MaterialPackageModel, base.material_package_id)
        run = await session.get(CopyGenerationRunModel, poster.copy_generation_run_id)
        selection = await session.get(ContentSlotSelectionModel, poster.content_slot_selection_id)
        assert _valid_ready_pair(poster, base, window, settings=settings)
        assert _valid_source_lineage(poster, base, window, package, run, selection)

    group = _Group()
    supplement = WeComInfographicSupplementExecutor(
        session_factory=integration_context.session_factory,
        client=group,
        image_store=_Objects(blobs),
        settings=settings,
        clock=lambda: now + timedelta(minutes=1),
    )
    assert await supplement.reconcile() == 1
    assert await supplement.execute_next("advisory-fake-dispatcher")
    assert group.messages == [expected]
    assert await supplement.reconcile() == 0
    assert not await supplement.execute_next("advisory-fake-dispatcher")


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.parametrize(
    ("audit_rejected", "fact_text", "day"),
    [
        (True, "教育部介绍科学课探究的相关内容。", 9),
        (False, "教育部介绍科学课探究的相关内容。", 10),
        (False, "教育部举行新闻发布会，介绍教育改革工作进展。", 11),
        (False, "教育部开会。", 12),
    ],
)
async def test_evidence_first_copy_skips_copy_model_and_obeys_independent_audit(
    integration_context: IntegrationContext,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    audit_rejected: bool,
    fact_text: str,
    day: int,
) -> None:
    _install_synthetic_reference(monkeypatch, tmp_path)
    target = datetime(2026, 10, day, 7, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    now = target + timedelta(minutes=2)
    window_id, job_ids, business_date, _ = await _seed_slot_delivery_lane(
        integration_context, target_at=target
    )
    async with integration_context.session_factory() as session:
        window = await session.get(WeComDeliveryWindowModel, window_id)
        assert window is not None
        window.provider = "group_webhook"
        for base_id in job_ids:
            base = await session.get(WeComDeliveryJobModel, base_id)
            assert base is not None
            package = await session.get(MaterialPackageModel, base.material_package_id)
            assert package is not None
            run = await session.get(CopyGenerationRunModel, package.run_id)
            assert run is not None
            _bind_valid_package_snapshot(package, run, business_date, fact_text=fact_text)
            copy_snapshot = deepcopy(package.copy_snapshot)
            copy_snapshot["claims"].append(
                {
                    "claim_id": "opinion-1",
                    "kind": "opinion",
                    "text": "孩子可以先说出自己的猜想。",
                    "evidence_ids": [],
                    "brand_chunk_ids": [],
                }
            )
            package.copy_snapshot = copy_snapshot
        await session.commit()

    class CopyModels(_Models):
        def __init__(self) -> None:
            super().__init__()
            self.copy_prompts: list[str] = []

        async def complete_json(self, prompt: str) -> dict[str, object]:
            self.copy_prompts.append(prompt)
            assert "逐句检查" in prompt
            issues = ("unsupported",) if audit_rejected else ()
            return {"accepted": not audit_rejected, "issues": issues}

    models = CopyModels()
    if len(fact_text) >= 12:
        models.copy = build_evidence_first_copy(
            validate_package_snapshot(_evidence_ready_payload(fact_text))
        )
    producer = NewsInfographicProducer(
        session_factory=integration_context.session_factory,
        image_store=_Objects({}),
        models=models,
        settings=_settings(max_ordinal=1),
        clock=lambda: now,
    )
    assert await producer.reconcile() == 1
    assert await producer.execute_next("claim-scoped-copy-test")
    async with integration_context.session_factory() as session:
        poster = await session.scalar(
            select(NewsInfographicJobModel).where(NewsInfographicJobModel.base_job_id == job_ids[0])
        )
        assert poster is not None
        assert poster.copy_intent_at is None, (poster.status, poster.safe_error_code)
        assert poster.copy_request_fingerprint is None
        if len(fact_text) < 12:
            assert poster.status == "failed"
            assert poster.safe_error_code == "copy_preflight_failed"
            assert poster.audit_intent_at is None
            assert poster.image_intent_at is None
            assert models.copy_prompts == []
            assert models.image_requests == []
            return
        assert poster.audit_intent_at is not None
        assert len(models.copy_prompts) == 1
        if audit_rejected:
            assert poster.status == "failed"
            assert poster.safe_error_code == "copy_audit_rejected"
            assert poster.image_intent_at is None
            assert models.image_requests == []
        else:
            assert poster.image_intent_at is not None
            assert len(models.image_requests) == 1
            assert fact_text in models.image_requests[0].prompt
            assert "科学机制" in models.image_requests[0].prompt


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.parametrize(
    ("field", "day"),
    [
        ("selected_event_id", 5),
        ("business_date", 6),
        ("content_slot", 7),
        ("recipient_id", 8),
    ],
)
async def test_tampered_reserved_identity_stops_before_any_paid_intent(
    integration_context: IntegrationContext,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    field: str,
    day: int,
) -> None:
    _install_synthetic_reference(monkeypatch, tmp_path)
    target = datetime(2026, 10, day, 7, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    now = target + timedelta(minutes=2)
    window_id, job_ids, business_date, _ = await _seed_slot_delivery_lane(
        integration_context, target_at=target
    )
    async with integration_context.session_factory() as session:
        window = await session.get(WeComDeliveryWindowModel, window_id)
        assert window is not None
        window.provider = "group_webhook"
        for base_id in job_ids:
            base = await session.get(WeComDeliveryJobModel, base_id)
            assert base is not None
            package = await session.get(MaterialPackageModel, base.material_package_id)
            assert package is not None
            run = await session.get(CopyGenerationRunModel, package.run_id)
            assert run is not None
            _bind_valid_package_snapshot(package, run, business_date)
        await session.commit()
    models = _Models()
    producer = NewsInfographicProducer(
        session_factory=integration_context.session_factory,
        image_store=_Objects({}),
        models=models,
        settings=_settings(max_ordinal=1),
        clock=lambda: now,
    )
    assert await producer.reconcile() == 1
    async with integration_context.session_factory() as session:
        poster = await session.scalar(
            select(NewsInfographicJobModel).where(NewsInfographicJobModel.base_job_id == job_ids[0])
        )
        assert poster is not None
        replacement: object = {
            "selected_event_id": uuid4(),
            "business_date": business_date - timedelta(days=1),
            "content_slot": "noon",
            "recipient_id": "wrong-recipient",
        }[field]
        setattr(poster, field, replacement)
        await session.commit()
    assert await producer.execute_next("tampered-lineage-review")
    async with integration_context.session_factory() as session:
        poster = await session.scalar(
            select(NewsInfographicJobModel).where(NewsInfographicJobModel.base_job_id == job_ids[0])
        )
        assert poster is not None
        assert poster.status == "failed"
        assert poster.safe_error_code == "input_preflight_failed"
        assert poster.copy_intent_at is None
        assert poster.audit_intent_at is None
        assert poster.image_intent_at is None
    assert models.image_requests == []


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
@pytest.mark.parametrize(
    ("failure_stage", "expected_code", "image_calls"),
    [
        ("preflight", "overlay_preflight_failed", 0),
        ("render", "overlay_render_failed", 1),
        ("ocr", "delivery_ocr_failed", 1),
    ],
)
async def test_overlay_or_ocr_failure_never_enqueues_a_supplement(
    integration_context: IntegrationContext,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    failure_stage: str,
    expected_code: str,
    image_calls: int,
) -> None:
    _install_synthetic_reference(monkeypatch, tmp_path)
    day = {"preflight": 2, "render": 3, "ocr": 4}[failure_stage]
    target = datetime(2026, 10, day, 7, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    now = target + timedelta(minutes=2)
    window_id, job_ids, business_date, _ = await _seed_slot_delivery_lane(
        integration_context, target_at=target
    )
    async with integration_context.session_factory() as session:
        window = await session.get(WeComDeliveryWindowModel, window_id)
        assert window is not None
        window.provider = "group_webhook"
        for base_id in job_ids:
            base = await session.get(WeComDeliveryJobModel, base_id)
            assert base is not None
            package = await session.get(MaterialPackageModel, base.material_package_id)
            assert package is not None
            run = await session.get(CopyGenerationRunModel, package.run_id)
            assert run is not None
            _bind_valid_package_snapshot(package, run, business_date)
        await session.commit()
    settings = _settings(max_ordinal=1)
    blobs: dict[str, bytes] = {}
    models = _Models()
    producer = NewsInfographicProducer(
        session_factory=integration_context.session_factory,
        image_store=_Objects(blobs),
        models=models,
        settings=settings,
        clock=lambda: now,
    )
    assert await producer.reconcile() == 1

    def fail_overlay(*_args: object, **_kwargs: object) -> None:
        raise TextOverlayError("synthetic deterministic layout failure")

    async def fail_ocr(
        request: PosterRegionRecognitionRequest,
    ) -> ImageTextRecognitionResult:
        return ImageTextRecognitionResult(
            recognized_lines=("wrong",),
            request_fingerprint=request.request_fingerprint,
        )

    with monkeypatch.context() as patcher:
        if failure_stage == "preflight":
            patcher.setattr(
                wecom_news_infographic_service, "preflight_text_overlay_layout", fail_overlay
            )
        elif failure_stage == "render":
            patcher.setattr(
                wecom_news_infographic_service, "render_exact_text_overlay", fail_overlay
            )
        else:
            patcher.setattr(models, "recognize_poster_region", fail_ocr)
        assert await producer.execute_next("synthetic-producer")

    async with integration_context.session_factory() as session:
        poster = await session.scalar(
            select(NewsInfographicJobModel).where(NewsInfographicJobModel.base_job_id == job_ids[0])
        )
        assert poster is not None
        assert poster.status == "failed"
        assert poster.safe_error_code == expected_code
        assert (poster.image_intent_at is not None) == bool(image_calls)
        assert poster.visual_status != "passed"
        base = await session.get(WeComDeliveryJobModel, job_ids[0])
        assert base is not None
        base.status = "delivered"
        base.text_status = "delivered"
        base.image_status = "delivered"
        base.completed_at = now
        await session.commit()
    assert len(models.image_requests) == image_calls
    group = _Group()
    supplement = WeComInfographicSupplementExecutor(
        session_factory=integration_context.session_factory,
        client=group,
        image_store=_Objects(blobs),
        settings=settings,
        clock=lambda: now + timedelta(minutes=1),
    )
    assert await supplement.reconcile() == 0
    assert not await supplement.execute_next("synthetic-dispatcher")
    assert group.messages == []


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_three_siblings_reconcile_independently_and_unknown_is_not_replayed(
    integration_context: IntegrationContext,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    _install_synthetic_reference(monkeypatch, tmp_path)
    target = datetime(2026, 9, 23, 7, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    now = target + timedelta(minutes=2)
    window_id, job_ids, business_date, _ = await _seed_slot_delivery_lane(
        integration_context, target_at=target
    )
    async with integration_context.session_factory() as session:
        window = await session.get(WeComDeliveryWindowModel, window_id)
        assert window is not None
        window.provider = "group_webhook"
        for job_id in job_ids:
            base = await session.get(WeComDeliveryJobModel, job_id)
            assert base is not None
            package = await session.get(MaterialPackageModel, base.material_package_id)
            assert package is not None
            run = await session.get(CopyGenerationRunModel, package.run_id)
            assert run is not None
            _bind_valid_package_snapshot(package, run, business_date)
        await session.commit()

    settings = _settings(morning=False, noon=True)
    producer = NewsInfographicProducer(
        session_factory=integration_context.session_factory,
        image_store=SimpleNamespace(),
        models=SimpleNamespace(image_model="gpt-image-2.5-sunburst", copy_model="fake-copy-v1"),
        settings=settings,
        clock=lambda: now,
    )
    assert await producer.reconcile() == 0  # No noon packages exist in this fixture.
    settings = _settings(max_ordinal=1)
    producer = NewsInfographicProducer(
        session_factory=integration_context.session_factory,
        image_store=SimpleNamespace(),
        models=SimpleNamespace(image_model="gpt-image-2.5-sunburst", copy_model="fake-copy-v1"),
        settings=settings,
        clock=lambda: now,
    )
    assert await producer.reconcile() == 1
    assert await producer.reconcile() == 0
    settings = _settings(max_ordinal=3)
    producer = NewsInfographicProducer(
        session_factory=integration_context.session_factory,
        image_store=SimpleNamespace(),
        models=SimpleNamespace(image_model="gpt-image-2.5-sunburst", copy_model="fake-copy-v1"),
        settings=settings,
        clock=lambda: now,
    )
    assert await producer.reconcile() == 2
    assert await producer.reconcile() == 0

    async with integration_context.session_factory() as session:
        base = await session.get(WeComDeliveryJobModel, job_ids[0])
        assert base is not None
        package = await session.get(MaterialPackageModel, base.material_package_id)
        assert package is not None
        run = await session.get(CopyGenerationRunModel, package.run_id)
        selection = await session.get(ContentSlotSelectionModel, base.content_slot_selection_id)
        window = await session.get(WeComDeliveryWindowModel, window_id)
        assert run is not None and selection is not None and window is not None
        case = _input_from_package(package)
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
        validate_exact_source_footer_layout(case, mode="formal")
        _approved_reference()

    generated: dict[str, bytes] = {}
    fake_models = _Models()
    fake_models.image_model = "gpt-image-2.5-sunburst"

    async def assert_persisted_group_intent(request: PosterRegionRecognitionRequest) -> None:
        async with integration_context.session_factory() as session:
            claimed = await session.scalar(
                select(NewsInfographicJobModel).where(
                    NewsInfographicJobModel.base_job_id == job_ids[0]
                )
            )
            assert claimed is not None and claimed.status == "running"
            assert claimed.ocr_intent_at is not None
            assert claimed.ocr_request_fingerprint != request.request_fingerprint
            if request.region_id == "footer":
                assert claimed.footer_ocr_intent_at is not None
                assert claimed.footer_ocr_request_fingerprint != request.request_fingerprint

    fake_models.before_ocr = assert_persisted_group_intent
    trial_producer = NewsInfographicProducer(
        session_factory=integration_context.session_factory,
        image_store=_Objects(generated),
        models=fake_models,
        settings=settings,
        clock=lambda: now,
    )
    assert await trial_producer.execute_next("synthetic-producer")
    async with integration_context.session_factory() as session:
        first = await session.scalar(
            select(NewsInfographicJobModel).where(NewsInfographicJobModel.base_job_id == job_ids[0])
        )
        assert first is not None and first.status == "ready", (
            first.status if first else None,
            first.safe_error_code if first else None,
            first.stage if first else None,
            len(fake_models.image_requests),
        )
        assert first.image_intent_at is not None
        assert first.ocr_status == first.footer_ocr_status == first.visual_status == "passed"
        # Footer v6 draws nothing on a formal poster: footer bytes equal the composite.
        assert first.footer_sha256 == first.composite_sha256
        assert (
            len(
                {
                    first.raw_sha256,
                    first.composite_sha256,
                    first.delivery_sha256,
                }
            )
            == 3
        )
        assert first.composite_sha256 is not None
        assert first.composite_byte_size == len(generated[first.composite_sha256])
        assert first.raw_sha256 is not None
        assert first.footer_sha256 is not None
        with Image.open(BytesIO(generated[first.composite_sha256])) as composite:
            assert composite.format == "PNG"
            assert composite.size == (1152, 2048)
            overlay_pixel = composite.getpixel((100, 200))
            assert overlay_pixel != (211, 230, 245)
        with Image.open(BytesIO(generated[first.footer_sha256])) as with_footer:
            assert with_footer.getpixel((100, 200)) == overlay_pixel
        assert first.delivery_media_type == "image/jpeg"
    assert len(fake_models.image_requests) == 1
    assert "x35-874、y42-520" in fake_models.image_requests[0].prompt
    assert "除机器人胸前AI徽章外" in fake_models.image_requests[0].prompt
    assert [request.region_id for request in fake_models.ocr_requests] == [
        "masthead",
        "science",
        "learning",
        "brand",
        "footer",
    ]
    with Image.open(BytesIO(fake_models.ocr_requests[0].image_bytes)) as main_region:
        assert main_region.size == (850, 530)
    with Image.open(BytesIO(fake_models.ocr_requests[-1].image_bytes)) as footer_region:
        assert footer_region.size == (1152, 190)
    assert len({request.request_fingerprint for request in fake_models.ocr_requests}) == 5
    assert len(fake_models.visual_requests) == 1
    visual_request = fake_models.visual_requests[0]
    assert visual_request.rubric_version == (
        wecom_news_infographic_service._POSTER_VISUAL_RUBRIC_VERSION
    )
    assert "Chinese news poster" in visual_request.criteria[0]
    assert "science-news poster" not in " ".join(visual_request.criteria)

    async def interrupt_second_region(request: PosterRegionRecognitionRequest) -> None:
        if request.region_id == "science":
            raise TimeoutError("simulated ambiguous poster OCR result")

    fake_models.before_ocr = interrupt_second_region
    assert await trial_producer.execute_next("synthetic-producer")
    async with integration_context.session_factory() as session:
        interrupted = await session.scalar(
            select(NewsInfographicJobModel).where(NewsInfographicJobModel.base_job_id == job_ids[1])
        )
        assert interrupted is not None and interrupted.status == "result_unknown"
        assert interrupted.ocr_intent_at is not None
        assert interrupted.footer_ocr_intent_at is None
        assert interrupted.safe_error_code == "production_stage_unknown"
    assert await trial_producer.reconcile() == 0  # Unknown is never requeued.

    bodies: dict[str, bytes] = {}
    async with integration_context.session_factory() as session:
        posters = (
            await session.scalars(
                select(NewsInfographicJobModel)
                .where(NewsInfographicJobModel.base_job_id.in_(job_ids))
                .order_by(NewsInfographicJobModel.sequence_ordinal)
            )
        ).all()
        assert [item.sequence_ordinal for item in posters] == [1, 2, 3]
        for poster in posters:
            base = await session.get(WeComDeliveryJobModel, poster.base_job_id)
            assert base is not None
            base.status = "delivered"
            base.text_status = "delivered"
            base.image_status = "delivered"
            base.completed_at = now
            body = _jpeg(poster.sequence_ordinal)
            digest = sha256(body).hexdigest()
            bodies[digest] = body
            poster.status = "ready"
            poster.ocr_status = "passed"
            poster.footer_ocr_status = "passed"
            poster.visual_status = "passed"
            poster.delivery_sha256 = digest
            poster.delivery_byte_size = len(body)
            poster.delivery_media_type = "image/jpeg"
            poster.delivery_width = 1152
            poster.delivery_height = 2048
        await session.commit()

    # A ready poster cannot bypass its own original-image confirmation. Other
    # siblings may enqueue while this one remains ineligible.
    async with integration_context.session_factory() as session:
        withheld = await session.get(WeComDeliveryJobModel, job_ids[0])
        assert withheld is not None
        withheld.image_status = "pending"
        await session.commit()

    group = _Group(timeout_at=2)
    supplement = WeComInfographicSupplementExecutor(
        session_factory=integration_context.session_factory,
        client=group,
        image_store=_Objects(bodies),
        settings=settings,
        clock=lambda: now + timedelta(minutes=1),
    )
    assert await supplement.reconcile() == 2
    async with integration_context.session_factory() as session:
        withheld = await session.get(WeComDeliveryJobModel, job_ids[0])
        assert withheld is not None
        withheld.image_status = "delivered"
        await session.commit()
    assert await supplement.reconcile() == 1
    assert await supplement.reconcile() == 0

    async with integration_context.session_factory() as session:
        first_base = await session.get(WeComDeliveryJobModel, job_ids[0])
        first_window = await session.get(WeComDeliveryWindowModel, window_id)
        assert first_base is not None and first_window is not None
        assert _valid_ready_pair(posters[0], first_base, first_window, settings=settings)
        package = await session.get(MaterialPackageModel, posters[0].material_package_id)
        run = await session.get(CopyGenerationRunModel, posters[0].copy_generation_run_id)
        selection = await session.get(
            ContentSlotSelectionModel, posters[0].content_slot_selection_id
        )
        assert _valid_source_lineage(posters[0], first_base, first_window, package, run, selection)
        wrong_event = deepcopy(posters[0])
        wrong_event.selected_event_id = uuid4()
        assert not _valid_source_lineage(
            wrong_event, first_base, first_window, package, run, selection
        )
        assert package is not None
        changed_package = deepcopy(package)
        changed_package.topic_snapshot = {**package.topic_snapshot, "title": "另一条新闻"}
        assert not _valid_source_lineage(
            posters[0], first_base, first_window, changed_package, run, selection
        )
        wrong_slot = deepcopy(posters[0])
        wrong_slot.content_slot_selection_id = uuid4()
        assert not _valid_ready_pair(wrong_slot, first_base, first_window, settings=settings)
        wrong_provider = deepcopy(first_window)
        wrong_provider.provider = "app_message"
        assert not _valid_ready_pair(posters[0], first_base, wrong_provider, settings=settings)
        projection = await read_wecom_infographic_status(job_ids[0], session)
        assert projection.infographic_status == "ready"
        assert projection.supplement_status == "queued"
        assert projection.delivery_sha256 == posters[0].delivery_sha256
        assert projection.attempts == []

    assert await supplement.execute_next("synthetic-worker")
    assert await supplement.execute_next("synthetic-worker")
    assert await supplement.execute_next("synthetic-worker")
    assert not await supplement.execute_next("synthetic-worker")
    assert [sha256(item).hexdigest() for item in group.messages] == [
        item.delivery_sha256 for item in posters
    ]
    async with integration_context.session_factory() as session:
        states = (
            await session.scalars(
                select(WeComInfographicSupplementModel)
                .where(WeComInfographicSupplementModel.base_job_id.in_(job_ids))
                .order_by(WeComInfographicSupplementModel.created_at)
            )
        ).all()
        assert sorted(item.status for item in states) == [
            "delivered",
            "delivered",
            "result_unknown",
        ]
        assert (
            await session.scalar(
                select(func.count(WeComInfographicAttemptModel.id)).where(
                    WeComInfographicAttemptModel.supplement_id.in_(item.id for item in states)
                )
            )
            == 3
        )
        for job_id in job_ids:
            base = await session.get(WeComDeliveryJobModel, job_id)
            assert base is not None and base.status == "delivered"
        unknown_projection = await read_wecom_infographic_status(job_ids[1], session)
        assert unknown_projection.supplement_status == "result_unknown"
        assert [item.result_state for item in unknown_projection.attempts] == ["unknown"]

    # The date ceiling is enforced by a PostgreSQL advisory lock and the committed intent
    # count of the scheduled slots, independently of which slot/package supplied the rows.
    over_limit_id = None
    over_limit_token = None
    async with integration_context.session_factory() as session:
        for poster in posters[1:]:
            persisted = await session.get(NewsInfographicJobModel, poster.id)
            assert persisted is not None
            persisted.image_intent_at = now
        for base_id in job_ids:
            base = await session.get(WeComDeliveryJobModel, base_id)
            assert base is not None
            run = await session.get(
                CopyGenerationRunModel,
                (await session.get(MaterialPackageModel, base.material_package_id)).run_id,
            )
            assert run is not None
            for version in (2, 3) if base_id != job_ids[0] else (2, 3, 4):
                variant_id = await _add_delivery_variant(
                    session,
                    source_job_id=base_id,
                    package_version=version,
                    mode="formal",
                    status="queued",
                )
                variant = await session.get(WeComDeliveryJobModel, variant_id)
                assert variant is not None
                is_over_limit = base_id == job_ids[0] and version == 4
                token = uuid4()
                candidate = NewsInfographicJobModel(
                    id=uuid4(),
                    base_job_id=variant_id,
                    material_package_id=variant.material_package_id,
                    copy_generation_run_id=run.id,
                    content_slot_selection_id=variant.content_slot_selection_id,
                    sequence_ordinal=variant.sequence_ordinal,
                    selected_event_id=run.selected_event_id,
                    selected_event_version_id=run.selected_event_version_id,
                    business_date=business_date,
                    content_slot="morning",
                    recipient_id="default",
                    provider="group_webhook",
                    package_version=version,
                    policy_fingerprint=stable_key("synthetic-quota-policy", base_id, version),
                    input_fingerprint="a" * 64,
                    status="running",
                    stage="preflight",
                    image_intent_at=None if is_over_limit else now,
                    lease_owner="synthetic-quota-worker",
                    lease_token=token,
                    lease_expires_at=now + timedelta(minutes=10),
                )
                session.add(candidate)
                if is_over_limit:
                    over_limit_id, over_limit_token = candidate.id, token
        await session.commit()
    assert over_limit_id is not None and over_limit_token is not None
    quota_producer = NewsInfographicProducer(
        session_factory=integration_context.session_factory,
        image_store=_Objects(generated),
        models=fake_models,
        settings=settings.model_copy(update={"wecom_infographic_daily_image_limit": 9}),
        clock=lambda: now,
    )
    assert not await quota_producer._intent(over_limit_id, over_limit_token, "image", "b" * 64)
    async with integration_context.session_factory() as session:
        stale = await session.get(NewsInfographicJobModel, over_limit_id)
        assert stale is not None
        stale.lease_expires_at = now - timedelta(seconds=1)
        await session.commit()
    assert not await trial_producer.execute_next("new-producer")
    async with integration_context.session_factory() as session:
        stale = await session.get(NewsInfographicJobModel, over_limit_id)
        assert stale is not None and stale.status == "result_unknown"
        assert stale.safe_error_code == "production_lease_expired"
    async with integration_context.session_factory() as session:
        count = await session.scalar(
            select(func.count(NewsInfographicJobModel.id)).where(
                NewsInfographicJobModel.business_date == business_date,
                NewsInfographicJobModel.image_intent_at.is_not(None),
            )
        )
        assert count == 9

    # A corrupted child fingerprint must not turn a previously delivered image
    # into a second physical group send if its row is accidentally re-queued.
    sent_before = len(group.messages)
    async with integration_context.session_factory() as session:
        wrong_child = await session.scalar(
            select(WeComInfographicSupplementModel).where(
                WeComInfographicSupplementModel.base_job_id == job_ids[0]
            )
        )
        assert wrong_child is not None
        wrong_child.status = "queued"
        wrong_child.next_attempt_at = now
        wrong_child.completed_at = None
        wrong_child.request_fingerprint = "f" * 64
        await session.commit()
    assert await supplement.execute_next("synthetic-worker")
    assert len(group.messages) == sent_before
    async with integration_context.session_factory() as session:
        wrong_child = await session.get(WeComInfographicSupplementModel, wrong_child.id)
        assert wrong_child is not None and wrong_child.status == "result_unknown"


@pytest.mark.integration
@pytest.mark.asyncio(loop_scope="session")
async def test_supplement_confirmed_transient_retry_is_bounded_and_windowed(
    integration_context: IntegrationContext,
) -> None:
    target = datetime(2026, 9, 24, 7, 30, tzinfo=ZoneInfo("Asia/Shanghai"))
    now = target + timedelta(minutes=2)
    window_id, job_ids, business_date, _ = await _seed_slot_delivery_lane(
        integration_context, target_at=target
    )
    body = _jpeg(1)
    digest = sha256(body).hexdigest()
    async with integration_context.session_factory() as session:
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
        assert run is not None and base.content_slot_selection_id is not None
        _bind_valid_package_snapshot(package, run, business_date)
        case = _input_from_package(package)
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
                delivery_sha256=digest,
                delivery_byte_size=len(body),
                delivery_media_type="image/jpeg",
                delivery_width=1152,
                delivery_height=2048,
                ocr_status="passed",
                footer_ocr_status="passed",
                visual_status="passed",
            )
        )
        await session.commit()

    moment = [now + timedelta(minutes=1)]
    group = _TransientGroup()
    executor = WeComInfographicSupplementExecutor(
        session_factory=integration_context.session_factory,
        client=group,
        image_store=_Objects({digest: body}),
        settings=_settings(),
        clock=lambda: moment[0],
    )
    assert await executor.reconcile() == 1
    assert await executor.execute_next("worker-1")
    async with integration_context.session_factory() as session:
        supplement = await session.scalar(
            select(WeComInfographicSupplementModel).where(
                WeComInfographicSupplementModel.base_job_id == job_ids[0]
            )
        )
        assert supplement is not None and supplement.status == "queued"
        assert supplement.attempt_count == 1
        assert supplement.safe_error_code == "wecom_transient"
    assert not await executor.execute_next("worker-2")
    moment[0] += timedelta(seconds=3)
    assert await executor.execute_next("worker-2")
    assert not await executor.execute_next("worker-3")
    assert len(group.messages) == 2
    async with integration_context.session_factory() as session:
        supplement = await session.scalar(
            select(WeComInfographicSupplementModel).where(
                WeComInfographicSupplementModel.base_job_id == job_ids[0]
            )
        )
        assert supplement is not None and supplement.status == "delivered"
        attempts = (
            await session.scalars(
                select(WeComInfographicAttemptModel)
                .where(WeComInfographicAttemptModel.supplement_id == supplement.id)
                .order_by(WeComInfographicAttemptModel.attempt_number)
            )
        ).all()
        assert [item.result_state for item in attempts] == ["failed", "succeeded"]

    # A response received after the durable lease elapsed must not become a
    # retryable queued send, even if the provider's rejection itself is known.
    late_token = uuid4()
    moment[0] += timedelta(minutes=3)
    async with integration_context.session_factory() as session:
        supplement = await session.scalar(
            select(WeComInfographicSupplementModel).where(
                WeComInfographicSupplementModel.base_job_id == job_ids[0]
            )
        )
        assert supplement is not None
        supplement.status = "running"
        supplement.attempt_count = 3
        supplement.lease_token = late_token
        supplement.lease_expires_at = moment[0] - timedelta(seconds=1)
        await session.commit()
    await executor._record_result(
        supplement.id, late_token, state="failed", code="wecom_transient", retryable=True
    )
    async with integration_context.session_factory() as session:
        supplement = await session.get(WeComInfographicSupplementModel, supplement.id)
        assert supplement is not None
        assert supplement.status == "result_unknown"
        assert supplement.safe_error_code == "supplement_lease_expired_after_send"
    assert not await executor.execute_next("worker-4")
