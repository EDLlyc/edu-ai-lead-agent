# Source checks before release

- Template implementation: 128 backend cases PASS, 6 existing asset-dependent skips; 3 page tests PASS.
- Independent actual legacy-module ACK replay: both body-media and no-media cases reconcile after expiry with no retry writes; old journal JSON bytes unchanged.
- Full frontend 52 files / 371 tests PASS; full ESLint/TypeScript and main/agent API generated parity PASS.
- Real PostgreSQL admin/template + model integration: 36 cases PASS in isolated fixture databases.
- Scoped backend Ruff/format/Mypy PASS; full final source gate follows on the exact source commit.
- Built demo/production admin bundles PASS; browser 390/768/1366 checks cover all four renderer previews, truthful saved selection and no overflow/errors. Three saves are locally intercepted; no real mutation.
- Browser harness initially expected raw HTML srcdoc, but application intentionally wraps it as a complete document. Corrected the harness to compare contained renderer HTML; app unchanged.
- Model lifecycle/config focused checks: 51 PASS; final actual candidate-image offline smoke is still required.

- Final source gate: `predeploy gate PASS @ f062b82+dirty: 10 passed, 0 failed, 1 skipped (2026-10-10T06:19:43+00:00)`. The only dirty entry was an untracked `frontend/node_modules` tooling symlink; all tracked application, test and build-helper files matched committed f062b8221c387ecd44d6e7529832f50331d1508d. Unit/contract stage reported zero known/new failures; private visual-asset authoring is the one existing skip.
- Actual candidate image `6226855a` offline smoke PASS: complete364file manifest,12overlays,fourimports,legacydefault/configcrypto/templatefixtures,zero provider calls.
- First live attempt detected pre-existing two-version environment drift and was restored exactly; see runtime-drift-analysis.md. Release helper-only follow-up adds earlier admission; application/image payload remain exactly at the gated source commit.
