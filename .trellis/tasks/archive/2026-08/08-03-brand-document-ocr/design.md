# Design: GLM-OCR brand ingestion

## 1. Data flow

```text
multipart upload
  -> immutable private MinIO original + version/job rows
  -> worker claims lease
  -> local pypdf parse
       -> sufficient text: normalize/chunk
       -> empty/sparse PDF: Zhipu GLM-OCR layout_parsing
       -> DOCX/TXT/Markdown: local parser
  -> normalize Markdown/chunk deterministically
  -> Zhipu embedding-3 brand vectors
  -> persist version/attempt diagnostics
  -> explicit activation
  -> separated brand retrieval
```

The API remains an enqueue-only boundary. All OCR and embedding calls occur in the worker outside
database transactions. The original remains the source artifact; OCR text is a derived versioned
artifact.

## 2. Application contracts

Add a `BrandDocumentOcrModel` port with a request containing version ID, input hash, media type,
page count, and original bytes, and a result containing normalized Markdown, provider/model,
request fingerprint, provider request ID, page count, token usage, and latency. Keep the port
provider-neutral; the Zhipu implementation lives under `infrastructure/ai`.

Extend `ParsedBrandDocument` with extraction metadata (`extraction_method`, optional OCR provider,
model, request fingerprint, provider request ID, and token/latency counters). The parser returns a
non-empty local result when coverage is sufficient and a typed OCR-needed result for sparse PDFs;
the worker owns the decision to call the OCR port. Non-PDF documents always use local parsing.

Use one normalized text path after either source. Markdown from GLM-OCR and locally parsed DOCX text
are treated as untrusted brand text: normalize bounded whitespace, preserve useful headings/table
text, reject empty output, and then use the existing deterministic chunk IDs and offsets. The
authorized founder-interview DOCX uses local parsing and embedding; it does not need OCR.

## 3. Provider adapter

Implement the adapter against `/api/paas/v4/layout_parsing` with:

- `model="glm-ocr"` and a `data:application/pdf;base64,...` file value;
- `return_crop_images=false` and `need_layout_visualization=false`;
- stable request ID derived from the version/input fingerprint;
- existing HTTP timeout, semaphore, retry, response-size, and secret handling conventions;
- strict JSON validation for `id`, `model`, `md_results`, `data_info`, and bounded `usage`;
- provider identity validation and a stable application-owned error for missing/invalid Markdown.

Reuse the existing Zhipu HTTP transport helper after making it provider-shared if needed. Do not
copy a second unbounded retry implementation. The adapter must never log request bodies or response
content.

## 4. Persistence and migration

Add nullable derivation metadata to `brand_document_versions` for extraction method and OCR provider
identity/request metadata, plus bounded OCR usage fields if the existing version table cannot carry
them in its safe metadata. Store an allowlisted OCR summary in `brand_ingestion_attempts.safe_metadata`.
Existing rows receive local/unknown defaults and remain readable. Update parser/embedding derivation
idempotency only by versioning the parser contract (for example `brand-parser-v2-glm-ocr`); never
rewrite existing chunks or vectors.

The migration must be Alembic-only, have explicit constraints/indexes, and contain no provider calls.

## 5. Settings and rollout

Add bounded settings for OCR model, sparse-text threshold, OCR request/response bytes, OCR timeout,
and maximum OCR page count. The provider is available only in `AI_PROVIDER_MODE=zhipu`; disabled mode
continues to fail closed at upload/worker boundaries. Bump the brand parser version so new and old
derivations cannot be confused.

Roll out by rebuilding the content worker, uploading the two existing PDFs and the authorized DOCX
through the API, waiting for successful jobs, querying diagnostics, and explicitly activating ready
versions. If OCR is unavailable, leave PDF versions failed/queued with safe diagnostics and do not
activate partial text; the DOCX can still use the local-parser path if embeddings are available.

## 6. Compatibility and risks

- Local text PDFs retain the old behavior except for additive metadata.
- The current 25 MB upload limit is below GLM-OCR's 50 MB PDF limit; both supplied files are below
  the upload limit and within 100 pages.
- Base64 expands request size, so the adapter must bound encoded payloads and provider responses.
- OCR output may contain hallucinated or malformed text; it is brand guidance only and remains
  separated from factual evidence. Low-confidence information is not silently promoted to facts.
- OCR cost and latency are intentional for sparse PDFs; logs expose counts and latency, not content.
