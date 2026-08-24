# Implementation Plan: IP Digital Asset Sharing Platform MVP

## Preconditions

- Do not run `task.py start` until the user explicitly approves the final planning summary.
- Although the parent task is already active, do not implement Section 3A until the user explicitly
  approves the latest AI-assisted upload-recognition summary in a subsequent message.
- Preserve all unrelated dirty-worktree changes and the current static brand visual catalog.
- Before each implementation layer, load the relevant Trellis specs from `implement.jsonl`.
- Use additive migrations and feature-disabled committed defaults.

## Ordered implementation checklist

### 1. Domain and contracts

- [x] Add a dedicated IP asset domain with bounded enums, metadata normalization, raster validation,
      canonical naming/version allocation inputs, lifecycle states, and safe public projections.
- [x] Extract/reuse raster safety helpers only where existing static-catalog behavior remains
      byte-for-byte and test compatible.
- [x] Define provider-neutral repository/storage/job ports for upload, browse, verified reads,
      dynamic embeddings, and generation jobs.
- [x] Add unit tests for taxonomy, names, metadata bounds, raster types/limits, checksum dedupe, and
      safe projection redaction.

### 2. Database and storage foundation

- [x] Add one additive Alembic migration for asset, tag, derivative, embedding/job, and generation-job
      tables plus required uniqueness and pgvector indexes.
- [x] Implement the async SQLAlchemy repository with keyset pagination, exact dedupe, transactional
      name-version allocation, compatible-vector search, and lease-safe jobs.
- [x] Implement a private content-addressed original store with exact-key, byte/checksum verification
      on existing and new objects plus bounded reads. Thumbnail descriptors/work remain deferred.
- [x] Add real PostgreSQL/pgvector schema/model-parity, dedupe, ordering, dynamic/static vector
      isolation, lease, generation-concurrency, and MinIO integration tests.
- [ ] Add a populated-IP-row downgrade-refusal test and an explicit concurrent canonical-name
      allocation test.

### 3. Upload, gallery, preview, and download APIs

- [x] Add feature/config validation and fail-closed application wiring.
- [x] Implement bounded multipart upload, exact duplicate response, asset detail/list/filter APIs,
      verified preview/original download, and bounded ZIP+manifest download.
- [x] Keep provider calls and heavy image decode/thumbnail work outside request event-loop work and
      outside database transactions.
- [x] Add typed API/error tests for valid PNG/JPEG/WebP, malformed/polyglot/oversize/pixel-bomb input,
      pagination, filters, duplicate replay, headers, streaming integrity, ZIP limits, and response
      privacy.

### 3A. AI-assisted upload recognition

- [x] Add feature-disabled recognition configuration and capability projection, including a bounded
      reviewed Zhipu vision model identity. Keep manual upload available for every disabled or
      provider-failure state.
- [x] Define a provider-neutral `IpAssetRecognitionModel` port plus strict request/result domain
      types. Accept only allowlisted core enums and bounded secondary values/tags; discard unknown
      keys, reasoning, prose, fingerprints, provider request IDs, and raw bodies.
- [x] Implement an async Zhipu vision adapter by extracting/reusing the reviewed transport and
      security patterns from the offline annotator without importing its synchronous CLI code or
      static-catalog taxonomy into the runtime feature.
- [x] Add `POST /api/v1/ip-assets/recognitions` as a bounded transient multipart operation: validate
      and normalize the raster, call the model only after this explicit request, return suggestions,
      and create no asset/job/database/MinIO state.
- [x] Add “AI 辅助识别” to the upload drawer after local preview. Preserve the selected file and
      manual values on failure; on success prefill editable classification fields, visibly label
      suggestions, never change department/contributor, and never submit automatically.
- [x] Add provider-free unit/API/component tests for no-call-before-click, typed allowlisting,
      malformed/oversized input, disabled/unavailable/timeout/invalid-output behavior, no durable
      side effects, new-file stale-suggestion reset, editable prefill, accessibility, and payload
      privacy.
- [ ] Run one separately authorized bounded live acceptance after automated gates pass.

### 4. Dynamic embedding and search

- [x] Add durable per-asset embedding jobs using the existing fixed visual identity and normalizer.
- [x] Implement compatible partial-index cosine retrieval separate from the static complete-catalog
      repository.
- [x] Implement controlled-term extraction, bounded conversational text query, image-similarity
      query, versioned hybrid ranking, deterministic explanations, and metadata fallback.
- [x] Add provider-free tests for ranking, filter authority, prior-turn bounds, partial index,
      identity mismatch, query-image non-persistence, and degraded behavior; add real pgvector ordering
      coverage.

### 5. Image-generation-to-library workflow

- [x] Add idempotent generation enqueue/status APIs and lease-safe worker processing.
- [x] Load at most one verified reference, call the existing `ImageGenerator`, validate the output,
      and ingest it through the same immutable asset path with `generated` provenance.
- [x] Fence gallery-asset creation and generation-job success in one lease-owned transaction, link
      the output, enqueue embedding work when enabled, and persist only bounded safe provider/job
      metadata. Thumbnail work remains deferred with the derivative table reserved.
- [x] Add fake-provider success, atomic replay, provider-identity failure, stale-lease/no-gallery,
      heartbeat cancellation, and generation-disabled independence tests.
- [ ] Add an explicit transient-provider retry/exhaustion test.

### 6. Existing asset bootstrap

- [x] Add an explicit local CLI that reads the current approved manifest through existing safe
      loading, copies/registers assets without modifying sources, and deduplicates by checksum.
- [x] Add a provider-free aggregate-only dry-run test that proves source bytes are not read or
      mutated.
- [ ] Run/add a real idempotent second import replay and invalid-source test only after the approved
      source library has been backed up; no real import was performed in this task.

### 7. Frontend hub

- [x] Create a dedicated `ip-assets` feature with generated API mappers/hooks and expose it only as a
      standalone lazy `/ip-assets` page behind a frontend flag; do not mount it in the shared console.
- [x] Implement the intranet/no-login notice, chat-like text search, similar-image query, filterable
      gallery, processing/degraded/error states, upload form, detail/preview/download experience,
      multi-select ZIP tray, and creation panel/job polling.
- [x] Keep query/server state in TanStack Query and transient conversation/selection state local.
- [ ] Synchronize shareable filters into URL state; this remains a deliberate post-MVP enhancement.
- [x] Add component/API/hook tests for keyboard operation, accessible announcements, upload/search/
      download/generation flows, no-auth wording, safe errors, and semantic fallback.

### 8. Contracts, operations, and final verification

- [x] Regenerate OpenAPI/frontend types and prove no contract drift.
- [x] Update Docker Compose/Doctor/Make targets only as needed for feature-disabled defaults and the
      existing PostgreSQL/pgvector/MinIO stack.
- [x] Document local/intranet activation, backup, migration, seed import, worker startup, provider
      configuration, rollback, and the prohibition on public exposure without authentication.
- [x] Run scoped secret/private-path/object-key scans and verify browser payloads.
- [x] Dispatch independent Trellis quality review, apply task-scoped findings, rerun affected gates,
      and record full-repository failures caused by concurrent official-account work without changing
      those unrelated files.
- [x] Capture the implemented cross-layer contracts in dedicated backend/frontend IP asset hub specs
      and link them from both layer indexes.

## Validation commands

Exact focused test paths will be filled during implementation. The minimum final gate is expected to
include:

```bash
make backend-check
make frontend-check
make api-contract-check
make doctor
git diff --check
```

Also run focused domain/service/API/UI tests, real PostgreSQL/pgvector integration tests, real MinIO
integration tests, migration upgrade/head/refusal checks, the seed-import dry run, and a local
browser smoke flow covering select image -> explicit AI recognition -> edit/confirm -> upload ->
search -> preview -> download -> generate -> library.

Live provider calls are not part of the default automated suite. Any live embedding or generation
acceptance requires separate user authorization, bounded attempts, aggregate-safe output, and no
secret/provider-body logging.

## Risky files and rollback points

- `backend/app/infrastructure/db/models.py` and Alembic heads: additive only; back up the local
  database before activation and refuse destructive downgrade when asset data exists.
- `backend/app/api_main.py` and worker composition: new optional dependencies must remain disabled
  without provider configuration and must not regress existing startup modes.
- existing visual retrieval/image generation helpers: preserve static-catalog and material-package
  behavior; prefer new adapters over widening old invariants.
- `scripts/annotate_brand_visual_assets.py` and the runtime recognition adapter: share only reviewed
  parsing/transport patterns or an extracted neutral primitive. Do not make the IP API import a
  repository CLI, accept its mismatched catalog taxonomy, or let suggestions become approval truth.
- `frontend/src/app/Application.tsx` and `pathResolver.ts`: resolve `/`, `/ip-assets[/]`, and unknown
  paths before composition. Keep `App.tsx` free of the IP page and preserve all existing
  brand/material/local workspaces.
- MinIO: never overwrite an existing content-addressed key with different bytes; verify metadata on
  every read and make rollback disable access rather than delete immutable assets.

## Pre-start review checklist

- [x] Goal and user value are explicit.
- [x] One shared no-auth intranet model is explicit.
- [x] In-scope and out-of-scope behavior are explicit.
- [x] Acceptance criteria are observable and testable.
- [x] Current reusable capabilities and incompatible static-catalog semantics are documented.
- [x] Complex-task PRD, design, and implementation artifacts exist.
- [x] Implementation/check context manifests contain real entries.
- [x] User has reviewed the final planning summary and explicitly authorized implementation in a
      subsequent message.
