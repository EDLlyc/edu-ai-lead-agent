# Approved combined admin release

User approval: “好的，请你处理” following the explicit plan to fix audit records, add publication
record pagination/filters, and deploy the preceding reliability and usability batches together.
The candidate consists of twelve backend files over the verified release-2 image, migrations
0060/0061, and the separate production-labeled admin bundle. No dependency/config-secret changes.

## Exact artifacts / preflight

- `files.txt`: exact deployed-base and candidate backend hashes; Dockerfile copies only these.
- `frontend-sha256.json`: production-labeled assets, built outside the live preview directory.
- `preflight.py`: read-only live image/config/source/schema/work checks; no provider calls.
- `preflight-state.json`: sanitized admission snapshot, revalidated in cutover before stopping.
- `smoke.py`: run in the candidate image with no network, environment file or production mounts.
  Verify every backend hash, schema head, import boundary and new OpenAPI projection.
- `candidate.json` is generated only after the final source gate and offline image smoke; it binds
  the candidate image ID, source commit, and exact frontend asset hashes.

Run `make predeploy-check PY_RUN=` with the edu-ai interpreter on PATH, from the exact final
application source commit. Save the report before deploying. Existing private-asset skips remain
explicit; no new test failures are waived. Rebuild any artifact after a source change.

## Cutover

Run `cutover.py` as root on the production host, from its staged artifact directory. It checks the
quiet window, original container IDs/images/config hashes, twelve base file hashes, and idle work.
Only six previously upgraded services are stopped/recreated. Seven older services, Postgres/MinIO,
stored keys, credentials and existing config remain intact.

After stopping the six target services, recheck idle, save a custom-format database dump and
verify its restore listing; back up configs and existing frontend. Preserve queued durable work.
Change only the application image pin, migrate through 0061, restart six services, and verify
health, unauthorized HTTP refusals and preserved business counts. Frontend directories are swapped
atomically using Linux `renameat2(RENAME_EXCHANGE)`, probed before stop. A failed probe aborts.

Run `postcheck.py` afterward: it uses an isolated Python process with a projected operator role and
read-only DB transactions to verify protected route responses and editor restrictions. This is
not a claim of an actual password login. It creates no session, changes no credentials, starts no
application lifespan/background tasks, and calls no provider APIs. Require fresh successful
heartbeats from the API/content/infographic services and no new tracebacks or heartbeat errors.
The separate HTTP checks verify the running service still rejects unauthenticated requests.

Then refresh production preview5180 against its existing loopback API tunnel and refresh the
isolated demo5181 against its own fake API18103. Verify direct URLs/reload, visible environment
label, asset hashes, and unauthorized API behavior. No real publication is used as a smoke test.

## Recovery

The script retains root-only backups and sanitized receipts. A normal failed cutover restores
the original image pin and matching frontend, then verifies old-service health while keeping the
additive schema. Never downgrade 0060/0061 or delete history to force a rollback.

If the new API has recorded an unknown result/manual reconciliation, or that guard cannot be read,
keep the acquisition API stopped during rollback, restore only the five workers, and report
`ROLLBACK_FORWARD_FIX_REQUIRED`. Resolve the publication state with compatible code before
re-enabling API publication. Existing unknown/reconciled history is never silently discarded.

Template-worker upgrade, public HTTPS, other legacy services/cron images and real model probes are
outside this release. An updated mainline may only be fast-forwarded after successful deployment.

## Completed execution

Deployed 2026-10-10 13:40 CST from source `0a68c7d`, image `sha256:da05208214aa273084fd2bccb9ce86dbdc1c0ee2069a855706a5d058686e2df7`. See `../result.md` and `../research/*-result.json`. `build-candidate.py` records image identity and runs the offline check. Mount its check at `/app/.admin-history-smoke.py`: mounting at `/smoke.py` put the wrong import directory first and caused a pre-cutover `ModuleNotFoundError`; correcting the launcher passed without any application-source/image-input change. No production environment is supplied to that smoke.

`check-preview.mjs` verifies the refreshed local production preview and the separate demo without logging in or sending writes. Temporary paths in that evidence helper describe this execution; regenerate them for a later release. The previous local SSH tunnel had exited, so it was replaced with keepalive settings before the preview checks.
