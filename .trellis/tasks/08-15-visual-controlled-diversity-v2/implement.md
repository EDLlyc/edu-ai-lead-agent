# 配图受控多样性 v2 — Implementation Plan

## Phase 0 — Freeze baseline and contracts

- [x] Re-read the PRD/design, curated Trellis specs, and baseline research before edits.
- [x] Capture the current Alembic head, focused visual/material tests, OpenAPI/type drift, catalog
      count, and production-safe baseline query shape.
- [x] Add fixture images for perceptual calibration without using provider output or private
      production images in Git.
- [x] Confirm no live provider, Enterprise WeChat, ACR, frontend deployment, or production mutation
      is authorized by ordinary implementation/testing.

## Phase 1 — Pure visual planning domain

- [x] Add versioned scene/composition/camera/cast/slot-tone/subject enums and compatibility matrix.
- [x] Extend accepted visual context using only stored safe slot/event/category/entity/product
      projections.
- [x] Implement `visual-brief-v2-controlled-diversity` and a deterministic candidate enumerator,
      scorer, stable tie-break, primary/alternate choice, and controlled relaxation codes.
- [x] Preserve exact v1 builders/dispatch for historical versions.
- [x] Add exhaustive/unit tests for at least 10 scenes, 8 compositions, 5 cameras, three casts,
      three slot tones, invalid combinations, topic compatibility, same-input determinism, 10-item
      diversity, and primary/alternate difference.

## Phase 2 — Novelty-aware reference selection

- [x] Extend selection requests with the chosen cast/subject/scene and recent action/style asset or
      variant-group history; identity assets remain repetition-exempt.
- [x] Implement v2 novelty scoring and explicit relaxation without weakening approval, role,
      checksum, media, path, reference-count, or byte-budget gates.
- [x] Ensure single-character plans can use one identity plus action/style references, while duo
      plans retain complete approved identity coverage.
- [x] Test dominant-asset avoidance, candidate exhaustion, stable fallbacks, no style asset,
      combined-character identity, and v1 selector replay.

## Phase 3 — Migration and exact reservation lineage

- [x] Add Alembic 0021 and matching ORM for artifact diversity fields, primary/alternate plan
      reservations, attempt-aware references, perceptual results, and relational constraints.
- [x] Make legacy rows valid through nullable/default-compatible fields; do not rewrite v1 snapshots.
- [x] Refactor package reservation so manifest parsing is outside the lock, the bounded history
      read/plan/reference reservation is inside a short PostgreSQL lock, and provider/MinIO work is
      after commit.
- [x] Add real PostgreSQL tests for clean upgrade, metadata drift, previous-head upgrade, guarded
      downgrade, cross-wire rejection, same-slot sibling uniqueness, two-reserver concurrency,
      replay, and unique provider reservation.

## Phase 4 — Prompt v3 and perceptual similarity

- [x] Add v3 prompt assembly from safe plan enums while keeping all current brand/text/security
      clauses and excluding raw source/copy/private metadata.
- [x] Bind controlled v2/v3 rendering to the exact three-level `赛先生科学` + allowlisted category
      title + allowlisted short subtitle card; reuse the same allowlist for provider-rejection
      recovery and OCR while preserving exact v1 metadata/replay.
- [x] Implement deterministic perceptual hash and bounded seven-day comparison after media
      validation; calibrate the versioned threshold with the fixture matrix.
- [x] Persist safe attempt metadata and execute the pre-reserved alternate plan exactly once on the
      first near duplicate with a distinct provider-request fingerprint.
- [x] On a safe second near duplicate, store it as the final image with
      `diversity_warning=near_duplicate_after_retry`; prove no third call and no
      `review_required`/delivery block.
- [x] Keep network retry, provider-rejection recovery, OCR/quality repair, lease fencing, and
      similarity retry budgets distinct and globally bounded.
- [x] Test exact SHA duplicate, near duplicate, clearly different, threshold boundary, null legacy
      hash, provider error on either attempt, lease loss, replay, and concurrency using fake/mock
      providers only.

## Phase 5 — API and local inspection UI

- [x] Project optional safe diversity fields through material-package schemas/repositories/routes;
      keep historical responses compatible and private values absent.
- [x] Regenerate OpenAPI and frontend schema types.
- [x] Add a compact local-only visual-variation panel with slot/scene/composition/camera/cast,
      relaxation, retry, and warning status; retain polling/accessibility behavior.
- [x] Add backend contract/API tests and frontend mapping/component tests for v1, v2 distinct,
      v2 repaired, and v2 warning cases.

## Phase 6 — Configuration, operations, and specs

- [x] Add default-off bounded settings to `.env.example`, Compose service environments, Doctor,
      production evidence, README, and the image/material package runbook.
- [x] Require the relevant services to resolve identical diversity versions, lookback, threshold,
      and retry bounds, and fail startup when diversity is enabled without exact image OCR.
- [x] Validate the fixed regeneration bound through the actual Compose string environment path;
      accept only `"1"` and reject every other configured value.
- [x] Add safe baseline/observation queries for plan coverage, reference dominance, similarity
      retries/warnings, success/latency/cost, and zero unintended delivery/provider activity.
- [x] Update backend Agent Pipeline, database, error, logging, quality, directory, and slot specs
      where the implemented contract changes.
- [x] Document disabled rollout, bounded live acceptance, enablement, seven-day observation, and
      rollback without deleting v2 history.

## Phase 7 — Quality and independent review

- [x] Run focused domain/selector/similarity/material/API/frontend tests and real PostgreSQL
      migration/concurrency tests after each phase.
- [x] Run Ruff format/lint, strict mypy, full backend tests, API contract, frontend check, unique
      Alembic head/migrate/Doctor, full-profile Compose render, shell syntax, and
      `git diff --check`.
- [x] Audit no test weakening, no secret/private-path/provider-body leakage, no migration drift, no
      public API breaking change, no real provider/WeCom call, and no modification of unrelated
      dirty files or reports.
- [x] Run an independent Trellis check after implementation, fix findings, repeat affected/full
      gates, then update result/checklist and request deployment authorization separately.

## Rollback points

- Before 0021: no persistence changes; revert domain/config code only.
- After 0021 with feature disabled: keep additive schema and restore v1 settings/code path.
- After fake/replay gates: disable the master flag; no provider or delivery state needs reversal.
- After a separately approved live acceptance: disable the flag and keep all v2 artifacts/audit
  rows immutable for diagnosis; do not delete or rewrite delivered history.

## Explicit validation targets

- `backend/tests/unit/test_visual_brief.py`
- `backend/tests/unit/test_visual_assets.py`
- new visual-diversity/similarity unit tests and image fixtures
- `backend/tests/unit/test_material_package.py`
- real PostgreSQL material/slot/concurrency and migration tests
- material-package API/OpenAPI/frontend feature tests
- complete repository quality commands described in `.trellis/spec/backend/quality-guidelines.md`
