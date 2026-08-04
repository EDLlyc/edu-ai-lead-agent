# Content-Driven Company IP Image Generation

## Goal

Generate one parent-facing science image whose subject follows the accepted Moments copy and whose
characters and visual language come from the supplied Sai Xiansheng company IP assets. The selected
assets, visual brief, prompt version, provider request, validation result, and final image must be
reproducible in the existing versioned material package.

## User Value

The image should communicate the same science/AI/robotics idea as the copy while remaining visibly
owned by Sai Xiansheng. A generic child-and-robot illustration is not an acceptable success result.

## Confirmed Repository Facts

- `scripts/build_brand_asset_manifest.py` builds a private, text-RAG-ineligible manifest for bounded
  PNG assets, but currently records only basic image metadata and character-name tags.
- `MaterialPackageExecutor` reads one configured `reference_asset` and passes one
  `reference_image` into `ImageGenerationRequest` (`backend/app/application/services/material_package.py:270-320`).
- The image request fingerprint currently includes one optional `reference_sha256`
  (`backend/app/domain/image_generation.py:30-58`); the image artifact stores the same single digest
  (`backend/app/infrastructure/db/models.py:2453-2537`).
- The Comfly adapter already sends an `image` array, but its public application contract and current
  tests exercise only one encoded reference image (`backend/app/infrastructure/ai/image_generation.py`).
- The supplied `output/imagegen` examples define the target visual direction: parent-facing science
  education, polished 3D illustration/information-graphic composition, deep blue/white/orange visual
  language, and Sai Xiansheng/Xiaosai identity. They are style references, not replacements for the
  real company IP assets.
- Image provider calls remain content-worker-only, bounded, private, idempotent, and gated by an
  accepted copy draft. Existing MinIO, SSRF/output-host, media-type, size, signature, and dimension
  checks remain mandatory.

## Requirements

### R1. Controlled visual asset catalog

- Extend the private visual manifest with human-approved roles, topic tags, action/pose tags, priority,
  approval state, checksum, and schema version.
- Distinguish identity, action, and style references. Identity must come from the supplied company IP
  assets; style examples cannot be the only identity reference.
- Reject symlinks, missing files, invalid checksums, unsupported media, oversized files, and unapproved
  assets before a provider request.
- Do not ingest visual asset bodies into text RAG or expose their private paths through the API.

### R2. Copy-driven visual brief

- Produce a typed visual brief from the accepted topic/copy with category, learning goal, scene, main
  action, character tags, asset tags, reference roles, and text-rendering mode.
- Model output may propose bounded tags and short descriptions but may not choose arbitrary file paths,
  URLs, or untrusted asset IDs.
- A deterministic selector must turn the brief into an ordered, explainable asset set. The same brief,
  manifest version, and selector version must produce the same selection.

### R3. Brand prompt assembly

- Assemble a versioned prompt from the topic, visual brief, selected asset roles, approved style rules,
  and safety constraints; do not send the raw generic `image_prompt` as the complete provider prompt.
- Preserve Sai Xiansheng/Xiaosai identity, proportions, clothing colors, and approved visual language.
- Keep the full Moments copy out of the image. The image may contain a compact visual text layer that
  follows the approved example: a short topic title, one concise learning/brand line, a few topic or
  process keywords, and one approved brand-value phrase such as “守护好奇心 · 锤炼思考力 · 培养创造力”.
- The visual text layer is derived from a bounded allowlist/visual brief, never copied from the full
  Moments draft. It must be validated with OCR or an equivalent exact-text check.
- Forbid invented logos/marks, watermark, QR code, unrelated characters, real child faces, unsupported
  promises, and excessive or unverified embedded text.

### R4. Multi-reference provider contract

- Extend the provider-neutral request to carry an ordered tuple of typed references with role, asset ID,
  filename, checksum, and bytes.
- Send up to the configured reference limit to Comfly when the model accepts multiple images. If the
  provider supports only one, use an explicit single-reference fallback and persist that mode; never
  silently discard selected identity references.
- Keep all request, response, URL, redirect, byte, media, signature, and dimension safety controls.

### R5. Durable identity and package traceability

- Include the visual brief, ordered asset IDs/checksums, manifest version, selector version, prompt
  version, pipeline version, provider, and model in the request fingerprint.
- Persist one reference record per selected asset or an equivalent normalized immutable projection.
- Expose safe visual brief/reference metadata in the material-package detail view without exposing
  private object keys, temporary provider URLs, raw prompts, or secrets.

### R6. Validation and bounded repair

- Validate brief schema, selected references, provider output, raster signature, media type, dimensions,
  byte limits, and allowed short text in a fixed order.
- Add a provider-neutral image-quality audit seam for visual relevance and IP adherence; deterministic
  checks remain authoritative for hard failures.
- Allow at most one targeted image repair. A second failure remains `review_required` and cannot become
  a sendable or automatically distributed package.

### R7. Compatibility and operations

- Keep fake/offline generation network-free and preserve existing single-reference mode behind a
  feature flag for rollback.
- Do not change acquisition, governance, topic locking, copy evidence bindings, or enterprise-WeChat
  distribution boundaries.
- Use Alembic for schema changes, PostgreSQL for durable state, MinIO for private generated images,
  and existing worker leases/heartbeats/retry rules.

## Acceptance Criteria

- [ ] A robotics brief deterministically selects approved Xiaosai/Sai Xiansheng identity/action assets;
      astronomy and reading briefs select their corresponding approved assets.
- [ ] An unapproved, missing, symlinked, corrupted, or path-escaping asset is rejected before any paid
      provider call.
- [ ] The generated provider request contains the selected company IP reference bytes in the expected
      order, or records an explicit provider single-reference fallback.
- [ ] The final fingerprint changes when the selected asset, visual brief, prompt version, or pipeline
      version changes, and an idempotent replay does not create a second successful artifact.
- [ ] The material package can show the selected reference roles, safe asset names, visual brief,
      validation/audit status, and image download without leaking secrets or private storage details.
- [ ] A real robotics or AI topic produces a visually relevant image containing the supplied company IP
      identity; a generic unrelated character is rejected or marked for review.
- [ ] Provider/output validation, one-repair limit, review-required terminal state, existing image
      tests, backend quality gates, frontend tests, Doctor, and Compose checks remain green.
- [ ] No API, worker, or package introduces automatic social publishing.

## Out of Scope

- A new vector database, Redis/Celery queue, or public brand-asset CDN.
- Automatic publishing to Moments or any social platform.
- Video, animation, multi-image package variants, arbitrary user-uploaded image references, or logo
  redesign.
- Rewriting historical image artifacts or manufacturing a new result by direct database edits.

## Resolved Product Decision

The image is a standalone visual asset, not a rendered copy card and not the full Moments post. It may
contain a compact editorial layer matching the approved reference image:

- short topic title, for example `具身智能`;
- one concise learning-oriented line, for example `在真实体验中学习，在不断调整中成长`;
- a small number of topic/process keywords, for example `尝试`、`调整`、`进步`;
- one approved brand-value phrase, for example `守护好奇心 · 锤炼思考力 · 培养创造力`.

The full generated copy remains a separate material-package field and is never pasted into the image.
The initial render mode is therefore `editorial_keywords_and_brand_values`, with exact allowed strings
recorded in the visual brief and checked after generation.
