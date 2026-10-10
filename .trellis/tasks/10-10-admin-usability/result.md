# Admin usability result — 2026-10-10

All U1–U6 acceptance requirements are implemented and verified. The refreshed isolated preview is
`http://127.0.0.1:5181/admin/` (simulated data, read-only API, automatic demo owner, no password).
The production-connected preview at 5180 and production services were not changed.

## Delivered behavior

- Responsive source/publication cards, bounded long names/selectors, contained keyboard-accessible
  comparison tables, and consistently sized controls/reconciliation forms.
- In-memory unsaved protection for menu/history/logout/reload/close/cancel, including unsubmitted
  keyword input and credential/account forms. Local cancel is scoped; save failure retains values;
  successful save/discard clears the guard; session expiry forces login. Submitting forms freeze
  inputs until the request settles to prevent late edits disappearing on success.
- Offset pagination for draft/published lists, totals/ranges, 20/20/5 last page, retry, shrinking
  totals, stale-response isolation, and account/tab reset. Publication confirmations, uncertainty
  locks and reconciliation tokens remain intact. Returning to an unresolved previously visited
  context cannot revive actionable stale drafts.
- Statistics emphasize numbers with separate missing-day coverage, retaining zero/missing and
  calendar semantics. Publication status uses labelled badges and explicit reconciliation form.
- Explicit build-time demo/production/unknown environment labels, visible even on login.

## Final verification

| Gate | Result |
|---|---|
| Full frontend ESLint / strict TypeScript | PASS |
| Changed TS/TSX/CSS Prettier / git diff check | PASS |
| Full frontend Vitest | 50 files, 345 tests PASS (37 more than baseline) |
| Main + agent-workbench generated API parity | PASS |
| Backend OpenAPI export check, worktree PYTHONPATH | PASS |
| Admin demo and explicit-production builds | PASS, separate output directories |
| Main SPA production build | PASS, separate output directory |
| Independent Trellis review | Two findings fixed, no remaining implementation defects |
| Final bundle responsive browser matrix | 10 pages × 390/768/1366 = 30 checks; no page overflow, clipped controls, JS errors or writes |
| Expanded forms / confirmation layouts | 12 browser checks on developer preview PASS; final bundle interactive checks PASS |
| Real browser interactions | Nine grouped flows PASS; see browser-interaction-report.json |
| Refreshed 5181 demo smoke | Deep-route reload, demo badge, 45-item pagination, writes refused with 405 PASS |

Real browser interactions covered menu/Escape/focus, cancelled logout without a write, native
beforeunload on reload, repeated back cancellation without history growth and subsequent forward,
failed and intercepted-success saves, both 45-item lists/account switching, scoped model-form
cancel without secret persistence, and forced login after a simulated expired session.

The only forwarded test mutation was a keyword save to the isolated fake server and was rejected
with 405. Simulated success/401 were intercepted inside Playwright. No real provider, publication,
credential or production mutation was sent. Native browser prompt wording remains browser-owned.

## Evidence and release handoff

- `review-usability.md`: independently reproduced/fixed round-trip context and pending-save issues.
- `research/browser-report.json`, `research/browser-interaction-report.json`: final browser evidence.
- `/tmp/edu-admin-usability-preview/`: final demo bundle, fake server/fixtures, harnesses, screenshots,
  process IDs/logs, and final test output. Temporary validation preview 5182 is stopped; 5181 +
  isolated fake API18102 remain running. Prior demo processes are stopped, with their files retained.
- `/tmp/edu-admin-usability-styles/`: expanded-form and earlier responsive inspection evidence.
- `rollout/README.md`, `rollout/frontend-sha256.json`: production-labeled candidate hashes and
  prerequisite backend release through schema 0061. The current production is still the prior
  release; production image build/migration/deployment are not claimed by this task.
- `.trellis/spec/frontend/admin-console.md`: durable contracts for forms/history, pagination,
  responsive data, environment labels, and release separation.

The overview dashboard remains outside this approved batch. No backend code, migration, dependency,
production config, or real publication was changed. Preserve the pre-existing node_modules symlink.
