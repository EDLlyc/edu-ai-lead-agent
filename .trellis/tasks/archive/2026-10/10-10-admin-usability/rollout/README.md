# Admin usability candidate — not deployed

This task changes only the frontend and project documentation. The production-labeled admin
bundle is in `/tmp/edu-admin-usability-release/dist-admin`; its archive is
`/tmp/edu-admin-usability-release/frontend-admin.tar.gz`. See `frontend-sha256.json` for exact
bytes. The main SPA was also built separately to verify compatibility, not for release here.

Build commands, from the admin worktree's `frontend/`:

```sh
VITE_ADMIN_DATA_MODE=production npx vite build --mode admin --outDir /tmp/edu-admin-usability-release/dist-admin --emptyOutDir
VITE_ADMIN_DATA_MODE=demo VITE_API_BASE_URL=http://127.0.0.1:18102 npx vite build --mode admin --outDir /tmp/edu-admin-usability-preview/dist-admin --emptyOutDir
```

The explicit build variable controls the visible label. It does not select or authenticate the
API. Missing/invalid values show an unconfigured notice. The isolated preview's API is a fake
GET-only service on 18102 which refuses every mutation with 405. No password is needed there.

## Backend prerequisite

This frontend includes the preceding reliability change (`d555011`) and requires its compatible
backend/schema through `20261010_0061`. Do not independently replace assets against the current
production release-2/schema-0059 backend. Follow the archived reliability task's
`rollout/README.md`, `files.txt`, `preflight.sql`, Dockerfile, and offline `smoke.py`, substituting
this newer admin asset archive after backend upgrade. That handoff remains the source of truth
for the twelve backend overlay files, backups, migration preflight, quiet window, service cutover,
verification, and rollback.

No production image build, migration, cutover, model probe, publication, or production config
write occurred in this UI task. The existing production-connected preview on port 5180 and its
`frontend/dist-admin` assets remain untouched. The isolated demo at port 5181 is refreshed only
after the final bundle passes browser checks on port 5182.

## Verification / rollback

Check every artifact hash before release. After a separately authorized rollout, verify direct
admin URLs/reload, correct environment label, mobile reflow, edit cancellation, pagination with
real totals, and read-only authenticated responses. Do not publish to test the UI.

Retain the previous matching frontend directory when swapping assets atomically. If the backend
must also roll back, use the reliability handoff's rollback procedure; do not downgrade schema
or remove publication history to accommodate an older UI.
