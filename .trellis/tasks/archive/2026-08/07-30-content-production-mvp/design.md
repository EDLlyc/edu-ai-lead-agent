# Design: Complete Content Production MVP

## 1. Design Intent

Extend the completed event pool into one daily, evidence-backed, brand-aligned material package for
manual use. The MVP is functionally complete across selection, brand RAG, copy/audit/repair, image,
and internal review, while deliberately limiting product breadth to one brand, one parent audience,
one daily topic, one draft, one repair, one image, and one reviewer workflow.

Delivery is functional-first: connect the happy path and critical safety gates with thin but real
persistence/API/UI contracts, then tune reliability, evaluation depth, performance, and production
operations after the user can inspect the running product.

The parent task coordinates four child deliverables and final integration. It is not a monolithic
implementation target. Each child establishes durable contracts that the next child consumes.

## 2. End-to-End Architecture

```text
completed governed event pool
          |
          v
daily topic-selection run
  hard veto -> scoring-v1 -> Top 1 / no_topic
          |
          v
separate evidence retrieval + brand retrieval
          |
          v
typed Moments draft + claim bindings
          |
          v
deterministic validation -> LLM brand/risk audit
          |                         |
          | accepted                +-> one bounded repair -> revalidate/audit
          v
approved image prompt -> image provider -> MinIO
          |
          v
versioned material package -> internal React review/copy/download
```

### Process boundaries

- Existing acquisition/governance processes remain unchanged.
- `content_scheduler_main` creates one content run per `Asia/Shanghai` business date and active
  pipeline/profile version after governed events are available.
- `content_worker_main` claims durable topic/material and brand-ingestion jobs. It executes
  deterministic services directly and uses LangGraph only for the resumable generation/audit/
  repair/image sequence where checkpointed state adds value.
- FastAPI enqueues brand ingestion/manual content runs and exposes status/query/download routes. It
  never parses a document, calls a model/image provider, or runs the multi-stage pipeline inline.
- PostgreSQL run/job/artifact tables are operational truth. Checkpoints contain IDs, hashes,
  versions, statuses, issue codes, and small typed outputs only.

## 3. Child Task Boundaries and Dependencies

### Child 1 — Daily topic selection and locking

Input: immutable current event versions plus facts, categories, entities, source diversity,
publication/event times, assignment review state, and prior daily selections.

Output: one durable daily selection containing either a locked event/version or `no_topic`, plus
score rows for every considered event and a versioned configuration snapshot.

No model is required for the final score. Controlled preprocessing may derive bounded deterministic
features from already persisted governance projections.

### Child 2 — Brand knowledge ingestion and RAG

Depends on shared embedding/provider/object-storage patterns, not on a selected topic for ingestion.
Retrieval acceptance consumes a selected event/evidence query from Child 1.

Output: active versioned brand documents/chunks/embeddings and a typed `BrandContextResult` that is
separate from `EvidenceContextResult`.

### Child 3 — Evidence-bound copy generation and audit

Depends on locked topic/evidence from Child 1 and active brand retrieval from Child 2.

Output: immutable draft versions, typed claims, relational fact/brand bindings, deterministic
validation results, model audit attempts/issues, and either an accepted draft or a visible reviewable
failure after one repair.

### Child 4 — Image generation and material-package UI

Depends on an accepted draft/image prompt from Child 3.

Output: one idempotent image artifact in MinIO, one versioned material package projection, query/
download APIs, and an internal accessible React experience.

## 4. Persistence Shape

Use UUIDs, UTC `TIMESTAMPTZ`, explicit status constraints, named indexes/constraints, immutable
versions, JSONB only for genuinely variable safe metadata, and Alembic-only schema changes.

### Topic selection

- `topic_selection_runs`: unique `(business_date, timezone, pipeline_version, scoring_profile)`;
  status, selected event/version, `no_topic` reason, counts, timestamps.
- `topic_score_configs`: immutable version, feature ranges, weights, penalties, threshold, tie-break
  definition, activation/evaluation metadata.
- `topic_scores`: one event version/config/run evaluation with raw+normalized features, vetoes,
  total, eligibility, rank, and decision explanation.
- `daily_topic_selections`: immutable lock binding business date to event/version/config or explicit
  no-topic; uniqueness prevents two selected topics per date/profile.

### Brand knowledge

- `brand_documents`: stable logical identity, brand/audience/type/status/current-version pointer.
- `brand_document_versions`: filename, media type, checksum, object key, validity, parser version,
  metadata, immutable version.
- `brand_ingestion_jobs` and attempts: durable parse/chunk/embed lifecycle.
- `brand_chunks`: stable ordinal/hash/text offsets, audience, validity, safety/tone/visual tags.
- `brand_embeddings`: provider/model/dimension/input-version/vector with purpose `brand_retrieval`.

### Draft, audit, and package

- `content_runs` and `content_jobs`: daily material orchestration, stage, lease, attempts, versions,
  safe errors, token/latency counters.
- `material_drafts` and versions: structured copy fields, image prompt, prompt/schema/model versions,
  request fingerprint, status.
- `draft_claims`: `external_fact`, `brand_statement`, or `opinion`.
- `claim_evidence_bindings`: relational link to governance evidence passage/binding and occurrence.
- `claim_brand_bindings`: relational link to active brand document version/chunk.
- `validation_results`, `audit_attempts`, and `audit_issues`: ordered deterministic/model gates and
  one repair lineage.
- `image_artifacts`: provider/model/prompt version/fingerprint, dimensions, object identity, status,
  attempts, safe provider ID.
- `material_packages` and versions: selected topic, accepted draft, image, sources/bindings, audit
  state, manual-review state, timestamps.

Operational rollback disables scheduling/workers and preserves all evidence, selections, brand
versions, drafts, audits, images, and packages. Production rollback does not downgrade the schema.

## 5. Topic Scoring Design

### Veto precedence

Hard vetoes run first and cannot be outweighed. Initial codes cover unresolved/review-required
event identity, insufficient eligible evidence, privacy/minor risk, legal/safety uncertainty,
unsuitable negative incident, prohibited marketing risk, and materially the same event selected
within seven business days.

### Versioned scoring-v1 proposal process

The owning child defines feature ranges and proposes numeric values for:

- source trust/diversity;
- AI/science-education relevance;
- parent relevance;
- freshness;
- communication potential;
- historical/theme repetition penalty; and
- controversy/marketing-risk penalty.

The configuration is evaluated against controlled fixtures plus accumulated real governed events.
Product review inspects expected versus actual eligibility, ranks, Top 1, and no-topic outcomes.
Only an explicitly approved config becomes active; later tuning creates a new immutable version.

Stable tie-breaks are part of the config, initially: higher source trust/diversity, newer event time,
then stable event UUID. Selection reads one consistent event-version cutoff and locks in a short
transaction.

## 6. Brand Ingestion and Retrieval Design

### Upload and parsing

- Initial supported formats are bounded PDF, DOCX, UTF-8 TXT, and Markdown unless parser research
  finds an unsafe/incompatible format that must be deferred explicitly.
- Validate extension, MIME signature, size, page/character limits, filename/object key, and checksum
  before accepting durable work. Store the original in a brand-specific MinIO prefix with no public
  access.
- Parsing and chunking run outside API requests. Reject encrypted, malformed, excessive, or
  unsupported content with typed safe diagnostics.
- Normalize conservatively and build deterministic chunks by headings/paragraphs with stable IDs,
  hashes, ordinals, and source offsets. A new file/checksum/parser/chunking version creates a new
  document version.

### Hybrid retrieval

- Apply brand, audience, active/valid-at, content-type, and safety metadata filters first.
- Retrieve a bounded keyword set with PostgreSQL full-text `ts_rank` and a bounded vector set with
  pgvector cosine distance.
- Fuse ranked lists with a documented reciprocal-rank or equivalent deterministic algorithm, then
  optionally rerank a small set through a typed provider port only if evaluation shows value.
- Return chunk IDs, document/version IDs, scores/components, tags, and bounded text. Never return
  brand results through the factual evidence type.

## 7. Draft, Validation, Audit, and Repair Design

### Generation contract

The model receives a selected-topic envelope with separate delimited sections:

```python
class DraftClaim(BaseModel):
    id: str
    text: str
    kind: Literal["external_fact", "brand_statement", "opinion"]
    evidence_ids: tuple[UUID, ...] = ()
    brand_chunk_ids: tuple[UUID, ...] = ()

class MaterialDraft(BaseModel):
    copywriting: str
    parent_takeaway: str
    interaction: str
    source_note: str
    image_prompt: str
    claims: tuple[DraftClaim, ...]
```

The application validates referenced IDs against the supplied retrieval sets and persists
relational bindings. Model memory cannot add evidence or brand rules.

### Gate order

1. Schema/size/field validation.
2. Claim-kind and evidence/brand binding validation.
3. Source/date/topic consistency, banned expression, privacy, marketing, image, and no-publish
   deterministic checks.
4. Typed LLM brand/risk audit over the accepted artifacts.
5. If rejected and repair remains, generate one new draft using only structured issue codes,
   locations, and allowed artifacts; repeat deterministic validation and audit.
6. Accept or persist a terminal reviewable failure with both versions and issue history.

The audit cannot change the selected topic, add factual evidence, override a veto, or mark a
deterministically invalid draft accepted.

## 8. Image and Material Package Design

- Define an application-owned `ImageGenerator` port and deterministic fake. Provider/model/size/
  output-format compatibility is probed and pinned before live migration assumptions are finalized.
- The image request uses only the accepted versioned image prompt plus safe style parameters. One
  fingerprint maps to at most one successful image artifact.
- Store the image in MinIO; API responses expose package/image metadata and a controlled download
  endpoint rather than object-store credentials or permanent public URLs.
- Package state progresses to `awaiting_manual_use` when copy, image, bindings, and audit are ready.
  Internal review may acknowledge/approve or reject with a bounded note, but the MVP does not
  include in-browser copy editing, multi-role approval, or publishing.

### Frontend routes

- `/` or `/daily`: current business-date status, Top 1/no-topic, score explanation, and navigation.
- `/brand-documents`: upload, list versions/status, activate/deactivate, ingestion diagnostics.
- `/runs/:runId`: bounded pipeline stage/status view.
- `/packages/:packageId`: topic, copy, takeaway, interaction, image, sources/bindings, validation/
  audit issues, manual review action, copy, and download.

Use generated API types, TanStack Query hooks, feature-local view models, semantic controls,
keyboard-visible focus, `aria-live` copy/download feedback, safe text rendering, and explicit
loading/no-topic/failed/ready states.

## 9. API Surface

Versioned internal APIs are expected for:

- topic run enqueue/status/scores and daily selection detail;
- brand document multipart upload, list/detail/version/status/activate/deactivate and ingestion job
  status;
- content run enqueue/status/jobs;
- material package list/detail/review acknowledgement;
- controlled image download.

Lists are cursor-paginated and bounded. Mutations use durable `202` enqueue or idempotent short
transactions. OpenAPI exposes no prompt/raw response, full embedding, secret, arbitrary object key,
social credential, or publish endpoint.

## 10. Security, Privacy, and Observability

- Treat uploaded files, brand text, evidence, model output, filenames, URLs, and provider responses
  as untrusted.
- Enforce upload type/size/decompression/page/text bounds; sanitize filenames and object keys.
- Preserve strict factual-versus-brand types, foreign keys, prompts, and API projections.
- Do not send obvious secrets, personal data, or unsafe minor-related material to providers.
- Keep credentials only in `.env`/deployment secrets. The API key previously shared in chat must be
  rotated before production use.
- Emit structured run/job/stage/provider/model/version/duration/token/result/error telemetry without
  full content or credentials.
- Add cost/token/image budgets per run/day and fail closed on exhaustion.

## 11. Deployment and Rollout

1. Apply each child migration with its feature disabled.
2. Verify deterministic fake flow and focused real PostgreSQL/MinIO tests.
3. Activate an approved scoring config and inspect a real daily selection.
4. Upload representative brand documents and accept retrieval quality.
5. Enable live copy/audit for one selected topic and approve evidence/brand bindings.
6. Enable live image for one accepted draft and inspect the package/UI.
7. Run one integrated functional smoke and the existing format/lint/type/test/build/Doctor/Compose
   gates. Record broader reliability/performance work in the hardening backlog.

Every child has a feature flag/worker gate and an operational disable path. Earlier capabilities
continue operating when later providers or documents are unavailable.

## 12. Key Trade-offs

- **Complete narrow MVP over placeholders:** every requested capability works, but only for one
  brand/audience/topic/draft/repair/image/reviewer path.
- **One content worker over many services:** lower operational overhead for MVP; typed job kinds and
  concurrency limits retain clear boundaries. Split only after measured contention.
- **PostgreSQL hybrid retrieval first:** reuses the approved stack and keeps evidence/brand controls
  inspectable; external search is deferred until measured quality/scale requires it.
- **Deterministic selection and validation:** more explicit configuration and fixtures, but prevents
  unexplained model ranking and unsupported copy.
- **No inline editor:** keeps the package immutable and auditable; staff copy/download for manual
  use. Collaborative editing is a later product capability.
- **Functional-first hardening:** the initial implementation includes upgrade-safe ports, schemas,
  versions, migrations, feature flags, essential idempotency, and critical security/evidence rules,
  but deliberately postpones exhaustive concurrency/chaos/performance/operations work until the
  business flow has been reviewed.
