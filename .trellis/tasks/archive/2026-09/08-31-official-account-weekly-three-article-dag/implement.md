# 公众号每周三篇确定性 DAG：实施计划

## Phase 0 — prerequisites and baseline

- [x] Confirm the existing weekly V2 files have a committed/owned baseline; otherwise stop before editing overlapping files.
- [x] Read weekly/editorial/database/Agent governance specs, inspect scoped diffs/migration head and freeze current weekly artifact bytes/tests.

## Phase 1 — static graph and contracts

- [x] Add versioned node/role/status/error contracts and code-owned DAG construction with cycle/dependency tests.
- [x] Define application ports for run repository, artifact handlers, governance and clock without importing infrastructure.

## Phase 2 — durable scheduler/worker

- [x] Add migration/models/repository for run/node checkpoints, uniqueness, leases and fencing.
- [x] Implement idempotent scheduler enqueue, ready-node claim, heartbeat, completion/failure and branch-local retry.
- [x] Add worker entrypoint/config/Compose/Doctor wiring with bounded concurrency and clean shutdown.
- [x] Add real PostgreSQL tests for once-only schedule, competing workers, expiry, stale completion and restart recovery.

## Phase 3 — existing handler and governance adapters

- [x] Adapt existing selection, V2 child build/validation and weekly aggregate/writer functions without duplicating rules.
- [x] Register node capabilities, root/child budgets, causal events and artifact metadata through the shared governance core.
- [x] Add deterministic interruption tests at every node and prove final bytes/fingerprints match one-shot execution.

## Phase 4 — status and checks

- [x] Add the development-only enqueue/status/retry CLI and prove the public API/OpenAPI remains unchanged; no publish action or public UI.
- [x] Run weekly/V1/V2/live fixture regressions, zero-social construction tests, migration/worker/API, Ruff/mypy/pytest/Compose/Doctor and diff checks.
- [x] Dispatch Trellis check and repair verified findings.
- [x] Add the executable weekly-DAG backend spec and backend-index entry.
- [x] Resolve the owned weekly V2 baseline first, then create one scoped DAG commit.

## Implementer verification (2026-08-31)

- Task-owned unit/integration/migration suite: 11 passed, including a restart after every static node, three-worker claims, retry/fencing, governance denial and exact fixture bytes.
- Existing weekly/V1/V2/live regression suite: 74 passed.
- Migration-head compatibility/downgrade regressions: 11 passed after advancing the expected head to `20260831_0040`.
- Scoped Ruff format/check, mypy, Compose render, Docker worker build/container help, release-head validation and `git diff --check` passed. The worker now drains its current claim on SIGINT/SIGTERM, stops claiming new work and has a 90-second Compose stop grace period.
- Doctor passed the new weekly worker, Compose and migration-declaration gates, then stopped because the already-running shared development database remains at `20260831_0038`; applying migrations to shared developer state is left to the owning session.
- No API/OpenAPI surface was added because the reviewed design permits the equivalent development-only CLI. No WeChat/WeCom client is imported or constructed.
- Final independent Trellis check, shared spec updates, commit and archive remain parent-session work by dispatch instruction.

## Risky files and rollback points

- Blocked until ownership of current uncommitted weekly modules/tests/specs is resolved.
- High collision: models/migrations/config/Compose/Doctor, official-account route/schema/OpenAPI and Agent governance adapters.
- Feature-off stops new scheduling; existing one-shot weekly functions and immutable artifacts remain valid.

## Pre-start gate

- [x] Existing weekly baseline is owned by active task `08-27-official-account-editor-automation-v2`; prior focused weekly/V2 checks passed and this task will preserve those files as the prerequisite baseline.
- [x] Shared Agent governance work is committed in `19fe3ec` and its execution-governance spec is current.
- [x] Context manifests validate.
- [x] User approves the latest parent planning summary.
