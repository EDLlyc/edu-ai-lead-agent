# Implementation Plan: Data Governance and Event Organization

## Execution Rules

- Do not run `task.py start` until the user approves the final planning summary.
- Implement milestones in order. Each milestone ends with focused tests and a review/rollback gate.
- Keep acquisition behavior unchanged and keep the Zhipu provider optional outside governance
  processes.
- Use deterministic fakes for normal tests. Bounded live Zhipu calls are authorized when credentials
  are configured for compatibility/quality evaluation, but credentials never enter Git, test
  fixtures, logs, task artifacts, or reports and live availability never becomes a normal test
  dependency.
- Run narrow checks while editing and one complete backend/frontend/doctor gate after the final
  production-code change.
- Do not add scoring, brand retrieval, copy/image generation, product UI, arbitrary browsing,
  automatic publishing, or a ninth acquisition source.

## Milestone 1 — Foundation, versions, migration, and durable runtime

Target: first implementation working day.

- [x] Verify and pin compatible LangGraph/PostgreSQL-checkpoint and provider-client dependencies;
      record exact package/runtime constraints, checkpointer DB driver/URL requirements, selected
      embedding model, and fixed vector dimension in task research and `backend/pyproject.toml`.
- [x] Extend validated settings and `.env.example` for governance enablement, polling/concurrency,
      leases/heartbeats/retries, pipeline/version bundle, Zhipu endpoint/key/model identifiers,
      input/output/token limits, timeouts, and daily budget controls.
- [x] Add governance domain enums/entities/value objects for categories, version bundles, statuses,
      typed outcomes, idempotency keys, passage IDs, duplicate relations, and event decisions.
- [x] Add application ports for governance repository, structured factual model, embedding model,
      graph checkpoint integration, clock, and ID generation.
- [x] Add Alembic revision and SQLAlchemy mappings for governance runs/jobs/attempts, source
      occurrences, normalized articles/passages, analyses/facts/evidence bindings/entities/
      categories, purpose-specific embeddings, duplicate relations, events/versions/memberships,
      assignment decisions, safe invocation metadata, and required checkpoint schema without
      runtime DDL.
- [x] Implement repository claim/lease/heartbeat/retry/idempotent persistence/query primitives using
      short transactions, named constraints, `SKIP LOCKED`, and safe locking for event assignment.
- [x] Add `governance_scheduler_main` and `governance_worker_main` process shells with graceful
      shutdown; the scheduler reconciles terminal acquisition runs but remains disabled by default.
- [x] Add unit and real-PostgreSQL tests for settings invariants/redaction, version keys, migrations,
      fixed vector dimensions, occurrence synchronization, uniqueness, competing claims, lease
      recovery, and non-interference with acquisition tables.

### Gate 1

```bash
conda run --name edu-ai pytest backend/tests/unit/test_governance_foundation.py -q
conda run --name edu-ai pytest backend/tests/integration/test_governance_migrations.py backend/tests/integration/test_governance_repositories.py -q
make backend-format-check backend-lint backend-typecheck
git diff --check
```

Rollback: keep governance disabled, stop new processes, and revert the new migration/code. Never
delete or downgrade acquisition-owned tables or MinIO objects.

## Milestone 2 — Normalization, passages, exact dedup, and Zhipu structured analysis

Target: second implementation working day.

- [x] Implement pure, versioned Unicode/whitespace/boilerplate normalization and bounded passage
      segmentation with stable IDs, hashes, source offsets, and basic sensitive-data redaction or
      quarantine signals.
- [x] Implement normalized hash and SimHash helpers plus deterministic exact-duplicate canonical
      selection; exact duplicates preserve every source occurrence and reuse safe existing
      derivations.
- [x] Implement application-owned Pydantic schemas for factual claims/entities/categories/summary
      with the approved seven-category taxonomy and passage-ID evidence bindings.
- [x] Implement the Zhipu structured-analysis adapter behind the model port with bounded requests,
      concurrency, safe error mapping, metadata accounting, and no full prompt/output logging.
- [x] Implement prompt construction that clearly delimits untrusted source passages, requests only
      stored-passage IDs, and versions/hash-identifies the template.
- [x] Implement deterministic schema, taxonomy, date, length, and evidence-binding validation plus
      at most one configured corrective regeneration for invalid provider output.
- [x] Add fixture/contract tests for valid output, malformed JSON, unsupported labels, missing
      evidence, hallucinated passage IDs, prompt-injection text, timeout, rate limit, provider 5xx,
      retry exhaustion, and redaction.

### Gate 2

```bash
conda run --name edu-ai pytest backend/tests/unit/test_governance_normalization.py backend/tests/unit/test_governance_analysis.py -q
conda run --name edu-ai pytest backend/tests/contract/test_zhipu_provider.py -q
make backend-format-check backend-lint backend-typecheck
git diff --check
```

Rollback: disable provider-backed nodes while preserving migration and deterministic normalization.
No provider failure may affect acquisition API/scheduler/worker health.

## Milestone 3 — LangGraph, embeddings, semantic relations, and event assignment

Target: third implementation working day.

- [x] Implement the typed LangGraph candidate state and nodes: load, normalize/segment,
      exact-duplicate gate, analyze, validate, embed, retrieve event candidates, decide assignment,
      attach/create/review, and terminal projection.
- [x] Configure durable PostgreSQL checkpointing with one thread ID per governance job and prove
      resume after interruption without duplicate provider calls or derived records.
- [x] Implement the embedding adapter behind its port, persist provider/model/dimension/vector, and
      validate the fixed dimension, persist separate near-duplicate and event-signature vectors,
      and expose no credentials or full content.
- [x] Implement bounded recent candidate/event retrieval using category, time, SimHash, entities,
      title tokens, and exact pgvector distance; do not add an external vector store.
- [x] Implement a versioned deterministic assignment policy with auto-attach, create-new, and
      review-required bands; store every feature and threshold used in the decision.
- [x] Serialize final event assignment with short database locking and uniqueness constraints;
      create immutable event projection versions when membership changes.
- [x] Add controlled labeled fixtures for exact copies, paraphrases of one event, similar-but-
      distinct events, conflicting dates/entities, ambiguous review cases, and concurrent workers.
- [x] Prove that two source observations sharing one acquisition candidate remain two governed
      occurrences and contribute two sources to the event projection.
- [x] Record precision-oriented extraction/clustering evaluation metrics and representative errors;
      tune only through a new similarity/assignment rule version.

### Gate 3

```bash
conda run --name edu-ai pytest backend/tests/unit/test_event_assignment.py backend/tests/unit/test_semantic_dedup.py -q
conda run --name edu-ai pytest backend/tests/integration/test_governance_graph.py backend/tests/integration/test_event_organization.py -q
make backend-format-check backend-lint backend-typecheck
git diff --check
```

Rollback: disable automatic governance enqueue and leave existing derivations/events immutable.
Never delete historical event versions to change a threshold.

## Milestone 4 — APIs, deployment, acceptance, and handoff

Target: Tuesday, 2026-08-04.

- [x] Add versioned API schemas/routes for governance run enqueue/status/jobs, candidate analyses,
      event lists/details, passages, source occurrences, provenance, versions, duplicate relations,
      assignment features, and review state with bounded cursor pagination.
- [x] Wire repositories/provider adapters/graph dependencies through application composition without
      model calls in request handlers.
- [x] Extend Compose, Makefile, `.env.example`, Doctor, README, and operator commands for governance
      migration/planner/worker, fake-provider checks, and opt-in live Zhipu acceptance.
- [x] Regenerate backend OpenAPI and frontend generated API types; verify that no product page,
      scoring/generation endpoint, arbitrary fetch endpoint, or credential field appears.
- [x] Add end-to-end real PostgreSQL/pgvector acceptance: terminal acquisition candidate -> durable
      governance run/job -> factual analysis/passages -> duplicate relation -> event -> API detail,
      repeated replay idempotent, and interrupted job resumable.
- [x] Run an opt-in Zhipu smoke on a bounded real candidate set only after credentials are configured;
      record model IDs, versions, counts, latency/token totals, extraction validation, and event
      results without recording secrets or full prompts.
- [x] Produce a concise second-capability handoff/report section with observable results, quality
      commands, known limitations, and the clean boundary to third-stage topic scoring.
- [x] Update `.trellis/spec/backend/` with implemented graph, model, persistence, security, and
      testing contracts learned during delivery.

### Final gate — once after the final production edit

```bash
make backend-check
make frontend-check
make doctor
docker compose config --quiet
git diff --check
```

Also run a credential-pattern scan over tracked/dirty project files and inspect Alembic head,
governance job/lease state, event membership uniqueness, and API/OpenAPI drift. Live Zhipu smoke is
reported separately and does not replace deterministic tests.

Final result on 2026-07-30: backend 201/201 with 87% coverage; Provider contract 26/26; Ruff,
strict mypy over 77 files, frontend OpenAPI/format/lint/type/test/build, Doctor, and Compose passed;
strong credential-pattern matches were zero; invalid leases, duplicate active memberships, run
counter mismatches, and orphan event current versions were all zero.

Rollback: stop governance planner/worker and disable governance enqueue. Keep acquisition running
and retain all evidence/derived records. Operational rollback does not downgrade the schema.

## Final Review Checklist Before `task.py start`

- [ ] PRD contains no blocking open question and reflects factual neutrality, seven categories,
      eight-source boundary, and the 2026-08-04 target.
- [ ] Design preserves stored-evidence input, acquisition independence, durable state, idempotency,
      explainable assignment, and provider secrecy.
- [ ] Exact dependency and checkpoint compatibility research is recorded or explicitly resolved in
      Milestone 1 without altering accepted behavior.
- [ ] `implement.jsonl` and `check.jsonl` contain real spec/research entries rather than the example
      row.
- [ ] User has reviewed the final planning summary and explicitly approved implementation in a
      subsequent message.
