# Result — 图片供应商输出容错与品牌素材兜底

## Outcome

- Comfly `gpt-image-2` now requests `response_format="url"` while retaining strict URL, valid
  Base64, direct-raster, and documented task-response compatibility.
- Only `ImageOutputValidationError.reason == "image_output_representation_invalid"` enters the
  compatibility one-use output recovery. The durable fallback snapshot carries
  `initial_error_code=image_output_invalid` without a migration.
- Representation recovery preserves the active prompt, controlled plan, and reference order while
  deriving a distinct replay-stable provider request fingerprint. Historical provider rejection
  keeps its neutralized prompt and existing fingerprint behavior.
- A second representation failure renders and validates one pre-reserved catalog asset without a
  third provider call. Success retains the requested provider/model, records safe `brand_catalog`
  provenance, and leaves the package `awaiting_manual_use`; missing/corrupt assets and storage
  failures remain review-required/failed.
- URL/address, redirect, media/signature, byte-size, dimension, identity, OCR parser, and other
  security/integrity failures remain terminal. No OpenAPI, frontend wire, migration, or delivery
  eligibility changes were introduced.

## Files changed

- `backend/app/infrastructure/ai/image_generation.py`
- `backend/app/domain/image_fallback.py`
- `backend/app/application/services/material_package.py`
- `backend/tests/unit/test_image_generation.py`
- `backend/tests/unit/test_image_fallback.py`
- `backend/tests/unit/test_material_package.py`
- `backend/tests/unit/test_wecom_delivery.py`
- `.trellis/spec/backend/error-handling.md`
- `.trellis/spec/backend/agent-pipeline.md`
- `.trellis/spec/backend/visual-diversity.md`
- `.trellis/spec/backend/wecom-delivery.md`
- `.trellis/spec/backend/quality-guidelines.md`
- `.trellis/spec/guides/cross-layer-thinking-guide.md`
- `.trellis/tasks/08-17-image-output-fallback-reliability/implement.md`
- `.trellis/tasks/08-17-image-output-fallback-reliability/research/root-cause.md`
- `.trellis/tasks/08-17-image-output-fallback-reliability/result.md`

## Verification

- Baseline focused suite: `136 passed`.
- Final focused suite:
  `conda run --name edu-ai pytest backend/tests/unit/test_image_generation.py backend/tests/unit/test_image_fallback.py backend/tests/unit/test_material_package.py backend/tests/unit/test_wecom_delivery.py -q`
  → `154 passed` after independent review replaced the injected worker error with a real
  MockTransport adapter response and added explicit catalog-fallback delivery replay coverage.
- Focused Ruff format/lint → passed.
- Strict application mypy: `Success: no issues found in 157 source files`.
- `make backend-check` → Ruff format (`279 files already formatted`), Ruff lint passed, mypy
  (`162 source files`) passed, full backend `967 passed in 65.84s`, total coverage `81%`.
- Independent post-review components → `make backend-format-check`, `make backend-lint`, and
  `make backend-typecheck` passed; `make backend-test` passed with `968 passed in 65.05s` and 81%
  coverage.
- `make api-contract-check` → backend OpenAPI and generated frontend API contract drift checks
  passed.
- `git diff --check` → passed.
- `docker compose config --quiet` → passed.
- Added-line credential-pattern scan → clean. `gitleaks` was unavailable in the environment.

## Safety and release boundary

- All provider behavior used fakes, `httpx.MockTransport`, and local raster fixtures.
- No Comfly, Zhipu, MinIO, WeCom, or production call was made.
- The 2026-08-17 noon package was not replayed, rebuilt, resent, or otherwise mutated.
- No deployment, commit, or push was performed.

## Remaining risk

- PostgreSQL/MinIO contention behavior continues to rely on the existing full-suite lease,
  uniqueness, and delivery idempotency coverage; this change adds no schema or new persistence
  primitive. The independent Trellis check found no remaining code blocker before any separately
  authorized deployment.
