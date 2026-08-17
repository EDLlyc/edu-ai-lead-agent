# Bounded implementation and check contract

This summary extracts only the image-output reliability rules needed from the large backend
pipeline and quality specifications. The source specifications remain authoritative and must be
updated with the implementation.

## Image generation and package rules

- One accepted draft reserves exactly one image artifact. Provider calls are made outside database
  transactions and persistence re-checks lease/fingerprint ownership.
- The provider adapter owns all untrusted response parsing. Accepted output is one bounded,
  validated 1024×1024 PNG/JPEG/WebP representation; generated URLs and provider bodies are
  transient and never enter durable metadata, APIs, or logs.
- URL output requires HTTPS, no redirects, public address resolution, bounded bytes, compatible
  media type/signature, and exact dimensions. These gates are security/integrity gates and cannot
  be bypassed by fallback.
- Material-package recovery budgets are independent: ordinary network attempts, one provider
  output/rejection recovery, one quality repair, and one diversity regeneration must not consume or
  silently extend each other.
- Existing provider-rejection behavior is one durable recovery followed by deterministic approved
  catalog fallback. The catalog source must be a reference already reserved for the same artifact,
  selected in role order, validated, written once to private immutable storage, and projected with
  safe provenance only.
- A successful catalog fallback keeps the configured provider/model identity, records the actual
  catalog source in fallback provenance, and sets the package to `awaiting_manual_use`.
- Direct WeCom mode accepts `awaiting_manual_use`/`completed` packages and uses stable uniqueness so
  replay or concurrent reconciliation cannot create a duplicate formal job.
- Missing/corrupt catalog input or storage failure remains typed `review_required`/package failed.

## Compatibility rules

- Preserve valid URL, Base64, direct raster and documented task-envelope decoding.
- Preserve provider authentication/quota/rate-limit/transient classifications and bounded retry.
- Preserve OCR, generative quality audit, perceptual similarity and historical artifact behavior.
- Do not add a migration or change production API/OpenAPI wire types unless implementation evidence
  proves it unavoidable and the task is replanned first.

## Required verification

- Adapter tests use MockTransport/fakes; no live provider call in ordinary gates.
- Non-isomorphic tests must distinguish representation syntax failure from unsafe URL, bad raster
  signature, wrong dimensions and oversized output, proving only the intended failure class enters
  recovery.
- State-machine tests prove first recovery, second-failure fallback, no-asset/store failure,
  idempotent fingerprinting, lease fencing, no third provider call, one object/artifact and at most
  one delivery job.
- Safe diagnostic tests include a sentinel in fake provider content and prove it is absent from
  exceptions, logs, durable snapshots and HTTP projection.
- Final checks include Ruff format/lint, strict mypy, focused unit/contract/integration tests, full
  backend tests, Alembic uniqueness/no drift, production OpenAPI drift, diff hygiene and committed
  secret/private-path scans.
- Tests and implementation do not access production, Comfly, Zhipu, MinIO or WeCom. Deployment and
  replay/resend are separately authorized operations.
