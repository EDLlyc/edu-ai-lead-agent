from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from uuid import UUID

import httpx
import pytest
from app.api.dependencies import get_session
from app.api.v1.routes import brand_knowledge as brand_routes
from app.api.v1.routes.brand_knowledge_views import digital_ip_document_bindings
from app.domain.brand_knowledge import BrandAudience, BrandDocumentKind
from app.domain.digital_ip import (
    DigitalIpDocumentBinding,
    DigitalIpVisualCatalogStatus,
    project_digital_ip_profile,
    project_visual_catalog,
    unavailable_visual_catalog,
)
from app.domain.visual_assets import VisualAsset, VisualAssetCatalog, VisualAssetError
from app.infrastructure.db.brand_knowledge import BrandDocumentProjection
from app.infrastructure.db.models import BrandDocumentModel, BrandDocumentVersionModel
from app.schemas.brand_knowledge import DigitalIpProfileResponse
from fastapi import FastAPI

DOCUMENT_A = UUID("00000000-0000-4000-8000-000000000001")
VERSION_A = UUID("00000000-0000-4000-8000-000000000002")
DOCUMENT_B = UUID("00000000-0000-4000-8000-000000000003")
VERSION_B = UUID("00000000-0000-4000-8000-000000000004")


def _binding(
    document_id: UUID,
    version_id: UUID,
    *,
    kind: BrandDocumentKind,
    tone_tags: tuple[str, ...] = (),
    safety_tags: tuple[str, ...] = (),
) -> DigitalIpDocumentBinding:
    return DigitalIpDocumentBinding(
        document_id=document_id,
        version_id=version_id,
        version=1,
        title=f"{kind.value} rules",
        document_kind=kind,
        audience=BrandAudience.PARENTS,
        valid_from=date(2026, 1, 1),
        valid_until=None,
        tone_tags=tone_tags,
        safety_tags=safety_tags,
    )


def _asset(
    digest: str,
    *,
    approved: bool = True,
    characters: tuple[str, ...] = ("xiao-sai",),
    priority: int = 100,
) -> VisualAsset:
    return VisualAsset(
        asset_id=digest,
        relative_path=f"private/characters/{digest[:8]}.png",
        filename=f"{digest[:8]}.png",
        category="visual-asset",
        byte_size=128,
        media_type="image/png",
        width=256,
        height=256,
        has_alpha=True,
        asset_kind="identity",
        display_name=f"角色 {digest[:4]}",
        characters=characters,
        topics=("science",),
        scene_tags=("brand",),
        approved=approved,
        priority=priority,
    )


def test_profile_projection_is_stable_and_aggregates_active_metadata() -> None:
    bindings = (
        _binding(
            DOCUMENT_A,
            VERSION_A,
            kind=BrandDocumentKind.TONE,
            tone_tags=("温暖", "准确"),
        ),
        _binding(
            DOCUMENT_B,
            VERSION_B,
            kind=BrandDocumentKind.SAFETY_RULE,
            tone_tags=("准确",),
            safety_tags=("不制造焦虑",),
        ),
    )
    catalog = VisualAssetCatalog(
        schema_version="brand-visual-assets-v2",
        catalog_version="catalog-v7",
        assets=(
            _asset("b" * 64, priority=80),
            _asset("a" * 64, priority=120),
            _asset("c" * 64, approved=False),
            _asset("d" * 64, characters=("unrelated",)),
        ),
    )
    visual = project_visual_catalog(catalog)

    first = project_digital_ip_profile(bindings, visual)
    second = project_digital_ip_profile(tuple(reversed(bindings)), visual)

    assert first == second
    assert first.active_document_count == 2
    assert first.document_kinds == (
        BrandDocumentKind.SAFETY_RULE,
        BrandDocumentKind.TONE,
    )
    assert first.tone_tags == ("准确", "温暖")
    assert first.safety_tags == ("不制造焦虑",)
    assert first.visual_catalog_status is DigitalIpVisualCatalogStatus.READY
    assert [asset.asset_ref for asset in first.visual_assets] == ["a" * 16, "b" * 16]
    assert first.evidence_eligible is False
    assert len(first.profile_fingerprint) == 64


def test_visual_projection_and_schema_never_expose_private_fields() -> None:
    visual = project_visual_catalog(
        VisualAssetCatalog(
            schema_version="brand-visual-assets-v2",
            catalog_version="catalog-v1",
            assets=(_asset("a" * 64),),
        )
    )
    profile = project_digital_ip_profile((), visual)
    response = DigitalIpProfileResponse.model_validate(
        brand_routes.digital_ip_profile_response(profile).model_dump()
    )
    serialized = response.model_dump_json()

    assert response.active_document_count == 0
    assert response.visual_assets[0].approved is True
    assert "relative_path" not in serialized
    assert "filename" not in serialized
    assert "object_key" not in serialized
    assert "image_bytes" not in serialized
    assert "private/characters" not in serialized
    assert "a" * 64 not in serialized


def test_visual_projection_replaces_filename_fallback_and_rejects_private_values() -> None:
    legacy_asset = VisualAsset(
        asset_id="a" * 64,
        relative_path="private/characters/xiao-sai.png",
        filename="xiao-sai.png",
        category="visual-asset",
        byte_size=128,
        media_type="image/png",
        width=256,
        height=256,
        has_alpha=True,
        asset_kind="identity",
        characters=("xiao-sai",),
        approved=True,
    )

    projected = project_visual_catalog(
        VisualAssetCatalog(
            schema_version="brand-visual-assets-v2",
            catalog_version="catalog-v1",
            assets=(legacy_asset,),
        )
    )

    assert projected.assets[0].display_name == "受控视觉素材 aaaaaaaa"
    assert legacy_asset.filename not in projected.assets[0].display_name

    unsafe_asset = VisualAsset(
        asset_id="b" * 64,
        relative_path="private/characters/unsafe.png",
        filename="unsafe.png",
        category="visual-asset",
        byte_size=128,
        media_type="image/png",
        width=256,
        height=256,
        has_alpha=True,
        asset_kind="identity",
        display_name="private/brand-materials/unsafe.png",
        characters=("xiao-sai",),
        approved=True,
    )
    with pytest.raises(VisualAssetError, match="not browser-safe"):
        project_visual_catalog(
            VisualAssetCatalog(
                schema_version="brand-visual-assets-v2",
                catalog_version="catalog-v1",
                assets=(unsafe_asset,),
            )
        )


def test_document_binding_mapper_keeps_only_active_ready_authority() -> None:
    active_document = BrandDocumentModel(
        id=DOCUMENT_A,
        title="语气规范",
        document_kind=BrandDocumentKind.TONE.value,
        audience=BrandAudience.PARENTS.value,
        status="active",
        active_version_id=VERSION_A,
    )
    active_version = BrandDocumentVersionModel(
        id=VERSION_A,
        document_id=DOCUMENT_A,
        version=2,
        status="ready",
        active=True,
        valid_from=date(2026, 1, 1),
        valid_until=None,
        tone_tags=["温暖"],
        safety_tags=["不制造焦虑"],
        visual_tags=["3d"],
    )
    stale_version = BrandDocumentVersionModel(
        id=VERSION_B,
        document_id=DOCUMENT_A,
        version=1,
        status="ready",
        active=False,
        tone_tags=["过时"],
        safety_tags=[],
        visual_tags=[],
    )
    inactive_document = BrandDocumentModel(
        id=DOCUMENT_B,
        title="停用规范",
        document_kind=BrandDocumentKind.POSITIONING.value,
        audience=BrandAudience.PARENTS.value,
        status="inactive",
        active_version_id=None,
    )

    bindings = digital_ip_document_bindings(
        (
            BrandDocumentProjection(
                document=active_document,
                versions=(stale_version, active_version),
                jobs_by_version={},
            ),
            BrandDocumentProjection(
                document=inactive_document,
                versions=(),
                jobs_by_version={},
            ),
        )
    )

    assert len(bindings) == 1
    assert bindings[0].version_id == VERSION_A
    assert bindings[0].tone_tags == ("温暖",)


@pytest.mark.asyncio
async def test_profile_api_returns_typed_unavailable_without_manifest_leak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_documents(_session: object) -> tuple[BrandDocumentProjection, ...]:
        return ()

    def unavailable_manifest(_path: object) -> object:
        raise VisualAssetError("private/path/visual-assets.manifest.json")

    async def session_override() -> object:
        yield object()

    monkeypatch.setattr(brand_routes, "list_brand_documents", no_documents)
    monkeypatch.setattr(brand_routes, "load_visual_catalog", unavailable_manifest)
    app = FastAPI()
    app.state.settings = SimpleNamespace(
        image_asset_manifest="private/path/visual-assets.manifest.json"
    )
    app.include_router(brand_routes.router, prefix="/api/v1")
    app.dependency_overrides[get_session] = session_override

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        response = await client.get("/api/v1/digital-ip/profile")

    assert response.status_code == 200
    payload = response.json()
    assert payload["visual_catalog_status"] == "unavailable"
    assert payload["visual_catalog_version"] is None
    assert payload["visual_assets"] == []
    assert payload["evidence_eligible"] is False
    assert "private/path" not in response.text


def test_unavailable_visual_catalog_does_not_remove_text_profile() -> None:
    binding = _binding(
        DOCUMENT_A,
        VERSION_A,
        kind=BrandDocumentKind.PROHIBITED_LANGUAGE,
        safety_tags=("禁用绝对化承诺",),
    )

    profile = project_digital_ip_profile((binding,), unavailable_visual_catalog())

    assert profile.active_document_count == 1
    assert profile.visual_catalog_status is DigitalIpVisualCatalogStatus.UNAVAILABLE
    assert profile.visual_assets == ()
    assert profile.safety_tags == ("禁用绝对化承诺",)
