# IP 图片翻页相册 MVP — Implementation Plan

## Ordered checklist

1. Add `react-pageflip@2.0.3` with the existing frontend npm lockfile workflow; inspect the resulting
   dependency diff and license/audit output.
2. Add the typed in-memory draft owner, validation/projection helpers, Strict Mode-safe read/clear
   lifecycle, navigation helper, and pure tests. Keep constants and the ordered selection contract
   in one feature-owned module.
3. Refactor the gallery's selected collection to one ordered asset structure. Preserve checkbox,
   clear, count, and ZIP behavior; add the bounded “制作翻页相册” action and persistent accessible
   feedback for invalid counts or draft projection failures.
4. Extend `pathResolver`, demo return-target safety, and `Application` with the lazily loaded
   standalone flipbook route, route title/loading state, and missing-draft recovery.
5. Build the project-native `IpAssetFlipbookPage`, focused renderer, leaf contract, and scoped visual
   design. Add title editing, immutable reorder/removal, cover labeling, safe preview resolution,
   page status, input locking, keyboard/touch controls, responsive layout, image failure state, and
   reduced motion.
6. Expand unit/component/application tests for selection regression, draft lifecycle, route/login
   safety, renderer parity, accessibility, and empty/error behavior.
7. Run focused tests while iterating, then complete the full validation gates and live browser/data
   mutation smoke below.

## Expected files and risks

- `frontend/package.json`, `frontend/package-lock.json`: one new MIT runtime dependency; reject
  unrelated lockfile churn.
- `frontend/src/app/pathResolver.ts`, `Application.tsx`, and tests: exact route/login composition;
  a missed allowlist branch can break login restoration or expose the page in the shared console.
- `frontend/src/features/ip-assets/IpAssetHub.tsx` and module CSS/tests: preserve ZIP and existing
  selection semantics while adding ordered asset projection.
- New feature-local draft/page/renderer/CSS/test files: avoid external unlicensed source copying,
  global CSS collisions, unsafe URLs, and animation-only feedback.
- The worktree contains unrelated concurrent changes. Stage, test, and commit only files owned by
  this task; do not rewrite or revert parallel work.

## Validation commands

```bash
npm --prefix frontend run format:check
npm --prefix frontend run lint
npm --prefix frontend run typecheck
npm --prefix frontend run test -- --run
npm --prefix frontend run build
npm --prefix frontend audit --omit=dev
git diff --check
```

Run focused Vitest files before the full suite. After static checks, start the existing local IP
stack/UI and run a real Playwright smoke with 2–3 existing ready shared assets. Capture before/after
counts for assets, generation jobs, downloads, favorites, and provider/worker claim logs; all must
remain unchanged by album construction and viewing.

## Review and rollback gates

- Stop if adding `react-pageflip` requires a React downgrade, package-manager switch, unreviewed
  transitive package, or copying the external skill source.
- Stop if an implementation needs a backend write/API/schema change; return to planning because
  that violates the approved ephemeral MVP.
- Roll back only task-owned route/action/component/dependency changes. No database or object-store
  rollback should exist.
