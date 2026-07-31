# Design: Image Generation and Material Package UI

## Boundary

Consume one accepted draft/image prompt, generate one safe image, store it privately, assemble one
versioned material package, and expose an accessible internal review/copy/download experience. No
inline editing, multiple variants, complex approval, public access, or publishing.

## Image Contract

- Add application-owned `ImageGenerator` with deterministic fake and a bounded ToAPIs adapter.
- Pin `POST /v1/uploads/images`, `POST /v1/images/generations`, and
  `GET /v1/images/generations/{task_id}` at the HTTPS origin `https://toapis.com`.
- Submit `model=gpt-image-2`, `n=1`, `size=1:1`, `resolution=1k`,
  `response_format=url`, and a stable `client_business_id` derived from the application request
  fingerprint. Use one uploaded approved PNG through `reference_images=[url]`.
- Poll after an initial five seconds, then every 5-10 seconds with jitter; honor `Retry-After` on
  429/503 and stop after a bounded 120-second provider window. Treat `queued`, `in_progress`,
  `completed`, and `failed` as the only accepted task statuses.
- A completed task must contain exactly one `result.data[].url`. Download it immediately because
  provider URLs expire after 24 hours. Accept only HTTPS `files.toapis.com`, no redirects, an
  allowlisted raster content type, bounded bytes, and the expected 1024x1024 dimensions before
  private MinIO storage.
- `TOAPIS_API_KEY` is the only provider credential. The local upload URL, generated URL, raw
  provider response, prompt body, and bearer token are transient and must not enter logs, APIs, or
  durable job metadata. Persist only safe task/upload IDs, model/version identity, checksums,
  attempts, dimensions, status, and typed error codes.
- One accepted prompt/profile fingerprint maps to at most one successful artifact. Provider calls
  occur outside transactions; persistence checks the fingerprint/provider state before retry.
- Validate prompt/rules before call and returned content type/size/dimensions after call. Do not
  accept unsafe minor identity, infringement-prone marks, complex rendered Chinese text, or raw
  provider material. The model may use the approved character reference, but it must not invent,
  trace, or typeset a logo; brand text remains an application/UI overlay outside the generated
  bitmap.

## Storage and Package

- Store images under sanitized content-addressed MinIO keys with private access and checksum.
- A package version references the exact daily selection/event/config, accepted draft/claims/
  bindings/audit, image artifact, source links, versions, and manual review state.
- `awaiting_manual_use` means ready for internal review/copy/download. `completed` is internal
  acknowledgement only, never proof of publication.
- Image downloads use a controlled API stream/short-lived mechanism without permanent public URLs,
  object-store credentials, or arbitrary object keys.

## Frontend Architecture

Add app routing and feature directories for `daily-topics`, `brand-documents`, `pipeline-runs`, and
`material-packages`. Feature API modules consume generated OpenAPI types; TanStack Query owns server
state/polling; pure mappers create discriminated loading/no-topic/failed/reviewable/ready views.

Package page sections:

- topic and score explanation;
- copy, parent takeaway, interaction, and source note;
- image preview/alt/download;
- source links and claim evidence/brand context;
- deterministic validation and audit issues/status;
- manual acknowledge/approve or reject note;
- accessible copy/download feedback.

Render all model/source/brand text as text, validate URLs/filenames, and use no
`dangerouslySetInnerHTML`. There is no publish button or social credential surface.

## API

- Image/content run and job status queries.
- Package list/detail and bounded manual review mutation.
- Controlled image download.
- Existing brand upload and daily topic APIs become navigable product surfaces.

## Rollout

Deploy image disabled, prove fake provider/storage/package/API/UI/E2E, run one live image safety/
brand review, then enable for accepted drafts. Rollback disables image/content worker stages and
keeps ready/failed packages inspectable.
