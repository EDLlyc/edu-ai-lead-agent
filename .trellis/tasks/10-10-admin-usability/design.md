# Design

## Existing contracts and decisions

- Keep the existing typed AdminApi/WeChatApi injection architecture for this focused improvement;
  no router/store/UI library migration or dependency install. No backend wire changes required.
- Responsive table opt-in: `data-responsive="cards"` on source/job tables, visible per-cell
  `data-label` values; preserve semantic headers and desktop tables. Long titles may wrap by word,
  not be squeezed to a one-character column. Shell/fields use min-width:0 and bounded widths.
- Shared CSS vocabulary: `statusBadge` keyed by `data-status`, `reconcileForm`, `pagination`,
  `environmentBadge` keyed by `data-mode`; implementation owners coordinate exact use.
- Central in-memory unsaved-navigation provider: form-owned dirty state registers with a narrow
  guard context; shell consults it for menu/logout/history. Explicit cancel uses the same guard.
  Use accessible confirmation with keep-editing/discard-and-leave actions and browser beforeunload
  only while dirty. Session expiry is forced; no secret drafts in storage or URLs.
- Pagination uses the existing per-account offset + total contract (20 records per request).
  A small keyed page loader or hook owns request identity/cancellation, page state/loading/error.
  Disable stale content/actions while changing context. Do not add redundant hand-written wire
  response types; keep polling/refetch behavior compatible with late API state.
- Explicit `VITE_ADMIN_DATA_MODE=demo|production`; all other/missing values map to unconfigured.
  Its text is an operator-set environment label, not authentication or a backend security check.
  Read-only demo writes remain blocked by the isolated mock server. Do not infer from Vite PROD.
- Statistics reuse current pure date/coverage functions; split value and coverage presentation.

## Ownership

1. Responsive/styles worker: Admin.module.css; SourcesPage (mobile markup only); WeChatStatsPage
   and tests; ModelsPage (mobile markup only), optionally layout/other table markup after coordination.
2. Guard/shell worker: new unsaved provider/hooks/tests; AdminApp/tests; KeywordsPage/tests;
   SourceEditor/tests; account and WeChat binding/model key form guards (coordinate ModelsPage
   with worker 1; other form files are yours). Environment mode utility and badge shell markup.
3. Pagination worker: WeChatPublishPage/tests and pagination hook/tests if useful; wechat/api.ts
   only if necessary; responsive job markup and reconciliation layout/status badges. Coordinate
   with guard worker to protect reconciliation and account/tab switches through the shared API.
4. Root: task/specs, combined QA, demo fixture/harness updates outside repo, release handoff,
   scoped commit. No rebuilding frontend/dist-admin or touching production preview 5180.

## Verification and release

Build demo to /tmp/edu-admin-usability-preview/dist-admin with explicit demo label. Use the isolated fake API on 18102 and validate the bundle on preview5182 before refreshing
preview5181; all fake writes remain rejected.
Production-target build is separate with explicit production label, requires reliability backend.
Run full frontend suites and true browser navigation/forms/pagination/reflow against injected data.
Keep prior source branch and existing production services untouched. No database migration in
this task; backend code remains as verified by the previous final predeploy gate.
