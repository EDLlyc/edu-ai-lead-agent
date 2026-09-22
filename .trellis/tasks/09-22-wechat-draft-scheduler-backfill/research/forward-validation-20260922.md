# Forward validation and baseline test debt

## Scope

The candidate is derived from isolated `720305b6f83d4647058c9ee223fb441b39cce54d`,
not the dirty root checkout. The deployed base remains `abfb89d9371d56b1fc651e9ea0a11f50bed37724`.
No dependency, Dockerfile, Compose or Alembic file changes are part of this release.

## Completed component gates

- Prior backfill, badge regeneration, same-draft replacement and published-to-redraft fake tests:
  78 passed. The backfill integration fixture import was moved to test execution so whole-suite
  collection does not depend on unit-module import order.
- V4 geometry / Chinese-family / AI chest-badge / isolated PostgreSQL geometry recovery: 153 passed.
- Release/health independent review: 113 passed; real local read-only aggregate SQL scenarios,
  Ruff, strict typing, shell syntax and all six production Compose profiles passed.
- Offline release independent review: 51 fake tests passed; actual cached base OCI's 21 layers,
  manifest/config/revision/archive identity verified and malformed platform refused. No production
  mutation occurred in implementation/review.
- Full-tree Ruff lint and formatting passed (597 Python files at that checkpoint); strict mypy
  passed for all application/tool/release targets (289 source files).
- Two existing catalog tests passed using ignored, locally copied approved brand assets. These
  private assets are neither committed nor included in the application overlay.
- Final independent runtime review: 143 affected regressions passed, including 34 fallback
  tests. New PostgreSQL negatives reject extra/incomplete attempts, bad stage/provider, shifted
  historical dates, existing prepared/ACK state and lease drift. A real prepared-directory →
  durable journal → fake client test proves repeated delivery performs just one add. Status
  truth and diagnostic decoding were tightened; final app typing/lint/format passed.

## Full-suite result is not all-green

The full backend suite completed with **27 failures**. A separate detached `720305b` worktree was
used to rerun those exact existing tests; the candidate then reran the same list. Both focused
runs produced the identical result: **26 failed, 1 passed**. The one isolated pass on both sides
was `test_v4_rerank_applied_and_finalization_fallback_are_atomic`, indicating a full-suite
ordering/shared-fixture issue rather than a candidate-only difference.

Failure categories are existing stale migration-head/downgrade expectations, old topic-policy
expectations, an old mixed-observe prompt assertion, a date-sensitive visual-diversity test,
an absent IP evaluation method, five missing ignored editor-demo visual fixtures, and the sealed
September 16 generated-update operator's obsolete private image-normalizer override. The dated
operator is not used by this release and must not be edited or re-run to make a current check green.

The full-suite result is retained as a limitation; it is not reported as a successful full gate.
This release relies on the independently reviewed affected-runtime, PostgreSQL, prepared-contract,
delivery/journal, release and actual-image gates. It does not change unrelated topic/IP behavior,
rewrite old migrations, or relax failed assertions merely to claim a clean repository.

The final frozen-image smoke and production activation results will be
recorded separately after completion. Test success does not prove a future live image provider
request or WeChat draft acknowledgement has occurred.

## Real-image baseline exception discovered before production mutation

The first committed candidate `9a67bf8e7c88cd7827b8c57b133b616954caf783` built correctly but its
local network-none smoke rejected `offline_smoke`. Exact path/hash comparison found just one
pre-existing difference between the pinned `c98c...` base image and its nominal `abfb89d...`
Git source: `app/infrastructure/ai/zhipu.py`. The image preserves the older deployed OCR
integration; both base and candidate Git still contain the same newer OCR implementation.

- Actual pinned-base file: SHA-256 `b9aa021414acc1dcb25068bac707c97da3b52cbd5fc5cb3195ed1a3174514cd9`, 48,896 bytes.
- Base/candidate Git file: SHA-256 `3e63bf9d40131c3be51ee4351e8acec8832319f24ba5e5bfc9aab5e256f0345e`.
- All other application path/hash entries and all immutable runtime inputs matched.
- No server services or production configuration were changed; the failed candidate remains
  local evidence, not a deployed release.

The replacement builder must prove this exact one-file base-preservation contract from the
validated OCI layers, require unchanged base/candidate Git bytes for that path, exclude it from
the overlay, and explicitly record the exception. Any other mismatch stays fatal. Do not deploy
the unrelated newer OCR implementation merely to make an overbroad Git-equality claim pass.

## Real-host metadata preflight

Candidate `eaf310cd8bf2a1843a0449fa11bd91f61c5b5679` passed the real network-none
image smoke. Its first production read-only capture then refused
`protected_metadata_policy` before creating a baseline or stopping any service.
The fixed allowlist had incorrectly generalized two existing file modes:
`deploy/release/migration-compatibility.json` is `0644`, and `scripts/doctor.sh`
is `0755` (both root:root). The other eight protected files matched, including
`.env` at `0600`, UID 1000, GID 1001. The replacement operator must enumerate
these exact measured permissions and preserve them; production permissions must
not be changed to satisfy the preflight. No activation attempt was made.

## Historical terminal article-run preflight

Candidate `c7d38aa9773b6cb52b641ffd319123ba59152b43` passed the same real-image
smoke, then stopped read-only capture at `active_or_unknown_work`. Aggregate
inspection found exactly five `official_account_article_runs.result_unknown`
rows, created September 11 (three), September 14 (one), and September 16 (one).
All three lease fields are null. This table has no `expires_at` column, so the
generic JSON-field check incorrectly classified these old terminal rows as live
unknown work. No service was stopped and no baseline or activation was created.

The exact five-row cohort, including all fields except `updated_at`, has SHA-256
`636c9d034399d98ae6aaa3a507347e983c6163e2e128ca9b7354b2b624973ad9`
using ordered `jsonb_agg(to_jsonb(t)-'updated_at' ORDER BY id)`. Any release
exception must require this fixed hash, count five, creation before September 17
Shanghai time, and empty leases; it must not accept arbitrary terminal unknowns.
The article repository only claims queued or expired-running rows. Full-table
database fingerprints still protect these records across quiescence and startup;
their unknown state must never be cleared or replayed for this deployment.

The remaining inventory checks were exercised independently without producing a
baseline or bypassing any deployment gate: 620 runtime source files and all 21
database snapshot entries passed. Brand inventory exposed a second overly broad
check: seven existing data files are `0664` (the other 249 are `0644`), all owned
by UID 1000/GID 1001 and mounted read-only into the applications. Protected
configuration must retain its strict non-group-writable rule; brand data needs a
separate explicit inventory policy that preserves its measured mode and freezes
hash/size/ownership. No permissions were changed. All three named volumes use
ordinary `0600`/`0644` files, so no broader volume-permission exception is needed.

The final operator delta passed 117 fake tests, Ruff/format, strict mypy and diff
checks. An independent real-host read-only execution of the exact cohort and
exclusion SQL returned count=eligible=5, the fixed hash, and zero remaining
active/unknown Article runs. No apply or quiescence occurred during these checks.

## Terminal draft-job state preflight

The following full capture stopped at `pending_work`, still before baseline or
activation. All 14 queue/run tables were then aggregated read-only. The only
remaining falsely classified pending group was two `wechat_mp_draft_jobs.ready`
rows from September 7–8, with empty leases and no later changes. In that
repository, `ready` is the successful terminal state set by `_finish_job_ready`;
only `queued`, `retryable_failed`, or expired `running` jobs are claimable.
Fix the pending query for this table's actual state machine, preserving unknown
and lease checks and full-table fingerprints. Explicitly reject `retryable_failed`
instead of omitting it from the generic pending vocabulary. Do not clear or replay
successful drafts. The measured ready cohort hash is
`875748c456419e1e517711dce3ecc1194ff031b6f0e9dafb30c6031b6ef2b1a4`.
No other active/pending states were found beyond the already frozen seven old
preview copy jobs. Deployment and backup locks are root-owned `0600`, the backup
root is `0700`, and the backup timer is active.

## Docker mount-order preflight

Candidate `95e65157e12c776562577a3354554b13d817398c` passed real-image smoke,
full production capture and the read-only plan. Its first apply loaded and
verified the candidate image, then refused `baseline_drift` **before quiesce**.
The backup/activation attempt directory did not exist, and all original services
remained running; this was not an uncertain activation or a rollback.

Read-only comparison isolated only the weekly producer's `mounts` list order.
Repeated Docker inspections of the same un-restarted container alternated the
two destinations' order. Container identity, image, command, environment and
each complete mount record were unchanged. Canonicalize ordering at both capture
and post-start verification; never discard duplicate records or ignore source,
destination, volume identity or read-only flags. The frozen baseline must be
recaptured with the corrected, newly sealed operator before any apply.

## Historical task closure limitation

The initial exact-target backfill has five unit and two fake-repository integration
tests, not a complete direct test matrix for all Phase 2 bullets. In particular,
direct target/authorization drift, concurrent apply, expired backfill authorization,
explicit provider failure, and reconciliation exceptions remain audit-test debt.
The 78 prior operator tests must not be presented as proof of each missing case.
This does not change the separately reviewed prospective fallback's 34 tests.
Keep that Phase 2 checklist item open. Four historical test modules resolve their
operators from the active task directory; archive only with an atomic test-path
update and rerun, preserving the sealed operators and their hashes.
