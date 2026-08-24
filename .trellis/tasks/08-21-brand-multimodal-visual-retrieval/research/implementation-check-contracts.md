# Bounded implementation and check contracts

This task-local summary prevents the implementation/check context from truncating the much larger
`agent-pipeline.md` and `quality-guidelines.md`. The source specifications remain authoritative; this file
extracts only the contracts that directly govern the multimodal visual-retrieval change.

## Material-package and visual-selection boundary

- Only an accepted draft may reach image preparation. `no_topic` and failed drafts never call an image or
  embedding provider.
- The existing `VisualBrief` and approved private visual catalog are the controlled inputs. Raw Moments copy,
  evidence bodies, private object URLs, arbitrary model prose and private paths are not query inputs.
- Existing catalog hard gates remain authoritative: identity coverage, role, approved state, physical-file and
  checksum integrity, reference count and aggregate byte budget all run before semantic ranking.
- Provider calls happen outside database transactions. Persistence rechecks the claimed immutable derivation and
  lease before accepting a result; a stale worker cannot persist provider output.
- Persist only bounded safe metadata: provider/model/policy identities, checksums, attempts, dimensions, status,
  typed error codes and allowlisted semantic scores. API keys, workspace values, provider bodies/request IDs,
  image bytes, raw vectors, prompts and private paths never enter logs, APIs or durable audit metadata.
- Replay and concurrency must be idempotent. One immutable input/provider/model/policy derivation produces at most
  one ready result; classified failures are visible and never swallowed.
- Feature-disabled and typed-unavailable paths must execute the literal deterministic selector-v1 behavior. They
  must not retry a query provider inside the same material attempt or cross into another vector identity.

## Provider and async boundary

- Provider adapters use explicit connect/read/overall timeouts, bounded request and response sizes, bounded
  concurrency and exactly the configured attempt count. Default automated tests are provider-free.
- No blocking I/O runs directly in an async route/worker. Use the repository's established async HTTP and database
  patterns; do not add `time.sleep`, unbounded retries or catch-and-ignore exception handling.
- External response dictionaries are parsed into strict typed contracts at the adapter boundary. Finite 2048-value
  vectors, non-negative usage and immutable requested identity are validated before crossing into application code.
- Model omission may be bound to the fixed requested model only for the documented provider contract; an explicit
  conflicting model/provider/dimension is terminal and never mixed into retrieval.

## Persistence and migration boundary

- pgvector behavior, leasing, idempotent derivations, complete-index proofs and query filtering are verified against
  real PostgreSQL, not SQLite or mock-only SQL substring assertions.
- Visual embeddings use dedicated tables and exact provider/model/dimension/input-policy/catalog predicates. They
  never reuse or reinterpret `brand_chunk_embeddings` even though both spaces are 2048-dimensional.
- Transactions remain short. The paid/network embedding call finishes before the write transaction; the write is
  conditional on current lease ownership and exact asset checksum/catalog identity.
- Alembic must retain one head, have upgrade and downgrade integration coverage, and synchronize the repository's
  migration compatibility declaration and Doctor expectation.

## API, privacy and demo boundary

- The internal search route accepts exactly one bounded text query or one bounded PNG, never an arbitrary URL.
- Responses are generated from Pydantic/OpenAPI contracts and contain only safe asset IDs/references, allowlisted
  role/type/approval/catalog fields and bounded similarity. No filename fallback, path, bytes, vector, credential,
  provider body/request ID or factual-evidence claim is exposed.
- Schema changes regenerate production OpenAPI and frontend types and pass drift checks.
- The feature does not add publishing, delivery, replay or production-deployment behavior.

## Verification cadence and final gate

- During implementation, use narrow unit/contract tests and focused real-PostgreSQL integration tests. Batch related
  changes before running static checks.
- After the final production-code edit, run exactly one final full gate. A subsequent production-code fix invalidates
  that gate and requires affected focused tests plus one new final full gate.
- Required final evidence includes Ruff format/lint, strict mypy, full backend tests, deterministic eval drift,
  real-PostgreSQL migration/repository tests, API/frontend generated-contract drift, Compose render, Doctor,
  `git diff --check`, and scoped credential/private-path/raw-provider scans.
- Live provider checks and the final 41-asset indexing are explicit opt-in operations after code and independent
  review gates. They use one attempt per asset, aggregate-only diagnostics and no raw response retention.
