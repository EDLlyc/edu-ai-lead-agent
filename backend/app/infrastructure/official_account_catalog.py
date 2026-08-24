# ruff: noqa: RUF001 -- Chinese punctuation is intentional reader-facing copy.
from __future__ import annotations

import asyncio
import hashlib
from dataclasses import replace
from io import BytesIO
from pathlib import Path

from PIL import Image, UnidentifiedImageError

from app.application.ports.official_account_local import OfficialAccountSourceMedia
from app.domain.official_account_local import fingerprint
from app.domain.visual_assets import VisualAsset, VisualAssetKind, VisualAssetRole
from app.infrastructure.brand.visual_catalog import (
    LoadedVisualCatalog,
    load_visual_catalog,
    read_visual_asset_bytes,
)

OFFICIAL_ACCOUNT_CATALOG_PUBLICATION_MEDIA_TYPE = "image/jpeg"
OFFICIAL_ACCOUNT_CATALOG_PUBLICATION_MAX_BYTES = 10 * 1024 * 1024
OFFICIAL_ACCOUNT_CATALOG_EXPECTED_ASSET_COUNT = 41
_MAX_EDGE = 1_536


def create_catalog_publication_derivative(source: bytes) -> bytes:
    """Create deterministic, metadata-free reader bytes without modifying the PNG master."""
    try:
        with Image.open(BytesIO(source)) as opened:
            if opened.format != "PNG":
                raise ValueError("official-account catalog source must be PNG")
            opened.load()
            image = opened.convert("RGBA")
    except (OSError, UnidentifiedImageError) as error:
        raise ValueError("official-account catalog source cannot be decoded") from error
    if max(image.size) > _MAX_EDGE:
        image.thumbnail((_MAX_EDGE, _MAX_EDGE), Image.Resampling.LANCZOS)
    background = Image.new("RGB", image.size, (248, 246, 240))
    background.paste(image, mask=image.getchannel("A"))
    output = BytesIO()
    background.save(
        output,
        format="JPEG",
        quality=82,
        subsampling=2,
        optimize=False,
        progressive=False,
        exif=b"",
        icc_profile=None,
    )
    body = output.getvalue()
    if not 1 <= len(body) <= OFFICIAL_ACCOUNT_CATALOG_PUBLICATION_MAX_BYTES:
        raise ValueError("official-account catalog publication derivative is outside bounds")
    return body


def _reader_copy(asset: VisualAsset) -> tuple[str, str, str]:
    label = str(asset.display_name or "科学探索插画")[:80]
    tags = set(asset.selection_tags)
    if {"experiment", "observe", "microscope"} & tags:
        alt = f"{label}，呈现观察与实验过程的科学探索插画"
        caption = "从认真观察开始，把发现记录下来，再用实验验证自己的想法。"
    elif {"discuss", "think", "thinking", "question"} & tags:
        alt = f"{label}，呈现提问、思考与交流的科学探索插画"
        caption = "一个好问题，会在思考、讨论和下一次尝试中慢慢变得清晰。"
    elif {"read", "reading", "education"} & tags:
        alt = f"{label}，呈现阅读与共同学习场景的科学教育插画"
        caption = "把阅读中的线索带回真实生活，孩子就有机会继续提问和验证。"
    elif {"astronomy", "space", "explore", "discover"} & tags:
        alt = f"{label}，呈现面向未知展开探索的科学主题插画"
        caption = "探索不急着得到标准答案，而是从线索出发，走向更多可以验证的问题。"
    else:
        alt = f"{label}，与本节科学探索主题相呼应的品牌插画"
        caption = "让孩子保留好奇，也把每一次观察变成下一步行动的线索。"
    return label, alt[:160], caption[:200]


def _candidate_from_asset(
    loaded: LoadedVisualCatalog,
    asset: VisualAsset,
) -> OfficialAccountSourceMedia:
    expected_role = None
    if asset.asset_kind == VisualAssetKind.IDENTITY:
        expected_role = VisualAssetRole.IDENTITY_REFERENCE
    elif asset.asset_kind == VisualAssetKind.ACTION:
        expected_role = VisualAssetRole.ACTION_REFERENCE
    if (
        not asset.approved
        or expected_role is None
        or asset.roles != (expected_role,)
        or asset.media_type != "image/png"
        or asset.width < 256
        or asset.height < 256
        or asset.width / asset.height > 3.0
        or asset.height / asset.width > 3.0
    ):
        raise ValueError("official-account catalog asset is not publication suitable")
    source = read_visual_asset_bytes(loaded, asset)
    if hashlib.sha256(source).hexdigest() != asset.checksum:
        raise ValueError("official-account catalog asset checksum changed")
    publication = create_catalog_publication_derivative(source)
    publication_checksum = hashlib.sha256(publication).hexdigest()
    label, alt, caption = _reader_copy(asset)
    public_ref = asset.asset_id[:16]
    return OfficialAccountSourceMedia(
        source_image_artifact_id=None,
        fixture_id=f"catalog:{public_ref}",
        media_type=OFFICIAL_ACCOUNT_CATALOG_PUBLICATION_MEDIA_TYPE,
        byte_size=len(publication),
        sha256=publication_checksum,
        ordinal=0,
        semantic_label=label,
        selection_reason="manifest_approved_catalog_candidate",
        candidate_id=public_ref,
        semantic_tags=asset.selection_tags,
        alt_text=alt,
        caption_text=caption,
        publication_priority=1_000 - asset.priority,
        catalog_asset_id=asset.asset_id,
        catalog_asset_ref=public_ref,
        catalog_version=loaded.catalog.catalog_version,
        source_master_sha256=asset.checksum,
    )


class LocalOfficialAccountCatalogMediaProvider:
    def __init__(self, manifest_path: str | Path) -> None:
        self._manifest_path = Path(manifest_path)

    async def load_candidates(self) -> tuple[OfficialAccountSourceMedia, ...]:
        return await asyncio.to_thread(self._load_candidates)

    def _load_candidates(self) -> tuple[OfficialAccountSourceMedia, ...]:
        loaded = load_visual_catalog(self._manifest_path)
        approved = tuple(asset for asset in loaded.catalog.assets if asset.approved)
        if len(approved) != OFFICIAL_ACCOUNT_CATALOG_EXPECTED_ASSET_COUNT:
            raise ValueError("official-account catalog does not contain the exact approved set")
        candidates = tuple(_candidate_from_asset(loaded, asset) for asset in approved)
        if (
            len(candidates) != OFFICIAL_ACCOUNT_CATALOG_EXPECTED_ASSET_COUNT
            or len({item.catalog_asset_ref for item in candidates}) != len(candidates)
            or len({item.source_master_sha256 for item in candidates}) != len(candidates)
            or len({item.sha256 for item in candidates}) != len(candidates)
        ):
            raise ValueError("official-account catalog candidate identity is not unique")
        return candidates

    async def revalidate_candidate(
        self,
        candidate: OfficialAccountSourceMedia,
    ) -> OfficialAccountSourceMedia:
        refreshed = await asyncio.to_thread(
            self._load_one_candidate,
            candidate.catalog_asset_ref,
        )
        if refreshed is None or any(
            left != right
            for left, right in (
                (refreshed.catalog_asset_id, candidate.catalog_asset_id),
                (refreshed.catalog_version, candidate.catalog_version),
                (refreshed.source_master_sha256, candidate.source_master_sha256),
                (refreshed.sha256, candidate.sha256),
                (refreshed.byte_size, candidate.byte_size),
            )
        ):
            raise ValueError("official-account catalog candidate changed")
        return replace(
            refreshed,
            ordinal=candidate.ordinal,
            assigned_section_index=candidate.assigned_section_index,
            score_band=candidate.score_band,
            selection_reason_code=candidate.selection_reason_code,
            selection_method=candidate.selection_method,
            similarity_band=candidate.similarity_band,
        )

    async def catalog_is_current(
        self,
        candidates: tuple[OfficialAccountSourceMedia, ...],
    ) -> bool:
        return await asyncio.to_thread(self._catalog_is_current, candidates)

    def _catalog_is_current(
        self,
        candidates: tuple[OfficialAccountSourceMedia, ...],
    ) -> bool:
        try:
            loaded = load_visual_catalog(self._manifest_path)
            approved = tuple(asset for asset in loaded.catalog.assets if asset.approved)
            if len(approved) != len(candidates):
                return False
            expected = {
                item.catalog_asset_id: (item.source_master_sha256, item.catalog_version)
                for item in candidates
            }
            for asset in approved:
                if expected.get(asset.asset_id) != (
                    asset.checksum,
                    loaded.catalog.catalog_version,
                ):
                    return False
                read_visual_asset_bytes(loaded, asset)
            return True
        except ValueError:
            return False

    async def read_publication_bytes(
        self,
        *,
        catalog_asset_ref: str,
        catalog_version: str,
        source_master_sha256: str,
        publication_sha256: str,
    ) -> bytes:
        candidate = await asyncio.to_thread(self._load_one_candidate, catalog_asset_ref)
        if (
            candidate is None
            or candidate.catalog_version != catalog_version
            or candidate.source_master_sha256 != source_master_sha256
            or candidate.sha256 != publication_sha256
        ):
            raise ValueError("official-account catalog publication identity changed")
        loaded = await asyncio.to_thread(load_visual_catalog, self._manifest_path)
        assert candidate.catalog_asset_id is not None
        asset = loaded.catalog.asset_by_id.get(candidate.catalog_asset_id)
        if asset is None:
            raise ValueError("official-account catalog asset is unavailable")
        source = await asyncio.to_thread(read_visual_asset_bytes, loaded, asset)
        publication = await asyncio.to_thread(create_catalog_publication_derivative, source)
        if hashlib.sha256(publication).hexdigest() != publication_sha256:
            raise ValueError("official-account catalog publication bytes changed")
        return publication

    def _load_one_candidate(
        self,
        catalog_asset_ref: str | None,
    ) -> OfficialAccountSourceMedia:
        if catalog_asset_ref is None or len(catalog_asset_ref) != 16:
            raise ValueError("official-account catalog public reference is invalid")
        loaded = load_visual_catalog(self._manifest_path)
        matches = tuple(
            asset
            for asset in loaded.catalog.assets
            if asset.approved and asset.asset_id.startswith(catalog_asset_ref)
        )
        if len(matches) != 1:
            raise ValueError("official-account catalog public reference is ambiguous")
        return _candidate_from_asset(loaded, matches[0])


def _catalog_fingerprint(candidates: tuple[OfficialAccountSourceMedia, ...]) -> str:
    return fingerprint(
        "official-account-approved-catalog-v1",
        tuple(
            sorted(
                (
                    item.catalog_asset_ref,
                    item.source_master_sha256,
                    item.sha256,
                    item.byte_size,
                    item.catalog_version,
                )
                for item in candidates
            )
        ),
    )


def official_account_catalog_fingerprint(
    candidates: tuple[OfficialAccountSourceMedia, ...],
) -> str:
    return _catalog_fingerprint(candidates)
