from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from uuid import UUID

import pytest
from app import brand_embedding_reindex_main
from app.brand_embedding_reindex_main import _matching_target, _selected_source_projections
from app.core.config import Settings
from app.infrastructure.db.brand_knowledge import BrandDocumentProjection
from app.infrastructure.db.models import BrandDocumentVersionModel


def _version(
    *,
    ordinal: int,
    provider: str,
    model: str,
    status: str,
) -> BrandDocumentVersionModel:
    return cast(
        BrandDocumentVersionModel,
        SimpleNamespace(
            id=UUID(int=ordinal),
            version=ordinal,
            sha256="a" * 64,
            metadata_fingerprint="b" * 64,
            parser_version="brand-parser-v3-source-structure",
            chunk_version="brand-chunk-v3-parent-child",
            embedding_input_version="brand-embedding-input-v2-section-context",
            embedding_provider=provider,
            embedding_model=model,
            status=status,
        ),
    )


def _projection(
    *,
    document_id: UUID,
    media_type: str = "application/pdf",
    active: bool = True,
    status: str = "ready",
) -> BrandDocumentProjection:
    version = _version(
        ordinal=document_id.int + 10,
        provider="alibaba-model-studio",
        model="qwen3-vl-embedding",
        status=status,
    )
    version.media_type = media_type
    return cast(
        BrandDocumentProjection,
        SimpleNamespace(
            document=SimpleNamespace(
                id=document_id,
                active_version_id=version.id if active else None,
            ),
            versions=(version,),
        ),
    )


def test_reindex_target_never_relabels_or_selects_failed_vector_space() -> None:
    source = _version(ordinal=1, provider="zhipu", model="embedding-3", status="ready")
    failed_alibaba = _version(
        ordinal=2,
        provider="alibaba-model-studio",
        model="qwen3-vl-embedding",
        status="failed",
    )
    ready_alibaba = _version(
        ordinal=3,
        provider="alibaba-model-studio",
        model="qwen3-vl-embedding",
        status="ready",
    )
    failed_only_projection = cast(
        BrandDocumentProjection,
        SimpleNamespace(versions=(source, failed_alibaba)),
    )
    projection = cast(
        BrandDocumentProjection,
        SimpleNamespace(versions=(source, failed_alibaba, ready_alibaba)),
    )
    settings = cast(
        Settings,
        SimpleNamespace(
            brand_parser_version="brand-parser-v3-source-structure",
            brand_chunk_version="brand-chunk-v3-parent-child",
            brand_embedding_input_version="brand-embedding-input-v2-section-context",
            brand_embedding_provider="alibaba-model-studio",
            brand_embedding_model="qwen3-vl-embedding",
        ),
    )

    assert _matching_target(failed_only_projection, source, settings) is None
    assert _matching_target(projection, source, settings) is ready_alibaba


def test_scoped_reindex_selects_only_explicit_ready_pdf_document_ids() -> None:
    first_id = UUID(int=1)
    second_id = UUID(int=2)
    unrelated_id = UUID(int=3)
    projections = (
        _projection(document_id=first_id),
        _projection(document_id=second_id),
        _projection(document_id=unrelated_id),
    )

    selected = _selected_source_projections(projections, frozenset({second_id, first_id}))

    assert tuple(projection.document.id for projection in selected) == (first_id, second_id)


@pytest.mark.parametrize(
    "projection",
    (
        _projection(document_id=UUID(int=4), media_type="text/markdown"),
        _projection(document_id=UUID(int=5), active=False),
        _projection(document_id=UUID(int=6), status="processing"),
    ),
)
def test_scoped_reindex_rejects_non_pdf_or_non_ready_sources(
    projection: BrandDocumentProjection,
) -> None:
    with pytest.raises(RuntimeError):
        _selected_source_projections((projection,), frozenset({projection.document.id}))


def test_scoped_reindex_rejects_unknown_document_ids() -> None:
    with pytest.raises(RuntimeError, match="do not exist"):
        _selected_source_projections((), frozenset({UUID(int=7)}))


@pytest.mark.asyncio
async def test_mutating_reindex_requires_explicit_execute_before_engine_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = cast(
        Settings,
        SimpleNamespace(
            app_env="development",
            resolved_brand_embedding_provider_mode="alibaba",
        ),
    )
    engine_calls = 0

    def create_engine(_settings: Settings) -> object:
        nonlocal engine_calls
        engine_calls += 1
        return object()

    monkeypatch.setattr(brand_embedding_reindex_main, "get_settings", lambda: settings)
    monkeypatch.setattr(brand_embedding_reindex_main, "create_engine", create_engine)

    with pytest.raises(RuntimeError, match="require --execute"):
        await brand_embedding_reindex_main._run("migrate", execute=False)

    assert engine_calls == 0


@pytest.mark.asyncio
async def test_mutating_reindex_requires_explicit_document_allowlist_before_engine_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = cast(
        Settings,
        SimpleNamespace(
            app_env="development",
            resolved_brand_embedding_provider_mode="alibaba",
        ),
    )
    engine_calls = 0

    def create_engine(_settings: Settings) -> object:
        nonlocal engine_calls
        engine_calls += 1
        return object()

    monkeypatch.setattr(brand_embedding_reindex_main, "get_settings", lambda: settings)
    monkeypatch.setattr(brand_embedding_reindex_main, "create_engine", create_engine)

    with pytest.raises(RuntimeError, match="require --document-id"):
        await brand_embedding_reindex_main._run("migrate", execute=True)

    assert engine_calls == 0
