# Bug Analysis: Current Comfly calls return non-image JSON with HTTP 200

## 1. Root Cause Category

- **Category**: B - Cross-Layer Contract; D - Test Coverage Gap.
- **Specific Cause**: The configured Comfly endpoint completed multiple live requests with HTTP 200
  and JSON but no image URL, Base64 value, or supported task representation. The same outcome
  occurred with content-driven references, one configured reference, and no reference. The adapter
  therefore received a provider-level unusable result, not a local image-validation failure.

## 2. Why Fixes Failed

1. **Direct-raster compatibility**: The previous fix correctly supports valid direct PNG/JPEG/WebP
   responses, but the live response was JSON rather than raster.
2. **Request representation experiments**: Earlier live probes did not establish a useful provider
   response. The current operator decision is to follow the published Comfly contract explicitly:
   omit undocumented `aspect_ratio`, request `b64_json`, and support the documented nested task
   result envelope.
3. **Initial smoke output**: It printed only a generic typed code, and the execution harness did
   not retain it. A bounded smoke summary and JSON-envelope metadata were needed to classify the
   failure without exposing provider content.

## 3. Prevention Mechanisms

| Priority | Mechanism | Specific Action | Status |
| --- | --- | --- | --- |
| P0 | Runtime diagnostics | Carry only HTTP status and response kind for rejected creation JSON envelopes. | Done |
| P0 | Operator visibility | Print only allowlisted typed image failure fields in the live smoke command. | Done |
| P1 | Regression coverage | Cover malformed JSON envelopes and smoke-summary redaction. | Done |
| P1 | Protocol compatibility | Use documented creation fields and decode `data.data.data[]` task results. | Done |
| P1 | Operations | Treat HTTP 200 as transport success only; require a valid image representation before accepting provider health. | Done |

## 4. Systematic Expansion

- **Similar Issues**: Other provider adapters must not equate 2xx transport status with a successful
  model result; their success representation must be parsed and validated explicitly.
- **Design Improvement**: Keep provider-body parsing inside the adapter and project only stable,
  content-free diagnostics across the application boundary.
- **Process Improvement**: A live provider probe must exercise at least one no-reference request
  before attributing a failure to private asset selection or prompting.

## 5. Knowledge Capture

- [x] Added the JSON-envelope diagnostic contract to the backend error-handling specification.
- [x] Added smoke-summary and malformed-envelope tests.
- [x] Recorded that the current provider result is operationally blocked, rather than guessing a
  replacement model or retaining unverified request-parameter changes.

## 6. Live Verification Update

- The fresh content-driven call on 2026-08-11 returned the same bounded finding: HTTP `200` with
  normalized response kind `json`, but no supported image or task representation.
- The smoke command created no output file and emitted no provider body, prompt, temporary URL, or
  credential.
- This is a provider-result contract failure after transport success. It is not an image-dimension,
  private-reference, database, or Enterprise WeChat failure.
