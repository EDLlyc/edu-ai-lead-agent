# Frontend Quality Guidelines

## Contract status

These are the implemented gates for the React + TypeScript + Vite frontend. Local package scripts,
generated-contract checks, brand-workspace and material-package mapper/component tests, and
production build are active. A controlled full browser flow remains a follow-up.

## Required gates

The implemented toolchain is declared in
[`frontend/package.json`](../../../frontend/package.json): ESLint with type-aware TypeScript and
React Hooks rules, Prettier, strict project-reference `tsc`, Vitest 4, React Testing Library,
`jest-axe`, and Playwright. `make frontend-check` runs formatting, lint, type checking, component
tests, OpenAPI contract drift checking, and a production Vite build. Playwright is installed for
the later product flow; browser
binaries and product E2E tests are intentionally deferred until that flow exists. Equivalent tools
are acceptable only if the same behaviors are enforced and the change is documented.

The current brand-workspace regression suite is
[`frontend/src/app/App.test.tsx`](../../../frontend/src/app/App.test.tsx). It asserts the
brand/evidence boundary, durable upload-job feedback, absence of publishing controls, and no
automatically detectable accessibility violations. The material-package regression suite is
[`frontend/src/features/material/MaterialPackagePanel.test.tsx`](../../../frontend/src/features/material/MaterialPackagePanel.test.tsx)
and [`api.test.ts`](../../../frontend/src/features/material/api.test.ts); it asserts typed mapping,
queued/failed states, copy/download actions, evidence and audit display, and absence of publishing
controls.

The material detail's local-only visual-variation panel consumes the generated optional
`image.diversity` contract. Mapper/component tests must cover absent historical data, primary and
alternate plans, one-retry state, and the non-blocking `near_duplicate_after_retry` warning. The
view may display controlled labels/counts/decisions only; never add prompt, seed, perceptual hash,
nearest object identity, private reference path, or a publishing control.

CI must run, in a deterministic order where dependencies require it:

1. generate or verify the checked-in FastAPI OpenAPI document;
2. generate frontend API types and fail if the working tree differs;
3. formatting and lint checks;
4. strict TypeScript checking;
5. unit/component/accessibility tests;
6. production Vite build;
7. the critical end-to-end flow against controlled backend/provider fixtures.

## Test requirements

### Components

Test behavior through accessible roles, names, and visible text. Cover ready, loading, no-topic,
failed, and partial artifact states. Verify source links, copy/download actions, meaningful image
alt text, keyboard operation, focus behavior, and live-region success/error feedback.

Do not assert internal hook state or snapshot entire pages as the primary test. Small snapshots may
support stable presentational fragments but cannot replace behavior assertions.

### Hooks and API mapping

Use controlled request handlers and a fresh QueryClient. Cover typed success/error mapping,
cancellation, polling termination, cache invalidation, and stale-response isolation. Test view-
model mappers as pure functions, including missing optional metadata and unknown safe enum values
when the API contract permits them.

### End-to-end critical flow

Maintain one reliable flow that opens a ready material package, verifies topic/copy/image/source
provenance, copies the text, downloads the image and JSON package, and confirms that no automatic
publishing action exists. Add a no-topic or terminal-failure flow so a bad day is not rendered as a
blank success.

## Accessibility review

Automated checks are necessary but insufficient. Manually verify keyboard-only use, visible focus,
heading/landmark structure, zoom/reflow, source-link clarity, copy status announcement, error
recovery, reduced motion, and non-color status cues. Contrast must meet WCAG AA for the applicable
content.

The material package is an internal tool, not an accessibility exemption.

## Performance and reliability

- Keep the initial bundle small; lazy-load route-level screens when they become substantial.
- Avoid polling after terminal run states and pause/recover sensibly across network loss.
- Revoke object URLs created for downloads/previews.
- Render long copy/source lists without blocking interactions; add virtualization only after
  measurement.
- Preserve a usable error boundary around route content and report a safe correlation ID.

## Security and privacy

- Render model/source content as text; do not use `dangerouslySetInnerHTML`.
- Validate external URLs and download metadata; do not construct executable URLs from raw content.
- Never put API keys, provider credentials, full prompts, or signed long-lived URLs in the bundle,
  logs, analytics, URL state, or browser storage.
- Avoid third-party analytics/clipboard/download services unless separately reviewed.
- Do not collect or display personal information about minors unless an explicit approved workflow
  requires it.
- Do not add automated social publishing or credential capture.

## Review checklist

- Does the component have a focused owner and use the feature's typed hook/client?
- Are server, local, and URL state kept in their correct owners?
- Are generated API types current and unmodified?
- Are loading, no-topic, failed, and ready states explicit?
- Are evidence links and audit/validation status inspectable?
- Are copy/download controls native, keyboard accessible, and announced?
- Is untrusted content rendered safely and are URLs/filenames validated?
- Do tests cover user-observable behavior and negative states?
- Does the UI preserve manual review and publishing only?
- If this is the first vertical slice, were the greenfield examples in these specs replaced with
  actual source/test references?

## Forbidden patterns

- Shipping with TypeScript or hooks-lint errors suppressed globally.
- `any`, double assertions, or hand-written API response duplicates.
- Fetching in render/effects when a feature query hook should own server state.
- Clickable non-semantic elements, hidden focus, color-only status, or toast-only feedback.
- Snapshot-only coverage for the material-package workflow.
- A frontend control that implies the system published content automatically.
