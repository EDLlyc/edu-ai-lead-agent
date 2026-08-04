# Current Image and Asset Contract Research

## Repository evidence

- `scripts/build_brand_asset_manifest.py` scans the private image-example and visual-asset roots,
  validates bounded PNG structure, computes content-derived IDs, and records only character-name tags.
  It intentionally keeps visual assets out of text RAG.
- `private/brand-materials/05-visual-assets/` contains the supplied Sai Xiansheng/Xiaosai character
  and action artwork. The files are private, mounted read-only into `content-worker`, and are not
  public API resources.
- `backend/app/application/services/material_package.py` reserves one image artifact using one
  configured `reference_asset`, then re-reads and checks that same file before calling the provider.
- `backend/app/application/ports/image_generation.py` exposes one optional `reference_image` and one
  optional `reference_filename` on `ImageGenerationRequest`.
- `backend/app/domain/image_generation.py` includes one optional reference digest in the idempotency
  fingerprint.
- `backend/app/infrastructure/ai/image_generation.py` converts one reference body into a Comfly
  `image` data-URL array with one member, enforces request/response byte bounds, and normalizes one
  provider image result.
- `image_artifacts` currently stores one `reference_sha256`; `material_packages.version_snapshot` is
  the existing safe place for immutable version metadata, while relational artifact data is preferred
  for repeated reference rows.
- The existing material-package API/UI already shows image status, copy, evidence, brand bindings,
  validation, audit, and a private download. It does not expose visual brief or selected reference
  metadata.

## Provider evidence

The archived Comfly research records `POST /v1/images/generations`, the `image` array field, and
model-dependent reference-image support. The public response schema is incomplete, so the existing
adapter deliberately accepts only bounded recognized URL/base64/task shapes. Multi-reference support
must therefore be verified with mocks and one bounded live capability check; it must not silently drop
references when the configured model rejects them.

## Target visual evidence

The user-approved target is:

`output/imagegen/sai-xiansheng-embodied-ai-gpt-image-2-zh-brand-v2-20260731.png`

It establishes the visual acceptance direction: both supplied characters, a clear central science or
robotics subject, deep science blue with white and restrained orange accents, a polished 3D educational
scene, an editorial title/learning line, a few process labels, and one concise brand-value line. It is
not a substitute for the private source IP files and must not become an unapproved generic reference.

## Constraints and implications

- Full Moments copy must stay outside the generated image. The image text layer is a bounded editorial
  projection: title, one concise line, up to four keywords, and up to one approved brand-value phrase.
- Reference selection must be deterministic and explainable, not a model-generated path lookup.
- The Comfly request has a total byte bound. Since several private PNGs are multi-megabyte, the selector
  needs a reference budget and an explicit single-reference fallback.
- Existing private storage, SSRF/output-host validation, accepted-draft gating, idempotency, worker
  lease, and manual-use-only boundaries remain unchanged.
