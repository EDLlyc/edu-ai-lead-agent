# Implementation Plan: Content-Driven Company IP Image Generation

## Preconditions and gates

- [x] Keep task in `planning` until the final planning summary is approved by the user.
- [x] Before code edits, load `trellis-before-dev` for the backend and frontend layers touched.
- [x] Preserve the existing clean/dirty worktree boundary; do not modify unrelated user files.

## Step 1 — Catalog and selection foundation

- [x] Extend the private manifest schema and builder with approved visual roles, topic/action tags,
      priority, and catalog version while retaining path, PNG, checksum, and sidecar safety checks.
- [x] Add a deterministic catalog loader and selector with request-byte budgeting, combined-character
      preference, fallback mode, and explainable selection reasons.
- [x] Add unit tests for robotics, astronomy, reading, tie-breaks, missing assets, checksum changes,
      path escape, unapproved assets, and byte-budget fallback.
- [x] Rebuild the private local manifest and inspect the selected real asset set without staging
      private source files or secrets.

## Step 2 — Visual brief and prompt assembly

- [x] Add provider-neutral `VisualBrief`, `VisualTextLayer`, and typed allowlists with strict bounds.
- [x] Build the brief from accepted topic/copy context and the approved target text pattern; keep full
      Moments copy outside the image prompt text layer.
- [x] Add a versioned prompt assembler with identity, scene, composition, palette, exact text, and
      negative-constraint sections.
- [x] Add unit tests proving brief normalization, text allowlist rejection, prompt versioning, prompt
      injection resistance, and no full-copy leakage.

## Step 3 — Multi-reference image contract

- [x] Extend `ImageGenerationRequest` and all adapters/fakes to carry ordered typed references.
- [x] Update Comfly payload encoding, total request bounds, mock response tests, and explicit provider
      single-reference fallback behavior.
- [x] Include ordered asset IDs/checksums, brief, catalog/selector versions, and prompt/pipeline
      versions in the image fingerprint.
- [x] Add migration/model/repository support for `image_artifact_references` and immutable reference
      projections.

## Step 4 — Worker, package API, and UI integration

- [x] Replace the single configured reference read in material-package reservation/execution with the
      catalog/brief/selector flow while retaining the rollback flag.
- [x] Persist visual brief and reference summaries in the package snapshot and reference rows after
      successful reservation; preserve lease and idempotency behavior.
- [x] Add API schemas/projections for safe visual brief and selected reference metadata.
- [x] Add an accessible frontend section that shows image intent, selected brand assets, and safe
      validation/fallback state without exposing private paths or adding publishing controls.
- [x] Update generated OpenAPI/frontend types and focused backend/frontend tests.

## Step 5 — Validation, repair, and live acceptance

- [ ] Add exact-text OCR validation for the compact editorial layer where the configured OCR capability
      is available; fail closed on unexpected text.
- [ ] Add the provider-neutral image-quality audit seam and one targeted repair path; keep the existing
      one-repair/no-force-publish rule.
- [x] Run focused tests, Ruff, strict mypy, frontend tests, Compose config, Doctor, and diff/secret
      checks.
- [x] Rebuild only the required content services, then run a real robotics/AI package with a new prompt
      and pipeline version. Save the inspected output under the project `output/` directory using a
      versioned descriptive filename.
- [x] Verify database idempotent replay, MinIO object, API download, UI projection, selected IP
      references, and no automatic distribution.

## Validation commands

```bash
conda run --name edu-ai pytest backend/tests/unit/test_image_generation.py backend/tests/unit/test_material_package.py backend/tests/unit/test_brand_asset_manifest.py -q
conda run --name edu-ai ruff check backend/app backend/tests scripts
conda run --name edu-ai mypy --strict backend/app
npm --prefix frontend test -- --run
docker compose config -q
make doctor
git diff --check
```

Run broader suites after the focused gate passes. Live provider calls must use the existing local
secret configuration and must never print credentials, raw provider bodies, signed URLs, or full raw
prompts.

## Rollback points

- Before migration: keep selector disabled and use the existing one-reference path.
- After migration/provider work: set selector/multi-reference feature flag off; retain new rows and
  historical artifacts without relabeling them.
- After live acceptance: stop content worker or disable image generation if provider quality is not
  acceptable; never repair a successful artifact by direct database mutation.
