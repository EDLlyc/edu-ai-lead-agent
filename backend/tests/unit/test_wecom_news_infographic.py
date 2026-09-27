"""Provider-free portrait supplement identity, bytes and default-off guards."""

# ruff: noqa: RUF001 -- Chinese punctuation is part of exact poster OCR expectations.

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from hashlib import sha256
from io import BytesIO
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest
from app.api.v1.routes.wecom_deliveries import router as wecom_router
from app.application.ports.image_validation import ImageTextRecognitionResult
from app.application.services import wecom_news_infographic as infographic_service
from app.application.services.news_infographic import (
    EVIDENCE_FIRST_COPY_VERSION,
    PosterCard,
    PosterCopy,
    build_evidence_first_copy,
    build_image_prompt,
)
from app.application.services.news_infographic_footer import (
    FOOTER_TOP,
    render_exact_source_footer,
)
from app.application.services.wecom_infographic_supplement import _valid_ready_pair
from app.application.services.wecom_news_infographic import (
    _assert_job_lineage,
    _assert_lineage,
    _enabled_slot,
    _moments_binding_from_accepted_models,
    _poster_ocr_regions,
    _poster_region_text_matches,
    prepare_infographic_group_jpeg,
)
from app.core.config import Settings
from app.domain.news_infographic import InfographicInputError, validate_package_snapshot
from app.infrastructure.db.models import (
    ContentSlotSelectionModel,
    CopyDraftVersionModel,
    CopyGenerationRunModel,
    MaterialPackageModel,
    NewsInfographicJobModel,
    WeComDeliveryJobModel,
    WeComDeliveryWindowModel,
)
from app.infrastructure.wecom.group_webhook import prepare_group_webhook_image
from fastapi.openapi.utils import get_openapi
from PIL import Image, ImageChops
from pydantic import SecretStr, ValidationError
from tests.unit.test_news_infographic import package_payload
from tests.unit.test_news_infographic_rich_copy import _binding, _frozen_real_cases


def _raster() -> bytes:
    stream = BytesIO()
    Image.new("RGB", (1152, 2048), "#e9f5ff").save(stream, format="PNG")
    return stream.getvalue()


def _copy() -> PosterCopy:
    return PosterCopy(
        title="科学课怎样探究",
        news_summary="孩子从真实问题出发，观察并记录。",
        news_claim_ids=("fact-1",),
        cards=(
            PosterCard(
                kind="science", heading="动手做", body="观察身边的变化。", claim_ids=("fact-1",)
            ),
            PosterCard(
                kind="learning", heading="学什么", body="提出问题再验证。", claim_ids=("fact-1",)
            ),
            PosterCard(
                kind="brand",
                heading="赛先生鼓励孩子提问",
                body="赛先生鼓励孩子提问。",
                claim_ids=("brand-1",),
            ),
        ),
    )


def test_formal_rich_binding_uses_the_actual_active_same_package_moments_draft() -> None:
    case = _frozen_real_cases()[0]
    snapshot = _binding(case).copy_snapshot.model_dump(mode="python")
    snapshot["source_note"] = case.source_footer
    package = MaterialPackageModel(
        id=case.package_id,
        run_id=case.copy_generation_run_id,
        copy_snapshot=snapshot,
        validation_snapshot={"passed": True, "result_fingerprint": case.validation_fingerprint},
        audit_snapshot={"accepted": True, "result_fingerprint": case.audit_fingerprint},
    )
    run = CopyGenerationRunModel(
        id=case.copy_generation_run_id, active_draft_version_id=case.draft_version_id
    )
    draft = CopyDraftVersionModel(
        id=case.draft_version_id,
        run_id=run.id,
        version=case.draft_version,
        copywriting=case.copywriting,
        parent_takeaway=snapshot["parent_takeaway"],
        interaction=snapshot["interaction"],
        source_note=snapshot["source_note"],
        validation_passed=True,
        audit_accepted=True,
    )
    binding = _moments_binding_from_accepted_models(
        case=case, package=package, run=run, active_draft=draft
    )
    assert binding.active_draft_version_id == case.draft_version_id
    assert binding.copy_snapshot.copywriting == case.copywriting
    run.active_draft_version_id = uuid4()
    with pytest.raises(InfographicInputError, match="differs"):
        _moments_binding_from_accepted_models(
            case=case, package=package, run=run, active_draft=draft
        )


def test_formal_overlay_prompt_reserves_all_masked_panels_and_forbids_stray_text() -> None:
    payload = deepcopy(package_payload())
    fact = "教育部介绍科学课探究的相关内容。"
    payload["copy"]["claims"][0]["text"] = fact
    payload["sources"][0]["claim_text"] = fact
    payload["sources"][0]["exact_quote"] = fact
    case = validate_package_snapshot(payload)
    copy = build_evidence_first_copy(case)
    prompt = build_image_prompt(case, copy, mode="formal", reserve_text_panels=True)
    assert copy.news_summary in prompt
    assert case.topic_title not in prompt
    assert "不要画未证实的人物、设备、实验、科学机制或因果过程" in prompt
    assert "x35-874、y42-520" in prompt
    assert "x42-672、y950-1237" in prompt
    assert "x42-672、y1260-1532" in prompt
    assert "x42-672、y1548-1848" in prompt
    assert "y1858-2048" in prompt
    assert "除机器人胸前AI徽章外" in prompt
    assert "原文链接：" not in prompt
    assert "场景为科普示意" not in prompt


def test_policy_fingerprint_changes_with_either_exact_font(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first = infographic_service._policy_fingerprint("gpt-image-2.5-sunburst", "audit-v1")
    monkeypatch.setattr(infographic_service, "text_overlay_font_sha256", lambda: "f" * 64)
    second = infographic_service._policy_fingerprint("gpt-image-2.5-sunburst", "audit-v1")
    monkeypatch.setattr(infographic_service, "footer_font_sha256", lambda: "e" * 64)
    third = infographic_service._policy_fingerprint("gpt-image-2.5-sunburst", "audit-v1")
    assert len(first) == len(second) == len(third) == 64
    assert first != second
    assert second != third


def test_advisory_policy_is_distinct_from_v8_and_pins_visible_notice_font() -> None:
    strict = infographic_service._policy_fingerprint("gpt-image-2.5-sunburst", "audit-v1")
    advisory = infographic_service._policy_fingerprint(
        "gpt-image-2.5-sunburst", "audit-v1", quality_mode="advisory"
    )
    assert len(strict) == len(advisory) == 64
    assert strict != advisory
    assert infographic_service.POLICY_VERSION == "wecom-news-infographic-v8-evidence-first-copy"
    assert infographic_service.ADVISORY_POLICY_VERSION == (
        "wecom-news-infographic-v13-boundary-comma-advisory"
    )


def test_policy_fingerprint_changes_with_copy_and_production_policy_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model = "gpt-image-2.5-sunburst"
    first = infographic_service._policy_fingerprint(model, "audit-v1")
    assert infographic_service.POLICY_VERSION == "wecom-news-infographic-v8-evidence-first-copy"
    assert EVIDENCE_FIRST_COPY_VERSION == "daily-news-infographic-evidence-first-copy-v1"
    monkeypatch.setattr(infographic_service, "COPY_VERSION", "prior-copy-policy")
    second = infographic_service._policy_fingerprint(model, "audit-v1")
    monkeypatch.setattr(infographic_service, "POLICY_VERSION", "prior-production-policy")
    third = infographic_service._policy_fingerprint(model, "audit-v1")
    assert len(first) == len(second) == len(third) == 64
    assert first != second
    assert second != third
    assert third != infographic_service._policy_fingerprint(model, "audit-v2")


def test_poster_ocr_regions_are_small_fixed_crops_of_reviewed_jpeg() -> None:
    jpeg = prepare_infographic_group_jpeg(_raster(), max_bytes=2 * 1024 * 1024)
    regions = _poster_ocr_regions(jpeg, _copy(), "新闻日期：2026-08-04")
    assert [region.region_id for region in regions] == [
        "masthead",
        "science",
        "learning",
        "brand",
        "footer",
    ]
    assert [region.expected_text for region in regions] == [
        "小赛洞察科学课怎样探究孩子从真实问题出发，观察并记录。",
        "动手做观察身边的变化。",
        "学什么提出问题再验证。",
        "赛先生鼓励孩子提问赛先生鼓励孩子提问。",
        "新闻日期：2026-08-04",
    ]
    for region in regions:
        with Image.open(BytesIO(region.image_bytes)) as cropped:
            cropped.load()
            assert cropped.format == "JPEG" and cropped.width <= 1152
            assert cropped.height <= 530


def test_poster_ocr_matches_wrapped_text_but_rejects_drift_and_wrong_identity() -> None:
    expected = "做中学：从真实问题出发引导孩子观察并记录。"
    good = ImageTextRecognitionResult(
        recognized_lines=("做中学：从真实问题", "出发", "引导孩子观察", "并记录。"),
        request_fingerprint="region-1",
    )
    assert _poster_region_text_matches(good, fingerprint="region-1", expected_text=expected)
    assert not _poster_region_text_matches(good, fingerprint="region-2", expected_text=expected)
    assert not _poster_region_text_matches(
        ImageTextRecognitionResult(
            recognized_lines=("做中学：从真实问题", "出发", "引导孩子观察并实验。"),
            request_fingerprint="region-1",
        ),
        fingerprint="region-1",
        expected_text=expected,
    )


def _enabled_settings() -> Settings:
    return Settings(
        _env_file=None,
        wecom_enabled=True,
        wecom_auto_delivery_enabled=True,
        wecom_delivery_provider="group_webhook",
        wecom_group_webhook_key=SecretStr("synthetic-unit-key"),
        content_enabled=True,
        content_slot_mode_enabled=True,
        content_llm_rerank_enabled=False,
        content_morning_enabled=True,
        content_noon_enabled=True,
        content_evening_enabled=True,
        wecom_infographic_producer_enabled=True,
        wecom_infographic_delivery_enabled=True,
        wecom_infographic_morning_enabled=True,
        wecom_infographic_noon_enabled=True,
        wecom_infographic_evening_enabled=True,
        wecom_infographic_max_ordinal=3,
        image_ocr_enabled=True,
        image_quality_audit_enabled=True,
    )


def test_feature_is_default_off_and_requires_group_and_quality_gates() -> None:
    defaults = Settings(_env_file=None)
    assert not defaults.wecom_infographic_producer_enabled
    assert not defaults.wecom_infographic_delivery_enabled
    assert not any(_enabled_slot(defaults, slot) for slot in ("morning", "noon", "evening"))
    with pytest.raises(ValidationError, match="automatic group-webhook slot delivery"):
        Settings(_env_file=None, wecom_infographic_producer_enabled=True)
    with pytest.raises(ValidationError, match="requires OCR and visual audit"):
        _enabled_settings().model_copy(update={"image_ocr_enabled": False}).model_validate(
            _enabled_settings().model_dump() | {"image_ocr_enabled": False}
        )
    settings = _enabled_settings()
    assert all(_enabled_slot(settings, slot) for slot in ("morning", "noon", "evening"))


def test_safe_infographic_status_openapi_contract() -> None:
    document = get_openapi(title="WeCom", version="test", routes=wecom_router.routes)
    endpoint = document["paths"]["/wecom-deliveries/{delivery_id}/infographic"]["get"]
    assert endpoint["responses"]["200"]["content"]["application/json"]["schema"]["$ref"] == (
        "#/components/schemas/WeComInfographicStatusResponse"
    )
    fields = document["components"]["schemas"]["WeComInfographicStatusResponse"]["properties"]
    assert {"delivery_sha256", "ocr_status", "supplement_status", "attempts"} <= fields.keys()
    assert {"object_key", "prompt", "provider_response_body", "webhook_key"}.isdisjoint(fields)


def test_exact_formal_jpeg_is_reviewed_and_webhook_keeps_its_bytes() -> None:
    source = _raster()
    body = prepare_infographic_group_jpeg(source, max_bytes=2 * 1024 * 1024)
    with Image.open(BytesIO(body)) as opened:
        opened.load()
        assert opened.format == "JPEG" and opened.size == (1152, 2048)
    prepared = prepare_group_webhook_image(body, "image/jpeg")
    assert prepared.body == body
    assert prepared.media_type == "image/jpeg"
    assert sha256(prepared.body).hexdigest() == sha256(body).hexdigest()
    with pytest.raises(ValueError, match="cannot fit"):
        prepare_infographic_group_jpeg(source, max_bytes=100)


def test_footer_modes_keep_source_and_raw_pixels_but_never_reuse_local_marker() -> None:
    case = validate_package_snapshot(package_payload())
    source = _raster()
    local = render_exact_source_footer(source, case, mode="local")
    formal = render_exact_source_footer(source, case, mode="formal")
    test = render_exact_source_footer(source, case, mode="test")
    assert len({local.image_sha256, formal.image_sha256, test.image_sha256}) == 3
    assert all("".join(item.source_url_lines) == case.source_url for item in (local, formal, test))
    with Image.open(BytesIO(source)) as original, Image.open(BytesIO(formal.image_bytes)) as final:
        assert (
            ImageChops.difference(
                original.crop((0, 0, 1152, FOOTER_TOP)),
                final.crop((0, 0, 1152, FOOTER_TOP)),
            ).getbbox()
            is None
        )


def test_lineage_refuses_other_ordinal_slot_or_date() -> None:
    case = validate_package_snapshot(package_payload())
    now = datetime(2026, 8, 7, 7, 32, tzinfo=ZoneInfo("Asia/Shanghai"))
    target = now - timedelta(minutes=2)
    expiry = target + timedelta(hours=1)
    selection = ContentSlotSelectionModel(
        id=case.copy_generation_run_id,
        business_date=case.business_date,
        timezone="Asia/Shanghai",
        content_slot="morning",
        ordinal=1,
        selected_event_id=case.selected_event_id,
        selected_event_version_id=case.selected_event_version_id,
    )
    run = CopyGenerationRunModel(
        id=case.copy_generation_run_id,
        content_slot_selection_id=selection.id,
        business_date=case.business_date,
        timezone="Asia/Shanghai",
        selected_event_id=case.selected_event_id,
        selected_event_version_id=case.selected_event_version_id,
    )
    package = MaterialPackageModel(
        id=case.package_id,
        run_id=run.id,
        package_version=case.package_version,
        request_fingerprint="a" * 64,
    )
    window = WeComDeliveryWindowModel(
        id=case.package_id,
        business_date=case.business_date,
        timezone="Asia/Shanghai",
        content_slot="morning",
        recipient_id="default",
        provider="group_webhook",
        mode="formal",
        target_at=target,
        expires_at=expiry,
    )
    base = WeComDeliveryJobModel(
        id=case.package_id,
        material_package_id=package.id,
        delivery_window_id=window.id,
        content_slot_selection_id=selection.id,
        sequence_ordinal=1,
        not_before=target,
        expires_at=expiry,
        recipient_id="default",
        mode="formal",
        package_version=1,
        content_fingerprint=package.request_fingerprint,
        include_copy=True,
        include_image=True,
        status="queued",
    )
    settings = _enabled_settings()
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
    poster = NewsInfographicJobModel(
        base_job_id=base.id,
        material_package_id=package.id,
        copy_generation_run_id=run.id,
        content_slot_selection_id=selection.id,
        sequence_ordinal=selection.ordinal,
        selected_event_id=selection.selected_event_id,
        selected_event_version_id=selection.selected_event_version_id,
        business_date=selection.business_date,
        content_slot=selection.content_slot,
        recipient_id=base.recipient_id,
        provider=window.provider,
        package_version=package.package_version,
    )
    _assert_job_lineage(
        job=poster, package=package, run=run, selection=selection, base=base, window=window
    )
    for field, replacement in (
        ("base_job_id", uuid4()),
        ("material_package_id", uuid4()),
        ("copy_generation_run_id", uuid4()),
        ("content_slot_selection_id", uuid4()),
        ("sequence_ordinal", 2),
        ("selected_event_id", uuid4()),
        ("selected_event_version_id", uuid4()),
        ("business_date", selection.business_date - timedelta(days=1)),
        ("content_slot", "noon"),
        ("recipient_id", "wrong-recipient"),
        ("provider", "wrong-provider"),
        ("package_version", package.package_version + 1),
    ):
        original = getattr(poster, field)
        setattr(poster, field, replacement)
        with pytest.raises(InfographicInputError, match="reserved infographic lineage changed"):
            _assert_job_lineage(
                job=poster, package=package, run=run, selection=selection, base=base, window=window
            )
        setattr(poster, field, original)
    base.sequence_ordinal = 2
    with pytest.raises(InfographicInputError):
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
    base.sequence_ordinal = 1
    window.content_slot = "noon"
    with pytest.raises(InfographicInputError):
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


def test_supplement_requires_own_confirmed_original_two_messages() -> None:
    settings = _enabled_settings()
    now = datetime(2026, 8, 7, 7, 40, tzinfo=ZoneInfo("Asia/Shanghai"))
    window = WeComDeliveryWindowModel(
        id=validate_package_snapshot(package_payload()).package_id,
        business_date=now.date(),
        content_slot="morning",
        recipient_id="default",
        provider="group_webhook",
        mode="formal",
        target_at=now - timedelta(minutes=10),
        expires_at=now + timedelta(minutes=50),
    )
    base = WeComDeliveryJobModel(
        id=window.id,
        material_package_id=window.id,
        delivery_window_id=window.id,
        content_slot_selection_id=window.id,
        sequence_ordinal=1,
        recipient_id="default",
        mode="formal",
        package_version=1,
        not_before=window.target_at,
        expires_at=window.expires_at,
        status="delivered",
        text_status="delivered",
        image_status="delivered",
        completed_at=now,
    )
    poster = NewsInfographicJobModel(
        id=window.id,
        base_job_id=base.id,
        material_package_id=base.material_package_id,
        content_slot_selection_id=base.content_slot_selection_id,
        sequence_ordinal=1,
        recipient_id="default",
        provider="group_webhook",
        content_slot="morning",
        business_date=window.business_date,
        package_version=1,
        status="ready",
        ocr_status="passed",
        footer_ocr_status="passed",
        visual_status="passed",
        delivery_sha256="a" * 64,
        delivery_byte_size=200_000,
        delivery_media_type="image/jpeg",
        delivery_width=1152,
        delivery_height=2048,
    )
    assert _valid_ready_pair(poster, base, window, settings=settings)
    base.image_status = "unknown"
    assert not _valid_ready_pair(poster, base, window, settings=settings)
    base.image_status = "delivered"
    poster.sequence_ordinal = 2
    assert not _valid_ready_pair(poster, base, window, settings=settings)
