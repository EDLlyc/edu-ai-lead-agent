# PRODUCTION ENVIRONMENT CHECKLIST

Complete this checklist before enabling the full Compose profile set. Blank fields are intentional
placeholders. Do not enter real secrets in this file, commit a production `.env`, or paste secret
values into task logs.

## Release and host

- [ ] Release commit/image digests: `______________________________`
- [ ] Operator and maintenance window: `______________________________`
- [ ] Host OS/Docker/Compose versions recorded: `______________________________`
- [ ] System clock/NTP and `BUSINESS_TIMEZONE` verified: `______________________________`
- [ ] Disk capacity and inode alerts cover PostgreSQL, MinIO, logs, and backups.
- [ ] Firewall allows only required HTTPS and restricted administrator access.
- [ ] `docker compose config --quiet` passes for the exact release configuration.
- [ ] No floating image tags are used.

## Production configuration

Set values in the protected deployment secret store or an untracked permission-600 file. Leave
the value column blank in this checklist.

| Variable or setting                          | Production value location/status | Secret?         |
| -------------------------------------------- | -------------------------------- | --------------- |
| `APP_ENV=production`                         | `________________`               | No              |
| `APP_HOST` / API loopback binding            | `________________`               | No              |
| `APP_PORT` / public HTTPS origin             | `________________`               | No              |
| `BUSINESS_TIMEZONE`                          | `________________`               | No              |
| `DATABASE_URL`                               | `________________`               | Yes             |
| `GOVERNANCE_CHECKPOINT_DATABASE_URL`         | `________________`               | Yes             |
| `POSTGRES_DB` / `POSTGRES_USER`              | `________________`               | User/config     |
| `POSTGRES_PASSWORD`                          | `________________`               | Yes             |
| `MINIO_ENDPOINT` / private bucket            | `________________`               | Endpoint/config |
| `MINIO_ROOT_USER` / `MINIO_ACCESS_KEY`       | `________________`               | User/config     |
| `MINIO_ROOT_PASSWORD` / `MINIO_SECRET_KEY`   | `________________`               | Yes             |
| `AI_PROVIDER_MODE` / approved model versions | `________________`               | No              |
| `AI_PLATFORM_BASE_URL`                       | `________________`               | No              |
| `AI_PLATFORM_API_KEY`                        | `________________`               | Yes             |
| `IMAGE_PROVIDER_MODE` / image versions       | `________________`               | No              |
| `TOAPIS_API_KEY` or `COMFLY_API_KEY`         | `________________`               | Yes             |

- [ ] Every production credential differs from the local placeholders in `.env.example`.
- [ ] Secret files are outside Git, mode 600, readable only by the deployment account, and absent
      from container logs, crash reports, support tickets, and monitoring labels.
- [ ] `VITE_API_BASE_URL` points to the HTTPS reverse-proxy origin, never a development port.
- [ ] Provider/model/parser/scoring/policy versions are recorded with the release.

## Enterprise WeChat group-webhook route

Use this section only when the approved recipient is the official group webhook.

- [ ] `WECOM_ENABLED=true`.
- [ ] `WECOM_DELIVERY_PROVIDER=group_webhook`.
- [ ] `WECOM_GROUP_WEBHOOK_KEY` is present only in the protected secret store; checklist value is
      blank: `________________`.
- [ ] `WECOM_AUTO_DELIVERY_ENABLED` and `WECOM_REQUIRE_REVIEW_BEFORE_SEND` match the written
      rollout approval.
- [ ] `WECOM_MAX_ATTEMPTS`, lease, heartbeat, timeout, text, and image limits are bounded and
      recorded.
- [ ] Dispatcher egress to `https://qyapi.weixin.qq.com:443` is allowed with certificate
      verification and no redirect bypass.
- [ ] No inbound firewall rule, callback URL, trusted domain, trusted recipient API, or self-built
      application IP configuration was added for the group webhook.
- [ ] No `access_token`, webhook key, raw user ID, temporary media ID, signed URL, or provider body
      appears in logs, API responses, or delivery rows.
- [ ] Any real test is one visible `mode=test` job with a new idempotency fingerprint; no real
      provider message is sent during ordinary validation.
- [ ] Text-before-image child attempts, durable status, leases, and unknown-timeout behavior have
      been verified with safe fields only.

## Network and reverse proxy

- [ ] Public exposure is limited to the reverse proxy's HTTPS listener and the approved admin path.
- [ ] PostgreSQL `5432`, MinIO API `9000`, MinIO Console `9001`, API development port `8000`,
      Vite `5173`, schedulers, and workers are private or loopback-only.
- [ ] MinIO bucket is private; anonymous access is disabled; administrative console is not public.
- [ ] Reverse proxy serves the built `frontend/dist/` assets and forwards `/api/` and `/healthz`
      to the API over the private host/network.
- [ ] TLS certificate chain, renewal timer, expiry alert, HSTS/access policy, request limits, and
      forwarded host/proto handling are verified.
- [ ] HTTPS frontend and API origins match; no mixed-content or development Vite process remains.

## Startup and migration

- [ ] Pre-deployment PostgreSQL dump and MinIO snapshot/mirror completed.
- [ ] `postgres` and `minio` are healthy.
- [ ] `minio-init` completed successfully and the private bucket exists.
- [ ] `backend-migrate` completed successfully.
- [ ] Alembic head: `________________`.
- [ ] Seed source count and active versions verified without direct row edits.
- [ ] Frontend dependencies installed from `package-lock.json` and the production build published
      atomically.
- [ ] Base API, acquisition scheduler, and acquisition worker started after migration.
- [ ] `governance` profile was explicitly enabled where approved, and its scheduler/worker are
      healthy before starting content:

  ```bash
  docker compose --profile governance up -d --build governance-scheduler governance-worker
  ```

- [ ] `content` profile was explicitly enabled where approved, after upstream health/liveness was
      verified:

  ```bash
  docker compose --profile content up -d --build content-scheduler content-worker
  ```

- [ ] `wecom` profile was explicitly enabled only after upstream stages and the delivery policy were
      verified:

  ```bash
  docker compose --profile wecom up -d --build wecom-dispatcher
  ```

- [ ] API, scheduler, worker, and dispatcher health/liveness is recorded; disabled domain stages
      are labeled as intentional domain configuration, not infrastructure failure.
- [ ] API and content worker share the same `IMAGE_MAX_ATTEMPTS` value.

## Backups, monitoring, and retention

- [ ] PostgreSQL backup command, encrypted destination, checksum, and retention: `________________`.
- [ ] MinIO backup/snapshot destination includes source snapshots, brand references, generated
      images, and metadata: `________________`.
- [ ] A clean restore destination and restore operator are assigned.
- [ ] Restore drill date/result: `________________`.
- [ ] Alerts cover `/healthz`, proxy errors, container exits/restarts, queue age, failed jobs,
      lease expiry, `delivery_unknown`, database/MinIO capacity, backup age, and TLS expiry.
- [ ] Log retention and access controls are approved; exported diagnostics are redacted.
- [ ] Domain outcomes such as `no_topic`, `review_required`, and disabled stages are separated
      from infrastructure failures in the on-call dashboard.

## Upgrade and rollback gate

- [ ] Previous image/configuration bundle and migration compatibility are available.
- [ ] Rollback owner and stop order are recorded: workers/schedulers/dispatcher first, durable
      volumes preserved.
- [ ] Rollback does not rely on an unreviewed Alembic downgrade or direct business-row edits.
- [ ] Reconciliation incident control is understood: stop `wecom-dispatcher` or disable automatic
      delivery, preserve queued/unknown jobs, and never resend an unknown provider outcome blindly.
- [ ] First-day verification evidence directory: `________________`.
- [ ] Final operator sign-off: `________________` / date `________________`.
