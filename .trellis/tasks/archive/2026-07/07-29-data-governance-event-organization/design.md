# Design: Data Governance and Event Organization

## 1. Design Intent

Build the second capability as a durable transformation layer between authoritative-source
acquisition and later topic scoring. It converts immutable evidence candidates into versioned
factual analyses, duplicate relations, and auditable event clusters. It does not browse the web,
rank topics, ingest brand knowledge, or generate user-facing copy.

The capability remains one Trellis implementation task rather than a parent with four child tasks.
Normalization, model analysis, embeddings, clustering, and event APIs share one migration family,
one pipeline-version contract, one idempotency model, and one end-to-end acceptance flow. Splitting
them before those contracts exist would create partially useful children and move the highest risk
into integration. `implement.md` therefore uses independently verifiable daily milestones and
rollback gates inside one task.

## 2. Existing Integration Seams

- `EvidenceCandidateModel` already stores immutable candidate identity, source/version, URLs,
  title, cleaned text, publication/fetch time, content hash, parser/relevance versions, extraction
  metadata, and the primary snapshot reference in
  `backend/app/infrastructure/db/models.py:324`.
- Acquisition can reuse that candidate row when identical content is observed from another source;
  the additional source occurrence remains in `source_observations` and `source_snapshots`.
  Governance therefore loads both candidate content and all stable source occurrences instead of
  treating `candidate.source_id` as the complete provenance set.
- Candidate detail is already queryable through
  `backend/app/infrastructure/db/repositories.py:861` and the evidence route; governance uses the
  same repository-level projection rather than another source fetch.
- The acquisition port/adapter split in
  `backend/app/application/ports/acquisition.py:40` and the independent worker composition in
  `backend/app/worker_main.py:22` provide the process and dependency-injection pattern to reuse.
- Settings already contain secret-safe AI platform placeholders in
  `backend/app/core/config.py`; this task expands them into validated provider/model settings.
- PostgreSQL/pgvector is already provisioned by `compose.yaml`; no external vector database is
  introduced.
- Existing quality rules require SQLAlchemy 2 async mappings, Alembic-only schema changes, typed
  errors, structured/redacted logs, real PostgreSQL integration tests, generated API contracts, and
  one final complete gate after focused development loops.

## 3. Runtime Architecture

```text
completed acquisition run / manual request
                 |
                 v
       Governance Run Planner
   unique(acquisition_run, pipeline_version)
                 |
                 v
       PostgreSQL governance jobs
       claim / lease / retry / heartbeat
                 |
                 v
       Governance Worker process
                 |
                 v
     LangGraph candidate workflow
       |     |       |       |
       |     |       |       +--> event assignment / review
       |     |       +----------> embedding + near-duplicate candidates
       |     +------------------> Zhipu structured factual analysis
       +------------------------> deterministic normalization / exact dedup
                 |
                 v
 PostgreSQL analyses, passages, relations, events, memberships, versions
                 |
                 v
       internal analysis/event APIs
                 |
                 v
      later topic eligibility/scoring
```

### Process boundaries

- `app.governance_scheduler_main` reconciles terminal acquisition runs into governance runs. It
  never invokes the model itself. A unique business key prevents two schedulers from enqueueing the
  same acquisition run for the same pipeline version.
- `app.governance_worker_main` claims persisted candidate jobs, renews leases, executes one
  LangGraph thread per job, and handles graceful shutdown. It is a separate service from the
  acquisition worker so provider latency cannot block source collection.
- The existing FastAPI process exposes enqueue/status/query routes only. Requests return durable
  IDs and never perform model analysis inline.
- PostgreSQL remains the source of truth for operational state and derived artifacts. LangGraph
  checkpoints persist resumable node state; they do not replace run/job status or domain records.
- Checkpoint state contains IDs, hashes, versions, statuses, and small typed outputs only. Nodes
  reload passages by ID; full source bodies, prompts, provider responses, and credentials never
  enter durable graph state.

### Automatic trigger

The planner selects terminal acquisition runs that have no governance run for the active pipeline
version. It creates one job per candidate ID observed by that run and synchronizes every occurrence
identity `(candidate_id, observation_id, snapshot_id, source_item_id)`, even when content analysis
can reuse an existing derivation. Jobs skip provider work only when the same immutable input hash
and version bundle already succeeded. Manual enqueue remains available for replay, testing, or a
selected candidate set.

## 4. Pipeline and LangGraph State

### Version bundle

Every job resolves one immutable version bundle before execution:

- `pipeline_version`
- `normalization_version`
- `passage_schema_version`
- `taxonomy_version`
- `prompt_version`
- `analysis_schema_version`
- chat provider/model identifier
- embedding provider/model identifier and returned dimension
- `similarity_rule_version`
- `event_assignment_version`

The job idempotency key is derived from candidate ID, candidate content hash, and the complete
version bundle. Changing a prompt/model/rule creates a new derivation; it never mutates an older
result.

### Candidate graph

```text
load_candidate
  -> sync_source_occurrences
  -> normalize_and_segment
  -> exact_duplicate_gate
       -> reuse_existing_derivation ---------------------+
       -> structured_factual_analysis                    |
            -> validate_schema_and_evidence              |
            -> embed_for_near_duplicate                  |
            -> decide_near_duplicate                     |
            -> build_and_embed_event_signature           |
            -> retrieve_recent_event_candidates          |
            -> decide_event_assignment                   |
                 -> attach_existing_event                |
                 -> create_event                         |
                 -> mark_review_required                 |
  -> persist_terminal_projection <-----------------------+
```

Node results are typed. A retry resumes from the latest durable checkpoint and reuses already
persisted idempotent artifacts. Provider calls are outside database transactions. Persistence uses
short transactions with uniqueness constraints as the final concurrency guard.

### Deterministic preprocessing

- Normalize Unicode, whitespace, line endings, repeated boilerplate, canonical URLs, and timestamp
  representations without changing factual wording.
- Segment stored clean text into bounded, stable passages before the model call. Passage IDs derive
  from candidate ID, normalization version, ordinal, and passage hash.
- The model returns passage IDs for each key fact. It does not invent free-form evidence IDs.
  Deterministic validation rejects missing passage IDs, unsupported categories, excessive output,
  invalid dates, or claims whose cited passage is absent.
- Apply bounded redaction/quarantine rules for obvious secrets, phone numbers, identity numbers,
  email addresses, or sensitive minor-related material before any provider request. The immutable
  source candidate remains unchanged.

### Structured factual analysis

The application-owned schema has this logical shape:

```python
class FactualClaim(BaseModel):
    text: str
    passage_ids: list[UUID]

class CandidateAnalysis(BaseModel):
    summary: str
    key_facts: list[FactualClaim]
    entities: list[StructuredEntity]
    event_time: datetime | None
    primary_category: FactualCategory | None
    categories: list[FactualCategory]
    keywords: list[str]
```

The seven `FactualCategory` values are versioned slugs for AI education policy,
large/generative models, robotics/embodied intelligence, AI compute/chips, youth science
education, AI industry/application, and AI governance/safety. Classification is multi-label with
an optional primary label so an ambiguous article is not forced into an unsupported single class.
Summaries are concise, factual Chinese and contain no brand tone or
marketing recommendation.

### Zhipu provider boundary

- Define application ports for structured chat analysis and embeddings. Domain/application code
  does not import a provider SDK.
- The infrastructure adapter uses configured base URL, API key, chat model, embedding model,
  timeouts, concurrency, request limits, and bounded retries. Exact dependency/version selection is
  verified and pinned in the first implementation milestone without changing these contracts.
- Automated tests use deterministic fakes and provider response fixtures. When credentials are
  configured, bounded live calls may compare compatible Zhipu chat/embedding models for factual
  quality, embedding behavior, latency, and token/cost telemetry; the formal smoke/acceptance
  command remains a separate recorded gate.
- Store provider request IDs when safe, token counts, latency, and model identifiers; store prompt
  template hashes/versions, not full sensitive prompts or authorization data.

## 5. Duplicate and Event Decisions

### Exact duplicate

Use a deterministic hierarchy:

1. same active derivation key;
2. same normalized text SHA-256;
3. same canonical URL/source item identity where the content hash also agrees.

An exact duplicate creates a relation to the canonical governed article and may reuse its analysis
and event membership. Source provenance is never inferred from the retained candidate row alone:
each observation/snapshot occurrence is synchronized and preserved, including the case where
acquisition already reused one candidate ID across sources.

### Near duplicate and event candidate retrieval

- Store a 64-bit SimHash over normalized text for cheap bounded filtering.
- Store separate vectors for `near_duplicate` and `event_assignment` purposes. The selected
  embedding model and fixed dimension are validated before the migration and encoded in both
  settings and the vector column contract; a mismatched provider response is rejected before
  persistence.
- The MVP uses a bounded recent comparison window and exact vector distance rather than an ANN
  index because daily volume is small. HNSW/IVFFlat remains deferred until representative volume
  and query measurements justify it.
- Retrieve only recent, category-compatible events, then compute a versioned feature record:
  embedding similarity, title/token overlap, entity overlap, event-time distance, SimHash distance,
  and source relationship.

### Assignment policy

- A high-confidence match that passes required entity/time/category gates attaches to an existing
  event.
- A clearly low match creates a new event.
- The ambiguity band becomes `review_required`; it does not force a merge or call an LLM for an
  unexplained final score.
- Final assignment runs inside a short transaction with an advisory/row lock and uniqueness
  constraints so concurrent workers cannot create duplicate memberships or conflicting active
  event assignments.
- Adding/removing a member creates a new event projection version. Historical summaries and
  decision features remain queryable.

## 6. Persistence Model

All tables use UUIDs, UTC-aware instants, named constraints/indexes, JSONB only for genuinely
variable metadata, and explicit status checks.

| Table | Purpose / key constraints |
|---|---|
| `governance_runs` | One per acquisition run/manual key and pipeline version; aggregate status/counts |
| `governance_jobs` | One candidate/version-bundle work item; lease, heartbeat, attempts, terminal outcome |
| `governance_attempts` | Attempt timing, node/result/error metadata without prompt/body leakage |
| `article_occurrences` | Every governed observation/snapshot/source occurrence; unique stable occurrence identity |
| `normalized_articles` | Immutable normalized candidate text/hash/SimHash; unique candidate+input+normalization version |
| `normalized_passages` | Stable normalized passage text/hash/offsets tied to a normalized article |
| `candidate_analyses` | Schema/prompt/taxonomy/provider-versioned factual analysis projection |
| `analysis_facts` | Individual factual statements rather than an opaque summary blob |
| `evidence_bindings` | Relational fact-to-passage/candidate/snapshot/source-occurrence support |
| `analysis_entities` | Extracted mention plus canonical name/type and supporting passage |
| `analysis_categories` | Seven-label multi-label assignments, version and optional primary flag |
| `article_embeddings` | Purpose-specific provider/model/dimension/vector artifacts |
| `duplicate_relations` | Canonical ordered candidate pair, exact/near kind, features and rule version |
| `event_clusters` | Stable event identity and lifecycle/current-version pointer |
| `event_cluster_versions` | Immutable representative title/summary/time/entities/categories/member-set hash |
| `event_memberships` | Candidate-to-event assignment, active/superseded status and source occurrences |
| `event_assignment_decisions` | Candidate events, vector/entity/category/time features, thresholds and outcome |
| `model_invocations` | Safe request fingerprint, provider/model, token/latency metadata; no prompt/body/secret |
| LangGraph checkpoint tables | Durable graph thread/checkpoint/write state under a dedicated namespace |

Deleting or superseding a derivation never cascades into source candidates or snapshots. Event and
derivation tables use `RESTRICT` for evidence-bearing references. Development downgrade removes
only second-capability tables after application processes stop; it never deletes acquisition data
or MinIO objects.

## 7. API Contracts

Versioned internal endpoints:

- `POST /api/v1/governance-runs` -> `202`, run ID, status URL; optional acquisition run or bounded
  candidate selection and manual idempotency key.
- `GET /api/v1/governance-runs/{run_id}` and `/jobs` -> durable progress, counts, safe errors,
  versions, tokens, and latency.
- `GET /api/v1/candidate-analyses` and `/{candidate_id}` -> factual analysis, passages, duplicate
  relation, active event membership, versions, and provenance.
- `GET /api/v1/events` and `/{event_id}` -> event projection, member candidates, sources, passages,
  source occurrences, assignment features, review state, and provenance.

Lists are cursor-paginated and bounded. API responses never expose API keys, raw provider errors,
full prompts, complete hidden model responses, signed object URLs, or another arbitrary URL-fetch
surface. OpenAPI and frontend generated types are updated together; no product UI is added.

## 8. Failure, Retry, and Observability

Typed outcomes distinguish: already processed, exact duplicate reused, analyzed, event attached,
event created, review required, provider rate limit, provider timeout/unavailable, invalid provider
output, evidence validation failure, embedding failure, checkpoint failure, lease lost, and internal
terminal failure.

- Retry only transient provider/database/checkpoint failures with bounded exponential backoff and
  jitter.
- Invalid schema/evidence output may receive one bounded corrective regeneration when configured;
  repeated invalid output terminates visibly instead of looping.
- Emit structured events with governance run/job, acquisition run, candidate, graph thread/node,
  attempt, provider/model/version, duration, token count, result, and safe error code.
- Never log complete source text, prompt bodies, model output bodies, credentials, authorization
  headers, or personal data.

## 9. Compatibility and Rollout

- Existing acquisition APIs, scheduler, worker, tables, and eight source profiles keep their
  behavior. The governance planner observes completed runs instead of modifying fetch execution.
- New settings have safe disabled/no-credential behavior. API and acquisition continue to run when
  the Zhipu provider is not configured; governance jobs remain visibly blocked/not runnable rather
  than crashing unrelated services.
- Apply Alembic migration, deploy API/planner/worker with governance disabled, verify schema and
  fake-provider flow, configure secrets, then enable automatic planning and run the opt-in live
  model acceptance.
- Rollback disables governance planner/worker first, leaves derived records intact, and reverts API
  exposure/code. Schema downgrade is development-only and never part of an operational rollback.

## 10. Key Trade-offs

- **One task, milestone gates:** shared migrations and graph contracts outweigh administrative
  separation; daily milestones preserve independent verification.
- **Deterministic clustering decision:** embeddings propose candidates, but versioned feature gates
  make the final decision explainable. Ambiguity goes to review rather than hidden LLM judgment.
- **Fixed vector contract, exact search first:** the selected model/dimension is pinned before the
  migration for safe storage, while an ANN index is deferred until measured volume justifies it.
- **Separate governance processes:** slightly more deployment configuration, but prevents model
  outages from delaying evidence acquisition.
- **Brand-neutral summaries:** postpones personalization but preserves a clean fact boundary and
  protects the 2026-08-04 delivery target.
