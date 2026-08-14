# Implementation plan

## Execution strategy

Implement sequentially in one task because the migration and origin/delivery contracts are atomic.
Use one `trellis-implement` sub-agent for the vertical slice and one independent `trellis-check`
sub-agent after implementation. The main agent owns planning changes, cross-agent coordination,
spec updates, commits and finish-work.

Do not touch or include the pre-existing dirty `.agents/skills/trellis-break-loop/SKILL.md` or any
untracked `reports/` files.

## Phase 0 — preflight and baselines

- [x] Run `trellis-before-dev` and load the curated implement context.
- [x] Reconfirm current git status, unique Alembic head `20260807_0019`, Compose profiles and no
      unrelated worktree overlap.
- [x] Run focused baseline tests for acquisition scheduling/repositories, topic selection/delivery,
      copy/material package, WeCom delivery, topic APIs and frontend material mapping.
- [x] Record current OpenAPI hash/generated-type cleanliness and current migration upgrade/downgrade
      baseline.

## Phase 1 — shared slot domain and migration foundation

- [x] Add exhaustive shared slot/schedule value objects, timezone-aware preparation/target/expiry
      helpers and bounded settings. Unit-test invalid enums, DST/timezone behavior, bounds and all
      three default schedules.
- [x] Add Alembic `20260814_0020` and SQLAlchemy models for slot runs/scores/selections, acquisition
      slot identity, copy-origin XOR, delivery windows and nullable slot job metadata.
- [x] Preserve historical rows and legacy partial indexes; make downgrade fail safely if live
      slot-origin rows would be lost.
- [x] Add real PostgreSQL migration tests for tables, columns, checks, FKs, partial unique indexes,
      cross-slot event uniqueness, copy-origin XOR and upgrade/downgrade.
- [x] Gate: affected Ruff/mypy plus migration integration tests pass before orchestration changes.

## Phase 2 — slot-aware acquisition, readiness and selection

- [x] Extend scheduled acquisition creation/recovery with optional typed slot while preserving exact
      legacy null-slot behavior and manual idempotency.
- [x] Register one preparation cron/reconciliation per enabled slot and add restart/catch-up tests;
      slot mode off must execute the current daily schedule unchanged.
- [x] Resolve exact terminal acquisition/governance lineage for a slot and persist immutable cutoff;
      unrelated same-day runs cannot satisfy readiness.
- [x] Refactor existing pure score computation without changing legacy `select_daily_topic` results.
- [x] Implement `slot-ranking-v1` from stored governed/editorial/product signals, after eligibility;
      persist affinity/reasons/order and explicit unfilled reasons.
- [x] Implement transactional run/item persistence, date-level advisory lock, exact/same-day
      exclusions and concurrency/replay convergence.
- [x] Add bilingual unit fixtures for all three preferences, Ministry global priority, no-rescue,
      veto independence, 0/1/2/3 selections, stable ties and cross-slot dedupe.
- [x] Add PostgreSQL integration tests for slot acquisition keys, readiness lineage, immutable
      scores, concurrent selection, daily event uniqueness and legacy daily coexistence.
- [x] Gate: acquisition + governance readiness + topic-selection focused suites, Ruff and strict
      mypy pass.

## Phase 3 — independent copy, image and package lineage

- [x] Add discriminated legacy/slot `LockedTopicContext` and repository loaders; reject missing or
      dual origins.
- [x] Reconcile one copy run per selected slot item with independent idempotency/version identity.
- [x] Carry safe slot/ordinal/target/expiry projections through copy runs, material package snapshots
      and JSON downloads without changing factual prompts or evidence boundaries.
- [x] Prove each item independently runs the current 180--240 target copy policy, evidence/source
      footer, brand RAG, IP asset selection, image validation/audit, repair and fallback.
- [x] Test sibling isolation: one no-topic/failed/review-required copy or image does not cancel,
      duplicate or retry another selection.
- [x] Test at most nine distinct daily slot copy/image/package identities and exact replay.
- [x] Gate: copy/material/image unit + repository integration suites, Ruff and strict mypy pass.

## Phase 4 — delivery windows, ordering and durable 60-second gap

- [x] Create/reconcile one typed delivery window per slot/recipient/provider/mode and one formal job
      per eligible slot package before expiry.
- [x] Preserve the legacy date-wide formal guard for legacy origins; new slot queries must use typed
      relational slot/window fields, not mutable JSON or creation timestamps.
- [x] Extend claim logic to lock the window, require `not_before`/`next_allowed_at`, choose the lowest
      ready ordinal and advance the lane by the configured gap before any provider call.
- [x] Persist typed expiry without provider calls and ensure an unready/failed/unknown lower ordinal
      does not block ready siblings.
- [x] Preserve text-before-image, child persistence, image integrity, lease/heartbeat, bounded retry
      and `delivery_unknown` no-auto-resend semantics.
- [x] Add clock-controlled unit and PostgreSQL concurrency tests for no-early-send, 60-second gap,
      concurrent dispatchers, restart, expiry, partial/unknown results, sibling continuation and
      legacy guard compatibility.
- [x] Gate: full WeCom unit/contract/integration suites, Ruff and strict mypy pass with zero external
      provider calls.

## Phase 5 — additive API and frontend slot board

- [x] Add typed create/run/scores/content-edition schemas and routes with stable conflicts and safe
      projections; keep `DailyTopicResponse` unchanged.
- [x] Add optional slot/ordinal/window fields to material package projections and generated package
      downloads.
- [x] Add API integration tests for disabled, missing, preparing, partial, 0-item, 1--3 item, failed,
      expired and complete slot states plus legacy daily responses.
- [x] Regenerate checked-in `backend/openapi.json` and frontend generated schema once backend shapes
      are final.
- [x] Add a date-oriented three-slot frontend view using generated types, one API mapper/hook and
      reused material-package cards. Show loading/empty/unfilled/preparing/ready/failed/expired and
      delivery states without publishing controls.
- [x] Add mapper, hook, component and accessibility tests including 0/1/3 items, sibling failures,
      source links and keyboard behavior.
- [x] Gate: `make api-contract-check` and focused frontend tests/typecheck/build pass.

## Phase 6 — configuration, operations and specs

- [x] Wire all slot settings identically to migration/API/acquisition/governance/content/WeCom
      services in `.env.example` and Compose; default slot mode and all slot enables remain false.
- [x] Update doctor and production evidence with safe feature/slot/window/gap and queue counters; do
      not expose content or credentials.
- [x] Update the production runbook with preparation timing, manual enqueue/read-only verification,
      morning→noon→evening rollout gates, disabling slot mode and no-resend rollback behavior.
- [x] Update `backend/topic-selection.md`, `backend/agent-pipeline.md`,
      `backend/wecom-delivery.md`, `backend/database-guidelines.md`, relevant frontend specs and README
      so “daily Top 1” is clearly legacy and the new slot contract is versioned.
- [x] Run `docker compose --profile governance --profile content --profile wecom config --quiet`,
      `bash -n` on changed shell scripts and `git diff --check`.

## Phase 7 — complete verification

- [x] Run affected tests first, then `make backend-check` exactly once after the final backend edit.
- [x] Run `make frontend-check` exactly once after the final frontend/generated-contract edit; if
      host memory prevents parallel Vitest workers, rerun the same suite with one worker and record
      the environment limitation rather than weakening tests.
- [x] Run `make doctor`, full-profile Compose render, Alembic unique-head/upgrade/downgrade checks,
      API contract check and `git diff --check`.
- [x] Run a controlled offline full pipeline for all three slots with fake providers: prove 0--3
      independent packages, exact cross-slot dedupe, no early/late provider calls, persisted gap and
      historical replay.
- [x] Audit changed/untracked files, secret-shaped content, authenticated URLs, migration/API drift
      and accidental modifications to unrelated dirty paths.
- [x] Dispatch independent `trellis-check`; repair any material spec, type, test, cross-layer or
      security finding and rerun proportionate gates.

## Rollback points

- Slot mode defaults off, so application rollback before activation is configuration-only.
- Before any later production activation, back up PostgreSQL/MinIO/brand materials and record the
  prior image digest through the separate deployment task.
- Disable slot mode to stop new slot scheduling; do not delete slot rows, downgrade Alembic or resend
  expired/unknown jobs.
- Legacy daily mode remains usable only after verifying no new slot job is running and no slot
  delivery window is still open.
