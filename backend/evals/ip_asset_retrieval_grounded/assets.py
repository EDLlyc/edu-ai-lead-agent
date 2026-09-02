from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Literal, cast
from uuid import UUID

from app.application.ports.ip_assets import (
    IpAssetPage,
    IpAssetQuery,
    IpAssetRecord,
    IpAssetVectorHit,
)
from app.domain.ip_assets import IpAssetSemanticStatus, IpAssetStatus
from app.domain.visual_retrieval import VisualEmbeddingIdentity, VisualEmbeddingResult
from app.infrastructure.brand.visual_catalog import load_visual_catalog
from app.infrastructure.db.ip_assets import PostgresIpAssetRepository
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from .models import (
    ASSET_SNAPSHOT_SCHEMA_VERSION,
    EXPECTED_ASSET_COUNT,
    SafeGroundedAsset,
    SafeGroundedAssetSnapshot,
)


def build_safe_asset_snapshot(manifest_path: Path) -> SafeGroundedAssetSnapshot:
    loaded = load_visual_catalog(manifest_path)
    approved = tuple(asset for asset in loaded.catalog.assets if asset.approved)
    if len(approved) != EXPECTED_ASSET_COUNT:
        raise ValueError("grounded catalog must contain exactly 41 approved assets")
    assets = tuple(
        sorted(
            (
                SafeGroundedAsset(
                    catalog_ref=asset.asset_id[:16],
                    display_name=str(asset.display_name or "IP asset")[:80],
                    asset_kind=_safe_asset_kind(asset.asset_kind),
                    characters=_safe_characters(asset.characters),
                    roles=tuple(role.value for role in asset.roles),
                    poses=asset.poses,
                    scene_tags=asset.scene_tags,
                    topics=asset.topics,
                    selection_tags=asset.selection_tags,
                    width=asset.width,
                    height=asset.height,
                    has_alpha=asset.has_alpha,
                )
                for asset in approved
            ),
            key=lambda item: item.catalog_ref,
        )
    )
    fingerprint = safe_asset_fingerprint(
        catalog_version=loaded.catalog.catalog_version,
        assets=assets,
    )
    return SafeGroundedAssetSnapshot(
        schema_version=ASSET_SNAPSHOT_SCHEMA_VERSION,
        catalog_version=loaded.catalog.catalog_version,
        asset_set_fingerprint=fingerprint,
        assets=assets,
    )


def safe_asset_fingerprint(*, catalog_version: str, assets: tuple[SafeGroundedAsset, ...]) -> str:
    payload = {
        "schema_version": ASSET_SNAPSHOT_SCHEMA_VERSION,
        "catalog_version": catalog_version,
        "assets": [asset.model_dump(mode="json") for asset in assets],
    }
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def assert_safe_snapshot_current(
    snapshot: SafeGroundedAssetSnapshot, *, manifest_path: Path
) -> None:
    current = build_safe_asset_snapshot(manifest_path)
    if current != snapshot:
        raise ValueError("grounded approved 41-asset snapshot drifted")


@dataclass(frozen=True, slots=True)
class LiveGroundedAssetMap:
    records: tuple[IpAssetRecord, ...]
    catalog_ref_by_asset_ref: dict[str, str]
    allowed_asset_ids: frozenset[UUID]


class GroundedLivePreflightError(ValueError):
    """Closed, non-sensitive reason for refusing a grounded live run."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(f"grounded live preflight failed: {code}")


def _safe_asset_kind(value: object) -> Literal["identity", "action"]:
    normalized = getattr(value, "value", value)
    if normalized not in {"identity", "action"}:
        raise ValueError("grounded approved asset kind is unsupported")
    return cast(Literal["identity", "action"], normalized)


def _safe_characters(
    values: tuple[str, ...],
) -> tuple[Literal["xiao-sai", "sai-xiansheng"], ...]:
    if not values or any(value not in {"xiao-sai", "sai-xiansheng"} for value in values):
        raise ValueError("grounded approved asset characters are unsupported")
    return cast(tuple[Literal["xiao-sai", "sai-xiansheng"], ...], values)


async def map_live_grounded_assets(
    *,
    repository: PostgresIpAssetRepository,
    snapshot: SafeGroundedAssetSnapshot,
    manifest_path: Path,
    identity: VisualEmbeddingIdentity,
) -> LiveGroundedAssetMap:
    try:
        assert_safe_snapshot_current(snapshot, manifest_path=manifest_path)
    except ValueError as error:
        raise GroundedLivePreflightError("asset_snapshot_drift") from error
    loaded = load_visual_catalog(manifest_path)
    approved_by_ref = {
        asset.asset_id[:16]: asset for asset in loaded.catalog.assets if asset.approved
    }
    records: list[IpAssetRecord] = []
    catalog_ref_by_asset_ref: dict[str, str] = {}
    for asset in snapshot.assets:
        source = approved_by_ref.get(asset.catalog_ref)
        if source is None:
            raise GroundedLivePreflightError("approved_asset_unavailable")
        record = await repository.get_by_sha256(source.checksum)
        if record is None:
            raise GroundedLivePreflightError("dynamic_asset_missing")
        if record.status is not IpAssetStatus.READY or record.shared_at is None:
            raise GroundedLivePreflightError("dynamic_asset_not_ready_shared")
        if record.semantic_status is not IpAssetSemanticStatus.READY:
            raise GroundedLivePreflightError("dynamic_embedding_not_ready")
        records.append(record)
        catalog_ref_by_asset_ref[record.asset_ref] = asset.catalog_ref
    if (
        len(records) != EXPECTED_ASSET_COUNT
        or len({record.id for record in records}) != EXPECTED_ASSET_COUNT
        or len(catalog_ref_by_asset_ref) != EXPECTED_ASSET_COUNT
    ):
        raise GroundedLivePreflightError("dynamic_mapping_not_one_to_one")
    allowed_asset_ids = frozenset(record.id for record in records)
    shared_page = await repository.list_assets(IpAssetQuery(limit=500))
    if shared_page.next_cursor_id is not None:
        raise GroundedLivePreflightError("shared_corpus_exceeds_safe_projection")
    if not allowed_asset_ids.issubset(record.id for record in shared_page.items):
        raise GroundedLivePreflightError("dynamic_asset_not_searchable")
    probe = VisualEmbeddingResult(
        identity=identity,
        input_sha256="0" * 64,
        request_fingerprint="1" * 64,
        vector=(1.0,) + (0.0,) * (identity.dimensions - 1),
    )
    compatible_hits = await repository.search_vectors(
        query=IpAssetQuery(limit=500),
        embedding=probe,
        identity=identity,
    )
    if not allowed_asset_ids.issubset(hit.record.id for hit in compatible_hits):
        raise GroundedLivePreflightError("compatible_embedding_incomplete")
    return LiveGroundedAssetMap(
        records=tuple(records),
        catalog_ref_by_asset_ref=catalog_ref_by_asset_ref,
        allowed_asset_ids=allowed_asset_ids,
    )


class GroundedIpAssetRepository(PostgresIpAssetRepository):
    """Evaluation-only corpus view over the production repository implementation."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        allowed_asset_ids: frozenset[UUID],
    ) -> None:
        super().__init__(session_factory)
        if len(allowed_asset_ids) != EXPECTED_ASSET_COUNT:
            raise ValueError("grounded repository needs exactly 41 allowed assets")
        self._allowed_asset_ids = allowed_asset_ids

    async def list_assets(self, query: IpAssetQuery) -> IpAssetPage:
        unbounded = await super().list_assets(
            replace(
                query,
                cursor_created_at=None,
                cursor_id=None,
                limit=500,
            )
        )
        selected = tuple(
            record for record in unbounded.items if record.id in self._allowed_asset_ids
        )[: query.limit]
        return IpAssetPage(
            items=selected,
            next_cursor_created_at=None,
            next_cursor_id=None,
        )

    async def search_vectors(
        self,
        *,
        query: IpAssetQuery,
        embedding: VisualEmbeddingResult,
        identity: VisualEmbeddingIdentity,
    ) -> tuple[IpAssetVectorHit, ...]:
        unbounded = await super().search_vectors(
            query=replace(query, limit=500),
            embedding=embedding,
            identity=identity,
        )
        return tuple(hit for hit in unbounded if hit.record.id in self._allowed_asset_ids)[
            : query.limit
        ]
