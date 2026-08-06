# Direct Enterprise WeChat delivery design

## Boundaries

The change stays in the backend delivery service and configuration. Material-package generation
continues to persist a versioned package with copy validation/audit snapshots and an immutable
image descriptor. The API only creates a durable `wecom_delivery_jobs` row. The dispatcher remains
the sole component allowed to call Enterprise WeChat.

## Eligibility contract

Introduce one service-level eligibility decision used by both explicit enqueue and automatic
reconciliation:

- Review-required mode (`WECOM_REQUIRE_REVIEW_BEFORE_SEND=true`): preserve the current
  `completed + approved` requirement.
- Direct mode (`false`): accept `awaiting_manual_use` or `completed`, reject `rejected`, and do
  not require a `MaterialReviewModel` row.
- Both modes reject failed/incomplete package states and require a non-rejected package review
  status.
- Direct mode additionally verifies the persisted copy quality snapshots. The image artifact is
  checked for success and quality before the job is created; the dispatcher repeats immutable
  image byte, size, checksum, and media-signature checks immediately before upload.

This keeps the manual decision optional while retaining deterministic and provider-independent
quality gates. A review rejection remains an explicit veto even when future packages do not need
review.

## Automatic reconciliation

The dispatcher queries a bounded set of candidate packages according to the same mode policy:

- strict mode: `status=completed` and `review_status=approved`;
- direct mode: `status IN (awaiting_manual_use, completed)` and `review_status != rejected`.

The enqueue service is still the final authority, so stale or malformed candidates are skipped
with a safe error code. The existing request fingerprint prevents duplicate jobs when the poller
sees a package on multiple cycles or multiple workers race.

## Configuration and rollout

Keep credential-free defaults in `.env.example`. Change only the local deployment `.env` to enable
automatic direct delivery after tests:

```text
WECOM_AUTO_DELIVERY_ENABLED=true
WECOM_REQUIRE_REVIEW_BEFORE_SEND=false
```

The dispatcher is restarted after the backend image is rebuilt so its settings and service code
are loaded together. Rollback is a configuration-only change back to `false` / `true`, followed by
a dispatcher restart; already-created jobs retain their durable state and are not silently
deleted.

## Compatibility

No database migration is needed. Existing job/status constraints, request fingerprints, leases,
attempt rows, retry classification, and API response shapes remain unchanged. Existing explicit
formal delivery behavior remains strict when the review setting is true.

The package API may continue to expose `awaiting_manual_use` and `review_status=pending` in direct
mode because those fields describe the package lifecycle and optional review record separately
from the delivery policy. Delivery status is observed through the existing WeCom delivery API.

## Failure behavior

Quality failures are local conflicts and create no job. Provider transient errors retain existing
bounded retry behavior; timeouts remain `delivery_unknown` and are not auto-resubmitted. Provider
success is persisted child-by-child, preserving text-before-image ordering and avoiding duplicate
text on image-only retries.
