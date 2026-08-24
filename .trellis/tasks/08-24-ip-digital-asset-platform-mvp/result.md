# Implementation Result: IP Digital Asset Sharing Platform MVP

## Outcome

Implemented and independently reviewed an additive, feature-disabled-by-default IP asset hub across
FastAPI, PostgreSQL/pgvector, private MinIO, a separate durable worker, generated OpenAPI types, and
the internal React SPA. The existing approved static visual catalog and its complete-index retrieval
remain separate from the mutable IP-library tables and partial dynamic vector search.

The delivered UI is one shared no-login library: upload, controlled core classification, canonical
naming, newest-first cursor browsing, provenance/orientation/tag filters, chat-like text search,
transient similar-image search, detail/preview/original download, bounded ZIP+manifest, optional
1:1 generation, and generation-status polling. It visibly states the company-intranet/no-auth
boundary. Local Vite `127.0.0.1:5173` to API `127.0.0.1:8000` access is covered by an exact,
noncredentialed CORS allowlist and a real allow/deny OPTIONS preflight test.

After user visual review, the frontend was redesigned from the original dense industrial archive to
a calm, image-first enterprise library: compact product header, one search/filter surface, full-width
asset grid, and on-demand upload/creation/detail drawers. Desktop and 390 px layouts were visually
smoked in a real browser with no console errors, horizontal overflow, or drawer overflow.

After a second user boundary correction, the hub was removed entirely from the shared development
console and exposed only at `/ip-assets` (plus `/ip-assets/`) as a separate lazy page. The root `/`
console no longer imports, renders, or mounts the IP page. The standalone route owns its title,
loading/fail-closed states, skip link, single `main`, and single `h1`; unknown and flag-disabled paths
do not fall back to the console.

## Acceptance status

| PRD acceptance criterion                              | Status                                                   | Evidence / qualification                                                                                                                                                                                                                                                         |
| ----------------------------------------------------- | -------------------------------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| AC1 upload and immediate shared gallery               | Implemented                                              | Multipart/API/UI coverage plus real repository/MinIO integration; no login dependency exists.                                                                                                                                                                                    |
| AC2 invalid raster/metadata safety                    | Implemented                                              | Full-decode validator rejects malformed, signature-mismatched, oversized, pixel-bound and trailing-payload PNG/JPEG/WebP input. Similar-image input is validated even when semantic search is disabled.                                                                          |
| AC3 exact and near dedupe                             | Implemented                                              | SHA-256 uniqueness, exact-key put-or-verify storage with byte verification, perceptual warning, advisory locking and real dedupe integration.                                                                                                                                    |
| AC4 deterministic provider-free browse/search         | Implemented                                              | Keyset repository, stable ordering, composable filters, metadata fallback and UI load-more cursor.                                                                                                                                                                               |
| AC5 multimodal ranked retrieval/degradation           | Implemented; live acceptance deferred                    | Dynamic `ip_asset_embeddings` search enforces exact provider/model/dimension/input-policy/source-checksum identity and never queries the static approved-catalog table. No live embedding call was run.                                                                          |
| AC6 verified preview/download/ZIP                     | Implemented                                              | Private-store key/bucket/size/checksum verification, safe response headers, sequential aggregate ZIP budget and accessible download feedback.                                                                                                                                    |
| AC7 asynchronous generation-to-library                | Implemented with fake provider; live acceptance deferred | Atomic enqueue/replay, lease heartbeat, provider identity/output validation, and a single lease-fenced transaction for gallery creation plus job success are covered. Fingerprints include persisted request labels. No live image call was run; output remains `1:1`/1024×1024. |
| AC8 generation-disabled independence                  | Implemented                                              | Capabilities and UI disable creation without disabling library workflows.                                                                                                                                                                                                        |
| AC9 existing asset bootstrap                          | Partially accepted                                       | Aggregate-only dry-run and checksum-idempotent implementation are complete. No real import or second real replay was performed.                                                                                                                                                  |
| AC10 response/browser privacy                         | Implemented                                              | Public schemas omit bucket/object keys/secrets/paths; resource URLs are API-origin restricted; MinIO is private; scoped scans pass.                                                                                                                                              |
| AC11 engineering gates                                | Task scope passes; full-repository gate qualified        | Focused IP/schema/model/MinIO/pgvector/backend/frontend checks pass. Concurrent official-account `0032` work currently blocks shared full-repository gates; exact failures are below.                                                                                            |
| AC12 documented no-auth intranet boundary/default-off | Implemented                                              | Exact origin config, loopback Compose ports, disabled defaults, UI and runbook prohibit public exposure.                                                                                                                                                                         |

## Independent review findings fixed

- Generation output asset, tags, optional embedding job, output link and job success now commit in one
  lease-fenced transaction; a stale claim is proven unable to publish a gallery row.
- Concurrent generation replays use PostgreSQL conflict handling. Fingerprints now include department
  and contributor, preventing requests with different persisted labels from being incorrectly merged.
- Embedding/generation work renews leases. Lease loss and parent cancellation cancel child/provider
  work, and expired/exhausted claims cannot complete.
- MinIO existing metadata is no longer content proof: existing and newly written bytes are read back
  and verified, and keys must exactly match the content-addressed path.
- Upload/search rejects trailing raster polyglots. Transient image search shares the bounded raster
  semaphore through decode/provider use, including degraded mode.
- ZIP originals are read sequentially and stop at the aggregate budget.
- The UI now has provenance/orientation/tag filters, required taxonomy selects, accessible ZIP status,
  and dialog focus trapping/restoration.
- The redesigned UI preserves semantic match explanations, reports search failures accessibly,
  prevents non-ready assets from preview/download/reference flows, replaces broken images with named
  fallbacks, and links completed generation jobs to their output detail.
- Generation polling no longer invalidates its own query family from `refetchInterval`; terminal
  success stops polling and refreshes only the gallery list, preventing recursive refetch/stack
  overflow.
- The application composition now routes `/ip-assets` independently and keeps the shared root console
  free of the IP feature tree. An independent review added unknown-path and StrictMode title-lifecycle
  regression coverage.
- Cross-port access uses validated `APP_BROWSER_ORIGINS`; wildcard, credentials, paths and malformed
  origins are rejected.

## Known deferrals and deliberate limits

- `ip_asset_derivatives` reserves thumbnails, but the MVP serves verified bounded originals. Thumbnail
  generation/storage and derivative lease tests remain deferred.
- Optional emotion/action/scene/use/style values are normalized bounded text, not strict vocabularies.
- Filters are not synchronized into browser URL state.
- Explicit tests remain desirable for concurrent canonical-name allocation, populated-IP-row
  downgrade refusal, transient-provider retry exhaustion, and a backed-up real importer replay plus
  invalid source. These claims are not marked complete.
- No importer replay, public deployment, authentication, or delete/archive control was performed. A
  later user-authorized local acceptance uploaded the complete 41-image PNG IP corpus through the
  normal multipart API; this was not an importer run. One explicitly authorized live Comfly
  generation was then performed after enabling the API and dedicated worker.

## Independent validation evidence

- Focused backend/real-infrastructure/schema suite: **28 passed** (`21` IP unit, `5` IP
  PostgreSQL/pgvector/MinIO integration, clean-head schema and model parity).
- Focused frontend hub suite after redesign review: **3 files / 11 tests passed**. Full frontend
  TypeScript, ESLint, Prettier and production build pass; task-scoped backend mypy and Ruff checks
  remain covered by the prior independent review.
- Standalone composition review: IP feature remains **3 files / 11 tests passed**; App/Application
  routing is **2 files / 18 tests passed**. Vite production build keeps `IpAssetPage` in a separate
  lazy JS/CSS chunk. Desktop 1440×1000 and mobile 390×844 deep-link smoke passed with one main/h1,
  no shared-console content, overflow, console errors, or page errors.
- Persistent-data browser acceptance: all **41 PNG inputs** were processed through the normal upload
  contract: **33 created, 8 checksum-deduplicated, 0 failed**, leaving 41 durable assets. Every asset
  lists as `ready` and renders through the private preview endpoint. A real standalone gallery smoke
  eagerly decoded **41/41** previews at nonzero natural dimensions, opened the named detail
  drawer/full preview, and reported no console/page errors or document overflow. That 41-image
  bulk-upload acceptance phase stayed local; the separately authorized provider call is recorded below.
- Live generation acceptance: capabilities reported `generation_available=true`; one idempotent
  `1:1` job used a ready Xiaosai asset as its single reference, transitioned `queued -> running ->
succeeded` in about 28 seconds, and published one 1024×1024 PNG as a `ready`/semantic-`ready`
  generated asset. The standalone gallery increased from 41 to **42** items, enabled the AI creation
  action, rendered the generated card and detail preview, and reported no console/page errors or
  overflow. No secret or raw provider response was recorded.
- Search/focus corrective acceptance: `ip-asset-hybrid-v2` merges bounded metadata evidence with
  compatible vectors, keeps explicit filters authoritative, and lets the current turn replace stale
  conversational taxonomy. Restarting the real worker idempotently backfilled the 41 previously
  unavailable assets through the configured Alibaba `qwen3-vl-embedding` adapter; the library
  reached **42 semantic-ready, 0 queued/running/failed**. Live queries ranked happy Xiaosai metadata
  matches first, returned only Sai Xiansheng after a conflicting prior Xiaosai turn, and respected an
  explicit Sai Xiansheng filter over Xiaosai query text. Chromium desktop/mobile smoke confirmed one
  rounded composite search focus ring, zero horizontal overflow, and zero console/page errors.
- `make api-contract-check` passes; OpenAPI and generated frontend types match.
- `make migrate` reports current head `20260824_0032`. Direct checks confirm all six IP tables,
  `vector(2048)`, and a private MinIO bucket.
- Actual OPTIONS tests allow `http://127.0.0.1:5173` and omit allow-origin for an unlisted origin.
- `make ip-asset-import-dry-run MAX_ASSETS=2` selects two entries with aggregate-only output and no
  source read/mutation, provider call or import.
- Compose render, scoped privacy scans and `git diff --check` pass.

## Shared-worktree gate qualification

- `make backend-check`: mypy passes **202 source files**. Full pytest reports **1,361 passed / 3
  failed**: two unrelated migration tests still assert `0031` after official-account migration
  `0032`, and one official-account generated-visual worker test fails. Ruff findings are likewise
  confined to official-account files.
- `make frontend-check`: generated contracts, Prettier and ESLint pass; TypeScript reports two
  official-account-local omissions (`generated_visuals_enabled` fixture data and the
  `generating_body_visuals` label).
- The later standalone-page review again found full TypeScript blocked only by concurrent
  `official-account-local` generated-schema drift (`alt_text`, `block_index`, `block_kind`, and
  `output_profile_version`). Focused IP/App tests, ESLint, Prettier, production build and diff checks
  pass; those unrelated files were preserved.
- `make doctor`: IP worker/Compose checks pass, then Doctor stops because the concurrent migration
  compatibility declaration does not match `0032`; its later migration expectation also names
  `0031`. Direct current-head/IP schema/vector/private-bucket checks pass.

The reviewer intentionally did not edit concurrent official-account/release files, commit, archive,
call live providers, or perform a real asset import.

## Executable spec update

- Added `.trellis/spec/backend/ip-asset-hub.md` with the dynamic-index, API/DB/env, private storage,
  raster validation, CORS, idempotency and lease-fencing contracts found during implementation and
  review.
- Added `.trellis/spec/frontend/ip-asset-hub.md` with generated-wire, gallery/filter, resource-origin,
  dialog focus, download feedback and degraded-state contracts.
- Linked both documents from their layer indexes so future implementation/check context can discover
  them before changing this feature.

## Commit and archive state

The task is implemented and independently reviewed but is intentionally not committed or archived
from this session. The shared worktree contains uncommitted prerequisite migrations/features
(`0023` through `0030`, visual retrieval) and concurrent official-account `0032` work, including
overlapping composition, configuration, database-model, generated-contract, frontend-app, Doctor,
Compose and release files. A selective IP-only commit would therefore be incomplete/non-buildable,
while committing whole overlapping files would capture unrelated user/parallel work. Preserve this
task as `in_progress` until the stacked worktree is coordinated into buildable commits.
