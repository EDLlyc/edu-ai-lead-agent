# Operations Console UI

## 1. Scope / Trigger

Applies to `frontend/src/features/admin/` and the separate `/admin/` entry. This
authenticated operator console follows [backend admin contracts](../backend/admin-console.md),
including explicit publication confirmation and uncertain-result recovery. It does not change
the manual-only boundaries of the material workspace or editor-handoff demo.

Keep the existing injected `AdminApi` / feature API architecture for focused maintenance.
No router, cache library, or wire-schema migration is required for a UI-only improvement.

## 2. Signatures

- `UnsavedChangesProvider` wraps the entire console, including login/environment presentation.
- `useUnsavedChanges(dirty, reset)` registers an in-memory form and returns
  `requestDiscard(action)` for cancellation of that form alone.
- `useUnsavedNavigation()` exposes `requestNavigation(action)` for whole-page changes,
  `isDirty()`, and `clearAll()` for forced session expiry.
- `useAdminHistory()` owns menu/history navigation. Admin-created entries carry integer
  `eduAdminPosition`; restoring a blocked traversal uses `history.go`, never a new sentinel entry.
- `usePublicationPage` owns account/tab/offset request identity and refresh state. Its ready/loading
  state gates the non-overlapping job-polling effect in `WeChatPublishPage`.
  `PUBLICATION_PAGE_SIZE` is 20; list APIs already accept `offset` and return `items` / `total`.
- `adminDataMode(value: unknown)` accepts only `demo` or `production`, otherwise `unknown`.

## 3. Contracts

### Edits and credentials

Register both submitted-list edits and text still being typed. Freeze each submitting form's inputs while its request is pending. Saving successfully clears dirty
state; a rejected save keeps entered values in component memory so the operator can correct them.
Never put drafts, passwords, provider keys, or account secrets in storage, URLs, logs, or history.
Cancelling one provider form must not discard another provider's key draft on the same page.
Menu/account/tab transitions and logout must confirm dirty edits before making their side effects.
Forced session expiry clears registration and returns to login without a leave-page prompt.

The accessible alert dialog focuses “continue editing”, traps focus, supports Escape to stay,
makes background content inert, and restores focus. Attach `beforeunload` only while edits exist;
browser-controlled reload/close prompts require a user interaction and use browser wording.

### Pagination and publication

Account or list-tab changes reset offset to zero. Late responses from another API/account/tab/page
must not replace the current view. Returning to a previously visited key still waits for the current
request; an old snapshot must not re-enable publication. While loading a different context, hide old items; while refreshing
the same context, existing items may remain visible but publication actions stay disabled.
Recheck current draft identity and open-job lock before submitting. Keep both confirmation steps,
all article titles, submit deduplication, uncertain-result locks, and reconciliation concurrency token.
When totals shrink below the current page, request the new last page. A failure is an explicit
retryable state, never an empty successful list. Stop obsolete polling on context change/unmount.

### Presentation and environment

Source/job tables opt in to mobile cards using `data-responsive="cards"` and per-cell `data-label`.
Comparison tables use a `tableScroll` region with `tabIndex={0}`, `role="region"`, and an accessible
name. Fix content sizing; never mask page overflow. Verify 390, 768, and 1366 px with long names.
Statistics show numeric totals separately from coverage labels; `0` is known zero, `—` is missing.
Use textual status badges; unknown results remain amber and failed results red.

`VITE_ADMIN_DATA_MODE=demo|production` is an explicit **build-time** operator-supplied label.
Missing/invalid values show an unconfigured warning. Never infer data source from hostname,
`import.meta.env.PROD`, or build optimization. The badge is not authentication or proof of origin.
A read-only demo must independently reject writes in its isolated API. Production-target builds
must be paired with compatible backend/admin schema versions; UI labels do not establish that.

## 4. Validation & Error Matrix

| Condition | Required behavior |
|---|---|
| Dirty menu/back/forward/logout | Restore current location, confirm, keep values if cancelled |
| Dirty local cancel | Confirm and discard only the chosen form |
| Successful / failed save | Clear / retain relevant dirty state |
| Session expired | Clear forms through unmount, show login, no guard blocking expiry |
| Old account/page response | Ignore; do not restore obsolete items/actions |
| Page request failure | Visible error and retry; actions unavailable |
| Current offset beyond new total | Load last valid page |
| Unknown environment value | Visible “environment unconfigured” text |
| Missing metric days | Show coverage/missing count; never substitute zero |

## 5. Good / Base / Bad Cases

- Good: 45 drafts render pages of 20/20/5; switching accounts starts at page one.
- Base: zero records show an empty state with both page controls disabled.
- Bad: after entering two model keys, cancelling the first clears both. Use form-scoped discard.
- Bad: returning from a cancelled browser-back prompt appends a new history entry. Restore the
  indexed entry instead, preserving forward navigation.

## 6. Tests Required

Meaningful regressions live in `AdminApp.unsaved.test.tsx`, `environment.test.ts`, model/account
form tests, `WeChatPublishPage.pagination.test.tsx`, existing publication-safety tests, and stats tests.
Assert user-visible values, focus, history length/location, late-response isolation, last-page totals,
failed-save retention, scoped cancellation, forced expiry, and absence of credential persistence.
Run frontend lint/types/tests, generated API parity, both Vite entries, and real browser navigation /
reflow against isolated fixtures. Browser inspection must include expanded forms and long labels.

## 7. Wrong vs Correct

```tsx
// Wrong: local cancellation discards every dirty form on the page.
requestNavigation(closeProviderEditor);

// Correct: this form owns its own discard request.
const { requestDiscard } = useUnsavedChanges(key !== "", () => setKey(""));
requestDiscard(closeProviderEditor);
```

Build previews into a task-specific directory with an explicit API origin. Do not overwrite
`frontend/dist-admin` while another preview serves it, or retarget a production-connected preview
to mock data. See the release handoff for the particular backend prerequisite and artifact hash.

## History extension (2026-10-10)

`WeChatApi.jobsPage(accountId, offset, filters)` returns the generated publication-job list response;
the unfiltered `jobs(accountId)` array adapter remains available to draft/published views.
All three tabs now have 20-row pagination. Publication records additionally filter by status and
inclusive creation dates; render `business_timezone` returned by the API rather than assuming
the browser's timezone. Account/filter changes reset offset; invalid ranges do not trigger a
misleading successful empty state. Date/status changes and pagination use the unsaved-navigation
guard when a manual reconciliation has edits. Keep the whole filter context in request identity.

Audit initial loads, refreshes, filter changes, and append requests share a generation guard.
Invalidate synchronously before starting another view; ignore obsolete successes, errors and
finally handlers. A separate page-request identity prevents double loads and old finally blocks
releasing a new lock. Append failure preserves rows and exposes retry at the same cursor.
Current session expiry still logs out; an obsolete request cannot expire a newer view.

`wechat.publish_rechecked` describes the query outcome, never publication success or source
fetching. `wechat.publish_reconciled` displays the explicit published/not-published conclusion
and note. Guard unknown nested audit-detail values before rendering; future events must not
crash the table. Tests cover delayed success/error/expiry, refresh, A→B→A, retry, malformed
future details, and the exact two publication audit descriptions.

## Layout selection is saved configuration

The template API proves a saved account selection, not draft-worker liveness. Show “已保存” and a
save-success message; do not infer “正在使用” or “已生效” from that response. Explain that supported
automatic single drafts use the choice at first upload, retries retain the original choice and
existing drafts remain unchanged. Keep a concise note that the page does not check worker runtime
state. Remove a dated deployment warning only with the matching reviewed consumer upgrade; this
saved-state wording remains accurate when a worker disconnects or a release is rolled back.

Model-service release verification additionally binds heartbeats to the current container host
and process start. A green row from a different old host cannot prove a replacement connected.
