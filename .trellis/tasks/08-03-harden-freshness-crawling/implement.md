# Implementation Plan: Freshness, Orchestration, and Compliant Crawling

## Phase 1 - Contracts and settings

- [x] Add validated freshness settings and bump acquisition/scoring policy versions.
- [x] Add pure freshness decisions and stable reason codes.
- [x] Extend source profile/runtime policy data for robots/terms enforcement and safe retry delay.
- [x] Add unit tests for exact ten-day boundaries, unknown dates, and policy states.

## Phase 2 - Acquisition freshness gate

- [x] Apply discovery-time freshness filtering before detail fetch where publication metadata is
      trustworthy.
- [x] Resolve missing publication metadata from the bounded detail response, then filter before
      candidate persistence.
- [x] Persist safe filtered observations/snapshots and expose freshness counters/metadata.
- [x] Add connector/executor regressions proving stale items do not trigger normal candidate writes
      and current relevant items still do.

## Phase 3 - Readiness-aware topic scheduling

- [x] Add a repository read model for terminal acquisition/governance readiness.
- [x] Make content reconciliation poll while due and enqueue only after readiness.
- [x] Capture topic cutoffs after readiness and pass the configured ten-day freshness window into
      the immutable scoring config.
- [x] Add integration tests for startup race, pending governance, partial governance, and cutoff
      immutability.

## Phase 4 - Safe same-day revisions

- [x] Add Alembic migration for topic revision and daily-selection supersession fields/constraints.
- [x] Update enqueue/persist/query repositories and schemas to resolve the current revision while
      preserving historical runs.
- [x] Add bounded recovery for early provisional no-topic results only; reject replacement of a
      selected topic and make repeated recovery idempotent.
- [x] Update copy-generation reconciliation to consume only the current revision and test duplicate
      prevention.

## Phase 5 - Fetch hardening

- [x] Enforce recorded robots/terms policy states at the safe fetch boundary.
- [x] Parse and clamp `Retry-After` for 429 responses while preserving bounded jitter/backoff.
- [x] Add contract tests for 429 delay, 403 terminal behavior, redirect policy, and no stealth
      mechanisms.
- [x] Review source rate limits, scan/item limits, and User-Agent without expanding the approved
      source frontier.
- [x] Persist source request slots across jobs and retries so every list/detail request observes the
      configured source interval.

## Phase 6 - Verification and rollout

- [x] Run focused unit/contract tests for freshness, fetcher, scheduling, and revisions.
- [x] Run PostgreSQL/MinIO integration tests and migration checks.
- [x] Run `docker compose config --quiet`, `make doctor`, and `git diff --check`.
- [x] Rebuild/recreate the enabled service profiles and verify all long-running containers.
- [x] Verify the observed early no-topic run is superseded only through the new durable recovery
      path; inspect current topic and copy-generation state without manually editing data.
- [ ] Run the optional one-item source smoke only if operationally approved; do not make live source
      access part of ordinary CI.

## Validation Commands

```bash
conda run --name edu-ai pytest backend/tests/unit/test_freshness.py backend/tests/unit/test_topic_selection.py -q
conda run --name edu-ai pytest backend/tests/contract/test_safe_fetcher.py backend/tests/contract/test_source_connectors.py -q
conda run --name edu-ai pytest backend/tests/integration/test_topic_selection_repositories.py backend/tests/integration/test_scheduler_worker.py -q
make backend-check
make doctor
docker compose --profile content --profile governance config --quiet
git diff --check
```

## Risky Files and Rollback Points

- Risky code: `backend/app/application/services/execute_acquisition.py`,
  `backend/app/infrastructure/ingestion/fetcher.py`, `backend/app/infrastructure/db/topic_selection.py`,
  `backend/app/content_scheduler_main.py`, and related ORM/migration files.
- Rollback before migration: revert the image/config and leave existing data untouched.
- Rollback after migration: disable content scheduling/recovery, preserve the forward schema, and
  continue acquisition/governance read-only until a corrective image is available.

## Completion Gate

Do not start implementation until this plan and the design are approved. Do not declare completion
until the focused checks, real-service integration checks, Compose/Doctor checks, and a read-only
current-revision verification all pass.
