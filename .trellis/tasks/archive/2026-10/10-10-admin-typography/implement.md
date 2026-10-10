# Execution and checks

1. Implementer owns admin product files and focused tests; root owns task/spec/browser/release work.
2. Complete scoped typography, responsive navigation, explanatory disclosure and spacing/actions.
3. Run focused navigation/unsaved/model/layout tests; then full frontend lint, typecheck, tests,
   generated main/agent API parity and both normal/admin builds. Format touched files.
4. Independent checker reviews requirements, accessibility, dirty/history guards and scope. Root
   uses browser fixtures for390/768/1366/320 widths, focus/Escape/resize and long-label reflow;
   preserve real production read-only boundaries. Inspect screenshots visually.
5. Record source commit and separate environment-labeled builds. Apply the production-mainline
   source gate for a release, then verify old assets and backend invariants before a frontend-only
   atomic asset exchange. Refresh stable previews, check login/reload/assets401/404 and demo pages.
6. Update frontend spec and release record, commit, archive and journal; fast-forward mainline.

The prior user-facing five-point planning summary is approved by this turn. The artifacts formalize
that same scope without adding product decisions. No unresolved question blocks implementation.
