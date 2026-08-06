# Enable direct Enterprise WeChat delivery after package completion

## Goal

When a material package has finished deterministic copy validation, copy audit, and image
generation validation, the system must be able to send the package directly to the configured
internal Enterprise WeChat sales recipient without a separate manual review decision.

This is an internal one-recipient delivery workflow. It does not publish to Moments or any other
social platform.

## Confirmed current behavior

- `WECOM_AUTO_DELIVERY_ENABLED` is currently disabled in the local `.env`.
- `WECOM_REQUIRE_REVIEW_BEFORE_SEND` is currently enabled.
- A generated package is stored as `status=awaiting_manual_use`, `review_status=pending` even when
  copy validation passed, copy audit was accepted, and image validation passed.
- `enqueue_wecom_delivery` currently accepts only `status=completed` and requires approval for a
  formal message.
- Automatic reconciliation currently selects only `completed + approved` packages.
- Delivery is already durable and idempotent: the API enqueues a job and the independent
  dispatcher performs provider calls, with text-before-image ordering, leases, bounded retries,
  and safe error projection.

## Requirements

1. Add a direct-delivery policy path controlled by the existing
   `WECOM_REQUIRE_REVIEW_BEFORE_SEND=false` setting. In that path, a package in
   `awaiting_manual_use` or `completed` may be enqueued without a manual review record.
2. Never send a package explicitly marked `review_status=rejected`, or a package in a failed,
   queued, or otherwise incomplete state.
3. Direct delivery must still require `validation_snapshot.passed=true` and
   `audit_snapshot.accepted=true` for the copy. When an image is requested, it must be succeeded,
   have valid persisted metadata, and have passed image byte/format validation; if image quality
   audit is configured, it must also be accepted.
4. Automatic reconciliation must use the same eligibility policy as explicit enqueueing. It must
   discover newly completed `awaiting_manual_use` packages and remain idempotent across polling
   cycles.
5. Preserve the existing Enterprise WeChat boundary: only the dispatcher performs provider calls;
   no secret, raw userid, access token, media ID, provider body, or private object location is
   exposed or persisted.
6. Preserve delivery behavior after enqueueing: stable request fingerprints, text-before-image
   ordering, lease recovery, bounded retry for classified transient errors, and terminal unknown
   handling.
7. Configure the local deployment for the requested behavior after implementation:
   `WECOM_AUTO_DELIVERY_ENABLED=true` and `WECOM_REQUIRE_REVIEW_BEFORE_SEND=false`. Keep
   `.env.example` credential-free and safe by default.

## Acceptance Criteria

- [ ] With direct mode enabled, the current package `77d866b0-0337-4755-bae4-9e236edf5b15`
  can be enqueued from its existing `awaiting_manual_use + pending` state without a review API
  call, because its copy validation/audit and image validation pass.
- [ ] With direct mode enabled, automatic reconciliation finds the same eligible package and
  creates exactly one durable formal delivery job for the configured default recipient.
- [ ] With review-required mode enabled, the existing `completed + approved` contract remains
  unchanged and an unapproved package is rejected before any job is created.
- [ ] A package with failed copy validation, rejected copy audit, rejected review, failed image,
  invalid image metadata, or failed configured image audit is rejected before provider calls.
- [ ] Repeated reconciliation and repeated explicit enqueue return/reuse one job for the same
  package/version/recipient/mode/content fingerprint.
- [ ] Focused unit tests cover direct eligibility, strict-mode compatibility, auto-reconciliation
  filtering, quality vetoes, and idempotency; the backend quality gate passes.
- [ ] After restart with the local direct-delivery configuration, dispatcher logs show the direct
  policy and the delivery job reaches a truthful `delivered`, `partial`, `failed`, or
  `delivery_unknown` state. No result is represented as successful before the provider confirms it.

## Out of Scope

- Moments or social-platform publishing.
- Multiple recipients, recipient selection UI, or group delivery.
- Removing image security checks, SSRF protections, HTTPS restrictions, or provider response
  validation.
- Changing database schema or manually editing package/job rows to bypass application rules.
