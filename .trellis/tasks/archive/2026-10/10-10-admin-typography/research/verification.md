# Verification before frontend release

- Full frontend suite: 53 files / 376 tests PASS (final product tree).
- Implementer focused suite: 10 files / 76 tests PASS. Independent reviewer:
  navigation/unsaved/source suite 3 files / 20 tests PASS; lint, types, formatting PASS.
- Main and agent OpenAPI generated parity PASS; normal Vite entry and explicitly labeled
  demo/production admin builds PASS. No shared style, iframe generator, API or backend edits.
- Browser: 50 page/width cases across 320/390/768/1366/1440 pixels, plus source table
  901/1024 breakpoint checks. No page overflow or browser error. GET-only fixture harness
  recorded zero mutations/external calls; demo fixture failures are intentionally synthetic.
- Keyboard: native instruction disclosures, Escape/Tab, accepted and cancelled dirty navigation,
  role-filtered menu, current-page label and desktop/mobile focus transitions PASS.
- 200% text enlargement at 390 CSS pixels and long source names at 320 PASS. All four real
  template fixture HTML bodies remain byte-preserved inside sandboxed preview frames.
- Visual inspection found short desktop source values wrapping; reviewer fixed only short
  columns above the mobile-card breakpoint, then final build and browser checks passed.
- At 390px, model first card moved from approximately 481px to 415px; heading now 24px,
  desktop26px, with weight synthesis enabled inside the console only.
- Screenshots and full measurements: /tmp/edu-admin-typography/browser/. Script:
  rollout/check-browser.mjs. Live read-only check uses rollout/check-preview.mjs.

Production frontend baseline matches the previous release's exact three hashes. Snapshot
captures 16 container identities/images/start/restarts and config hashes (never raw secrets).
Frontend-only helper received independent static review; cutover remains gated by the source
predeploy gate and exact pre/post invariant comparisons.
