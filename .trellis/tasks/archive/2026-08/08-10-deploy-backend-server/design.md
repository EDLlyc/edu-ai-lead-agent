# Backend Release Deployment Design

## Deployment boundary

This is an in-place upgrade of the existing single-host backend runtime. The server runs Docker
Compose for PostgreSQL, MinIO, the loopback API, acquisition, governance, content/image generation,
and the outbound Enterprise WeChat group-webhook dispatcher. There is no frontend, reverse proxy,
public API, inbound WeCom callback, or self-built-app recipient route.

The local workspace is a release source only. Its acquisition/content/governance/WeCom schedulers
and workers remain stopped while the server is the sole automatic producer and sender.

## Runtime layout

```text
/opt/edu-ai-lead-agent/                 pinned release checkout
  .env                                  production-only, mode 0600, never committed
  private/brand-materials/              Git-ignored release input, read-only in containers
  deployment-evidence/                  safe status summaries, no secrets

/var/backups/edu-ai/                    root-owned, mode 0700, local-only
  postgres/                             custom-format dumps and checksums
  minio/                                private bucket snapshots and checksums
  brand-materials/                      protected release-input backups and checksums
```

Compose named volumes retain PostgreSQL and MinIO data. The declared host bindings keep PostgreSQL,
MinIO API/console, and the API on `127.0.0.1`; schedulers, workers, and the dispatcher have no host
ports.

## Release and state flow

```text
GitHub a14847a + protected brand materials
        -> server staging/checksums
        -> pinned checkout and rebuilt backend images
        -> PostgreSQL/MinIO backup
        -> migration/seed completion
        -> acquisition -> governance -> content/image/package -> WeCom dispatcher
```

The server's existing database and object storage are authoritative for this incremental release.
The deployment preserves durable runs, source evidence, selected topics, packages, images, and
delivery jobs. It does not re-import local development state or delete rows based on timestamps.
If read-only preflight proves the server is not actually provisioned, the operator stops and uses
the archived clean-host bootstrap design as a separate reviewed path.

## Configuration contract

The existing server `.env` is backed up before edits and remains mode `0600`. The deployment checks
configuration by variable names and redacted status only. It must contain production values for
the AI/chat and image providers, the Comfly base URL/model settings, database and MinIO credentials,
the ten-day acquisition/content freshness settings, and the read-only brand manifest path.

The delivery settings are:

```dotenv
WECOM_ENABLED=true
WECOM_DELIVERY_PROVIDER=group_webhook
WECOM_AUTO_DELIVERY_ENABLED=true
WECOM_REQUIRE_REVIEW_BEFORE_SEND=false
```

The actual webhook key is written only to the protected server configuration. The group adapter
makes outbound HTTPS calls to the official webhook endpoint, sends the copy body before the image,
and records durable child/job state. It does not need a trusted domain, trusted IP, callback URL,
access token, recipient userid, or public listener.

## Rollout sequence

1. **Local release gate:** verify `a14847a`, Compose syntax, tests already associated with the
   release, private material checksum, and local automatic workers remain stopped.
2. **Server read-only preflight:** verify OS/Docker/Compose, disk/inodes, current checkout,
   container state, open listeners, firewall, backup timer, migration head, and safe queue counts.
3. **Durable backup:** stop API and all write-producing schedulers/workers/dispatcher; create
   PostgreSQL, MinIO, and brand-material backups under the server-local backup root with checksums.
4. **Stage release inputs:** fetch and detach checkout at `a14847a`; stage the 219 MiB brand
   directory, compare checksums, install it read-only, and preserve the previous copy for rollback.
5. **Build/configure:** validate Compose without printing resolved environment values, build the
   changed backend images, and update only the approved non-secret delivery flags while preserving
   provider secrets.
6. **Migrate/start:** keep durable infrastructure healthy, run `backend-migrate`, then start
   acquisition, governance, content, and WeCom profiles in that order.
7. **Verify/hand off:** inspect bounded logs and safe database states, verify automatic delivery
   reconciliation and no duplicate fingerprints, check backup timer/evidence, and retain the
   previous release reference.

## Failure handling and rollback

- A failed read-only preflight stops the rollout and leaves the server untouched.
- A failed backup, checksum, Compose config, build, or migration stops the rollout before the new
  workers or dispatcher start. The old checkout/images and durable volumes remain available.
- A failed application startup stops profiled schedulers/workers and the dispatcher first, keeps
  PostgreSQL/MinIO volumes, and restores the old checkout/configuration. A schema incompatibility
  uses the matching backup restore procedure; it never relies on an improvised Alembic downgrade.
- A delivery incident is isolated by stopping `wecom-dispatcher` or setting automatic delivery
  false. Queued, partial, and `delivery_unknown` jobs remain queryable; unknown provider results
  are never blindly resent.
- No rollback step uses `docker compose down -v`, broad `docker system prune`, direct business-row
  updates, or unbounded deletion.

## Resource and security trade-offs

The host is small and backend-only by design. Avoid frontend dependencies and public proxy services;
build only backend images and retain seven-day local backups. This reduces resource use but leaves
the host vulnerable to total-loss of its local backups, so off-host backup and SSH key hardening are
explicit deferred follow-ups.
