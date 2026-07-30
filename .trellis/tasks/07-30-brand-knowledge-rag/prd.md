# Brand Knowledge Ingestion and RAG

## Goal

Allow an internal administrator to upload and activate versioned 赛先生 brand knowledge, then
provide bounded parent-targeted brand context to the internal WeChat Moments copy-generation
pipeline without mixing it with factual evidence. This is not a parent-facing search product.

## Parent and Dependency

- Parent: `07-30-content-production-mvp`.
- Consumes the selected-topic/evidence query contract from `07-30-daily-topic-selection` for live
  retrieval evaluation.
- Produces typed brand context for `07-30-copy-generation-audit`.

## Requirements

- Support bounded PDF, DOCX, UTF-8 TXT, and Markdown upload unless parser research documents a safe
  narrower set.
- Validate file signature/type/size/pages/text, sanitize filenames/keys, and store private originals
  in MinIO.
- Persist logical documents, immutable versions, metadata, validity, audience, checksum, parser/
  chunk/embed versions, ingestion jobs/attempts, chunks, and embeddings.
- Parse and chunk deterministically with stable IDs/hashes/offsets.
- Embed active chunks through the application-owned port using fixed validated dimensions.
- Retrieve through filtered PostgreSQL full-text plus pgvector search and deterministic rank fusion.
- Return explainable chunk/document/version/score metadata through a brand-specific typed API for
  copy-generation consumption and internal diagnostics.
- Support activate/deactivate and re-index without mutating or deleting history.

## Acceptance Criteria

- [ ] An internal user can upload a supported document and observe durable ingestion status.
- [ ] Re-upload/replay is idempotent; a changed file/version creates new immutable artifacts.
- [ ] Active/valid `parents` target-audience filtering works before generation-context retrieval.
- [ ] Controlled generation-intent queries return expected brand rules/examples and exclude
      inactive/wrong-audience chunks.
- [ ] Product wording and API documentation identify retrieval as internal copy-generation context,
      never a parent-facing search service.
- [ ] Brand chunks cannot satisfy an external fact evidence binding at type, service, or DB level.
- [ ] A bounded live evaluation on supplied documents records representative retrieval quality.
- [ ] Malformed/excessive/encrypted files fail safely without leaking corpus content or credentials.

## External Input

Brand positioning, values, parent communication guidance, approved examples, prohibited language,
safety/compliance rules, and visual guidance are required before live acceptance.

The first supplied corpus contains two slide-deck PDFs and 26 visual assets. It is sufficient for
initial positioning/product context, but approved/rejected Moments examples, an explicit prohibited-
language policy, externally verified public achievements/data, and canonical logo/color/font files
remain missing inputs for generation-quality acceptance.

## Out of Scope

- Multiple brands/tenants, public uploads, collaborative editing, OCR-heavy scanned archives,
  external vector/search services, parent-facing search, or brand content as factual proof.
