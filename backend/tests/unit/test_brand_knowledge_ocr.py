from __future__ import annotations

from io import BytesIO
from typing import cast
from uuid import uuid4

import pytest
from app.application.ports.brand_knowledge import (
    BrandDocumentOcrRequest,
    BrandDocumentOcrResult,
    BrandEmbeddingRequest,
    BrandEmbeddingResult,
    BrandKnowledgeRepository,
    BrandOriginalStore,
)
from app.application.services.brand_knowledge import BrandIngestionExecutor
from app.core.config import Settings
from app.core.errors import BrandOcrInvalidOutputError, BrandOcrInvalidOutputReason
from app.domain.brand_knowledge import (
    BrandChunkingResult,
    BrandDocumentKind,
    BrandOcrBlockKind,
    BrandOcrLayoutBlock,
    BrandOcrLayoutPage,
    BrandSectionKind,
    ClaimedBrandIngestionJob,
    ParsedBrandDocument,
)
from app.domain.value_objects import sha256_bytes
from app.infrastructure.brand.parser import BoundedBrandDocumentParser
from pydantic import SecretStr
from pypdf import PdfWriter
from structlog.testing import capture_logs


class _Originals:
    def __init__(self, body: bytes) -> None:
        self.body = body

    async def get_immutable(self, *, bucket: str, object_key: str, sha256: str) -> bytes:
        return self.body


class _Ocr:
    def __init__(
        self,
        markdown: str = "# OCR 品牌原则\n\n保持准确与克制。",
        *,
        layout_pages: tuple[BrandOcrLayoutPage, ...] = (),
    ) -> None:
        self.requests: list[BrandDocumentOcrRequest] = []
        self.markdown = markdown
        self.layout_pages = layout_pages

    async def parse_document(self, request: BrandDocumentOcrRequest) -> BrandDocumentOcrResult:
        self.requests.append(request)
        return BrandDocumentOcrResult(
            markdown=self.markdown,
            provider="zhipu",
            model="glm-ocr",
            request_fingerprint="ocr-request-fingerprint",
            provider_request_id="provider-request-1",
            page_count=request.page_count,
            prompt_tokens=8,
            completion_tokens=12,
            latency_ms=15,
            layout_pages=self.layout_pages,
        )


class _Embeddings:
    def __init__(self) -> None:
        self.requests: list[BrandEmbeddingRequest] = []

    async def embed_brand(self, request: BrandEmbeddingRequest) -> BrandEmbeddingResult:
        self.requests.append(request)
        return BrandEmbeddingResult(
            vector=(0.1,) * 2048,
            provider="zhipu",
            model="embedding-3",
            request_fingerprint=f"embedding-{request.chunk_id}",
            provider_request_id="embedding-request-1",
        )


class _InvalidOcr:
    def __init__(self, reason: BrandOcrInvalidOutputReason) -> None:
        self.reason = reason

    async def parse_document(self, _: BrandDocumentOcrRequest) -> BrandDocumentOcrResult:
        raise BrandOcrInvalidOutputError(self.reason)


class _Repository:
    def __init__(self, claimed: ClaimedBrandIngestionJob) -> None:
        self.claimed: ClaimedBrandIngestionJob | None = claimed
        self.persisted: ParsedBrandDocument | None = None
        self.persisted_chunking: BrandChunkingResult | None = None
        self.failed: dict[str, object] | None = None

    async def claim(self, **_: object) -> ClaimedBrandIngestionJob | None:
        claimed, self.claimed = self.claimed, None
        return claimed

    async def heartbeat(self, **_: object) -> bool:
        return True

    async def persist_ingestion(
        self,
        *,
        parsed: ParsedBrandDocument,
        chunking: BrandChunkingResult,
        **_: object,
    ) -> bool:
        self.persisted = parsed
        self.persisted_chunking = chunking
        return True

    async def fail_ingestion(self, **values: object) -> bool:
        self.failed = values
        return True


def _blank_pdf() -> bytes:
    buffer = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.write(buffer)
    return buffer.getvalue()


@pytest.mark.asyncio
async def test_worker_v4_ocr_handoff_persists_page_sections_and_exact_chunks() -> None:
    body = _blank_pdf()
    claimed = ClaimedBrandIngestionJob(
        job_id=uuid4(),
        version_id=uuid4(),
        attempt_number=1,
        lease_token=uuid4(),
        bucket="private",
        object_key="brand-originals/sha256/aa/" + sha256_bytes(body),
        media_type="application/pdf",
        sha256=sha256_bytes(body),
        safe_filename="scan.pdf",
        document_title="合成扫描资料",
        document_kind=BrandDocumentKind.OTHER,
        parser_version="brand-parser-v4-layout-aware",
        chunk_version="brand-chunk-v4-layout-blocks",
        embedding_input_version="brand-embedding-input-v2-section-context",
    )
    repository = _Repository(claimed)
    layout_pages = (
        BrandOcrLayoutPage(
            page_number=1,
            blocks=(
                BrandOcrLayoutBlock(
                    ordinal=0,
                    kind=BrandOcrBlockKind.TEXT,
                    text="页面主题",
                    normalized_bbox=(0.1, 0.1, 0.5, 0.2),
                ),
                BrandOcrLayoutBlock(
                    ordinal=1,
                    kind=BrandOcrBlockKind.TEXT,
                    text="页面正文用于说明安全能力。",
                    normalized_bbox=(0.1, 0.24, 0.5, 0.4),
                ),
            ),
        ),
    )
    ocr = _Ocr(layout_pages=layout_pages)
    embeddings = _Embeddings()
    settings = Settings(
        content_enabled=True,
        ai_provider_mode="zhipu",
        ai_platform_base_url="https://open.bigmodel.invalid/api/paas/v4",
        ai_platform_api_key=SecretStr("local-test-key"),
        brand_ocr_sparse_text_threshold=40,
    )
    executor = BrandIngestionExecutor(
        repository=cast(BrandKnowledgeRepository, repository),
        originals=cast(BrandOriginalStore, _Originals(body)),
        parser=BoundedBrandDocumentParser(
            max_pages=20,
            max_characters=20_000,
            max_chunks=50,
            chunk_characters=300,
            overlap_characters=20,
            parser_version=settings.brand_parser_version,
            chunk_version=settings.brand_chunk_version,
            embedding_input_version=settings.brand_embedding_input_version,
            sparse_text_threshold=settings.brand_ocr_sparse_text_threshold,
        ),
        embeddings=embeddings,
        ocr=ocr,
        settings=settings,
    )

    assert await executor.execute_next("ocr-worker") is True
    assert ocr.requests[0].require_layout is True
    assert repository.persisted is not None
    assert repository.persisted_chunking is not None
    assert repository.persisted.sections[0].kind == BrandSectionKind.PAGE
    assert repository.persisted.sections[0].source_page == 1
    assert len(repository.persisted_chunking.sections) == 1
    assert all(
        repository.persisted.text[chunk.char_start : chunk.char_end] == chunk.text
        for chunk in repository.persisted_chunking
    )


@pytest.mark.asyncio
async def test_worker_ocr_handoff_stays_outside_parser_and_persists_safe_metadata() -> None:
    body = _blank_pdf()
    claimed = ClaimedBrandIngestionJob(
        job_id=uuid4(),
        version_id=uuid4(),
        attempt_number=1,
        lease_token=uuid4(),
        bucket="private",
        object_key="brand-originals/sha256/aa/" + sha256_bytes(body),
        media_type="application/pdf",
        sha256=sha256_bytes(body),
        safe_filename="scan.pdf",
        document_title="扫描品牌资料",
        document_kind=BrandDocumentKind.OTHER,
        parser_version="brand-parser-v3-source-structure",
        chunk_version="brand-chunk-v3-parent-child",
        embedding_input_version="brand-embedding-input-v2-section-context",
    )
    repository = _Repository(claimed)
    ocr = _Ocr()
    embeddings = _Embeddings()
    settings = Settings(
        content_enabled=True,
        ai_provider_mode="zhipu",
        ai_platform_base_url="https://open.bigmodel.invalid/api/paas/v4",
        ai_platform_api_key=SecretStr("local-test-key"),
        brand_parser_version="brand-parser-v3-source-structure",
        brand_chunk_version="brand-chunk-v3-parent-child",
        brand_embedding_input_version="brand-embedding-input-v2-section-context",
        brand_ocr_sparse_text_threshold=40,
    )
    executor = BrandIngestionExecutor(
        repository=cast(BrandKnowledgeRepository, repository),
        originals=cast(BrandOriginalStore, _Originals(body)),
        parser=BoundedBrandDocumentParser(
            max_pages=20,
            max_characters=20_000,
            max_chunks=50,
            chunk_characters=120,
            overlap_characters=20,
            parser_version=settings.brand_parser_version,
            chunk_version=settings.brand_chunk_version,
            embedding_input_version=settings.brand_embedding_input_version,
            sparse_text_threshold=settings.brand_ocr_sparse_text_threshold,
        ),
        embeddings=embeddings,
        ocr=ocr,
        settings=settings,
    )

    assert await executor.execute_next("ocr-worker") is True
    assert len(ocr.requests) == 1
    assert ocr.requests[0].require_layout is False
    assert repository.persisted is not None
    assert repository.persisted.extraction_method == "ocr"
    assert repository.persisted.ocr_provider == "zhipu"
    assert repository.persisted.ocr_model == "glm-ocr"
    assert repository.persisted.ocr_prompt_tokens == 8
    assert repository.persisted.ocr_completion_tokens == 12
    assert repository.persisted.ocr_latency_ms == 15
    assert embeddings.requests
    assert all("文档\uff1a扫描品牌资料" in request.text for request in embeddings.requests)
    assert all(
        request.input_hash == sha256_bytes(request.text.encode()) for request in embeddings.requests
    )


@pytest.mark.asyncio
async def test_worker_ocr_handoff_coalesces_pathological_generic_markdown() -> None:
    body = _blank_pdf()
    claimed = ClaimedBrandIngestionJob(
        job_id=uuid4(),
        version_id=uuid4(),
        attempt_number=1,
        lease_token=uuid4(),
        bucket="private",
        object_key="brand-originals/sha256/aa/" + sha256_bytes(body),
        media_type="application/pdf",
        sha256=sha256_bytes(body),
        safe_filename="scan.pdf",
        document_title="合成扫描资料",
        document_kind=BrandDocumentKind.OTHER,
        parser_version="brand-parser-v3-source-structure",
        chunk_version="brand-chunk-v3-parent-child",
        embedding_input_version="brand-embedding-input-v2-section-context",
    )
    repository = _Repository(claimed)
    ocr = _Ocr("\n\n".join(f"合成微块 {index:04d}。" for index in range(701)))
    embeddings = _Embeddings()
    settings = Settings(
        content_enabled=True,
        ai_provider_mode="zhipu",
        ai_platform_base_url="https://open.bigmodel.invalid/api/paas/v4",
        ai_platform_api_key=SecretStr("local-test-key"),
        brand_parser_version="brand-parser-v3-source-structure",
        brand_chunk_version="brand-chunk-v3-parent-child",
        brand_embedding_input_version="brand-embedding-input-v2-section-context",
        brand_ocr_sparse_text_threshold=40,
    )
    executor = BrandIngestionExecutor(
        repository=cast(BrandKnowledgeRepository, repository),
        originals=cast(BrandOriginalStore, _Originals(body)),
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
        embeddings=embeddings,
        ocr=ocr,
        settings=settings,
    )

    assert await executor.execute_next("ocr-worker") is True
    assert len(ocr.requests) == 1
    assert repository.persisted is not None
    assert repository.persisted_chunking is not None
    assert len(repository.persisted_chunking.chunks) < settings.brand_parse_max_chunks
    assert len(embeddings.requests) == len(repository.persisted_chunking.chunks)
    assert all(
        repository.persisted.text[chunk.char_start : chunk.char_end] == chunk.text
        for chunk in repository.persisted_chunking
    )


@pytest.mark.parametrize(
    "reason",
    (
        BrandOcrInvalidOutputReason.LAYOUT_NATIVE_LABEL_TYPE_INVALID,
        BrandOcrInvalidOutputReason.LAYOUT_NATIVE_LABEL_LIMIT_EXCEEDED,
        BrandOcrInvalidOutputReason.LAYOUT_NATIVE_LABEL_UNKNOWN,
        BrandOcrInvalidOutputReason.LAYOUT_NATIVE_LABEL_CONFLICT,
    ),
)
@pytest.mark.asyncio
async def test_worker_persists_only_allowlisted_brand_ocr_diagnostic_reason(
    reason: BrandOcrInvalidOutputReason,
) -> None:
    body = _blank_pdf()
    claimed = ClaimedBrandIngestionJob(
        job_id=uuid4(),
        version_id=uuid4(),
        attempt_number=1,
        lease_token=uuid4(),
        bucket="private",
        object_key="brand-originals/sha256/aa/" + sha256_bytes(body),
        media_type="application/pdf",
        sha256=sha256_bytes(body),
        safe_filename="scan.pdf",
        document_title="合成扫描资料",
        document_kind=BrandDocumentKind.OTHER,
        parser_version="brand-parser-v4-layout-aware",
        chunk_version="brand-chunk-v4-layout-blocks",
        embedding_input_version="brand-embedding-input-v2-section-context",
    )
    repository = _Repository(claimed)
    embeddings = _Embeddings()
    settings = Settings(
        content_enabled=True,
        ai_provider_mode="zhipu",
        ai_platform_base_url="https://open.bigmodel.invalid/api/paas/v4",
        ai_platform_api_key=SecretStr("local-test-key"),
        brand_ocr_sparse_text_threshold=40,
    )
    executor = BrandIngestionExecutor(
        repository=cast(BrandKnowledgeRepository, repository),
        originals=cast(BrandOriginalStore, _Originals(body)),
        parser=BoundedBrandDocumentParser(
            max_pages=20,
            max_characters=20_000,
            max_chunks=50,
            chunk_characters=300,
            overlap_characters=20,
            parser_version=settings.brand_parser_version,
            chunk_version=settings.brand_chunk_version,
            embedding_input_version=settings.brand_embedding_input_version,
            sparse_text_threshold=settings.brand_ocr_sparse_text_threshold,
        ),
        embeddings=embeddings,
        ocr=_InvalidOcr(reason),
        settings=settings,
    )

    with capture_logs() as logs:
        assert await executor.execute_next("ocr-diagnostic-worker") is True
    assert repository.persisted is None
    assert repository.failed is not None
    assert repository.failed["error_code"] == "brand_ocr_invalid_output"
    assert repository.failed["diagnostic_reason"] == reason.value
    assert embeddings.requests == []
    failure_log = next(log for log in logs if log["event"] == "brand_ingestion_failed")
    assert failure_log["error_code"] == "brand_ocr_invalid_output"
    assert failure_log["diagnostic_reason"] == reason.value
    assert "合成扫描资料" not in repr(logs)
    assert "scan.pdf" not in repr(logs)
