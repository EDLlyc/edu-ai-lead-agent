# Current single-daily seams and migration consequences

## Purpose

This note records the repository evidence that constrains the three-slot/multi-selection design. It
is not a replacement for the PRD or design; it prevents implement/check agents from treating the
change as “add two cron expressions.”

## Current orchestration

- `backend/app/scheduler_main.py:30-56` owns one acquisition reconciliation and one daily cron. The
  scheduled acquisition key is `(business_date, timezone, acquisition_version)` in
  `backend/app/infrastructure/db/models.py:168-188` and duplicated deliberately in the repository
  lookup/recovery paths at `backend/app/infrastructure/db/repositories.py:116-208`.
- Governance already reconciles every terminal acquisition run independently
  (`backend/app/governance_scheduler_main.py:38-48`), so slot-aware acquisition lineage can reuse
  the existing acquisition-to-governance boundary.
- `backend/app/content_scheduler_main.py:40-88` owns one content cron and a polling reconciliation.
  `backend/app/application/services/topic_selection.py` skips when the one current daily run is
  locked.
- Content target settings are a single hour/minute at `backend/app/core/config.py:77-91`. Compose
  passes the same settings to migration/API/schedulers/workers, so slot settings must remain one
  shared typed contract.

## Current selection and downstream identity

- `TopicSelectionRunModel` stores one selected event/version and one no-topic code. Its current run
  key is date/timezone/profile/revision (`backend/app/infrastructure/db/models.py:1344-1449`).
- `DailyTopicSelectionModel` stores one selected event/version, has one row per run, and has a
  partial unique current key on date/timezone/profile
  (`backend/app/infrastructure/db/models.py:1544-1637`).
- `CopyGenerationRunModel.daily_topic_selection_id` is non-null and the copy identity is unique by
  daily selection + version fingerprint (`backend/app/infrastructure/db/models.py:1980-2050`).
- Material-package/image identity is already downstream-run-specific. Once a slot selection has a
  distinct copy run, existing request fingerprints prevent two successful image/package artifacts
  for that content unit.
- `select_daily_topic` persists a full score row for every candidate and exact historical config
  snapshots. `.4`, `.5`, and `.6` dispatch cannot be reinterpreted to make multi-select work.

## Current copy and image policy

- The active copy validator targets 180--240 Hanzi and emits the existing bounded repair warning
  only above 260 (`backend/app/domain/copy_generation.py:512-552`). This is the correct independent
  full-copy policy; the 80--120 summary proposal applies only to a rejected digest design.
- `LockedTopicContext` currently knows only the daily selection. It needs a typed origin projection
  so legacy daily and new slot selections use the same generator/auditor without guessing from JSON.
- The content-driven visual catalog, deterministic selector, per-request reference fingerprint,
  image validation/audit, one repair, and catalog fallback have already passed live acceptance.
  Multi-slot work must create independent requests, not duplicate this policy.

## Current Enterprise WeChat behavior

- `WeComDeliveryExecutor` sends text first and records it before reading/sending the image; lease
  recovery skips successful children (`backend/app/application/services/wecom_delivery.py:278-378`).
- The dispatcher claims the oldest job continuously. It has retry backoff inside provider adapters
  but no durable gap between different packages (`backend/app/wecom_dispatcher_main.py:88-104`).
- Automatic reconciliation excludes all later formal jobs once any package on that business date
  has a durable formal job (`backend/app/application/services/wecom_delivery.py:636-676`). This is
  an intentional legacy safeguard and cannot be deleted globally.
- The existing group provider also has a process-local 20-message/minute guard. The requested
  60-second package gap is stricter but must be database-authoritative across processes.

## API and frontend assumptions

- `GET /api/v1/daily-topics/{business_date}` returns singular `selected_event_id` fields through
  `DailyTopicResponse`; generated frontend types depend on that shape.
- The material-package frontend already lists multiple packages, but its topic projection carries
  only business date/event identity. Slot, ordinal, target/window, unfilled reasons and slot state
  need generated wire fields and one mapper update.
- Existing package UI behavior (evidence, copy, image, quality, review/download) can be reused for
  each item. A date/slot grouping view should compose current cards instead of cloning them.

## Recommended architecture

1. Preserve legacy daily selection tables and APIs as-is for exact historical replay.
2. Add a parallel slot orchestration aggregate: slot run, persisted scores, and 0--3 ordered slot
   selections. This avoids forcing a multi-valued decision into singular legacy run columns.
3. Add a nullable slot-selection origin to copy runs and require exactly one of legacy daily origin
   or new slot origin. All downstream copy/image/package code consumes a shared typed topic context.
4. Add nullable `content_slot` to new scheduled acquisition runs and extend the scheduled unique key;
   historical null-slot rows remain under the legacy unique key.
5. Reuse `.6` to compute eligibility and hard vetoes. Add a separate immutable
   `slot-ranking-v1` ordering layer after eligibility. Slot affinity never changes total,
   `passes_threshold`, `eligible`, or vetoes.
6. Persist delivery windows/lanes and assign each slot package an ordinal. A transactional lane
   reservation owns `next_allowed_at`; the claim path advances it by the configured gap before any
   provider call. Each job also owns `not_before` and `expires_at`.
7. Branch automatic reconciliation by typed origin: retain the date-wide legacy guard for old daily
   packages; use package/slot/window identities for new rows.
8. Add new slot collection endpoints and frontend projections. Do not change the existing daily
   Top 1 response shape.

## Alternatives rejected

- **Three cron jobs over the current daily key:** later jobs converge to the morning run and cannot
  produce new content.
- **Three independent legacy Top-1 revisions:** repeats scoring and cannot atomically enforce the
  slot cap/order or explain unfilled positions.
- **Change `.6` totals with slot keywords:** could create eligibility, breaks historical replay, and
  duplicates existing governed editorial/product features.
- **Remove the date-wide WeCom guard:** makes legacy regenerated/historical packages sendable after
  restart or deployment.
- **Use `asyncio.sleep(60)` between packages:** loses state on restart and is bypassed by concurrent
  dispatchers.
- **One fused digest package:** contradicts the explicit product decision for independent copy and
  image per news item.

## Migration and verification implications

- Next migration follows current head `20260807_0019`; it must preserve all legacy rows and add real
  PostgreSQL unique/check/FK constraints for slot identity, daily cross-slot event uniqueness,
  copy-origin XOR, delivery ordinals/windows, and persisted throttle lanes.
- Upgrade/downgrade, concurrent enqueue/claim, replay, expiry, partial/unknown delivery, and exact
  legacy API/config behavior require integration tests.
- The feature spans acquisition, governance readiness, selection, copy/image/package, delivery,
  API/OpenAPI, frontend, Compose/settings, doctor and operations docs. It is one atomic compatibility
  task with staged internal gates, not independently releasable child tasks.
