from __future__ import annotations

from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from app.core.errors import ConflictError
from app.infrastructure.db.models import (
    CopyGenerationRunModel,
    EventClusterVersionModel,
    ImageArtifactModel,
    MaterialPackageModel,
    TopicScoreModel,
)
from app.infrastructure.db.official_account_local import material_package_source_snapshot
from app.infrastructure.db.official_account_weekly_production import (
    PostgresWeeklyProductionInputPlanner,
    _material_is_eligible,
)
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker
from structlog.testing import capture_logs

_CUTOFF = datetime(2026, 9, 7, 1, tzinfo=UTC)


def _material(
    ordinal: int = 1,
    *,
    source_url: str = "https://example.org/news",
) -> tuple[MaterialPackageModel, ImageArtifactModel]:
    image = ImageArtifactModel(
        id=UUID(int=100 + ordinal),
        status="succeeded",
        media_type="image/jpeg",
        byte_size=100,
        sha256="a" * 64,
        validation_snapshot={"passed": True},
        audit_snapshot={"configured": True, "status": "accepted"},
    )
    package = MaterialPackageModel(
        id=UUID(int=200 + ordinal),
        package_version=1,
        request_fingerprint=f"{ordinal:064x}",
        image_artifact_id=image.id,
        created_at=_CUTOFF - timedelta(days=1),
        status="completed",
        review_status="not_required",
        validation_snapshot={"passed": True},
        audit_snapshot={"accepted": True},
        topic_snapshot={"title": f"科技实践 {ordinal}", "summary": "科技课堂实践取得具体进展。"},
        copy_snapshot={"copywriting": "已有文案。"},
        source_snapshot=[
            {
                "evidence_binding_id": str(UUID(int=300 + ordinal)),
                "source_url": source_url,
                "source_tier": "A",
                "exact_quote": "学校完成了科学实验课程试点。",
            }
        ],
        brand_snapshot=[
            {
                "brand_chunk_id": str(UUID(int=400 + ordinal)),
                "document_title": "合成品牌指南",
                "text": "鼓励学生探索科学。",
            }
        ],
    )
    return package, image


def test_http_source_is_rejected_despite_successful_material_quality() -> None:
    package, image = _material(source_url="http://example.org/private-source?token=sentinel")
    original = deepcopy(package.source_snapshot)
    assert package.status == "completed"
    assert package.validation_snapshot["passed"] is True
    assert package.audit_snapshot["accepted"] is True
    assert image.validation_snapshot["passed"] is True

    with pytest.raises(ConflictError, match="source snapshot is invalid"):
        material_package_source_snapshot(package, image)
    assert not _material_is_eligible(package, image)
    assert package.source_snapshot == original


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_snapshot", []),
        ("source_snapshot", [{"evidence_binding_id": "bad-id"}]),
        ("source_snapshot", [None]),
        ("brand_snapshot", []),
        ("brand_snapshot", [{"brand_chunk_id": "bad-id"}]),
        ("topic_snapshot", {"title": "ok"}),
        ("topic_snapshot", {"title": "x" * 301, "summary": "ok"}),
        ("topic_snapshot", {"title": "ok", "summary": "x" * 2_001}),
        ("copy_snapshot", {"copywriting": "x" * 4_001}),
        ("validation_snapshot", {"passed": False}),
        ("audit_snapshot", {"accepted": False}),
        ("validation_snapshot", []),
        ("review_status", "rejected"),
        ("status", "failed"),
    ],
)
def test_preflight_rejects_full_source_bounds_and_quality(field: str, value: Any) -> None:
    package, image = _material()
    setattr(package, field, value)

    assert not _material_is_eligible(package, image)


@pytest.mark.parametrize(
    ("snapshot_field", "item_field", "value"),
    [
        ("source_snapshot", "exact_quote", "x" * 2_001),
        ("source_snapshot", "source_url", "https://user:secret@example.org/article"),
        ("source_snapshot", "source_url", "https://example.org/article#fragment"),
        ("brand_snapshot", "document_title", "x" * 301),
        ("brand_snapshot", "text", "x" * 2_001),
        ("brand_snapshot", "tone_tags", ["tone"] * 25),
    ],
)
def test_preflight_rejects_malformed_evidence_and_brand(
    snapshot_field: str, item_field: str, value: Any
) -> None:
    package, image = _material()
    getattr(package, snapshot_field)[0][item_field] = value

    assert not _material_is_eligible(package, image)


@pytest.mark.parametrize(("field", "maximum"), [("source_snapshot", 40), ("brand_snapshot", 20)])
def test_preflight_includes_outer_snapshot_collection_limits(field: str, maximum: int) -> None:
    package, image = _material()
    template = getattr(package, field)[0]
    id_key = "evidence_binding_id" if field == "source_snapshot" else "brand_chunk_id"
    setattr(
        package, field, [{**template, id_key: str(UUID(int=i + 1))} for i in range(maximum + 1)]
    )

    with pytest.raises(ValidationError):
        material_package_source_snapshot(package, image)
    assert not _material_is_eligible(package, image)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("status", "failed"),
        ("validation_snapshot", {"passed": False}),
        ("audit_snapshot", {"configured": True, "status": "rejected"}),
        ("audit_snapshot", []),
        ("media_type", None),
        ("byte_size", None),
        ("sha256", None),
    ],
)
def test_preflight_preserves_image_quality_and_metadata_gates(field: str, value: Any) -> None:
    package, image = _material()
    setattr(image, field, value)

    assert not _material_is_eligible(package, image)


@pytest.mark.parametrize("status", ["ready", "awaiting_manual_use", "completed"])
def test_valid_source_projection_is_unchanged(status: str) -> None:
    package, image = _material(source_url="https://example.org/news?edition=1")
    package.status = status
    before = material_package_source_snapshot(package, image)

    assert _material_is_eligible(package, image)
    assert material_package_source_snapshot(package, image) == before
    assert package.source_snapshot[0]["source_url"] == "https://example.org/news?edition=1"


def _row(
    ordinal: int,
    *,
    source_url: str = "https://example.org/news",
) -> tuple[
    MaterialPackageModel, CopyGenerationRunModel, EventClusterVersionModel, ImageArtifactModel
]:
    package, image = _material(ordinal, source_url=source_url)
    event_id = UUID(int=500 + ordinal)
    event_version_id = UUID(int=600 + ordinal)
    run = CopyGenerationRunModel(
        id=UUID(int=700 + ordinal),
        selected_event_id=event_id,
        selected_event_version_id=event_version_id,
    )
    event = EventClusterVersionModel(
        id=event_version_id,
        event_id=event_id,
        representative_title=f"科技实践 {ordinal}",
        summary_projection={"summary": "科技课堂实践取得具体进展。"},
        source_diversity=1,
        event_time_start=_CUTOFF - timedelta(days=1),
        created_at=_CUTOFF - timedelta(days=1),
    )
    return package, run, event, image


@pytest.mark.asyncio
@pytest.mark.parametrize("same_event_replacement", [False, True])
async def test_planner_skips_invalid_high_ranked_material_and_uses_valid_replacement(
    monkeypatch: pytest.MonkeyPatch,
    same_event_replacement: bool,
) -> None:
    rows = tuple(_row(ordinal) for ordinal in range(1, 5))
    rows[2][0].source_snapshot[0]["source_url"] = "http://example.org/private?token=sentinel"
    rows[2][0].created_at = _CUTOFF - timedelta(hours=1)
    if same_event_replacement:
        rows[3][1].selected_event_id = rows[2][1].selected_event_id
        rows[3][1].selected_event_version_id = rows[2][1].selected_event_version_id
        rows[3][2].event_id = rows[2][2].event_id
        rows[3][2].id = rows[2][2].id
    original = deepcopy(rows[2][0].source_snapshot)
    scores = {
        package.id: TopicScoreModel(
            id=UUID(int=800 + ordinal),
            event_id=run.selected_event_id,
            event_version_id=run.selected_event_version_id,
            raw_features={},
            normalized_features={},
            weights={},
            penalty_weights={},
            positive_components={},
            penalty_components={},
            total=0.99 - ordinal / 100,
            threshold=0.59,
            passes_threshold=True,
            eligible=True,
            veto_codes=[],
            rank=ordinal,
            deterministic_rank=ordinal,
            explanation={"scoring_version": "scoring-test", "scoring_profile": "test"},
        )
        for ordinal, (package, run, _version, _image) in enumerate(rows, start=1)
    }
    authority = {
        run.selected_event_id: (
            ("government" if ordinal == 1 else "authoritative_media", "a" * 64),
        )
        for ordinal, (_package, run, _version, _image) in enumerate(rows, start=1)
    }
    planner = PostgresWeeklyProductionInputPlanner(async_sessionmaker())
    monkeypatch.setattr(planner, "_load_material_rows", AsyncMock(return_value=rows))
    monkeypatch.setattr(planner, "_load_scores", AsyncMock(return_value=scores))
    monkeypatch.setattr(planner, "_load_source_authority", AsyncMock(return_value=authority))

    with capture_logs() as logs:
        planned = await planner.plan(week_start=date(2026, 9, 7), cutoff=_CUTOFF)

    assert [item.material_package_id for item in planned.items] == [
        rows[ordinal][0].id for ordinal in (0, 1, 3)
    ]
    for ordinal in (0, 1, 3):
        source = material_package_source_snapshot(rows[ordinal][0], rows[ordinal][3])
        assert source.material_package_id == rows[ordinal][0].id
    assert rows[2][0].source_snapshot == original
    assert logs == [
        {
            "event": "official_account_weekly_materials_skipped",
            "log_level": "info",
            "week_start": "2026-09-07",
            "reason_code": "material_source_incompatible",
            "skipped_count": 1,
        }
    ]
    assert "sentinel" not in str(logs)
    assert "example.org" not in str(logs)

    # No partial edition when the compatible candidate pool cannot fill all three roles.
    monkeypatch.setattr(planner, "_load_material_rows", AsyncMock(return_value=rows[:3]))
    with pytest.raises(ValueError, match="current"):
        await planner.plan(week_start=date(2026, 9, 7), cutoff=_CUTOFF)
