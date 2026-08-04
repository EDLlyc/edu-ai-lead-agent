# Implementation Plan: Comfly Image Provider Switch

## Phase 1 - Settings and provider selection

- [x] Add `comfly` to the validated image provider mode and add `COMFLY_BASE_URL`/
      `COMFLY_API_KEY` settings with fail-closed HTTPS/key validation.
- [x] Update `compose.yaml` and `.env.example` with the new provider variables, preserving blank
      placeholder secrets and the existing ToAPIs rollback configuration.
- [x] Update API and content-worker lifecycles to own an HTTP client for the Comfly adapter.
- [x] Keep material-package provider/model identity sourced from settings and avoid any database
      mutation of existing ToAPIs artifacts.

## Phase 2 - OpenAI-compatible adapter

- [x] Implement `OpenAICompatibleImageGenerator` behind `ImageGenerator`.
- [x] Build the documented JSON request with bounded prompt, square ratio, model, and optional
      bounded data-URL reference input.
- [x] Normalize direct URL/base64 results and bounded async task results into
      `ImageGenerationResult`.
- [x] Reuse the existing raster, URL, identifier, timeout, retry, and safe-error helpers where
      their contracts apply; add only the helpers needed for the new response envelope.
- [x] Ensure all provider bodies, URLs, prompts, credentials, and reference contents stay within
      the adapter and are absent from logs/errors/persistence.

## Phase 3 - Tests and smoke tooling

- [x] Add unit tests for payload fields, data-URL encoding, direct URL/base64 responses, task
      polling, model/reference failures, 401/429/5xx classification, response bounds, and redaction.
- [x] Update factory/settings/lifecycle tests and preserve all existing ToAPIs/fake tests.
- [x] Update `image_live_smoke.py` to use the configured provider through the factory while keeping
      an explicit output-exists guard and bounded local output behavior.
- [x] Add provider contract documentation/spec updates for Comfly and its error matrix.

## Phase 4 - Local rollout and live verification

- [x] Write the supplied key only to the ignored local `.env` and verify it is not staged or logged.
- [x] Rebuild/recreate the API/content worker images with `IMAGE_PROVIDER_MODE=comfly`.
- [x] Run an authenticated `/v1/models` capability check without printing the response body; require
      `gpt-image-2` or stop with a typed model-unavailable finding.
- [x] Run one bounded live image smoke with the approved reference asset. It failed closed with a
      typed timeout/unknown CDN-host validation; no image was created or persisted.
- [x] Confirm the worker claims only Comfly reservations and existing ToAPIs failures remain
      historical/unchanged.

## Phase 5 - Quality gate

- [x] Run focused image/config tests.
- [x] Run backend unit/contract tests and existing material-package tests.
- [x] Run Ruff format/lint, mypy, frontend checks if generated API/config contracts change,
      `make doctor`, Compose validation, and `git diff --check`.
- [x] Run a credential/staged-path scan that reports only counts and paths, never secret values.
- [x] Obtain Trellis check approval before committing and pushing.

## Validation commands

```bash
conda run --name edu-ai pytest backend/tests/unit/test_image_generation.py backend/tests/unit/test_material_package.py -q
conda run --name edu-ai pytest backend/tests -q
make backend-check
make doctor
docker compose --profile content config --quiet
git diff --check
```

## Risky files and rollback points

- Risky code: `backend/app/infrastructure/ai/image_generation.py`,
  `backend/app/core/config.py`, `backend/app/infrastructure/ai/factory.py`,
  `backend/app/api_main.py`, `backend/app/content_worker_main.py`, `backend/app/image_live_smoke.py`,
  `compose.yaml`, and the image provider tests/spec.
- Before live rollout, rollback is changing the local mode to `fake` or the previous `toapis` mode;
  no database rollback is needed.
- If the provider response shape or reference handling is incompatible, leave Comfly disabled and
  preserve the old/fake route; do not broaden URL acceptance or rewrite failed artifacts.

## Completion gate

The code/configuration switch and quality gate are complete. The authenticated capability check
passed, but the live smoke did not produce a stored image because the provider returned a CDN host
that is not yet explicitly configured in `COMFLY_OUTPUT_HOSTS`; the adapter correctly failed closed.
Do not call the provider live-ready or publish an image until that exact hostname is obtained from
the provider and a bounded smoke succeeds. Do not broaden the allowlist to an arbitrary host.
