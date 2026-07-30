from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, datetime
from typing import Protocol
from uuid import UUID

from app.domain.brand_knowledge import (
    BrandAudience,
    BrandChunk,
    BrandChunkEmbedding,
    BrandDocumentKind,
    BrandOriginalDescriptor,
    BrandRetrievalHit,
    BrandUploadMetadata,
    ClaimedBrandIngestionJob,
    ParsedBrandDocument,
    ValidatedBrandUpload,
)


@dataclass(frozen=True, slots=True)
class BrandEmbeddingRequest:
    chunk_id: UUID
    input_hash: str
    text: str


@dataclass(frozen=True, slots=True)
class BrandEmbeddingResult:
    vector: tuple[float, ...]
    provider: str
    model: str
    request_fingerprint: str
    provider_request_id: str | None


class BrandOriginalStore(Protocol):
    async def put_immutable(self, upload: ValidatedBrandUpload) -> BrandOriginalDescriptor: ...

    async def get_immutable(self, *, bucket: str, object_key: str, sha256: str) -> bytes: ...


class BrandDocumentParser(Protocol):
    def parse(self, *, body: bytes, media_type: str) -> ParsedBrandDocument: ...

    def chunk(
        self, *, version_id: UUID, document: ParsedBrandDocument
    ) -> tuple[BrandChunk, ...]: ...


class BrandEmbeddingModel(Protocol):
    async def embed_brand(self, request: BrandEmbeddingRequest) -> BrandEmbeddingResult: ...


class BrandKnowledgeRepository(Protocol):
    async def create_upload(
        self,
        *,
        metadata: BrandUploadMetadata,
        upload: ValidatedBrandUpload,
        original: BrandOriginalDescriptor,
        parser_version: str,
        chunk_version: str,
        embedding_input_version: str,
        embedding_provider: str,
        embedding_model: str,
        dimensions: int,
    ) -> tuple[UUID, UUID, UUID, bool]: ...

    async def claim(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
        max_attempts: int,
        embedding_provider: str,
        embedding_model: str,
    ) -> ClaimedBrandIngestionJob | None: ...

    async def heartbeat(self, *, claimed: ClaimedBrandIngestionJob, lease_seconds: int) -> bool: ...

    async def persist_ingestion(
        self,
        *,
        claimed: ClaimedBrandIngestionJob,
        parsed: ParsedBrandDocument,
        embeddings: Sequence[BrandChunkEmbedding],
    ) -> bool: ...

    async def fail_ingestion(
        self,
        *,
        claimed: ClaimedBrandIngestionJob,
        error_code: str,
        retry_at: datetime | None = None,
    ) -> bool: ...

    async def retrieve(
        self,
        *,
        query_text: str,
        query_vector: tuple[float, ...],
        query_provider: str,
        query_model: str,
        audience: BrandAudience,
        document_kinds: tuple[BrandDocumentKind, ...],
        valid_on: date,
        limit: int,
        candidate_limit: int,
    ) -> tuple[BrandRetrievalHit, ...]: ...
