# Implementation Plan: Authoritative-Source Acquisition and Evidence Ingestion

## Execution Rules

- Implement in the order below; do not start connectors before the shared persistence, safe-fetch,
  and snapshot contracts exist.
- Keep API, scheduler, and worker entry points independent throughout the work.
- Use controlled fixtures for automated connector tests. Live website access is opt-in smoke
  verification only and must not block the normal test suite.
- Run formatting, lint, strict typing, focused tests, and `git diff --check` at every review gate.
- Do not add LLM, embedding, scoring, generation, social publishing, or product-page work.

## 1. Foundation and Shared Contracts

- [x] Add the official MinIO Python client and any directly used test/runtime dependency with
      bounded compatible versions.
- [x] Extend validated settings and `.env.example` with schedule, catch-up, worker lease/poll,
      retry, safe-fetch, concurrency, item-limit, User-Agent, and MinIO credential settings.
- [x] Add typed application errors, acquisition domain enums/entities/value objects, state
      transition functions, clock/ID interfaces, and deterministic idempotency/hash helpers.
- [x] Add a shared structlog configuration with API/process correlation and redaction helpers.
- [x] Restructure `api_main.py` only as needed to install routers, lifecycle dependencies, and
      exception handlers without starting durable background work.
- [x] Add unit tests for settings invariants/redaction, state transitions, error mapping,
      idempotency keys, and schedule calculations.

### Review gate

```bash
make backend-format
make backend-lint
make backend-typecheck
conda run --name edu-ai pytest backend/tests/unit -q
git diff --check
```

Rollback point: foundation modules and dependency/config changes can be reverted before any schema
or object-store data exists.

## 2. Alembic, ORM Models, and PostgreSQL Repositories

- [x] Create `alembic.ini`, async Alembic environment, metadata ownership, and the initial
      acquisition revision.
- [x] Implement typed SQLAlchemy models for sources, source versions/cursors, runs, jobs,
      attempts, fetch leases, snapshots, evidence candidates, and observations.
- [x] Add named primary/foreign/unique/check constraints and query/claim indexes described in
      `design.md`.
- [x] Implement async session/transaction factories with redacted configuration.
- [x] Implement repository ports/adapters for versioned source seed/upsert, due-run creation,
      job claim/heartbeat/reclaim, per-source fetch lease, snapshot/candidate/observation
      persistence, cursor advance, run completion, and API projections.
- [x] Seed the eight stable source identities and initial versions through an idempotent explicit
      command/service, never through live network calls in a migration.
- [x] Add real PostgreSQL tests for clean upgrade, source seed idempotency/versioning, scheduled
      uniqueness, competing `SKIP LOCKED` claims, lease expiry, exact duplicate constraints, and
      provenance queries.

### Review gate

```bash
make infra-up
conda run --name edu-ai alembic -c backend/alembic.ini upgrade head
conda run --name edu-ai pytest backend/tests/integration/test_migrations.py backend/tests/integration/test_acquisition_repositories.py -q
make backend-lint
make backend-typecheck
git diff --check
```

Rollback point: stop application processes before downgrading. In development only, the initial
revision may drop acquisition-owned tables; do not delete MinIO or user data implicitly.

## 3. Safe Fetcher and Immutable MinIO Snapshot Store

- [x] Implement URL normalization and approved scheme/host/path/port validation.
- [x] Implement injected asynchronous DNS resolution and rejection of private, loopback,
      link-local, multicast, reserved, unspecified, IP-literal, and metadata targets.
- [x] Implement manual redirect handling with validation on every hop and HTTPS downgrade/host
      escape rejection.
- [x] Implement bounded streaming, content-type policy, total/connect/read/write/pool timeouts,
      SHA-256 calculation, no-cookie client behavior, safe header projection, and typed failures.
- [x] Implement the MinIO snapshot port using the official client behind an explicit bounded
      thread boundary, content-addressed keys, object verification, and no signed-URL logging.
- [ ] Add deterministic fetcher tests for success, conditional response, redirects, DNS/IP policy,
      timeout, oversized/misdeclared body, unsupported/missing type, compressed HTML, TLS policy,
      header/cookie redaction, and hostile page text.
- [ ] Add real MinIO tests for immutable write/reuse, hash/size metadata, database reference, and
      failure recovery after object write.

### Review gate

```bash
conda run --name edu-ai pytest backend/tests/unit/test_url_policy.py backend/tests/contract/test_safe_fetcher.py -q
conda run --name edu-ai pytest backend/tests/integration/test_minio_snapshot_store.py -q
make backend-lint
make backend-typecheck
git diff --check
```

Rollback point: content-addressed objects may remain unreferenced after a failed test or rollback;
do not bulk-delete the bucket. Record cleanup as explicit test-fixture teardown only.

## 4. Eight Source Connectors and Contract Fixtures

- [x] Define the common connector/profile interfaces and shared HTML link/date/canonicalization and
      detail-extraction machinery.
- [x] Add bounded, sanitized list/detail fixtures and expected contracts for all eight sources.
- [x] Implement `gov_cn_policy_v1` JSON discovery and government policy detail extraction.
- [x] Implement `bnu_news_v1`, including conservative limits and ETag/Last-Modified support.
- [x] Implement `cas_research_v1` with explicit research-content selectors and fallback.
- [x] Implement `sensetime_news_v1` using stable item IDs and hashes rather than cache validators.
- [x] Implement `xinhua_tech_v1`, `gmw_education_v1`, `stdaily_tech_v1`, and
      `chinanews_education_v1` with approved path filters and source-specific selectors.
- [x] Verify every connector returns typed items/documents, records parser version, bounds list
      depth, rejects off-domain/irrelevant links, and treats page instructions only as text.
- [x] Add parser-drift fixtures proving missing required title/body becomes a typed parse outcome,
      not an empty successful candidate.

### Review gate

```bash
conda run --name edu-ai pytest backend/tests/contract/test_source_connectors.py -q
make backend-lint
make backend-typecheck
git diff --check
```

Rollback point: each connector is selected by a source version and can be disabled independently;
do not change a historical source version in place to roll back a parser.

## 4A. AI-Centered Title Relevance and Downstream Handoff

- [x] Add a pure, versioned title-relevance policy with Unicode/case normalization and an
      AI-centered Chinese/English vocabulary covering AI/models/agents/learning/algorithms,
      AI compute/chips, vision/speech/NLP, robotics/embodied intelligence, autonomous systems,
      drones, brain-computer interfaces, and AI-related plans/regulations/standards/governance/
      support policies.
- [x] Keep general quantum, aerospace, biotechnology, and new-energy titles excluded unless the
      same title explicitly connects them to AI, robotics, or intelligent systems.
- [x] Separate bounded discovery scan depth from accepted relevant-item limit. Merge duplicate
      image/text anchors first, filter before detail fetching, preserve newest-first ordering, and
      treat missing titles conservatively as non-matches.
- [x] Add relevance-rule version to immutable source-version configuration/fingerprints and seed a
      new source version for all eight sources without rewriting historical jobs/candidates.
- [x] Add durable `filtered_count` aggregation to jobs/runs and safe no-match/filter observations;
      a zero-match source succeeds with zero candidates and advances its raw-list cursor.
- [x] Record relevance-rule version and matched terms in accepted candidate extraction metadata;
      do not add scores, embeddings, or model output.
- [x] Update the candidate-list projection to expose source slug/display name, original/canonical
      URL, candidate ID, title, publication time, and relevance-rule version. Candidate detail
      remains the stored clean-text/snapshot handoff for later LangGraph nodes.
- [x] Add mixed-list, zero-match, missing-title, English/case, false-positive boundary, no-detail-
      request, AI-policy acceptance, unrelated-policy rejection, ordering, counter, migration,
      source-version, API, and real PostgreSQL/MinIO end-to-end regression tests.
- [x] Regenerate OpenAPI/frontend types and update README/operator examples to show the fixed eight
      sources and the four-field human projection: source, latest relevant title, publication time,
      and original link.

### Review gate

```bash
conda run --name edu-ai pytest backend/tests/unit/test_title_relevance.py -q
conda run --name edu-ai pytest backend/tests/contract/test_source_connectors.py -q
conda run --name edu-ai pytest backend/tests/integration -q
make api-generate
make backend-check
make frontend-check
git diff --check
```

Rollback point: disable the new source versions or revert the relevance-rule version selection;
never mutate or delete historical candidates/snapshots. LangGraph remains outside this rollback
because this task adds only its typed evidence handoff, not a graph runtime.

## 5. Acquisition Application Service, Scheduler, and Worker

- [x] Implement manual/scheduled enqueue services that create one run and one job per approved
      enabled source using database uniqueness.
- [x] Implement the acquisition executor flow: claim, fetch lease, list snapshot, bounded discovery,
      detail snapshot, extraction, candidate/observation persistence, cursor advance, counters, and
      terminal source outcome.
- [x] Implement retry classification/backoff/jitter with durable `available_at`, attempt history,
      maximum attempts, and safe terminal errors.
- [x] Implement heartbeat, expired-lease recovery, graceful shutdown, and run aggregate completion
      including partial success.
- [x] Implement `scheduler_main` startup reconciliation plus the 06:30 cron wake-up; use database
      uniqueness for multi-replica safety and bound catch-up to the current configured window.
- [x] Implement `worker_main` polling and bounded concurrency without importing API modules.
- [x] Make zero relevant items a successful terminal job, persist filtered counts/observations, and
      ensure retries never turn a relevance miss into an unrelated fallback fetch.
- [ ] Add fixed-clock tests for before/at/after schedule, timezone/DST library behavior, catch-up,
      duplicate scheduler replicas, historical non-backfill, retry timing, and worker restart.

### Review gate

```bash
conda run --name edu-ai pytest backend/tests/unit/test_schedule_policy.py backend/tests/unit/test_acquisition_state.py -q
conda run --name edu-ai pytest backend/tests/integration/test_scheduler_worker.py -q
make backend-lint
make backend-typecheck
git diff --check
```

Rollback point: stop scheduler before rolling application code back; disable all source records if
needed so existing workers drain without issuing new requests.

## 6. API, OpenAPI, and Query Surface

- [x] Add `/api/v1/sources` with active-version and latest-health projections.
- [x] Add `POST /api/v1/acquisition-runs` with approved optional source selection, manual
      idempotency, `202`, durable identifier, `Location`, and status URL.
- [x] Add run and job status endpoints with typed outcomes and stable error envelopes.
- [x] Add cursor-paginated candidate list/detail endpoints with complete provenance and safe
      snapshot metadata but no signed URL/credentials/raw body.
- [x] Add source display metadata, original URL, relevance-rule version, and filtered counters to
      the relevant API projections for downstream workflow consumption.
- [ ] Add API tests for validation, not-found/conflict, status codes, bounded pagination, query
      count shape, and secret/content redaction.
- [x] Regenerate and commit `backend/openapi.json` and frontend generated API types; verify no
      publishing endpoint or frontend feature UI is added.

### Review gate

```bash
make api-generate
make api-contract-check
conda run --name edu-ai pytest backend/tests/contract/test_acquisition_api.py -q
make frontend-typecheck
git diff --check
```

Rollback point: API routes can be removed while retaining durable acquisition data; generated
OpenAPI and frontend types must be reverted in the same change.

## 7. Server Process Shape and Operational Documentation

- [x] Add a deterministic backend container build with an unprivileged runtime user and no secrets
      in layers.
- [x] Extend Compose with explicit migration, API, scheduler, and worker services, health/dependency
      ordering, loopback-only API exposure, no worker/scheduler ports, and restart policies.
- [x] Add Make targets for migration, API, scheduler, worker, integration verification, and
      opt-in live source smoke checks.
- [x] Update `.env.example`, README, and doctor checks with daily schedule behavior, source list,
      startup order, process health, migration requirement, catch-up semantics, and production
      prerequisites such as TLS/auth/backups.
- [x] Verify Compose interpolation does not leak secrets and service logs remain structured.

### Review gate

```bash
docker compose config
bash -n scripts/doctor.sh
make doctor
git diff --check
```

Rollback point: application services can be stopped independently while PostgreSQL/MinIO volumes
remain intact. Never use `docker compose down -v` as part of rollback.

## 8. Full Acceptance and Contract Update

- [x] Add the real PostgreSQL/MinIO end-to-end flow using controlled source fixtures: enqueue,
      claim, fetch, snapshot, extract, persist, query, repeat, and assert idempotency/provenance.
- [x] Prove one source's terminal failure yields partial success and does not block other sources.
- [ ] Prove the next scheduled run observes a newly published fixture item.
- [x] Prove a run whose source lists mix unrelated and AI-centered titles requests/persists only
      relevant details, while a zero-match source succeeds without a candidate.
- [x] Prove a later workflow consumer can list candidate/source/title/time/original link and fetch
      stored clean text/snapshot provenance by candidate ID without another source-network call.
- [x] Run clean-database migration, all backend checks, API/frontend contract checks, Compose/doctor
      checks, credential scan, and diff validation.
- [x] Update `.trellis/spec/backend/` greenfield statements with real implementation and test paths,
      without expanding into later pipeline stages.
- [x] Review generated OpenAPI to ensure no automated publishing or source-body endpoint exists.

### Required final validation

```bash
make infra-up
conda run --name edu-ai alembic -c backend/alembic.ini upgrade head
make backend-check
make api-generate
make frontend-check
make doctor
docker compose config
git diff --check
```

The optional live smoke command, if implemented and explicitly run, must use the production-safe
fetch policy, conservative rates, and a small item limit. Its result is operational evidence only;
fixture-based acceptance remains authoritative.

## Remaining Verification Gaps

- The Dockerfile reached the dependency-download stage without a build error, but the first build
  was cancelled after prolonged external package downloads; rerun `docker compose build
  backend-migrate` on a normal-bandwidth server to close this deployment-only gate.
- The implemented fetcher behavior is covered for core policy, redirect, timeout, size, type,
  conditional-request, redaction, and hostile-text cases. Additional explicit fixtures for
  compressed/misdeclared responses and TLS failure remain useful hardening tests.
- Add focused retry-timing/worker-restart tests, candidate pagination/redaction API tests, and a
  scheduled second-run fixture that introduces a newly published item.
- `gitleaks` is not installed on the current host; the project credential-pattern scan passed, but
  installing and running gitleaks remains a deployment/tooling hardening follow-up.

## Files and Areas Requiring Extra Review

- `backend/alembic/versions/` — destructive downgrade behavior and constraint correctness.
- `backend/app/core/security.py` and ingestion fetcher — SSRF, redirects, DNS, byte/type/time limits.
- Job claim/lease repositories — concurrency, short transactions, stale-worker behavior.
- Snapshot persistence ordering — immutable object identity and database failure recovery.
- Source profiles/selectors — domain/path leakage and parser drift.
- `compose.yaml`, `.env.example`, logs, OpenAPI — credentials and accidental public/raw-content
  exposure.

## Pre-Start Gate

Before `task.py start`, confirm:

- [x] Goal, eight-source scope, 06:30 schedule, catch-up behavior, and exclusions are explicit.
- [x] `prd.md`, `design.md`, and this implementation plan agree.
- [x] Source feasibility and current-state research are persisted.
- [x] `implement.jsonl` and `check.jsonl` contain real curated spec/research entries.
- [x] Trellis task validation passes (`implement.jsonl`: 12 entries; `check.jsonl`: 11 entries).
- [x] The user has reviewed the final planning summary and explicitly approved implementation in a
      subsequent message.
