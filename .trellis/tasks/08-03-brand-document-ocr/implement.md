# Implementation Plan: GLM-OCR brand ingestion

## Phase 1 - Contracts and settings

- [x] Add OCR request/result and parser extraction metadata types.
- [x] Add bounded OCR settings and bump the brand parser version.
- [x] Add typed provider errors for OCR input/output, rate limit, timeout, and identity failures.

## Phase 2 - Parser and provider

- [x] Extend the bounded parser with local coverage detection and a sparse-PDF OCR-needed result.
- [x] Add the provider-neutral OCR port and Zhipu GLM-OCR `layout_parsing` adapter.
- [x] Reuse the existing bounded Zhipu HTTP transport and validate Markdown/layout response data.
- [x] Add unit/contract tests for local fast path, sparse PDF fallback, base64 bounds, response
      validation, retries, and secret/raw-content redaction.

## Phase 3 - Worker and persistence

- [x] Wire OCR into `BrandIngestionExecutor` outside the transaction and under the existing lease.
- [x] Persist extraction/OCR metadata and safe attempt summaries through an Alembic migration.
- [x] Preserve existing deterministic chunking, embedding, activation, and idempotency behavior.
- [x] Add repository/integration tests for migration defaults, retry/lease recovery, OCR metadata,
      and duplicate derivation prevention.

## Phase 4 - Real supplied documents

- [x] Rebuild/recreate content services with Zhipu mode and verify no secrets in startup output.
- [x] Upload both PDFs and the authorized founder-interview DOCX from
      `private/brand-materials/01-brand-profile/` through the existing API.
- [x] Poll durable jobs; record only IDs, statuses, extraction method, page/character/chunk counts,
      and safe provider metadata.
- [x] Confirm the DOCX uses local parsing and the PDFs use GLM-OCR when sparse, then activate only
      ready versions and verify brand-context retrieval plus copy-job progression.

## Phase 5 - Verification

- [x] Run focused OCR/parser/provider/worker tests.
- [x] Upgrade brand chunking to `brand-chunk-v2-structure-aware`: prefer paragraph/Markdown,
      sentence, and line boundaries while preserving deterministic offsets and bounded overlap.
- [x] Upgrade post-RRF brand retrieval selection to preserve ranked order while avoiding repeated
      text, adjacent chunks, and excessive same-document results, with deterministic fallbacks.
- [x] Run backend lint, strict mypy, migration/integration checks, `make doctor`, Compose validation,
      OpenAPI/client contract checks, and `git diff --check`.
- [x] Review the diff for secrets, raw OCR logging, public file URLs, and auto-publish paths.

## Validation commands

```bash
conda run --name edu-ai pytest backend/tests/unit/test_brand_knowledge.py backend/tests/unit/test_brand_knowledge_ocr.py -q
conda run --name edu-ai pytest backend/tests/contract/test_zhipu_ocr.py backend/tests/integration/test_brand_knowledge_rag.py -q
make backend-check
make doctor
docker compose --profile content --profile governance config --quiet
git diff --check
```

## Rollback

Before migration, disable content worker OCR and redeploy the prior image. After migration, keep
the forward-compatible columns, disable OCR/brand ingestion, preserve originals and prior ready
versions, and do not downgrade or delete brand data.
