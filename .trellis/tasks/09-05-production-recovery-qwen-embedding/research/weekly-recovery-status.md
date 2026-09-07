# September 7 weekly recovery status

Status at 2026-09-07 09:38 Asia/Shanghai: prevention fix implemented and under independent review;
production recovery has not executed. Existing production services remain running.

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
- Independent check and recovery operator verification are still in progress.
- No production source, config, schema, image, article, or draft changes executed as of this record.

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
Only two runtime files change. No Qwen migration, .12 scoring activation, URL weakening, new model,
schema migration, public publishing, or original terminal-run reset is included.
