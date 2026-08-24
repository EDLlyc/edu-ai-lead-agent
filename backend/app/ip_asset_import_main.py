from __future__ import annotations

import argparse
import asyncio
import json

from app.application.ports.ip_assets import IpAssetObjectDescriptor
from app.core.config import get_settings
from app.domain.ip_assets import (
    IpAssetCharacter,
    IpAssetMetadata,
    IpAssetSource,
    IpAssetType,
    validate_ip_asset_upload,
)
from app.domain.visual_assets import VisualAssetKind
from app.infrastructure.brand.visual_catalog import load_visual_catalog, read_visual_asset_bytes
from app.infrastructure.db.ip_assets import PostgresIpAssetRepository
from app.infrastructure.db.session import create_engine, create_session_factory
from app.infrastructure.storage.minio_ip_asset_store import MinioIpAssetStore


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import approved visual assets into the IP hub")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-assets", type=int, default=500)
    return parser.parse_args()


async def _run(*, dry_run: bool, max_assets: int) -> int:
    if not 1 <= max_assets <= 10_000:
        raise SystemExit("--max-assets must be in [1, 10000]")
    settings = get_settings()
    loaded = await asyncio.to_thread(load_visual_catalog, settings.image_asset_manifest)
    selected = tuple(asset for asset in loaded.catalog.assets if asset.approved)[:max_assets]
    if dry_run:
        print(
            json.dumps(
                {
                    "selected_count": len(selected),
                    "created_count": 0,
                    "existing_count": 0,
                    "failed_count": 0,
                    "dry_run": True,
                },
                separators=(",", ":"),
            )
        )
        return 0
    if not settings.ip_asset_hub_enabled:
        raise SystemExit("IP asset hub is disabled")
    engine = create_engine(settings)
    repository = PostgresIpAssetRepository(create_session_factory(engine))
    store = MinioIpAssetStore(settings)
    counts = {"created": 0, "existing": 0, "failed": 0}
    try:
        for asset in selected:
            try:
                body = await asyncio.to_thread(read_visual_asset_bytes, loaded, asset)
                upload = await asyncio.to_thread(
                    validate_ip_asset_upload,
                    filename=asset.filename,
                    declared_media_type=asset.media_type,
                    body=body,
                )
                descriptor: IpAssetObjectDescriptor = await store.put_immutable(upload)
                _record, created = await repository.create_asset(
                    upload=upload,
                    metadata=_metadata(asset),
                    descriptor=descriptor,
                    source_kind=IpAssetSource.SEED_IMPORT,
                    semantic_enabled=settings.visual_semantic_enabled,
                )
                counts["created" if created else "existing"] += 1
            except Exception:
                counts["failed"] += 1
        print(
            json.dumps(
                {
                    "selected_count": len(selected),
                    "created_count": counts["created"],
                    "existing_count": counts["existing"],
                    "failed_count": counts["failed"],
                    "dry_run": False,
                },
                separators=(",", ":"),
            )
        )
        return 0 if counts["failed"] == 0 else 1
    finally:
        await engine.dispose()


def _metadata(asset: object) -> IpAssetMetadata:
    from app.domain.visual_assets import VisualAsset

    if not isinstance(asset, VisualAsset):
        raise TypeError("visual catalog asset is invalid")
    characters = {value.casefold().replace("-", "_") for value in asset.characters}
    if {"sai_xiansheng", "xiao_sai"}.issubset(characters):
        character = IpAssetCharacter.DUO
    elif "xiao_sai" in characters or any("小赛" in value for value in asset.characters):
        character = IpAssetCharacter.XIAO_SAI
    elif "sai_xiansheng" in characters or any("赛先生" in value for value in asset.characters):
        character = IpAssetCharacter.SAI_XIANSHENG
    else:
        character = IpAssetCharacter.OTHER
    kind = VisualAssetKind(asset.asset_kind) if asset.asset_kind is not None else None
    asset_type = (
        {
            VisualAssetKind.IDENTITY: IpAssetType.IDENTITY_REFERENCE,
            VisualAssetKind.ACTION: IpAssetType.FULL_BODY_ACTION,
            VisualAssetKind.STYLE: IpAssetType.SCENE_ILLUSTRATION,
        }.get(kind, IpAssetType.OTHER)
        if kind is not None
        else IpAssetType.OTHER
    )
    return IpAssetMetadata(
        character=character,
        asset_type=asset_type,
        action=asset.poses[0] if asset.poses else "",
        scene=asset.scene_tags[0] if asset.scene_tags else "",
        tags=tuple((*asset.selection_tags, *asset.topics))[:20],
    )


def main() -> None:
    args = _arguments()
    raise SystemExit(asyncio.run(_run(dry_run=args.dry_run, max_assets=args.max_assets)))


if __name__ == "__main__":
    main()
