# Bug Analysis: final bundle lagged current code and projection contract

## 1. Root Cause Category

- **Category**: C/D — Change Propagation Failure plus Test Coverage Gap
- **Specific cause**: semantic-selection and Markdown-projection code changed after an otherwise
  valid local export. Focused tests proved the functions, while no gate proved that the named
  delivery was rebuilt from the current code or that source/credit/rights/placement survived every
  projection.
- **Evidence and confidence**: the first delivery still contained `提醒我们` after the current unit
  test forbade it, and the next delivery's Markdown lacked fields present in JSON/API/UI. Direct byte
  inspection and current-code rebuilds make this diagnosis greater than 95% confidence.

## 2. Why Fixes Failed

1. **Function-level semantic fix**: corrected selection but did not invalidate or rebuild the named
   delivery, so the exported bytes remained stale.
2. **Structured projection coverage**: JSON, manifest, API and UI retained context provenance, but
   Markdown was treated as presentation rather than another governed projection.
3. **Independent validity checks**: Playwright and gzh verified the exact bytes they received, but
   could not prove that those bytes came from the latest implementation.

## 3. Prevention Mechanisms

| Priority | Mechanism | Specific action | Status |
|---|---|---|---|
| P0 | Test coverage | Rebuild from current code with the accepted sidecar and hash-match the named ZIP | DONE |
| P0 | Cross-layer contract | Assert source URL, credit, rights and placement across Markdown/JSON/manifest/API/UI | DONE |
| P1 | Process | Generate a fresh non-overwriting final directory after the last byte-affecting change | DONE |
| P1 | Documentation | Record final-delivery parity in the focused backend spec and cross-layer guide | DONE |

## 4. Systematic Expansion

- **Similar issues**: HTML/preview, manifest/archive, generated OpenAPI/TypeScript and browser
  sidecars can each be valid alone while describing different revisions.
- **Design improvement**: keep one typed provenance/placement projection and derive every artifact
  representation from it.
- **Process improvement**: distinguish staging/reviewed directories from the single named final
  delivery and validate only the latter in the final report.

## 5. Knowledge Capture

- [x] Added a focused seven-section backend V2 code-spec.
- [x] Added final-delivery rebuild and projection-parity requirements to backend/frontend specs.
- [x] Added the reusable checklist to `cross-layer-thinking-guide.md`.
- [x] Added regressions for generic emphasis, exact mobile observations and Markdown provenance.
- [x] Template sync is not applicable: this repository has no `src/templates/markdown/spec/` tree.
- [ ] Commit intentionally omitted because the user explicitly required no commit.
