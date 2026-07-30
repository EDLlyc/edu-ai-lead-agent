# Implementation Plan: Functional Image and Material Package UI

- [ ] Run a short image endpoint/model/account/output compatibility probe.
- [ ] Add image port/fake/live adapter with critical bounds, typed errors, and request fingerprint.
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
