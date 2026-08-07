# Production Server Deployment Design

## Deployment Boundary

The Ubuntu server is a single-host, backend-only runtime. Docker Compose runs PostgreSQL, MinIO,
the loopback-only API, acquisition services, governance services, content services, and the
Enterprise WeChat group-webhook dispatcher. There is no frontend, reverse proxy, public HTTP
route, inbound Enterprise WeChat callback, or self-built-app recipient route.

The `ubuntu` operator account retains password SSH access by explicit decision. UFW permits only
SSH and rate-limits repeated connection attempts. This is a transition configuration, not a
substitute for later key-only SSH and cloud security-group CIDR restrictions.

## Runtime Layout

```
/opt/edu-ai-lead-agent/             pinned Git release; owned by ubuntu
  .env                              production-only mode 0600; never committed
  private/brand-materials/          copied release input; Git-ignored; read-only in containers
  compose.yaml

/var/backups/edu-ai/                root-owned, mode 0700
  postgres/                         compressed custom-format PostgreSQL dumps plus checksums
  minio/                            private-bucket snapshots plus checksums
  brand-materials/                  release-input backup plus checksums
```

Docker named volumes retain PostgreSQL and MinIO data. Ports for PostgreSQL, MinIO, MinIO Console,
and the API remain bound to `127.0.0.1`, as declared by Compose. Schedulers, workers, and the
dispatcher do not listen on host ports.

## Configuration Contract

The deployment creates a protected production `.env` owned by `ubuntu` with mode `0600`.
PostgreSQL and MinIO credentials are freshly generated on the server. It carries the approved
production model, image, and Enterprise WeChat group-webhook values without writing them to Git,
task artifacts, shell history, or logs. Direct group delivery stays enabled only after validation
has completed, with `WECOM_DELIVERY_PROVIDER=group_webhook`, auto delivery enabled, and review
disabled as approved. Existing copy, image, package, audit, idempotency, and retry gates remain
unchanged.

The release is pinned to the local `main` commit selected during deployment rather than tracking a
moving remote branch. The server receives the same commit through Git checkout and records the
commit hash in its deployment evidence.

## State Migration

The local runtime is the authoritative baseline. Transfer occurs while its Compose workers are
stopped so the database dump and object snapshot describe one consistent point in time. The
preflight found several durable packages and formal delivery rows without a typed test marker;
the migration therefore preserves all rows and matching objects. It does not perform timestamp-
based deletion or direct business-row cleanup.

1. Start clean server PostgreSQL and MinIO with their new named volumes.
2. Restore a PostgreSQL custom-format dump into the empty server database using `pg_restore`.
3. Create the private MinIO bucket and mirror the corresponding local bucket objects into it using
   the official MinIO client image, not a raw volume copy.
4. Copy `private/brand-materials/` with ownership and permissions appropriate for the read-only
   Compose bind mount.
5. Run the release migration and source seeding service. It must succeed before application
   workers start.

This preserves the 2026-08-07 scheduled selection and delivery history, so duplicate-topic
suppression continues on the server. The prior manual tests have already been deleted locally and
are not transferred.

## Startup and Delivery Sequence

After state restoration, startup is strictly ordered:

1. `postgres`, `minio`, and `minio-init` become healthy.
2. `backend-migrate` completes migrations and source seeding.
3. `acquisition-api`, `acquisition-scheduler`, and `acquisition-worker` start.
4. The `governance` profile starts and its scheduler/worker are checked.
5. The `content` profile starts and its scheduler/worker are checked.
6. The `wecom` profile starts only after preceding services are healthy. It makes outbound HTTPS
   calls to the official group webhook; it accepts no external callback.

Validation uses container health, safe database counts/revisions, MinIO object counts, and a
single controlled end-to-end run only if it cannot duplicate a real business delivery. It never
logs environment values or webhook credentials.

## Backup and Restore

A root-owned systemd timer runs daily after the content/delivery window. It uses Compose commands
to create a custom PostgreSQL dump, mirror the private MinIO bucket to a dated directory, and
archive the brand materials. Each output has a SHA-256 checksum. Backups older than seven days
are removed only inside `/var/backups/edu-ai` after verifying the exact path.

Restore stops schedulers, workers, and the dispatcher first; preserves the current volumes; then
restores matching PostgreSQL, MinIO, and brand-material backup sets. Any `delivery_unknown` state
remains unresolved and is never resent automatically. Local-only backups protect against ordinary
operator errors but not full server loss; off-host backup is deferred.

## Rollback

Before changing the server, record the selected Git commit, Compose configuration result, empty
volume state, and imported backup checksums. If application startup fails, stop only application
services, retain the durable volumes and evidence, and restore the matching PostgreSQL/MinIO/brand
set. Do not execute destructive volume removal, Alembic downgrade, or direct business-row edits.
