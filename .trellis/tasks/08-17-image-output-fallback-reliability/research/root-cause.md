# Bug Analysis: Provider image representation failure suppressed delivery

## 1. Root Cause Category

- **Category**: B/E/D — Cross-Layer Contract, Implicit Assumption, and Test Coverage Gap
- **Specific cause**: the Comfly adapter explicitly requested `b64_json` and correctly rejected a
  non-empty value that was not strict Base64. The application layer then treated every
  `ImageOutputValidationError` as a terminal quality/security failure. It did not distinguish a
  provider representation-syntax fault from unsafe URLs, bad raster signatures, wrong dimensions,
  or oversized bytes, even though a durable one-use provider-output recovery and approved catalog
  fallback already existed. The accepted topic/copy therefore ended with a failed package and no
  WeCom job.

### Evidence and confidence

Initial hypotheses were: provider outage (35%), unsupported image bytes (35%), and integration
contract mismatch (30%). The stored typed evidence showed HTTP/provider work reached a non-empty
`b64_json`, strict Base64 decoding failed before media/dimension/storage, and no raw value was
retained. Seven-day history included successful artifacts from the same model. Current official
documentation uses URL output. These observations increase the integration/representation mismatch
hypothesis above 90%, but the exact malformed provider value remains unknowable by design.

## 2. Why Earlier Behavior Failed

1. **Request assumption**: the adapter comment and specification asserted Base64 was the documented
   default, while current provider documentation uses URL output.
2. **Incomplete scope**: strict decoding protected storage correctly, but the application recovery
   branch handled provider rejection and exhausted transient failures—not invalid representation.
3. **Test gap**: adapter tests proved malformed Base64 was rejected and material tests proved
   provider rejection could fall back, but no cross-layer test asked whether the exact safe parser
   reason should consume one recovery and then reach delivery-eligible catalog fallback.
4. **Missing discriminating cases**: there was no non-isomorphic matrix proving representation
   syntax may recover while unsafe URL, signature, size and dimension failures stay terminal.

## 3. Prevention Mechanisms

| Priority | Mechanism | Specific action | Status |
| --- | --- | --- | --- |
| P0 | Architecture | Request URL, retain closed compatibility parsing, and route only the allowlisted representation reason through one durable recovery | DONE |
| P0 | Test coverage | Prove first failure recovery, second failure catalog fallback, no third call, and unsafe-output terminal controls | DONE |
| P0 | Privacy | Preserve content-free safe reasons; assert sentinels never reach logs/snapshots/API | DONE |
| P1 | Documentation | Update provider, material-package, diversity, delivery, quality, and cross-layer contracts | DONE |
| P1 | Runtime evidence | Continue typed error/recovery/fallback counters without retaining raw provider content | DONE |
| P2 | Live acceptance | Optional separately authorized one-call provider smoke after deployment; never part of ordinary gates | DEFERRED |

## 4. Systematic Expansion

- **Similar issues**: OCR, copy, and other AI adapters can also return transport-success envelopes
  whose representation is invalid. Each adapter needs an explicit representation matrix and safe
  recovery classification rather than a generic retryable flag.
- **Design improvement**: business recovery belongs in the durable application state machine;
  parsing remains strict and content-free in the infrastructure adapter.
- **Process improvement**: provider contract changes require an official-doc check plus a
  proxy-positive/outcome-negative cross-layer test through the actual downstream eligibility query.
- **Knowledge gap**: “provider returned HTTP success” is not the business fact. The business fact is
  a validated stored artifact or an explicitly validated fallback that remains eligible for the
  intended delivery mode.

## 5. Knowledge Capture

- [x] Updated `.trellis/spec/guides/cross-layer-thinking-guide.md`.
- [x] Updated affected backend provider/pipeline/diversity/delivery/quality specs.
- [x] Added adapter, state-machine, safety, fallback and delivery-eligibility regressions.
- [x] Recorded incident evidence without raw provider response content.
- [ ] Commit together with the reviewed implementation after the final Trellis check.

The repository contains no `src/templates/markdown/spec/` mirror, so there is no generated spec
template to synchronize for this project-local guide change.
