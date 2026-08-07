# Add resilient image generation fallback

## Goal

Ensure an accepted daily Moments copy can still become a deliverable material package when the
configured image provider rejects its first request, while retaining provider safety boundaries and
making the failure and all fallback decisions operationally visible.

## Confirmed Facts

- On 2026-08-07, the package for "全球首个端侧驱动本体的具身世界模型！大晓机器人发布
  Kairos 3.1" stopped before WeCom delivery because Comfly returned the typed
  `image_provider_rejected` error. The image became `review_required` and the package became
  `failed`; no delivery job was correctly created.
- Local image OCR and quality-audit gates were disabled for that run. The failure came from the
  upstream image-provider request rather than local validation or WeCom.
- The current system persists only typed provider errors and safe identity metadata. It deliberately
  does not persist raw provider responses, prompts, reference contents, credentials, temporary
  URLs, or private MinIO locations.
- `MaterialPackageExecutor` already owns durable image state, lease-safe retries, private MinIO
  persistence, package completion, and image-only operator retry. The visual-asset catalog already
  selects approved private brand assets deterministically by the accepted visual brief, but today
  it uses them only as provider references.
- Existing automatic WeCom reconciliation correctly excludes incomplete packages, so it must not
  enqueue delivery until a real generated or approved fallback image is durably available.

## Requirements

- R1: Classify and log image-provider rejections with bounded, non-sensitive operational fields so
  operators can see the package/image identifiers, provider/model, attempt/repair stage, fallback
  action, and typed safe error code without exposing prompts, raw responses, reference bytes,
  credentials, URLs, object keys, or copy text.
- R2: For an upstream image-provider rejection, perform one bounded retry using a deterministic,
  topic-preserving neutralized image prompt. The retry must not attempt to bypass or weaken provider
  safety controls.
- R3: When the neutralized retry cannot produce a valid 1024x1024 image, complete the material
  package with a topic-matched, approved existing visual asset rather than failing the delivery
  chain solely because image generation was rejected.
- R4: Persist a clear, versioned fallback provenance record in the image/package safe snapshots and
  expose it through the existing material-package API/frontend projection.
- R5: Preserve idempotency, leases, immutable private MinIO storage, current image output
  validation, and direct WeCom quality predicates. A fallback image must pass the same storage and
  delivery requirements as a generated image.
- R6: Add focused tests for the rejection -> neutral retry -> successful generated image path, the
  rejection -> approved asset fallback path, terminal/non-retryable behavior, log redaction, and
  idempotent replay.

## Acceptance Criteria

- [ ] A provider-rejected first image request generates exactly one safe structured operational log
  describing the rejection and the next action, without content-bearing or secret fields.
- [ ] The worker makes at most one neutralized retry for a rejection and records that fallback stage
  in durable safe metadata.
- [ ] If the retry succeeds, the package becomes `awaiting_manual_use` with a validated private
  image and can be selected by automatic WeCom delivery.
- [ ] If the retry is rejected or otherwise cannot yield a valid image, the worker stores a
  topic-matched approved existing visual asset privately, marks the package ready, and records the
  fallback provenance.
- [ ] Replays, races, and worker restarts do not create duplicate image artifacts, object writes, or
  delivery jobs.
- [ ] Existing image provider security and output validation rules remain enforced; raw provider
  rejection bodies remain unavailable in logs, APIs, database snapshots, and material downloads.

## Scope Boundaries

- In scope: automatic handling of typed image-provider rejections after an accepted copy has been
  reserved as a material package.
- Out of scope: changing, disabling, or bypassing Comfly/OpenAI safety policy; relaxing SSRF,
  output validation, or MinIO privacy controls; automatic social-network publishing; storing raw
  provider responses.

## Product Decisions

- The final fallback source is an approved image from the private brand visual catalog, selected
  against the current visual brief. The system must not reuse a generated image from a different
  news topic.
- The fallback renderer preserves the selected asset's aspect ratio on a 1024x1024 brand-neutral
  canvas and adds no generated copy, claims, QR code, watermark, or new logo. The resulting bytes
  undergo the normal raster and private-storage checks before package readiness.
- Provider rejection receives one independent, bounded neutralized-prompt retry. It does not
  consume the existing one-time output-quality repair allowance; both allowances are individually
  persisted and capped.
