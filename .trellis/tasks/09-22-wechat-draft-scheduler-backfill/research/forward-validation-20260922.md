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
