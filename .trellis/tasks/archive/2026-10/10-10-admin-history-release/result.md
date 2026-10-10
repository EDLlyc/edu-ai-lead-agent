# Admin history release — completed

The user-approved history fixes and the preceding reliability/usability batches are live as of
2026-10-10 13:40 CST. Application source is `0a68c7df32de101eb5296ce6a873b3ea716022ee`.
Deployment receipts and release-helper corrections after that commit do not change application source.

## Delivered behavior

- Audit history discards obsolete initial/page responses after filter, refresh, retry and account
  context changes; a page failure preserves earlier rows and retries the same cursor. Publication
  recheck/reconciliation entries have clear Chinese labels and safe result/note rendering.
- Publication history shows all records, 20 per page, with total/range and status/inclusive
  creation-date filters in the business timezone. Account/tab/filter changes isolate old responses;
  history filters do not affect draft occupancy locks or manual-reconciliation safeguards.
- Previous completed batches are included: uncertain-publication recovery and reconciliation,
  honest model-load diagnostics and statistics coverage, mobile navigation/layout, environment
  labels, unsaved-edit guards, and paginated draft/published content browsing.

## Verified source

- Frontend: 52 files / 371 tests; full lint/types; changed-file formatting; generated main/agent
  API parity; production admin, demo admin and main SPA builds PASS.
- Backend: 33 publication integration cases rerun after the final TypeAdapter change, plus 30
  other admin cases against PostgreSQL; Ruff, bare/configured Mypy and OpenAPI parity PASS.
- Independent review: no unresolved application findings; 7 isolated cutover-script tests PASS.
- Built-browser checks: 7 history scenarios, 9 preceding interaction scenarios, 6 history-page
  responsive checks at 390/768/1366; no JS errors or horizontal overflow. Fake-data write tests
  were intercepted locally; no real publication or provider/model probe was performed.
- Exact final gate:
  `predeploy gate PASS @ 0a68c7d+dirty: 10 passed, 0 failed, 1 skipped (2026-10-10T05:32:49+00:00)`.
  The only dirty entry was the pre-existing untracked `frontend/node_modules` symlink. All tracked
  application code was committed. The skip requires the absent private visual asset manifest;
  unit/contract tests reported zero known failures and no new failures.

## Live cutover

- Image: `sha256:da05208214aa273084fd2bccb9ce86dbdc1c0ee2069a855706a5d058686e2df7`.
- Base: `sha256:24e967081b2e9b303a1f295e7e99eacd24ed96304d5cbb5bd3645270fe159249`;
  all 12 old file hashes matched; all 12 candidate hashes/imports/OpenAPI/schema checks passed
  in a network-disabled container without production env or data mounts.
- Six services upgraded: acquisition-api, acquisition-worker, content-scheduler, content-worker,
  wecom-infographic-producer, wecom-dispatcher. All run the candidate with zero restarts and
  no startup tracebacks, model-overlay errors or heartbeat errors.
- Schema `20261009_0059` → `20261010_0061`. Backup and migration admission ran with the target
  services stopped and no active jobs/conflicts, outside the push windows.
- Verified backup: `/var/backups/edu-ai/admin-history-20261010T053904Z`, including root-only
  configs, old frontend and 101,876,511-byte custom-format DB dump with restore-list and SHA256
  verification. Database dumps and secret configs stay on the server.
- Ten enabled seeds, zero stored model keys, one bound WeChat account and zero publish jobs
  were preserved. Seven legacy service identities and Postgres/MinIO stayed intact; `.env`
  and Compose hashes did not change. Only `APP_IMAGE` changed in the release pin file.
- API health is 200; real HTTP requests without authentication still receive 401. A separate
  isolated process with read-only DB transactions verified owner projections, editor restrictions,
  four invalid-query refusals, new pagination metadata and statistics coverage. This is not an
  end-user password-login test; it created no session and did not alter the running API's auth.
- API/content/infographic consumers report fresh, successful load diagnostics. Older non-reporting
  consumers remain explicitly unverified. The account has all 30 statistics dates in the checked
  2026-09-10 through 2026-10-09 range.
- Frontend was installed by atomic directory exchange at `/var/www/edu-ai-admin`; exact asset
  hashes are in `research/candidate.json`. Old frontend remains at
  `/var/www/edu-ai-admin.before-20261010T053904Z`.

## User previews and recovery

- Production-data preview: `http://127.0.0.1:5180/admin/`, new production-labeled bundle via an
  SSH tunnel to the live loopback API. Existing credentials remain valid and unchanged. Four direct
  routes and reloads show the login screen correctly; missing assets/unproxied paths return 404.
  Served asset hashes match production, mobile login has no overflow and no JS errors were seen.
- Read-only fake-data demo: `http://127.0.0.1:5181/admin/`; its environment is explicitly labeled.
  It contains 65 fixture publication records so the new pagination and filters can be inspected.
- Recovery restores the old image pin and matching frontend while retaining additive schema.
  If unknown/reconciled publication records exist, or their guard query fails, keep publishing
  stopped and require a compatible forward fix; never delete history or downgrade the database.
- Template-worker application/upgrade, overview dashboard, poster styles and public domain/TLS
  remain outside this release. Local preview availability depends on the running local process
  and SSH tunnel. No remote Git push was performed.

Sanitized source/browser/release evidence is under `research/`; reviewed operations are under
`rollout/`. Mainline is fast-forwarded only after the successful deployment and local closeout.
