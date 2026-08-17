# Implementation Plan — 部署图片供应商格式容错修复

## Phase 1 — Freeze and review tooling

- [x] Add a task-local baseline-7ba offline release operator and focused fake/recovery harness.
- [x] Reuse the existing source/image validator and offline builder logic; bind exact cbc/7ba
      identities, 321/179 counts, three runtime hash deltas and no dependency/migration drift.
- [x] Cover early/mid/late/signal rollback, stale stage/container, backup collision, source metadata,
      tag/container restore and post-failure stop-all behavior.
- [x] Run bash syntax, focused harnesses, Ruff/mypy for validators, task validate, diff and secret scan.

## Phase 2 — Commit and Codeup

- [x] Commit reviewed task-local tooling/docs without altering application commit `cbc27b2`.
- [x] Fetch Codeup, require no remote-only commit, and fast-forward push local `main`.
- [x] Verify remote main contains both `cbc27b2` and the operator commit; no force push.

## Phase 3 — Build artifacts

- [x] Create a clean detached worktree at `cbc27b2` and build the offline candidate from the pinned
      dependency base.
- [x] Run full artifact/runtime/source/OpenAPI/Alembic/fallback gates; record exact hashes and sizes.
- [x] Assemble and independently validate the protected transfer stage.

## Phase 4 — Deploy once

- [x] Take fresh double-sample read-only production baseline and safe-window evidence.
- [x] Transfer exact stage, verify remote hashes/modes, then invoke the operator exactly once. The
      unique invocation exited 1 at its post-migration Settings probe.
- [x] Do not interrupt after first stop/backup. If it exits nonzero, allow its single recovery and
      perform only independent read-only recovery verification; do not rerun.

## Phase 5 — Verify and record

- [x] Verify exact cbc image/source/markers, eight services/restart0, API/PG/MinIO health, scoring
      `.7`, OCR/diversity `true:true`, Alembic head and zero provider/WeCom delta.
- [x] Record the failed activation, fresh backup, automatic recovery, independent 16-second prior
      runtime/vector verification and exact probe root cause in `result.md`.
- [x] Update task result with successful activation hashes and final acceptance evidence.
- [x] Commit/push evidence only after production actions have stopped; archive the task and journal.
