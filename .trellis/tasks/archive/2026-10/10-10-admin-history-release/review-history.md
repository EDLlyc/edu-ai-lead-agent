# Independent history / combined-release review

Status: application review and rollout-script review passed. Root subsequently completed the
source gate, candidate smoke, live cutover and postchecks; see `result.md` and `research/` receipts. Reviewed against H1–H6 and the task check manifest. No remote commands,
production writes, publication requests, model probes, commits, or preview changes are performed
by this reviewer. Application implementers and the root coordinator own their respective files.

## Release compatibility review

- Migration 0060 locks publication history before checking occupied-draft conflicts and replacing
  the unique index. Conflicts abort without deleting history. Migration 0061 adds nullable model
  load-error diagnostics; legacy rows remain explicitly unverified.
- The previous release's exact 12-file overlay remains the minimal backend change surface. The
  history service, route and schema hashes must be regenerated after H3 completion. The image
  smoke must run against those exact hashes and single schema head 0061 without network or
  production environment access.
- The recorded read-only preflight confirms the expected six-service base image, schema 0059,
  no occupied-draft conflicts and no publication jobs. It is evidence of that instant only;
  rerun base/config/idle admission immediately before cutover, outside documented slot windows.
- Because the older acquisition scheduler remains running, stop target consumers and recheck
  idle before the database backup/migration. Pending durable jobs must survive restart. Preserve
  the seven legacy service identities and the existing credential configuration.
- A normal image/frontend rollback retains schema 0061. If manual reconciliation occurs after
  cutover, freeze publishing during rollback because the previous UI cannot explain that
  provenance. Do not automatically downgrade or erase publication history.

## Findings fixed

- Audit description rendering assumed each `detail.changes` value was an object. An unknown
  future action containing a null change could throw and hide the entire page. Coordinated with
  the audit implementer, who added safe unknown-to-object narrowing and a future/null/scalar/
  malicious-text regression. Publication query/reconciliation labels and note/result rendering
  match the actual backend audit payloads.
- The paginated publication route inherited per-row account-name lookups. Requested one bounded
  account-name preload from the publication implementer, who implemented one deduplicated query
  for the whole page. Single-job mutation responses preserve their existing lookup.
- `rollout/cutover.py` initially excluded container inspection from logs but still logged image
  inspection. Both are now excluded because image configuration can also contain environment data.
- The original frontend replacement used two renames, briefly removing the live path. Replaced
  it with Linux `renameat2(RENAME_EXCHANGE)` for both install and rollback. A temporary-directory
  probe on the target filesystem runs before any service stop; unsupported exchange aborts early.
- Final business counts were only reported after service restart. Added assertions for schema,
  enabled source/seed counts, stored-key count, bound-account count, publication count, and absence
  of occupied-draft conflicts before accepting the release.
- Automatic rollback could have restarted the old API after a new manual reconciliation or
  uncertain publication. It now checks those states through a read-only, migration-compatible
  row-JSON query. An unsafe result or failed check leaves the API stopped, restores the five other
  target services, retains additive schema and emits `ROLLBACK_FORWARD_FIX_REQUIRED`. The normal
  zero-conflict case restores all six services and the matching frontend.

## Application review conclusion

- Audit request generations and request-specific append tokens cover initial/page requests,
  filter changes, refresh, retries, API/callback replacement, unmount and loaded A → pending B → A.
  A failed page keeps the earlier rows and offers the same cursor for retry; duplicate requests
  and obsolete success/failure/session-expiry responses cannot replace or unlock current state.
- Publication queries use bounded offset/limit, closed statuses, validated date/range bounds,
  matching count predicates, and deterministic `created_at DESC, id DESC`. Inclusive business
  dates become half-open UTC bounds; DST dates are covered by the integration tests. No new
  migration is required for the history query.
- The UI binds each response to the account, tab, filters, page and visit identity. History filters
  never affect the draft occupancy response; pending publication/reconciliation guards, concurrency
  token, nonoverlapping polling, errors/retries and shrinking last-page behavior are preserved.
- No remaining application defect was found. The release-only checks below do not claim that
  production has already been changed or that final H5/H6 gates have completed.

## Verification

Independent reviewer verification:

| Check | Result |
|---|---|
| Changed frontend ESLint | PASS |
| Full frontend strict TypeScript | PASS |
| Audit component tests | 19 PASS |
| Publication safety/pagination/history/client tests | 29 PASS in four files |
| Changed backend Ruff | PASS |
| Backend Mypy, three changed application files, project configuration | PASS |
| Cutover script Ruff and compilation | PASS |
| Isolated local cutover checks | 7 PASS; no remote operations |
| `git diff --check` | PASS |

The local rollout harness at `/tmp/edu-admin-history-release/check-cutover-local.py` extracts only
helper definitions and the rollback handler with AST; it never executes the production script's
top level. It checks real temporary-directory atomic exchange/probe/error/rollback behavior,
inspection-log exclusion, read-only provenance-query shape, five-service health checks, and
rollback decisions for zero, unsafe and unavailable publication evidence. Rollout assertions and
the actual target filesystem probe still run during the real release.

The implementer separately reported 33 passing real-PostgreSQL publication cases, including 14
new history cases; final full gates, browser checks, offline image verification and production
receipts belong to the root coordinator. Postcheck review recommended requiring all three key
consumers to report fresh, verified `{}` load errors and checking heartbeat-error logs rather
than accepting mere field presence; the root owns that script and final verification.
