# Implementation Plan: Reliable Comfly Image Output Handling

1. Trace all `ImageOutputValidationError` paths in the Comfly adapter and add bounded internal
   reason classification without changing the external safe error contract.
2. Remove the Comfly output-host allowlist requirement; validate every HTTPS output hostname with
   the public-IP resolver, then normalize media type from verified bytes. Accept only a
   generic/missing header when PNG/JPEG/WebP signature and dimensions pass, and reject explicit
   mismatches.
3. Persist the allowlisted adapter-stage diagnostic into `image_artifacts.validation_snapshot` on
   failed attempts while keeping provider URLs, headers, bodies, prompts, and credentials out.
4. Add regression tests for generic CDN content types, header/signature mismatch, invalid rasters,
   dimension failures, retry behavior, and sensitive-data redaction.
5. Add a locked, bounded image-only retry API for terminal material-package images, then rebuild
   the API/content worker, execute a bounded live image generation, and requeue only the failed
   business-date image artifact if the live validation succeeds.
6. Run focused tests, full backend checks, Compose validation, and a staged secret scan.

## Validation

```bash
conda run --name edu-ai pytest backend/tests/unit/test_image_generation.py backend/tests/unit/test_material_package.py
make backend-check
docker compose --profile content config --quiet
git diff --check
```

## Rollback

Stop the updated content worker and redeploy the prior image adapter. The failed image artifact
remains review-required and no message is sent.

## Execution Record

- The observed Comfly output used a generic CDN response header. The adapter now accepts a generic
  or missing header only after the bounded body verifies as PNG/JPEG/WebP at 1024x1024; explicit
  header/signature disagreement remains terminal.
- A live content-driven Comfly smoke succeeded and wrote a persistent 1024x1024 PNG under
  `output/imagegen/` without creating a database artifact or Enterprise WeChat job.
- The first image-only retry exposed a cross-service deployment defect: `IMAGE_MAX_ATTEMPTS` was
  injected into `content-worker` but not `acquisition-api`. The API accepted a retry using its
  default of three attempts while the worker used one and immediately exhausted the image.
- Compose now injects the same value into both services, and `make doctor` renders the content
  profile and rejects a missing or divergent value. After recreation, the same image artifact was
  retried successfully, validated, stored privately in MinIO, and its package reached
  `awaiting_manual_use`. No Enterprise WeChat delivery job was created.
