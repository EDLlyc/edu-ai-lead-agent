# Bug Analysis: Current-news advisory preflight rejected eligible packages

### 1. Root Cause Category

- **Category:** E — implicit assumption, exposed as a cross-layer contract and test-coverage gap.
- **Specific cause:** the frozen-copy reader treated every historical draft in an accepted run as accepted, compared an evidence-binding ID list by order rather than set identity, and assumed the first eligible fact/title fragment would fit. Real package history and copy snapshots do not guarantee any of those properties. This made four of five fresh-news preflights fail before the v12 correction, despite an accepted active draft.

### 2. Why Fixes Failed

1. Earlier single-draft, short-fact synthetic fixtures omitted rejected predecessors and overlong first facts, so focused unit success overstated daily coverage.
2. Changing only the title fallback would not have addressed historical-draft and binding-order mismatches. The correction had to preserve the exact active accepted draft and same-package evidence while changing all three assumptions together.

### 3. Prevention Mechanisms

| Priority | Mechanism | Specific action | Status |
| --- | --- | --- | --- |
| P0 | Architecture | Select the exact accepted active draft; require package prose equality; compare unique binding-ID sets while rejecting changed or duplicate IDs. | DONE |
| P0 | Test coverage | Add rejected-v1/accepted-v2, reordered/changed/duplicate binding, and long-first-fact same-package fallback regressions. | DONE |
| P0 | Runtime gate | Run provider-free preflight against several current accepted packages before consuming any model/image intent. | DONE for five 2026-09-26 packages |
| P1 | Release review | Keep three distinct final-image and fixed-recipient receipts separate from input-preflight success. | TODO; release remains off |

### 4. Systematic Expansion

- **Similar issues:** any selector that scans whole draft history instead of dereferencing an active pointer, or compares semantically unordered evidence IDs as ordered arrays.
- **Design improvement:** carry typed active-draft and canonical binding-set identities across package, copy and poster boundaries; never repair a mismatch with unrelated news text.
- **Process improvement:** pair synthetic cases with frozen, accepted same-day package snapshots before paid calls. A green no-provider preflight is necessary but not image quality or send authorization.

### 5. Knowledge Capture

- [x] Updated `.trellis/spec/backend/daily-news-infographic-local.md` with the active-pointer and production-shaped regression contract.
- [x] Added the related unit and integration regressions in the v12 candidate.
- [ ] Obtain three distinct v12 exact-JPEG reviews and fixed-group receipt before any enablement.

There is no `src/templates/markdown/spec/` directory in this repository checkout, so no template mirror exists to synchronize. The independent check passed the selection regressions; the later cod image request yielded an unknown/quality-failed result without pixels and is not evidence of image-provider root cause.
