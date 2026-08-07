# Full Automation Acceptance Evidence

Date: 2026-08-07 (Asia/Shanghai)

## Safety boundary

- This evidence contains no provider credentials, webhook keys, signed URLs, raw provider bodies,
  or private MinIO object keys.
- The run used the configured group-webhook route only. It did not publish to Moments or another
  social platform.
- No database rows were edited directly and no volumes were reset.

## Isolated real run

- Preview output: `output/preview/full-automation-20260807/`
- Redacted manifest: `output/preview/full-automation-20260807/latest.json`
- Generated image: `output/preview/full-automation-20260807/52fa9292-06b3-41c2-a79c-4bf7fda9bce6/image-52fa9292-06b3-41c2-a79c-4bf7fda9bce6.png`
- Business date: `2026-08-09`
- Overall preview status: `ready`
- Stage statuses: acquisition `completed`; governance `completed` with domain status
  `partially_succeeded`; topic selection `completed`; copy generation `completed`; material
  package/image `completed`.
- Selected topic: `安徽启动人工智能专项技能培训`
- Selection result: `selected`, score `0.7580941`, threshold `0.62`.
- Copy validation: passed. Copy audit: accepted. The configured copy policy treats the emoji and
  length targets as warnings, not hard rejection conditions.
- Image: `succeeded`, `image/png`, `1024x1024`, `1446961` bytes, image validation passed.
- Image quality audit: not configured in this local run; this is reflected in the manifest and is
  not treated as a fabricated pass.

## WeCom delivery

- The enabled automatic dispatcher created one formal delivery for the newly eligible package;
  it reached `delivered`.
- One visible `mode=test` delivery was then enqueued through the public API and reached
  `delivered`.
- Test delivery child attempts were persisted in this order: `text/succeeded/0`, then
  `image/succeeded/0`.
- Test delivery attempt count: `1`; the replayed identical enqueue request returned the existing
  job ID and did not create another row.
- The delivery query showed two jobs for this package, one automatic formal job and one explicit
  test job. Both were delivered once; the test job was not retried.

## Runtime checks

- Compose profiles `governance`, `content`, and `wecom` were explicitly enabled.
- API, schedulers, workers, and dispatcher were running; PostgreSQL and MinIO were healthy.
- One-shot `backend-migrate` and `minio-init` exited successfully.
- API health check passed.
- Alembic head: `20260805_0018`.
- `make backend-check`: passed, `495 passed`.
- `make frontend-check`: passed, including OpenAPI drift, formatting, lint, typecheck, 27 frontend
  tests, and production build.
- `make doctor`: passed, including pgvector, schema, active source, MinIO, and shared image retry
  limit checks.
- `docker compose --profile governance --profile content --profile wecom config --quiet`: passed.
- `git diff --check`: passed.

## Test determinism follow-up

The full backend suite initially exposed two existing integration-test assumptions: fixture dates
were evaluated against the wall clock despite the ten-day freshness policy, and one test depended
on another test having seeded the source registry. The tests now inject a fixed fixture clock and
seed their own source registry. Production acquisition behavior was not changed; the final full
suite passed.
