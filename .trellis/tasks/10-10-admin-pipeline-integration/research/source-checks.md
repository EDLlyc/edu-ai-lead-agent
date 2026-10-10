# Source checks before release

- Template implementation: 128 backend cases PASS, 6 existing asset-dependent skips; 3 page tests PASS.
- Independent actual legacy-module ACK replay: both body-media and no-media cases reconcile after expiry with no retry writes; old journal JSON bytes unchanged.
- Full frontend 52 files / 371 tests PASS; full ESLint/TypeScript and main/agent API generated parity PASS.
- Real PostgreSQL admin/template + model integration: 36 cases PASS in isolated fixture databases.
- Scoped backend Ruff/format/Mypy PASS; full final source gate follows on the exact source commit.
- Built demo/production admin bundles PASS; browser 390/768/1366 checks cover all four renderer previews, truthful saved selection and no overflow/errors. Three saves are locally intercepted; no real mutation.
- Browser harness initially expected raw HTML srcdoc, but application intentionally wraps it as a complete document. Corrected the harness to compare contained renderer HTML; app unchanged.
- Model lifecycle/config focused checks: 51 PASS; final actual candidate-image offline smoke is still required.
