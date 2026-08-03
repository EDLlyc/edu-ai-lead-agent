# Verification Results

**Date:** 2026-08-03
**Branch:** `main`

## Passed Gates

- `docker compose config --quiet` passed.
- `make infra-up` passed; PostgreSQL/pgvector and MinIO are healthy.
- `make migrate` passed; database revision is `20260731_0009`.
- `make backend-integration-test` passed: 39 tests.
- `make check` passed: 294 backend tests, OpenAPI contract check, frontend formatting/lint/typecheck,
  3 Vitest tests, and Vite production build.
- `make stack-up` passed; API, scheduler, and worker containers are running.
- `GET http://127.0.0.1:8000/healthz` returned HTTP 200 with `status: "ok"`.
- Startup logs show the acquisition scheduler and worker started successfully; the worker completed
  the scheduled acquisition run for the configured sources without a process error.

## Doctor Result

`make doctor` reaches all environment, dependency, Compose, service-health, and pgvector checks,
then fails only because `scripts/doctor.sh:93` expects `20260730_0007`. The database and migration
tests confirm the repository's current head is `20260731_0009` (material-package migration).

Classification: **verification-script defect**, not an application or database migration failure.
The script was intentionally left unchanged in this verification-only task.

## Not Exercised

- Real Zhipu model generation.
- Real ToAPIs image generation.
- Production deployment and public exposure.

No provider credentials or paid provider calls were used by this verification task.
