from __future__ import annotations

import asyncio
import hashlib
import io
import json
import zipfile
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import UTC, date, datetime
from typing import TypeVar
from uuid import UUID

from app.application.ports.image_generation import (
    ImageGenerationRequest,
    ImageGenerator,
    ImageReference,
)
from app.application.ports.ip_assets import (
    IpAssetDerivativeRecord,
    IpAssetEmbeddingClaim,
    IpAssetGenerationClaim,
    IpAssetGenerationRecord,
    IpAssetLeaderboardRecord,
    IpAssetObjectDescriptor,
    IpAssetPage,
    IpAssetPersonalPage,
    IpAssetProfileRecord,
    IpAssetQuery,
    IpAssetRecord,
    IpAssetRepository,
    IpAssetStore,
    IpAssetVectorHit,
)
from app.application.ports.visual_retrieval import VisualEmbeddingModel
from app.core.errors import (
    ConflictError,
    ImageOutputValidationError,
    IpAssetUploadRejectedError,
    NotFoundError,
    ProviderError,
    ProviderIdentityMismatchError,
)
from app.domain.image_generation import validate_image_prompt
from app.domain.ip_assets import (
    IP_ASSET_MAX_ZIP_BYTES,
    IP_ASSET_MAX_ZIP_ITEMS,
    IP_ASSET_SEARCH_VERSION,
    IP_ASSET_THUMBNAIL_POLICY_VERSION,
    IpAssetCharacter,
    IpAssetLeaderboardPeriod,
    IpAssetMembershipSource,
    IpAssetMetadata,
    IpAssetOrientation,
    IpAssetSearchMode,
    IpAssetSearchVersion,
    IpAssetSource,
    IpAssetStatus,
    IpAssetType,
    IpAssetValidationError,
    ValidatedIpAssetUpload,
    build_ip_asset_thumbnail,
    canonical_download_filename,
    leaderboard_start_date,
    normalize_generation_reference_refs,
    normalize_optional_text,
    normalize_profile_metadata,
    profile_token_digest,
    validate_ip_asset_upload,
)
from app.domain.visual_retrieval import (
    VisualEmbeddingError,
    VisualEmbeddingIdentity,
    VisualEmbeddingRequest,
    VisualEmbeddingResult,
    normalize_visual_embedding_image,
)


@dataclass(frozen=True, slots=True)
class IpAssetUploadResult:
    asset: IpAssetRecord
    duplicate: bool
    near_duplicate_ref: str | None
    near_duplicate_distance: int | None


@dataclass(frozen=True, slots=True)
class IpAssetSearchHit:
    asset: IpAssetRecord
    similarity: float | None
    explanation: str


@dataclass(frozen=True, slots=True)
class IpAssetSearchResult:
    mode: IpAssetSearchMode
    degraded_reason: str | None
    search_version: IpAssetSearchVersion
    items: tuple[IpAssetSearchHit, ...]


@dataclass(frozen=True, slots=True)
class IpAssetPreparedDownload:
    asset: IpAssetRecord
    body: bytes


@dataclass(frozen=True, slots=True)
class IpAssetPreparedZip:
    body: bytes
    assets: tuple[IpAssetRecord, ...]


@dataclass(frozen=True, slots=True)
class IpAssetPreparedThumbnail:
    asset: IpAssetRecord
    derivative: IpAssetDerivativeRecord
    body: bytes


@dataclass(frozen=True, slots=True)
class _MetadataSearchHit:
    asset: IpAssetRecord
    score: float
    matches: tuple[str, ...]


_IP_ASSET_SEARCH_CANDIDATE_LIMIT = 500
_SEMANTIC_RANK_WEIGHT = 0.35
_METADATA_RANK_WEIGHT = 0.65


class IpAssetService:
    def __init__(
        self,
        *,
        repository: IpAssetRepository,
        store: IpAssetStore,
        embeddings: VisualEmbeddingModel | None,
        identity: VisualEmbeddingIdentity,
    ) -> None:
        self._repository = repository
        self._store = store
        self._embeddings = embeddings
        self._identity = identity
        self._thumbnail_semaphore = asyncio.Semaphore(2)

    async def upload(
        self,
        *,
        filename: str,
        media_type: str | None,
        body: bytes,
        metadata: IpAssetMetadata,
        source_kind: IpAssetSource = IpAssetSource.UPLOADED,
        profile: IpAssetProfileRecord | None = None,
    ) -> IpAssetUploadResult:
        try:
            upload = await asyncio.to_thread(
                validate_ip_asset_upload,
                filename=filename,
                declared_media_type=media_type,
                body=body,
            )
        except IpAssetValidationError as error:
            raise IpAssetUploadRejectedError(error.code) from error
        except ValueError as error:
            raise IpAssetUploadRejectedError("invalid_ip_asset_metadata") from error
        existing = await self._repository.get_by_sha256(upload.sha256)
        if existing is not None:
            existing, _created = await self._repository.create_asset(
                upload=upload,
                metadata=metadata,
                descriptor=IpAssetObjectDescriptor(
                    bucket=existing.bucket,
                    object_key=existing.object_key,
                    media_type=existing.media_type,
                    byte_size=existing.byte_size,
                    sha256=existing.blob_sha256,
                ),
                source_kind=source_kind,
                semantic_enabled=self._embeddings is not None,
                shared=True,
                membership_profile_id=profile.id if profile is not None else None,
                membership_source=(
                    IpAssetMembershipSource.UPLOADED if profile is not None else None
                ),
            )
            return IpAssetUploadResult(
                asset=existing,
                duplicate=True,
                near_duplicate_ref=None,
                near_duplicate_distance=None,
            )
        descriptor = await self._store.put_immutable(upload)
        asset, created = await self._repository.create_asset(
            upload=upload,
            metadata=metadata,
            descriptor=descriptor,
            source_kind=source_kind,
            semantic_enabled=self._embeddings is not None,
            shared=True,
            membership_profile_id=profile.id if profile is not None else None,
            membership_source=(IpAssetMembershipSource.UPLOADED if profile is not None else None),
        )
        near = (
            await self._repository.find_near_duplicate(
                perceptual_hash=upload.perceptual_hash, exclude_id=asset.id
            )
            if created
            else None
        )
        return IpAssetUploadResult(
            asset=asset,
            duplicate=not created,
            near_duplicate_ref=near[0] if near is not None else None,
            near_duplicate_distance=near[1] if near is not None else None,
        )

    async def list(self, query: IpAssetQuery) -> IpAssetPage:
        return await self._repository.list_assets(query)

    async def bootstrap_profile(
        self, *, token: str, display_name: str, department: str
    ) -> tuple[IpAssetProfileRecord, bool]:
        try:
            digest = profile_token_digest(token)
            name, group = normalize_profile_metadata(display_name, department)
        except ValueError as error:
            raise IpAssetUploadRejectedError("invalid_ip_asset_metadata") from error
        return await self._repository.bootstrap_profile(
            token_digest=digest, display_name=name, department=group
        )

    async def profile_for_token(self, token: str) -> IpAssetProfileRecord | None:
        try:
            digest = profile_token_digest(token)
        except ValueError:
            return None
        return await self._repository.get_profile_by_token_digest(digest)

    async def personal_assets(
        self,
        *,
        profile: IpAssetProfileRecord,
        source: str,
        cursor_created_at: datetime | None,
        cursor_id: UUID | None,
        limit: int,
    ) -> IpAssetPersonalPage:
        if source not in {"all", "generated", "uploaded", "favorite"}:
            raise IpAssetUploadRejectedError("invalid_ip_asset_metadata")
        return await self._repository.list_personal_assets(
            profile_id=profile.id,
            source=source,
            cursor_created_at=cursor_created_at,
            cursor_id=cursor_id,
            limit=limit,
        )

    async def favorite(
        self, *, profile: IpAssetProfileRecord, asset_ref: str, favorite: bool
    ) -> None:
        if not await self._repository.favorite_asset(
            profile_id=profile.id, asset_ref=asset_ref, favorite=favorite
        ):
            raise NotFoundError("IP asset")

    async def favorite_asset_ids(
        self, *, profile: IpAssetProfileRecord, assets: tuple[IpAssetRecord, ...]
    ) -> frozenset[UUID]:
        return await self._repository.favorite_asset_ids(
            profile_id=profile.id, asset_ids=tuple(asset.id for asset in assets)
        )

    async def share(self, *, profile: IpAssetProfileRecord, asset_ref: str) -> IpAssetRecord:
        return await self._repository.share_generated_asset(
            profile_id=profile.id, asset_ref=asset_ref
        )

    async def leaderboard(
        self, *, period: IpAssetLeaderboardPeriod, timezone: str, limit: int
    ) -> IpAssetLeaderboardRecord:
        start = leaderboard_start_date(period=period, now=datetime.now(UTC), timezone=timezone)
        return await self._repository.leaderboard(period=period, start_date=start, limit=limit)

    async def get(
        self, asset_ref: str, *, profile: IpAssetProfileRecord | None = None
    ) -> IpAssetRecord:
        asset = await self._repository.get_accessible_by_ref(
            asset_ref, profile_id=profile.id if profile is not None else None
        )
        if asset is None:
            raise NotFoundError("IP asset")
        return asset

    async def original(
        self, asset_ref: str, *, profile: IpAssetProfileRecord | None = None
    ) -> tuple[IpAssetRecord, bytes]:
        asset = await self.get(asset_ref, profile=profile)
        if asset.status is not IpAssetStatus.READY:
            raise NotFoundError("IP asset")
        descriptor = IpAssetObjectDescriptor(
            bucket=asset.bucket,
            object_key=asset.object_key,
            media_type=asset.media_type,
            byte_size=asset.byte_size,
            sha256=asset.blob_sha256,
        )
        return asset, await self._store.get_verified(descriptor)

    async def thumbnail(
        self, asset_ref: str, *, profile: IpAssetProfileRecord | None = None
    ) -> IpAssetPreparedThumbnail:
        asset = await self.get(asset_ref, profile=profile)
        if asset.status is not IpAssetStatus.READY:
            raise NotFoundError("IP asset")
        async with self._thumbnail_semaphore:
            derivative = await self._repository.get_derivative(
                asset_id=asset.id,
                policy_version=IP_ASSET_THUMBNAIL_POLICY_VERSION,
                kind="thumbnail",
            )
            if derivative is None:
                original_descriptor = IpAssetObjectDescriptor(
                    bucket=asset.bucket,
                    object_key=asset.object_key,
                    media_type=asset.media_type,
                    byte_size=asset.byte_size,
                    sha256=asset.blob_sha256,
                )
                original = await self._store.get_verified(original_descriptor)
                try:
                    thumbnail = await asyncio.to_thread(build_ip_asset_thumbnail, original)
                except IpAssetValidationError as error:
                    raise ConflictError("IP asset thumbnail could not be derived") from error
                descriptor = await self._store.put_thumbnail(
                    thumbnail,
                    policy_version=IP_ASSET_THUMBNAIL_POLICY_VERSION,
                )
                derivative = await self._repository.create_derivative(
                    asset_id=asset.id,
                    policy_version=IP_ASSET_THUMBNAIL_POLICY_VERSION,
                    kind="thumbnail",
                    source_sha256=asset.blob_sha256,
                    descriptor=descriptor,
                    width=thumbnail.width,
                    height=thumbnail.height,
                )
            if derivative.source_sha256 != asset.blob_sha256:
                raise ConflictError("IP asset derivative source does not match the original")
            descriptor = IpAssetObjectDescriptor(
                bucket=derivative.bucket,
                object_key=derivative.object_key,
                media_type=derivative.media_type,
                byte_size=derivative.byte_size,
                sha256=derivative.sha256,
            )
            body = await self._store.get_verified(descriptor)
        return IpAssetPreparedThumbnail(asset=asset, derivative=derivative, body=body)

    async def download(
        self,
        asset_ref: str,
        *,
        profile: IpAssetProfileRecord | None,
        business_date: date | None = None,
    ) -> IpAssetPreparedDownload:
        asset, body = await self.original(asset_ref, profile=profile)
        if asset.shared_at is not None:
            await self._repository.increment_downloads(
                asset_ids=(asset.id,), business_date=business_date or datetime.now(UTC).date()
            )
        return IpAssetPreparedDownload(asset=asset, body=body)

    async def download_zip(
        self,
        refs: tuple[str, ...],
        *,
        profile: IpAssetProfileRecord | None = None,
        business_date: date | None = None,
    ) -> IpAssetPreparedZip:
        unique = tuple(dict.fromkeys(refs))
        if not unique or len(unique) > IP_ASSET_MAX_ZIP_ITEMS:
            raise IpAssetUploadRejectedError("invalid_ip_asset_metadata")
        originals: list[tuple[IpAssetRecord, bytes]] = []
        total_bytes = 0
        for asset_ref in unique:
            original = await self.original(asset_ref, profile=profile)
            total_bytes += len(original[1])
            if total_bytes > IP_ASSET_MAX_ZIP_BYTES:
                raise IpAssetUploadRejectedError("image_too_large")
            originals.append(original)
        body = await asyncio.to_thread(_build_zip, originals)
        shared_ids = tuple(asset.id for asset, _body in originals if asset.shared_at is not None)
        await self._repository.increment_downloads(
            asset_ids=shared_ids, business_date=business_date or datetime.now(UTC).date()
        )
        return IpAssetPreparedZip(body=body, assets=tuple(asset for asset, _body in originals))

    async def search_text(
        self,
        *,
        message: str,
        prior_turns: tuple[str, ...],
        filters: IpAssetQuery,
    ) -> IpAssetSearchResult:
        try:
            current = normalize_optional_text(message, maximum=2_000)
            if not current:
                raise ValueError("IP asset search text is blank")
            bounded_turns = tuple(
                normalize_optional_text(turn, maximum=500) for turn in prior_turns[-4:]
            )
        except ValueError as error:
            raise IpAssetUploadRejectedError("invalid_ip_asset_metadata") from error
        # Only the current turn may infer hard taxonomy constraints. Historical turns still add
        # semantic context, but a stale role/type must never override the user's current request.
        # Explicit controls in ``filters`` remain authoritative over inferred terms.
        extracted = _extract_filters(current, filters)
        metadata_hits = await self._search_metadata(text=current, query=extracted)
        if self._embeddings is None:
            return self._metadata_result(metadata_hits, "semantic_disabled", extracted)
        try:
            embedding = await self._embeddings.embed_visual(
                VisualEmbeddingRequest.for_text(
                    "\n".join((*bounded_turns, current)), identity=self._identity
                )
            )
            hits = await self._repository.search_vectors(
                query=extracted, embedding=embedding, identity=self._identity
            )
        except (VisualEmbeddingError, ValueError):
            return self._metadata_result(metadata_hits, "provider_unavailable", extracted)
        if not hits:
            return self._metadata_result(metadata_hits, "partial_index", extracted)
        return IpAssetSearchResult(
            mode=IpAssetSearchMode.SEMANTIC,
            degraded_reason=None,
            search_version=IP_ASSET_SEARCH_VERSION,
            items=_merge_text_search_hits(
                semantic_hits=hits,
                metadata_hits=metadata_hits,
                query=extracted,
            ),
        )

    async def search_image(
        self, *, body: bytes, media_type: str | None, filters: IpAssetQuery
    ) -> IpAssetSearchResult:
        try:
            validated = await asyncio.to_thread(
                validate_ip_asset_upload,
                filename="similarity-query",
                declared_media_type=media_type,
                body=body,
            )
        except IpAssetValidationError as error:
            raise IpAssetUploadRejectedError(error.code) from error
        if self._embeddings is None:
            return await self._metadata_fallback(filters, "semantic_disabled")
        try:
            normalized = await asyncio.to_thread(
                normalize_visual_embedding_image, validated.body, identity=self._identity
            )
            embedding = await self._embeddings.embed_visual(
                VisualEmbeddingRequest.for_normalized_image(
                    normalized.png_bytes, identity=self._identity
                )
            )
            hits = await self._repository.search_vectors(
                query=filters, embedding=embedding, identity=self._identity
            )
        except ValueError:
            return await self._metadata_fallback(filters, "input_normalization_failed")
        except VisualEmbeddingError:
            return await self._metadata_fallback(filters, "provider_unavailable")
        if not hits:
            return await self._metadata_fallback(filters, "partial_index")
        return IpAssetSearchResult(
            mode=IpAssetSearchMode.SEMANTIC,
            degraded_reason=None,
            search_version=IP_ASSET_SEARCH_VERSION,
            items=tuple(
                IpAssetSearchHit(
                    asset=hit.record,
                    similarity=hit.similarity,
                    explanation=_explanation(
                        hit.record,
                        similarity=hit.similarity,
                        query=filters,
                        matches=(),
                    ),
                )
                for hit in hits
            ),
        )

    async def _metadata_fallback(self, query: IpAssetQuery, reason: str) -> IpAssetSearchResult:
        hits = await self._search_metadata(text="", query=query)
        return self._metadata_result(hits, reason, query)

    async def _search_metadata(
        self, *, text: str, query: IpAssetQuery
    ) -> tuple[_MetadataSearchHit, ...]:
        # Conversational text is rarely an exact SQL substring (for example, "找小赛开心庆祝").
        # Fetch a bounded, structure-filtered candidate pool and rank exact metadata values in the
        # service. This also keeps assets without a compatible vector discoverable.
        page = await self._repository.list_assets(
            replace(
                query,
                query="",
                cursor_created_at=None,
                cursor_id=None,
                limit=_IP_ASSET_SEARCH_CANDIDATE_LIMIT,
            )
        )
        include_unmatched = not text or _has_structured_filter(query)
        ranked = tuple(_metadata_search_hit(asset, text) for asset in page.items)
        selected = tuple(hit for hit in ranked if include_unmatched or hit.score > 0)
        return tuple(
            sorted(
                selected,
                key=lambda hit: (
                    hit.score,
                    hit.asset.created_at,
                    hit.asset.id.hex,
                ),
                reverse=True,
            )[: query.limit]
        )

    @staticmethod
    def _metadata_result(
        hits: tuple[_MetadataSearchHit, ...], reason: str, query: IpAssetQuery
    ) -> IpAssetSearchResult:
        return IpAssetSearchResult(
            mode=IpAssetSearchMode.DEGRADED_METADATA,
            degraded_reason=reason,
            search_version=IP_ASSET_SEARCH_VERSION,
            items=tuple(
                IpAssetSearchHit(
                    asset=hit.asset,
                    similarity=None,
                    explanation=_explanation(
                        hit.asset,
                        similarity=None,
                        query=query,
                        matches=hit.matches,
                    ),
                )
                for hit in hits
            ),
        )


class IpAssetWorkerService:
    def __init__(
        self,
        *,
        repository: IpAssetRepository,
        store: IpAssetStore,
        embeddings: VisualEmbeddingModel | None,
        identity: VisualEmbeddingIdentity,
        image_generator: ImageGenerator | None,
    ) -> None:
        self._repository = repository
        self._store = store
        self._embeddings = embeddings
        self._identity = identity
        self._image_generator = image_generator

    async def enqueue_unavailable_embeddings(self, *, limit: int = 500) -> int:
        if self._embeddings is None:
            return 0
        return await self._repository.enqueue_unavailable_embeddings(limit=limit)

    async def process_one_embedding(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
        heartbeat_seconds: int | None = None,
        max_attempts: int = 3,
    ) -> bool:
        if self._embeddings is None:
            return False
        claim = await self._repository.claim_embedding_job(
            worker_id=worker_id, lease_seconds=lease_seconds, max_attempts=max_attempts
        )
        if claim is None:
            return False
        try:
            embedding = await _run_with_lease_heartbeat(
                self._prepare_embedding(claim),
                renew=lambda: self._repository.renew_embedding_lease(
                    claim=claim, lease_seconds=lease_seconds
                ),
                heartbeat_seconds=heartbeat_seconds or max(1, lease_seconds // 3),
            )
            completed = await self._repository.complete_embedding(
                claim=claim, embedding=embedding, identity=self._identity
            )
            if not completed:
                await self._repository.fail_embedding(
                    claim=claim, error_code="invalid_provider_output"
                )
        except _IpAssetLeaseLost:
            return True
        except (VisualEmbeddingError, ValueError):
            await self._repository.fail_embedding(claim=claim, error_code="provider_unavailable")
        return True

    async def _prepare_embedding(self, claim: IpAssetEmbeddingClaim) -> VisualEmbeddingResult:
        if self._embeddings is None:
            raise ValueError("IP asset embeddings are unavailable")
        descriptor = IpAssetObjectDescriptor(
            bucket=claim.asset.bucket,
            object_key=claim.asset.object_key,
            media_type=claim.asset.media_type,
            byte_size=claim.asset.byte_size,
            sha256=claim.asset.blob_sha256,
        )
        body = await self._store.get_verified(descriptor)
        normalized = await asyncio.to_thread(
            normalize_visual_embedding_image, body, identity=self._identity
        )
        return await self._embeddings.embed_visual(
            VisualEmbeddingRequest.for_normalized_image(
                normalized.png_bytes, identity=self._identity
            )
        )

    async def process_one_generation(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
        max_attempts: int,
        heartbeat_seconds: int | None = None,
    ) -> bool:
        if self._image_generator is None:
            return False
        claim = await self._repository.claim_generation_job(
            worker_id=worker_id, lease_seconds=lease_seconds, max_attempts=max_attempts
        )
        if claim is None:
            return False
        try:
            upload, descriptor, metadata = await _run_with_lease_heartbeat(
                self._generate_and_store(claim),
                renew=lambda: self._repository.renew_generation_lease(
                    claim=claim, lease_seconds=lease_seconds
                ),
                heartbeat_seconds=heartbeat_seconds or max(1, lease_seconds // 3),
            )
            await self._repository.complete_generation_asset(
                claim=claim,
                upload=upload,
                metadata=metadata,
                descriptor=descriptor,
                semantic_enabled=self._embeddings is not None,
            )
        except _IpAssetLeaseLost:
            return True
        except ProviderError as error:
            if error.retryable and claim.job.attempt_count < max_attempts:
                await self._repository.retry_generation(
                    claim=claim,
                    error_code="provider_unavailable",
                    delay_seconds=min(300, 2**claim.job.attempt_count),
                )
            else:
                code = (
                    "invalid_output"
                    if isinstance(error, ImageOutputValidationError)
                    else "provider_rejected"
                )
                await self._repository.fail_generation(claim=claim, error_code=code)
        except (IpAssetValidationError, ValueError):
            await self._repository.fail_generation(claim=claim, error_code="invalid_output")
        return True

    async def _generate_and_store(
        self, claim: IpAssetGenerationClaim
    ) -> tuple[ValidatedIpAssetUpload, IpAssetObjectDescriptor, IpAssetMetadata]:
        if self._image_generator is None:
            raise ValueError("IP asset image generator is unavailable")
        references = await self._generation_references(claim)
        result = await self._image_generator.generate(
            ImageGenerationRequest(
                run_id=claim.job.id,
                draft_version_id=claim.job.id,
                prompt=claim.job.prompt,
                request_fingerprint=claim.job.request_fingerprint,
                references=references,
                unrestricted_prompt_length=True,
                reference_mode=(
                    "legacy_single"
                    if not references
                    else (
                        "single_reference" if len(references) == 1 else "budgeted_multi_reference"
                    )
                ),
            )
        )
        if (
            result.provider != claim.job.provider
            or result.model != claim.job.model
            or result.request_fingerprint != claim.job.request_fingerprint
        ):
            raise ProviderIdentityMismatchError()
        upload = await asyncio.to_thread(
            validate_ip_asset_upload,
            filename="ai-generated",
            declared_media_type=result.media_type,
            body=result.image_bytes,
        )
        if (upload.width, upload.height) != (1_024, 1_024) or (
            upload.width,
            upload.height,
        ) != (result.width, result.height):
            raise ImageOutputValidationError("image_output_invalid")
        descriptor = await self._store.put_immutable(upload)
        metadata = IpAssetMetadata(
            character=claim.job.character,
            asset_type=claim.job.asset_type,
            department=claim.job.department,
            contributor=claim.job.contributor,
            intended_use="AI创作",
            tags=("ai-generated",),
        )
        return upload, descriptor, metadata

    async def _generation_references(
        self, claim: IpAssetGenerationClaim
    ) -> tuple[ImageReference, ...]:
        references: list[ImageReference] = []
        for expected in claim.job.references:
            record = await self._repository.get_by_id(expected.asset_id)
            if (
                record is None
                or record.status.value != "ready"
                or record.blob_sha256 != expected.source_sha256
            ):
                raise ValueError("generation reference asset is unavailable")
            descriptor = IpAssetObjectDescriptor(
                bucket=record.bucket,
                object_key=record.object_key,
                media_type=record.media_type,
                byte_size=record.byte_size,
                sha256=record.blob_sha256,
            )
            body = await self._store.get_verified(descriptor)
            references.append(
                ImageReference(
                    role="identity_reference",
                    asset_id=record.asset_ref,
                    filename=canonical_download_filename(record.canonical_slug, record.media_type),
                    sha256=record.blob_sha256,
                    image_bytes=body,
                    selection_reason=f"user_selected_reference_{expected.ordinal + 1}",
                )
            )
        return tuple(references)


async def enqueue_ip_asset_generation(
    *,
    repository: IpAssetRepository,
    prompt: str,
    metadata: IpAssetMetadata,
    ratio: str,
    profile: IpAssetProfileRecord,
    reference_assets: tuple[IpAssetRecord, ...],
    idempotency_key: str,
    provider: str,
    model: str,
) -> tuple[IpAssetGenerationRecord, bool]:
    try:
        clean_prompt = validate_image_prompt(
            prompt,
            minimum_length=None,
            maximum_length=None,
        )
        clean_key = normalize_optional_text(idempotency_key, maximum=128)
        normalized_refs = normalize_generation_reference_refs(
            tuple(asset.asset_ref for asset in reference_assets)
        )
    except ValueError as error:
        raise IpAssetUploadRejectedError("invalid_ip_asset_metadata") from error
    if (
        not clean_key
        or ratio != "1:1"
        or normalized_refs != tuple(asset.asset_ref for asset in reference_assets)
        or any(
            asset.status is not IpAssetStatus.READY or asset.shared_at is None
            for asset in reference_assets
        )
    ):
        raise IpAssetUploadRejectedError("invalid_ip_asset_metadata")
    fingerprint = hashlib.sha256(
        "\0".join(
            (
                "ip-asset-generation-v2-profile-multi-reference",
                profile.profile_ref,
                clean_prompt,
                metadata.character.value,
                metadata.asset_type.value,
                metadata.department,
                metadata.contributor,
                ratio,
                *(
                    value
                    for asset in reference_assets
                    for value in (asset.asset_ref, asset.blob_sha256)
                ),
                provider,
                model,
            )
        ).encode()
    ).hexdigest()
    return await repository.enqueue_generation(
        idempotency_key=clean_key,
        request_fingerprint=fingerprint,
        prompt=clean_prompt,
        metadata=metadata,
        ratio=ratio,
        profile_id=profile.id,
        references=tuple((asset.id, asset.blob_sha256) for asset in reference_assets),
        provider=provider,
        model=model,
    )


def _extract_filters(text: str, base: IpAssetQuery) -> IpAssetQuery:
    normalized = text.casefold()
    character = base.character
    if character is None:
        has_xiao_sai = "小赛" in normalized
        has_sai_xiansheng = "赛先生" in normalized
        if (has_xiao_sai and has_sai_xiansheng) or any(
            term in normalized for term in ("双角色", "两个角色", "同框", "合影")
        ):
            character = IpAssetCharacter.DUO
        elif has_xiao_sai:
            character = IpAssetCharacter.XIAO_SAI
        elif has_sai_xiansheng:
            character = IpAssetCharacter.SAI_XIANSHENG
    asset_type = base.asset_type
    if asset_type is None:
        for terms, value in (
            (("表情包", "贴纸", "meme"), IpAssetType.MEME_STICKER),
            (("头像",), IpAssetType.PORTRAIT_AVATAR),
            (("透明底素材", "免抠素材", "透明抠图"), IpAssetType.TRANSPARENT_CUTOUT),
            (("全身", "动作"), IpAssetType.FULL_BODY_ACTION),
            (("场景", "插画"), IpAssetType.SCENE_ILLUSTRATION),
            (("表情",), IpAssetType.EXPRESSION),
            (("海报元素",), IpAssetType.POSTER_ELEMENT),
            (("形象设定", "角色设定"), IpAssetType.IDENTITY_REFERENCE),
        ):
            if any(term in normalized for term in terms):
                asset_type = value
                break
    orientation = base.orientation
    if orientation is None:
        if "横图" in normalized:
            orientation = IpAssetOrientation.LANDSCAPE
        elif "竖图" in normalized:
            orientation = IpAssetOrientation.PORTRAIT
        elif "方图" in normalized or "正方形" in normalized:
            orientation = IpAssetOrientation.SQUARE
    return IpAssetQuery(
        # Keep the lexical evidence even after controlled terms become hard constraints. Vector
        # retrieval ignores this field, while hybrid metadata ranking uses the normalized text.
        query=base.query or text[-200:],
        character=character,
        asset_type=asset_type,
        department=base.department,
        source_kind=base.source_kind,
        orientation=orientation,
        tag=base.tag,
        limit=base.limit,
    )


def _has_structured_filter(query: IpAssetQuery) -> bool:
    return any(
        (
            query.character is not None,
            query.asset_type is not None,
            bool(query.department),
            query.source_kind is not None,
            query.orientation is not None,
            bool(query.tag),
        )
    )


def _metadata_search_hit(asset: IpAssetRecord, text: str) -> _MetadataSearchHit:
    normalized = text.casefold()
    matches_by_value: dict[str, tuple[str, float]] = {}
    for value, explanation, weight in (
        (asset.canonical_name, "资产名称关键词", 4.0),
        # The safe original filename is searchable by contract but remains detail-only. A generic
        # reason proves why the record matched without copying the filename into search responses.
        (asset.safe_original_filename, "原文件名关键词", 3.5),
        (asset.department, f"部门: {asset.department}", 2.0),
        (asset.contributor, f"贡献者: {asset.contributor}", 1.5),
        (asset.emotion, asset.emotion, 3.0),
        (asset.action, asset.action, 2.5),
        (asset.scene, asset.scene, 2.0),
        (asset.intended_use, asset.intended_use, 2.0),
        (asset.style, asset.style, 1.0),
        *((tag, tag, 1.5) for tag in asset.tags),
    ):
        clean = value.casefold().strip()
        if not clean or clean not in normalized:
            continue
        previous = matches_by_value.get(clean)
        if previous is None or weight > previous[1]:
            matches_by_value[clean] = (explanation, weight)
    ordered = tuple(
        value
        for value, _weight in sorted(
            matches_by_value.values(), key=lambda item: (-item[1], item[0].casefold())
        )
    )
    raw_score = sum(weight for _value, weight in matches_by_value.values())
    return _MetadataSearchHit(
        asset=asset,
        score=min(1.0, raw_score / 8.0),
        matches=ordered,
    )


def _merge_text_search_hits(
    *,
    semantic_hits: tuple[IpAssetVectorHit, ...],
    metadata_hits: tuple[_MetadataSearchHit, ...],
    query: IpAssetQuery,
) -> tuple[IpAssetSearchHit, ...]:
    semantic_by_ref = {hit.record.asset_ref: hit for hit in semantic_hits}
    metadata_by_ref = {hit.asset.asset_ref: hit for hit in metadata_hits}
    records = {hit.record.asset_ref: hit.record for hit in semantic_hits} | {
        hit.asset.asset_ref: hit.asset for hit in metadata_hits
    }
    ranked: list[tuple[float, float, float, IpAssetSearchHit]] = []
    for asset_ref, asset in records.items():
        semantic = semantic_by_ref.get(asset_ref)
        metadata = metadata_by_ref.get(asset_ref)
        similarity = semantic.similarity if semantic is not None else None
        semantic_score = (
            ((similarity + 1.0) / 2.0) * _SEMANTIC_RANK_WEIGHT if similarity is not None else 0.0
        )
        metadata_score = metadata.score * _METADATA_RANK_WEIGHT if metadata is not None else 0.0
        ranked.append(
            (
                semantic_score + metadata_score,
                metadata.score if metadata is not None else 0.0,
                similarity if similarity is not None else -2.0,
                IpAssetSearchHit(
                    asset=asset,
                    similarity=similarity,
                    explanation=_explanation(
                        asset,
                        similarity=similarity,
                        query=query,
                        matches=metadata.matches if metadata is not None else (),
                    ),
                ),
            )
        )
    ranked.sort(
        key=lambda item: (
            item[0],
            item[1],
            item[2],
            item[3].asset.created_at,
            item[3].asset.id.hex,
        ),
        reverse=True,
    )
    return tuple(item[3] for item in ranked[: query.limit])


def _explanation(
    asset: IpAssetRecord,
    *,
    similarity: float | None,
    query: IpAssetQuery,
    matches: tuple[str, ...],
) -> str:
    parts: list[str] = []
    if query.character is not None:
        character_labels = {
            IpAssetCharacter.SAI_XIANSHENG: "赛先生",
            IpAssetCharacter.XIAO_SAI: "小赛",
            IpAssetCharacter.DUO: "双角色",
            IpAssetCharacter.OTHER: "其他 IP",
        }
        parts.append(f"角色: {character_labels[asset.character]}")
    if query.asset_type is not None:
        asset_type_labels = {
            IpAssetType.IDENTITY_REFERENCE: "形象设定",
            IpAssetType.PORTRAIT_AVATAR: "头像",
            IpAssetType.FULL_BODY_ACTION: "全身动作",
            IpAssetType.EXPRESSION: "表情",
            IpAssetType.MEME_STICKER: "表情包",
            IpAssetType.TRANSPARENT_CUTOUT: "透明底素材",
            IpAssetType.SCENE_ILLUSTRATION: "场景插画",
            IpAssetType.POSTER_ELEMENT: "海报元素",
            IpAssetType.OTHER: "其他",
        }
        parts.append(f"类型: {asset_type_labels[asset.asset_type]}")
    if matches:
        parts.append("文字匹配: " + "、".join(matches[:4]))
    if similarity is not None:
        parts.append("画面语义相关")
    explanation = "; ".join(parts) or "按分类与文字元数据匹配"
    if len(explanation) <= 240:
        return explanation
    return explanation[:239].rstrip() + "…"


def _build_zip(originals: list[tuple[IpAssetRecord, bytes]]) -> bytes:
    output = io.BytesIO()
    manifest: list[dict[str, object]] = []
    used_names: set[str] = set()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for asset, body in originals:
            filename = canonical_download_filename(asset.canonical_slug, asset.media_type)
            if filename in used_names:
                filename = f"{asset.asset_ref}-{filename}"
            used_names.add(filename)
            archive.writestr(filename, body)
            manifest.append(
                {
                    "asset_ref": asset.asset_ref,
                    "canonical_name": asset.canonical_name,
                    "character": asset.character.value,
                    "asset_type": asset.asset_type.value,
                    "sha256": asset.blob_sha256,
                    "filename": filename,
                }
            )
        archive.writestr(
            "manifest.json",
            json.dumps({"assets": manifest}, ensure_ascii=False, indent=2).encode("utf-8"),
        )
    return output.getvalue()


_HeartbeatResult = TypeVar("_HeartbeatResult")


class _IpAssetLeaseLost(RuntimeError):
    pass


async def _run_with_lease_heartbeat(
    operation: Awaitable[_HeartbeatResult],
    *,
    renew: Callable[[], Awaitable[bool]],
    heartbeat_seconds: int,
) -> _HeartbeatResult:
    async def heartbeat() -> None:
        while True:
            await asyncio.sleep(heartbeat_seconds)
            if not await renew():
                raise _IpAssetLeaseLost("IP asset worker lease ownership was lost")

    operation_task = asyncio.ensure_future(operation)
    heartbeat_task = asyncio.create_task(heartbeat())
    try:
        done, _pending = await asyncio.wait(
            {operation_task, heartbeat_task}, return_when=asyncio.FIRST_COMPLETED
        )
    except BaseException:
        operation_task.cancel()
        heartbeat_task.cancel()
        await asyncio.gather(operation_task, heartbeat_task, return_exceptions=True)
        raise
    if heartbeat_task in done:
        operation_task.cancel()
        await asyncio.gather(operation_task, return_exceptions=True)
        await heartbeat_task
        raise AssertionError("unreachable")
    heartbeat_task.cancel()
    await asyncio.gather(heartbeat_task, return_exceptions=True)
    return await operation_task
