from __future__ import annotations

import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

import httpx
from app.application.ports.ip_assets import IpAssetQuery
from app.application.ports.visual_retrieval import VisualEmbeddingModel
from app.application.services.ip_assets import IpAssetService
from app.core.config import Settings
from app.domain.ip_assets import (
    IP_ASSET_SEARCH_V2_VERSION,
    IP_ASSET_SEARCH_V3_VERSION,
    IpAssetSearchVersion,
)
from app.infrastructure.ai.visual_embedding import (
    AlibabaVisualEmbeddingAdapter,
    DeterministicFakeVisualEmbedding,
)
from app.infrastructure.db.ip_assets import PostgresIpAssetRepository
from app.infrastructure.db.session import create_engine, create_session_factory
from app.infrastructure.storage.minio_ip_asset_store import MinioIpAssetStore

from .assets import (
    GroundedIpAssetRepository,
    GroundedLivePreflightError,
    map_live_grounded_assets,
)
from .dataset import GroundedDatasetBundle
from .models import (
    RUN_SCHEMA_VERSION,
    GroundedQueryObservation,
    GroundedRetrievalRun,
)


async def preflight_live_grounded(
    *,
    settings: Settings,
    bundle: GroundedDatasetBundle,
    manifest_path: Path,
) -> None:
    _validate_live_settings(settings)
    engine = create_engine(settings)
    try:
        repository = PostgresIpAssetRepository(create_session_factory(engine))
        await map_live_grounded_assets(
            repository=repository,
            snapshot=bundle.assets,
            manifest_path=manifest_path,
            identity=settings.visual_embedding_identity,
        )
    finally:
        await engine.dispose()


async def run_live_grounded(
    *,
    settings: Settings,
    bundle: GroundedDatasetBundle,
    manifest_path: Path,
    search_version: str,
) -> GroundedRetrievalRun:
    _validate_live_settings(settings)
    if search_version not in {IP_ASSET_SEARCH_V2_VERSION, IP_ASSET_SEARCH_V3_VERSION}:
        raise ValueError("grounded live search version is unsupported")
    version = cast(IpAssetSearchVersion, search_version)
    engine = create_engine(settings)
    try:
        session_factory = create_session_factory(engine)
        base_repository = PostgresIpAssetRepository(session_factory)
        live_assets = await map_live_grounded_assets(
            repository=base_repository,
            snapshot=bundle.assets,
            manifest_path=manifest_path,
            identity=settings.visual_embedding_identity,
        )
        repository = GroundedIpAssetRepository(
            session_factory,
            allowed_asset_ids=live_assets.allowed_asset_ids,
        )
        async with _embedding_model(settings) as embeddings:
            service = IpAssetService(
                repository=repository,
                store=MinioIpAssetStore(settings),
                embeddings=embeddings,
                identity=settings.visual_embedding_identity,
                search_version=version,
                business_timezone=settings.business_timezone,
            )
            observations: list[GroundedQueryObservation] = []
            for query in bundle.queries:
                result = await service.search_text_for_evaluation(
                    message=query.query,
                    prior_turns=(),
                    filters=IpAssetQuery(limit=8),
                )
                try:
                    selected = tuple(
                        live_assets.catalog_ref_by_asset_ref[item.asset.asset_ref]
                        for item in result.items
                    )
                except KeyError as error:
                    raise ValueError(
                        "grounded retrieval escaped the approved 41-asset corpus"
                    ) from error
                observations.append(
                    GroundedQueryObservation(
                        query_ref=query.query_ref,
                        mode=result.mode.value,
                        degraded_reason=result.degraded_reason,
                        selected_catalog_refs=selected,
                        failure_code=None,
                    )
                )
    finally:
        await engine.dispose()
    identity = settings.visual_embedding_identity
    execution_mode = cast(Literal["fake", "alibaba"], settings.visual_embedding_provider_mode)
    return GroundedRetrievalRun(
        schema_version=RUN_SCHEMA_VERSION,
        run_ref=f"igr_{secrets.token_hex(10)}",
        created_at=datetime.now(UTC).isoformat(),
        maturity="seed",
        search_version=version,
        embedding_execution_mode=execution_mode,
        embedding_provider=identity.provider,
        embedding_model=identity.model,
        embedding_dimensions=identity.dimensions,
        embedding_input_policy_version=identity.input_policy_version,
        asset_set_fingerprint=bundle.assets.asset_set_fingerprint,
        query_dataset_sha256=bundle.queries_sha256,
        seed_dataset_sha256=bundle.seed_sha256,
        observations=tuple(observations),
    )


@asynccontextmanager
async def _embedding_model(settings: Settings) -> AsyncIterator[VisualEmbeddingModel]:
    client: httpx.AsyncClient | None = None
    if settings.visual_embedding_provider_mode == "fake":
        yield DeterministicFakeVisualEmbedding()
        return
    if (
        settings.visual_embedding_provider_mode != "alibaba"
        or settings.visual_embedding_endpoint is None
        or settings.visual_embedding_api_key is None
    ):
        raise ValueError("grounded live visual embedding provider is unavailable")
    client = httpx.AsyncClient(follow_redirects=False)
    try:
        yield AlibabaVisualEmbeddingAdapter(
            client=client,
            endpoint=settings.visual_embedding_endpoint,
            api_key=settings.visual_embedding_api_key,
            timeout_seconds=settings.visual_embedding_timeout_seconds,
            concurrency=settings.visual_embedding_concurrency,
        )
    finally:
        await client.aclose()


def _validate_live_settings(settings: Settings) -> None:
    if not settings.ip_asset_hub_enabled:
        raise GroundedLivePreflightError("ip_asset_hub_disabled")
    if not settings.visual_semantic_enabled:
        raise GroundedLivePreflightError("visual_semantic_disabled")
    if settings.visual_embedding_provider_mode == "disabled":
        raise GroundedLivePreflightError("embedding_provider_disabled")
