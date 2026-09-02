# Implementation Plan

## Phase A: Isolate and characterize

- [x] Create an isolated implementation worktree/branch from the reviewed production baseline and record all unrelated root-worktree changes as excluded.
- [x] Capture focused baseline tests for weekly schedule/DAG, official-account local generation, prepared draft execution, Compose and release contracts.
- [x] Query the production schema read-only to prove the real planner joins and eligible material lineage before writing repository code.

## Phase B: Scheduler and planner

- [x] Add default-off production weekly settings with strict production acknowledgement and minimum-Monday validation.
- [x] Implement the typed production weekly input planner/repository using existing stored authority, immutable scoring and delivered material lineage.
- [x] Add the scheduler entrypoint with the canonical due function, Monday 09:00 wake-up, interval catch-up and idempotent reconcile.
- [x] Add unit/integration tests for boundaries, 24-hour catch-up, restart replay, minimum week, frozen input and insufficient candidates.

## Phase C: Production DAG handlers

- [x] Add explicit fixture/production handler construction; production must fail closed if required Zhipu/worker/settings are unavailable.
- [x] Implement handler checkpoints that reuse the existing official-account local run and automatic quality contracts for the three canonical roles.
- [x] Preserve existing DAG leases, fencing, retries, sibling checkpoints and execution-governance lineage.
- [x] Test restart at each production checkpoint, upstream-not-ready retry, terminal quality failure, duplicate role/event rejection and no partial aggregate.

## Phase D: Prepared artifact and draft handoff

- [x] Add the versioned content-addressed prepared-draft batch with strict path/hash/media/HTML validation and atomic no-clobber writes.
- [x] Extend draft artifact resolution/preparation additively while preserving existing finalized-weekly inputs.
- [x] Prove all-three preflight before provider writes, exact one-job/three-item idempotency, completed-item resume and outcome-unknown no-replay behavior.
- [x] Add security tests proving no credentials, tokens, private object paths, raw provider IDs or bodies enter artifacts/logs/status.

## Phase E: Runtime and release

- [x] Add portless Compose services/profiles and Doctor/release-contract coverage without changing ordinary service start/restore lists.
- [x] Run focused Ruff/format/mypy/pytest, PostgreSQL integration, Compose render, shell syntax, secret scan, task validation and `git diff --check`.
- [x] Run the final repository gate once after the last production-code edit; distinguish unrelated dirty-worktree failures with evidence.
- [x] Update backend specs for the production scheduler/handler/prepared-batch contracts.
- [x] Commit and push only task-owned code/spec/evidence to Codeup.

## Phase F: Production activation

- [x] Build and validate an immutable linux/amd64 release whose app diff contains only reviewed task changes.
- [x] Stage a checksum-bound, single-use production operator with backups and zero-effect recovery.
- [x] Preflight WeChat access, database head, empty weekly/draft state, source/image volume integrity and disabled historical catch-up.
- [x] Activate new services before `2026-09-07 09:00`, without manual enqueue or real draft smoke.
- [x] Verify all old/new services stable with restart count 0, `due=false`, weekly/draft counts 0 and zero provider-write logs.
- [x] Record the exact first eligible schedule, monitoring query and rollback command; archive the task only after Codeup evidence is pushed.

## Validation commands

```bash
conda run --name edu-ai ruff format --check <affected-python-files>
conda run --name edu-ai ruff check <affected-python-files>
conda run --name edu-ai mypy --strict <affected-python-files>
conda run --name edu-ai pytest <focused-weekly-and-wechat-tests> -q
conda run --name edu-ai pytest backend/tests/integration/test_official_account_weekly_dag.py -q
docker compose config --quiet
python3 ./.trellis/scripts/task.py validate 09-02-wechat-weekly-scheduler-production
git diff --check
```

## Rollback points

- Before any migration: restore the prior source/image and keep all new profiles disabled.
- After additive persistence but before external writes: stop new scheduler/DAG/article/draft writers and restore the prior runtime; retain audit rows unless the reviewed downgrade proves every new table empty。
- After a WeChat side effect starts: never replay automatically; stop writers, preserve attempt state and resolve through the existing `outcome_unknown` operator path.
