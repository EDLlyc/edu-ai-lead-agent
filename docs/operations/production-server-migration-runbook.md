# Production Server Migration Runbook

This runbook deploys the pinned Compose services on one production host. It assumes a reviewed
release bundle, a protected secret store, persistent PostgreSQL and MinIO storage, and an operator
who can stop the workers during maintenance. It does not publish to Moments or any other social
platform.

## Operating boundaries

- Expose only the frontend and API through the host reverse proxy on HTTPS.
- Keep PostgreSQL, MinIO API, MinIO Console, schedulers, and workers on the private host/network.
- The official Enterprise WeChat group webhook is outbound-only HTTPS. It needs no inbound
  callback URL, trusted domain, trusted recipient API, or self-built-app IP allowlist.
- The API creates durable WeCom jobs. Only `wecom-dispatcher` calls the provider, sends Markdown
  before image, preserves leases/idempotency, and records safe status/error codes.
- Never put credentials, access tokens, webhook keys, raw provider bodies, signed object URLs, or
  private MinIO object keys in source control, logs, tickets, backups shared outside the operator
  boundary, or monitoring payloads.

## Prerequisites

1. Provision a supported Linux host with Docker Engine/Compose, a firewall, UTC system time with
   the configured business timezone available, and enough disk for PostgreSQL, MinIO, logs, and
   at least one complete backup set.
2. Install a host reverse proxy with a certificate renewal mechanism. The proxy must forward
   `/api` and `/healthz` to the loopback API port and serve the built frontend assets.
3. Prepare a release directory containing the pinned repository commit, `compose.yaml`, backend and
   frontend lockfiles, `private/brand-materials/`, and the approved production configuration.
   The brand directory is bind-mounted read-only into containers that run as the non-root `app`
   user. Preserve the operator as the host owner, but make the directory and files readable by
   that container user (for example, directories `0755` and files `0644`, with no write bit for
   other users); a copied `0600` manifest will make visual-asset selection fail at runtime.
4. Place production values in a permission-restricted deployment secret store or an untracked
   permission-600 `.env`. Start from the names in `.env.example`, but never copy its development
   credentials into production and never commit the production file.
5. Confirm the database and MinIO backup destinations, retention period, restore operator, alert
   recipients, maintenance window, and rollback bundle before changing the host.

After copying the private materials, verify the effective bind-mount access as the application
user before starting content workers:

```bash
find private/brand-materials -type d -exec chmod 0755 {} +
find private/brand-materials -type f -exec chmod 0644 {} +
docker compose run --rm --no-deps --entrypoint python content-worker -c \
  'from pathlib import Path; Path("private/brand-materials/visual-assets.manifest.json").read_text()'
```

The material files must remain non-writable to the container. Do not solve a read failure by
making the bind mount writable or by running the application containers as root.

## Configuration and secret placement

Set `APP_ENV=production`, a non-placeholder `DATABASE_URL` and
`GOVERNANCE_CHECKPOINT_DATABASE_URL`, non-placeholder MinIO credentials, the public
`VITE_API_BASE_URL`, and the approved versioned pipeline/provider settings. Keep database and
object-storage endpoints on the Compose network, for example `postgres:5432` and `minio:9000`,
unless the deployment uses separately managed private services.

For the group-webhook route, set:

```dotenv
WECOM_ENABLED=true
WECOM_DELIVERY_PROVIDER=group_webhook
WECOM_GROUP_WEBHOOK_KEY=<secret-store-value>
WECOM_AUTO_DELIVERY_ENABLED=true
WECOM_REQUIRE_REVIEW_BEFORE_SEND=<review-policy-value>
```

The placeholder above is documentation only. The real key belongs only in the deployment secret
store. Do not set a self-built-app `WECOM_CORP_SECRET` or a raw `WECOM_DEFAULT_RECIPIENT_ID` for a
group-webhook deployment unless another separately reviewed route requires it. Allow the
dispatcher host to resolve and reach `qyapi.weixin.qq.com:443`; no inbound provider connection
is expected.

Keep `WECOM_REQUIRE_REVIEW_BEFORE_SEND=true` unless the direct-delivery policy has been explicitly
approved. Direct mode still requires passed copy validation/audit, image validation, configured
image audit acceptance when enabled, and immutable private image metadata. Do not bypass those
checks to make a package deliverable.

## Migration and startup order

Run commands from the release directory. Save command summaries and safe status values, never
environment dumps or credential-bearing command output.

1. Verify the release and configuration without starting application workers:

   ```bash
   git rev-parse --verify HEAD
   docker compose config --quiet
   docker compose config --services
   ```

2. Take the pre-deployment PostgreSQL and MinIO backups described below. Confirm their checksums
   and that the restore destination is available.

3. Start durable infrastructure and wait for health checks:

   ```bash
   docker compose up -d postgres minio
   docker compose ps --all postgres minio
   ```

4. Initialize the private bucket, then run the one-shot migration/seed service. The service's
   command is intentionally ordered as `alembic upgrade head` followed by
   `python -m app.seed_sources`; do not seed before a successful migration:

   ```bash
   docker compose up -d minio-init
   docker compose wait minio-init
   docker compose run --rm backend-migrate
   docker compose ps --all backend-migrate
   ```

   Verify the expected Alembic revision and active source count before starting workers:

   ```bash
   docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
     -c 'SELECT version_num FROM alembic_version;'
   docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
     -c "SELECT count(*) FROM sources WHERE active_version_id IS NOT NULL;"
   ```

   The migration head is release-specific; record the value from the release manifest rather
   than assuming a future revision. Do not mutate business rows or repair historical packages by
   hand during migration.

5. Build the frontend in the release workspace with the public HTTPS API origin, then publish the
   resulting `frontend/dist/` directory atomically to the reverse-proxy document root:

   ```bash
   npm ci --prefix frontend
   npm run build --prefix frontend
   ```

6. Start the API and acquisition processes after migration succeeds:

   ```bash
   docker compose up -d --build acquisition-api acquisition-scheduler acquisition-worker
   ```

7. Start the governance profile explicitly. A clean host does not start this profile unless it is
   named:

   ```bash
   docker compose --profile governance up -d --build governance-scheduler governance-worker
   ```

   Enable the corresponding `GOVERNANCE_*` settings before this step and verify scheduler/worker
   liveness. If governance is intentionally disabled, leave its profile stopped and record the
   domain result as disabled rather than calling it an infrastructure failure.

8. Start the content profile after the upstream acquisition/governance state is healthy:

   ```bash
   docker compose --profile content up -d --build content-scheduler content-worker
   ```

   Enable the `CONTENT_*` and `IMAGE_*` settings before this step and verify the content scheduler
   and worker liveness. A disabled content stage is a recorded domain configuration result, not an
   infrastructure failure.

### Three-slot preparation and staged rollout

The legacy daily Top 1 path remains active while `CONTENT_SLOT_MODE_ENABLED=false`. A slot target is
the earliest delivery time, not generation start: acquisition is scheduled at target minus
`CONTENT_SLOT_PREPARE_LEAD_MINUTES` (default 90), and delivery closes after
`CONTENT_SLOT_DELIVERY_LATE_MINUTES` (default 60). Keep the mode and all three slot switches false
during an ordinary upgrade.

Before enabling a slot, use read-only checks to confirm the exact scheduled acquisition and its
terminal governance lineage, then inspect the edition without exposing content or object keys:

```bash
curl -fsS 'https://<public-host>/api/v1/content-editions/<yyyy-mm-dd>?profile=preview'
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c \
  "SELECT business_date, content_slot, status, selected_count, unfilled_count, error_code
     FROM content_slot_runs ORDER BY created_at DESC LIMIT 12;"
```

An authorized operator may enqueue a bounded replay only after readiness is verified:

```bash
curl -fsS -X POST 'https://<public-host>/api/v1/content-slot-runs' \
  -H 'Content-Type: application/json' \
  --data '{"business_date":"<yyyy-mm-dd>","content_slot":"morning"}'
```

Roll out one switch at a time. Enable morning first and require two completed windows with no
duplicate event, incorrect send, or `delivery_unknown`. Then enable noon and require two completed
morning+noon days with cross-slot deduplication. Enable evening only after the same evidence passes.
At every stage verify one package per selected item, `not_before`/`expires_at`, and the persisted
window `next_allowed_at` gap; never infer delivery from log timing alone.

To stop new slot scheduling, set `CONTENT_SLOT_MODE_ENABLED=false` (or the affected slot switch
false) and restart schedulers/workers. Do not delete slot rows or move late packages into another
slot. Before reverting to legacy daily scheduling, verify no slot selection, copy, image, or
delivery job is running and no delivery window remains open. Stop automatic delivery immediately
on an unknown result; `delivery_unknown` and expired jobs are audit records and must never be
automatically resent.

9. Start the WeCom dispatcher only after the upstream stages are healthy and the delivery policy has
   been reviewed:

   ```bash
   docker compose --profile wecom up -d --build wecom-dispatcher
   ```

   Enable the `WECOM_*` settings before this step. Verify that automatic reconciliation is enabled
   only for the approved policy; otherwise leave the dispatcher stopped or record it as disabled.

10. Configure/reload the reverse proxy only after the API health check succeeds. Expose HTTPS and,
    if required, redirect HTTP to HTTPS. Do not expose host ports `5432`, `9000`, `9001`, `8000`,
    `5173`, scheduler ports, or worker ports to the public network.

## Reverse proxy and TLS

The proxy should serve the static frontend and forward `/api/` and `/healthz` to the API's
loopback binding. Preserve the original host/proto headers, enforce request/body/time limits
appropriate for the API, and require the deployment's authentication/access-control policy. TLS
private keys remain in the proxy's protected certificate store. Renew certificates before expiry
and alert on renewal failure. The browser must use an HTTPS `VITE_API_BASE_URL`; do not mix an HTTPS
page with an HTTP API or expose a development Vite server.

The proxy is not an Enterprise WeChat callback endpoint. The group webhook provider only makes
outbound requests from the dispatcher to the official HTTPS webhook host.

## Backups and restore

Back up PostgreSQL and MinIO independently because database rows reference immutable image and
source artifacts.

### PostgreSQL backup

Run before every migration and on the scheduled backup cadence. Keep the dump encrypted at rest,
outside the application host where possible, with a checksum and retention label:

```bash
mkdir -p /var/backups/edu-ai/postgres
docker compose exec -T postgres pg_dump \
  -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc \
  > /var/backups/edu-ai/postgres/edu-ai-<utc-timestamp>.dump
sha256sum /var/backups/edu-ai/postgres/edu-ai-<utc-timestamp>.dump \
  > /var/backups/edu-ai/postgres/edu-ai-<utc-timestamp>.dump.sha256
```

Do not print `DATABASE_URL`, passwords, or a full environment when collecting backup evidence.

### MinIO backup

Use an authenticated, encrypted MinIO mirror, an object-storage replication target, or a
filesystem snapshot of `minio_data` approved by the storage operator. Include the immutable
source snapshots, brand references, generated images, and their metadata. Verify object counts and
checksums without making the bucket public. A database-only restore is incomplete.

### Restore drill

1. Put the application in maintenance mode and stop schedulers, workers, and the WeCom dispatcher
   first. Preserve the original volumes and the queued/unknown delivery records.
2. Restore PostgreSQL into a reviewed target using the matching release's `pg_restore` procedure;
   do not run ad hoc row updates. Restore MinIO objects from the matching backup/snapshot and
   verify the private bucket and immutable object descriptors.
3. Start `postgres`/`minio`, run only the compatible migration and seed steps, then verify the
   migration head, source registry, package/image counts, and `/healthz`.
4. Start API, schedulers, and workers in the order above. Reconcile durable queues from their
   persisted state. Treat `delivery_unknown` as requiring operator review; do not resend it
   automatically.
5. Record restore duration, backup IDs/checksums, safe row/object counters, and any gaps. Run a
   scheduled restore drill at least once per quarter or after a backup architecture change.

## Monitoring and retention

Use structured application logs and durable tables as the source of truth. Monitor:

- external HTTPS `/healthz`, reverse-proxy 4xx/5xx rates, certificate expiry, and container
  restart/exit state;
- acquisition, governance, topic-selection, copy/image, material-package, and WeCom queue age,
  terminal failures, lease expiry, attempt counts, and `delivery_unknown` jobs;
- PostgreSQL and MinIO disk capacity, database connection saturation, bucket health, backup age,
  backup checksum/replication status, and restore-drill success;
- provider latency, safe response codes, bounded retry counts, and configured model/image budget
  usage without request bodies, tokens, webhook keys, signed URLs, or private object paths.

Retain logs and backups according to the approved data-retention policy. Redact content and
credentials before exporting diagnostics. A valid `no_topic`, `review_required`, disabled stage,
or other typed terminal domain result must be reported separately from service unavailability.

## Upgrade

1. Announce the maintenance window, confirm a tested rollback bundle, and take both backups.
2. Capture the current image digests, git commit, environment version, migration head, health
   state, queue counters, and active profile list.
3. Stop profiled workers/schedulers and the WeCom dispatcher; keep PostgreSQL/MinIO volumes and
   the current API available only as the maintenance policy allows.
4. Deploy the new pinned images/configuration, run `docker compose config --quiet`, then run the
   migration/seed order above. Never use floating image tags.
5. Start API, health-check it, publish the frontend, then start acquisition, governance, content,
   and WeCom profiles in the documented order, waiting for upstream health before starting the next
   profile. Verify that `IMAGE_MAX_ATTEMPTS` is identical in API/content-worker configuration before
   accepting an image retry.
6. Perform first-day verification and retain safe evidence. Do not run a real provider delivery
   as part of an ordinary upgrade unless the production checklist has authorized one visible
   `mode=test` request and the fingerprint has not already been delivered.

## Rollback and incident controls

If the new application or dispatcher is unhealthy, stop the profiled workers first and preserve
the database/MinIO volumes. Restore the previous pinned image/configuration bundle and run only
the compatible migration and health steps. Do not downgrade Alembic by guesswork; a forward schema
change that is incompatible with the previous image requires the approved database restore or a
versioned rollback migration plan.

For a reconciliation regression, stop `wecom-dispatcher` or set
`WECOM_AUTO_DELIVERY_ENABLED=false`, then leave queued/partial/unknown jobs queryable for operator
handling. A provider timeout remains `delivery_unknown`; never resend blindly. Re-enable the
dispatcher only after the candidate query, quality gates, and idempotency behavior have been
verified.

## First-day verification

Record the following with secrets and private paths omitted:

```bash
docker compose --profile governance --profile content --profile wecom ps --all
curl -fsS https://<public-host>/healthz
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c 'SELECT version_num FROM alembic_version;'
docker compose logs --tail=100 acquisition-api acquisition-scheduler acquisition-worker \
  governance-scheduler governance-worker content-scheduler content-worker wecom-dispatcher
```

Check that all intended services are running, one-shot `minio-init` and `backend-migrate` have
completed successfully, no public route reaches PostgreSQL/MinIO, source and queue counters move,
and the API exposes no credential or private object location. Validate delivery with durable job
state and child-attempt ordering; do not infer success from a provider log line alone.
