from __future__ import annotations

import asyncio
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

import structlog

from app.application.ports.brand_knowledge import (
    BrandDocumentParser,
    BrandEmbeddingModel,
    BrandEmbeddingRequest,
    BrandKnowledgeRepository,
    BrandOriginalStore,
)
from app.core.config import Settings
from app.core.errors import AppError, BrandIngestionLeaseLostError
from app.domain.brand_knowledge import (
    BrandAudience,
    BrandChunkEmbedding,
    BrandDocumentKind,
    BrandRetrievalHit,
    ClaimedBrandIngestionJob,
)
from app.domain.value_objects import sha256_bytes, stable_key

logger = structlog.get_logger()


class BrandIngestionExecutor:
    def __init__(
        self,
        *,
        repository: BrandKnowledgeRepository,
        originals: BrandOriginalStore,
        parser: BrandDocumentParser,
        embeddings: BrandEmbeddingModel,
        settings: Settings,
    ) -> None:
        self._repository = repository
        self._originals = originals
        self._parser = parser
        self._embeddings = embeddings
        self._settings = settings

    async def execute_next(self, worker_id: str) -> bool:
        claimed = await self._repository.claim(
            worker_id=worker_id,
            lease_seconds=self._settings.content_lease_seconds,
            max_attempts=self._settings.content_max_attempts,
            embedding_provider=self._settings.ai_provider_mode,
            embedding_model=self._settings.ai_embedding_model,
        )
        if claimed is None:
            return False
        heartbeat_stop = asyncio.Event()
        heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(claimed=claimed, stop=heartbeat_stop)
        )
        try:
            body = await self._originals.get_immutable(
                bucket=claimed.bucket,
                object_key=claimed.object_key,
                sha256=claimed.sha256,
            )
            parsed = await asyncio.to_thread(
                self._parser.parse,
                body=body,
                media_type=claimed.media_type,
            )
            chunks = self._parser.chunk(version_id=claimed.version_id, document=parsed)
            artifacts: list[BrandChunkEmbedding] = []
            for chunk in chunks:
                if heartbeat_task.done():
                    heartbeat_task.result()
                result = await self._embeddings.embed_brand(
                    BrandEmbeddingRequest(
                        chunk_id=chunk.id,
                        input_hash=chunk.text_hash,
                        text=chunk.text,
                    )
                )
                if heartbeat_task.done():
                    heartbeat_task.result()
                artifacts.append(
                    BrandChunkEmbedding(
                        chunk=chunk,
                        vector=result.vector,
                        provider=result.provider,
                        model=result.model,
                        request_fingerprint=result.request_fingerprint,
                        provider_request_id=result.provider_request_id,
                    )
                )
            if heartbeat_task.done():
                heartbeat_task.result()
            persisted = await self._repository.persist_ingestion(
                claimed=claimed,
                parsed=parsed,
                embeddings=artifacts,
            )
            if not persisted:
                raise BrandIngestionLeaseLostError()
            logger.info(
                "brand_ingestion_succeeded",
                job_id=str(claimed.job_id),
                version_id=str(claimed.version_id),
                attempt=claimed.attempt_number,
                page_count=parsed.page_count,
                character_count=len(parsed.text),
                chunk_count=len(artifacts),
                embedding_provider=artifacts[0].provider,
                embedding_model=artifacts[0].model,
            )
        except asyncio.CancelledError:
            raise
        except AppError as error:
            await self._record_failure(
                claimed=claimed,
                error_code=error.code,
                retryable=error.retryable,
            )
        except Exception as error:
            logger.warning(
                "brand_ingestion_internal_failure",
                job_id=str(claimed.job_id),
                version_id=str(claimed.version_id),
                exception_type=type(error).__name__,
                constraint_name=_safe_constraint_name(error),
                sqlstate=_safe_sqlstate(error),
            )
            await self._record_failure(
                claimed=claimed,
                error_code="brand_ingestion_internal_error",
                retryable=False,
            )
        finally:
            heartbeat_stop.set()
            await asyncio.gather(heartbeat_task, return_exceptions=True)
        return True

    async def _heartbeat_loop(
        self, *, claimed: ClaimedBrandIngestionJob, stop: asyncio.Event
    ) -> None:
        while not stop.is_set():
            try:
                await asyncio.wait_for(
                    stop.wait(), timeout=self._settings.content_heartbeat_seconds
                )
            except TimeoutError:
                renewed = await self._repository.heartbeat(
                    claimed=claimed,
                    lease_seconds=self._settings.content_lease_seconds,
                )
                if not renewed:
                    raise BrandIngestionLeaseLostError() from None

    async def _record_failure(
        self, *, claimed: ClaimedBrandIngestionJob, error_code: str, retryable: bool
    ) -> None:
        can_retry = retryable and claimed.attempt_number < self._settings.content_max_attempts
        retry_at = (
            datetime.now(UTC) + timedelta(seconds=min(30 * 2 ** (claimed.attempt_number - 1), 300))
            if can_retry
            else None
        )
        await self._repository.fail_ingestion(
            claimed=claimed,
            error_code=error_code,
            retry_at=retry_at,
        )
        logger.warning(
            "brand_ingestion_failed",
            job_id=str(claimed.job_id),
            version_id=str(claimed.version_id),
            attempt=claimed.attempt_number,
            error_code=error_code,
            retry_scheduled=can_retry,
        )


async def retrieve_brand_context(
    *,
    repository: BrandKnowledgeRepository,
    embeddings: BrandEmbeddingModel,
    query: str,
    audience: BrandAudience,
    document_kinds: tuple[BrandDocumentKind, ...],
    valid_on: date,
    limit: int,
) -> tuple[BrandRetrievalHit, ...]:
    normalized_query = query.strip()
    if not normalized_query or len(normalized_query) > 2_000:
        raise ValueError("brand retrieval query must be 1-2000 characters")
    query_hash = sha256_bytes(normalized_query.encode("utf-8"))
    query_id = UUID(stable_key("brand-retrieval-query", query_hash)[:32])
    vector = await embeddings.embed_brand(
        BrandEmbeddingRequest(
            chunk_id=query_id,
            input_hash=query_hash,
            text=normalized_query,
        )
    )
    return await repository.retrieve(
        query_text=normalized_query,
        query_vector=vector.vector,
        query_provider=vector.provider,
        query_model=vector.model,
        audience=audience,
        document_kinds=document_kinds,
        valid_on=valid_on,
        limit=limit,
        candidate_limit=max(limit * 4, 20),
    )


def _safe_constraint_name(error: Exception) -> str | None:
    current: object | None = error
    for _ in range(4):
        original = getattr(current, "orig", None)
        cause = getattr(current, "__cause__", None)
        current = original or cause
        if current is None:
            return None
        diagnostic = getattr(current, "diag", None)
        value = getattr(diagnostic, "constraint_name", None) or getattr(
            current, "constraint_name", None
        )
        if isinstance(value, str) and value.replace("_", "").isalnum():
            return value[:120]
    return None


def _safe_sqlstate(error: Exception) -> str | None:
    current: object | None = error
    for _ in range(4):
        current = getattr(current, "orig", None) or getattr(current, "__cause__", None)
        if current is None:
            return None
        value = getattr(current, "sqlstate", None)
        if isinstance(value, str) and value.isalnum():
            return value[:10]
    return None
