# Validation Record

Date: 2026-08-03

This record intentionally contains metadata and bounded counts only. It does not include brand
document text, OCR output, provider payloads, credentials, or object-storage URLs.

## Supplied materials

| Material | Active version | Status | Extraction | Pages | Characters | Chunks | OCR provider/model |
|---|---:|---|---|---:|---:|---:|---|
| 小赛 AI 星球平台介绍 | 3 | ready/active | local | 48 | 2,496 | 4 | n/a |
| 赛先生品牌与产品介绍 | 4 | ready/active | ocr | 50 | 32,921 | 44 | zhipu / glm-ocr |
| 郭郭儿童发展计划 · 创始人访谈 | 2 | ready/active | local | n/a | 6,499 | 9 | n/a |

The DOCX used the local parser and did not call GLM-OCR. The sparse PDF used the worker OCR path;
the OCR result was normalized, chunked, embedded, and activated through the existing versioned
brand pipeline. Visual assets remain outside text RAG.

## Retrieval and runtime checks

- Brand-context retrieval returned 5 bounded hits across the 3 supplied document sources with
  `evidence_eligible=false`.
- PostgreSQL/pgvector and MinIO were healthy; Alembic was at `20260803_0014`.
- Acquisition API, acquisition scheduler/worker, governance scheduler/worker, and content
  scheduler/worker were running during verification.
- No raw document text, OCR response, authorization header, API key, or signed object URL was
  emitted in the verification record or application logs.
