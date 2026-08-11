# Implementation Plan

1. Read the backend implementation and test conventions immediately before editing.
2. Refactor the Comfly request-response boundary so creation responses retain normalized content
   type without retaining raw response material outside the adapter call.
3. Add a direct-raster creation-response branch that shares existing byte/media/dimension checks
   with decoded and downloaded images.
4. Preserve the JSON task/URL/Base64 paths; attach bounded safe diagnostics to actual provider
   rejection errors and their existing worker event.
5. Add focused unit tests for direct PNG/JPEG/WebP success, invalid direct responses, non-raster
   non-JSON rejection, and redaction of safe diagnostics.
6. Run focused tests, formatting/lint, strict mypy, and the full backend check. Inspect the diff and
   ensure user-owned report and skill changes are untouched.
7. After local quality passes, report the exact deployment smoke-test proposal before touching the
   server.

## Risky Files

- `backend/app/infrastructure/ai/image_generation.py`: provider protocol interpretation and output
  validation.
- `backend/app/core/errors.py`: typed error metadata must remain bounded and non-sensitive.
- `backend/app/application/services/material_package.py`: structured recovery logging only.
- `backend/tests/unit/test_image_generation.py`: protocol regression coverage.

## Local Validation

```bash
conda run --name edu-ai python -m pytest backend/tests/unit/test_image_generation.py
conda run --name edu-ai python -m ruff format --check backend/app backend/tests
conda run --name edu-ai python -m ruff check backend/app backend/tests
conda run --name edu-ai python -m mypy --config-file backend/pyproject.toml backend/app
make backend-check
git diff --check
```
