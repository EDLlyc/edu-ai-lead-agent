# Design: Brand Knowledge Ingestion and RAG

## Boundary

Create a private, versioned brand corpus for 赛先生 and Chinese-parent communication. Brand data
guides expression and visual direction but is structurally incapable of proving an external fact.

## Data Flow

```text
internal multipart upload
  -> validate/signature/checksum -> private MinIO original
  -> durable ingestion job
  -> bounded parse -> deterministic normalize/chunk
  -> embedding-3 brand_retrieval vectors
  -> activate document version

selected topic query
  -> metadata filters
  -> PostgreSQL full-text + pgvector candidates
  -> deterministic rank fusion
  -> bounded typed BrandContextResult
```

## Document Contract

- Logical document identity is stable; versions are immutable by checksum/parser/chunk/embed bundle.
- Initial formats target PDF, DOCX, TXT, and Markdown after compatibility/security research.
- Metadata includes brand, audience, document kind, validity, status, language, safety/tone/visual
  tags, filename, checksum, original object identity, and version bundle.
- Original files and parsed/chunk text are private. List APIs expose metadata/diagnostics, not full
  private bodies by default.

## Security and Parsing

Validate magic/MIME/extension agreement, filename, size, page/character/chunk counts, compression,
encryption, and parser timeout. No macros, remote resources, embedded object execution, OCR network
calls, or arbitrary archive expansion. Parsing occurs outside API transactions and processes.

## Retrieval Contract

Evidence and brand use separate tables, embedding purposes, ports, result schemas, and prompt
sections. Apply active brand/audience/valid-at/kind/safety filters before ranking. Use PostgreSQL
`ts_rank` plus pgvector cosine distance and a versioned deterministic fusion rule. Return bounded
chunk text with IDs, document/version, component/fused scores, and tags.

## API and UI

- Upload -> 202 document version + ingestion job/status URL.
- List/detail/version/status and activate/deactivate endpoints.
- Internal retrieval endpoint is bounded and intended for system evaluation/debugging, not public
  arbitrary semantic search.
- Minimal upload/status UI may land here; final product navigation/visual polish lands in Child 4.

## Rollout

Deploy disabled, verify parsers/fake embeddings, ingest supplied documents, inspect chunks privately,
evaluate queries, then activate accepted versions. Rollback deactivates versions/ingestion while
preserving originals/history.
