# Second capability handoff: factual governance and event organization

Date: 2026-07-30

## Delivered boundary

The second capability transforms stored acquisition candidates into versioned factual analyses,
duplicate relations, and auditable event projections. It reads candidate, observation, snapshot,
source, and source-version records from PostgreSQL and never treats an original URL as a browsing
instruction. The existing eight-source registry and `ai-title-v1` acquisition behavior are
unchanged.

Delivered runtime shape:

- durable governance runs, jobs, attempts, leases, heartbeats, retries, and idempotency keys;
- PostgreSQL-owned LangGraph checkpoint tables and ID/hash/version-only workflow state;
- stable normalized passages with offsets and evidence-bound structured factual analysis;
- exact and semantic duplicate relations with separate 2048-dimensional near-duplicate and event
  vectors;
- deterministic event assignment with attach/create/review outcomes, immutable event versions,
  source occurrences, and source-diversity projections;
- independent governance scheduler and worker processes, disabled by default;
- internal cursor-bounded APIs for run/job status, candidate analyses, passages, facts, entities,
  categories, evidence, occurrences, duplicate relations, assignment decisions, and events;
- deterministic fake provider acceptance and an explicit one-candidate Zhipu live-smoke command.

The HTTP API only enqueues durable work. It does not make model calls inline and exposes no
arbitrary URL-fetch, scoring, content-generation, product-page, publishing, or credential surface.

## Observable acceptance results

Focused delivery checks completed during Milestone 4:

- Ruff formatting/lint and strict mypy passed after API/worker/composition changes; mypy covered 77
  application/tooling source files at the latest checkpoint.
- `backend/tests/unit/test_governance_foundation.py` plus
  `backend/tests/unit/test_governance_delivery.py`: 16 tests passed. These cover settings and
  secret boundaries, fixed vector/version contracts, deterministic fake analysis/embeddings,
  enqueue routing/idempotency, checkpoint resume input, safe completion metadata, retry/review/
  terminal classification, and heartbeat cleanup that cannot mask the primary job result.
- `backend/tests/integration/test_governance_api_e2e.py`: 2 tests passed against real PostgreSQL/
  pgvector. The flow covers terminal acquisition to governance API enqueue, worker/LangGraph,
  accepted analysis/passages, an exact duplicate, two candidate members, three preserved source
  occurrences, immutable event versions, cursor pagination, acquisition replay idempotency,
  manual idempotency, and response redaction.
- OpenAPI and generated frontend types include only the governance run, candidate-analysis, and
  event query contracts added by this capability.
- `docker compose config --quiet` and `bash -n scripts/doctor.sh` passed after adding the default-
  disabled governance profile and schema/checkpoint/vector doctor checks.
- Final `make backend-check` passed 201 backend tests with 87% measured coverage, 113 formatted
  Python files, clean Ruff, and strict mypy over 77 source files.
- The final provider contract suite passed 26 tests, including bounded raw-stream handling for
  gzip chat and embedding responses, preloaded-response header/size checks, compressed-versus-
  decoded limits, and non-retryable malformed-gzip/content-length regressions.
- Final `make frontend-check` passed OpenAPI/type drift, Prettier, ESLint, strict TypeScript, three
  Vitest assertions, and the production Vite build.
- Final `make doctor` confirmed healthy PostgreSQL/MinIO, pgvector 0.8.1, Alembic
  `20260729_0004`, all governance/checkpoint tables, checkpoint migration 9, `vector(2048)`, the
  eight approved active sources, and the MinIO bucket.
- Read-only operational audit reported zero invalid running leases, duplicate active event
  memberships, governance run-counter mismatches, or orphan event current versions. Compose,
  OpenAPI forbidden-surface inspection, credential-pattern scan, and `git diff --check` passed.
- The production-shaped live workflow succeeded for stored candidate
  `0b274dab-b9ca-48c8-9262-531a3f0b07b5` (光明网教育, “首届北京市中学生人形机器人足球赛总决赛举行”):
  run `c803c6b2-ffe2-4e9d-b42f-3bc5c7061703`, job
  `0a5b3986-1fab-474a-83f7-70291aa1c4ee`, event
  `49fab2df-c3a2-51e6-9279-3d976ab61636`, result `succeeded / created_new`, five facts, two
  passages, one occurrence, `glm-5.2` plus two-purpose `embedding-3` at 2048 dimensions, 3881
  prompt tokens, 2079 completion tokens, 358 reasoning-token telemetry, and 18314 ms total model
  latency. See `research/milestone-4-live-zhipu-smoke.md` for the safe record.

Milestone 3's controlled policy evaluation remains the clustering quality baseline; see
`research/milestone-3-evaluation.md`. It reported no false merge in the controlled distinct-event
fixtures, deterministic ambiguity quarantine, durable checkpoint resume, preserved dual-source
occurrences, serialized concurrent assignment, and replay idempotency.

## Operator commands

```bash
make migrate
make doctor
make governance-fake-check
make governance-stack-up
make governance-live-smoke CANDIDATE_ID=<stored-candidate-uuid>
```

For offline acceptance, set `GOVERNANCE_ENABLED=true`, enable the governance scheduler/worker, and
use `AI_PROVIDER_MODE=fake`. For the explicit live command, use `AI_PROVIDER_MODE=zhipu` and supply
the provider base URL/key only through local `.env` or the deployment secret store. The command is
hard-bounded to one explicit stored candidate and outputs only IDs, models, versions, counts,
tokens, latency, and terminal outcomes. It never outputs credentials, source bodies, full prompts,
raw responses, embeddings, or provider request IDs.

The bounded Milestone 2 Zhipu compatibility probe succeeded for structured factual analysis and
evidence validation. Milestone 4 then completed the full durable event workflow on one real stored
candidate. During that acceptance, a Zhipu HTTP 200 gzip response exposed an httpx automatic-
decoding failure; the adapter now performs explicit, compressed-and-decoded bounded gzip handling,
maps malformed encodings to safe non-retryable output failures, and carries dedicated contract
regressions. Live acceptance remains intentionally separate from ordinary automated tests.

## Known limitations

- Live clustering metrics are not yet statistically representative. The current labeled fixture
  set is a regression baseline, not a production precision/recall claim.
- Entity compatibility uses exact normalized canonical names; aliases and renames may increase
  review volume.
- Event time falls back to publication time when structured event time is absent; retrospective or
  scheduled-event reporting may need richer temporal features.
- Recent-event lookup uses bounded exact pgvector distance. ANN indexing is deferred until measured
  volume and query latency justify it.
- There is no review-management mutation API yet. Ambiguous decisions are visible and durable but
  require a later approved operational workflow for human resolution.
- Authentication, public exposure, external monitoring, backup, retention, and secret-manager
  provisioning remain production-deployment work outside this repository slice.

## Boundary to the third capability

The next capability may consume governed events, facts, categories, entities, source diversity,
evidence bindings, and assignment/version metadata without another website fetch or summarization
call. It owns topic eligibility vetoes, versioned feature normalization/weights/penalties, freshness
and repeat handling, thresholding, stable tie-breaks, Top 1 selection, and `no_topic`.

This capability does not contain or pre-authorize those scoring rules. Brand knowledge, copy/image
generation, material-package UI, and publishing remain later independent boundaries.
