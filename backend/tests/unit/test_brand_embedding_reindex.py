from __future__ import annotations

from types import SimpleNamespace
from typing import cast
from uuid import UUID

import pytest
from app import brand_embedding_reindex_main
from app.brand_embedding_reindex_main import _matching_target
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
