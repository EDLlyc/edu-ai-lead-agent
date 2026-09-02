from __future__ import annotations

import asyncio
import hashlib
import io
import json
import zipfile
from base64 import urlsafe_b64encode
from dataclasses import replace
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import cast
from uuid import UUID

import pytest
from app.api.v1.routes import ip_assets as routes
from app.application.ports.ip_assets import (
    IpAssetDerivativeRecord,
    IpAssetLeaderboardItemRecord,
    IpAssetLeaderboardRecord,
    IpAssetPage,
    IpAssetPersonalItemRecord,
    IpAssetPersonalPage,
    IpAssetProfileRecord,
    IpAssetQuery,
    IpAssetRecord,
    IpAssetRepository,
    IpAssetSearchAggregateRecord,
    IpAssetStore,
    IpAssetVectorHit,
)
from app.application.services.ip_assets import (
    IpAssetPreparedDownload,
    IpAssetPreparedThumbnail,
    IpAssetPreparedZip,
    IpAssetSearchHit,
    IpAssetSearchMetricBucket,
    IpAssetSearchMetrics,
    IpAssetSearchResult,
    IpAssetService,
    IpAssetUploadResult,
    _build_zip,
    _explanation,
    _extract_filters,
    _IpAssetLeaseLost,
    _metadata_search_hit,
    _run_with_lease_heartbeat,
    enqueue_ip_asset_generation,
)
from app.core.config import Settings
from app.core.errors import ConflictError, IpAssetUploadRejectedError, NotFoundError
from app.domain.ip_assets import (
    IP_ASSET_SEARCH_V3_VERSION,
    IP_ASSET_SEARCH_VERSION,
    IP_ASSET_THUMBNAIL_POLICY_VERSION,
    IpAssetCharacter,
    IpAssetLeaderboardPeriod,
    IpAssetMembershipSource,
    IpAssetMetadata,
    IpAssetOrientation,
    IpAssetSearchEventKind,
    IpAssetSearchMetricPeriod,
    IpAssetSearchMode,
    IpAssetSemanticStatus,
    IpAssetSource,
    IpAssetStatus,
    IpAssetType,
    IpAssetValidationError,
    build_ip_asset_thumbnail,
    canonical_name_base,
    leaderboard_start_date,
    normalize_generation_reference_refs,
    profile_token_digest,
    validate_ip_asset_upload,
)
from app.domain.visual_retrieval import (
    VisualEmbeddingIdentity,
    VisualEmbeddingRequest,
    VisualEmbeddingResult,
)
from app.infrastructure.storage.minio_ip_asset_store import MinioIpAssetStore
from app.schemas.ip_assets import IpAssetGenerationRequest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from PIL import Image
from pydantic import ValidationError


def _raster(media_type: str = "image/png", size: tuple[int, int] = (64, 48)) -> bytes:
    output = io.BytesIO()
    mode = "RGBA" if media_type == "image/png" else "RGB"
    color = (244, 196, 48, 255) if mode == "RGBA" else (244, 196, 48)
    image = Image.new(mode, size, color)
    image.save(
        output, format={"image/png": "PNG", "image/jpeg": "JPEG", "image/webp": "WEBP"}[media_type]
    )
    return output.getvalue()


def _asset() -> IpAssetRecord:
    return IpAssetRecord(
        id=UUID("11111111-1111-4111-8111-111111111111"),
        asset_ref="ipa_11111111111111111111",
        blob_sha256="a" * 64,
        perceptual_hash="0" * 16,
        safe_original_filename="source.png",
        media_type="image/png",
        byte_size=128,
        width=64,
        height=48,
        has_alpha=True,
        orientation=IpAssetOrientation.LANDSCAPE,
        bucket="private-bucket",
        object_key="ip-assets/private-object-key.png",
        canonical_name="小赛-表情包-开心-社群-横图-v001",
        canonical_slug="xiao_sai-meme_sticker-happy-social-landscape-v001",
        name_version=1,
        character=IpAssetCharacter.XIAO_SAI,
        asset_type=IpAssetType.MEME_STICKER,
        source_kind=IpAssetSource.UPLOADED,
        department="市场部",
        contributor="同事甲",
        emotion="开心",
        action="庆祝",
        scene="社群",
        intended_use="社交媒体",
        style="3D",
        tags=("开心", "科学"),
        status=IpAssetStatus.READY,
        semantic_status=IpAssetSemanticStatus.UNAVAILABLE,
        failure_code=None,
        parent_asset_id=None,
        created_at=datetime(2026, 8, 24, 9, 0, tzinfo=UTC),
        updated_at=datetime(2026, 8, 24, 9, 0, tzinfo=UTC),
        shared_at=datetime(2026, 8, 24, 9, 0, tzinfo=UTC),
    )


class _FakeService:
    def __init__(self) -> None:
        self.asset = _asset()
        self.body = _raster()
        self.search_semaphore: asyncio.Semaphore | None = None

    async def upload(self, **_kwargs: object) -> IpAssetUploadResult:
        return IpAssetUploadResult(
            asset=self.asset,
            duplicate=False,
            near_duplicate_ref="ipa_22222222222222222222",
            near_duplicate_distance=4,
        )

    async def list(self, _query: object) -> IpAssetPage:
        return IpAssetPage(items=(self.asset,), next_cursor_created_at=None, next_cursor_id=None)

    async def get(self, _asset_ref: str, **_kwargs: object) -> IpAssetRecord:
        return self.asset

    async def original(self, _asset_ref: str, **_kwargs: object) -> tuple[IpAssetRecord, bytes]:
        return self.asset, self.body

    async def thumbnail(self, _asset_ref: str, **_kwargs: object) -> IpAssetPreparedThumbnail:
        thumbnail = build_ip_asset_thumbnail(self.body)
        return IpAssetPreparedThumbnail(
            asset=self.asset,
            derivative=IpAssetDerivativeRecord(
                asset_id=self.asset.id,
                policy_version=IP_ASSET_THUMBNAIL_POLICY_VERSION,
                kind="thumbnail",
                source_sha256=self.asset.blob_sha256,
                media_type=thumbnail.media_type,
                byte_size=thumbnail.byte_size,
                width=thumbnail.width,
                height=thumbnail.height,
                bucket="private-bucket",
                object_key="private-derivative-key",
                sha256=thumbnail.sha256,
            ),
            body=thumbnail.body,
        )

    async def download(self, _asset_ref: str, **_kwargs: object) -> IpAssetPreparedDownload:
        return IpAssetPreparedDownload(asset=self.asset, body=self.body)

    async def download_zip(self, _refs: tuple[str, ...], **_kwargs: object) -> IpAssetPreparedZip:
        return IpAssetPreparedZip(body=_build_zip([(self.asset, self.body)]), assets=(self.asset,))

    async def search_text(self, **_kwargs: object) -> IpAssetSearchResult:
        return IpAssetSearchResult(
            mode=IpAssetSearchMode.DEGRADED_METADATA,
            degraded_reason="semantic_disabled",
            search_version="ip-asset-hybrid-v2",
            items=(),
        )

    async def search_image(self, **_kwargs: object) -> IpAssetSearchResult:
        assert self.search_semaphore is not None and self.search_semaphore.locked()
        return await self.search_text()


class _ProfileFakeService(_FakeService):
    def __init__(self) -> None:
        super().__init__()
        now = datetime(2026, 8, 24, 9, 0, tzinfo=UTC)
        self.profile = IpAssetProfileRecord(
            id=UUID("33333333-3333-4333-8333-333333333333"),
            profile_ref="ipp_33333333333333333333",
            display_name="内容同事",
            department="品牌部",
            created_at=now,
            updated_at=now,
        )
        self.favorite_calls: list[tuple[str, bool]] = []

    async def bootstrap_profile(self, **_kwargs: object):
        return self.profile, True

    async def profile_for_token(self, _token: str):
        return self.profile

    async def personal_assets(self, **_kwargs: object) -> IpAssetPersonalPage:
        return IpAssetPersonalPage(
            items=(
                IpAssetPersonalItemRecord(
                    asset=self.asset,
                    membership_sources=(IpAssetMembershipSource.UPLOADED,),
                    favorite=True,
                ),
            ),
            next_cursor_created_at=None,
            next_cursor_id=None,
        )

    async def search_text(self, **_kwargs: object) -> IpAssetSearchResult:
        return IpAssetSearchResult(
            mode=IpAssetSearchMode.DEGRADED_METADATA,
            degraded_reason="semantic_disabled",
            search_version=IP_ASSET_SEARCH_VERSION,
            items=(
                IpAssetSearchHit(
                    asset=self.asset,
                    similarity=None,
                    explanation="元数据匹配",
                ),
            ),
        )

    async def favorite(self, *, asset_ref: str, favorite: bool, **_kwargs: object) -> None:
        self.favorite_calls.append((asset_ref, favorite))

    async def favorite_asset_ids(self, **_kwargs: object) -> frozenset[UUID]:
        return frozenset({self.asset.id})

    async def share(self, **_kwargs: object) -> IpAssetRecord:
        return self.asset

    async def leaderboard(self, **_kwargs: object) -> IpAssetLeaderboardRecord:
        return IpAssetLeaderboardRecord(
            period=IpAssetLeaderboardPeriod.THIRTY_DAYS,
            generated_at=datetime(2026, 8, 24, 9, 0, tzinfo=UTC),
            items=(IpAssetLeaderboardItemRecord(asset=self.asset, download_count=7),),
        )


@pytest.mark.parametrize("media_type", ["image/png", "image/jpeg", "image/webp"])
def test_upload_validation_decodes_supported_rasters(media_type: str) -> None:
    validated = validate_ip_asset_upload(
        filename="../部门素材/IP source.any",
        declared_media_type=media_type,
        body=_raster(media_type),
    )

    assert validated.media_type == media_type
    assert validated.width == 64
    assert validated.height == 48
    assert validated.orientation is IpAssetOrientation.LANDSCAPE
    assert "/" not in validated.safe_original_filename
    assert len(validated.sha256) == 64
    assert len(validated.perceptual_hash) == 16


def test_upload_validation_rejects_declared_signature_mismatch() -> None:
    with pytest.raises(IpAssetValidationError) as captured:
        validate_ip_asset_upload(
            filename="unsafe.jpg",
            declared_media_type="image/jpeg",
            body=_raster("image/png"),
        )

    assert captured.value.code == "media_type_signature_mismatch"


def test_thumbnail_is_deterministic_bounded_webp_without_upscaling() -> None:
    source = _raster(size=(1_200, 800))

    first = build_ip_asset_thumbnail(source)
    replay = build_ip_asset_thumbnail(source)
    small = build_ip_asset_thumbnail(_raster(size=(64, 48)))

    assert first.body == replay.body
    assert first.sha256 == replay.sha256
    assert first.media_type == "image/webp"
    assert first.width == 640
    assert first.height == 427
    assert (small.width, small.height) == (64, 48)
    with Image.open(io.BytesIO(first.body)) as decoded:
        assert decoded.format == "WEBP"
        assert decoded.size == (640, 427)


def test_thumbnail_preserves_transparent_pixels() -> None:
    output = io.BytesIO()
    Image.new("RGBA", (800, 800), (244, 196, 48, 0)).save(output, format="PNG")

    thumbnail = build_ip_asset_thumbnail(output.getvalue())

    with Image.open(io.BytesIO(thumbnail.body)) as decoded:
        assert decoded.size == (640, 640)
        assert "A" in decoded.getbands()
        assert decoded.getchannel("A").getextrema() == (0, 0)


@pytest.mark.parametrize("media_type", ["image/png", "image/jpeg", "image/webp"])
def test_upload_validation_rejects_trailing_polyglot_payload(media_type: str) -> None:
    with pytest.raises(IpAssetValidationError) as captured:
        validate_ip_asset_upload(
            filename="polyglot.bin",
            declared_media_type=media_type,
            body=_raster(media_type) + b"<script>not-image-content</script>",
        )

    assert captured.value.code == "invalid_raster"


def test_canonical_name_uses_controlled_taxonomy_and_omits_missing_values() -> None:
    display, naming = canonical_name_base(
        IpAssetMetadata(
            character=IpAssetCharacter.XIAO_SAI,
            asset_type=IpAssetType.MEME_STICKER,
            emotion="开心",
            scene="科学课堂",
        ),
        IpAssetOrientation.SQUARE,
    )

    assert display == "小赛-表情包-开心-科学课堂-方图"
    assert "none" not in display.casefold()
    assert naming.startswith(tuple("0123456789abcdef"))


def test_profile_token_is_canonical_and_only_its_digest_is_derived() -> None:
    raw = bytes(range(32))
    token = urlsafe_b64encode(raw).decode().rstrip("=")

    assert profile_token_digest(token) == hashlib.sha256(raw).hexdigest()
    for invalid in (token + "=", token[:-1], "A" * 42 + "+"):
        with pytest.raises(ValueError, match="profile token"):
            profile_token_digest(invalid)


def test_generation_references_preserve_order_and_reject_duplicates() -> None:
    first = "ipa_11111111111111111111"
    second = "ipa_22222222222222222222"

    assert normalize_generation_reference_refs([second, first]) == (second, first)
    with pytest.raises(ValueError, match="distinct"):
        normalize_generation_reference_refs([first, first])
    with pytest.raises(ValueError, match="one to three"):
        normalize_generation_reference_refs([])


def test_generation_request_accepts_legacy_single_reference_but_not_mixed_shapes() -> None:
    base = {
        "prompt": "小赛在科学课堂开心挥手",
        "character": "xiao_sai",
        "asset_type": "scene_illustration",
        "idempotency_key": "request-1234",
    }
    legacy = IpAssetGenerationRequest(**base, reference_asset_ref="ipa_11111111111111111111")
    assert legacy.reference_asset_ref == "ipa_11111111111111111111"

    with pytest.raises(ValidationError):
        IpAssetGenerationRequest(
            **base,
            reference_asset_ref="ipa_11111111111111111111",
            reference_asset_refs=["ipa_22222222222222222222"],
        )
    with pytest.raises(ValidationError):
        IpAssetGenerationRequest(
            **base,
            reference_asset_refs=[
                "ipa_11111111111111111111",
                "ipa_11111111111111111111",
            ],
        )


@pytest.mark.parametrize("prompt", ["图", "图" * 2_001])
def test_generation_request_accepts_any_non_blank_prompt_length(prompt: str) -> None:
    request = IpAssetGenerationRequest(
        prompt=prompt,
        character="xiao_sai",
        asset_type="scene_illustration",
        idempotency_key="request-unbounded-prompt",
        reference_asset_refs=["ipa_11111111111111111111"],
    )

    assert request.prompt == prompt


@pytest.mark.asyncio
async def test_generation_enqueue_normalizes_any_non_blank_prompt_length() -> None:
    class Repository:
        def __init__(self) -> None:
            self.prompts: list[str] = []

        async def enqueue_generation(self, **kwargs: object) -> tuple[object, bool]:
            self.prompts.append(cast(str, kwargs["prompt"]))
            return object(), True

    now = datetime(2026, 8, 24, 9, 0, tzinfo=UTC)
    profile = IpAssetProfileRecord(
        id=UUID("99999999-9999-4999-8999-999999999999"),
        profile_ref="ipp_99999999999999999999",
        display_name="同事甲",
        department="教研部",
        created_at=now,
        updated_at=now,
    )
    repository = Repository()
    for index, prompt in enumerate(("  图  ", "图" * 2_001), start=1):
        await enqueue_ip_asset_generation(
            repository=cast(IpAssetRepository, repository),
            prompt=prompt,
            metadata=IpAssetMetadata(
                character=IpAssetCharacter.XIAO_SAI,
                asset_type=IpAssetType.SCENE_ILLUSTRATION,
            ),
            ratio="1:1",
            profile=profile,
            reference_assets=(_asset(),),
            idempotency_key=f"generation-unbounded-{index}",
            provider="fake",
            model="gpt-image-2",
        )

    assert repository.prompts == ["图", "图" * 2_001]

    with pytest.raises(IpAssetUploadRejectedError):
        await enqueue_ip_asset_generation(
            repository=cast(IpAssetRepository, repository),
            prompt=" \n\t ",
            metadata=IpAssetMetadata(
                character=IpAssetCharacter.XIAO_SAI,
                asset_type=IpAssetType.SCENE_ILLUSTRATION,
            ),
            ratio="1:1",
            profile=profile,
            reference_assets=(_asset(),),
            idempotency_key="generation-blank",
            provider="fake",
            model="gpt-image-2",
        )


def test_leaderboard_window_uses_business_timezone_and_includes_thirty_dates() -> None:
    now = datetime(2026, 8, 23, 16, 30, tzinfo=UTC)

    assert leaderboard_start_date(
        period=IpAssetLeaderboardPeriod.THIRTY_DAYS,
        now=now,
        timezone="Asia/Shanghai",
    ) == date(2026, 7, 26)
    assert (
        leaderboard_start_date(
            period=IpAssetLeaderboardPeriod.ALL,
            now=now,
            timezone="Asia/Shanghai",
        )
        is None
    )


@pytest.mark.asyncio
async def test_search_outcomes_use_actual_mode_but_evaluation_does_not_record() -> None:
    calls: list[tuple[date, str, IpAssetSearchMode, IpAssetSearchEventKind]] = []

    class Repository:
        async def list_assets(self, _query: IpAssetQuery) -> IpAssetPage:
            return IpAssetPage(items=(_asset(),), next_cursor_created_at=None, next_cursor_id=None)

        async def increment_search_aggregate(
            self,
            *,
            business_date: date,
            search_version: str,
            mode: IpAssetSearchMode,
            event_kind: IpAssetSearchEventKind,
        ) -> None:
            calls.append((business_date, search_version, mode, event_kind))

    service = IpAssetService(
        repository=cast(IpAssetRepository, Repository()),
        store=cast(object, SimpleNamespace()),
        embeddings=None,
        identity=VisualEmbeddingIdentity(),
        search_version=IP_ASSET_SEARCH_V3_VERSION,
        business_timezone="Asia/Shanghai",
        now=lambda: datetime(2026, 8, 30, 16, 30, tzinfo=UTC),
    )

    evaluation_result = await service.search_text_for_evaluation(
        message="找一张小赛开心的图片",
        prior_turns=(),
        filters=IpAssetQuery(limit=8),
    )

    assert evaluation_result.mode is IpAssetSearchMode.DEGRADED_METADATA
    assert calls == []

    result = await service.search_text(
        message="找一张小赛开心的图片",
        prior_turns=(),
        filters=IpAssetQuery(limit=8),
    )

    assert result.mode is IpAssetSearchMode.DEGRADED_METADATA
    assert result.degraded_reason == "semantic_disabled"
    assert result.search_version == IP_ASSET_SEARCH_V3_VERSION
    assert calls == [
        (
            date(2026, 8, 31),
            IP_ASSET_SEARCH_V3_VERSION,
            IpAssetSearchMode.DEGRADED_METADATA,
            IpAssetSearchEventKind.SEARCH_RESULTS,
        )
    ]


@pytest.mark.asyncio
async def test_search_metrics_group_closed_anonymous_dimensions() -> None:
    class Repository:
        async def list_search_aggregates(
            self, *, start_date: date, end_date: date
        ) -> tuple[IpAssetSearchAggregateRecord, ...]:
            assert start_date == date(2026, 8, 2)
            assert end_date == date(2026, 8, 31)
            return (
                IpAssetSearchAggregateRecord(
                    business_date=end_date,
                    search_version=IP_ASSET_SEARCH_V3_VERSION,
                    mode=IpAssetSearchMode.SEMANTIC,
                    event_kind=IpAssetSearchEventKind.SEARCH_RESULTS,
                    count=4,
                ),
                IpAssetSearchAggregateRecord(
                    business_date=end_date,
                    search_version=IP_ASSET_SEARCH_V3_VERSION,
                    mode=IpAssetSearchMode.SEMANTIC,
                    event_kind=IpAssetSearchEventKind.ZERO_RESULTS,
                    count=1,
                ),
                IpAssetSearchAggregateRecord(
                    business_date=end_date,
                    search_version=IP_ASSET_SEARCH_V3_VERSION,
                    mode=IpAssetSearchMode.SEMANTIC,
                    event_kind=IpAssetSearchEventKind.PREVIEW_FROM_SEARCH,
                    count=3,
                ),
            )

    service = IpAssetService(
        repository=cast(IpAssetRepository, Repository()),
        store=cast(object, SimpleNamespace()),
        embeddings=None,
        identity=VisualEmbeddingIdentity(),
        now=lambda: datetime(2026, 8, 31, 8, 0, tzinfo=UTC),
    )

    metrics = await service.search_metrics(period=IpAssetSearchMetricPeriod.THIRTY_DAYS)

    assert metrics.start_date == date(2026, 8, 2)
    assert len(metrics.buckets) == 1
    bucket = metrics.buckets[0]
    assert bucket.searches == 5
    assert bucket.zero_result_rate == pytest.approx(0.2)
    assert bucket.preview_per_result_search == pytest.approx(0.75)


@pytest.mark.asyncio
async def test_search_action_rejects_server_owned_outcome_events() -> None:
    service = IpAssetService(
        repository=cast(IpAssetRepository, SimpleNamespace()),
        store=cast(object, SimpleNamespace()),
        embeddings=None,
        identity=VisualEmbeddingIdentity(),
    )

    with pytest.raises(ValueError, match="action event"):
        await service.record_search_action(
            event_kind=IpAssetSearchEventKind.SEARCH_RESULTS,
            search_version=IP_ASSET_SEARCH_V3_VERSION,
            mode=IpAssetSearchMode.SEMANTIC,
        )


@pytest.mark.asyncio
async def test_media_reads_require_a_ready_accessible_asset() -> None:
    class Repository:
        async def get_accessible_by_ref(self, *_args: object, **_kwargs: object) -> IpAssetRecord:
            return replace(_asset(), status=IpAssetStatus.PROCESSING)

    class Store:
        async def get_verified(self, _descriptor: object) -> bytes:
            raise AssertionError("non-ready media must not reach object storage")

    service = IpAssetService(
        repository=cast(IpAssetRepository, Repository()),
        store=cast(IpAssetStore, Store()),
        embeddings=None,
        identity=VisualEmbeddingIdentity(),
    )

    with pytest.raises(NotFoundError, match="IP asset"):
        await service.original(_asset().asset_ref)


def test_http_upload_list_preview_download_and_zip_are_safe() -> None:
    service = _FakeService()
    test_app = FastAPI()
    test_app.include_router(routes.router, prefix="/api/v1")
    test_app.state.settings = SimpleNamespace(
        ip_asset_hub_enabled=True,
        ip_asset_generation_enabled=False,
        visual_semantic_enabled=False,
        business_timezone="Asia/Shanghai",
    )
    test_app.state.ip_asset_service = service
    test_app.state.image_generator = None
    test_app.state.ip_asset_upload_semaphore = asyncio.Semaphore(1)
    service.search_semaphore = test_app.state.ip_asset_upload_semaphore
    client = TestClient(test_app)

    upload = client.post(
        "/api/v1/ip-assets",
        files={"file": ("xiaosai.png", service.body, "image/png")},
        data={"character": "xiao_sai", "asset_type": "meme_sticker", "tags": "开心,科学"},
    )
    assert upload.status_code == 201
    assert upload.json()["asset"]["canonical_name"].endswith("v001")
    assert upload.json()["near_duplicate_distance"] == 4

    listed = client.get("/api/v1/ip-assets")
    assert listed.status_code == 200
    payload = listed.json()
    assert payload["items"][0]["asset_ref"] == service.asset.asset_ref
    assert payload["items"][0]["thumbnail_url"].endswith("/thumbnail?v=1")
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "private-bucket" not in serialized
    assert "private-object-key" not in serialized
    assert "blob_sha256" not in serialized

    preview = client.get(f"/api/v1/ip-assets/{service.asset.asset_ref}/preview")
    assert preview.status_code == 200
    assert preview.content == service.body
    assert preview.headers["content-disposition"] == "inline"
    assert preview.headers["cache-control"] == "private, no-store"

    thumbnail = client.get(f"/api/v1/ip-assets/{service.asset.asset_ref}/thumbnail?v=1")
    assert thumbnail.status_code == 200
    assert thumbnail.headers["content-type"] == "image/webp"
    assert thumbnail.headers["content-disposition"] == "inline"
    assert thumbnail.headers["cache-control"] == "private, max-age=604800, immutable"
    assert thumbnail.headers["etag"]
    assert thumbnail.headers["vary"] == "X-IP-Profile-Token"
    thumbnail_operation = client.app.openapi()["paths"]["/api/v1/ip-assets/{asset_ref}/thumbnail"][
        "get"
    ]
    assert set(thumbnail_operation["responses"]["200"]["content"]) == {"image/webp"}

    download = client.get(f"/api/v1/ip-assets/{service.asset.asset_ref}/download")
    assert download.status_code == 200
    assert download.content == service.body
    assert "attachment" in download.headers["content-disposition"]

    package = client.post(
        "/api/v1/ip-assets/downloads", json={"asset_refs": [service.asset.asset_ref]}
    )
    assert package.status_code == 200
    with zipfile.ZipFile(io.BytesIO(package.content)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["assets"][0]["asset_ref"] == service.asset.asset_ref
        assert manifest["assets"][0]["sha256"] == service.asset.blob_sha256

    similar = client.post(
        "/api/v1/ip-assets/search/image",
        files={"file": ("query.png", service.body, "image/png")},
    )
    assert similar.status_code == 200
    assert similar.json()["degraded_reason"] == "semantic_disabled"


def test_http_profile_personal_favorite_and_anonymous_ranking_are_safely_projected() -> None:
    service = _ProfileFakeService()
    test_app = FastAPI()
    test_app.include_router(routes.router, prefix="/api/v1")
    test_app.state.settings = SimpleNamespace(
        ip_asset_hub_enabled=True,
        ip_asset_generation_enabled=False,
        visual_semantic_enabled=False,
        business_timezone="Asia/Shanghai",
    )
    test_app.state.ip_asset_service = service
    test_app.state.image_generator = None
    test_app.state.ip_asset_upload_semaphore = asyncio.Semaphore(1)
    token = "A" * 43
    headers = {"X-IP-Profile-Token": token}
    client = TestClient(test_app)

    created = client.post(
        "/api/v1/ip-assets/profiles",
        headers=headers,
        json={"display_name": "内容同事", "department": "品牌部"},
    )
    assert created.status_code == 201
    assert created.json()["identity_boundary"] == "browser_local_unverified"
    assert token not in created.text

    listed = client.get("/api/v1/ip-assets", headers=headers)
    assert listed.status_code == 200
    assert listed.json()["items"][0]["favorite"] is True
    searched = client.post(
        "/api/v1/ip-assets/search/text",
        headers=headers,
        json={"message": "开心的小赛"},
    )
    assert searched.status_code == 200
    assert searched.json()["items"][0]["asset"]["favorite"] is True
    personal = client.get("/api/v1/ip-assets/profiles/me/assets", headers=headers)
    assert personal.status_code == 200
    assert personal.json()["items"][0]["membership_sources"] == ["uploaded"]

    favorited = client.put(f"/api/v1/ip-assets/{service.asset.asset_ref}/favorite", headers=headers)
    assert favorited.status_code == 200
    assert service.favorite_calls == [(service.asset.asset_ref, True)]

    ranking = client.get("/api/v1/ip-assets/leaderboard?period=30d")
    assert ranking.status_code == 200
    assert ranking.json()["items"][0]["download_count"] == 7
    assert "profile" not in ranking.text.casefold()


def test_http_search_action_and_internal_metrics_are_strict_anonymous_aggregates() -> None:
    class Service(_FakeService):
        def __init__(self) -> None:
            super().__init__()
            self.action_calls: list[tuple[IpAssetSearchEventKind, str, IpAssetSearchMode]] = []

        async def record_search_action(
            self,
            *,
            event_kind: IpAssetSearchEventKind,
            search_version: str,
            mode: IpAssetSearchMode,
        ) -> None:
            self.action_calls.append((event_kind, search_version, mode))

        async def search_metrics(
            self, *, period: IpAssetSearchMetricPeriod
        ) -> IpAssetSearchMetrics:
            return IpAssetSearchMetrics(
                period=period,
                start_date=date(2026, 8, 2),
                end_date=date(2026, 8, 31),
                buckets=(
                    IpAssetSearchMetricBucket(
                        business_date=date(2026, 8, 31),
                        search_version=IP_ASSET_SEARCH_V3_VERSION,
                        mode=IpAssetSearchMode.SEMANTIC,
                        search_results=4,
                        zero_results=1,
                        preview_from_search=3,
                        favorite_from_search=2,
                        download_from_search=1,
                    ),
                ),
            )

    service = Service()
    test_app = FastAPI()
    test_app.include_router(routes.router, prefix="/api/v1")
    test_app.state.settings = SimpleNamespace(ip_asset_hub_enabled=True)
    test_app.state.ip_asset_service = service
    client = TestClient(test_app)

    accepted = client.post(
        "/api/v1/ip-assets/search/events",
        json={
            "event_kind": "preview_from_search",
            "search_version": IP_ASSET_SEARCH_V3_VERSION,
            "mode": "semantic",
        },
    )
    server_owned = client.post(
        "/api/v1/ip-assets/search/events",
        json={
            "event_kind": "search_results",
            "search_version": IP_ASSET_SEARCH_V3_VERSION,
            "mode": "semantic",
        },
    )
    extra_identity = client.post(
        "/api/v1/ip-assets/search/events",
        json={
            "event_kind": "download_from_search",
            "search_version": IP_ASSET_SEARCH_V3_VERSION,
            "mode": "semantic",
            "asset_ref": _asset().asset_ref,
        },
    )
    unknown_version = client.post(
        "/api/v1/ip-assets/search/events",
        json={
            "event_kind": "favorite_from_search",
            "search_version": "ip-asset-experiment",
            "mode": "semantic",
        },
    )
    metrics = client.get("/api/v1/ip-assets/search/metrics?period=30d")
    extra_metrics = client.get(
        "/api/v1/ip-assets/search/metrics?period=30d&profile_ref=ipp_forbidden"
    )

    assert accepted.status_code == 204
    assert service.action_calls == [
        (
            IpAssetSearchEventKind.PREVIEW_FROM_SEARCH,
            IP_ASSET_SEARCH_V3_VERSION,
            IpAssetSearchMode.SEMANTIC,
        )
    ]
    assert server_owned.status_code == 422
    assert extra_identity.status_code == 422
    assert unknown_version.status_code == 422
    assert metrics.status_code == 200
    assert extra_metrics.status_code == 422
    payload = metrics.json()
    assert payload["interpretation"] == "anonymous_aggregate_action_ratios"
    assert payload["buckets"][0]["searches"] == 5
    assert payload["buckets"][0]["zero_result_rate"] == pytest.approx(0.2)
    serialized = metrics.text.casefold()
    for prohibited in (
        "query",
        "asset_ref",
        "profile",
        "session",
        "user_id",
        "ip_address",
        "user_agent",
        "referrer",
        "cookie",
    ):
        assert prohibited not in serialized


@pytest.mark.asyncio
async def test_disabled_capabilities_are_explicit_and_provider_free() -> None:
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                settings=SimpleNamespace(
                    ip_asset_hub_enabled=False,
                    ip_asset_generation_enabled=False,
                    visual_semantic_enabled=False,
                ),
                ip_asset_service=None,
                image_generator=None,
            )
        )
    )

    result = await routes.capabilities(cast(Request, request))

    assert result.enabled is False
    assert result.authentication == "none"
    assert result.generation_available is False


class _TextEmbedding:
    async def embed_visual(self, request: VisualEmbeddingRequest) -> VisualEmbeddingResult:
        vector = (1.0,) + (0.0,) * (request.identity.dimensions - 1)
        return VisualEmbeddingResult(
            identity=request.identity,
            input_sha256=request.input_sha256,
            request_fingerprint=request.request_fingerprint,
            vector=vector,
            input_tokens=1,
        )


@pytest.mark.asyncio
async def test_text_search_blends_unindexed_metadata_ahead_of_weak_semantic_hit() -> None:
    metadata_asset = _asset()
    semantic_asset = replace(
        _asset(),
        id=UUID("22222222-2222-4222-8222-222222222222"),
        asset_ref="ipa_22222222222222222222",
        canonical_name="小赛-场景插画-AI创作-方图-v001",
        asset_type=IpAssetType.SCENE_ILLUSTRATION,
        emotion="",
        action="",
        scene="",
        intended_use="",
        tags=("ai-generated",),
        semantic_status=IpAssetSemanticStatus.READY,
        created_at=datetime(2026, 8, 24, 10, 0, tzinfo=UTC),
    )
    unindexed_filtered_asset = replace(
        _asset(),
        id=UUID("33333333-3333-4333-8333-333333333333"),
        asset_ref="ipa_33333333333333333333",
        canonical_name="小赛-头像-通用-方图-v001",
        asset_type=IpAssetType.PORTRAIT_AVATAR,
        emotion="",
        action="",
        scene="",
        intended_use="",
        tags=(),
        created_at=datetime(2026, 8, 24, 8, 0, tzinfo=UTC),
    )

    class Repository:
        async def list_assets(self, query: IpAssetQuery) -> IpAssetPage:
            assert query.character is IpAssetCharacter.XIAO_SAI
            assert query.query == ""
            return IpAssetPage(
                items=(semantic_asset, metadata_asset, unindexed_filtered_asset),
                next_cursor_created_at=None,
                next_cursor_id=None,
            )

        async def search_vectors(self, **_kwargs: object) -> tuple[IpAssetVectorHit, ...]:
            return (IpAssetVectorHit(record=semantic_asset, similarity=0.08),)

    service = IpAssetService(
        repository=cast(IpAssetRepository, Repository()),
        store=cast(object, SimpleNamespace()),
        embeddings=_TextEmbedding(),
        identity=VisualEmbeddingIdentity(),
    )

    result = await service.search_text(
        message="找一张小赛开心庆祝、适合社群推送的图片",
        prior_turns=(),
        filters=IpAssetQuery(query="找一张小赛开心庆祝、适合社群推送的图片", limit=20),
    )

    assert result.mode is IpAssetSearchMode.SEMANTIC
    assert [item.asset.asset_ref for item in result.items] == [
        metadata_asset.asset_ref,
        semantic_asset.asset_ref,
        unindexed_filtered_asset.asset_ref,
    ]
    assert result.items[0].similarity is None
    assert "文字匹配: 开心、庆祝" in result.items[0].explanation


@pytest.mark.asyncio
async def test_text_search_current_turn_and_explicit_filters_override_stale_terms() -> None:
    captured: list[IpAssetQuery] = []
    sai_asset = replace(
        _asset(),
        character=IpAssetCharacter.SAI_XIANSHENG,
        canonical_name="赛先生-全身动作-专注-通用-方图-v001",
    )

    class Repository:
        async def list_assets(self, query: IpAssetQuery) -> IpAssetPage:
            captured.append(query)
            return IpAssetPage(items=(sai_asset,), next_cursor_created_at=None, next_cursor_id=None)

        async def search_vectors(
            self, *, query: IpAssetQuery, **_kwargs: object
        ) -> tuple[IpAssetVectorHit, ...]:
            captured.append(query)
            return (IpAssetVectorHit(record=sai_asset, similarity=0.9),)

    service = IpAssetService(
        repository=cast(IpAssetRepository, Repository()),
        store=cast(object, SimpleNamespace()),
        embeddings=_TextEmbedding(),
        identity=VisualEmbeddingIdentity(),
    )

    await service.search_text(
        message="现在改找赛先生",
        prior_turns=("先找小赛表情包",),
        filters=IpAssetQuery(query="现在改找赛先生", limit=20),
    )
    await service.search_text(
        message="找小赛图片",
        prior_turns=(),
        filters=IpAssetQuery(
            query="找小赛图片", character=IpAssetCharacter.SAI_XIANSHENG, limit=20
        ),
    )

    assert all(query.character is IpAssetCharacter.SAI_XIANSHENG for query in captured)
    assert all(query.asset_type is None for query in captured)


def test_generic_transparent_background_term_stays_lexical_not_asset_type() -> None:
    query = _extract_filters("找一张小赛开心庆祝的透明底图片", IpAssetQuery(limit=20))

    assert query.character is IpAssetCharacter.XIAO_SAI
    assert query.asset_type is None
    assert query.query == "找一张小赛开心庆祝的透明底图片"


@pytest.mark.parametrize(
    ("message", "expected_match"),
    (
        ("按完整名称找 小赛-表情包-开心-社群-横图-v001", "资产名称关键词"),
        ("找 source.png", "原文件名关键词"),
        ("找市场部素材", "部门: 市场部"),
        ("找同事甲上传的素材", "贡献者: 同事甲"),
        ("找一张 3D 图片", "3D"),
    ),
)
def test_metadata_ranking_covers_all_conventional_keyword_fields_without_filename_leak(
    message: str, expected_match: str
) -> None:
    hit = _metadata_search_hit(_asset(), message)

    assert hit.score > 0
    assert expected_match in hit.matches
    if "source.png" in message:
        assert "source.png" not in hit.matches


def test_search_explanation_is_bounded_to_wire_contract() -> None:
    explanation = _explanation(
        _asset(),
        similarity=1.0,
        query=IpAssetQuery(
            character=IpAssetCharacter.XIAO_SAI,
            asset_type=IpAssetType.MEME_STICKER,
        ),
        matches=("甲" * 60, "乙" * 60, "丙" * 60, "丁" * 60),
    )

    assert len(explanation) <= 240
    assert explanation.endswith("…")


def test_search_response_forwards_versioned_service_contract() -> None:
    result = IpAssetSearchResult(
        mode=IpAssetSearchMode.DEGRADED_METADATA,
        degraded_reason="semantic_disabled",
        search_version=IP_ASSET_SEARCH_VERSION,
        items=(),
    )

    assert routes._search_response(result).search_version == result.search_version


@pytest.mark.asyncio
async def test_invalid_similarity_image_is_typed_input_failure_before_provider() -> None:
    class Embeddings:
        async def embed_visual(self, _request: object) -> object:
            raise AssertionError("invalid query bytes must not call the provider")

    service = IpAssetService(
        repository=cast(object, SimpleNamespace()),
        store=cast(object, SimpleNamespace()),
        embeddings=cast(object, Embeddings()),
        identity=VisualEmbeddingIdentity(),
    )

    with pytest.raises(IpAssetUploadRejectedError) as captured:
        await service.search_image(
            body=b"not-an-image",
            media_type="image/png",
            filters=SimpleNamespace(),
        )

    assert captured.value.code == "invalid_raster_signature"


@pytest.mark.asyncio
async def test_disabled_similarity_still_validates_transient_query_bytes() -> None:
    service = IpAssetService(
        repository=cast(object, SimpleNamespace()),
        store=cast(object, SimpleNamespace()),
        embeddings=None,
        identity=VisualEmbeddingIdentity(),
    )

    with pytest.raises(IpAssetUploadRejectedError) as captured:
        await service.search_image(
            body=b"not-an-image",
            media_type="image/png",
            filters=SimpleNamespace(),
        )

    assert captured.value.code == "invalid_raster_signature"


@pytest.mark.asyncio
async def test_worker_heartbeat_cancels_work_after_lease_loss() -> None:
    cancelled = asyncio.Event()

    async def operation() -> None:
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.set()

    async def renew() -> bool:
        return False

    with pytest.raises(_IpAssetLeaseLost):
        await _run_with_lease_heartbeat(operation(), renew=renew, heartbeat_seconds=0)

    assert cancelled.is_set()


@pytest.mark.asyncio
async def test_worker_heartbeat_cleans_up_children_when_parent_is_cancelled() -> None:
    operation_started = asyncio.Event()
    operation_cancelled = asyncio.Event()

    async def operation() -> None:
        operation_started.set()
        try:
            await asyncio.Event().wait()
        finally:
            operation_cancelled.set()

    async def renew() -> bool:
        return True

    worker = asyncio.create_task(
        _run_with_lease_heartbeat(operation(), renew=renew, heartbeat_seconds=60)
    )
    await operation_started.wait()
    worker.cancel()

    with pytest.raises(asyncio.CancelledError):
        await worker
    assert operation_cancelled.is_set()


@pytest.mark.asyncio
async def test_generation_fingerprint_includes_persisted_descriptive_labels() -> None:
    class Repository:
        def __init__(self) -> None:
            self.fingerprints: list[str] = []

        async def enqueue_generation(self, **kwargs: object) -> tuple[object, bool]:
            self.fingerprints.append(cast(str, kwargs["request_fingerprint"]))
            return object(), True

    repository = Repository()
    profile = IpAssetProfileRecord(
        id=UUID("99999999-9999-4999-8999-999999999999"),
        profile_ref="ipp_99999999999999999999",
        display_name="同事甲",
        department="教研部",
        created_at=datetime(2026, 8, 24, 9, 0, tzinfo=UTC),
        updated_at=datetime(2026, 8, 24, 9, 0, tzinfo=UTC),
    )
    reference = _asset()
    await enqueue_ip_asset_generation(
        repository=cast(IpAssetRepository, repository),
        prompt="生成小赛在科学课堂讲解知识的方形插画",
        metadata=IpAssetMetadata(
            character=IpAssetCharacter.XIAO_SAI,
            asset_type=IpAssetType.SCENE_ILLUSTRATION,
            department="教研部",
            contributor="同事甲",
        ),
        ratio="1:1",
        profile=profile,
        reference_assets=(reference,),
        idempotency_key="generation-labels-one",
        provider="fake",
        model="gpt-image-2",
    )
    await enqueue_ip_asset_generation(
        repository=cast(IpAssetRepository, repository),
        prompt="生成小赛在科学课堂讲解知识的方形插画",
        metadata=IpAssetMetadata(
            character=IpAssetCharacter.XIAO_SAI,
            asset_type=IpAssetType.SCENE_ILLUSTRATION,
            department="市场部",
            contributor="同事乙",
        ),
        ratio="1:1",
        profile=profile,
        reference_assets=(reference,),
        idempotency_key="generation-labels-two",
        provider="fake",
        model="gpt-image-2",
    )
    alternate_identity = replace(
        reference,
        id=UUID("22222222-2222-4222-8222-222222222222"),
        asset_ref="ipa_22222222222222222222",
    )
    await enqueue_ip_asset_generation(
        repository=cast(IpAssetRepository, repository),
        prompt="生成小赛在科学课堂讲解知识的方形插画",
        metadata=IpAssetMetadata(
            character=IpAssetCharacter.XIAO_SAI,
            asset_type=IpAssetType.SCENE_ILLUSTRATION,
            department="教研部",
            contributor="同事甲",
        ),
        ratio="1:1",
        profile=profile,
        reference_assets=(alternate_identity,),
        idempotency_key="generation-labels-three",
        provider="fake",
        model="gpt-image-2",
    )

    assert len(set(repository.fingerprints)) == 3
    with pytest.raises(IpAssetUploadRejectedError):
        await enqueue_ip_asset_generation(
            repository=cast(IpAssetRepository, repository),
            prompt="生成小赛在科学课堂讲解知识的方形插画",
            metadata=IpAssetMetadata(
                character=IpAssetCharacter.XIAO_SAI,
                asset_type=IpAssetType.SCENE_ILLUSTRATION,
            ),
            ratio="1:1",
            profile=profile,
            reference_assets=(replace(reference, shared_at=None),),
            idempotency_key="generation-private-reference",
            provider="fake",
            model="gpt-image-2",
        )


@pytest.mark.asyncio
async def test_zip_download_stops_reading_when_aggregate_budget_is_exceeded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.application.services import ip_assets as service_module

    class Service(IpAssetService):
        def __init__(self) -> None:
            self.calls: list[str] = []

        async def original(self, asset_ref: str, **_kwargs: object) -> tuple[IpAssetRecord, bytes]:
            self.calls.append(asset_ref)
            return _asset(), b"123456"

    monkeypatch.setattr(service_module, "IP_ASSET_MAX_ZIP_BYTES", 10)
    service = Service()

    with pytest.raises(IpAssetUploadRejectedError, match="validation"):
        await service.download_zip(
            (
                "ipa_11111111111111111111",
                "ipa_22222222222222222222",
                "ipa_33333333333333333333",
            )
        )

    assert service.calls == [
        "ipa_11111111111111111111",
        "ipa_22222222222222222222",
    ]


def test_ip_asset_settings_require_exact_browser_origins_and_short_heartbeat() -> None:
    settings = Settings(
        _env_file=None,
        app_browser_origins="http://127.0.0.1:5173,https://assets.intranet.example",
    )
    assert settings.browser_origins == (
        "http://127.0.0.1:5173",
        "https://assets.intranet.example",
    )
    with pytest.raises(ValidationError, match="exact HTTP"):
        Settings(_env_file=None, app_browser_origins="*")
    with pytest.raises(ValidationError, match="heartbeat must be shorter"):
        Settings(_env_file=None, ip_asset_lease_seconds=60, ip_asset_heartbeat_seconds=60)
    assert (
        Settings(
            _env_file=None, ip_asset_search_version="ip-asset-hybrid-v2"
        ).ip_asset_search_version
        == "ip-asset-hybrid-v2"
    )
    with pytest.raises(ValidationError, match="ip-asset-hybrid-v3-rrf"):
        Settings(_env_file=None, ip_asset_search_version="ip-asset-experiment")


def test_main_api_installs_an_exact_noncredentialed_browser_origin_allowlist() -> None:
    from app import api_main
    from fastapi.middleware.cors import CORSMiddleware

    middleware = next(item for item in api_main.app.user_middleware if item.cls is CORSMiddleware)
    assert middleware.kwargs["allow_origins"] == list(api_main.settings.browser_origins)
    assert middleware.kwargs["allow_origins"] != ["*"]
    assert middleware.kwargs["allow_credentials"] is False
    assert middleware.kwargs["allow_methods"] == [
        "GET",
        "POST",
        "PUT",
        "DELETE",
        "OPTIONS",
    ]
    assert middleware.kwargs["allow_headers"] == [
        "Content-Type",
        "X-Request-ID",
        "X-IP-Profile-Token",
    ]

    allowed_origin = api_main.settings.browser_origins[0]
    with TestClient(api_main.app) as client:
        allowed = client.options(
            "/api/v1/ip-assets/capabilities",
            headers={
                "Origin": allowed_origin,
                "Access-Control-Request-Method": "GET",
            },
        )
        denied = client.options(
            "/api/v1/ip-assets/capabilities",
            headers={
                "Origin": "https://public-attacker.invalid",
                "Access-Control-Request-Method": "GET",
            },
        )
        profile_write = client.options(
            "/api/v1/ip-assets/ipa_11111111111111111111/favorite",
            headers={
                "Origin": allowed_origin,
                "Access-Control-Request-Method": "PUT",
                "Access-Control-Request-Headers": "X-IP-Profile-Token",
            },
        )

    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == allowed_origin
    assert "access-control-allow-origin" not in denied.headers
    assert profile_write.status_code == 200
    assert "x-ip-profile-token" in profile_write.headers["access-control-allow-headers"].casefold()


@pytest.mark.asyncio
async def test_existing_minio_object_bytes_are_verified_not_just_metadata() -> None:
    original = _raster()
    upload = validate_ip_asset_upload(
        filename="asset.png", declared_media_type="image/png", body=original
    )

    class Response:
        def stream(self, _size: int):
            yield b"x" * len(original)

        def close(self) -> None:
            pass

        def release_conn(self) -> None:
            pass

    class Client:
        def stat_object(self, _bucket: str, _key: str) -> SimpleNamespace:
            return SimpleNamespace(
                size=len(original),
                metadata={"x-amz-meta-sha256": upload.sha256},
            )

        def get_object(self, _bucket: str, _key: str) -> Response:
            return Response()

    store = object.__new__(MinioIpAssetStore)
    store._bucket = "private-bucket"
    store._client = Client()

    with pytest.raises(ConflictError, match="checksum"):
        await store.put_immutable(upload)


@pytest.mark.asyncio
async def test_seed_import_dry_run_is_aggregate_only_and_does_not_read_sources(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from app import ip_asset_import_main as importer

    reads: list[object] = []
    monkeypatch.setattr(
        importer,
        "get_settings",
        lambda: SimpleNamespace(image_asset_manifest="approved-manifest.json"),
    )
    monkeypatch.setattr(
        importer,
        "load_visual_catalog",
        lambda _path: SimpleNamespace(
            catalog=SimpleNamespace(
                assets=(
                    SimpleNamespace(approved=True),
                    SimpleNamespace(approved=False),
                    SimpleNamespace(approved=True),
                )
            )
        ),
    )
    monkeypatch.setattr(
        importer,
        "read_visual_asset_bytes",
        lambda *_args: reads.append(object()),
    )

    result = await importer._run(dry_run=True, max_assets=10)
    payload = json.loads(capsys.readouterr().out)

    assert result == 0
    assert payload == {
        "selected_count": 2,
        "created_count": 0,
        "existing_count": 0,
        "failed_count": 0,
        "dry_run": True,
    }
    assert reads == []


@pytest.mark.asyncio
async def test_seed_import_rejects_unbounded_limit_before_loading_catalog() -> None:
    from app.ip_asset_import_main import _run

    with pytest.raises(SystemExit, match="max-assets"):
        await _run(dry_run=True, max_assets=0)
