# Result — completed and frontend released

Application source: `6b5465e50c2b10fe9afd1c8e7fa3e3f91514ba74`.
Accepted R1–R5 on 2026-10-10; installed and verified at 16:26 Asia/Shanghai.

## What changed

- Console-scoped Chinese system fonts, functioning weight fallback, 26/24 px page titles,
  18 px section titles and consistent secondary text, cards, tables and actions.
- Phone navigation always identifies the current page and expands all permitted groups.
  Escape, keyboard focus, responsive resize and the existing dirty-navigation guard work together.
- Model/template instructions use native disclosures; live errors, unknown state and saved-layout
  limitations remain visible. Article-preview HTML and all operational API behavior remain intact.

## Verification

Full frontend: 53 test files / 376 tests PASS, lint/typecheck, main/agent OpenAPI parity,
normal and explicitly labeled admin production/demo builds PASS. Independent Trellis review
fixed desktop short-field wrapping and found no remaining blockers. Final browser inspection
covered 50 page/width cases and two additional table breakpoints, narrow/long-name and 200%
text reflow, menu roles, keyboard/dirty/focus behavior, and four unchanged sandboxed templates.
See `research/verification.md` and `research/browser-validation.json`.

Source gate:

```text
predeploy gate PASS @ 6b5465e+dirty: 10 passed, 0 failed, 1 skipped (2026-10-10T08:21:03+00:00)
```

The only untracked path at the gate was the tooling `frontend/node_modules` symlink; tracked
source matched the commit. The skip requires the existing private visual asset manifest.

## Frontend rollout

`rollout/frontend_release.py` staged and verified all asset hashes, saved the exact prior frontend,
then atomically exchanged `/var/www/edu-ai-admin`. It checked all 16 container identities/images,
starts/restarts and configuration hashes before and after; none changed. No backend recreation,
database change, actual publishing/sync, provider request or credential action was performed.

- Stage: `/var/tmp/edu-admin-typography-20261010T081308Z`.
- Backup: `/var/backups/edu-ai/admin-typography-20261010T081308Z/frontend`.
- Previous assets: `/var/www/edu-ai-admin.before-20261010T081308Z`.
- Restore frontend only by verifying and exchanging the previous assets back; never restore
  backend/configuration/database state for this presentation-only release.
- Candidate hashes and sanitized receipts are in `research/`; no raw environment/configuration
  contents or credentials are stored there.

Stable preview URLs are `http://127.0.0.1:5180/admin/` (production API) and
`http://127.0.0.1:5181/admin/` (isolated read-only fixtures). Both use the task-specific bundles
under `/tmp/edu-admin-typography/`; process metadata is in that directory. The expired API SSH
tunnel was restored. Temporary 5182/5183 validation previews were stopped after acceptance.

Production login/reload across five routes, protected GET 401, missing assets/routes 404 and all
asset hashes passed. Demo verifies its read-only label, 65 fixture history records, exact bundle
hashes and 11 mobile destinations. Authenticated UI/interaction acceptance used local fixtures,
not production credentials or writes. Re-run the fixture browser harness with
`ADMIN_REVIEW_ORIGIN=http://127.0.0.1:5181 node <archived-task>/rollout/check-browser.mjs`.

Mainline receives this task by fast-forward; the root checkout's unrelated edits and mainline's
untracked evaluation labelling directory are excluded. No remote push is part of this work.
