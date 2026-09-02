# Result

## Outcome

- Application commit `40e4dec0ae82569fc798355d4515ab0009697c6f` implements the production weekly planner, Monday scheduler, production DAG handlers, immutable prepared-draft handoff, and draft-worker integration.
- Documentation hardening commit `a4a3c00` records the activation stdin isolation gate. Both commits are pushed to `feature/wechat-weekly-scheduler-production` on Codeup.
- Production runs immutable image `edu-ai-lead-agent-backend@sha256:cda49d5666c4e42e9d3c9ad0aac18c743f9a5ebcc800f0395b7e3c4169352bf0` built from the application commit.
- Twelve application services are running on that image with restart count zero. PostgreSQL and MinIO are healthy; `/healthz` returns HTTP 200; Alembic is at `20260901_0042`.
- Scheduler reconciliation logged `due=false`. Weekly run/node/attempt counts, draft job/item/attempt counts, and weekly output files are all zero. No Zhipu or WeChat provider work was triggered during rollout.
- First eligible execution is Monday `2026-09-07 09:00 Asia/Shanghai`. It may create exactly three independent unpublished WeChat drafts and cannot publish, mass-send, or pin them.

## Validation

- Focused Ruff formatting/lint, strict mypy, Compose rendering, Bash syntax, secret/path scans, PostgreSQL planner replay, prepared-artifact contracts, weekly/DAG/draft tests, and `git diff --check` passed.
- The focused production regression set passed with the real ignored brand assets mounted read-only.
- Full backend run completed with `1834 passed`; its 33 failures reproduced known checkout/environment dependencies (ignored brand assets plus shared local DB/business-worker expectations) and the same affected weekly/WeChat tests passed in the isolated focused run.
- Production read-only planner replay selected three distinct real roles and generated a stable frozen input fingerprint without enqueueing a run.

## Operational Evidence

- Live evidence: `/var/lib/edu-ai/weekly-production-activation-evidence.txt` (root-only, mode 600).
- Rollback snapshot and copied evidence: `/var/backups/edu-ai/releases/weekly-production-40e4dec0ae82-20260902T061642Z`.
- Pre-deployment full backup: `20260902T055756Z`.
- Monitoring: inspect the three weekly/draft table triplets, scheduler `official_account_weekly_reconciled` events, all 12 service restart counts, and the shared weekly output volume.
- Rollback before any external side effect: stop `official-account-weekly-scheduler`, `official-account-weekly-dag-worker`, `official-account-local-worker`, and `wechat-official-account-draft-worker`; restore the source/config/runtime snapshot above and start the prior service set. After a WeChat side effect starts, preserve audit state and never automatically replay an unknown draft attempt.

## Bug Analysis: Remote activation stopped after migration

### 1. Root Cause Category

- **Category**: E — Implicit assumption.
- **Specific cause**: `docker compose exec -T postgres ...` inherited the stdin-backed SSH heredoc. The child command consumed the remaining activation script after migration, so the shell reached EOF before the service-start and verification commands.
- **Confidence**: 99%. The activation output stopped exactly after the first Compose exec; two later diagnostic heredocs reproduced the same cutoff, and `</dev/null` made the remaining commands execute.

### 2. Why Earlier Checks Did Not Resolve It

1. The first inspection command had a formatting error before service output and did not discriminate between script completion and partial activation.
2. A full Compose status command produced oversized output, hiding the concise state needed to identify that every application container was stopped.
3. Migration success was initially treated as progress inside the same script, but it did not prove the caller still had unread commands.

### 3. Prevention Mechanisms

| Priority | Mechanism | Specific action | Status |
|---|---|---|---|
| P0 | Architecture | Install and execute a root-owned activation file, or redirect every stdin-capable child command from `/dev/null` inside SSH heredocs | Done |
| P0 | Runtime gate | Require candidate image, running state, restart count, API health, migration, scheduler due state, DB counts, and output-volume checks before declaring success | Done |
| P1 | Documentation | Add the stdin-isolation and post-migration acceptance contract to the weekly production spec | Done |
| P1 | Evidence | Atomically persist root-only activation evidence in live state and the rollback snapshot | Done |

### 4. Systematic Expansion

- Similar risk exists in any stdin-streamed release, backup, migration, or diagnostic script that invokes `docker compose exec`, `ssh`, or another command that reads stdin.
- Release completion must be defined by observed end state, not by the last visible intermediate command.
- Concise per-service inspection is safer for remote acceptance than an unbounded full Compose dump.

### 5. Knowledge Capture

- [x] Updated `.trellis/spec/backend/official-account-weekly-dag.md`.
- [x] Pushed the spec update in commit `a4a3c00`.
- [x] Stored production activation evidence and rollback coordinates.
