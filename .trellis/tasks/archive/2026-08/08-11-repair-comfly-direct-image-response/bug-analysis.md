## Bug Analysis: Comfly Direct Raster Was Misclassified as Rejection

### 1. Root Cause Category

- **Category**: B - Cross-Layer Contract; D - Test Coverage Gap; E - Implicit Assumption.
- **Specific Cause**: The Comfly adapter assumed every successful creation response was a JSON
  envelope. The actual server diagnostic observed a non-JSON HTTP 200 response. The adapter parsed
  it as JSON, raised `ImageProviderRejectedError`, and the worker performed its normal retry and
  catalog fallback despite the model request succeeding.

### 2. Why Fixes Failed

1. **Existing neutralized retry**: It simplified prompt content but retained the JSON-only response
   parser, so it could not recover a direct raster response.
2. **Existing unit suite**: It covered JSON URL, Base64, and task forms, but not a direct creation
   response, allowing the incorrect assumption to remain green locally.

### 3. Prevention Mechanisms

| Priority | Mechanism | Specific Action | Status |
| --- | --- | --- | --- |
| P0 | Runtime contract | Dispatch allowed direct raster content types before JSON decoding and validate signature, size, and dimensions. | Done |
| P0 | Regression tests | Cover direct PNG, JPEG, `VP8` WebP, `VP8L` WebP, invalid raster, oversized raster, and non-raster non-JSON bodies. | Done |
| P1 | Observability | Carry only allowlisted HTTP status and response kind into the existing rejection event. | Done |
| P1 | Documentation | Add the executable adapter contract to backend error handling and a provider-representation question to the cross-layer guide. | Done |

### 4. Systematic Expansion

- **Similar Issues**: The ToAPIs adapter intentionally owns a JSON-only contract and is covered by
  separate tests; it must not be generalized without provider evidence. Future image adapters must
  enumerate their successful representations explicitly.
- **Design Improvement**: Keep provider transport decoding inside the adapter, then return the typed
  `ImageGenerationResult` only after common raster validation. Worker fallback must act only on a
  typed rejection, never on a parser assumption.
- **Process Improvement**: Every new external provider success path requires a `MockTransport`
  test for each documented representation, including direct media responses.

### 5. Knowledge Capture

- [x] Updated `.trellis/spec/backend/error-handling.md`.
- [x] Updated `.trellis/spec/guides/cross-layer-thinking-guide.md`.
- [x] Added direct-raster and safe-diagnostic unit regressions.
