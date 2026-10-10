# Design

- Add an admin-only wrapper and semantic type/spacing/color tokens in Admin.module.css. Override
  inherited font-synthesis:none within that wrapper to permit weight synthesis where a Chinese
  bold face is missing. Use installed system fonts; no external font fetch, package or shared
  Application.module.css/global token edit. Keep the existing light background and teal accent.
- Implement a small admin navigation component or focused shell change: a mobile disclosure
  button with current group/page, aria-expanded/aria-controls, grouped links and CSS responsive
  visibility. Desktop sidebar persists. Keep the existing useAdminHistory/unsaved guard as the
  navigation authority. Collapse only on approved route changes (or explicit close), support
  Escape and sensible focus restoration, and handle viewport resize without orphaned focus.
- Change only explanatory copy/disclosure markup in model/template pages, and class hooks for
  action/numeric treatment as needed. Preserve all API calls, providers, status calculations,
  confirmation semantics, pending/error UI, dirty form registration and sensitive state handling.
- Consolidate vertical rhythm in cards/forms/tables; avoid large decorative surfaces and animation.
  Separate secondary/revert/delete actions visually while retaining touch targets and focus rings.
- Tests target menu interaction/dirty cancellation and help discovery; do not add CSS-value or
  snapshot-only tests. Real Playwright inspection supplies visual, responsive and keyboard proof.
- Release is frontend-only. Build distinct demo/production artifacts in a task-specific temp path.
  Keep the existing old previews serving until checks pass. Verify live asset baseline, save exact
  prior frontend and atomically exchange /var/www/edu-ai-admin; preserve backend image/config/IDs.
  Refresh5180 via existing production SSH tunnel and5181 via existing fixture server. No authenticated
  production writes/provider requests. Revert by exchanging the previous frontend back.
