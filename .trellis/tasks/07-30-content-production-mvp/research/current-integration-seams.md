# Current Integration Seams for the Content Production MVP

Date: 2026-07-30

## Existing production-shaped foundations

- Acquisition and factual governance/event organization are complete. The current schema head is
  `20260729_0004`, and the final backend gate passed 201 tests with 87% coverage.
- `event_clusters`, immutable `event_cluster_versions`, `event_memberships`, candidate analyses,
  facts, passages, evidence bindings, occurrences, assignment decisions, and purpose-specific
  embeddings already provide the stored input needed by topic selection.
- FastAPI owns enqueue/query APIs; acquisition and governance schedulers/workers are separate
  processes. New model work must preserve that boundary.
- LangGraph and PostgreSQL checkpoints are available for resumable model-oriented workflows.
  Business run/job tables remain the operational/API source of truth.
- PostgreSQL 16 with pgvector 0.8.1 is the approved evidence and brand vector store. MinIO is the
  approved object store for immutable source snapshots and future brand originals/generated images.
- The current Zhipu adapter supports bounded structured chat and `embedding-3` with a fixed 2048
  dimension, safe telemetry, explicit gzip handling, deterministic fakes, and typed failures.
- The frontend is a React/TypeScript/Vite shell with TanStack Query, generated OpenAPI types,
  accessibility tests, clipboard feedback, and no existing product feature tree.

## Reusable patterns

- Run/job/attempt status, unique business keys, claims, leases, heartbeats, bounded retries, stale
  worker fencing, and short transactions from acquisition/governance.
- Application-owned Protocol ports with provider-specific adapters under `infrastructure/`.
- Version bundles and request fingerprints rather than mutation of previous derived artifacts.
- Pydantic v2 schemas at HTTP and model-output boundaries.
- Safe provider logging: IDs/models/versions/counts/tokens/latency only; no full bodies, prompts,
  hidden reasoning, credentials, raw exceptions, or vectors.
- Generated OpenAPI/frontend types and tiered verification: focused loops, then one final complete
  gate after the last production edit.

## Gaps owned by this program

- No topic eligibility/score/selection tables, services, daily scheduler, or APIs.
- No brand document/chunk/embedding domain, file-upload surface, parsing adapters, hybrid retrieval,
  or activation/version lifecycle.
- No draft/claim/binding schemas, content model ports, deterministic validator, audit port, repair
  workflow, or associated durable artifacts.
- No image provider port, generated-image object lifecycle, material package projection, download
  endpoint, or internal product UI.
- Existing backend/frontend specs still describe these capabilities prospectively and must be
  updated as each child task lands real contracts.

## Planning decisions

- Use a parent program with four sequential, independently verifiable child tasks. The parent is
  not the implementation target; each child is planned, reviewed, started, checked, committed, and
  archived in dependency order.
- Reuse PostgreSQL/pgvector and MinIO; do not add an external vector database or another object
  store.
- Add one content scheduler and one content worker for the MVP. The content worker may claim both
  brand-ingestion jobs and daily material jobs through typed repositories, while concurrency and
  job-kind limits prevent image/model latency from affecting acquisition/governance.
- Keep topic scoring deterministic. Models may extract/generate/audit but may not produce an
  unexplained selection score or override vetoes.
- Use separated evidence and brand retrieval types, tables, prompts, and bindings.
- Use one automatic repair and one image. Manual review/copy/download is the terminal product
  boundary; no automated publishing exists.
- Deliver the functional happy path first in approximately 4--5 working days. Keep versioned ports,
  migrations, schemas, feature flags, and critical idempotency/security/evidence rules now; defer
  exhaustive resilience, scale, evaluation depth, and production operations until after product
  review.

## Technical research deferred to owning child

- Exact initial scoring ranges/weights/penalties/threshold and labeled evaluation set. The user
  approved an implementation-proposed `scoring-v1` followed by real-data review before defaulting.
- Exact PDF/DOCX/TXT/Markdown parser dependencies, upload byte/page limits, and safe malformed-file
  behavior.
- Hybrid retrieval fusion constants and reranking cutoff; PostgreSQL `ts_rank` must not be called
  BM25.
- Zhipu/company image endpoint, model identifier, output format, dimensions, moderation/error
  behavior, and account compatibility. The live API key remains external to Git and task artifacts.
- Final brand copy lengths, banned phrases, examples, and visual constraints derived from the user-
  supplied brand corpus. Safe conservative defaults may support controlled tests but cannot replace
  live brand acceptance.

## External input timing

- Child 1 can start without brand/image input.
- Child 2 needs representative brand documents before live retrieval acceptance.
- Child 3 needs brand rules/examples before live copy/audit acceptance.
- Child 4 needs visual guidance/assets and image-provider compatibility before live image/package
  acceptance.
