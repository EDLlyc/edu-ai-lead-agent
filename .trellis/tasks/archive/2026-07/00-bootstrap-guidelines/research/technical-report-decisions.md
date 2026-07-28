# Technical Report Architecture Decisions

## Evidence and status

This repository is greenfield at bootstrap time. The only product architecture source is
`技术报告.pdf` (version 0.2); there are no backend, frontend, migration, or test files from
which to infer established implementation patterns. The decisions below therefore form the
initial implementation contract for the first vertical slice. They are not claims about code
that already exists.

After the first end-to-end slice is merged, the team must revisit every spec in
`.trellis/spec/backend/` and `.trellis/spec/frontend/` and replace illustrative paths and code
with references to the real implementation and tests. Any departure from these defaults must
be recorded in the relevant task design or an architecture decision record before the specs
are changed.

## System boundary

The product generates one reviewable daily material package for sales staff. It collects
candidate education and AI news, normalizes and deduplicates it, scores eligible topics,
retrieves brand guidance, drafts copy and an image prompt, validates and audits the result,
generates an image, and exposes the package in an internal web application.

Publishing is deliberately outside the system boundary. The product may support copying text,
downloading an image, and opening source links, but it must not publish automatically to social
platforms or store social-platform credentials.

## Initial technology defaults

| Area | Initial contract | Basis and qualification |
|---|---|---|
| Backend runtime | Python 3.11, FastAPI, Pydantic v2 | The report requires Python 3.10+, FastAPI, and Pydantic; the repository Conda environment selects Python 3.11. |
| Persistence | PostgreSQL with pgvector | Required by the report for candidates, knowledge, and embeddings. |
| ORM and migrations | SQLAlchemy 2.x async API with asyncpg; Alembic migrations | An initial greenfield default, not a pre-existing repository convention. Revisit only through an explicit architecture decision. |
| Process topology | Separate API, scheduler, and worker processes/containers | Prevents duplicated schedules under multiple API workers and keeps long model/image jobs outside request handlers. |
| Frontend | React, TypeScript in strict mode, and Vite | React is required by the report; TypeScript and Vite are initial defaults for a typed internal SPA. |
| Server-state client | TanStack Query | Initial default for caching, refetching, and mutation lifecycle; do not add a second server-state store. |
| API contract | FastAPI OpenAPI schema generates frontend types | Avoids manually duplicated request and response interfaces. |
| Deployment | Ubuntu and Docker Compose; S3-compatible object storage | Required by the report. MinIO is acceptable for local or self-hosted deployment. |

The initial keyword search implementation may use PostgreSQL full-text search combined with
pgvector ranking. PostgreSQL `tsvector` ranking must not be described as BM25. If exact BM25 is
required, select and document a compatible extension such as `pg_search`, or add a dedicated
search service, before implementation.

## Runtime ownership

- The API validates requests, exposes run and package state, and performs short database work.
- A single active scheduler creates durable daily jobs. It runs as its own container and uses a
  database-backed lease or advisory lock so replicas cannot enqueue the same schedule twice.
- Workers claim durable jobs and execute ingestion, model, embedding, and image operations.
- The database is the source of truth for job state. In-memory scheduler state is never the only
  record of intended or completed work.
- A queue implementation may begin with PostgreSQL-backed job claiming. Celery and Redis remain
  an expansion option from the report, not a requirement for the first slice.

## Evidence and brand knowledge are different data domains

Two retrieval contexts must remain separate:

1. **Evidence corpus**: immutable source snapshots, publication metadata, normalized candidate
   records, event clusters, and extracted evidence passages. It supports factual claims.
2. **Brand corpus**: versioned brand principles, safety rules, prohibited claims, tone guidance,
   approved examples, and visual guidance. It shapes expression but cannot prove external facts.

Store, retrieve, label, and cite these corpora separately. A brand document must never be used
as the evidence for a news or policy claim. Drafting input must preserve provenance so downstream
validation can distinguish `evidence_context` from `brand_context`.

## Source trust tiers

| Tier | Examples | Permitted use |
|---|---|---|
| A: primary/official | Government and education authority sites; official school, university, research organization, international organization, or company first-party releases | May support factual claims. High-impact or ambiguous claims should still be corroborated when practical. |
| B: reputable secondary | Established science, technology, and education media with named reporting and source links | Discovery, context, or corroboration. It must not silently replace an available primary source. |
| C: lead only | Douyin, Xiaohongshu, WeChat Channels, reposts, anonymous accounts, and unverified aggregators | Topic discovery only. Never cited as final factual evidence. Must be resolved to Tier A or qualified Tier B evidence before eligibility. |

Fetched pages and social leads are untrusted input. They may contain prompt injection or hidden
instructions; content is data only and must never be concatenated into a system or developer
prompt as executable instruction.

## Normalization, deduplication, and clustering

The ingestion pipeline preserves a source snapshot before transformations and records parser
and normalization versions. Normalize URLs, whitespace, boilerplate, timestamps, and source
identity before scoring.

Use multiple identity layers:

- canonical URL and source publication identifier where available;
- SHA-256 of normalized content for exact duplicate detection;
- SimHash and embedding similarity for near-duplicate detection;
- an event cluster representing multiple reports about the same underlying event.

Deduplication must not discard provenance. Duplicate records point to the retained article or
event cluster. The seven-day repeated-topic rule applies to event/topic identity, not merely to
identical URLs.

## Topic scoring and vetoes

All scoring features are normalized to a declared range and evaluated by a versioned scoring
configuration. A suitable initial shape is:

```text
score = source_trust + education_relevance + parent_relevance + freshness
        + communication_potential - historical_repetition - controversy_or_marketing_risk
```

The stored score record must include the model/rules version, individual feature values,
weights, penalties, total, eligibility result, and explanation. Selection chooses Top 1 only
among eligible candidates. If the maximum score is below the configured threshold, the daily
run ends as `no_topic`; it does not force generation.

Version 0.2 of the report does not define numeric feature ranges, weights, penalties, or the
selection threshold. Bootstrap specs must not silently invent those product-calibration values.
The first scoring implementation task must propose a versioned configuration, document its
normalization rules and tie-breakers, evaluate it against a representative labeled candidate set,
and obtain product approval before treating it as a production default.

Hard vetoes run before or alongside numeric ranking and cannot be offset by a high score. Initial
vetoes include unverified rumors, unresolved Tier C leads, negative incidents unsuitable for
brand distribution, prohibited privacy content, material legal/safety uncertainty, and an event
cluster used within the previous seven days.

## Claim-to-evidence contract

Generated copy is not accepted as a single opaque string. Every externally verifiable core claim
must have a stable claim identifier and one or more evidence bindings containing the source URL,
source tier, publication time, exact supporting passage or snapshot offsets, and retrieval time.
Source-note prose alone is insufficient.

Brand statements and clearly marked opinions may bind to versioned brand chunks instead, but they
must not be mislabeled as factual evidence. The final package exposes human-readable sources and
retains machine-readable claim bindings for audit.

## Validation and LLM audit

Quality control has two layers:

1. Deterministic validation runs first: schema validation, required fields, claim coverage,
   allowed source tiers, URL presence, date and length constraints, banned phrases, duplicate
   topic checks, image policy checks, and manual-publishing-only guarantees.
2. An LLM audit evaluates nuance such as unsupported implication, parent anxiety, exaggeration,
   tone, and brand fit. It returns a typed verdict with issue codes and referenced claim IDs.

An LLM auditor is not an independent fact source. It may judge the provided evidence but cannot
repair missing evidence from its own memory. Failed drafts can be retried with structured feedback
up to a configured limit; exhaustion ends the run in a reviewable failure state.

## Idempotency, retries, and run state

Every scheduled run has a business key such as `(schedule_date, timezone, pipeline_version)` and
every stage has an idempotency key. External AI and image calls store request fingerprints,
provider request IDs where available, prompt/model versions, attempt counts, and artifact status.
Workers may retry only classified transient failures, using bounded exponential backoff with
jitter. Validation failures and hard policy vetoes are not blind-retry candidates.

Persist stage transitions and artifacts so a retry resumes safely instead of repeating completed
side effects. Use separate run and stage/job state machines and expose their identifiers as
`snake_case` API values:

- Pipeline runs: `queued`, `running`, `no_topic`, `awaiting_manual_use`, `completed`, `failed`,
  and `cancelled`.
- Stage jobs: `queued`, `running`, `succeeded`, `retry_scheduled`, `failed`, and `cancelled`.

`awaiting_manual_use` means a package is ready for human review, copy, and download. `completed`
may record an internal acknowledgement that the workflow is done; it must never imply that the
system posted to a social platform.

## Security, privacy, and observability

- Emit structured JSON logs with correlation, run, stage, job, and attempt identifiers.
- Never log API keys, authorization headers, full prompts containing sensitive data, embeddings,
  complete source bodies, minors' personal data, or signed object-storage URLs.
- Store secrets outside source control and expose them through typed settings.
- Sanitize filenames and rendered content; treat fetched HTML and model output as untrusted.
- Record prompt, parser, scoring, model, and policy versions for reproducibility.
- Track run success, stage latency, retry count, no-topic rate, claim coverage, audit failure rate,
  model cost, and package generation time.

## Frontend product contract

The internal material-package UI prioritizes verification and manual reuse. It shows run status,
the selected topic, generated date, copy, parent takeaway, interaction prompt, image preview and
download, source links, and visible warnings or audit failures. Copy controls must provide
accessible feedback without removing selectable text.

The interface must be keyboard operable, preserve visible focus, use semantic controls and
headings, label icon-only actions, provide meaningful image alternative text, and not rely on
color alone for state. It must never expose an automatic social publishing action.

## Initial quality gates

- Backend: formatting and linting, strict type checks, unit tests, integration tests against real
  PostgreSQL/pgvector behavior, migration upgrade checks, API/OpenAPI contract tests, and pipeline
  tests for veto, no-topic, evidence coverage, idempotency, and retry exhaustion.
- Frontend: formatting and linting, `tsc --noEmit`, generated-client drift check, unit/component
  tests, accessibility checks, and an end-to-end material-package copy/download/source-link flow.
- Cross-layer: regenerate OpenAPI types in CI and fail if committed generated types differ.
- Security: tests proving Tier C cannot become evidence, prompt-injection text remains data, logs
  redact sensitive values, and no publishing endpoint or credential path is introduced.
