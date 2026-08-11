# Bug Analysis: Comfly image responses use empty alternate placeholders

## 1. Root Cause Category

- **Category**: B - Cross-Layer Contract; D - Test Coverage Gap.
- **Specific Cause**: The configured Comfly endpoint returns HTTP 200 JSON whose `data[0]` contains
  both `url` and `b64_json` keys; one representation is populated and the alternate is an empty
  string. The adapter previously treated the simultaneous key presence as ambiguous, even when one
  value was empty, and raised `image_provider_rejected` before downloading or decoding the image.

## 2. Why Fixes Failed

1. **Direct-raster compatibility**: The adapter already supported valid direct PNG/JPEG/WebP
   responses, but the provider normally returns a JSON envelope containing the image URL.
2. **Request representation experiments**: The live request matched the published fields (`model`,
   `prompt`, `size`, `response_format`, and optional `image`). The failure was in interpreting the
   documented response shape, not in private-reference selection or prompt format.
3. **Initial parser assumption**: The parser used `None` presence checks rather than non-empty
   representation checks, so a valid `url` plus empty `b64_json` was rejected before download.

## 3. Prevention Mechanisms

| Priority | Mechanism | Specific Action | Status |
| --- | --- | --- | --- |
| P0 | Runtime diagnostics | Carry only HTTP status and response kind for rejected creation JSON envelopes. | Done |
| P0 | Operator visibility | Print only allowlisted typed image failure fields in the live smoke command. | Done |
| P1 | Regression coverage | Cover malformed JSON envelopes and smoke-summary redaction. | Done |
| P1 | Protocol compatibility | Use documented creation fields and decode `data.data.data[]` task results. | Done |
| P0 | Response compatibility | Accept exactly one non-empty URL/Base64 representation when the provider includes an empty alternate placeholder. | Done |
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
- [x] Recorded that the original failure was a local response-parser incompatibility, rather than
  guessing a replacement model or retaining unverified request-parameter changes.

## 6. Live Verification Update

- The structural diagnostic confirmed the live envelope had `created`, `data`, `model`, and `usage`;
  its single `data` item had `url`, `b64_json`, and `revised_prompt`. The empty alternate
  representation exposed the local parser incompatibility.
- After the parser repair, a fresh no-reference live request saved a valid 1024x1024 PNG under
  `output/imagegen/live-comfly-no-reference-20260811-v2.png` without database or Enterprise WeChat
  side effects. The provider request contract and image output validation both passed.
- A second fresh content-driven request also saved a valid 1024x1024 PNG under
  `output/imagegen/live-comfly-content-driven-20260811-v1.png`, confirming the private brand
  reference selection and injection path remains compatible with the same response envelope.
