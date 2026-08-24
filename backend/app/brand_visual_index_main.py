from __future__ import annotations

import argparse
import asyncio
import json
from uuid import uuid4

import httpx

from app.application.ports.visual_retrieval import VisualEmbeddingModel
from app.application.services.visual_retrieval import VisualCatalogIndexService
from app.core.config import get_settings
from app.infrastructure.ai.visual_embedding import (
    AlibabaVisualEmbeddingAdapter,
    DeterministicFakeVisualEmbedding,
)
from app.infrastructure.brand.visual_catalog import (
    load_visual_catalog,
    read_visual_asset_bytes,
)
from app.infrastructure.db.session import create_engine, create_session_factory
from app.infrastructure.db.visual_retrieval import PostgresVisualIndexRepository


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Index approved private visual assets")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-assets", type=int, default=100)
    parser.add_argument("--max-attempts", type=int, choices=(1,), default=1)
    return parser.parse_args()


async def _run(*, dry_run: bool, max_assets: int, max_attempts: int = 1) -> int:
    if not 1 <= max_assets <= 10_000:
        raise SystemExit("--max-assets must be in [1, 10000]")
    if max_attempts != 1:
        raise SystemExit("--max-attempts must be exactly 1")
    settings = get_settings()
    try:
        loaded = await asyncio.to_thread(load_visual_catalog, settings.image_asset_manifest)
    except Exception:
        raise SystemExit("approved visual catalog is unavailable") from None
    assets = tuple(
        sorted(
            (asset for asset in loaded.catalog.assets if asset.approved),
            key=lambda item: item.asset_id,
        )
    )
    selected = assets[:max_assets]
    if dry_run:
        print(
            json.dumps(
                {
                    "catalog_asset_count": len(assets),
                    "selected_asset_count": len(selected),
                    "dry_run": True,
                },
                separators=(",", ":"),
            )
        )
        return 0
    if settings.visual_embedding_provider_mode == "disabled":
        raise SystemExit("visual embedding provider is disabled")
    engine = create_engine(settings)
    client: httpx.AsyncClient | None = None
    try:
        if settings.visual_embedding_provider_mode == "fake":
            embeddings: VisualEmbeddingModel = DeterministicFakeVisualEmbedding()
        else:
            if (
                settings.visual_embedding_endpoint is None
                or settings.visual_embedding_api_key is None
            ):
                raise SystemExit("visual embedding secrets are unavailable")
            client = httpx.AsyncClient(follow_redirects=False)
            embeddings = AlibabaVisualEmbeddingAdapter(
                client=client,
                endpoint=settings.visual_embedding_endpoint,
                api_key=settings.visual_embedding_api_key,
                timeout_seconds=settings.visual_embedding_timeout_seconds,
                concurrency=settings.visual_embedding_concurrency,
            )
        service = VisualCatalogIndexService(
            embeddings=embeddings,
            repository=PostgresVisualIndexRepository(create_session_factory(engine)),
            identity=settings.visual_embedding_identity,
            lease_seconds=settings.visual_index_lease_seconds,
        )
        counts = {"indexed": 0, "existing": 0, "failed": 0}
        worker_id = f"local-visual-index:{uuid4()}"
        for original in selected:
            try:
                refreshed = await asyncio.to_thread(
                    load_visual_catalog, settings.image_asset_manifest
                )
                current = refreshed.catalog.asset_by_id.get(original.asset_id)
                if current is None or current.checksum != original.checksum or not current.approved:
                    counts["failed"] += 1
                    continue
                expected_asset_id = current.asset_id
                expected_checksum = current.checksum
                expected_catalog_version = refreshed.catalog.catalog_version
                body = await asyncio.to_thread(read_visual_asset_bytes, refreshed, current)

                async def verify_current_asset(
                    asset_id: str = expected_asset_id,
                    checksum: str = expected_checksum,
                    catalog_version: str = expected_catalog_version,
                ) -> bool:
                    after = await asyncio.to_thread(
                        load_visual_catalog, settings.image_asset_manifest
                    )
                    after_asset = after.catalog.asset_by_id.get(asset_id)
                    if (
                        after.catalog.catalog_version != catalog_version
                        or after_asset is None
                        or not after_asset.approved
                        or after_asset.checksum != checksum
                    ):
                        return False
                    rechecked_body = await asyncio.to_thread(
                        read_visual_asset_bytes, after, after_asset
                    )
                    del rechecked_body
                    return True

                result = await service.index_asset(
                    catalog_version=refreshed.catalog.catalog_version,
                    asset_id=current.asset_id,
                    checksum=current.checksum,
                    body=body,
                    worker_id=worker_id,
                    verify_current=verify_current_asset,
                )
                del body
                counts[result] += 1
            except Exception:
                counts["failed"] += 1
                continue
        print(
            json.dumps(
                {
                    "catalog_asset_count": len(assets),
                    "attempted_count": len(selected),
                    "indexed_count": counts["indexed"],
                    "existing_count": counts["existing"],
                    "failed_count": counts["failed"],
                    "dry_run": False,
                },
                separators=(",", ":"),
            )
        )
        return 0 if counts["failed"] == 0 else 1
    finally:
        if client is not None:
            await client.aclose()
        await engine.dispose()


def main() -> None:
    args = _arguments()
    raise SystemExit(
        asyncio.run(
            _run(
                dry_run=args.dry_run,
                max_assets=args.max_assets,
                max_attempts=args.max_attempts,
            )
        )
    )


if __name__ == "__main__":
    main()
