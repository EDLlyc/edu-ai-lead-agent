# Image Generation and Material Package UI

## Goal

Generate one safe image for an accepted draft, assemble one auditable material package, and provide
an accessible internal review, copy, and image-download experience.

## Parent and Dependency

- Parent: `07-30-content-production-mvp`.
- Requires an accepted draft/image prompt from `07-30-copy-generation-audit`.
- Completes the end-user vertical slice and parent integration gate.

## Requirements

- Use the approved ToAPIs provider at `https://toapis.com` with model `gpt-image-2`, exactly one
  `1:1` / `1k` output, and the documented asynchronous generation contract.
- Upload one approved local Sai Xiansheng/Xiaosai PNG reference through the provider upload API;
  never ask the model to redraw a textual logo or persist the transient public upload URL.
- Generate exactly one image for one accepted prompt/fingerprint and store it privately in MinIO.
- Persist provider/model/prompt versions, dimensions, safe provider ID, object identity, attempts,
  statuses, and idempotency without raw provider material or credentials.
- Assemble selected topic/score, draft, takeaway, interaction, image, sources, evidence/brand
  bindings, validation/audit state, and manual review state into an immutable package version.
- Expose bounded run/package/review APIs and a controlled image-download route.
- Build internal routes for daily/no-topic status, brand documents, run status, and package detail.
- Support keyboard-accessible review acknowledgement/rejection, copy feedback, source inspection,
  and image download. Do not provide inline editing or publishing.

## Acceptance Criteria

- [ ] Provider retries/replay/concurrency create at most one successful image artifact per request
      fingerprint.
- [ ] Unsafe prompts/provider outputs fail with typed, reviewable states before package readiness.
- [ ] A ready package exposes complete source/binding/validation/audit/version metadata.
- [ ] UI explicitly renders loading, no-topic, failed, reviewable failure, and ready states.
- [ ] Copy and download work with keyboard and accessible success/error announcements.
- [ ] A controlled end-to-end test and one bounded live image/package acceptance pass.
- [ ] No API, UI, config, or data field enables automatic publishing or stores social credentials.

## External Input

The approved visual assets are available under `private/brand-materials/05-visual-assets/`. Live
acceptance requires `TOAPIS_API_KEY` to be injected locally as a secret; it must not be committed,
logged, returned by an API, or stored in provider/job metadata.

## Out of Scope

- Multiple images, image editing, templates, video, public access, complex approval roles,
  collaborative editing, analytics, or social publishing.
