# Architecture Integration Audit: Data Governance and Event Organization

## Scope and conclusion

This audit covers only the second capability described in `prd.md`: stored-evidence loading,
versioned normalization, deterministic and semantic duplicate handling, structured factual
analysis, evidence binding, incremental event organization, durable LangGraph execution, a typed
Zhipu provider boundary, and internal query APIs. Brand knowledge, topic eligibility/scoring,
copy/image generation, additional acquisition sources, arbitrary browsing, and product frontend
pages remain out of scope.

The existing backend is a sound base for this capability. It already has the important process and
persistence patterns: immutable acquisition artifacts, short SQLAlchemy transactions, PostgreSQL
job leases, typed application ports, centralized settings/errors, generated OpenAPI, and real
PostgreSQL/MinIO integration tests. The second capability should be added as a separate governance
workflow and worker, not inserted into the acquisition executor.

The most important integration finding is that a governance input is not equivalent to a row in
`evidence_candidates`. Acquisition deliberately reuses an existing candidate when the same body is
seen from another source. The new source occurrence survives in `source_observations` and
`source_snapshots`. Governance must therefore model both:

1. a content-bearing candidate, which can be normalized/analyzed once; and
2. one or more source occurrences, which preserve every source, URL, snapshot, and observation.

If the second capability reads only `EvidenceCandidateModel.source_id`, source diversity and
multi-source event evidence will be undercounted.

The user has accepted the recommended seven-label factual taxonomy. It should be implemented as a
versioned, multi-label taxonomy with one optional primary label, rather than as a PostgreSQL enum.

## Code-backed current-state findings

### Reusable architecture patterns

- The implemented process boundary is API / scheduler / worker. The API only enqueues durable work,
  while the worker claims jobs and performs side effects. This is documented in
  `.trellis/spec/backend/directory-structure.md` and implemented by
  `backend/app/api_main.py:37-49`, `backend/app/scheduler_main.py`, and
  `backend/app/worker_main.py:22-58`.
- Application ports are Python protocols with provider-independent dataclasses
  (`backend/app/application/ports/acquisition.py:17-149`). The governance capability should reuse
  this dependency direction for repositories, factual-analysis models, embedding models, clocks,
  and checkpoint/runtime adapters.
- The acquisition repository uses short-lived sessions per operation
  (`backend/app/infrastructure/db/repositories.py:885-1040`). Job claiming uses
  `FOR UPDATE SKIP LOCKED`, a lease token, expiry, and heartbeat
  (`backend/app/infrastructure/db/repositories.py:201-345`). These are directly reusable semantics
  for governance jobs, but governance must have its own tables and repository.
- External fetch work is performed outside transactions and persistence is split into idempotent
  steps (`backend/app/application/services/execute_acquisition.py:90-267`). Governance model calls
  and embedding calls must follow the same pattern.
- Database inserts use named unique constraints plus `ON CONFLICT`, rather than check-then-insert as
  the sole race defense (`backend/app/infrastructure/db/repositories.py:438-562`). Every derived
  governance artifact should have an equivalent database business key.
- Application errors carry stable codes and retryability (`backend/app/core/errors.py:6-63`), and
  the API translates them through one handler (`backend/app/api_main.py:60-63`). Provider adapters
  should translate Zhipu/network errors into application-owned provider errors instead of leaking
  provider exception strings.
- Settings use Pydantic `SecretStr` and validated cross-field invariants
  (`backend/app/core/config.py:8-87`). Zhipu configuration should extend this model and keep the API
  key out of string representations, logs, task artifacts, and OpenAPI.
- PostgreSQL 16/pgvector is already provisioned by `compose.yaml:3-24` and
  `infra/postgres/init/001-enable-vector.sql:1`. The Python `pgvector` dependency is already present
  in `backend/pyproject.toml:10-28`.
- Real-database integration tests create an isolated PostgreSQL database and migrate it to head
  (`backend/tests/integration/conftest.py:29-53`). Vector constraints, similarity queries,
  concurrency, checkpoint recovery, and event assignment must be tested through this fixture, not
  SQLite.
- OpenAPI is generated and checked through `Makefile:49-55`, and frontend contract drift is part of
  `Makefile:110-111`. New internal governance APIs therefore imply regenerated
  `backend/openapi.json` and frontend types, but no new product screen.

### Stored-evidence handoff is already safe

- A candidate contains cleaned full text, original and canonical URLs, publication/fetch times,
  language, content hash, parser/relevance versions, extraction metadata, and a required primary
  snapshot foreign key (`backend/app/infrastructure/db/models.py:324-378`).
- The detail endpoint returns stored `clean_text`, snapshot metadata, and observations without a
  source fetch (`backend/app/api/v1/routes/evidence_candidates.py:69-110`). The no-refetch behavior
  is covered by `backend/tests/integration/test_title_relevance_ingestion.py:206-246`.
- Source snapshots are immutable provenance rows whose object bytes may be shared while response
  provenance remains distinct (`backend/app/infrastructure/db/models.py:287-321` and
  `backend/alembic/versions/20260728_0002_snapshot_provenance.py:34-79`).

Governance should normally read candidates, observations, and snapshot metadata through a direct
`GovernanceInputRepository`; it does not need to call the project's own HTTP API. The API remains
the inspection contract, while the repository is the internal processing seam. No governance node
should import or instantiate `SafeHttpFetcher`.

### Critical provenance seam: candidate content versus source occurrence

`persist_candidate` computes a hash over acquisition `clean_text`. When it finds the same hash on a
different source/item, it returns the pre-existing candidate and the outcome `exact_duplicate`
instead of inserting another candidate (`backend/app/infrastructure/db/repositories.py:491-522`).
The new observation still stores the current source version, source item, snapshot, and reused
candidate ID (`backend/app/infrastructure/db/models.py:381-426` and
`backend/app/infrastructure/db/repositories.py:565-605`). The snapshot retains the duplicate
source's original/final URL and response metadata (`backend/app/infrastructure/db/models.py:287-313`).

Consequences:

- `candidate.source_id` is the owner of the retained content record, not a complete list of all
  sources that published the content.
- Governance source diversity must be calculated from governed source-occurrence records derived
  from observations/snapshots, not from candidate rows alone.
- Repeated acquisition runs can produce multiple observations for the same occurrence. A governed
  occurrence needs a stable identity such as `(candidate_id, snapshot_id, source_item_id)` and an
  idempotent unique constraint.
- The current HTTP observation schema exposes neither `source_version_id` nor `source_item_id`, and
  returns only the candidate's primary snapshot (`backend/app/schemas/evidence.py:44-59`). Either
  extend the inspection API or have the governance input repository join observations, snapshots,
  source versions, and sources. The latter is required regardless for efficient batch processing.

This is not a reason to rewrite acquisition history. Add a versioned governance occurrence layer
and preserve the existing immutable candidate/snapshot/observation records.

### Acquisition `content_hash` is an input signal, not the final governed hash

The current hash is computed directly from connector-produced `clean_text`
(`backend/app/infrastructure/db/repositories.py:501`). It has no normalization-policy version. The
second capability must persist its own normalized text hash with its normalization version and
input candidate hash. Do not overwrite `EvidenceCandidateModel.clean_text` or `content_hash`.

Canonical URL and source item ID also require careful interpretation: the same source item with a
different content hash can be a corrected revision, not an exact duplicate. Persist deterministic
signals and a typed relation (`same_content`, `same_url`, `same_source_item`, `revision_of`) rather
than collapsing all signals into one boolean.

## Recommended package and process boundaries

Extend the current real layout without changing acquisition ownership:

```text
backend/app/
├── application/
│   ├── ports/governance.py            # repositories and typed model ports
│   ├── services/enqueue_governance.py # run/job creation
│   ├── services/execute_governance.py # claim + graph invocation boundary
│   └── workflows/governance_graph.py  # LangGraph state and node wiring
├── domain/
│   ├── governance_entities.py
│   ├── governance_enums.py
│   ├── normalization.py
│   ├── duplicate_policy.py
│   └── event_assignment.py
├── infrastructure/
│   ├── db/governance_repositories.py
│   └── models/zhipu.py                # provider-specific HTTP/payload mapping
├── schemas/
│   ├── governance.py                  # HTTP projections
│   └── factual_analysis.py            # strict model-output schemas
├── api/v1/routes/
│   ├── governance_runs.py
│   ├── candidate_analyses.py
│   └── events.py
└── governance_worker_main.py
```

For the MVP, ORM mappings may remain in the existing `infrastructure/db/models.py` so there is one
metadata registration path, while governance query/write logic should go into a separate repository
module. A future model-package split should be deliberate; do not mix that refactor into the first
governance migration unless file size becomes an immediate blocker.

Add a separate `governance-worker` process/container. Do not call LangGraph inside
`AcquisitionExecutor`, and do not give the acquisition worker Zhipu credentials. A lightweight
governance scheduler can poll terminal acquisition runs that do not yet have a governance run and
enqueue them using a unique `(acquisition_run_id, governance_profile_fingerprint)` key. A manual
`POST /governance-runs` remains useful for fixture, replay, and acceptance work.

## Proposed durable data model

Names can be refined in design, but the following responsibilities should remain distinct.

| Entity | Purpose and essential contract |
|---|---|
| `governance_runs` | One manual or acquisition-run-triggered batch. Stores trigger, source acquisition run/cutoff, timezone, complete governance profile fingerprint, status/counters, and timestamps. Unique scheduled/input business key. |
| `governance_jobs` | One candidate per governance run, with lease/heartbeat/attempt/retry fields. It synchronizes all source occurrences for that candidate even when content derivation already exists. Unique `(run_id, candidate_id)`. |
| `governance_attempts` | Attempt history with stage/node, safe result/error code, token/latency counts, and timestamps. Do not overload acquisition attempt rows. |
| `article_occurrences` | Durable governed projection of every source occurrence. References candidate, observation, snapshot, source/source version, source item, original/final URL, publication/fetch times, and trust tier. Unique stable occurrence identity; never use candidate source alone for diversity. |
| `normalized_articles` | Versioned derived text for a candidate. Stores input content hash, normalization version, normalized hash, SimHash, normalized text or immutable object reference, language, and timestamps. Unique `(candidate_id, input_hash, normalization_version)`. |
| `normalized_passages` | Deterministically segmented paragraphs/spans. Stores article ID, ordinal/stable passage ID, text/hash, and offsets back to acquisition `clean_text`. These are the only passage IDs offered to the model as support. |
| `candidate_analyses` | Schema-validated factual analysis and invocation metadata: normalized article, prompt/schema/taxonomy versions, provider/model, request fingerprint, status, summary, event-time range/precision, token/latency/provider request ID, and safe validation outcome. Unique processing key. |
| `analysis_facts` | Individual factual statements, not an opaque summary blob. Stores analysis ID, ordinal, text, event time/precision where applicable, and status. |
| `evidence_bindings` | Relational binding from every accepted fact/summary statement to a normalized passage, candidate, snapshot/source occurrence, exact quote/offsets, and validation result. This is required for the later scoring/generation handoff. |
| `analysis_entities` | Versioned extracted mentions/canonical names with type and support passage. Canonicalization must not erase the source mention. |
| `analysis_categories` | Seven-label taxonomy assignments with taxonomy version, primary flag, and bounded confidence. Validated text/check constraint is preferable to a DB enum. |
| `article_embeddings` | Purpose-specific vectors (`near_duplicate`, `event_assignment`) with provider, model, dimension, input hash, truncation/normalization version, and vector. Unique by artifact purpose/configuration. |
| `duplicate_relations` | Canonically ordered article pair, relation kind, deterministic/semantic features, policy/version/threshold, outcome, and optional supersession. Evidence is retained; rows are never a deletion instruction. |
| `event_clusters` | Stable event identity and lifecycle/current-revision pointer. It does not contain an unversioned mutable prose truth. |
| `event_cluster_versions` | Versioned representative title, structured summary projection, time range/precision, member-set hash, taxonomy/entity projection, clustering policy, and created-by run. |
| `event_memberships` | Article-to-event membership with active/superseded state, assignment-decision ID, source occurrences, and version metadata. Enforce at most one active event per governed article for the current policy. |
| `event_assignment_decisions` | Auditable assignment features: bounded candidate event IDs, vector scores, entity/category/time overlap, thresholds, selected/new/review outcome, and policy/model versions. |
| `model_invocations` | Optional shared audit row if invocation metadata would otherwise be duplicated. Stores request fingerprint and safe metadata, never the API key, authorization header, complete prompt/body, or raw provider exception. |

Core foreign keys, status, membership, and evidence bindings belong in relational columns. JSONB is
appropriate for bounded feature maps, provider usage metadata, and immutable schema output, but it
must not replace the candidate/snapshot/passage/event foreign-key path.

### Vector design

- Use a fixed dimension encoded in both settings and the migration. Reject a response whose length
  differs from that dimension before persistence.
- Store separate vectors by purpose. A full-article/lead representation can support near-duplicate
  detection, while an event signature built from title, supported facts, entities, categories, and
  event time is a better input for event assignment. One generic article vector is likely to merge
  topically similar but distinct events.
- Do not create HNSW/IVFFlat purely by habit. The initial corpus is tiny; start with an exact
  bounded recent-window scan and add an index only after representative volume/query measurement,
  as required by `.trellis/spec/backend/database-guidelines.md:105-115`.
- Ensure the new Alembic revision makes the `vector` extension requirement explicit and extend the
  clean-head integration test. The existing Docker init script alone does not prove an externally
  provisioned database has the extension.

## Recommended LangGraph workflow

LangGraph should orchestrate model-oriented resumable steps; the database job lease remains the
outer work-ownership boundary.

```text
load_stored_evidence
  -> sync_source_occurrences
  -> normalize_and_segment
  -> deterministic_identity_and_exact_dedup
  -> reuse_existing_derivation? ----------------------+
  -> factual_analysis_model                           |
  -> validate_schema_and_evidence                     |
  -> embed_for_near_duplicate                         |
  -> decide_near_duplicate                            |
  -> build_and_embed_event_signature                  |
  -> retrieve_recent_event_candidates                 |
  -> assign_new_existing_or_review                    |
  -> persist_event_projection <-----------------------+
```

The graph state should contain IDs, hashes, versions, statuses, and small typed outputs. Do not put
complete source bodies, API keys, authorization headers, or complete provider prompts in durable
checkpoint state. Nodes load the required stored passages through ports by ID.

Compile the graph with a durable PostgreSQL checkpointer. The official PostgreSQL checkpointer is
preferable to an improvised in-memory saver, but its pinned version/driver requirements must be
validated: the current application uses SQLAlchemy async + `asyncpg`, while LangGraph PostgreSQL
checkpoint packages commonly use `psycopg`. If the official async saver introduces `psycopg`, treat
that as an explicit second DB driver, configure it separately, and integration-test setup/resume.
Do not silently reuse an `asyncpg` URL with an incompatible saver.

Keep application-owned `governance_runs/jobs/attempts` as the API and operational source of truth.
LangGraph checkpoint tables are an internal orchestration detail and should not be queried directly
by routes. Record a node transition before/after work in application tables even when a checkpoint
exists so operators can inspect safe state without understanding LangGraph internals.

### Idempotency and restart semantics

Each node derives an idempotency key from its immutable input IDs/hashes and every controlling
version. Before work, it checks for an already successful artifact with that key; persistence uses
a matching database unique constraint. Replaying the same graph then returns artifact IDs instead
of creating a second analysis/vector/relation/membership.

Provider calls are necessarily at-least-once across a crash between provider success and local
commit. The system can guarantee exactly-once artifact persistence, not exactly-once external
billing. Persist the request fingerprint and provider request ID when available, and reuse a
completed result; never claim stronger semantics than the provider supports.

Typed retry policy should distinguish:

- retryable: timeout, temporary 429/5xx, transient network/provider unavailability, lost job lease
  before persistence;
- non-retryable/reviewable: invalid credentials, unsupported model, invalid JSON after bounded
  repair, unsupported evidence, unknown category, quote/passage mismatch, dimension mismatch, and
  prompt-injection-driven invalid output;
- review transition: ambiguous event match, conflicting event identity/time/entity, or similarity
  in a configured gray band.

## Structured factual-analysis boundary

Use two application-owned ports rather than allowing domain/workflow code to import a Zhipu SDK:

```python
class FactualAnalysisModel(Protocol):
    async def analyze(self, request: FactualAnalysisRequest) -> ModelResult[FactualAnalysisDraft]: ...

class EmbeddingModel(Protocol):
    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult: ...
```

Separate ports allow different Zhipu models or a future provider per capability without rewriting
normalization, duplicate, or event logic. Deterministic tests inject fakes. Provider-specific JSON,
HTTP headers, response parsing, retry headers, and exception mapping stay in
`infrastructure/models/zhipu.py`. The existing `httpx` dependency is sufficient for an
OpenAI-compatible HTTP adapter if that is the selected and verified Zhipu contract; adding a vendor
SDK should require a documented reason.

Recommended settings are explicit rather than overloading the existing generic placeholders:

- provider mode (`disabled`/`zhipu`, with tests using injected fakes);
- Zhipu base URL and `SecretStr` API key;
- factual-analysis model and embedding model IDs;
- embedding dimension;
- connect/read/total timeouts;
- max attempts/backoff, provider concurrency, per-request token limit, and per-run token/cost cap;
- prompt, schema, taxonomy, normalization, embedding-input, duplicate-policy, and clustering-policy
  versions.

Only the governance worker needs the Zhipu API key. Do not add it to the shared Compose environment
anchor inherited by API, scheduler, and acquisition worker (`compose.yaml:76-103`). A live provider
smoke test is opt-in; normal health, unit, integration, and OpenAPI tests must pass without a key.

### Model input/output contract

The model receives numbered, bounded stored passages and metadata, not a URL to browse and not an
unbounded full webpage. Fetched text is placed in an explicitly delimited untrusted-data section.
Page instructions have no workflow authority.

Use strict Pydantic v2 output models with `extra="forbid"`, length/count limits, the approved
taxonomy, and passage references. A useful shape is:

- concise factual summary plus supporting passage IDs;
- key facts, each with support passage IDs/exact quote and optional event time;
- entities with type, source mention, canonical form, and support passage;
- event-time range and precision (`exact`, `day`, `month`, `unknown`);
- one primary and zero or more secondary categories from taxonomy version `ai-factual-taxonomy-v1`;
- uncertainty/conflict flags.

The seven initial category codes should represent:

1. AI education policy;
2. large/generative models;
3. robotics and embodied intelligence;
4. AI compute and chips;
5. youth science education;
6. AI industry and applications; and
7. AI governance and safety.

The deterministic gate verifies schema, category membership, passage existence, exact quote/offset,
candidate/snapshot ownership, timestamp bounds, vector dimension, count/length limits, and that
every exposed factual item has at least one binding. Unsupported output is persisted as an invalid
attempt, not partially accepted. Semantic entailment cannot be proven by a JSON schema alone, so a
labeled evaluation set must measure support quality; do not market schema validation as proof that
the model cannot hallucinate.

## Duplicate and incremental event policy

### Duplicate decision order

1. Synchronize all occurrences and compute versioned normalized text/passages.
2. Record deterministic signals: canonical URL identity, source item identity, normalized SHA-256,
   and SimHash distance.
3. `normalized_hash` equality is an exact-content relation. The same source item/URL with changed
   content is normally a revision relation and still receives a new derived artifact.
4. Retrieve a bounded set of semantic candidates and evaluate a versioned near-duplicate policy.
5. Preserve every candidate/occurrence and store the relation/decision; never delete the secondary
   evidence row.

Near-duplicate and same-event are different decisions. A rewritten syndication may be a near
duplicate; two substantially different reports can still be members of the same event. Conversely,
two articles about the same technology but different announcements must remain separate events.

### Event assignment

- Search only a configured recent window using event time when known and publication/fetch time as
  a fallback. Persist the window and cutoff used in each decision.
- Use event-signature similarity together with entity overlap, category compatibility, and time
  compatibility. Thresholds and weights must come from a versioned policy evaluated against labeled
  fixtures; they should not be guessed in a prompt.
- Avoid transitive chaining drift (`A~B`, `B~C`, but `A` does not describe the same event as `C`).
  Compare with a versioned event representative/centroid and enforce entity/time constraints.
- Serialize or lock the final assignment transaction. Parallel extraction/embedding is safe, but
  concurrent workers can otherwise create two events for the same new report. For the initial
  volume, one event-assignment lane or a tested PostgreSQL advisory/event-window lock is preferable
  to premature complex concurrency.
- Persist one of `assigned_existing`, `created_new`, or `review_required`, plus the top bounded
  alternatives and features. The absence of a review UI does not justify a forced cluster; expose a
  reviewable API projection.
- Conflicting dates/entities remain source-specific facts with conflict flags. Do not overwrite one
  source with another or synthesize a false consensus.

For the initial event summary, a deterministic projection from supported member analyses is safer
than an extra free-form event-synthesis call: choose a stable representative title, deduplicate
supported facts, retain source-specific conflicts, and bind every projected fact. If an event-level
model call is later introduced, it needs the same typed schema and evidence gate.

## Internal API handoff

Recommended minimum endpoints:

- `POST /api/v1/governance-runs` -> `202`, accepting either an acquisition run ID or bounded
  candidate IDs plus an idempotency key;
- `GET /api/v1/governance-runs/{id}` and `/jobs` or `/stages`;
- `GET /api/v1/evidence-candidates/{id}/analysis` with versions, facts, passages, relations, event
  membership, and safe failures;
- `GET /api/v1/duplicate-relations` with bounded filters;
- `GET /api/v1/events` with cursor/time/category/source filters;
- `GET /api/v1/events/{id}` with current version, member candidates, all source occurrences,
  evidence bindings, assignment decisions, and conflict/review state.

List projections must not return complete article bodies, vectors, prompts, provider payloads, or
checkpoint state. The detail endpoints may return approved evidence excerpts with source URLs and
snapshot/candidate IDs. This event projection should be sufficient for the third capability to
score topics without another source request or summarization call.

## Risks and mitigations

| Risk | Code-backed reason | Mitigation |
|---|---|---|
| Under-counted source diversity | Cross-source exact content reuses a candidate (`repositories.py:511-521`) | Build `article_occurrences` from observations/snapshots and base event source diversity on occurrences. |
| Duplicate derivations under retry/concurrency | Existing candidate read-then-insert logic is backed by a unique constraint; new artifacts do not yet exist | Give every derived artifact a database business key and use conflict-safe insert/upsert. |
| Holding DB transactions across model calls | Current acquisition correctly avoids this; a monolithic graph node could regress it | Repository operations before/after provider call; checkpoint state contains IDs only. |
| LangGraph checkpoint mismatch with asyncpg | No LangGraph/checkpointer dependency exists in `pyproject.toml`; current DB runtime is asyncpg | Pin and integration-test the chosen PostgreSQL saver/driver, or explicitly implement a compatible saver; never fall back to memory in production. |
| Secret overexposure | Compose currently shares one environment anchor across all backend services | Give Zhipu secrets only to the governance worker and redact settings/provider errors. |
| Unsupported model output accepted as partial truth | Current code has no structured model-output gate | Strict Pydantic schema plus deterministic passage/quote/category/version validation; atomic artifact acceptance. |
| Topical clustering merges distinct events | A single generic article embedding overweights broad topic similarity | Separate event-signature embeddings and require entity/time/category compatibility with a review band. |
| Event split under parallel workers | Incremental cluster creation is a shared mutable decision | Serialize final assignment or use tested locks and conflict-safe creation. |
| Vector dimension/model change corrupts search | Dimension is not yet configured in the codebase | Encode dimension in migration/settings/artifact metadata and re-index through a new version, never in-place overwrite. |
| Checkpoints leak source bodies/prompts | LangGraph state is often serialized wholesale | Store artifact IDs/hashes in state; never full bodies, credentials, authorization, or full prompts. |
| False confidence in six live articles | The report run is too small for clustering evaluation | Combine controlled labeled pairs/clusters with accumulated live candidates and publish measured quality. |
| Scope creep into scoring/brand/generation | The technical report has adjacent future stages | Keep event API factual/brand-neutral; no scores, Top-1, brand embeddings, copy, images, or frontend pages in this task. |

## Validation implications

### Unit and contract tests

- Normalization: Unicode/whitespace/boilerplate/time normalization, stable passages and source
  offsets, input-hash/version sensitivity, and idempotent replay.
- Deterministic relations: normalized hash, canonical URL, source item revision, SimHash boundaries,
  canonical pair ordering, and preservation of both occurrences.
- Structured output: valid seven-label multi-label output; extra/missing fields; invalid JSON;
  unknown label; missing passage; wrong quote/offset; unsupported entity/date; excessive sizes; and
  prompt-injection text that attempts to change instructions.
- Provider adapter: typed mapping for 2xx, 401/403, 429 with retry metadata, timeout, 5xx, malformed
  payload, dimension mismatch, and redaction. Use a fake transport/server; no live key.
- Event policy: paraphrases of one event, same topic/different event, time/entity conflicts, gray-band
  review, stable representative selection, no transitive-chain merge, and deterministic tie breaks.
- LangGraph state: serializable ID-only state and node short-circuit when an artifact already exists.

### Real PostgreSQL integration tests

- Alembic clean upgrade to the new head, explicit `vector` extension assertion, vector column
  dimension/round trip, and documented downgrade behavior.
- Governance run/job uniqueness, competing worker claim/lease/heartbeat/reclaim, stale-worker fencing,
  and terminal run aggregation.
- Concurrent insert tests for normalized artifacts, model results, embeddings, duplicate pair
  decisions, occurrence synchronization, and event membership.
- Exact acquisition duplicate fixture proving two sources/snapshots become two governed occurrences
  even though they share one candidate ID.
- Bounded vector/event candidate retrieval and metadata/time filtering.
- Final assignment race test proving one event is created, or one assignment is deterministically
  selected, under concurrent workers.
- Durable checkpoint interruption after model analysis and after embedding; restart resumes at the
  next incomplete node and does not duplicate accepted artifacts or re-run acquisition.

### API/OpenAPI tests

- `202` enqueue/location/idempotency semantics and stable error envelopes.
- Run/job/node status, retry-safe failures, candidate analysis, duplicate relation, event list/detail,
  all source occurrences, evidence bindings, version fields, and review state.
- No complete source body, vector, prompt, API key, authorization header, raw provider exception, or
  LangGraph checkpoint in list/detail responses.
- Regenerated `backend/openapi.json` and frontend `schema.d.ts` must be drift-free even though no
  frontend page is added.

### Labeled evaluation and live acceptance

Build a committed, non-sensitive labeled fixture corpus that covers exact copies, controlled
paraphrases, same-event multi-source reports, similar but distinct events, conflicting facts,
prompt injection, invalid JSON, and restart/idempotency. Report at least:

- schema-valid and evidence-bound extraction rate;
- unsupported-fact/binding failure count;
- exact/near-duplicate precision and recall;
- same-event pairwise precision/recall/F1 (and review rate);
- distinct-event false-merge count;
- stage success, latency, retries, tokens, and estimated cost.

The first live acquisition run's six candidates can exercise the workflow but cannot establish
clustering quality. Live Zhipu acceptance must be explicitly enabled, use credentials from local
environment/deployment secrets, record only safe IDs/counts/usage, and never become part of the
ordinary automated test suite.

## Suggested independently verifiable implementation nodes

This sequence matches the user's estimate of roughly one working day per major node:

1. **Persistence and input boundary:** migration, governance runs/jobs/attempts, occurrence
   synchronization, versioned normalization/passages, exact relations, and focused PostgreSQL tests.
2. **Factual model workflow:** typed ports, fake provider, Zhipu adapter/config, LangGraph/checkpoint
   shell, strict factual schemas, evidence bindings, retry/resume tests.
3. **Semantic duplicate layer:** purpose-specific embeddings, pgvector repository, SimHash/semantic
   policy, labeled duplicate fixtures, and provider contract tests.
4. **Incremental event organization:** recent-window retrieval, assignment policy/locking, stable
   event versions/memberships/decisions, conflict/review behavior, and clustering evaluation.
5. **Queryable handoff and integrated gate:** run/analysis/relation/event APIs, OpenAPI/frontend
   contract regeneration, interruption/idempotency acceptance, opt-in live Zhipu smoke, metrics,
   and final quality/report handoff.

Do not reduce the fifth node to compensate for earlier schedule pressure; it is the stage that
proves the second capability is reproducible and safe enough to feed topic scoring.
