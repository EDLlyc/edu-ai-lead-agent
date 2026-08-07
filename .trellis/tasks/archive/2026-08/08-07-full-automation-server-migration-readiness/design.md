# Technical Design

## Boundaries

The change stays within the existing process boundaries:

```text
authoritative source fetch
  -> acquisition scheduler/worker -> PostgreSQL + MinIO snapshots
  -> governance scheduler/worker -> governed facts/events/evidence
  -> content scheduler/worker -> daily topic -> brand retrieval -> copy validation/audit
  -> image generation/validation -> private MinIO artifact
  -> material package snapshot
  -> WeCom API enqueue -> independent dispatcher -> official group webhook
```

The API and workers remain the only owners of durable state transitions. Provider calls remain
outside database transactions. The dispatcher remains the only owner of the WeCom side effect.

## Reconciliation Fix

Automatic reconciliation currently scans every ready package on every poll and lets the final
enqueue guard reject a legacy package that lacks image quality snapshots. That is correct for the
individual enqueue request but incorrect as a polling strategy.

The reconciliation query will become a candidate query rather than a broad status scan:

1. Exclude packages that already have any durable delivery job. Existing delivered, failed, partial,
   and unknown jobs remain available for their existing API status and explicit retry behavior.
2. In direct mode, require the persisted package copy validation/audit prerequisites and the image
   success plus configured/passed image validation prerequisites that the direct quality gate needs.
   Keep the Python quality gate and immutable image metadata check as the final race-safe guard.
3. Keep review-required mode's approved-package predicate unchanged.
4. If a state race still produces a typed conflict, emit a safe, bounded skip event rather than
   retrying/logging the same unchanged package every two seconds. The dedupe key is package ID plus
   the relevant readiness state, so a later validation/audit/status change is reconsidered.

This requires no database migration and does not mutate historical packages. The old package stays
visible as an inspectable invalid artifact; it simply stops being a candidate for automatic direct
delivery. The query and dedupe behavior will be covered with an in-memory service test and a real
PostgreSQL query/worker check where available.

## Real Acceptance Run

Use `backend/app/preview_run.py` with a new unused business date and a unique output root. After a
successful package is returned, create exactly one `mode=test` group-webhook delivery through the
public API and poll its durable job until `delivered`, `failed`, or `delivery_unknown`. The test
marker makes the external message distinguishable. Reconciliation must return the same job on a
second pass and must not create a duplicate row.

The output manifest is the evidence boundary. It may contain IDs, statuses, versions, safe issue
codes, source links/titles, copy text intended for the internal preview, and local image metadata;
it must not contain credentials, raw provider bodies, signed CDN URLs, access tokens, webhook keys,
or private MinIO object paths.

## Server Deployment Shape

The production host runs the same Compose services from rebuilt, pinned images. PostgreSQL and
MinIO use persistent volumes and bind only to loopback/private network interfaces. API traffic is
served through a host reverse proxy with TLS and authentication; the frontend is built as static
assets and served by the proxy, with `/api` forwarded to the API container. Schedulers and workers
are not exposed as network services.

The runbook will define this order:

```text
backup -> pull/build images -> postgres/minio -> minio-init -> backend-migrate -> API
  -> acquisition -> governance/content profiles -> wecom profile -> health/queue checks
```

The group webhook only requires outbound HTTPS from the dispatcher. Database and object storage
backups are separate: `pg_dump`/restore for PostgreSQL and an authenticated MinIO mirror or volume
backup for immutable artifacts. Rollback uses the previous image/config bundle; migration downgrade
is not an ad hoc recovery procedure.

## Compatibility and Rollback

- No schema change is expected for the reconciliation fix.
- Existing self-built-app delivery remains supported and is selected by configuration.
- If the group provider or a new image fails in production, disable automatic WeCom delivery or
  switch provider configuration, then preserve the queued/unknown job for operator handling.
- If a deployment fails, stop profiled workers first, retain data volumes, restore the previous image
  bundle, and run only the documented compatible migration/health steps.

## Observability

The runbook will use existing structured logs and durable tables as the source of truth, with an
external health check for `/healthz`, container restart alerts, queue-age/failed-job queries, disk
capacity alerts for PostgreSQL/MinIO, and scheduled backup restore drills. Secrets and full content
remain excluded from logs and monitoring payloads.
