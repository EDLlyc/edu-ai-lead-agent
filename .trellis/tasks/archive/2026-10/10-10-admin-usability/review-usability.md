# Independent usability review — 2026-10-10

Reviewed the current worktree against U1–U6, task design/implementation notes, the check context,
and the new frontend admin-console contract. No production or provider operations were performed.

## Findings fixed

### R1 — returning to an unresolved context reused actionable old drafts

- Files: `frontend/src/features/admin/wechat/usePublicationPage.ts`,
  `WeChatPublishPage.pagination.test.tsx`.
- Reproduction: load account A's drafts, switch to B while its request stays pending, then return
  to A while the new A request also stays pending. The previous snapshot still matched A's string
  key/API/revision, so the old draft and enabled publication actions reappeared. Switching
  drafts → pending published list → drafts had the same problem.
- Fix: bind each snapshot to the current visit's memoized request-context identity. A return to
  the same key is a new visit. A refresh within the same visit retains content but changes revision,
  keeping publication disabled until the fresh result arrives. Existing cancellation remains.
- Evidence: both delayed round-trip regressions failed before the fix because “立即发布” was still
  present. Both pass after the fix and verify that a newly occupied draft cannot be submitted.
  All 21 existing publication/pagination tests pass.

### R2 — edits made during a pending save could disappear on success

- Files: source editor, model key form, admin account forms, WeChat binding/edit forms, own-password
  form, and keyword notes; associated component tests.
- Reproduction by code path: save captures current inputs, further edits remain possible, then the
  successful response closes or resets the form. Those later inputs were never submitted.
- Fix coordinated with the guard implementer: disable the submitting form's inputs until success
  or failure; restore editing and retain the submitted values after rejection. Source preview and
  model connection-test behavior remain distinct from saving. Keyword lists already disabled
  their controls; the notes field now follows the same rule.
- Evidence: implementer's six affected suites pass (40 tests), including delayed saves and a
  password rejection that retains values, restores editing, and keeps beforeunload protection.
  Reviewer inspected the final changes and independently reran admin lint and TypeScript.

## Contract review

- U1/U5: source/job card opt-in retains labelled cells and headers; comparison tables have named,
  focusable scrolling regions. Shell, selectors, long text, forms, and status badges use bounded
  sizing and visible focus. Page overflow is not hidden. Root owns final built-browser reflow and
  expanded-form screenshots at 390/768/1366 px.
- U2: in-memory dirty registrations include keyword text before adding, changes to saved lists,
  notes and credential/account/source forms. Local cancellation is form-scoped; global navigation
  confirms all affected edits. Session expiry clears registration and unmounts the form. History
  restoration uses existing indexed entries rather than pushState sentinels. Tests check focus,
  Escape/stay/discard, history length/location, logout, failure/success and expiry. No draft or
  secret persistence was introduced.
- U3: page/account/tab isolation, last-page shrinking, retry, totals, polling cleanup, open-job
  occupancy, changed-content invalidation, all-title confirmation and single-submit ref reviewed.
  R1 closes rapid round-trip reuse. Reconciliation retains its expected_updated_at contract.
- U4: large numbers and coverage are separate; real zero and entirely missing data remain distinct.
  Existing calendar-day and coverage helpers retain their semantics.
- U6: only explicit demo/production strings are accepted; everything else is unknown. The badge is
  rendered before session state, including login, and does not infer origin or authorize writes.
- Spec sync: root updated `frontend/admin-console.md` to describe round-trip request identity,
  frozen submitting inputs, and the actual division of polling between hook and page.

## Verification

- Admin-wide ESLint: PASS (`npx eslint src/features/admin`).
- Full frontend TypeScript: PASS (`npm run typecheck`).
- Publication and pagination: 21/21 PASS, including two initially failing R1 regressions.
- Unsaved shell/history, statistics/calendar gaps and environment labels: 25/25 PASS.
- Changed hook/test formatting: PASS.
- Guard implementer after coordinated R2: six suites / 40 tests PASS; final code inspected.
- Root retains ownership of full frontend gate, generated contract parity, both entry builds,
  and real-browser acceptance. Those release-level checks were not duplicated here.

## Findings not fixed

None remaining in the reviewed implementation. This report is code/component review evidence;
the task's browser and isolated-preview acceptance remains a separate root-owned gate.
