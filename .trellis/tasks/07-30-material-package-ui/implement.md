# Implementation Plan: Functional Image and Material Package UI

- [ ] Run one bounded ToAPIs `gpt-image-2` account/upload/generation/poll/download compatibility
      probe using `1:1`, `1k`, one image, and one approved local reference PNG.
- [ ] Add image port/fake/ToAPIs adapter with critical bounds, typed errors, request fingerprint,
      safe provider IDs, transient URL handling, and secret-safe diagnostics.
- [ ] Add minimal image artifact/package/version/review persistence and migration.
- [ ] Generate one image, store it privately in MinIO, and expose controlled download.
- [ ] Add package assembly plus run/package/review APIs and regenerate OpenAPI types.
- [ ] Replace the environment shell with a simple internal daily/package experience; include brand
      upload navigation, score explanation, copy, image, sources, audit, review, and download.
- [ ] Cover ready, no-topic, and failed states with focused component/accessibility tests.
- [ ] Run a controlled end-to-end path and one bounded live image/package demonstration.
- [ ] Run the existing final program gates once, update specs, commit/archive child and parent.

Deferred: multiple images, editing, complex roles/approval, full Playwright matrix, public auth,
analytics, production operations, and exhaustive provider/storage concurrency testing.
