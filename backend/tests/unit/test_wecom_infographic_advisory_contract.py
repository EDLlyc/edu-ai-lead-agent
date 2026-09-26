"""Advisory send eligibility is separate from the original strict gate."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal
from uuid import uuid4

import pytest
from app.application.services.wecom_infographic_quality import (
    ADVISORY_NOTICE_VERSION,
    normalize_advisory_warnings,
    valid_advisory_warnings,
)
from app.application.services.wecom_infographic_supplement import _valid_ready_pair
from app.core.config import Settings
from app.infrastructure.db.models import (
    NewsInfographicJobModel,
    WeComDeliveryJobModel,
    WeComDeliveryWindowModel,
)
from pydantic import SecretStr, ValidationError


def _settings(
    mode: Literal["strict", "advisory"] = "strict", *, quality_services: bool = True
) -> Settings:
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        wecom_enabled=True,
        wecom_auto_delivery_enabled=True,
        wecom_delivery_provider="group_webhook",
        wecom_group_webhook_key=SecretStr("synthetic-unit-key"),
        content_enabled=True,
        content_slot_mode_enabled=True,
        content_llm_rerank_enabled=False,
        content_morning_enabled=True,
        wecom_infographic_delivery_enabled=True,
        wecom_infographic_morning_enabled=True,
        wecom_infographic_review_mode=mode,
        image_ocr_enabled=quality_services,
        image_quality_audit_enabled=quality_services,
    )


def _ready_pair() -> tuple[
    NewsInfographicJobModel, WeComDeliveryJobModel, WeComDeliveryWindowModel
]:
    now = datetime(2026, 9, 26, 2, tzinfo=UTC)
    package_id, window_id, base_id, selection_id = (uuid4() for _ in range(4))
    window = WeComDeliveryWindowModel(
        id=window_id,
        business_date=now.date(),
        content_slot="morning",
        recipient_id="default",
        provider="group_webhook",
        mode="formal",
        target_at=now - timedelta(minutes=10),
        expires_at=now + timedelta(minutes=50),
    )
    base = WeComDeliveryJobModel(
        id=base_id,
        material_package_id=package_id,
        delivery_window_id=window_id,
        content_slot_selection_id=selection_id,
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
        id=uuid4(),
        base_job_id=base_id,
        material_package_id=package_id,
        content_slot_selection_id=selection_id,
        sequence_ordinal=1,
        recipient_id="default",
        provider="group_webhook",
        content_slot="morning",
        business_date=now.date(),
        package_version=1,
        input_fingerprint="f" * 64,
        policy_fingerprint="a" * 64,
        status="ready",
        ocr_status="failed",
        footer_ocr_status="not_checked",
        visual_status="failed",
        image_intent_at=now,
        raw_sha256="b" * 64,
        raw_byte_size=750_000,
        raw_media_type="image/png",
        composite_sha256="e" * 64,
        composite_byte_size=780_000,
        footer_sha256="c" * 64,
        footer_byte_size=300_000,
        delivery_sha256="d" * 64,
        delivery_byte_size=500_000,
        delivery_media_type="image/jpeg",
        delivery_width=1152,
        delivery_height=2048,
        quality_mode="advisory",
        warning_codes=[
            "advisory_unverified",
            "body_ocr_failed",
            "footer_ocr_unavailable",
            "layout_unverified",
            "visual_failed",
        ],
        warning_notice_version=ADVISORY_NOTICE_VERSION,
        copy_candidate_snapshot={
            "package_id": str(package_id),
            "input_fingerprint": "f" * 64,
            "content_approved": False,
            "warning_codes": [],
        },
        copy_audit_snapshot={"status": "unavailable", "issues": []},
    )
    poster.warning_codes = normalize_advisory_warnings(
        [*poster.warning_codes, "copy_audit_unavailable"]
    )
    return poster, base, window


def test_advisory_mode_is_explicit_and_default_strict() -> None:
    assert Settings(_env_file=None).wecom_infographic_review_mode == "strict"  # type: ignore[call-arg]
    with pytest.raises(ValidationError, match="requires OCR and visual audit"):
        _settings(quality_services=False)
    assert _settings("advisory", quality_services=False).wecom_infographic_review_mode == (
        "advisory"
    )


def test_advisory_ready_does_not_forge_failed_ocr_or_visual_passes() -> None:
    poster, base, window = _ready_pair()
    assert not _valid_ready_pair(poster, base, window, settings=_settings())
    assert _valid_ready_pair(
        poster, base, window, settings=_settings("advisory", quality_services=False)
    )
    assert poster.ocr_status == "failed"
    assert poster.visual_status == "failed"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("warning_codes", []),
        ("warning_codes", ["advisory_unverified", "unknown_issue"]),
        ("warning_notice_version", None),
        ("warning_notice_version", "old-notice"),
        ("copy_candidate_snapshot", None),
        ("copy_audit_snapshot", None),
        ("footer_ocr_status", "failed"),
        ("raw_sha256", None),
        ("composite_sha256", None),
        ("footer_sha256", None),
        ("delivery_byte_size", 2 * 1024 * 1024 + 1),
        ("delivery_media_type", "image/png"),
        ("delivery_width", 941),
        ("status", "result_unknown"),
    ],
)
def test_advisory_still_refuses_missing_warning_or_hard_integrity(
    field: str, value: object
) -> None:
    poster, base, window = _ready_pair()
    setattr(poster, field, value)
    assert not _valid_ready_pair(
        poster, base, window, settings=_settings("advisory", quality_services=False)
    )


def test_advisory_still_requires_own_base_text_and_original_image() -> None:
    poster, base, window = _ready_pair()
    base.image_status = "unknown"
    assert not _valid_ready_pair(
        poster, base, window, settings=_settings("advisory", quality_services=False)
    )
    base.image_status = "delivered"
    poster.content_slot_selection_id = uuid4()
    assert not _valid_ready_pair(
        poster, base, window, settings=_settings("advisory", quality_services=False)
    )


def test_warning_codes_are_closed_bounded_and_canonical() -> None:
    assert normalize_advisory_warnings(["visual_failed", "visual_failed"]) == [
        "advisory_unverified",
        "visual_failed",
    ]
    assert valid_advisory_warnings(["advisory_unverified", "visual_failed"])
    assert not valid_advisory_warnings(["visual_failed"])
    assert not valid_advisory_warnings(["visual_failed", "advisory_unverified"])
    with pytest.raises(ValueError, match="not allowed"):
        normalize_advisory_warnings(["private-reviewer-prose"])


def test_advisory_send_refuses_dropped_copy_review_warning() -> None:
    poster, base, window = _ready_pair()
    settings = _settings("advisory", quality_services=False)
    assert _valid_ready_pair(poster, base, window, settings=settings)
    poster.warning_codes = [
        code for code in poster.warning_codes if code != "copy_audit_unavailable"
    ]
    assert not _valid_ready_pair(poster, base, window, settings=settings)
    poster.warning_codes = normalize_advisory_warnings(
        [*poster.warning_codes, "copy_audit_unavailable"]
    )
    poster.copy_candidate_snapshot["package_id"] = str(uuid4())
    assert not _valid_ready_pair(poster, base, window, settings=settings)
