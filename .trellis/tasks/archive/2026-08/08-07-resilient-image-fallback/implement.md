# Resilient Image Fallback Implementation Plan

## Implementation

1. Add the additive Alembic revision and SQLAlchemy mapping for the bounded provider-rejection
   retry counter; extend PostgreSQL migration assertions.
2. Add domain helpers for neutralized prompt assembly and approved catalog-asset square rendering.
   Reuse catalog checksum/path validation, raster validation, fingerprint, and MinIO storage code.
3. Extend the material-package worker claim budget and rejection branch to schedule exactly one
   neutralized retry, persist safe fallback provenance, and emit redacted structured events.
4. Add the terminal catalog fallback path, including stable selected-reference choice, aspect-safe
   PNG composition, deterministic validation, immutable storage, and package-ready persistence.
5. Project fallback provenance through the backend schema/route and generated OpenAPI types; map
   and display it in the material package UI.
6. Update the relevant backend specs for image-generation state, logging, API-safe provenance, and
   direct WeCom readiness semantics.

## Validation

- Focused backend unit tests for primary rejection, neutralized retry success, double rejection
  catalog success, fallback rendering failure, redacted logging, state/lease idempotency, and API
  safe projections.
- PostgreSQL migration test and existing material/WeCom candidate-query tests.
- `make backend-check`
- `make frontend-check`
- `make doctor`
- `docker compose config --quiet`
- `git diff --check`

## Rollback Points

- Before the migration, no persistent schema change exists.
- After the migration, reverting worker/API code preserves completed package/image rows and leaves
  the additive counter unused.
- A live provider or group-webhook send is not part of validation; deterministic adapters cover the
  recovery paths without generating external side effects.
