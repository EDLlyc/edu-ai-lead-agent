# September 7 weekly recovery status

Status at 2026-09-07 10:14 Asia/Shanghai: source compensation completed; three articles are ready
and a prepared batch is validated. Actual draft staging remains blocked by the confirmed consumer
inbox/mount mismatch. A narrowly scoped wiring correction and ordinary-CLI handoff are under review.

## Incident evidence

- Deployed commit: `5c560da71bcbb61b765d3fe82c742cf2d5e676e1`; database head `20260901_0042`.
- Original weekly run: `0ae1c882-4254-561f-bdac-17d254c0c166`, September 7; terminal at 09:02:11.
- Application source package `b290e00b-1e00-43a3-a69f-8f3bdb05137f` contained HTTP evidence.
  The full existing article-source contract rejects it. This branch created no article/model request.
- Two original live Zhipu/GLM-5.2 article runs are ready:
  `85f62fb9-0e96-4a9e-95c0-48a99043fdd3` and `24ad4ddc-7c1e-46e3-a787-acff86a1f102`.
- Original DAG attempts: ten succeeded, three failed; no original aggregate or draft jobs/items.
- Read-only full-preflight replanning at the original cutoff
  `2026-09-07T01:00:00.095359+00:00` preserves the first two selections and selects
  `198969a7-056d-482b-81f4-8219cbd2106b` as the application replacement.
- Standard production backup completed at `20260907T013135Z`: PostgreSQL 41,342,094 bytes,
  MinIO 3,201 files, private brand archive 210,227,952 bytes. No secret values were exported to logs.

## Verification so far

- Implementer: 72 focused units; Ruff/format for five code/test files; strict mypy for two runtime
  files; isolated PostgreSQL first-attempt terminal/no-repeat regression passed.
- Expanded candidate suite: 98/104 unit and 9/10 PostgreSQL passed. Exact production baseline
  has the same six unit and one PostgreSQL failures caused by absent ignored private PNG fixtures.
  There are no new failures in that comparison; the broad suite is not fully green.
- Independent product/recovery check: 92/92 focused tests passed, including three real PostgreSQL
  regressions; Ruff, format and strict mypy passed. Initial read-only production rehearsals found
  and fixed absent-first-inbox and ORM rollback expiration compatibility issues before any enqueue.
- Read-only sealed plan `d935acffe5a45e9389264de7043de20cd65f9b1cd8ed9d5110a008daeba59615`
  succeeded. Reviewed recovery script SHA `7320dca2df6eef091f2263ab754c8f49264718b11840df537accddfbca6ab8d6`.
- Source/recovery work committed as `117e59b` and pushed to Codeup and GitHub on the incident branch.
- One replacement article `1c8a0cc8-b960-4b33-82ff-e7204def40f6` started at 09:52:14 and became
  ready at 09:53:23 on its first attempt. Both original ready article identities and protected hashes
  were preserved, as were the original failed governed run and attempts.
- Recovery batch `abb680a1b8e52df9395a033199c1844b6cb2d919eaeef72a9fe196b9e8864bea`, aggregate
  `4d25b6c7c81055c101101100d18682d3aedf61d52228d662710b397b422248c5` is validated in the inbox.
  The audit truth is `inbox_ready`, not delivered or published.
- Actual draft consumer used `/app/input/weekly-inbox`, while the shared volume is mounted at
  `/app/input/official-account-weekly-editions`. Correct inbox is that mount plus `weekly-inbox`.
  No draft job had been created when this second defect was confirmed. No production source,
  config, schema, or image change has executed yet.

## Bug analysis

### 1. Root cause category

Cross-layer contract mismatch plus a test coverage gap: the planner treated successful material
quality and nonempty snapshots as sufficient, while article enqueue enforced stronger URL,
evidence, brand, and field constraints.

### 2. Why retries failed

All three attempts reused the same frozen invalid source. No infrastructure or provider retry
could change this input. An ordinary terminal-node retry remains correctly prohibited.

### 3. Prevention mechanisms

- Reuse the complete pure article-source projection before deduplication and ranking.
- Map known deterministic enqueue input failures to terminal `invalid_selection`.
- Cover invalid newer material and older same-event valid fallback; preserve transient errors.
- Preserve successful artifacts and original failure audit during the separately sealed recovery.

### 4. Systematic expansion

The same input validation must remain authoritative at selection and enqueue, including the final
outer Pydantic source model. A generic runtime exception must not be swallowed as material failure.
A recovered edition and its original failed governed run are separate truths.

### 5. Knowledge capture

The executable contract is recorded in
`.trellis/spec/backend/weekly-production-source-preflight.md` and indexed from the backend index.
This application repository has no `src/templates/markdown/spec/` template tree to synchronize.

## Scope fences

The release worktree is `.trellis/worktrees/weekly-source-preflight`, branch
`release/weekly-source-preflight-20260907`, based on exact deployed 5c560da.
Two runtime Python files and one exact Compose consumer inbox value change. No Qwen migration,
.12 scoring activation, URL weakening, new model,
schema migration, public publishing, or original terminal-run reset is included.
