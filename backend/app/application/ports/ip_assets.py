from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.domain.ip_asset_recognition import (
    IpAssetRecognitionRequest,
    IpAssetRecognitionSuggestion,
)
from app.domain.ip_assets import (
    IpAssetCharacter,
    IpAssetMetadata,
    IpAssetOrientation,
    IpAssetSemanticStatus,
    IpAssetSource,
    IpAssetStatus,
    IpAssetType,
    ValidatedIpAssetUpload,
)
from app.domain.visual_retrieval import VisualEmbeddingIdentity, VisualEmbeddingResult


@dataclass(frozen=True, slots=True)
class IpAssetObjectDescriptor:
    bucket: str
    object_key: str
    media_type: str
    byte_size: int
    sha256: str


@dataclass(frozen=True, slots=True)
class IpAssetRecord:
    id: UUID
    asset_ref: str
    blob_sha256: str
    perceptual_hash: str
    safe_original_filename: str
    media_type: str
    byte_size: int
    width: int
    height: int
    has_alpha: bool
    orientation: IpAssetOrientation
    bucket: str
    object_key: str
    canonical_name: str
    canonical_slug: str
    name_version: int
    character: IpAssetCharacter
    asset_type: IpAssetType
    source_kind: IpAssetSource
    department: str
    contributor: str
    emotion: str
    action: str
    scene: str
    intended_use: str
    style: str
    tags: tuple[str, ...]
    status: IpAssetStatus
    semantic_status: IpAssetSemanticStatus
    failure_code: str | None
    parent_asset_id: UUID | None
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class IpAssetQuery:
    query: str = ""
    character: IpAssetCharacter | None = None
    asset_type: IpAssetType | None = None
    department: str = ""
    source_kind: IpAssetSource | None = None
    orientation: IpAssetOrientation | None = None
    tag: str = ""
    cursor_created_at: datetime | None = None
    cursor_id: UUID | None = None
    limit: int = 24


@dataclass(frozen=True, slots=True)
class IpAssetPage:
    items: tuple[IpAssetRecord, ...]
    next_cursor_created_at: datetime | None
    next_cursor_id: UUID | None


@dataclass(frozen=True, slots=True)
class IpAssetVectorHit:
    record: IpAssetRecord
    similarity: float


@dataclass(frozen=True, slots=True)
class IpAssetEmbeddingClaim:
    job_id: UUID
    asset: IpAssetRecord
    lease_token: UUID
    attempt_number: int


@dataclass(frozen=True, slots=True)
class IpAssetGenerationRecord:
    id: UUID
    job_ref: str
    idempotency_key: str
    request_fingerprint: str
    prompt: str
    character: IpAssetCharacter
    asset_type: IpAssetType
    department: str
    contributor: str
    ratio: str
    reference_asset_id: UUID | None
    provider: str
    model: str
    status: str
    attempt_count: int
    lease_token: UUID | None
    output_asset_id: UUID | None
    error_code: str | None
    created_at: datetime
    completed_at: datetime | None


@dataclass(frozen=True, slots=True)
class IpAssetGenerationClaim:
    job: IpAssetGenerationRecord
    lease_token: UUID


class IpAssetStore(Protocol):
    async def put_immutable(self, upload: ValidatedIpAssetUpload) -> IpAssetObjectDescriptor: ...

    async def get_verified(self, descriptor: IpAssetObjectDescriptor) -> bytes: ...


class IpAssetRecognitionModel(Protocol):
    async def suggest(self, request: IpAssetRecognitionRequest) -> IpAssetRecognitionSuggestion: ...


class IpAssetRepository(Protocol):
    async def get_by_sha256(self, sha256: str) -> IpAssetRecord | None: ...

    async def get_by_ref(self, asset_ref: str) -> IpAssetRecord | None: ...

    async def get_by_id(self, asset_id: UUID) -> IpAssetRecord | None: ...

    async def create_asset(
        self,
        *,
        upload: ValidatedIpAssetUpload,
        metadata: IpAssetMetadata,
        descriptor: IpAssetObjectDescriptor,
        source_kind: IpAssetSource,
        parent_asset_id: UUID | None = None,
        semantic_enabled: bool,
    ) -> tuple[IpAssetRecord, bool]: ...

    async def list_assets(self, query: IpAssetQuery) -> IpAssetPage: ...

    async def find_near_duplicate(
        self, *, perceptual_hash: str, exclude_id: UUID | None = None
    ) -> tuple[str, int] | None: ...

    async def enqueue_unavailable_embeddings(self, *, limit: int = 500) -> int: ...

    async def claim_embedding_job(
        self, *, worker_id: str, lease_seconds: int, max_attempts: int = 3
    ) -> IpAssetEmbeddingClaim | None: ...

    async def complete_embedding(
        self,
        *,
        claim: IpAssetEmbeddingClaim,
        embedding: VisualEmbeddingResult,
        identity: VisualEmbeddingIdentity,
    ) -> bool: ...

    async def fail_embedding(self, *, claim: IpAssetEmbeddingClaim, error_code: str) -> bool: ...

    async def search_vectors(
        self,
        *,
        query: IpAssetQuery,
        embedding: VisualEmbeddingResult,
        identity: VisualEmbeddingIdentity,
    ) -> tuple[IpAssetVectorHit, ...]: ...

    async def enqueue_generation(
        self,
        *,
        idempotency_key: str,
        request_fingerprint: str,
        prompt: str,
        metadata: IpAssetMetadata,
        ratio: str,
        reference_asset_id: UUID | None,
        provider: str,
        model: str,
    ) -> tuple[IpAssetGenerationRecord, bool]: ...

    async def get_generation(self, job_ref: str) -> IpAssetGenerationRecord | None: ...

    async def claim_generation_job(
        self, *, worker_id: str, lease_seconds: int, max_attempts: int
    ) -> IpAssetGenerationClaim | None: ...

    async def complete_generation(
        self, *, claim: IpAssetGenerationClaim, output_asset_id: UUID
    ) -> bool: ...

    async def complete_generation_asset(
        self,
        *,
        claim: IpAssetGenerationClaim,
        upload: ValidatedIpAssetUpload,
        metadata: IpAssetMetadata,
        descriptor: IpAssetObjectDescriptor,
        semantic_enabled: bool,
    ) -> IpAssetRecord | None: ...

    async def renew_embedding_lease(
        self, *, claim: IpAssetEmbeddingClaim, lease_seconds: int
    ) -> bool: ...

    async def renew_generation_lease(
        self, *, claim: IpAssetGenerationClaim, lease_seconds: int
    ) -> bool: ...

    async def fail_generation(self, *, claim: IpAssetGenerationClaim, error_code: str) -> bool: ...

    async def retry_generation(
        self, *, claim: IpAssetGenerationClaim, error_code: str, delay_seconds: int
    ) -> bool: ...
