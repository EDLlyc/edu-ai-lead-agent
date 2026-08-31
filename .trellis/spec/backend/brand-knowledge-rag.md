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

- Feature migrations: `20260730_0007` and structured-section revision `20260820_0023`; current
  repository head: `20260823_0028` (local official-account editorial review after multi-image and
  the original local drafting foundation, after normalized visual inputs; no text-RAG vector changes).
- Upload: `POST /api/v1/brand-documents` as multipart PDF, DOCX, UTF-8 TXT, or Markdown -> HTTP 202.
- Query: `GET /api/v1/brand-documents`, `GET /api/v1/brand-documents/{document_id}`, and
  `GET /api/v1/brand-ingestion-jobs/{job_id}`.
- Lifecycle: `POST /api/v1/brand-documents/{document_id}/versions/{version_id}/activate` and
  `POST /api/v1/brand-documents/{document_id}/deactivate`.
- Retrieval: `POST /api/v1/brand-context/retrieve` -> bounded internal copy-generation
  `BrandContextResponse` with `evidence_eligible=false`; the HTTP route also supports controlled
  operator diagnostics.
- Digital-IP profile: `GET /api/v1/digital-ip/profile` -> one read-only
  `DigitalIpProfileResponse` for `sai-xiansheng-xiao-sai`, joining active-ready version metadata
  with a bounded safe projection of the private visual catalog.
- Worker: `python -m app.content_worker_main`; it alternates topic-selection and brand-ingestion
  claims when both queues contain work.
- Offline acceptance: `AI_PROVIDER_MODE=fake`; live brand vectors:
  `BRAND_EMBEDDING_PROVIDER_MODE=alibaba` (or `auto` with the Alibaba visual provider configured),
  using `qwen3-vl-embedding` and secrets supplied only through process/deployment settings. Zhipu
  remains the text-generation/OCR and governance-vector provider.

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
- The worker claims and recovers stale leases only for versions matching its parser, chunk,
  embedding-input, provider, and model identity. The persisted vector result must match the
  immutable provider/model and contain exactly 2048 finite, non-zero values.
- Brand upload, worker claim, API/content retrieval, and real-data MCP retrieval resolve provider,
  model, and dimensions through the same brand-specific settings/factory. They must not reuse the
  governance/article embedding identity merely because both vectors have 2048 dimensions.
- Brand-ingestion worker availability follows the resolved brand provider, not
  `AI_PROVIDER_MODE`. Alibaba brand ingestion may run while governance AI is disabled; sparse PDFs
  then fail through the existing typed OCR-unavailable path rather than disabling all text-layer
  brand ingestion. Copy generation keeps its independent fake/Zhipu provider requirement.
- Alibaba's upstream text fingerprint may repeat for identical text. The persisted brand
  `request_fingerprint` therefore hashes a version label, `chunk_id`, and the upstream fingerprint;
  it remains deterministic 64-hex metadata without including text. This changes no vector input,
  provider/model identity, parser/chunk version, or embedding-input policy.
- Parsing is bounded by file signature, MIME/extension agreement, bytes, PDF pages, text
  characters, chunk count, and DOCX archive safety rules. DOCX macros, embedded objects, external
  relationships, unsafe expansion, and encrypted PDFs are rejected.
- PDF pages and DOCX question-answer groups are immutable `BrandSection` parents. Section/chunk
  IDs, hashes, ordinals, and offsets are deterministic. Every parent and child is an exact slice of
  one canonical `parsed.text`; overlap never crosses a parent boundary.
- PostgreSQL full-text `ts_rank` and pgvector cosine candidates are filtered by active version,
  audience, validity, kind, provider, and model before weighted reciprocal-rank fusion.
- The retrieval query represents a selected topic or draft-generation intent. Its primary consumer
  is the copy-generation node; no route or UI may present it as a parent-facing search product.
- Brand tables, repositories, ports, response types, and embedding purpose remain separate from
  factual evidence. No brand chunk can satisfy an evidence binding foreign key or response type.
- Sections must be flushed before chunks, and chunks before embedding rows, when no ORM
  relationship owns dependency ordering. Do not rely on SQLAlchemy to infer unit-of-work ordering
  from foreign keys alone.

Environment keys are `BRAND_UPLOAD_MAX_BYTES`, `BRAND_PARSE_MAX_PAGES`,
`BRAND_PARSE_MAX_CHARACTERS`, `BRAND_PARSE_MAX_CHUNKS`, `BRAND_CHUNK_CHARACTERS`,
`BRAND_CHUNK_OVERLAP_CHARACTERS`, `BRAND_PARSER_VERSION`, `BRAND_CHUNK_VERSION`,
`BRAND_EMBEDDING_INPUT_VERSION`, `BRAND_RETRIEVAL_VERSION`, `BRAND_OCR_MODEL`,
`BRAND_OCR_SPARSE_TEXT_THRESHOLD`, `BRAND_OCR_MAX_REQUEST_BYTES`,
`BRAND_OCR_MAX_RESPONSE_BYTES`, `BRAND_OCR_TIMEOUT_SECONDS`, and `BRAND_OCR_MAX_PAGES`.

The default upload maximum is the hard-bounded 25 MiB so the initial supplied slide decks fit.
Slide-deck PDFs with partial but representative text layers are accepted without OCR and preserve
non-empty pages as parents; OCR is reserved for sparse extraction. Private image assets stay outside
brand chunks/embeddings. `scripts/build_brand_asset_manifest.py` inventories valid PNG assets for
the later image pipeline and skips `:com.tencent.wedrive.*` sidecars, symbolic links, malformed PNG
signatures/chunks, and unsupported files. Each accepted asset is at most 25 MiB, 8192 pixels on
either axis, and 32 million pixels total; discovery stops with an error after 10,000 entries. The
private manifest output must remain inside the resolved materials root and must not be a symbolic
link.

### 3.1 Read-only digital-IP projection

- The profile is derived from the existing active document authority. A document contributes only
  when its `active_version_id` resolves to a version whose state is both `active=true` and `ready`;
  inactive, stale, queued, processing, and failed versions do not contribute tags or bindings.
- Fixed identity fields describe the existing Sai Xiansheng/Xiao Sai portfolio only. Tone, safety,
  visual, approved-example, prohibited-language, and positioning coverage point back to active
  version IDs instead of copying a second body of mutable rule text.
- The visual branch reuses `load_visual_catalog` and returns at most 12 approved assets for
  `sai-xiansheng` or `xiao-sai`. Its response allowlist contains short digest references, display
  metadata, kind, characters, roles, topics, poses, scenes, dimensions, approval, and priority. It
  never contains a filename, relative/absolute path, object key, URL, bytes, or full digest. Apply
  the allowlist to values as well as field names: path-, URL-, and full-digest-shaped metadata is
  rejected, while a legacy filename-derived display name is replaced by a neutral safe label.
- Manifest filesystem work runs outside the async event loop. Missing, malformed, unsafe, or
  inconsistent manifests produce `visual_catalog_status=unavailable`; a valid catalog with no
  matching approved assets produces `empty`. Both preserve the independent text profile.
- `profile_fingerprint` is a deterministic SHA-256 over the fixed identity, ordered active version
  IDs, aggregate tags, visual status/version, and bounded safe asset references. The entire profile
  remains `evidence_eligible=false`.

### 3.2 Structured parents, contextual chunks, and retrieval diversity

The active identities are `brand-parser-v3-source-structure`, `brand-chunk-v3-parent-child`, and
`brand-embedding-input-v2-section-context`. A non-empty PDF page becomes one `page` section and a
blank page only contributes to `page_count`. DOCX blocks are traversed in XML order; recognized
`Q1`/`问题一` markers start `interview_qa` sections, while headings and unmatched content use bounded
`heading`/`generic` fallbacks. Tables remain at their original document position.

Within each parent, multiple blank-line card/paragraph blocks are preferred as child boundaries;
long blocks use paragraph, Markdown, sentence, line, and finally hard-size boundaries. Overlap is
allowed only inside the same parent. Raw child `text` remains the API/citation value. FTS and the
existing 2048-dimensional embedding use the deterministic contextual `embedding_text` containing
bounded document title, section title, optional question, chunk content type, and raw child. The
embedding request and stored derivation bind `embedding_input_hash`, not raw `text_hash`.

Generic OCR Markdown is budget-aware because layout output can contain hundreds of tiny blank-line
blocks. v3 first computes the ordinary exact child spans. Only when those spans exceed the remaining
global chunk budget does it greedily coalesce adjacent blocks within the same generic parent up to the
configured child size. If fragmentation still exceeds the budget, it bounded-splits one continuous
trimmed parent range with the existing boundary/overlap rules. Pure separator whitespace at output
span edges may remain uncovered; all non-whitespace content remains an exact source slice. If the
continuous parent-local representation still cannot fit, ingestion terminates with
`brand_chunk_limit`. Never raise the configured 600 hard cap, truncate content, merge parents/pages,
or apply this fallback to page/Q&A/heading sections or the frozen v2 chunker.

Version labels are executable behavior, not descriptive strings. Settings and parser construction
accept only two frozen derivation bundles: v2 parser + v2 global chunker + v1 raw embedding input,
or v3 parser + v3 parent-child chunker + v2 contextual embedding input. The v2 path retains the
old whole-document PDF/DOCX normalization, paragraphs-before-tables DOCX behavior, global overlap,
legacy chunk-key formula, raw embedding text/hash, and null section binding. Mixed/unknown bundles
fail before an upload can create an unclaimable job. Persistence permits sectionless chunks only for
the exact v2 bundle and requires parent bindings for the exact v3 bundle.

Chunk-level `BrandContentType` and `BrandClaimScope` are closed deterministic classifications.
Policy, market, award, certification, proportion, and third-party signals require verification;
`external_claim` takes priority over normative scope. All brand chunks remain evidence-ineligible.

The active retrieval contract is `brand-hybrid-rrf-v3-parent-diverse`. PostgreSQL full-text and
pgvector candidates retain all active/audience/validity/kind/provider/model filters and weighted
RRF. Selection first takes at most one child per section, relaxing the document soft cap before it
allows a second child from an already selected parent. Historical rows with no section use a
null-safe per-row compatibility key. Duplicate-text constraints are relaxed only to fill the limit.
The frozen `brand-hybrid-rrf-v2-diverse` rollback path keeps the prior document cap and adjacent
global-ordinal avoidance. Every retrieval caller passes the validated retrieval version through to
the repository; responses must never echo v2 while executing the v3 selector, or vice versa.

Historical brand vectors from another provider are immutable. The development-only
`python -m app.brand_embedding_reindex_main plan` command reports aggregate drift without writes;
`migrate --execute` creates a new derivation from each immutable original under the current
parser/chunk/input bundle, processes it with Alibaba, and activates only ready versions. Never
rewrite provider/model columns or reuse old vectors across vector spaces.

### 3.3 Provider-free text-retrieval policy evaluation

#### 1. Scope / Trigger

Run this evaluation whenever weighted RRF, retrieval v2/v3 selection, parent diversity, content or
claim classification, or the sanitized eval dataset changes. It measures deterministic retrieval
policy behavior only; it does not measure live embedding recall, private-corpus quality, generated
copy quality, or production effectiveness.

#### 2. Signatures

- Gate: `make brand-retrieval-eval`.
- Direct check: `cd backend && python -m evals.brand_retrieval.runner --check`.
- Canonical update: `cd backend && python -m evals.brand_retrieval.runner --write-canonical`.
- Dataset: `backend/evals/brand_retrieval/cases.v1.jsonl`; checked reports are adjacent.

#### 3. Contracts

- The dataset has exactly 36 sanitized cases: four for each of the nine `BrandContentType` values.
  Each case contains 7–12 independently graded observations with unique positive FTS/vector ranks.
- Ranking receives only candidate ranks and production metadata. Evaluator-only `relevance_grade`
  never enters weighted RRF or selection.
- `fuse_brand_retrieval_score` and `select_diverse_brand_hits` live in the domain layer and are used
  by both the PostgreSQL repository and evaluator. Do not copy their formulas into eval code.
- Both frozen retrieval v2 and structured retrieval v3 return exactly five unique known items. The
  report gates macro Recall@5, MRR@5, nDCG@5, a positive parent-diversity delta, complete verification
  marking for selected external claims, and zero brand-as-fact violations.
- Canonical reports exclude timestamps, latency, tokens, provider responses, private text, paths,
  vectors, and credentials. The fixture-policy disclaimer is mandatory in JSON and Markdown.

#### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Wrong case count/category balance, duplicate IDs/ranks, blank row, oversized or sensitive fixture | Loader fails closed before scoring |
| Fewer/more than five results, duplicate result, or unknown candidate ID | Metric scorer raises `ValueError` |
| v3 relevance metric regresses below v2 | Case and command fail |
| Parent-diversity delta is zero/negative | Command fails |
| Selected external claim lacks verification marking | Case and command fail |
| Any selected brand chunk is marked factual evidence | Case and command fail |
| JSON/Markdown differs from checked canonical artifacts | `--check` exits non-zero |

#### 5. Good / Base / Bad Cases

- Good: v3 retrieves relevant parent sections in the Top 5, improves diversity, retains fact
  separation, and the canonical report matches byte-for-byte.
- Base: an FTS-only or vector-only observation remains rankable through the same production RRF
  helper and both policy versions return five deterministic results.
- Bad: use relevance grades as fake-adapter answers, treat fixture numbers as live semantic recall,
  or permit an external claim/evidence leak because aggregate relevance remains high.

#### 6. Tests Required

- Unit tests freeze RRF weights/K, exact aggregate metrics, balanced category coverage, report
  stability, strict Top-5 shape, malformed datasets, verification/evidence gates, and canonical drift.
- Oracle-isolation tests mutate grades without changing selected order and must make relevance
  metrics fail when fixture truth no longer agrees with the production policy.
- Existing brand retrieval tests cover the same public selector used by PostgreSQL.

#### 7. Wrong vs Correct

Wrong: implement a fake evaluator that reads `relevance_grade` and emits the expected order, or quote
fixture Recall@5 as a production/private-corpus result.

Correct: reproduce candidate observations through shared weighted RRF and the versioned selector,
score the resulting IDs against a scorer-only grade, and label the output as fixture policy
regression evidence.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Content production disabled | HTTP 409; no object or durable job |
| Embedding provider unavailable | HTTP 409; no permanently unclaimable job |
| Unsupported/mismatched signature, MIME, or extension | Safe HTTP 422 without corpus text |
| Encrypted/malformed/excessive PDF or unsafe DOCX | Terminal typed ingestion/upload failure |
| Exact body, metadata, provider, and version bundle replay | Existing version/job with `created=false` |
| Same body but changed validity/tags or provider | New immutable version with `created=true` |
| Worker parser/chunk/input/provider/model differs from queued version | Job remains untouched by that worker |
| Parser/chunk/input versions form a mixed or unknown bundle | Settings/upload/parser fail closed; no job is created |
| Generic OCR Markdown has pathological tiny blocks | Coalesce exact adjacent spans inside that parent, then continuous parent-local bounded-split if needed |
| OCR content cannot fit after the continuous parent-local fallback | Terminal `brand_chunk_limit`; no cap increase, truncation or cross-parent merge |
| External-claim signal appears in brand material | Retrievable brand context, verification required, never factual evidence |
| Lease lost during embedding/persistence | Stop useful work; persist/recover through lease rules |
| Version not ready | Activation returns HTTP 409 |
| Inactive, expired, wrong-audience, wrong-kind, or wrong-model chunk | Excluded before ranking |
| Retrieval succeeds | `evidence_eligible=false` is always present |
| Visual manifest missing/malformed/private file changed | Profile succeeds with typed `unavailable`; no path or raw exception |
| Visual catalog valid but no approved Sai/Xiao Sai asset | Profile succeeds with typed `empty` and no fabricated asset |
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
  validation, PDF page/card parents, DOCX Q&A/table order, deterministic contextual chunks,
  generic OCR tiny-block budget coalescing, full non-whitespace coverage, cross-parent isolation,
  genuine hard-cap rejection, classifications, exact offsets, retrieval diversity/fallback behavior,
  metadata fingerprints, character limits, and filename sanitization.
- [`test_brand_knowledge_ocr.py`](../../../backend/tests/unit/test_brand_knowledge_ocr.py) asserts the
  worker's existing one-request OCR handoff, contextual embedding input, and successful bounded
  coalescing of pathological generic OCR Markdown before persistence.
- [`test_brand_knowledge_rag.py`](../../../backend/tests/integration/test_brand_knowledge_rag.py)
  uses real PostgreSQL/pgvector and MinIO to assert upload/replay, metadata/provider version splits,
  v3/v2 worker isolation, stale v2 rollback completion with null parents/raw input, activation,
  generation-context retrieval, wrong-audience exclusion, and deactivation.
- [`test_migrations.py`](../../../backend/tests/integration/test_migrations.py) asserts head
  `20260823_0028`, the seven text-brand tables, two isolated visual-index tables, normalized visual-input hashes, contextual chunk columns, metadata fingerprints, and
  provider identity.
- [`test_brand_asset_manifest.py`](../../../backend/tests/unit/test_brand_asset_manifest.py)
  asserts valid PNG metadata, character tags, sidecar/symlink/invalid-file exclusion, dimension
  limits, and private output-path enforcement.
- OpenAPI generation and frontend generated types must remain drift-free after route/schema edits.
- Real supplied brand documents have an aggregate-only parser record in the active task's
  `result.md`; it proves page/Q&A recognition and exact offsets without retaining filenames, paths,
  or source text. Storage, worker, retrieval, and typed metadata propagation are covered by synthetic
  real-PostgreSQL tests, while production semantic quality still requires the configured live
  embedding provider.

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
for section in sections:
    session.add(BrandSectionModel(...))
await session.flush()
for artifact in embeddings:
    session.add(BrandChunkModel(section_id=artifact.chunk.section_id, ...))
await session.flush()
for artifact in embeddings:
    session.add(BrandChunkEmbeddingModel(chunk_id=artifact.chunk.id, ...))
await session.commit()
```

Persist parents first, and include semantic metadata plus provider/model in the immutable
derivation key.

For private visual inputs, resolve and validate each real file before hashing it, keep the manifest
inside `private/brand-materials/`, and never treat an image filename or sidecar as brand text.
