# Design

Keep the existing provider and native-observe policy. Extend the typed diagnostic
projection and distinguish deterministic/pre-dispatch failures from ambiguous
external effects. Reuse existing attempt safe_metadata rather than adding raw
response storage. Safe retry ownership must span intent/run claims; do not merely
enable HTTP retries on all POST errors or reset an unknown intent.

Implement in the clean production-shaped release-hardening worktree. Preserve
deployed integration bytes via the existing immutable source-overlay release.
No schema migration unless inspection proves it unavoidable; prefer existing
durable attempt/state mechanisms. Build from the exact running image and retain
rollback/config identities, current providers and permanent banners.

Today's recovery requires a read-only preflight of article, image, edition and
draft ownership/journal. Prefer verified provider-result reconciliation if a
usable task handle exists. Otherwise retain old unknown history and implement an
explicit compensated attempt/new identity with exact source linkage. Reuse accepted
text, deterministic rendering and any verified ready images. Deliver only through
the existing prepared-child validator and draft consumer; no direct publish call.

Technical recovery seam and safe retry predicate must be documented by code
inspection and independently reviewed before production mutation.

## Selected compensation seam

Keep the visual row as the current logical-slot projection and retain immutable
old unknown attempts plus a protected snapshot of the old visual/run/edition
state. An exact-target operator records a closed-schema workflow authorization in
existing article_attempts, then releases the original run and edition together.
The regular retry API still rejects unknown outcomes. A dedicated claim helper
consumes the authorization only for the designated successor run attempt, appends
a durable consumed record, and returns a distinct provider_request_fingerprint.
The existing Comfly Idempotency-Key field carries this new physical operation;
logical plan, accepted article, audit and render fingerprints stay unchanged.
Safe non-applied retries after compensation retain that compensation key, never
fall back to the original unknown key. A later unknown does not get a second
automatic or operator compensation under the same authorization.

Claim seam: infrastructure/db/official_account_visual_compensation.py exposes
claim_authorized_visual_compensation(session, run, claimed, row, plan), returning
StrictGeneratedVisualClaim or None; the owning repository commits. Extend that
claim DTO with optional provider_request_fingerprint. Recovery also freezes and
audits the original cutoff and the bounded late-recovery cutoff authorized after
16:09. No default setting or schedule change is involved.

## Prospective retry and permissive-review design

Introduce a new immutable visual-pipeline identity for future editions instead of changing
the frozen V1 strict or V2 observe meanings. Give each body slot a bounded three-attempt
physical ledger. Each retry derives a distinct provider request fingerprint from the stable
logical plan plus attempt number; completed slots remain content-addressed and are reused.
The repository claim transition owns attempt increment, lease fencing and expiry checks so
process restart cannot reset the budget. Provider/output/unknown failures may advance to the
next attempt as explicitly authorized; invalid configuration/input, lost authority and expiry
do not.

Keep review execution and durable findings, but make quality verdicts advisory under the new
policy. Deterministic usable-raster, exact native geometry/count, byte/subject identity and
prepared-artifact integrity remain hard gates. Model rejection/unavailability, semantic/style
warnings, duplicate/reuse observations and weak composition no longer prevent readiness. The
new policy is selected prospectively by the edition/run identity and protected configuration;
old rows keep their literal V1/V2 replay behavior.
