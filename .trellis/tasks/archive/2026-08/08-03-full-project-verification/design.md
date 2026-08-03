# Verification Design

## Boundaries

The verification follows the same boundaries as the running system:

1. **Environment**: Conda/dependencies, Docker, Compose rendering, and repository scripts.
2. **Infrastructure**: PostgreSQL with pgvector and MinIO, including health and required schema
   state.
3. **Backend**: static checks, unit tests, integration tests, and API health/readiness.
4. **Frontend**: generated OpenAPI drift, formatting, lint, type checking, tests, and build.
5. **Cross-layer smoke**: API process starts against the migrated local services and exposes the
   expected health contract.

## Data Flow

```text
Makefile/scripts -> Compose services -> migrations/schema checks -> backend API
                 -> OpenAPI contract -> frontend checks/build
```

No provider call is part of the verification data flow. External acquisition, Zhipu, and image
provider paths remain explicitly unverified and must be labeled that way in the report.

## Evidence and Classification

Each gate records its command, exit status, and the first actionable failure. Failures are
classified as:

- **Product defect**: code, test, contract, or migration behavior is wrong.
- **Environment issue**: missing local dependency, unavailable daemon, or insufficient runtime
  resource.
- **Verification-script defect**: the checker asserts stale repository state, such as an old
  Alembic revision while the database is at the current migration head.

The repository's current migration head is discovered from Alembic and migration files, rather
than assumed from a hard-coded doctor message.

## Safety

Use only repository-local, reversible checks. Do not delete volumes, truncate data, publish
content, call paid providers, or expose credentials. If an already-running service is reused,
record that fact instead of restarting destructively.
