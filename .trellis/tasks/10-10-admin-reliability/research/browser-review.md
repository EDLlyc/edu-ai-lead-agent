# Browser verification — 2026-10-10 10:56 Asia/Shanghai

Result: **PASS**. Actual built admin bundle, Chromium, 1440 × 1050 desktop viewport.
No application JavaScript errors, unexpected external requests, or UI blockers were observed.

## Isolation and review entry

- Preview: <http://127.0.0.1:5181/admin/>. It is loopback-only and visibly identifies
  `演示账号（模拟数据·只读）`; no password is needed for these static fixtures.
- Its only upstream is a separate static fixture server at `127.0.0.1:18101`.
  Every non-GET request is refused with HTTP 405. It has no database, credential or provider code.
- Playwright also intercepted all admin requests and blocked other origins. Its recheck and
  reconciliation responses were in-memory simulations. No publication request was submitted.
- Existing preview `5180`, production APIs and `frontend/dist-admin` were untouched.

## Checks

| Check | Evidence |
| --- | --- |
| Open and reload the admin entry plus all 11 real menu routes | 24 successful document navigations, correct visible section and demo account |
| Real built assets and scoped API routing | JS asset 200; missing assets, unrelated APIs and nonexistent admin endpoint 404; demo write 405 |
| Publication confirmation | Selected account and both article titles visible; explicitly states no follower mass send |
| Unknown publication result | Occupied drafts have no publish button; records show an actionable unknown state |
| Recheck and reconciliation | Recheck did not submit; no recheck for missing provider identity; evidence plus explicit checkbox required before reconciliation |
| Statistics coverage | 25/30 stored days, missing five days and missing two of the last seven; chart/table mark missing days; separate complete all-zero account displays measured zero |
| Model keys | Saved version shown separately; only 1/3 consumers confirmed for the failing provider; unreadable key and legacy unknown heartbeat remain explicit |

Screenshots were inspected: reconciliation actions, missing-data chart/cards and model status table
are readable and actionable at the checked desktop size. Mobile redesign remains the already
deferred second batch. These checks verify browser behavior using fixtures, not live WeChat behavior
or the independent database/integration gates.

## Local artifacts and reproduction

All artifacts are under `/tmp/edu-admin-reliability-preview/`:

- `browser-report.json`, `browser_review.mjs`, `fixtures.json`, `mock_server.py`.
- `01-publish-confirmation.png`, `02-publish-unknown.png`, `03-publish-reconcile.png`.
- `04-statistics-gaps.png`, `05-statistics-measured-zero.png`, `06-model-load-failure.png`.
- `build-sha256.json`, `processes.json`, `preview.log`, `mock.log`.

Build (from `frontend/`, without replacing the running production-linked frontend):

```sh
VITE_API_BASE_URL=http://127.0.0.1:18101 node node_modules/vite/bin/vite.js build \
  --mode admin --outDir /tmp/edu-admin-reliability-preview/dist-admin --emptyOutDir
node /tmp/edu-admin-reliability-preview/browser_review.mjs
```

Build files: `assets/index-BCenyluj.js`, `assets/index-C_FTzGYV.css`, `admin/index.html`.
The manifest records SHA-256 hashes. Long-running demo processes were left available for review:
mock PID `100173`, preview PID `100174`; confirm current process identity before stopping them.
