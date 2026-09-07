# September 7 weekly recovery status

Status at 2026-09-07 10:26 Asia/Shanghai: the recovered edition has one ready draft job and three
succeeded WeChat drafts, with one attempt per role. A repeated reconcile returned the same ready
job with zero new enqueue. Prevention code and the Compose correction are committed and pushed;
immutable release checks are still finishing. Original failed DAG history remains unchanged.

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

## Actual draft completion

- A further first-use installation check found the empty draft-artifact volume root owned by
  `0:0` with mode `0755`, while the existing app process uses `999:999`. The exact named volume
  `edu-ai-lead-agent_wechat_mp_draft_artifacts` was checked against its current container mount,
  physical inode, empty contents and permissions. Only that directory's owner was changed to
  `999:999`; mode/inode were preserved, no recursive change or inbox write was made. Actual
  app-user write access then passed. Future fresh installations must provision this same writable
  artifact-root ownership; do not run the worker as root or loosen the read-only inbox mount.
- A single normal `reconcile --once --maximum 1` ran in the existing draft container with only
  its inbox path overridden for that invocation. No service was stopped and no additional provider
  executor was started. The existing daemon processed the immutable staged copies normally.
- Job `a13a7121-3f3e-57b0-a091-2d55741d55fb` enqueued at 10:24:24; `ready` at 10:24:49.
  Official/industry/application roles all `succeeded`, one attempt each, endpoint `draft_add`,
  with 5/5/6 images uploaded respectively. Three distinct safe draft-media fingerprints prove
  three independent accepted draft results; no raw media IDs or credentials are in evidence.
- At 10:25:43 a repeated corrected-path reconcile reported `discovered=1, enqueued=0, existing=1`
  and the same ready job. At 10:26 the ledger remained exactly one job, three items, three succeeded
  attempts, three distinct draft fingerprints, zero active draft leases or runnable draft jobs.
- All 14 production containers were running; API, PostgreSQL and MinIO health checks passed.
  Both original article completion timestamps and the original ten successful/two retryable/one
  terminal DAG attempts were unchanged. These are unpublished drafts, not public articles or sends.
- An additional backup using the checksum-verified deployed-source backup entrypoint completed
  at `20260907T021845Z` with its release evidence manifest. The legacy installed sbin entrypoint
  lacks that manifest; the prevention release must use the verified source entrypoint instead.

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
