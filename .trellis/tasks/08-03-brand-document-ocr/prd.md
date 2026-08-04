# Add GLM-OCR brand document ingestion

## Goal

Make the internal brand-document ingestion path accept the supplied brand PDFs even when their
pages are scans or sparse slide layouts. Use the configured Zhipu GLM-OCR service only when local
PDF text extraction is empty or below the configured coverage threshold, then continue through the
existing versioned chunking, embedding, retrieval, and activation workflow.

## Confirmed facts

- The current upload API accepts bounded PDF/DOCX/UTF-8 text uploads and stores immutable originals
  in the private MinIO brand prefix.
- The current parser uses `pypdf` for PDF text and rejects empty parsed text; it has no OCR port.
- The current content worker already owns provider calls and durable brand-ingestion leases, so OCR
  must run there rather than in the upload request or a database transaction.
- The two supplied brand PDFs are 48 pages / 25,105,469 bytes and 50 pages / 24,418,060 bytes.
- The updated directory now also contains `01-brand-profile/郭郭儿童发展计划 · 创始人访谈.docx`
  with 85 non-empty paragraphs and approximately 6,331 extracted characters. It includes an
  identified interview guest; the user explicitly authorized provider processing and activation
  for the internal parent-facing brand-context workflow on 2026-08-03.
- `05-visual-assets/logo_and_ip/` contains 18 real brand/IP image files plus 18 `__MACOSX` sidecar
  files. The existing visual manifest still governs the text-RAG boundary: visual assets are not
  text-RAG documents, and macOS/Tencent metadata sidecars are ignored.
- Zhipu's current GLM-OCR layout parsing API accepts PDF Base64 input up to 50 MB and 100 pages and
  returns Markdown plus layout metadata. The official endpoint is
  `POST https://open.bigmodel.cn/api/paas/v4/layout_parsing` with model `glm-ocr`.
- Brand text remains untrusted content. OCR output must not be logged as raw text or treated as
  factual evidence.

## Requirements

### R1 - OCR-aware parser boundary

- Preserve local extraction as the first path for text-bearing documents.
- Return a typed parser result that identifies extraction method, page count, and whether OCR is
  required; use a stable, configurable sparse-text rule rather than a hard-coded one-off check.
- For PDF documents requiring OCR, call an application-owned OCR port with the immutable original
  bytes and receive normalized Markdown/text plus bounded safe provider metadata.
- Keep non-PDF parsing behavior unchanged. Unsupported, malformed, encrypted, oversized, or
  provider-invalid documents must retain typed terminal diagnostics.

### R2 - Zhipu GLM-OCR adapter

- Add a Zhipu adapter for `layout_parsing` using the existing HTTPS, timeout, concurrency, retry,
  provider-identity, request-fingerprint, and secret-redaction conventions.
- Send local PDFs as bounded `data:application/pdf;base64,...` input; do not create public object
  URLs or expose MinIO credentials.
- Request Markdown text without crop images or layout visualizations for the brand RAG path.
- Validate response size, model identity, required result fields, and non-empty OCR text. Persist
  only provider/model/request fingerprint/request ID, page count, character count, and token/latency
  counters where available.
- Retry only typed transient provider failures; do not retry invalid credentials, unsupported
  input, or schema-invalid output.

### R3 - Durable ingestion and versioning

- Execute OCR outside API handlers and database transactions under the existing brand-ingestion
  job lease and heartbeat.
- Feed OCR text through the existing normalization and deterministic chunking path, then embed the
  resulting chunks with the configured brand embedding provider.
- Persist extraction method, OCR model/provider metadata, parser/chunk/embedding versions, and
  safe OCR diagnostics on the immutable document version/attempt. Do not mutate prior versions.
- Preserve idempotency: repeating the same upload and derivation bundle must not create duplicate
  chunks or provider calls after a successful persisted ingestion.

### R4 - Supplied document acceptance

- Upload the two PDFs and the newly authorized founder-interview DOCX under
  `private/brand-materials/01-brand-profile/`, using the existing brand metadata contract and
  parent audience.
- Parse the DOCX locally and send only its bounded parsed chunks to the configured embedding
  provider; do not call GLM-OCR for a text-bearing DOCX.
- Keep `05-visual-assets/` outside text RAG. Visual assets may be indexed by the later image pipeline,
  but are not part of this OCR/embedding task.
- Wait for each durable ingestion job to succeed, inspect parsed character/chunk counts and OCR
  extraction method, then activate the ready versions.
- Verify brand retrieval returns context from the activated versions and that content generation
  no longer stops at `missing_brand_context`.

### R5 - Safety and operational boundaries

- Never log API keys, authorization headers, raw PDFs, raw OCR responses, full brand text, or signed
  object URLs.
- Keep the single-brand and manual-use/no-auto-publish boundaries intact.
- Do not add arbitrary file URLs, general web ingestion, OCR CAPTCHA bypass, stealth networking, or
  a second vector database.

## Acceptance criteria

- [x] A text-bearing PDF uses local extraction and does not call GLM-OCR.
- [x] A scan/low-coverage PDF calls GLM-OCR through the worker port, stores normalized OCR text,
      and continues to chunking and embedding.
- [x] The two supplied PDFs ingest successfully with no raw document/provider payloads in logs;
      each result exposes extraction method and bounded OCR metadata.
- [x] The authorized founder-interview DOCX ingests through the local parser, receives brand
      embeddings, and can be activated without an OCR call.
- [x] A GLM-OCR timeout/rate limit is retryable with bounded attempts; invalid provider output and
      unsupported input become visible terminal diagnostics without a blind retry loop.
- [x] Existing non-OCR brand upload, activation, and provider-disabled behavior remain
      passing.
- [x] Repeating the same upload/ingestion request is idempotent and does not duplicate the active
      version's chunks or embeddings.
- [x] `brand-context/retrieve` returns hits from the activated documents and the selected-topic
      copy job advances past `missing_brand_context` when its other prerequisites are available.
- [x] Focused unit/contract/integration checks, migration checks, `make doctor`, Compose validation,
      and `git diff --check` pass.

## Out of scope

- OCR for arbitrary public URLs or general-purpose document conversion.
- Visual crop-image persistence, table-to-HTML post-processing, handwriting-specific OCR modes, or
  OCR of the existing visual-asset PNG library.
- Automatic activation of a failed or low-confidence document; activation remains an explicit
  operator action after ingestion succeeds.
