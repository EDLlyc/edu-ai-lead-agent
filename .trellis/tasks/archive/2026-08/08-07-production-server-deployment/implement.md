# Production Server Deployment Implementation Plan

## Preflight

1. Record local release commit, local Compose service status, Alembic revision, safe table/object
   counts, and available disk space without displaying secrets. Preserve all observed durable rows;
   do not classify or delete packages by timestamp during migration.
2. Stop local schedulers, workers, and dispatcher while creating the migration export; leave the
   source PostgreSQL and MinIO data intact. Restart them if server migration is cancelled.
3. Install Docker Engine, the Docker Compose plugin, and UFW on Ubuntu 24.04 from Docker's signed
   apt repository. Add `ubuntu` to the `docker` group.
4. Configure UFW to allow and rate-limit SSH only. Do not open HTTP, HTTPS, PostgreSQL, MinIO, or
   API ports. Verify the cloud security group likewise exposes only SSH.
5. Create `/opt/edu-ai-lead-agent` for the pinned release and `/var/backups/edu-ai` with root-only
   access. Clone the repository and checkout the recorded immutable commit.

## Configure Production Inputs

1. Copy `private/brand-materials/` to the release directory without committing it. Verify the
   visual-assets manifest exists and has no world-writable paths.
2. Create `.env` with mode `0600` using new PostgreSQL and MinIO passwords. Apply the existing
   approved production provider and group-webhook settings from the protected local configuration
   without displaying their values.
3. Set `APP_ENV=production`, `BUSINESS_TIMEZONE=Asia/Shanghai`, all three pipeline stages enabled,
   image generation enabled, the group-webhook provider, automatic delivery enabled, and review
   disabled. Keep all public-facing ports loopback-only as Compose declares.
4. Run `docker compose config --quiet` and inspect only service names and resolved port bindings.

## Export and Import Clean State

1. Export PostgreSQL with `pg_dump -Fc`, calculate a checksum, and copy it through the protected
   SSH channel to a server staging path with restricted permissions.
2. Export the current private MinIO bucket with the MinIO client into a temporary migration
   directory, record its file/object count, and copy it through the protected SSH channel.
3. Start server `postgres` and `minio`; wait for health checks, then restore PostgreSQL with
   `pg_restore --clean --if-exists --no-owner` into the newly created database.
4. Start `minio-init`, mirror the staged bucket contents into the private server bucket, and
   verify its object count against the export.
5. Run `backend-migrate`; verify its success, the Alembic revision, and seeded source count.
   Remove only the verified server staging copy after the import succeeds.

## Start and Verify Automation

1. Start the base acquisition services, then `governance`, `content`, and `wecom` profiles in the
   order defined in the design.
2. Verify every intended service is running; inspect bounded recent logs for errors without
   revealing secrets.
3. Verify `127.0.0.1` is the only host binding for PostgreSQL, MinIO, and the API; confirm UFW
   exposes no application ports.
4. Verify the existing scheduled topic/delivery history exists and that duplicate-topic state is
   preserved. Do not manufacture an extra daily selection or send a duplicate business message.
5. Confirm the dispatcher configuration can reach Enterprise WeChat only with a safe provider
   health/status check. A visible delivery is made only by the next valid daily material package.

## Backups and Handover

1. Install a root-owned backup script and systemd service/timer. It creates daily PostgreSQL,
   MinIO, and brand-material backups beneath `/var/backups/edu-ai`, checksums them, and retains
   seven days.
2. Run one backup manually and verify the expected files, permissions, checksum, and timer state.
3. Record deployed commit, running services, migration revision, backup timer status, safe state
   counters, and rollback commands in a server-local evidence file with no secrets.
4. Retain SSH password login by user decision. Schedule a separate key-based SSH hardening task;
   do not change authentication settings during this deployment.

## Validation Commands

```bash
docker compose config --quiet
docker compose --profile governance --profile content --profile wecom ps --all
docker compose exec -T postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c 'SELECT version_num FROM alembic_version;'
docker compose exec -T minio sh -c 'curl --fail --silent http://127.0.0.1:9000/minio/health/live >/dev/null'
systemctl status edu-ai-backup.timer --no-pager
```

## Rollback Points

- Before import: stop and remove only the newly created server Compose services; retain source
  data unchanged.
- After import but before application startup: stop application services and restore the matching
  import artifacts; never use `docker compose down -v`.
- After startup: stop schedulers, workers, and dispatcher first, preserve the database and object
  volumes, and investigate from safe logs and evidence before any restore.
