# Implementation result

## Outcome

Implemented the provider-gated, visual-only multimodal retrieval slice for approved brand assets. The
feature uses a fixed Alibaba `qwen3-vl-embedding` 2048-dimensional identity, immutable current-catalog
derivations, complete-index proof, cosine retrieval and semantic-primary selection after every existing hard
asset barrier. Disabled, provider-failure, identity-mismatch, catalog-change and incomplete-index paths fall
back to the existing deterministic selector without blocking image generation.

The implementation includes a separate PostgreSQL index and lease-safe jobs, a bounded provider adapter,
explicit opt-in local index CLI, safe internal text/PNG search route, material-package integration, generated
OpenAPI/frontend types, a six-case deterministic provider-free eval and focused domain/contract/API/CLI/real
PostgreSQL tests. Committed defaults remain disabled and provider-free. No credential CSV is read by the
application, and no private path, filename, image bytes, vector, provider body or request ID is returned by
the new API/CLI surfaces.

## Validation

- Independent Trellis review fixed post-provider asset revalidation, concurrent first-claim races,
  exact derivation predicates, provider identity binding, streamed response bounds, literal disabled
  snapshots, typed repository failures, lease/timeout validation, bounded-PNG validation and safe
  API/CLI projections. A protected zero-request preflight also exposed and fixed exact `2048`
  environment-string parsing without relaxing the frozen dimension contract.
- Pre-v2 `make backend-check`: Ruff, strict mypy over 176 source files, and 1,204 backend tests
  passed with 82% aggregate coverage. The final post-v2 gate is recorded below.
- Focused visual unit/contract/material/config/API/CLI tests: 115 passed.
- Post-preflight configuration/CLI/release regression: 32 passed.
- Real PostgreSQL visual retrieval, cosine ordering, identity exclusion and concurrent first-claim
  integration: 2 passed; focused migration/head/downgrade integration: 3 passed.
- `make api-contract-check`: passed.
- Frontend TypeScript type-check: passed.
- `make visual-retrieval-eval`: 6/6 cases passed.
- Compose render, release pipeline contract (13 tests), `git diff --check` and scoped secret/private-path scan:
  passed.
- The pre-v2 `make doctor` passed at the then-current `20260821_0024` head.

## Protected local indexing result

- Before migration, the main session captured a protected custom-format PostgreSQL backup (8,324,220 bytes,
  SHA-256 `a34312eb2a0711c43f5e9177f4e79752c8e8b302bc46b46b95d7bd1261a357d9`). No API, worker,
  scheduler, dispatcher or index process was running.
- The additive `20260820_0023` and `20260821_0024` migrations completed, and a fresh Doctor run passed at the
  single `0024` head.
- The first attempted live execution stopped during Settings validation because the strict dimension Literal
  rejected the normal environment string `2048`; it made zero HTTP requests and created no job rows. Independent
  review fixed the parser without accepting any other dimension, added regression coverage and reran the full
  1,204-test gate before live work resumed.
- The one authorized live catalog execution then processed the 41 approved PNGs serially with `max_attempts=1`.
  Aggregate result: 36 indexed, 0 pre-existing and 5 failed. Database audit shows exactly 36 succeeded jobs and
  5 `provider_unavailable` jobs, all with `attempt_count=1`; exactly 36 `vector(2048)` rows exist. Safe usage
  aggregates for successful image calls are 792 input tokens and 42,090 image tokens.
- After separate user authorization, one bounded retry execution rechecked all 41 derivations. The 36 ready rows
  were skipped without provider calls; the same five failed assets each made one additional request and again
  ended as `provider_unavailable`. Their job attempt counts are now 2; ready vector rows remain exactly 36.
- Aggregate-only local diagnosis found that the five failed PNGs are 8,420,810--10,248,863 bytes, while the
  largest successful PNG is 6,946,373 bytes. Their Base64 representations all exceed 10 MiB, matching a provider
  request-envelope boundary; dimensions overlap successful assets, so byte size is the material differentiator.
  A no-network, in-memory maximum-lossless-compression experiment was terminated after three minutes because it
  is too slow for the indexing path. It produced no files and did not modify source assets.
- Because current-catalog coverage is 36/41 rather than complete, semantic retrieval remains unavailable by design
  and automatic material selection continues through the literal deterministic selector-v1 fallback. Partial
  vectors are not used for ranking. Supporting all five oversized transport payloads would require a new immutable
  input-policy version with deterministic bounded image normalization, followed by a fresh complete-catalog index.
  The provider-free v2 implementation is recorded below; its new live indexing scope has not yet run.
- No raw provider response, request ID, asset name/path, image bytes, vector, credential or workspace value was
  printed or copied into task artifacts. No business replay, image generation, delivery, deployment, commit or
  push occurred.

## Input-policy v2 implementation

- Added active `brand-visual-embedding-input-v2` while retaining the exact historical v1 identity and
  derivation-key formula. V2 derivations additionally bind the actual normalized embedding-input SHA-256;
  repository retrieval exact-filters policy identities and rejects duplicate or mixed complete-index coverage.
- Added a deterministic in-memory PNG normalizer. It validates the original under the existing 25 MiB,
  8192-edge and 32-million-pixel limits, fully decodes it, preserves validated inputs at or below 7 MiB, and
  otherwise strips metadata, converts to RGB/RGBA and uses a fixed LANCZOS edge schedule with fixed PNG
  encoding. The original source bytes, files and manifest are never written.
- The fixed noisy 2048-square regression normalizes from 12,589,099 bytes to a metadata-free 1536-square PNG
  of 7,037,350 bytes. Its source and normalized hashes are frozen in provider-free tests, and the exact JSON
  request remains below the 10 MiB provider envelope.
- Indexing and image-query retrieval run the same normalizer outside the event loop. The adapter independently
  refuses an oversized serialized envelope before HTTP. Settings, API/worker/CLI wiring, Compose, Doctor,
  OpenAPI/frontend types and the offline eval now bind active policy v2.
- Alembic `20260821_0025` adds non-null `embedding_input_sha256` to both visual tables and backfills historical
  v1 rows from `asset_checksum`. Upgrade now refuses any pre-existing non-v1 policy row instead of assigning
  it an untruthful source/input identity. Downgrade accepts only v1 rows and refuses while normalized-policy
  rows remain.
- Independent v2 review moved API/index PNG normalization and validation off the async event loop, ensured the
  API reuses the already-normalized image rather than decoding twice, and included concurrency-semaphore wait
  inside the provider's overall timeout. Doctor now proves both visual tables, both non-null normalized-input
  columns and the dedicated `vector(2048)` column after migration.
- Focused provider-free normalization, service, adapter, selector, material, config and API/CLI regression:
  passed. Added literal v1-key, alpha/metadata, pixel-bomb, semaphore-wait and v1-only/v2-incomplete coverage.
  Real PostgreSQL migration/backfill/refusal/downgrade and retrieval/isolation regression: 7 passed. Compose,
  13 release-contract tests, frontend type-check, API drift, v2 eval 6/6 and `git diff --check`: passed.
- Final `make backend-check` after the last production edit passed Ruff, strict mypy over 176 source files and
  1,216 backend tests with 82% aggregate coverage.
- The implementer left the shared local database at reviewed head `20260821_0024`; the coordinated main-session
  activation below subsequently applied `0025` only after backup and independent review.

## Input-policy v2 local activation

- Before `0025`, the main session captured a second protected custom-format PostgreSQL backup (8,704,539 bytes,
  SHA-256 `8532d8a5c3779c010013ea71cc9b162efc3c784edb1aed9956b4d50e0353850e`). No API,
  worker, scheduler, dispatcher or index process was running.
- Migration `20260821_0025` upgraded successfully. A fresh Doctor run passed and proved the single head, both
  non-null normalized-input columns and dedicated `vector(2048)` storage.
- A no-network preflight normalized the complete approved catalog: 41 inputs, five transformed, 41 unique
  embedding-input hashes, maximum output 7,153,793 bytes, and every output within the 7 MiB policy bound. It
  modified no source image or manifest.
- The one authorized v2 catalog execution processed all 41 assets serially with one request per new derivation:
  41 indexed, 0 existing and 0 failed. Database evidence contains exactly 41 succeeded v2 jobs at
  `attempt_count=1`, 41 v2 vectors and 41 distinct normalized-input hashes. The 36 historical v1 vectors and five
  terminal v1 failures remain isolated and cannot complete a v2 query.
- One bounded synthetic text acceptance query returned `complete=true`, catalog/index/score counts of 41/41/41,
  and finite cosine similarities from 0.085981 to 0.379928 under
  `brand-visual-embedding-input-v2`. No asset identity, path, vector or provider body was printed.
- Only after those gates, the local mode-0600, Git-ignored `.env` was atomically updated to
  `semantic_enabled=true`, provider `alibaba`, model `qwen3-vl-embedding`, 2048 dimensions, concurrency 1 and
  input-policy v2. Its previous bytes were preserved in a protected mode-0600 backup. The credential and workspace
  values were neither printed nor copied into tracked files. A final Doctor run passed at `0025` with the active
  local settings, and no index/provider process remained.

## Intentionally not performed

- No server deployment, business replay, image generation, delivery, commit or push was performed. Committed
  defaults remain disabled/provider-free; only the protected local personal-project configuration is active.
