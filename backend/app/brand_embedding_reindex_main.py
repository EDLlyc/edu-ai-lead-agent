"""Development-only bootstrap for rebuilding active brand RAG in Alibaba's vector space."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

import httpx
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.services.brand_knowledge import BrandIngestionExecutor
from app.core.config import Settings, get_settings
from app.domain.brand_knowledge import (
    BrandAudience,
    BrandDocumentKind,
    BrandOriginalDescriptor,
    BrandUploadMetadata,
    BrandVersionStatus,
    ValidatedBrandUpload,
)
from app.infrastructure.ai.factory import (
    create_brand_embedding_model,
    create_brand_ocr_model,
)
from app.infrastructure.brand.parser import BoundedBrandDocumentParser
from app.infrastructure.db.brand_knowledge import (
    BrandDocumentProjection,
    PostgresBrandKnowledgeRepository,
    activate_brand_version,
    list_brand_documents,
)
from app.infrastructure.db.models import BrandDocumentVersionModel
from app.infrastructure.db.session import create_engine, create_session_factory
from app.infrastructure.storage.minio_brand_store import MinioBrandOriginalStore

_PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True, slots=True)
class _ReindexPlan:
    source_documents: int
    already_ready: int
    needs_enqueue: int


def _active_version(projection: BrandDocumentProjection) -> BrandDocumentVersionModel | None:
    active_id = projection.document.active_version_id
    if active_id is None:
        return None
    return next((version for version in projection.versions if version.id == active_id), None)


def _matching_target(
    projection: BrandDocumentProjection,
    source: BrandDocumentVersionModel,
    settings: Settings,
) -> BrandDocumentVersionModel | None:
    matches = (
        version
        for version in projection.versions
        if version.sha256 == source.sha256
        and version.metadata_fingerprint == source.metadata_fingerprint
        and version.parser_version == settings.brand_parser_version
        and version.chunk_version == settings.brand_chunk_version
        and version.embedding_input_version == settings.brand_embedding_input_version
        and version.embedding_provider == settings.brand_embedding_provider
        and version.embedding_model == settings.brand_embedding_model
        and version.status != BrandVersionStatus.FAILED.value
    )
    return max(matches, key=lambda version: version.version, default=None)


async def _load_projections(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[BrandDocumentProjection, ...]:
    async with session_factory() as session:
        return await list_brand_documents(session)


def _selected_source_projections(
    projections: tuple[BrandDocumentProjection, ...],
    document_ids: frozenset[UUID] | None,
) -> tuple[BrandDocumentProjection, ...]:
    """Select immutable ready sources without relying on private titles or object paths."""

    if document_ids is None:
        candidates = projections
    else:
        by_document_id = {projection.document.id: projection for projection in projections}
        missing_ids = document_ids.difference(by_document_id)
        if missing_ids:
            raise RuntimeError("one or more selected brand document IDs do not exist")
        candidates = tuple(
            by_document_id[document_id] for document_id in sorted(document_ids, key=str)
        )

    selected: list[BrandDocumentProjection] = []
    for projection in candidates:
        source = _active_version(projection)
        if source is None or source.status != BrandVersionStatus.READY.value:
            if document_ids is not None:
                raise RuntimeError(
                    "every selected brand document must have an active ready version"
                )
            continue
        if document_ids is not None and source.media_type != "application/pdf":
            raise RuntimeError("scoped brand layout reindex accepts only PDF documents")
        selected.append(projection)
    return tuple(selected)


async def _load_selected_source_projections(
    session_factory: async_sessionmaker[AsyncSession],
    document_ids: frozenset[UUID] | None,
) -> tuple[BrandDocumentProjection, ...]:
    return _selected_source_projections(await _load_projections(session_factory), document_ids)


async def _plan(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    document_ids: frozenset[UUID] | None = None,
) -> _ReindexPlan:
    projections = await _load_selected_source_projections(session_factory, document_ids)
    source_documents = 0
    already_ready = 0
    needs_enqueue = 0
    for projection in projections:
        source = _active_version(projection)
        if source is None:
            raise AssertionError("selected source projections must have an active version")
        source_documents += 1
        target = _matching_target(projection, source, settings)
        if target is not None and target.status == BrandVersionStatus.READY.value:
            already_ready += 1
        elif target is None:
            needs_enqueue += 1
    return _ReindexPlan(source_documents, already_ready, needs_enqueue)


async def _enqueue(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    document_ids: frozenset[UUID] | None = None,
) -> int:
    repository = PostgresBrandKnowledgeRepository(session_factory)
    created = 0
    for projection in await _load_selected_source_projections(session_factory, document_ids):
        source = _active_version(projection)
        if source is None:
            raise AssertionError("selected source projections must have an active version")
        if _matching_target(projection, source, settings) is not None:
            continue
        metadata = BrandUploadMetadata(
            brand_slug=projection.document.brand_slug,
            title=projection.document.title,
            document_kind=BrandDocumentKind(projection.document.document_kind),
            audience=BrandAudience(projection.document.audience),
            language=projection.document.language,
            valid_from=source.valid_from,
            valid_until=source.valid_until,
            tone_tags=tuple(source.tone_tags),
            safety_tags=tuple(source.safety_tags),
            visual_tags=tuple(source.visual_tags),
        )
        _, _, _, was_created = await repository.create_upload(
            metadata=metadata,
            upload=ValidatedBrandUpload(
                safe_filename=source.safe_filename,
                media_type=source.media_type,
                body=b"",
                sha256=source.sha256,
            ),
            original=BrandOriginalDescriptor(
                bucket=source.bucket,
                object_key=source.object_key,
                media_type=source.media_type,
                byte_size=source.byte_size,
                sha256=source.sha256,
            ),
            parser_version=settings.brand_parser_version,
            chunk_version=settings.brand_chunk_version,
            embedding_input_version=settings.brand_embedding_input_version,
            embedding_provider=settings.brand_embedding_provider,
            embedding_model=settings.brand_embedding_model,
            dimensions=settings.brand_embedding_dimensions,
        )
        created += int(was_created)
    return created


async def _process(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    client: httpx.AsyncClient,
    document_ids: frozenset[UUID] | None = None,
) -> int:
    projections = await _load_selected_source_projections(session_factory, document_ids)
    claim_version_ids = frozenset(
        target.id
        for projection in projections
        if (source := _active_version(projection)) is not None
        if (target := _matching_target(projection, source, settings)) is not None
        if target.status != BrandVersionStatus.READY.value
    )
    if not claim_version_ids:
        return 0
    executor = BrandIngestionExecutor(
        repository=PostgresBrandKnowledgeRepository(
            session_factory,
            claim_version_ids=claim_version_ids,
        ),
        originals=MinioBrandOriginalStore(settings),
        parser=BoundedBrandDocumentParser(
            max_pages=settings.brand_parse_max_pages,
            max_characters=settings.brand_parse_max_characters,
            max_chunks=settings.brand_parse_max_chunks,
            chunk_characters=settings.brand_chunk_characters,
            overlap_characters=settings.brand_chunk_overlap_characters,
            parser_version=settings.brand_parser_version,
            chunk_version=settings.brand_chunk_version,
            embedding_input_version=settings.brand_embedding_input_version,
            sparse_text_threshold=settings.brand_ocr_sparse_text_threshold,
        ),
        embeddings=create_brand_embedding_model(settings, client=client),
        ocr=(
            create_brand_ocr_model(settings, client=client)
            if settings.ai_provider_mode == "zhipu"
            else None
        ),
        settings=settings,
    )
    processed = 0
    worker_id = f"brand-alibaba-reindex:{uuid4()}"
    while await executor.execute_next(worker_id):
        processed += 1
    return processed


async def _activate_ready(
    session_factory: async_sessionmaker[AsyncSession],
    settings: Settings,
    document_ids: frozenset[UUID] | None = None,
) -> int:
    activated = 0
    for projection in await _load_selected_source_projections(session_factory, document_ids):
        source = _active_version(projection)
        if source is None:
            continue
        target = _matching_target(projection, source, settings)
        if target is None or target.status != BrandVersionStatus.READY.value:
            continue
        if source.id == target.id:
            continue
        async with session_factory() as session:
            await activate_brand_version(
                session,
                document_id=projection.document.id,
                version_id=target.id,
            )
        activated += 1
    return activated


async def _run(
    action: str,
    *,
    execute: bool,
    document_ids: frozenset[UUID] | None = None,
) -> None:
    settings = get_settings()
    if settings.app_env != "development":
        raise RuntimeError("brand embedding reindex is development-only")
    if settings.resolved_brand_embedding_provider_mode != "alibaba":
        raise RuntimeError("brand embedding reindex requires Alibaba multimodal embedding")
    if action != "plan" and not execute:
        raise RuntimeError("mutating brand embedding reindex actions require --execute")
    if action != "plan" and not document_ids:
        raise RuntimeError("mutating brand embedding reindex actions require --document-id")

    engine = create_engine(settings)
    session_factory = create_session_factory(engine)
    try:
        before = await _plan(session_factory, settings, document_ids)
        created = 0
        processed = 0
        activated = 0
        if action in {"enqueue", "migrate"}:
            created = await _enqueue(session_factory, settings, document_ids)
        if action == "migrate":
            async with httpx.AsyncClient(follow_redirects=False) as client:
                processed = await _process(session_factory, settings, client, document_ids)
            activated = await _activate_ready(session_factory, settings, document_ids)
        elif action == "activate-ready":
            activated = await _activate_ready(session_factory, settings, document_ids)
        after = await _plan(session_factory, settings, document_ids)
        print(
            json.dumps(
                {
                    "action": action,
                    "target_provider": settings.brand_embedding_provider,
                    "target_model": settings.brand_embedding_model,
                    "selected_document_count": len(document_ids) if document_ids else None,
                    "source_documents": before.source_documents,
                    "already_ready_before": before.already_ready,
                    "needs_enqueue_before": before.needs_enqueue,
                    "created": created,
                    "processed": processed,
                    "activated": activated,
                    "already_ready_after": after.already_ready,
                    "needs_enqueue_after": after.needs_enqueue,
                },
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            )
        )
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "action",
        choices=("plan", "enqueue", "activate-ready", "migrate"),
        default="plan",
        nargs="?",
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument(
        "--document-id",
        action="append",
        default=[],
        type=UUID,
        help="repeat for each explicitly approved brand document UUID",
    )
    args = parser.parse_args()
    os.chdir(_PROJECT_ROOT)
    asyncio.run(
        _run(
            args.action,
            execute=args.execute,
            document_ids=frozenset(args.document_id) if args.document_id else None,
        )
    )


if __name__ == "__main__":
    main()
