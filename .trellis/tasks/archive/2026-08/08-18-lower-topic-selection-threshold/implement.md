# Implementation Plan

## Phase 1 — immutable scoring version

- [x] Add explicit `.7` historical and `.8` current scoring constants plus named `0.62`/`0.59` thresholds.
- [x] Authenticate `.7` and `.8` for identical delivered-history v4, tiered editorial and ministry-priority behavior.
- [x] Make `build_topic_scoring_config` choose the threshold by exact version.
- [x] Update Settings, Compose and `.env.example` defaults to `.8`.

## Phase 2 — regression coverage

- [x] Add `.8` metadata, fingerprint and `0.5899`/`0.5900` boundary tests.
- [x] Prove `.7` remains `0.62`/v4 and `.6` remains `0.62`/v3.
- [x] Prove delivered repeat veto still wins above `0.59` and unrelated ranking behavior is unchanged.
- [x] Update current-default API/config assertions without rewriting literal historical fixtures.
- [x] Run focused unit/real-PG tests, Ruff and strict mypy.

## Phase 3 — repository gates and source control

- [x] Update topic-selection/content-slot specs and task result evidence.
- [x] Run `make backend-check`, API/Compose drift, diff and high-confidence secret scans.
- [x] Commit only reviewed repository files and push the exact full SHA to Codeup `main`.

## Phase 4 — bounded production rollout

- [x] Build/validate an offline candidate from a clean detached worktree at the pushed SHA.
- [x] Verify production preflight: current `.7`, single `.env` owner, no `.release.env` override, healthy prior services and stable counters.
- [x] Stop services safely and create a fresh verified rollback set.
- [x] Install candidate source/image and atomically change `.env` from exact `.7` to exact `.8`.
- [x] Confirm the unchanged Alembic head and restore all 8 services, dispatcher last; no migration command was required.
- [x] Verify runtime `.8`/`0.59`, candidate image/source, restart0/health and zero release-caused provider/WeCom increment.
- [x] Do not enqueue, replay or resend today's runs.

## Phase 5 — closure

- [x] Record exact commit/image/backup/config/runtime evidence in `result.md`.
- [x] Run final diff/secret checks and archive the task when complete.
