# Implementation Plan

1. Read the backend pre-development and quality guidance, then inspect current Comfly settings,
   factory wiring, downloader tests, and Compose environment propagation.
2. Add the opt-in setting to backend configuration, Compose, and `.env.example`; update the local
   ignored `.env` without printing or committing secrets.
3. Implement injected public-host DNS validation in the Comfly adapter while preserving the exact
   allowlist and bounded image validation paths.
4. Add focused regression tests for enabled CDN downloads, disabled unknown hosts, and non-global
   address rejection.
5. Run focused tests, Ruff, mypy, the backend suite, Compose config validation, and doctor.
6. Restart the API/content-worker services and run one real Comfly image-generation smoke. Inspect
   only safe status, dimensions, media type, artifact identity, and storage outcome.
7. Review the diff for secrets and unrelated changes, update the relevant backend spec if the new
   executable URL policy is worth preserving, commit the task changes, and archive the Trellis
   task.

## Validation commands

- `conda run --name edu-ai pytest backend/tests/unit/test_image_generation.py -q`
- `make backend-format-check backend-lint backend-typecheck`
- `make backend-check`
- `docker compose config --quiet`
- `make doctor`
- `git diff --check`

## Risk and rollback points

- URL policy implementation: keep the setting default false and reject non-global DNS results.
- Local configuration: modify only ignored `.env`; never include API key or signed URL in output.
- Live smoke: do not retry blindly if the provider charges per generation; use the existing
  request fingerprint/idempotency behavior and inspect the durable result first.
