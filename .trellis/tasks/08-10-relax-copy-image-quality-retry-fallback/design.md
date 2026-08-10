# Design: Relaxed Quality Gates with Bounded Recovery

## Boundaries

The change is limited to the copy-generation executor/domain policy and the material-package image worker. Existing provider adapters, source evidence storage, MinIO integrity checks, and Enterprise WeChat delivery remain the side-effect boundaries.

The system distinguishes three classes of outcomes:

1. **Hard safety/integrity failures**: privacy, prompt injection, automatic publishing, education anxiety, prohibited marketing, unsafe image prompts, evidence/brand binding errors, source-footer integrity, provider identity/schema errors, unsafe downloads, invalid raster output, and missing checksums. These remain blocking.
2. **Recoverable quality findings**: ordinary copy style/brand/readability findings and image composition/OCR/quality findings. These may consume one repair and then remain warning-only.
3. **Transient provider failures**: timeouts, rate limits, and temporary unavailability. These use the existing bounded attempt budget and exponential backoff.

## Copy flow

`validate_material_draft` continues to produce typed issues. The policy layer owns the allowlist of recoverable copy-quality codes and normalizes only those codes to `warning`. The executor sends recoverable issues through one structured repair request; after the repair budget is exhausted, it accepts a draft only when no hard validation or audit error remains. Existing durable drafts, attempts, and audit issues remain unchanged.

The version bundle/rule and prompt versions are bumped so this behavior is explicit in new fingerprints. Historical runs retain their stored version and status.

## Image flow

The existing sequence remains:

```text
provider call -> deterministic output/OCR/audit checks -> private MinIO success
```

On ordinary quality failure:

```text
first failure -> one targeted repair -> second failure -> reserved catalog fallback
```

On provider rejection:

```text
first rejection -> one neutralized prompt retry -> rejection/quality failure -> catalog fallback
```

On a transient provider error, the worker continues using `IMAGE_MAX_ATTEMPTS`. When that budget is exhausted, it attempts the same catalog fallback if the current reservation contains a valid topic-matched reference. The fallback path must not make another provider call. If no valid reference exists, the current typed terminal/review state is retained.

## Private visual catalog

The private PNG directory is compiled into the existing manifest. An optional one-shot catalog
annotation command may send one approved PNG at a time to the configured Zhipu vision model, but
the daily worker never depends on that remote call. The annotator requests one constrained JSON
object, strips provider reasoning/fences, validates it against a fixed allowlist, and stores model
suggestions separately from the production canonical tags. It never persists the raw provider body,
prompt, key, image copy, URL, or arbitrary model text. A provider failure, invalid JSON, or empty
label set leaves the filename/directory-derived metadata in place and records a bounded fallback
status in the private annotation sidecar.

Each entry adds bounded, human-readable metadata: `asset_kind` (`identity`, `action`, or
`style`), `variant_group`, `display_name`, and `selection_tags`. Existing topic/pose/scene fields
remain the matching vocabulary, while the catalog loader revalidates the file, dimensions, media
type, byte size, and checksum before use.

Identity assets are clean, character-focused references. Scene/action assets carry only
`action_reference`; their containing characters do not make them identity references. Style assets
are optional. The selector first covers requested characters with identity assets, then selects a
topic/action asset, and finally adds an available style asset if capacity and budget allow. Missing
style assets do not set the selection fallback flag. A stable selection seed can rotate equally
eligible variants for new runs; persisted reference rows remain authoritative for retries.

The Comfly adapter receives the ordered selected references as the existing `image` data-URL array.
The ToAPIs adapter keeps its explicit one-reference capability fallback. Metadata descriptions and
selection tags are used only after bounded allowlist validation and are not copied into text RAG or
provider prompts as arbitrary instructions.

The fallback uses the existing `render_catalog_fallback_image`, `validate_image_output`, `put_immutable`, `_persist_catalog_fallback_success`, and safe version-snapshot projection. It therefore keeps the existing idempotency and private-storage guarantees.

The visual model can suggest descriptive tags but cannot change the authoritative directory
classification, approval flag, identity role, canonical topic/action fields, or safe reference
limits. The metadata sidecar is private and ignored by Git; rebuilding the manifest remains
deterministic for a fixed sidecar and asset set.

## Retry and idempotency

No new retry loop or database column is introduced. Existing `content_max_attempts`, `image_max_attempts`, `repair_count`, and `provider_rejection_retry_count` remain the limits. Every new branch checks the claimed lease and reuses the existing request fingerprint. A retry may create another attempt record, but only one image artifact can become succeeded for the fingerprint.

## Observability

Use existing structured events and add explicit action/state fields where needed: `retry_scheduled`, `quality_warning_continued`, `brand_catalog_fallback`, or `review_required`. Values are bounded codes and IDs only; no raw provider data or content is logged.

## Compatibility and rollback

No migration is required. New version identifiers make the behavior explicit for future runs. Rolling back the code restores the old terminal behavior for new work; existing fallback artifacts remain valid and immutable. The feature should be deployed with API/content-worker configuration using the same existing attempt limits.

## Risks

- A quality-warning draft may be less polished. The repair is bounded, warnings remain visible, and hard safety/integrity findings still block.
- A fallback may be visually generic. Its topic-matched asset metadata and fallback state remain visible for review.
- A missing catalog asset still blocks image readiness; silently inventing or reusing unrelated assets is not acceptable.
