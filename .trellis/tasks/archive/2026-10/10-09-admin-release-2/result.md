# Admin release 2 — deployed 2026-10-10

Owner approval: “同意上线。” Cutover completed at **10:03:00 Asia/Shanghai**;
production read-only checks completed at 10:05:49. Application revision `9eaaaf3` is unchanged.

## Deployed and checked

- Exactly six approved services run
  `sha256:24e967081b2e9b303a1f295e7e99eacd24ed96304d5cbb5bd3645270fe159249`.
  API healthy; every service running with zero restarts, tracebacks or model-overlay errors.
- Base and overlaid file hashes: 42/42. Offline image smoke passed. Full provider-free gate:
  `predeploy gate PASS @ 12cccd6+dirty: 10 passed, 0 failed, 1 skipped`.
  The skip is the absent local private visual asset manifest. Independent review also passed
  backend lint/types, 45 admin frontend tests, frontend lint/types/build and API schema parity.
- Migration `20261008_0054` → `20261009_0059`; all 10 enabled seeds/sources preserved.
  Affected running/queued work counters were zero before cutover, outside all push windows.
- `ADMIN_SECRET_KEY` and `MODEL_SECRET_KEY` were generated and mapped without printing values.
  API, content-worker and wecom-infographic-producer report fresh model-consumer heartbeats.
  There are zero stored model keys, so all providers retain existing env keys.
- Existing production account bound as **赛先生** (editable display name), with verified
  credentials stored encrypted. Read-only provider checks: 6 drafts and 14 published records.
  First statistics sync succeeded for 2026-10-10: 21 article-stat rows and 30 account-daily rows.
  These are row counts, not a claim of 21 distinct articles. Publish-job count remained zero.
- HTTP `/healthz` returns 200; unauthenticated admin auth/models/accounts/WeChat/template
  endpoints return 401. Browser login page loads with no JavaScript errors. Existing password
  was neither read nor reset; an authenticated browser session was not exercised.
- Frontend static build and SHA manifest installed at `/var/www/edu-ai-admin`. Local preview:
  `http://127.0.0.1:5180/admin/`, same-origin proxy via SSH loopback tunnel on 18100.
  Local process metadata and screenshot: `/tmp/edu-admin-release-20261010/`.

## Scope retained

- Seven older services remain on `83a41e41` with unchanged container IDs; Postgres/MinIO were
  also preserved. Layout choices do not reach the old draft worker yet. Model-key changes
  reach only three services; other consumers keep using environment keys.
- No real publication was submitted. Public HTTPS needs the domain/certificate and is outside
  this release; no public port or internal API exposure was added.
- The existing model overlay can report a version whose decryption failed; follow-up recorded
  in the independent review and admin spec. Initial empty-table deployment does not hit it.
- The main checkout's exhibit connector now permits the new image digest; 20 connector tests
  passed. Its previous uncommitted changes were preserved, and the connector was not restarted.
  That mixed working-tree file is intentionally not included in this branch's commit.

## Backup and rollback

Production directory: `/var/backups/edu-ai/admin-release-2-20261010T015738Z`.

- Root-only `.env`, `.release.env`, `compose.yaml` and `database.dump`.
- Dump size 101026477 bytes; `pg_restore --list` verified its table-data entries.
- Dump SHA-256: `82963c4852cfc0fc59bc3b252b706a018b47299d821636162a1d4a8e77fce977`.
- Original configs also mirrored as `*.before-9eaaaf3-20261010T015738Z` in the app directory.
- To roll back, restore the three configs and recreate the same six services. Keep additive
  schema 0059 and the bound account. The earlier image is
  `sha256:5a5fb24ccaccf1894e3d857e583f412fb01526dd4bd5f71f83125bd2482f92b7`.

Sanitized receipts are in `research/cutover-result.json` (before account import) and
`research/postcheck-result.json` (after import/sync), plus `research/review-20261010.md`.
