# Brand Knowledge Ingestion and Retrieval

## Scenario: Private, versioned Sai Xiansheng brand corpus

### 1. Scope / Trigger

Use this contract whenever code changes internal brand-file upload, parsing, versioning, embedding,
activation, retrieval, the content worker, or the brand API/UI. The implemented scope is one
private brand (`sai-xiansheng`) with `parents` and `internal` audiences. Brand context guides tone,
safety, approved examples, and visual direction for internally generated copy; it is never eligible
external-fact evidence. `parents` identifies the generated copy's target audience, not a retrieval
user or public search role.

### 2. Signatures

- Feature migration: `20260730_0007`; current repository head: `20260805_0018`.
- Upload: `POST /api/v1/brand-documents` as multipart PDF, DOCX, UTF-8 TXT, or Markdown -> HTTP 202.
- Query: `GET /api/v1/brand-documents`, `GET /api/v1/brand-documents/{document_id}`, and
  `GET /api/v1/brand-ingestion-jobs/{job_id}`.
- Lifecycle: `POST /api/v1/brand-documents/{document_id}/versions/{version_id}/activate` and
  `POST /api/v1/brand-documents/{document_id}/deactivate`.
- Retrieval: `POST /api/v1/brand-context/retrieve` -> bounded internal copy-generation
  `BrandContextResponse` with `evidence_eligible=false`; the HTTP route also supports controlled
  operator diagnostics.
- Worker: `python -m app.content_worker_main`; it alternates topic-selection and brand-ingestion
  claims when both queues contain work.
- Offline acceptance: `AI_PROVIDER_MODE=fake`; production provider: `AI_PROVIDER_MODE=zhipu` with
  the key supplied only through process/deployment secrets.

### 3. Contracts

- Originals are content-addressed, immutable private MinIO objects under
  `brand-originals/sha256/<prefix>/<sha256>`. List/detail APIs expose metadata, not full originals.
- Logical documents are keyed by normalized title, kind, audience, and the single brand. Versions
  are immutable and own validity, tags, parser/chunk/input versions, provider/model/dimensions, and
  job state.
- The version derivation key includes body SHA-256, a canonical `metadata_fingerprint`, parser,
  chunk and embedding-input versions, embedding provider, and embedding model. Tag order is not a
  semantic change; validity or tag content is.
- Upload is rejected with HTTP 409 when no embedding provider is available. Never create a
  `provider=disabled` job that no worker can claim.
- The worker claims only versions matching its provider/model. The persisted vector result must
  match the immutable provider/model and contain exactly 2048 finite, non-zero values.
- Parsing is bounded by file signature, MIME/extension agreement, bytes, PDF pages, text
  characters, chunk count, and DOCX archive safety rules. DOCX macros, embedded objects, external
  relationships, unsafe expansion, and encrypted PDFs are rejected.
- Chunk IDs, hashes, ordinals, and offsets are deterministic. For every chunk,
  `parsed.text[char_start:char_end] == chunk.text`.
- PostgreSQL full-text `ts_rank` and pgvector cosine candidates are filtered by active version,
  audience, validity, kind, provider, and model before weighted reciprocal-rank fusion.
- The retrieval query represents a selected topic or draft-generation intent. Its primary consumer
  is the copy-generation node; no route or UI may present it as a parent-facing search product.
- Brand tables, repositories, ports, response types, and embedding purpose remain separate from
  factual evidence. No brand chunk can satisfy an evidence binding foreign key or response type.
- Parent chunks must be flushed before embedding rows when no ORM relationship owns dependency
  ordering. Do not rely on SQLAlchemy to infer unit-of-work ordering from foreign keys alone.

Environment keys are `BRAND_UPLOAD_MAX_BYTES`, `BRAND_PARSE_MAX_PAGES`,
`BRAND_PARSE_MAX_CHARACTERS`, `BRAND_PARSE_MAX_CHUNKS`, `BRAND_CHUNK_CHARACTERS`,
`BRAND_CHUNK_OVERLAP_CHARACTERS`, `BRAND_PARSER_VERSION`, `BRAND_CHUNK_VERSION`,
`BRAND_EMBEDDING_INPUT_VERSION`, `BRAND_RETRIEVAL_VERSION`, `BRAND_OCR_MODEL`,
`BRAND_OCR_SPARSE_TEXT_THRESHOLD`, `BRAND_OCR_MAX_REQUEST_BYTES`,
`BRAND_OCR_MAX_RESPONSE_BYTES`, `BRAND_OCR_TIMEOUT_SECONDS`, and `BRAND_OCR_MAX_PAGES`.

The default upload maximum is the hard-bounded 25 MiB so the initial supplied slide decks fit.
Slide-deck PDFs with partial but representative text layers are accepted without OCR for the MVP;
record extraction coverage and defer OCR/source-slide parsing. Private image assets stay outside
brand chunks/embeddings. `scripts/build_brand_asset_manifest.py` inventories valid PNG assets for
the later image pipeline and skips `:com.tencent.wedrive.*` sidecars, symbolic links, malformed PNG
signatures/chunks, and unsupported files. Each accepted asset is at most 25 MiB, 8192 pixels on
either axis, and 32 million pixels total; discovery stops with an error after 10,000 entries. The
private manifest output must remain inside the resolved materials root and must not be a symbolic
link.

### 3.1 Structure-aware chunks and retrieval diversity

The active chunk contract is `brand-chunk-v2-structure-aware`. After text normalization, the parser
uses the configured maximum chunk size and overlap while preferring, in order, paragraph breaks,
Markdown block boundaries, sentence endings, and line breaks. It falls back to the hard character
limit when no boundary is available. Chunk IDs, ordinals, hashes, and offsets remain deterministic,
and every chunk must satisfy `parsed.text[char_start:char_end] == chunk.text`.

The active retrieval contract is `brand-hybrid-rrf-v2-diverse`. PostgreSQL full-text and pgvector
each produce bounded candidates, which are fused with the documented weighted RRF scores. A
deterministic post-fusion selector then keeps rank order while preferring different documents,
skipping adjacent chunks from the same version, and removing identical text. It first caps the
number of chunks per document; it relaxes adjacency and duplicate-text constraints, then the
document cap, only when the available corpus cannot fill `limit`. This improves context coverage
without changing the evidence-ineligible brand-context boundary.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Content production disabled | HTTP 409; no object or durable job |
| Embedding provider unavailable | HTTP 409; no permanently unclaimable job |
| Unsupported/mismatched signature, MIME, or extension | Safe HTTP 422 without corpus text |
| Encrypted/malformed/excessive PDF or unsafe DOCX | Terminal typed ingestion/upload failure |
| Exact body, metadata, provider, and version bundle replay | Existing version/job with `created=false` |
| Same body but changed validity/tags or provider | New immutable version with `created=true` |
| Worker provider/model differs from queued version | Job remains unclaimed by that worker |
| Lease lost during embedding/persistence | Stop useful work; persist/recover through lease rules |
| Version not ready | Activation returns HTTP 409 |
| Inactive, expired, wrong-audience, wrong-kind, or wrong-model chunk | Excluded before ranking |
| Retrieval succeeds | `evidence_eligible=false` is always present |
| Visual asset is a sidecar, symlink, malformed/oversized PNG, or unsupported file | Skip it and increment the bounded unsupported/sidecar count; never add it to text RAG |
| Manifest output escapes the private materials root or is a symlink | Reject before writing |

### 5. Good / Base / Bad Cases

- Good: upload a controlled Markdown file, observe a durable job, process it with the fake provider,
  activate the ready version, and retrieve target-parent brand guidance as internal copy-generation
  context with document/chunk IDs and scores.
- Base: a valid upload queues while another provider's version exists; each worker claims only its
  own provider/model derivation.
- Bad: reuse a fake vector after switching to Zhipu, overwrite tags on an old version, combine
  evidence and brand search results, or queue work while the provider is disabled.

### 6. Tests Required

- [`test_brand_knowledge.py`](../../../backend/tests/unit/test_brand_knowledge.py) asserts file
  validation, DOCX rejection, deterministic structure-aware chunks, sentence fallback, exact
  offsets, retrieval diversity/fallback behavior, metadata fingerprint semantics, character limits,
  and filename sanitization.
- [`test_brand_knowledge_rag.py`](../../../backend/tests/integration/test_brand_knowledge_rag.py)
  uses real PostgreSQL/pgvector and MinIO to assert upload/replay, metadata/provider version splits,
  worker processing, activation, generation-context retrieval, wrong-audience exclusion, and
  deactivation.
- [`test_migrations.py`](../../../backend/tests/integration/test_migrations.py) asserts head
  `20260805_0018`, the six brand tables, non-null metadata fingerprint, and non-null provider.
- [`test_brand_asset_manifest.py`](../../../backend/tests/unit/test_brand_asset_manifest.py)
  asserts valid PNG metadata, character tags, sidecar/symlink/invalid-file exclusion, dimension
  limits, and private output-path enforcement.
- OpenAPI generation and frontend generated types must remain drift-free after route/schema edits.
- Real supplied brand documents have a bounded offline retrieval record in the active task's
  `validation.md`; it proves storage/worker/filtering/metadata propagation, while production
  semantic quality still requires the configured live embedding provider.

### 7. Wrong vs Correct

#### Wrong

```python
for artifact in embeddings:
    session.add(BrandChunkModel(...))
    session.add(BrandChunkEmbeddingModel(chunk_id=artifact.chunk.id, ...))
await session.commit()
```

Without ORM relationships, the unit of work may insert the embedding first and violate
`fk_brand_chunk_embeddings_chunk_id`.

#### Correct

```python
for artifact in embeddings:
    session.add(BrandChunkModel(...))
await session.flush()
for artifact in embeddings:
    session.add(BrandChunkEmbeddingModel(chunk_id=artifact.chunk.id, ...))
await session.commit()
```

Persist parents first, and include semantic metadata plus provider/model in the immutable
derivation key.

For private visual inputs, resolve and validate each real file before hashing it, keep the manifest
inside `private/brand-materials/`, and never treat an image filename or sidecar as brand text.
