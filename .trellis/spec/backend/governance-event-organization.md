# Factual Governance and Event Organization Contract

## Scenario: Stored evidence to auditable event pool

### 1. Scope / Trigger

Use this contract whenever code changes the second capability: governance run planning, stored
candidate normalization, passage construction, factual model analysis, exact/semantic duplicate
relations, LangGraph execution, event assignment, governance persistence, or the internal
governance APIs.

This capability starts from acquisition-owned PostgreSQL records. It does not fetch an article URL,
change the ten active approved source profiles (or activate the two pending profiles), change
`science-ai-education-v1`, score/select a topic, retrieve brand
knowledge, generate copy/images, expose a product UI, or publish content.

The controlling implementation lives in:

- [`governance_graph.py`](../../../backend/app/application/services/governance_graph.py) and
  [`governance_worker.py`](../../../backend/app/application/services/governance_worker.py) for
  resumable orchestration and durable job execution;
- [`governance.py`](../../../backend/app/application/ports/governance.py) for provider-neutral
  ports and typed artifacts;
- [`governance_artifacts.py`](../../../backend/app/infrastructure/db/governance_artifacts.py),
  [`governance_repositories.py`](../../../backend/app/infrastructure/db/governance_repositories.py),
  and [`governance_queries.py`](../../../backend/app/infrastructure/db/governance_queries.py) for
  persistence and projections;
- [`zhipu.py`](../../../backend/app/infrastructure/ai/zhipu.py) for the optional live provider
  boundary; and
- Alembic revision
  [`20260729_0004`](../../../backend/alembic/versions/20260729_0004_governance_foundation.py) for the
  complete schema and fixed `vector(2048)` contract.

### 2. Signatures

#### Processes and commands

- Planner: `python -m app.governance_scheduler_main`.
- Worker: `python -m app.governance_worker_main`.
- Offline acceptance: `make governance-fake-check`.
- Opt-in, one-candidate live acceptance:
  `make governance-live-smoke CANDIDATE_ID=<stored-candidate-uuid>`.
- Migration and diagnostics: `make migrate` followed by `make doctor`.

The API, acquisition scheduler/worker, governance planner, and governance worker are independent
processes. API routes enqueue or query durable records; they never invoke a model inline.

#### HTTP API

- `POST /api/v1/governance-runs` -> HTTP `202`, `Location` header, and
  `GovernanceRunResponse`.
- Request selection is exactly one of:
  `acquisition_run_id: UUID` or `candidate_ids: tuple[UUID, ...]` with 1--100 unique IDs.
- Optional `Idempotency-Key` header is 8--128 characters.
- `GET /api/v1/governance-runs/{run_id}` -> durable counts, safe status, version bundle, token
  usage, and model latency.
- `GET /api/v1/governance-runs/{run_id}/jobs`, `GET /api/v1/candidate-analyses`, and
  `GET /api/v1/events` use UUID cursor pagination with `limit` 1--100, default 20.
- `GET /api/v1/candidate-analyses/{candidate_id}` exposes facts, passages, evidence bindings,
  source occurrences, duplicate relations, assignment, and active event version.
- `GET /api/v1/events/{event_id}` exposes the immutable event projection history, members,
  sources, evidence, and assignment features.

#### Application ports

```python
class FactualAnalysisModel(Protocol):
    async def analyze(self, request: FactualAnalysisRequest) -> FactualAnalysisResult: ...

class EmbeddingModel(Protocol):
    async def embed(self, request: EmbeddingRequest) -> EmbeddingResult: ...

class GovernanceCheckpointer(Protocol):
    async def checkpoint_exists(self, *, thread_id: str) -> bool: ...
```

Both live and fake providers implement these ports. Domain and application modules do not import a
provider SDK or provider response type.

#### Database and state signatures

- Governance foundation revision: `20260729_0004`; the repository's current unique Alembic head is
  `20260730_0006` after topic-selection migrations.
- Run states: `queued`, `running`, `succeeded`, `partially_succeeded`, `failed`, `cancelled`.
- Job states: `queued`, `running`, `retry_scheduled`, `succeeded`, `review_required`, `failed`,
  `cancelled`.
- Assignment outcomes: `assigned_existing`, `created_new`, `review_required`.
- Embedding purposes: `near_duplicate` and `event_assignment`; both persist exactly 2048 finite,
  non-zero values for `embedding-3`.
- One governance job exists per `(run_id, candidate_id)`. Active derivations, occurrences,
  embeddings, relations, event memberships, event versions, and invocation fingerprints are also
  protected by named database uniqueness constraints.

### 3. Contracts

#### Stored-evidence and provenance contract

- Load candidate text, observations, snapshots, sources, and source versions from PostgreSQL. An
  original/canonical URL is provenance, not permission to browse.
- Never mutate acquisition candidates or immutable MinIO snapshots. Normalized articles, passages,
  analyses, embeddings, relations, and event versions are versioned derived records.
- Candidate content and source occurrence are different concepts. Synchronize each stable
  `(candidate_id, observation_id, snapshot_id, source_item_id)` occurrence even when acquisition
  reused one content-bearing candidate for identical reports from multiple sources.
- Every accepted summary/fact/entity is backed by stored passage IDs. API evidence bindings retain
  candidate, occurrence, snapshot, exact quote, and offsets.

#### Version and idempotency contract

Resolve one immutable bundle before executing a job:

```text
pipeline + normalization + passage schema + taxonomy + prompt + analysis schema
+ embedding input/provider/model/dimension + similarity rule + event assignment rule
```

Candidate ID, immutable input hash, and the complete bundle fingerprint form the derivation
identity. A retry or replay with the same identity reuses artifacts; changing any version creates a
new derivation and never rewrites the previous result.

#### LangGraph and transaction contract

- PostgreSQL run/job tables are the operational and API source of truth. LangGraph checkpoints are
  resumable orchestration state, not business projections.
- Checkpoints may contain IDs, hashes, versions, stage/status values, and small typed outputs. They
  must not contain full source text, prompts, provider responses, API keys, or authorization
  headers.
- Provider calls occur outside database transactions. Claim/lease, artifact persistence, and final
  event assignment use separate short transactions.
- Workers claim with `FOR UPDATE SKIP LOCKED`, renew a lease/heartbeat, and fence stale attempts.
  Final event assignment is serialized and database uniqueness remains the last concurrency guard.

#### Factual analysis and taxonomy contract

- Normalize and segment deterministically before a model call; passage IDs and hashes must be
  stable for the same input/version.
- Treat passage text as untrusted quoted data. Page instructions cannot change the system contract.
- The seven allowed labels are `ai_education_policy`, `large_generative_models`,
  `robotics_embodied_intelligence`, `ai_compute_chips`, `youth_science_education`,
  `ai_industry_application`, and `ai_governance_safety`.
- Classification is multi-label with an optional primary category. Summary and facts are factual
  Chinese, brand-neutral, bounded, and evidence-bound.
- For English candidates, normalization and passage offsets remain in the original language.
  Chinese summaries/facts bind to those original passage IDs; source language, URL, snapshot,
  passage ID, and exact English quote remain traceable. A Chinese governed fact is not represented
  as an original quote.
- One configured corrective regeneration is allowed for deterministically invalid model output.
  Repeated invalid output becomes a typed, visible terminal/review outcome; it is never silently
  accepted.

#### Duplicate and event contract

- Exact reuse uses immutable derivation identity, normalized SHA-256, or matching canonical/source
  identity plus agreeing content. Evidence and occurrences are retained instead of deleted.
- Persist separate purpose-specific embeddings for near-duplicate comparison and event assignment.
- The `event-assignment-v1` default searches at most 20 events in a 14-day window. Auto-attach
  requires similarity >= 0.90, composite score >= 0.80, time distance <= 3 days, category overlap
  >= 0.25, and no entity conflict. The review band starts at similarity 0.80, score 0.65, a
  7-day time distance, and non-zero category overlap. Lower matches create a new event.
- Persist all selected features, alternatives, thresholds, policy version, and outcome. Ambiguous
  candidates become `review_required`; no hidden LLM decision may force a merge.
- Event identity is stable. Membership changes create a new immutable event projection version with
  a member-set hash, representative article, time/category/entity projection, and source diversity.

#### Provider, transport, and environment contract

- `AI_PROVIDER_MODE` is `disabled`, `fake`, or `zhipu`. Governance processes remain disabled by
  default and require `GOVERNANCE_ENABLED=true` before their individual enable flags.
- Live defaults are `glm-5.2`, `embedding-3`, and `AI_EMBEDDING_DIMENSIONS=2048`. Model IDs, limits,
  timeouts, retries, concurrency, token budgets, cost-unit budgets, and every governance version are
  validated settings, not scattered constants.
- `GOVERNANCE_CHECKPOINT_DATABASE_URL` is a psycopg `postgresql://` URL; the SQLAlchemy application
  URL remains asyncpg. Never interchange them implicitly.
- Secrets belong only in a Git-ignored `.env` or deployment secret store. Do not return or log
  keys, authorization headers, full prompts/source bodies, raw provider output/exceptions, hidden
  reasoning, or full embedding vectors.
- Zhipu requests advertise only `Accept-Encoding: gzip`. Read the raw response stream, bound both
  compressed and decoded bytes, explicitly decode gzip, reject unsupported/malformed encodings,
  then construct a clean decoded `httpx.Response`. A response already consumed by `MockTransport`
  is treated as decoded content, but it still receives the same encoding and declared-length
  validation before transport encoding/length headers are stripped.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| No acquisition run and no candidate IDs | HTTP validation error; no run created |
| Acquisition run and candidate IDs both supplied | HTTP validation error; no run created |
| Same request/idempotency key or same derivation bundle is replayed | Return/reuse durable identity; create no duplicate artifacts |
| Candidate has multiple observations/snapshots | Persist every source occurrence; source diversity does not use `candidate.source_id` alone |
| Model cites an unknown/missing passage, unsupported category, invalid date, or excessive output | `invalid_provider_output`/typed validation code; never persist accepted facts |
| Provider returns 401/403 or other non-transient 4xx | Typed non-retryable authentication/rejected failure; suppress raw body |
| Provider returns 429, timeout, request error, or 5xx | Typed retryable failure with bounded exponential backoff |
| Provider returns the wrong embedding dimension, NaN/Inf, or an all-zero vector | Reject before persistence |
| Provider returns unsupported or malformed gzip | Non-retryable `invalid_provider_output`; one attempt and no raw material leakage |
| Provider declares a negative/non-integer content length or an unsupported encoding | Non-retryable `invalid_provider_output`, including for preloaded responses |
| Compressed or decoded response exceeds its bound | `output_limit_exceeded`; do not parse or retry as a network failure |
| Worker loses its lease or a stale attempt tries to persist | Fence the stale writer; preserve the current job/artifact owner |
| Event candidate passes attach gates | Add one active membership and create a new immutable event version |
| Candidate falls in the ambiguity band | Persist `review_required`; do not attach or create a misleading active membership |
| No candidate passes review gates | Create a stable new event and initial version |
| Governance is disabled or credentials are absent | Acquisition/API remain healthy; no accidental live model call |

### 5. Good / Base / Bad Cases

- Good: one stored authoritative article is normalized, analyzed by `glm-5.2`, embedded twice with
  `embedding-3`, evidence-validated, assigned to an event, and returned through the API with safe
  token/latency/version metadata and all occurrences intact.
- Good: two sources share one acquisition candidate; governance reuses content analysis but the
  event exposes two source occurrences and source diversity two.
- Base: there is no recent compatible event; the deterministic policy creates a new event and
  version without treating topical similarity as identity.
- Base: the live provider is unavailable; the job becomes retryable/failed according to its bounded
  attempt policy while acquisition and query APIs keep running.
- Bad: re-fetch the original URL in a graph node, store only `candidate.source_id`, put full text in
  a checkpoint, persist one shared vector for both purposes, let an LLM select the final event, or
  mutate the current event projection in place.

### 6. Tests Required

- Unit tests assert normalization/passage stability, evidence validation, exact/semantic duplicate
  rules, event thresholds/tie ordering, taxonomy bounds, fake-provider determinism, and typed worker
  outcomes.
- Provider contract tests assert safe JSON projection, full-prompt input limits, rate-limit/
  timeout/5xx/auth mappings, fixed 2048 dimensions, finite non-zero vectors, gzip chat+embedding
  decoding, malformed gzip rejection, compressed/decoded response bounds, and raw-material
  suppression.
- Real PostgreSQL/pgvector tests assert clean migration/downgrade isolation, occurrence uniqueness,
  competing claims/lease recovery, checkpoint resume without duplicate provider calls, versioned
  derivations, serialized event assignment, immutable event versions, source diversity, and
  end-to-end API replay idempotency.
- The final task gate runs backend format/lint/strict mypy/tests with coverage, OpenAPI/frontend
  contract checks, Doctor, Compose validation, `git diff --check`, credential scanning, unique
  Alembic-head inspection, and read-only database invariants.
- A live Zhipu smoke is opt-in, one stored candidate at a time, and recorded separately. It supports
  compatibility/quality evidence but never replaces deterministic tests.

### 7. Wrong vs Correct

#### Wrong: infer provenance from the content owner

```python
source_count = 1 if candidate.source_id else 0
```

#### Correct: derive it from durable occurrences

```python
occurrences = await repository.sync_occurrences(candidate.id)
source_count = len({occurrence.source_id for occurrence in occurrences})
```

#### Wrong: let automatic decoding read an unbounded provider body

```python
response = await client.post(url, json=payload)
provider_payload = response.json()
```

#### Correct: bound raw and decoded content before schema parsing

```python
async with client.stream("POST", url, headers={"Accept-Encoding": "gzip"}, json=payload) as raw:
    response = await _read_bounded_response(raw, max_response_bytes=response_limit)
provider_payload = response.json()
```

The byte limit and typed validation gate are security boundaries, not optional optimizations.
