# Native Official Account image failure and compensation

## 1. Scope / trigger

This contract covers native strict/observe Article image generation. It fixes the
September 16 failure where every generator exception became result_unknown and
lost its diagnostic. Ordinary WeCom generation, image-quality policy, existing
article identities and subscriber publication permissions remain unchanged.

## 2. Signatures

- `ImageGenerationFailure` owns a closed `strict-image-failure-v1` projection:
  error_code, disposition, reason, http_status and response_kind.
- `classify_image_generation_failure(...)` does not infer non-application from
  a generic retryable flag. `StrictImageGenerationError` carries the projection.
- `fail_generated_visual(..., diagnostic=...)` persists the projection in
  image-attempt safe_metadata; the run boundary preserves it and logs it safely.
- `StrictGeneratedVisualClaim.provider_request_fingerprint` optionally overrides
  the physical provider operation key, never the logical plan/result fingerprint.
- `claim_authorized_visual_compensation(session, run, claimed, row, plan)` and
  `resolve_visual_provider_request_fingerprint(session, *, run_id, visual_id)`
  live in `infrastructure/db/official_account_visual_compensation.py`.
- That module's CLI defaults to plan; `--apply` performs the exact dated operation.
  It is an operator entrypoint, not an API, scheduler or ordinary retry route.

## 3. Contracts

The one-shot transport proves only a POST connection/pool failure before dispatch
or an explicit POST HTTP429 is non-applied and retryable. Read/write failures,
generic HTTP5xx, post-success polling/download failure and orphaned dispatches
remain unknown. Authentication, quota, deterministic rejection and invalid output
are terminal and keep their real safe classification instead of becoming unknown.
No inner retry loop may turn one durable image intent into multiple paid POSTs.
Classification must retain the operation stage: a later poll/download HTTP4xx,
including authentication and rate-limit responses, says nothing conclusive about
the already accepted POST. Such retrieval failures remain unknown and non-retryable;
an HTTP200 fetch whose actual raster bytes fail validation remains a terminal
output-integrity failure. Do not reuse a stage-blind error-class classifier here.

Failed-slot reclaim requires the matching previous persisted non-applied proof,
a later fenced run attempt, and the existing frozen max-attempt/cutoff policy.
Successful article, audit, render and images are reused. A failed row is not a
successful completed image. Unknown historical rows lack proof and stay stopped.
Cancellation remains cancellation; a lost lease cannot overwrite another result.

Error projections contain only allowlisted codes/reasons, an integer HTTP status,
and json/raster/other response kind. Reject unknown keys, versions and invalid
field types when decoding. Never record raw exceptions, causes, bodies, prompts,
image data, endpoints, tokens or signed URLs in this projection or ordinary logs.

Explicit compensation is separate from retry. Immutable workflow attempts use
stages `visual_compensation_authorized` and `visual_compensation_consumed` and
capability workflow. The current visual row is a logical-slot projection; before
it advances, preserve its original snapshot in the protected draft journal and
keep all original unknown attempt rows unchanged. The closed authorization binds
target edition/run/article/render/visual, original attempt/lease, preserved content,
original bundle, snapshot, successor attempt, account and recovery window.

Authorization requires exact unknown target state, no active lease, no prepared
article/receipt/draft claim or delivery intent, accepted content, compatible event
ownership and remaining attempts. Consume once under the repository's row locks;
verify content/bundle/original attempt bindings again before paid dispatch. A
stable new provider key identifies compensation. Later proven non-applied retries
retain that new key; they must never fall back to the original ambiguous key.
Success or another unknown does not authorize a second compensation.

The September 16 operator is user-authorized after the original 16:00 cutoff.
It records the original window and freezes one replacement window, at most two
hours from authorization and never beyond the same Shanghai date. Repeating apply
returns the original authorization without changing its deadline or replaying work.
Only this edition/run window changes; global M/W/F scheduling and other dates do not.
Production recovery still ends at an unpublished draft ACK, never public publishing.

## 4. Validation and error matrix

| Condition | Required result |
| --- | --- |
| Proven POST connect/pool failure or explicit429 | Safe diagnostic; bounded later run/slot retry |
| POST read/write timeout, HTTP5xx, orphan or post-success poll failure | Unknown; no automatic repeated generation |
| Accepted POST then poll/download HTTP4xx or invalid polling envelope | Unknown; preserve retrieval diagnostic without replay |
| Successfully fetched HTTP200 but invalid raster | Terminal output-integrity failure, not a transport ambiguity |
| Auth/quota/rejection/output integrity failure | Typed terminal failure; no false unknown or success |
| Old failed row without matching proof | No automatic reclaim |
| Completed earlier image | Reuse exact saved artifact, zero new POST for that slot |
| Cancelled task or stale lease | Do not swallow cancellation or overwrite state |
| Exact authorized late target | Reuse text/audit/render; consume one distinct physical image key |
| Tampered authorization/content/bundle/old attempt or wrong successor | Reject before provider call |
| Repeated apply, consumed unknown or expired recovery | No new authority, no deadline refresh, no blind replay |

## 5. Good / base / bad cases

Good: a POST429 is recorded as non-applied; a later eligible run claim retries
only the failed slot. Base: a legacy unknown remains unknown until explicitly
reconciled or authorized for one compensating operation. Bad: reset all unknown
rows, clone content with invented prompt versions, or repeat the old paid key.

## 6. Tests required

- `test_official_account_image_failure.py` in unit/integration: real transport,
  strict/observe executor, image/run/log diagnostic propagation and sentinel
  redaction; connect versus read/write/POST500/poll distinction; bounded/concurrent
  reclaim, no old unknown replay and retained article/ready images.
- `test_official_account_visual_compensation.py`: real isolated SQL authorization,
  one-time consumption, wrong/tampered target and expired-window refusal, unchanged
  old attempts/content, distinct provider key, idempotent apply and same-edition
  producer continuation. Paired unit tests cover closed metadata and dispatch keys.
- Code-only release tests protect original history/config/schema and validate the
  committed source overlay against the exact deployed base before quiescence.
  Offline success never substitutes for a real generated artifact or draft ACK.

## 7. Wrong vs correct

Wrong: catch every image exception, store unknown, then reset unknown to queued.

Correct: preserve the typed diagnostic; require persisted non-applied proof for
automatic retry. For this explicitly authorized ambiguous target, keep immutable
history, consume a dedicated compensation record and send a new physical key.
