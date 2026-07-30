# Implementation Context: Governance and Event Organization

This is the compact implementation/check context distilled from the full
`architecture-integration-audit.md`. Read the full audit when a referenced seam needs deeper
evidence.

## Existing seams to reuse

- Keep the existing API / scheduler / worker separation. Add governance planner/worker processes;
  never invoke Zhipu or LangGraph inside `AcquisitionExecutor`.
- Follow application-owned Protocol ports, short SQLAlchemy transactions, `SKIP LOCKED` leases,
  heartbeat/recovery, named uniqueness constraints, typed errors, and structured/redacted logs.
- Governance reads candidates, observations, snapshots, sources, and source versions directly
  through a repository. It never imports `SafeHttpFetcher` or re-crawls an original URL.
- Use the real PostgreSQL/pgvector integration fixture and generated OpenAPI/frontend contract
  flow. No SQLite or external vector database.

## Critical provenance rule

Acquisition can reuse one `evidence_candidates` row when identical content is observed from another
source. The new source still exists in `source_observations` and `source_snapshots`. Therefore:

- candidate content and source occurrence are separate governed entities;
- source diversity comes from stable observation/snapshot occurrences, not `candidate.source_id`;
- synchronize occurrences with an idempotent identity such as candidate + observation + snapshot
  + source item;
- preserve multiple sources in event APIs and acceptance tests even when content analysis is reused.

## Required derived model

Keep relational identity/provenance columns and use JSONB only for bounded variable metadata.
Essential responsibilities:

- governance runs/jobs/attempts with leases and safe outcomes;
- source occurrences;
- normalized articles and stable passages;
- candidate analyses, individual facts, evidence bindings, entities, and seven-label categories;
- purpose-specific near-duplicate and event-signature embeddings;
- duplicate relations with stored deterministic/semantic features;
- stable events, immutable event versions, memberships, and assignment decisions;
- safe model invocation metadata and durable LangGraph checkpoint tables.

Never overwrite acquisition candidates/snapshots. Every derivation key includes immutable input
hashes and controlling normalization/prompt/schema/taxonomy/provider/model/similarity/assignment
versions.

## LangGraph and provider boundary

- The database job lease is the outer work-ownership boundary; LangGraph handles typed resumable
  model-oriented nodes inside one job.
- Graph checkpoints contain IDs, hashes, versions, statuses, and small typed results only. Do not
  persist full source bodies, prompts, API keys, authorization headers, or raw provider responses.
- Keep application run/job tables as the operational/API source of truth; checkpoint tables are an
  internal orchestration detail.
- Use separate application ports for factual analysis and embeddings. Provider SDK/HTTP payload
  types stay in infrastructure.
- Verify and pin LangGraph PostgreSQL checkpointer and driver compatibility. The application uses
  asyncpg; an official saver may require psycopg and a separate validated connection URL.
- Provider calls are at-least-once across a crash, while artifact persistence is exactly-once by
  idempotency key and uniqueness constraint. Do not promise exactly-once billing.

## Analysis and evidence contract

- Normalize and segment stored clean text into bounded stable passages before a model call.
- The model returns supported structured facts and passage IDs. Deterministic validation rejects
  unknown passages/categories, quote/offset mismatch, invalid dates, dimension mismatch, excessive
  output, and unsupported claims.
- The approved taxonomy has seven versioned labels, supports multi-label output, and has an
  optional primary label.
- Treat fetched text and model output as untrusted. Delimit passages as data and test embedded
  prompt-injection instructions.

## Duplicate and event policy

- Exact duplicate signals include active derivation key, normalized SHA-256, canonical URL/source
  identity plus agreeing content, and explicit revision relations where hashes differ.
- Persist separate vectors for near-duplicate detection and event signatures. Validate one selected
  fixed embedding dimension before the migration.
- Start with exact distance over a bounded recent window; do not add HNSW/IVFFlat before measured
  corpus/query volume justifies it.
- Event candidate features include embedding similarity, SimHash distance, entity/category overlap,
  title tokens, and event-time distance.
- High-confidence matches attach, low matches create, and the gray band becomes review-required.
  Store thresholds/features/versions; do not ask an LLM for an unexplained final merge score.
- Serialize final assignment with a short lock/transaction and uniqueness constraints; membership
  changes create immutable event projection versions.

## Validation priorities

- Migration head/rollback ownership, fixed vector dimension, uniqueness, competing claims, lease
  recovery, checkpoint resume, and acquisition non-interference.
- Valid/invalid Zhipu output, hallucinated passage IDs, rate limit/timeout/5xx, retry exhaustion,
  prompt injection, credential/content redaction, and deterministic fake-only normal tests.
- Exact copy, same-event paraphrase, similar-but-distinct events, conflicting dates/entities,
  ambiguous review, concurrent assignment, idempotent replay, and two sources sharing one candidate.
- End-to-end stored candidate/occurrences -> analysis/evidence -> duplicate/event -> API, plus
  OpenAPI/frontend drift, Compose/Doctor, final credential scan, and one opt-in bounded live smoke.
