# Implementation Plan — 部署图片供应商格式容错修复

## Phase 1 — Freeze and review tooling

- [x] Add a task-local baseline-7ba offline release operator and focused fake/recovery harness.
- [x] Reuse the existing source/image validator and offline builder logic; bind exact cbc/7ba
      identities, 321/179 counts, three runtime hash deltas and no dependency/migration drift.
- [x] Cover early/mid/late/signal rollback, stale stage/container, backup collision, source metadata,
      tag/container restore and post-failure stop-all behavior.
- [x] Run bash syntax, focused harnesses, Ruff/mypy for validators, task validate, diff and secret scan.

## Phase 2 — Commit and Codeup

- [ ] Commit reviewed task-local tooling/docs without altering application commit `cbc27b2`.
- [ ] Fetch Codeup, require no remote-only commit, and fast-forward push local `main`.
- [ ] Verify remote main contains both `cbc27b2` and the operator commit; no force push.

## Phase 3 — Build artifacts

- [ ] Create a clean detached worktree at `cbc27b2` and build the offline candidate from the pinned
      dependency base.
- [ ] Run full artifact/runtime/source/OpenAPI/Alembic/fallback gates; record exact hashes and sizes.
- [ ] Assemble and independently validate the protected transfer stage.

## Phase 4 — Deploy once

- [ ] Take fresh double-sample read-only production baseline and safe-window evidence.
- [ ] Transfer exact stage, verify remote hashes/modes, then invoke the operator exactly once.
- [ ] Do not interrupt after first stop/backup. If it exits nonzero, allow its single recovery and
      perform only independent read-only recovery verification; do not rerun.

## Phase 5 — Verify and record

- [ ] Verify exact cbc image/source/markers, eight services/restart0, API/PG/MinIO health, scoring
      `.7`, OCR/diversity `true:true`, Alembic head and zero provider/WeCom delta.
- [ ] Update task result with backup/artifact/operator/result hashes and any recovery evidence.
- [ ] Commit/push evidence only after production actions have stopped; archive the task and journal.
