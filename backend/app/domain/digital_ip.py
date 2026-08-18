"""Deterministic, read-only projection for the single local digital-IP portfolio."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from uuid import UUID

from app.domain.brand_knowledge import BrandAudience, BrandDocumentKind
from app.domain.value_objects import sha256_bytes
from app.domain.visual_assets import (
    VisualAsset,
    VisualAssetCatalog,
    VisualAssetError,
    VisualAssetKind,
)

DIGITAL_IP_PROFILE_ID = "sai-xiansheng-xiao-sai"
DIGITAL_IP_PROFILE_VERSION = "digital-ip-profile-v1"
MAX_DIGITAL_IP_VISUAL_ASSETS = 12
_CHARACTER_IDS = frozenset({"sai-xiansheng", "xiao-sai"})
_PRIVATE_VISUAL_VALUE = re.compile(r"(?i)(?:[\\/]|^[a-z][a-z0-9+.-]*:|[0-9a-f]{64})")


class DigitalIpVisualCatalogStatus(StrEnum):
    READY = "ready"
    EMPTY = "empty"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class DigitalIpCharacter:
    character_id: str
    display_name: str
    role: str


@dataclass(frozen=True, slots=True)
class DigitalIpDocumentBinding:
    document_id: UUID
    version_id: UUID
    version: int
    title: str
    document_kind: BrandDocumentKind
    audience: BrandAudience
    valid_from: date | None
    valid_until: date | None
    tone_tags: tuple[str, ...] = ()
    safety_tags: tuple[str, ...] = ()
    visual_tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class DigitalIpVisualAsset:
    asset_ref: str
    checksum_ref: str
    display_name: str
    asset_kind: VisualAssetKind
    characters: tuple[str, ...]
    roles: tuple[str, ...]
    topics: tuple[str, ...]
    poses: tuple[str, ...]
    scene_tags: tuple[str, ...]
    width: int
    height: int
    approved: bool
    priority: int


@dataclass(frozen=True, slots=True)
class DigitalIpVisualCatalogProjection:
    status: DigitalIpVisualCatalogStatus
    catalog_version: str | None
    assets: tuple[DigitalIpVisualAsset, ...]


@dataclass(frozen=True, slots=True)
class DigitalIpProfile:
    profile_id: str
    profile_version: str
    display_name: str
    brand_slug: str
    identity_summary: str
    characters: tuple[DigitalIpCharacter, ...]
    audiences: tuple[BrandAudience, ...]
    channels: tuple[str, ...]
    content_scenarios: tuple[str, ...]
    document_bindings: tuple[DigitalIpDocumentBinding, ...]
    active_document_count: int
    active_version_ids: tuple[UUID, ...]
    document_kinds: tuple[BrandDocumentKind, ...]
    tone_tags: tuple[str, ...]
    safety_tags: tuple[str, ...]
    visual_tags: tuple[str, ...]
    visual_catalog_status: DigitalIpVisualCatalogStatus
    visual_catalog_version: str | None
    visual_assets: tuple[DigitalIpVisualAsset, ...]
    profile_fingerprint: str
    evidence_eligible: bool = False


def project_visual_catalog(
    catalog: VisualAssetCatalog,
    *,
    limit: int = MAX_DIGITAL_IP_VISUAL_ASSETS,
) -> DigitalIpVisualCatalogProjection:
    """Return bounded approved metadata without filesystem or image-bearing fields."""

    if not 1 <= limit <= MAX_DIGITAL_IP_VISUAL_ASSETS:
        raise ValueError("digital IP visual asset limit is invalid")
    selected = sorted(
        (
            asset
            for asset in catalog.assets
            if asset.approved and _CHARACTER_IDS.intersection(asset.characters)
        ),
        key=lambda asset: (-asset.priority, asset.asset_id),
    )[:limit]
    assets = tuple(_project_visual_asset(asset) for asset in selected)
    return DigitalIpVisualCatalogProjection(
        status=(
            DigitalIpVisualCatalogStatus.READY if assets else DigitalIpVisualCatalogStatus.EMPTY
        ),
        catalog_version=catalog.catalog_version,
        assets=assets,
    )


def unavailable_visual_catalog() -> DigitalIpVisualCatalogProjection:
    return DigitalIpVisualCatalogProjection(
        status=DigitalIpVisualCatalogStatus.UNAVAILABLE,
        catalog_version=None,
        assets=(),
    )


def project_digital_ip_profile(
    document_bindings: tuple[DigitalIpDocumentBinding, ...],
    visual_catalog: DigitalIpVisualCatalogProjection,
) -> DigitalIpProfile:
    """Aggregate active-ready version metadata into one replay-stable profile."""

    ordered_bindings = tuple(
        sorted(
            document_bindings,
            key=lambda binding: (
                binding.document_kind.value,
                binding.title,
                str(binding.version_id),
            ),
        )
    )
    active_version_ids = tuple(binding.version_id for binding in ordered_bindings)
    document_kinds = tuple(
        sorted({binding.document_kind for binding in ordered_bindings}, key=lambda item: item.value)
    )
    tone_tags = _aggregate_tags(binding.tone_tags for binding in ordered_bindings)
    safety_tags = _aggregate_tags(binding.safety_tags for binding in ordered_bindings)
    visual_tags = _aggregate_tags(binding.visual_tags for binding in ordered_bindings)
    characters = (
        DigitalIpCharacter(
            character_id="sai-xiansheng",
            display_name="赛先生",
            role="品牌主体",
        ),
        DigitalIpCharacter(
            character_id="xiao-sai",
            display_name="小赛",
            role="数字角色",
        ),
    )
    fingerprint_payload = {
        "active_version_ids": [str(version_id) for version_id in active_version_ids],
        "brand_slug": "sai-xiansheng",
        "characters": [character.character_id for character in characters],
        "document_kinds": [kind.value for kind in document_kinds],
        "profile_id": DIGITAL_IP_PROFILE_ID,
        "profile_version": DIGITAL_IP_PROFILE_VERSION,
        "safety_tags": list(safety_tags),
        "tone_tags": list(tone_tags),
        "visual_asset_refs": [asset.asset_ref for asset in visual_catalog.assets],
        "visual_catalog_status": visual_catalog.status.value,
        "visual_catalog_version": visual_catalog.catalog_version,
        "visual_tags": list(visual_tags),
    }
    fingerprint = sha256_bytes(
        json.dumps(
            fingerprint_payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    )
    return DigitalIpProfile(
        profile_id=DIGITAL_IP_PROFILE_ID,
        profile_version=DIGITAL_IP_PROFILE_VERSION,
        display_name="赛先生与小赛",
        brand_slug="sai-xiansheng",
        identity_summary="赛先生品牌与小赛数字角色的本地受控资产视图",
        characters=characters,
        audiences=(BrandAudience.PARENTS, BrandAudience.INTERNAL),
        channels=("wechat_moments", "internal_copy_generation"),
        content_scenarios=("science_education", "parent_communication", "brand_copy"),
        document_bindings=ordered_bindings,
        active_document_count=len(ordered_bindings),
        active_version_ids=active_version_ids,
        document_kinds=document_kinds,
        tone_tags=tone_tags,
        safety_tags=safety_tags,
        visual_tags=visual_tags,
        visual_catalog_status=visual_catalog.status,
        visual_catalog_version=visual_catalog.catalog_version,
        visual_assets=visual_catalog.assets,
        profile_fingerprint=fingerprint,
        evidence_eligible=False,
    )


def _project_visual_asset(asset: VisualAsset) -> DigitalIpVisualAsset:
    asset_kind = (
        asset.asset_kind
        if isinstance(asset.asset_kind, VisualAssetKind)
        else VisualAssetKind.parse(str(asset.asset_kind))
    )
    display_name = asset.display_name
    if display_name is None or display_name == asset.filename:
        display_name = f"受控视觉素材 {asset.asset_id[:8]}"
    else:
        display_name = _public_visual_value(display_name, field_name="display_name")
    return DigitalIpVisualAsset(
        asset_ref=asset.asset_id[:16],
        checksum_ref=asset.checksum[:16],
        display_name=display_name,
        asset_kind=asset_kind,
        characters=_public_visual_values(asset.characters, field_name="characters"),
        roles=tuple(role.value for role in asset.roles),
        topics=_public_visual_values(asset.topics, field_name="topics"),
        poses=_public_visual_values(asset.poses, field_name="poses"),
        scene_tags=_public_visual_values(asset.scene_tags, field_name="scene_tags"),
        width=asset.width,
        height=asset.height,
        approved=True,
        priority=asset.priority,
    )


def _aggregate_tags(groups: Iterable[tuple[str, ...]]) -> tuple[str, ...]:
    return tuple(sorted({tag for group in groups for tag in group}))


def _public_visual_values(values: tuple[str, ...], *, field_name: str) -> tuple[str, ...]:
    return tuple(_public_visual_value(value, field_name=field_name) for value in values)


def _public_visual_value(value: str, *, field_name: str) -> str:
    """Reject path-, URL-, and full-digest-shaped values before browser projection."""

    if _PRIVATE_VISUAL_VALUE.search(value):
        raise VisualAssetError(f"visual asset {field_name} is not browser-safe")
    return value
