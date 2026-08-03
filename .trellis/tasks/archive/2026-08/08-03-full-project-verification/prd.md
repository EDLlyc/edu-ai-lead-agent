# Full project runtime verification

## Goal

Verify that the current MVP can be installed, migrated, tested, built, and started as a
single project, with observable evidence for the backend, frontend, and local infrastructure.

## In Scope

- Validate the local development environment and project dependency checks.
- Render and start the Docker Compose infrastructure required by the application.
- Verify PostgreSQL, pgvector, MinIO, the current Alembic head, required tables, and the
  configured source registry/bucket.
- Run backend formatting, linting, strict type checking, unit tests, and integration tests.
- Run frontend generated-contract synchronization, formatting, linting, strict type checking,
  tests, and production build.
- Run the API health/readiness smoke check and record the actual HTTP result.
- Report failures with the command, first useful error, and whether the failure is a product
  defect, an environment issue, or a verification-script defect.

## Out of Scope

- Real external source scraping or network-source freshness validation.
- Real Zhipu generation, ToAPIs image generation, or provider billing.
- Production deployment, public exposure, or destructive cleanup of user data.

## Acceptance Criteria

- [x] The environment/doctor result is recorded, including any migration-head mismatch.
- [x] Compose configuration renders successfully and required local services become healthy.
- [x] Database migration reaches the repository's actual current head and required schema checks
      pass, or the exact blocking defect is documented.
- [x] Backend and frontend checks complete with pass/fail evidence.
- [x] API health/readiness endpoint returns the expected success response when the stack is up.
- [x] A concise final report distinguishes verified capabilities from unverified external/provider
      paths and does not claim a full pass when any gate failed.

## Verification Outcome

See [`verification.md`](./verification.md). The product stack and all automated quality gates pass;
`make doctor` has one stale migration-head assertion that remains to be fixed separately.

## Notes

- This is a verification-only task. Do not change product code to hide or bypass a failing gate.
- Use existing Makefile targets and project scripts as the source of truth.
