# Admin reliability first batch — implementation complete

The five approved fixes are implemented on `fix/admin-reliability-20261010` in the admin
worktree. Production remains on release 2; no publication, credential rotation or production
configuration change was performed for this task.

## Delivered behavior

1. Confirmation identifies the account and every article, with accurate public-publication wording.
2. Uncertain submissions keep the draft occupied. Recheck never resubmits; owner reconciliation
   needs evidence/confirmation and a version token. Audit and late-response isolation preserve
   operator decisions. Failed polls reach unknown at 30 minutes. Invalid provider receipts are
   rejected before they can break database persistence.
3. Known admin pages support direct navigation/refresh in Vite dev and preview, while missing
   assets and unrelated APIs retain 404 responses.
4. Statistics recover missed dates within 30 days and run independently of publishing. Explicit
   date bounds, missing-date coverage and partial totals distinguish missing data from real zero.
5. Model versions are reported as loaded only after successful application. Safe failure status
   and legacy unknown heartbeats are visible; unchanged bad ciphertext does not cause restarts.

## Verification evidence

Final full predeploy gate: **PASS — 10 passed, 0 failed, 1 skipped** at
2026-10-10T02:59:21Z against the final working-tree application bytes. Unit/contract tests
report zero known or new failures. The skipped authoring evaluation requires the absent private
visual asset manifest; it is not reported as passed. See `research/predeploy-final.md`.

- PostgreSQL admin suite: **47 passed**. Independent final-review polling run: **5 passed**,
  including **2 additional** malformed-receipt cases (49 distinct integration cases validated).
- The initial full gate found a missing lifecycle test setting; its fixture now mirrors real
  application setup, with all client-close assertions preserved. Its file plus statistics tests
  passed (19 cases); no production fallback was added.
- Relevant initial backend units: **48 passed**. After review, adapter units: **29 passed**,
  including seven additional boundary cases; final bytes were rerun successfully.
- Frontend: **308 tests passed** across 47 files, including 65 admin/route cases. Complete ESLint,
  TypeScript, changed-file Prettier, ordinary build and isolated admin build passed.
- Backend: full app/tests Ruff lint, formatting of 657 files and mypy over 374 app source files
  passed. Deterministic backend OpenAPI and generated frontend contract checks passed.
- Alembic: single head `20261010_0061`; upgrade from 0059 exercised against isolated PostgreSQL;
  conflicting occupied history is refused without deletion. Local candidate smoke verifies 12
  final backend hashes, imports and schema head without provider traffic.
- Independent code review found and fixed malformed provider receipts, with no remaining R1–R5
  blocker. Actual Chromium checked 12 routes plus reload, recovery UI, gaps/zero, load failures,
  true 404s, and no JavaScript errors/external requests.
- Read-only production preflight: all 12 base file states match, schema 0059, zero historical
  occupied conflicts and zero publish jobs. Repeat these checks when deploying.

## Review preview

<http://127.0.0.1:5181/admin/> — explicitly labelled read-only simulated data, no password.
All writes are refused by its isolated mock API. Existing production-connected preview 5180
and its built bundle are unchanged. Six screenshots and the browser harness remain under
`/tmp/edu-admin-reliability-preview/`; detailed evidence is in `research/browser-review.md`.

## Deployment handoff

Credential-free backend/frontend archives are prepared in `/tmp/edu-admin-reliability-release/`,
with hashes recorded in `rollout/archives-sha256.json`.
`rollout/` contains the exact 12-file overlay manifest, Dockerfile, frontend checksums,
read-only migration preflight SQL, provider-free smoke and backend-first/paired-rollback steps.
The actual Docker candidate build against the production base is a deployment prerequisite;
that image is not installed on the local Docker daemon. This task does not claim it was built.
Production rollout requires a separate owner-approved cutover. Pagination, unsaved-form guards,
mobile cards, overview page, public-domain setup and old draft-worker upgrades remain outside
this first batch.
