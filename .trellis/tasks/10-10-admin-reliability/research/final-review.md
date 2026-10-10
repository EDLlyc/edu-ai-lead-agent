# Independent reliability review

Reviewed R1–R5 in `fix/admin-reliability-20261010` against the task PRD/design,
admin-console contract, database/error-handling guidelines, frontend component/types/quality
guidelines, and production-mainline boundary. Review and tests used the admin worktree; provider
traffic was replaced with fakes. No production mutation, real publication or model call occurred.

## Findings (fixed)

- Files: `backend/app/infrastructure/wechat_official_account/admin_client.py`,
  `backend/tests/unit/test_wechat_admin_publish_client.py`,
  `backend/tests/integration/test_admin_wechat.py`.
  A successful-looking poll response with an article ID longer than the database's 128-character
  limit, or containing NUL, reached PostgreSQL and raised a persistence error. This bypassed the
  bounded poll-error transition and could leave a job publishing indefinitely. The adapter now
  rejects these receipts with the existing safe provider error, so the 30-minute deadline still
  produces `outcome_unknown`. It also rejects malformed poll error codes and non-string/NUL URLs.
  The submit receipt now rejects NUL publish IDs as immediately uncertain rather than reaching
  the database. Seven new adapter cases cover these boundaries, and two new PostgreSQL/API
  parameters prove an unusable success receipt becomes unknown and can later be rechecked
  successfully without another submit.

## Findings (not fixed)

None within R1–R5. Production rollout and the approved second batch remain outside this task.

## Cross-layer checks

- Publication confirmation includes the selected account and every title, and accurately describes
  public publication without follower mass send. Owner-only reconciliation requires a confirmation,
  bounded note and an optimistic `updated_at` token; the state change and audit commit together.
- Unknown and succeeded drafts stay occupied in the service and PostgreSQL partial unique index.
  Recheck only invokes the status API. Late polls compare the observed state after reacquiring a
  row lock; late submits also require the unique claim identity. WeChat statuses 5/6 preserve
  successful-publication occupancy with the deletion/blocking explanation. These branches do not
  persist the provider's optional article identity or URL.
- Migration 0060 locks before conflict preflight and index replacement, refuses conflicting
  history without deletion, and guards destructive downgrade. 0061 is the single successor and
  preserves null load diagnostics for legacy consumers. Model metadata matches the migration.
- Statistics use explicit configured-business-date bounds through yesterday, recover missed and
  missing account dates within 30 days, and leave network calls outside open DB transactions.
  Failed calls do not advance the success watermark. UI gaps differ from true zero; partial sums
  identify known values. Missing-day coverage does not claim per-field completeness; legitimately
  omitted optional counters retain the existing zero convention.
- Separate lifecycle tasks keep slow statistics requests from delaying publication and cancel both
  loops during shutdown. Model consumers report successfully loaded versions separately from
  attempts/errors; unchanged bad ciphertext does not cause restart loops.
- Vite document fallback uses the actual section registry and preserves queries. Admin-mode MPA
  fallback plus the anchored API proxy leave missing assets and unrelated API routes unproxied/404.
- Generated API fields and frontend consumers agree. Updated `admin-console.md` documents the
  reliability contracts, including statuses 5/6 and malformed success receipts.

## Verification

- Reviewer: publication adapter unit tests **29 passed**, including the 7 newly added boundaries.
- Reviewer: bounded-poll PostgreSQL/API test **5 passed**, including the **2 new** oversized/NUL
  success-receipt cases. This followed the coordinator's original 47-case integration run; the
  additional cases were independently verified, not claimed as one combined 49-case run.
- Reviewer: targeted Ruff lint and format checks **pass**; targeted strict mypy **pass**.
- Reviewer: complete frontend ESLint and TypeScript project build/check **pass**.
- Coordinator supplied: original admin integration **47 passed**, relevant backend units
  **48 passed**, frontend admin/routes/view tests **65 passed**, and generated API parity passed.
  The coordinator owns final gate/build/browser verification and release manifest regeneration
  after these review fixes; those broader results are recorded in the final task evidence.

Review implementation edits are complete. No remaining blocking finding from this review.

## Coordinator gate follow-up

The first full gate exposed one lifecycle fixture missing `test_app.state.settings` after the
new independent tasks began reading application state. The real application already initializes
that state. The fixture now does likewise, without changing production behavior or removing
client-close assertions. Its full test file plus statistics tests passed (19 cases); targeted
Ruff/format/mypy passed. The second complete gate after this final test-only fix passed: 10 passed, zero failed,
one skipped private-visual-manifest evaluation; unit/contract tests have zero known/new failures.
