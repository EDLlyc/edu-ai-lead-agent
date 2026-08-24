# Implementation and Check Contracts

This bounded research note routes implement/check agents to the existing executable contracts that
matter for the IP asset hub without relying on truncation of the two large umbrella specs.

## Existing image-generation contract

Source: `.trellis/spec/backend/agent-pipeline.md:640-754`.

- The provider-neutral path produces exactly one stored image per accepted fingerprint, calls the
  provider outside database transactions, and persists a safe durable artifact/job state.
- Provider requests use bounded validated prompts and private reference bytes. Private MinIO URLs,
  transient provider URLs, raw provider responses, prompt bodies, reference contents, bearer tokens,
  and credentials never enter logs or APIs.
- Returned bytes must pass bounded PNG/JPEG/WebP signature/media/dimension validation before private
  content-addressed MinIO storage.
- Retry only typed transient failures within configured attempt/window limits. Authentication,
  quota, malformed output, unsafe URL, invalid raster, and request-bound failures are non-retryable
  or explicitly classified.
- Lease heartbeat and result fencing prevent a stale worker from persisting provider output.
- Fake-provider tests are the automated baseline. Live smoke work is separate, explicitly
  authorized, bounded, and secret-safe.

For this task, the existing “accepted draft” gate is not reused. A valid IP asset generation request
has its own durable fingerprint and job, while the provider/storage/privacy/result-validation
contracts remain authoritative.

## Backend quality and persistence contract

Sources: `.trellis/spec/backend/quality-guidelines.md:230-303`, `:306-328`, and `:928-952`.

- Use focused checks while iterating, then one final `make backend-check`, `make frontend-check`,
  `make doctor`, and `git diff --check` gate after review fixes stabilize.
- PostgreSQL locking, constraints, transactions, pgvector filtering, migrations, job claiming,
  idempotency, and MinIO behavior require real integration coverage; SQLite/mock-only proof is not
  acceptable.
- API changes require stable typed errors, enqueue/status semantics, regenerated OpenAPI/frontend
  types, and drift checks.
- Blocking I/O must not run directly in async handlers/workers; retries and concurrency must be
  bounded; raw dictionaries must not cross provider adapter boundaries.
- Review must confirm correct layer ownership, short transactions, idempotent external side effects,
  typed failure classes, secret/content/PII-safe logs, migration/OpenAPI drift coverage, and negative
  paths.

## Task-specific additions

- Dynamic library retrieval must keep exact provider/model/dimension/input-policy predicates but
  must not reuse or weaken the static catalog's complete-index proof.
- A base asset remains usable when its embedding is missing or failed; semantic search degrades to
  metadata/keyword results.
- No-auth mode must not create claims of verified user identity. Department/contributor labels are
  self-reported strings.
- No product route may expose a private object key, filesystem path, MinIO URL, vector, full provider
  body/request ID, credential, or transient query image.
- The feature remains disabled by default and is documented as local/company-intranet only.
