# Harden image generation output handling

## Goal

Make the automated image stage reliably turn a successful provider response into a validated
image artifact and completed material package, without weakening file, size, checksum, or SSRF
protections.

## Confirmed Facts

- The business-date `2026-08-06` copy run `4106296d-b5c4-4540-9676-05dde2ef9dfb` was accepted
  after deterministic validation and audit.
- Its Comfly `gpt-image-2` image artifact reached `review_required` with
  `image_output_invalid`, and the material package therefore failed.
- Worker logs show an HTTP 200 response from the image generation endpoint followed by an HTTP
  200 download from the provider CDN; the fault is in the output-handling path after a nominal
  provider response, not a missing API response.
- No Enterprise WeChat delivery job was created and no message was sent.

## Requirements

1. Identify the exact validation or normalization condition behind `image_output_invalid` using
   the stored failure and a reproducible provider-compatible response.
2. Correct provider response handling, download/normalization, and retry classification so valid
   PNG/JPEG output completes as a succeeded image artifact.
3. Allow any HTTPS output hostname whose DNS answers are all public, globally routable addresses;
   preserve private/loopback/link-local/metadata rejection, content signature checks, maximum byte
   limits, checksum verification, and immutable MinIO metadata requirements.
4. Keep invalid, ambiguous, or unsafe provider output out of material packages; store a bounded,
   actionable safe error code instead.
5. Add regression coverage for the observed response shape and error paths, then exercise a real
   image request after implementation.
6. Provide a controlled image-only retry operation for a failed/review-required material package;
   it must preserve the accepted copy version and existing image request identity.

## Key Decision

Provider image URLs may use any HTTPS hostname. The worker may download one only after DNS
validation confirms that every answer is public and globally routable. This removes manual CDN
allowlist maintenance while retaining the private-network and response-content boundaries.

## Acceptance Criteria

- [ ] The failure mechanism is documented with code/test evidence.
- [ ] A valid provider CDN image is normalized, validated, persisted to MinIO, and linked to a
      succeeded image artifact and completed material package.
- [ ] Invalid images and unsafe download targets remain rejected with no stored provider secret,
      signed URL, or raw provider response.
- [ ] Automatic retry happens only for explicitly retryable failures and preserves image request
      idempotency.
- [ ] Focused and full backend checks pass, and a real non-production image run completes.

## Out of Scope

- Changing the copywriting, daily topic-selection rules, or Enterprise WeChat delivery behavior.
- Disabling the image safety checks to make a failed response appear successful.
