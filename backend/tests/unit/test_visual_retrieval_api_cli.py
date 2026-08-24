from __future__ import annotations

import hashlib
import json
import struct
import zlib
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

import pytest
from app.api.v1.routes.brand_knowledge import search_brand_visual_catalog
from app.brand_visual_index_main import _run
from app.core.errors import BrandUploadRejectedError
from app.domain.visual_assets import (
    VisualAsset,
    VisualAssetCatalog,
    VisualAssetKind,
    VisualAssetRole,
)
from app.domain.visual_retrieval import (
    NormalizedVisualImage,
    VisualEmbeddingIdentity,
    VisualSemanticRanking,
    VisualSemanticScore,
)
from app.infrastructure.brand.visual_catalog import LoadedVisualCatalog
from starlette.datastructures import Headers, UploadFile
from starlette.requests import Request


def _png() -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + kind
            + data
            + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"\x00\x00\x00\x00\xff"))
        + chunk(b"IEND", b"")
    )


def _catalog() -> VisualAssetCatalog:
    asset_id = hashlib.sha256(b"approved-visual-asset").hexdigest()
    asset = VisualAsset(
        asset_id=asset_id,
        relative_path="private/approved.png",
        filename="approved.png",
        category="visual-asset",
        byte_size=100,
        media_type="image/png",
        width=100,
        height=100,
        has_alpha=True,
        asset_kind=VisualAssetKind.ACTION,
        variant_group="science-lab",
        characters=("xiao-sai",),
        roles=(VisualAssetRole.ACTION_REFERENCE,),
        topics=("science", "experiment"),
        poses=("observe",),
        scene_tags=("laboratory",),
        priority=50,
        approved=True,
    )
    return VisualAssetCatalog(
        schema_version="brand-visual-assets-v2",
        catalog_version="brand-visual-catalog-v1",
        assets=(asset,),
    )


def _request(*, enabled: bool, service: object | None) -> Request:
    state = SimpleNamespace(
        settings=SimpleNamespace(
            visual_semantic_enabled=enabled,
            image_asset_manifest="private/visual-assets.manifest.json",
        ),
        visual_retrieval_service=service,
    )
    app = SimpleNamespace(state=state)
    return Request({"type": "http", "app": app})


class _ReadySearch:
    def __init__(self, catalog: VisualAssetCatalog) -> None:
        self._catalog = catalog
        self.text_queries: list[str] = []
        self.image_queries: list[bytes] = []

    async def search_text(self, *, text: str, catalog: VisualAssetCatalog) -> VisualSemanticRanking:
        assert catalog == self._catalog
        self.text_queries.append(text)
        return self._ranking(catalog)

    async def search_normalized_image(
        self, *, normalized: NormalizedVisualImage, catalog: VisualAssetCatalog
    ) -> VisualSemanticRanking:
        assert catalog == self._catalog
        self.image_queries.append(normalized.png_bytes)
        return self._ranking(catalog)

    @staticmethod
    def _ranking(catalog: VisualAssetCatalog) -> VisualSemanticRanking:
        asset = catalog.assets[0]
        return VisualSemanticRanking(
            catalog_version=catalog.catalog_version,
            identity=VisualEmbeddingIdentity(),
            query_fingerprint="a" * 64,
            scores=(VisualSemanticScore(asset_id=asset.asset_id, similarity=0.75),),
            indexed_asset_count=1,
            catalog_asset_count=1,
            complete=True,
        )


@pytest.mark.asyncio
async def test_visual_search_returns_only_safe_asset_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = _catalog()
    loaded = LoadedVisualCatalog(catalog=catalog, materials_root=Path("private"))
    monkeypatch.setattr("app.api.v1.routes.brand_knowledge.load_visual_catalog", lambda _: loaded)
    service = _ReadySearch(catalog)

    response = await search_brand_visual_catalog(
        _request(enabled=True, service=service),
        text_query="  科学实验  ",
        image=None,
        limit=5,
    )

    serialized = json.dumps(response.model_dump(mode="json"), ensure_ascii=False)
    assert service.text_queries == ["科学实验"]
    assert response.status == "ready"
    assert response.items[0].asset_ref == catalog.assets[0].asset_id[:16]
    assert response.items[0].similarity == 0.75
    assert response.items[0].approved is True
    for private_field in (
        "relative_path",
        "filename",
        "image_bytes",
        "vector",
        "request_id",
        "provider_body",
    ):
        assert private_field not in serialized


@pytest.mark.asyncio
async def test_visual_search_accepts_one_valid_png_without_exposing_upload_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    catalog = _catalog()
    loaded = LoadedVisualCatalog(catalog=catalog, materials_root=Path("private"))
    monkeypatch.setattr("app.api.v1.routes.brand_knowledge.load_visual_catalog", lambda _: loaded)
    service = _ReadySearch(catalog)
    body = _png()
    upload = UploadFile(
        file=BytesIO(body),
        filename="private-query-name.png",
        headers=Headers({"content-type": "image/png"}),
    )

    response = await search_brand_visual_catalog(
        _request(enabled=True, service=service),
        text_query=None,
        image=upload,
        limit=5,
    )

    serialized = json.dumps(response.model_dump(mode="json"), ensure_ascii=False)
    assert service.image_queries == [body]
    assert response.status == "ready"
    assert response.query_modality == "image"
    assert "private-query-name.png" not in serialized


@pytest.mark.asyncio
async def test_visual_search_validates_exactly_one_query_even_when_disabled() -> None:
    image = UploadFile(
        file=BytesIO(b"\x89PNG\r\n\x1a\n"),
        filename="private.png",
        headers=Headers({"content-type": "image/png"}),
    )

    with pytest.raises(BrandUploadRejectedError):
        await search_brand_visual_catalog(
            _request(enabled=False, service=None),
            text_query="text",
            image=image,
            limit=5,
        )

    invalid_image = UploadFile(
        file=BytesIO(b"not-a-png"),
        filename="private.png",
        headers=Headers({"content-type": "image/png"}),
    )
    with pytest.raises(BrandUploadRejectedError):
        await search_brand_visual_catalog(
            _request(enabled=False, service=None),
            text_query=None,
            image=invalid_image,
            limit=5,
        )

    wrong_media_type = UploadFile(
        file=BytesIO(_png()),
        filename="private.png",
        headers=Headers({"content-type": "image/jpeg"}),
    )
    with pytest.raises(BrandUploadRejectedError):
        await search_brand_visual_catalog(
            _request(enabled=False, service=None),
            text_query=None,
            image=wrong_media_type,
            limit=5,
        )
    with pytest.raises(BrandUploadRejectedError):
        await search_brand_visual_catalog(
            _request(enabled=False, service=None),
            text_query=None,
            image=None,
            limit=5,
        )


@pytest.mark.asyncio
async def test_visual_index_cli_dry_run_is_provider_free_and_aggregate_only(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    catalog = _catalog()
    loaded = LoadedVisualCatalog(catalog=catalog, materials_root=Path("private"))
    monkeypatch.setattr(
        "app.brand_visual_index_main.get_settings",
        lambda: SimpleNamespace(image_asset_manifest="private/manifest.json"),
    )
    monkeypatch.setattr("app.brand_visual_index_main.load_visual_catalog", lambda _: loaded)

    assert await _run(dry_run=True, max_assets=1) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload == {
        "catalog_asset_count": 1,
        "selected_asset_count": 1,
        "dry_run": True,
    }
    output = json.dumps(payload)
    assert "approved.png" not in output
    assert "private" not in output
    assert catalog.assets[0].asset_id not in output
