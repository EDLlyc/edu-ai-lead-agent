from __future__ import annotations

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import cast
from uuid import UUID, uuid4

from sqlalchemy import func, or_, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.ports.brand_knowledge import BrandKnowledgeRepository
from app.core.errors import ConflictError, NotFoundError
from app.domain.brand_knowledge import (
    BrandAudience,
    BrandChunkEmbedding,
    BrandDocumentKind,
    BrandIngestionJobStatus,
    BrandOriginalDescriptor,
    BrandRetrievalHit,
    BrandUploadMetadata,
    BrandVersionStatus,
    ClaimedBrandIngestionJob,
    ParsedBrandDocument,
    ValidatedBrandUpload,
)
from app.infrastructure.db.models import (
    BrandChunkEmbeddingModel,
    BrandChunkModel,
    BrandDocumentModel,
    BrandDocumentVersionModel,
    BrandIngestionAttemptModel,
    BrandIngestionJobModel,
)

_SAFE_ERROR_CODE = re.compile(r"[a-z][a-z0-9_]{0,79}")
_RRF_K = 60.0
_FULL_TEXT_WEIGHT = 0.45
_VECTOR_WEIGHT = 0.55


@dataclass(frozen=True, slots=True)
class _RankedBrandHit:
    hit: BrandRetrievalHit
    ordinal: int


def _select_diverse_brand_hits(
    candidates: Sequence[_RankedBrandHit], *, limit: int
) -> tuple[BrandRetrievalHit, ...]:
    """Keep RRF order while using available candidates from different brand sections."""
    if limit < 1:
        return ()
    ordered = sorted(
        candidates,
        key=lambda candidate: (
            -candidate.hit.fused_score,
            -candidate.hit.vector_score,
            -candidate.hit.full_text_score,
            str(candidate.hit.chunk_id),
        ),
    )
    document_cap = max(1, min(2, (limit + 1) // 2))
    selected: list[_RankedBrandHit] = []
    selected_ids: set[UUID] = set()

    def add_candidates(
        *,
        max_per_document: int | None,
        avoid_adjacent: bool,
        avoid_duplicate_text: bool,
    ) -> None:
        document_counts: dict[UUID, int] = {}
        for candidate in selected:
            document_counts[candidate.hit.document_id] = (
                document_counts.get(candidate.hit.document_id, 0) + 1
            )
        for candidate in ordered:
            if len(selected) >= limit:
                return
            hit = candidate.hit
            if hit.chunk_id in selected_ids:
                continue
            if (
                max_per_document is not None
                and document_counts.get(hit.document_id, 0) >= max_per_document
            ):
                continue
            if avoid_duplicate_text and any(existing.hit.text == hit.text for existing in selected):
                continue
            if avoid_adjacent and any(
                existing.hit.document_id == hit.document_id
                and existing.hit.version_id == hit.version_id
                and abs(existing.ordinal - candidate.ordinal) <= 1
                for existing in selected
            ):
                continue
            selected.append(candidate)
            selected_ids.add(hit.chunk_id)
            document_counts[hit.document_id] = document_counts.get(hit.document_id, 0) + 1

    # The first pass is intentionally conservative. Later passes are deterministic fallbacks
    # for a corpus with one document, one section, or repeated OCR output.
    add_candidates(
        max_per_document=document_cap,
        avoid_adjacent=True,
        avoid_duplicate_text=True,
    )
    add_candidates(
        max_per_document=document_cap,
        avoid_adjacent=False,
        avoid_duplicate_text=True,
    )
    add_candidates(max_per_document=None, avoid_adjacent=False, avoid_duplicate_text=False)

    rank_by_chunk_id = {candidate.hit.chunk_id: rank for rank, candidate in enumerate(ordered)}
    selected.sort(key=lambda candidate: rank_by_chunk_id[candidate.hit.chunk_id])
    return tuple(candidate.hit for candidate in selected)


@dataclass(frozen=True, slots=True)
class BrandDocumentProjection:
    document: BrandDocumentModel
    versions: tuple[BrandDocumentVersionModel, ...]
    jobs_by_version: dict[UUID, BrandIngestionJobModel]


class PostgresBrandKnowledgeRepository(BrandKnowledgeRepository):
    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

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
    ) -> tuple[UUID, UUID, UUID, bool]:
        async with self._session_factory() as session:
            try:
                result = await _create_upload(
                    session,
                    metadata=metadata,
                    upload=upload,
                    original=original,
                    parser_version=parser_version,
                    chunk_version=chunk_version,
                    embedding_input_version=embedding_input_version,
                    embedding_provider=embedding_provider,
                    embedding_model=embedding_model,
                    dimensions=dimensions,
                )
                await session.commit()
                return result
            except IntegrityError:
                await session.rollback()
                existing = await _find_existing_derivation(
                    session,
                    document_key=metadata.document_key,
                    sha256=upload.sha256,
                    metadata_fingerprint=metadata.metadata_fingerprint,
                    parser_version=parser_version,
                    chunk_version=chunk_version,
                    embedding_input_version=embedding_input_version,
                    embedding_provider=embedding_provider,
                    embedding_model=embedding_model,
                )
                if existing is None:
                    try:
                        result = await _create_upload(
                            session,
                            metadata=metadata,
                            upload=upload,
                            original=original,
                            parser_version=parser_version,
                            chunk_version=chunk_version,
                            embedding_input_version=embedding_input_version,
                            embedding_provider=embedding_provider,
                            embedding_model=embedding_model,
                            dimensions=dimensions,
                        )
                        await session.commit()
                        return result
                    except IntegrityError:
                        await session.rollback()
                        raise ConflictError(
                            "brand document version changed concurrently; retry the upload"
                        ) from None
                return (*existing, False)

    async def claim(
        self,
        *,
        worker_id: str,
        lease_seconds: int,
        max_attempts: int,
        embedding_provider: str,
        embedding_model: str,
    ) -> ClaimedBrandIngestionJob | None:
        async with self._session_factory() as session:
            return await _claim(
                session,
                worker_id=worker_id,
                lease_seconds=lease_seconds,
                max_attempts=max_attempts,
                embedding_provider=embedding_provider,
                embedding_model=embedding_model,
            )

    async def heartbeat(self, *, claimed: ClaimedBrandIngestionJob, lease_seconds: int) -> bool:
        async with self._session_factory() as session:
            return await _heartbeat(session, claimed=claimed, lease_seconds=lease_seconds)

    async def persist_ingestion(
        self,
        *,
        claimed: ClaimedBrandIngestionJob,
        parsed: ParsedBrandDocument,
        embeddings: Sequence[BrandChunkEmbedding],
    ) -> bool:
        async with self._session_factory() as session:
            return await _persist_ingestion(
                session,
                claimed=claimed,
                parsed=parsed,
                embeddings=embeddings,
            )

    async def fail_ingestion(
        self,
        *,
        claimed: ClaimedBrandIngestionJob,
        error_code: str,
        retry_at: datetime | None = None,
    ) -> bool:
        async with self._session_factory() as session:
            return await _fail_ingestion(
                session,
                claimed=claimed,
                error_code=error_code,
                retry_at=retry_at,
            )

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
    ) -> tuple[BrandRetrievalHit, ...]:
        async with self._session_factory() as session:
            return await retrieve_brand_context(
                session,
                query_text=query_text,
                query_vector=query_vector,
                query_provider=query_provider,
                query_model=query_model,
                audience=audience,
                document_kinds=document_kinds,
                valid_on=valid_on,
                limit=limit,
                candidate_limit=candidate_limit,
            )


async def _create_upload(
    session: AsyncSession,
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
) -> tuple[UUID, UUID, UUID, bool]:
    document = await session.scalar(
        select(BrandDocumentModel)
        .where(BrandDocumentModel.document_key == metadata.document_key)
        .with_for_update()
    )
    if document is None:
        document = BrandDocumentModel(
            id=uuid4(),
            brand_slug=metadata.brand_slug,
            document_key=metadata.document_key,
            title=metadata.title.strip(),
            document_kind=metadata.document_kind.value,
            audience=metadata.audience.value,
            language=metadata.language,
            status="inactive",
            active_version_id=None,
        )
        session.add(document)
        await session.flush()
    existing = await _find_existing_derivation(
        session,
        document_key=metadata.document_key,
        sha256=upload.sha256,
        metadata_fingerprint=metadata.metadata_fingerprint,
        parser_version=parser_version,
        chunk_version=chunk_version,
        embedding_input_version=embedding_input_version,
        embedding_provider=embedding_provider,
        embedding_model=embedding_model,
    )
    if existing is not None:
        return (*existing, False)
    current_version = await session.scalar(
        select(func.coalesce(func.max(BrandDocumentVersionModel.version), 0)).where(
            BrandDocumentVersionModel.document_id == document.id
        )
    )
    next_version = (current_version or 0) + 1
    version_id = uuid4()
    job_id = uuid4()
    session.add(
        BrandDocumentVersionModel(
            id=version_id,
            document_id=document.id,
            version=next_version,
            safe_filename=upload.safe_filename,
            media_type=original.media_type,
            byte_size=original.byte_size,
            sha256=original.sha256,
            bucket=original.bucket,
            object_key=original.object_key,
            metadata_fingerprint=metadata.metadata_fingerprint,
            parser_version=parser_version,
            chunk_version=chunk_version,
            embedding_input_version=embedding_input_version,
            embedding_provider=embedding_provider,
            embedding_model=embedding_model,
            embedding_dimensions=dimensions,
            status=BrandVersionStatus.QUEUED.value,
            active=False,
            valid_from=metadata.valid_from,
            valid_until=metadata.valid_until,
            tone_tags=list(metadata.tone_tags),
            safety_tags=list(metadata.safety_tags),
            visual_tags=list(metadata.visual_tags),
            page_count=None,
            character_count=None,
            chunk_count=0,
            error_code=None,
        )
    )
    session.add(
        BrandIngestionJobModel(
            id=job_id,
            version_id=version_id,
            status=BrandIngestionJobStatus.QUEUED.value,
            attempt_count=0,
        )
    )
    return document.id, version_id, job_id, True


async def _find_existing_derivation(
    session: AsyncSession,
    *,
    document_key: str,
    sha256: str,
    metadata_fingerprint: str,
    parser_version: str,
    chunk_version: str,
    embedding_input_version: str,
    embedding_provider: str,
    embedding_model: str,
) -> tuple[UUID, UUID, UUID] | None:
    row = (
        (
            await session.execute(
                select(
                    BrandDocumentModel.id,
                    BrandDocumentVersionModel.id,
                    BrandIngestionJobModel.id,
                )
                .join(
                    BrandDocumentVersionModel,
                    BrandDocumentVersionModel.document_id == BrandDocumentModel.id,
                )
                .join(
                    BrandIngestionJobModel,
                    BrandIngestionJobModel.version_id == BrandDocumentVersionModel.id,
                )
                .where(
                    BrandDocumentModel.document_key == document_key,
                    BrandDocumentVersionModel.sha256 == sha256,
                    BrandDocumentVersionModel.metadata_fingerprint == metadata_fingerprint,
                    BrandDocumentVersionModel.parser_version == parser_version,
                    BrandDocumentVersionModel.chunk_version == chunk_version,
                    BrandDocumentVersionModel.embedding_input_version == embedding_input_version,
                    BrandDocumentVersionModel.embedding_provider == embedding_provider,
                    BrandDocumentVersionModel.embedding_model == embedding_model,
                    BrandIngestionJobModel.status != BrandIngestionJobStatus.FAILED.value,
                )
            )
        )
        .tuples()
        .first()
    )
    return row


async def _claim(
    session: AsyncSession,
    *,
    worker_id: str,
    lease_seconds: int,
    max_attempts: int,
    embedding_provider: str,
    embedding_model: str,
) -> ClaimedBrandIngestionJob | None:
    now = datetime.now(UTC)
    stale_jobs = tuple(
        (
            await session.scalars(
                select(BrandIngestionJobModel)
                .where(
                    BrandIngestionJobModel.status == BrandIngestionJobStatus.RUNNING.value,
                    BrandIngestionJobModel.lease_expires_at < now,
                )
                .with_for_update(skip_locked=True)
            )
        ).all()
    )
    for stale in stale_jobs:
        terminal = stale.attempt_count >= max_attempts
        stale.status = (
            BrandIngestionJobStatus.FAILED.value
            if terminal
            else BrandIngestionJobStatus.RETRY_SCHEDULED.value
        )
        stale.available_at = now
        stale.lease_owner = None
        stale.lease_token = None
        stale.lease_expires_at = None
        stale.error_code = "lease_expired"
        if terminal:
            stale.completed_at = now
            version = await session.get(BrandDocumentVersionModel, stale.version_id)
            if version is not None:
                version.status = BrandVersionStatus.FAILED.value
                version.error_code = "lease_expired"
                version.completed_at = now
        attempt = await session.scalar(
            select(BrandIngestionAttemptModel).where(
                BrandIngestionAttemptModel.job_id == stale.id,
                BrandIngestionAttemptModel.attempt_number == stale.attempt_count,
            )
        )
        if attempt is not None and attempt.status == "running":
            attempt.status = "failed" if terminal else "retry_scheduled"
            attempt.error_code = "lease_expired"
            attempt.completed_at = now
    job = await session.scalar(
        select(BrandIngestionJobModel)
        .join(
            BrandDocumentVersionModel,
            BrandDocumentVersionModel.id == BrandIngestionJobModel.version_id,
        )
        .where(
            BrandIngestionJobModel.status.in_(
                [
                    BrandIngestionJobStatus.QUEUED.value,
                    BrandIngestionJobStatus.RETRY_SCHEDULED.value,
                ]
            ),
            BrandIngestionJobModel.available_at <= now,
            BrandIngestionJobModel.attempt_count < max_attempts,
            BrandDocumentVersionModel.embedding_provider == embedding_provider,
            BrandDocumentVersionModel.embedding_model == embedding_model,
        )
        .order_by(BrandIngestionJobModel.available_at, BrandIngestionJobModel.created_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if job is None:
        await session.commit()
        return None
    version = await session.get(BrandDocumentVersionModel, job.version_id)
    if version is None:
        raise RuntimeError("brand ingestion job version is missing")
    lease_token = uuid4()
    job.status = BrandIngestionJobStatus.RUNNING.value
    job.attempt_count += 1
    job.lease_owner = worker_id
    job.lease_token = lease_token
    job.lease_expires_at = now + timedelta(seconds=lease_seconds)
    job.heartbeat_at = now
    job.started_at = job.started_at or now
    job.error_code = None
    version.status = BrandVersionStatus.PROCESSING.value
    version.error_code = None
    session.add(
        BrandIngestionAttemptModel(
            id=uuid4(),
            job_id=job.id,
            attempt_number=job.attempt_count,
            status="running",
            error_code=None,
            safe_metadata={"media_type": version.media_type, "byte_size": version.byte_size},
            started_at=now,
        )
    )
    claimed = ClaimedBrandIngestionJob(
        job_id=job.id,
        version_id=version.id,
        attempt_number=job.attempt_count,
        lease_token=lease_token,
        bucket=version.bucket,
        object_key=version.object_key,
        media_type=version.media_type,
        sha256=version.sha256,
        safe_filename=version.safe_filename,
    )
    await session.commit()
    return claimed


async def _heartbeat(
    session: AsyncSession, *, claimed: ClaimedBrandIngestionJob, lease_seconds: int
) -> bool:
    now = datetime.now(UTC)
    result = cast(
        CursorResult[object],
        await session.execute(
            update(BrandIngestionJobModel)
            .where(
                BrandIngestionJobModel.id == claimed.job_id,
                BrandIngestionJobModel.lease_token == claimed.lease_token,
                BrandIngestionJobModel.status == BrandIngestionJobStatus.RUNNING.value,
                BrandIngestionJobModel.lease_expires_at >= now,
            )
            .values(heartbeat_at=now, lease_expires_at=now + timedelta(seconds=lease_seconds))
        ),
    )
    if not result.rowcount:
        await session.rollback()
        return False
    await session.commit()
    return True


async def _persist_ingestion(
    session: AsyncSession,
    *,
    claimed: ClaimedBrandIngestionJob,
    parsed: ParsedBrandDocument,
    embeddings: Sequence[BrandChunkEmbedding],
) -> bool:
    now = datetime.now(UTC)
    job = await session.scalar(
        select(BrandIngestionJobModel)
        .where(
            BrandIngestionJobModel.id == claimed.job_id,
            BrandIngestionJobModel.version_id == claimed.version_id,
            BrandIngestionJobModel.lease_token == claimed.lease_token,
            BrandIngestionJobModel.status == BrandIngestionJobStatus.RUNNING.value,
            BrandIngestionJobModel.lease_expires_at >= now,
        )
        .with_for_update()
    )
    if job is None:
        await session.rollback()
        return False
    version = await session.get(BrandDocumentVersionModel, claimed.version_id)
    if version is None:
        raise RuntimeError("brand ingestion version is missing")
    if not embeddings:
        raise ValueError("brand ingestion requires at least one embedded chunk")
    for artifact in embeddings:
        if artifact.provider != version.embedding_provider:
            raise ValueError("brand embedding provider does not match the immutable version")
        if artifact.model != version.embedding_model:
            raise ValueError("brand embedding model does not match the immutable version")
        if any(not math.isfinite(value) for value in artifact.vector) or not any(artifact.vector):
            raise ValueError("brand embedding vector is invalid")
        session.add(
            BrandChunkModel(
                id=artifact.chunk.id,
                version_id=version.id,
                ordinal=artifact.chunk.ordinal,
                chunk_key=artifact.chunk.chunk_key,
                text_hash=artifact.chunk.text_hash,
                text=artifact.chunk.text,
                char_start=artifact.chunk.char_start,
                char_end=artifact.chunk.char_end,
            )
        )

    # These models intentionally have no ORM relationships. Flush the parent
    # chunk rows explicitly so SQLAlchemy cannot emit embedding inserts first.
    await session.flush()

    for artifact in embeddings:
        session.add(
            BrandChunkEmbeddingModel(
                id=uuid4(),
                chunk_id=artifact.chunk.id,
                purpose="brand_retrieval",
                provider=artifact.provider,
                model=artifact.model,
                dimensions=len(artifact.vector),
                input_hash=artifact.chunk.text_hash,
                input_version=version.embedding_input_version,
                request_fingerprint=artifact.request_fingerprint,
                provider_request_id=artifact.provider_request_id,
                vector=list(artifact.vector),
            )
        )
    provider_names = {artifact.provider for artifact in embeddings}
    model_names = {artifact.model for artifact in embeddings}
    if len(provider_names) != 1 or len(model_names) != 1:
        raise ValueError("one brand version must use one embedding provider and model")
    version.embedding_provider = next(iter(provider_names))
    version.status = BrandVersionStatus.READY.value
    version.extraction_method = parsed.extraction_method
    version.ocr_provider = parsed.ocr_provider
    version.ocr_model = parsed.ocr_model
    version.ocr_request_fingerprint = parsed.ocr_request_fingerprint
    version.ocr_provider_request_id = parsed.ocr_provider_request_id
    version.ocr_page_count = parsed.ocr_page_count
    version.ocr_prompt_tokens = parsed.ocr_prompt_tokens
    version.ocr_completion_tokens = parsed.ocr_completion_tokens
    version.ocr_latency_ms = parsed.ocr_latency_ms
    version.page_count = parsed.page_count
    version.character_count = len(parsed.text)
    version.chunk_count = len(embeddings)
    version.error_code = None
    version.completed_at = now
    job.status = BrandIngestionJobStatus.SUCCEEDED.value
    job.lease_owner = None
    job.lease_token = None
    job.lease_expires_at = None
    job.heartbeat_at = now
    job.error_code = None
    job.completed_at = now
    attempt = await session.scalar(
        select(BrandIngestionAttemptModel).where(
            BrandIngestionAttemptModel.job_id == job.id,
            BrandIngestionAttemptModel.attempt_number == claimed.attempt_number,
        )
    )
    if attempt is None:
        raise RuntimeError("brand ingestion attempt is missing")
    attempt.status = "succeeded"
    attempt.completed_at = now
    attempt.safe_metadata = {
        "page_count": parsed.page_count,
        "character_count": len(parsed.text),
        "chunk_count": len(embeddings),
        "extraction_method": parsed.extraction_method,
        "embedding_provider": version.embedding_provider,
        "embedding_model": version.embedding_model,
    }
    _add_ocr_safe_metadata(attempt.safe_metadata, parsed)
    await session.commit()
    return True


def _add_ocr_safe_metadata(metadata: dict[str, object], parsed: ParsedBrandDocument) -> None:
    fields = {
        "ocr_provider": parsed.ocr_provider,
        "ocr_model": parsed.ocr_model,
        "ocr_request_fingerprint": parsed.ocr_request_fingerprint,
        "ocr_provider_request_id": parsed.ocr_provider_request_id,
        "ocr_page_count": parsed.ocr_page_count,
        "ocr_prompt_tokens": parsed.ocr_prompt_tokens,
        "ocr_completion_tokens": parsed.ocr_completion_tokens,
        "ocr_latency_ms": parsed.ocr_latency_ms,
    }
    metadata.update({key: value for key, value in fields.items() if value is not None})


async def _fail_ingestion(
    session: AsyncSession,
    *,
    claimed: ClaimedBrandIngestionJob,
    error_code: str,
    retry_at: datetime | None,
) -> bool:
    if _SAFE_ERROR_CODE.fullmatch(error_code) is None:
        raise ValueError("brand ingestion error code must be safe snake_case")
    if retry_at is not None and retry_at.tzinfo is None:
        raise ValueError("brand ingestion retry instant must be timezone-aware")
    now = datetime.now(UTC)
    job = await session.scalar(
        select(BrandIngestionJobModel)
        .where(
            BrandIngestionJobModel.id == claimed.job_id,
            BrandIngestionJobModel.lease_token == claimed.lease_token,
            BrandIngestionJobModel.status == BrandIngestionJobStatus.RUNNING.value,
        )
        .with_for_update()
    )
    if job is None:
        await session.rollback()
        return False
    retrying = retry_at is not None
    job.status = (
        BrandIngestionJobStatus.RETRY_SCHEDULED.value
        if retrying
        else BrandIngestionJobStatus.FAILED.value
    )
    job.available_at = retry_at or now
    job.lease_owner = None
    job.lease_token = None
    job.lease_expires_at = None
    job.heartbeat_at = now
    job.error_code = error_code
    job.completed_at = None if retrying else now
    version = await session.get(BrandDocumentVersionModel, claimed.version_id)
    if version is not None:
        version.status = (
            BrandVersionStatus.QUEUED.value if retrying else BrandVersionStatus.FAILED.value
        )
        version.error_code = error_code
        version.completed_at = None if retrying else now
    attempt = await session.scalar(
        select(BrandIngestionAttemptModel).where(
            BrandIngestionAttemptModel.job_id == job.id,
            BrandIngestionAttemptModel.attempt_number == claimed.attempt_number,
        )
    )
    if attempt is not None:
        attempt.status = "retry_scheduled" if retrying else "failed"
        attempt.error_code = error_code
        attempt.completed_at = now
    await session.commit()
    return True


async def list_brand_documents(
    session: AsyncSession, *, limit: int = 100
) -> tuple[BrandDocumentProjection, ...]:
    documents = tuple(
        (
            await session.scalars(
                select(BrandDocumentModel)
                .order_by(BrandDocumentModel.updated_at.desc(), BrandDocumentModel.id)
                .limit(limit)
            )
        ).all()
    )
    return await _load_document_projections(session, documents)


async def get_brand_document(session: AsyncSession, document_id: UUID) -> BrandDocumentProjection:
    document = await session.get(BrandDocumentModel, document_id)
    if document is None:
        raise NotFoundError("brand document")
    projections = await _load_document_projections(session, (document,))
    return projections[0]


async def _load_document_projections(
    session: AsyncSession, documents: Sequence[BrandDocumentModel]
) -> tuple[BrandDocumentProjection, ...]:
    if not documents:
        return ()
    document_ids = tuple(document.id for document in documents)
    versions = tuple(
        (
            await session.scalars(
                select(BrandDocumentVersionModel)
                .where(BrandDocumentVersionModel.document_id.in_(document_ids))
                .order_by(
                    BrandDocumentVersionModel.document_id,
                    BrandDocumentVersionModel.version.desc(),
                )
            )
        ).all()
    )
    jobs = (
        tuple(
            (
                await session.scalars(
                    select(BrandIngestionJobModel).where(
                        BrandIngestionJobModel.version_id.in_(
                            tuple(version.id for version in versions)
                        )
                    )
                )
            ).all()
        )
        if versions
        else ()
    )
    versions_by_document: dict[UUID, list[BrandDocumentVersionModel]] = {
        document.id: [] for document in documents
    }
    for version in versions:
        versions_by_document[version.document_id].append(version)
    jobs_by_version = {job.version_id: job for job in jobs}
    return tuple(
        BrandDocumentProjection(
            document=document,
            versions=tuple(versions_by_document[document.id]),
            jobs_by_version=jobs_by_version,
        )
        for document in documents
    )


async def get_brand_ingestion_job(session: AsyncSession, job_id: UUID) -> BrandIngestionJobModel:
    job = await session.get(BrandIngestionJobModel, job_id)
    if job is None:
        raise NotFoundError("brand ingestion job")
    return job


async def activate_brand_version(
    session: AsyncSession, *, document_id: UUID, version_id: UUID
) -> BrandDocumentProjection:
    now = datetime.now(UTC)
    document = await session.scalar(
        select(BrandDocumentModel).where(BrandDocumentModel.id == document_id).with_for_update()
    )
    if document is None:
        raise NotFoundError("brand document")
    version = await session.scalar(
        select(BrandDocumentVersionModel)
        .where(
            BrandDocumentVersionModel.id == version_id,
            BrandDocumentVersionModel.document_id == document_id,
        )
        .with_for_update()
    )
    if version is None:
        raise NotFoundError("brand document version")
    if version.status != BrandVersionStatus.READY.value:
        raise ConflictError("only a ready brand document version can be activated")
    await session.execute(
        update(BrandDocumentVersionModel)
        .where(
            BrandDocumentVersionModel.document_id == document_id,
            BrandDocumentVersionModel.active.is_(True),
            BrandDocumentVersionModel.id != version_id,
        )
        .values(active=False, deactivated_at=now)
    )
    version.active = True
    version.activated_at = now
    version.deactivated_at = None
    document.active_version_id = version.id
    document.status = "active"
    document.updated_at = now
    await session.commit()
    return await get_brand_document(session, document_id)


async def deactivate_brand_document(
    session: AsyncSession, *, document_id: UUID
) -> BrandDocumentProjection:
    now = datetime.now(UTC)
    document = await session.scalar(
        select(BrandDocumentModel).where(BrandDocumentModel.id == document_id).with_for_update()
    )
    if document is None:
        raise NotFoundError("brand document")
    await session.execute(
        update(BrandDocumentVersionModel)
        .where(
            BrandDocumentVersionModel.document_id == document_id,
            BrandDocumentVersionModel.active.is_(True),
        )
        .values(active=False, deactivated_at=now)
    )
    document.active_version_id = None
    document.status = "inactive"
    document.updated_at = now
    await session.commit()
    return await get_brand_document(session, document_id)


async def retrieve_brand_context(
    session: AsyncSession,
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
) -> tuple[BrandRetrievalHit, ...]:
    if not query_text.strip() or len(query_text) > 2_000:
        raise ValueError("brand retrieval query must be 1-2000 characters")
    if len(query_vector) != 2048:
        raise ValueError("brand retrieval query vector must contain 2048 dimensions")
    if any(not math.isfinite(value) for value in query_vector) or not any(query_vector):
        raise ValueError("brand retrieval query vector is invalid")
    if not query_provider.strip() or not query_model.strip():
        raise ValueError("brand retrieval embedding identity must not be blank")
    if not 1 <= limit <= 10 or not limit <= candidate_limit <= 100:
        raise ValueError("brand retrieval limits are invalid")
    scope_filters = [
        BrandDocumentModel.brand_slug == "sai-xiansheng",
        BrandDocumentModel.status == "active",
        BrandDocumentModel.audience == audience.value,
        BrandDocumentModel.active_version_id == BrandDocumentVersionModel.id,
        BrandDocumentVersionModel.active.is_(True),
        BrandDocumentVersionModel.status == BrandVersionStatus.READY.value,
        BrandDocumentVersionModel.embedding_provider == query_provider,
        BrandDocumentVersionModel.embedding_model == query_model,
        BrandChunkEmbeddingModel.provider == query_provider,
        BrandChunkEmbeddingModel.model == query_model,
        or_(
            BrandDocumentVersionModel.valid_from.is_(None),
            BrandDocumentVersionModel.valid_from <= valid_on,
        ),
        or_(
            BrandDocumentVersionModel.valid_until.is_(None),
            BrandDocumentVersionModel.valid_until >= valid_on,
        ),
    ]
    if document_kinds:
        scope_filters.append(
            BrandDocumentModel.document_kind.in_([kind.value for kind in document_kinds])
        )
    columns = (
        BrandChunkModel,
        BrandDocumentModel,
        BrandDocumentVersionModel,
        BrandChunkEmbeddingModel,
    )
    joins = (
        (BrandChunkEmbeddingModel, BrandChunkEmbeddingModel.chunk_id == BrandChunkModel.id),
        (BrandDocumentVersionModel, BrandDocumentVersionModel.id == BrandChunkModel.version_id),
        (BrandDocumentModel, BrandDocumentModel.id == BrandDocumentVersionModel.document_id),
    )
    ts_query = func.websearch_to_tsquery("simple", query_text.strip())
    full_text_rank = func.ts_rank(BrandChunkModel.search_vector, ts_query)
    full_text_statement = select(*columns, full_text_rank.label("rank"))
    for target, condition in joins:
        full_text_statement = full_text_statement.join(target, condition)
    full_text_rows = tuple(
        (
            await session.execute(
                full_text_statement.where(
                    *scope_filters, BrandChunkModel.search_vector.op("@@")(ts_query)
                )
                .order_by(full_text_rank.desc(), BrandChunkModel.id)
                .limit(candidate_limit)
            )
        ).tuples()
    )
    cosine_distance = BrandChunkEmbeddingModel.vector.cosine_distance(list(query_vector))
    vector_statement = select(*columns, cosine_distance.label("distance"))
    for target, condition in joins:
        vector_statement = vector_statement.join(target, condition)
    vector_rows = tuple(
        (
            await session.execute(
                vector_statement.where(*scope_filters)
                .order_by(cosine_distance, BrandChunkModel.id)
                .limit(candidate_limit)
            )
        ).tuples()
    )
    data_by_chunk: dict[
        UUID,
        tuple[BrandChunkModel, BrandDocumentModel, BrandDocumentVersionModel],
    ] = {}
    fts_score: dict[UUID, float] = {}
    fts_rank: dict[UUID, int] = {}
    for rank, (chunk, document, version, _embedding, raw_score) in enumerate(full_text_rows, 1):
        data_by_chunk[chunk.id] = (chunk, document, version)
        fts_score[chunk.id] = max(0.0, float(raw_score))
        fts_rank[chunk.id] = rank
    vector_score: dict[UUID, float] = {}
    vector_rank: dict[UUID, int] = {}
    for rank, (chunk, document, version, _embedding, raw_distance) in enumerate(vector_rows, 1):
        data_by_chunk[chunk.id] = (chunk, document, version)
        vector_score[chunk.id] = max(-1.0, min(1.0, 1.0 - float(raw_distance)))
        vector_rank[chunk.id] = rank
    ranked_hits: list[_RankedBrandHit] = []
    for chunk_id, (chunk, document, version) in data_by_chunk.items():
        fused = 0.0
        if chunk_id in fts_rank:
            fused += _FULL_TEXT_WEIGHT / (_RRF_K + fts_rank[chunk_id])
        if chunk_id in vector_rank:
            fused += _VECTOR_WEIGHT / (_RRF_K + vector_rank[chunk_id])
        ranked_hits.append(
            _RankedBrandHit(
                ordinal=chunk.ordinal,
                hit=BrandRetrievalHit(
                    chunk_id=chunk.id,
                    document_id=document.id,
                    version_id=version.id,
                    document_title=document.title,
                    document_kind=BrandDocumentKind(document.document_kind),
                    audience=BrandAudience(document.audience),
                    text=chunk.text,
                    tone_tags=_string_tuple(version.tone_tags),
                    safety_tags=_string_tuple(version.safety_tags),
                    visual_tags=_string_tuple(version.visual_tags),
                    full_text_score=fts_score.get(chunk_id, 0.0),
                    vector_score=vector_score.get(chunk_id, 0.0),
                    fused_score=fused,
                ),
            )
        )
    return _select_diverse_brand_hits(ranked_hits, limit=limit)


def _string_tuple(values: object) -> tuple[str, ...]:
    if not isinstance(values, list):
        return ()
    return tuple(value for value in values if isinstance(value, str))
