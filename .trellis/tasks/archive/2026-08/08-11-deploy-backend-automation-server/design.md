# Backend release deployment design

## Boundary

This is an in-place backend-only upgrade of the existing single-host Compose runtime. The local
workspace supplies the pinned tracked release; PostgreSQL, MinIO, the server `.env`, private brand
materials, and durable queue state remain authoritative on the host. The frontend and all public
HTTP exposure remain out of scope.

## Runtime and state layout

```text
/opt/edu-ai-lead-agent/                 existing Compose runtime
  .env                                  production-only, mode 0600, preserved
  private/brand-materials/              existing read-only application input
  /var/lib/edu-ai/                      redacted operational evidence

/var/backups/edu-ai/                    server-local protected backups
  postgres/                              custom-format dump + checksum
  minio/                                 private object/data snapshot + checksum
  brand-materials/                       protected input backup + checksum
```

The preflight resolves the actual Compose project name and volume names before the upgrade. The
release is staged separately, then activated in the existing runtime directory so Compose does not
silently create new volumes. The protected `.env`, brand directory, and evidence directory are
excluded from the tracked release transfer.

## Release transfer

The local release is exactly `a29588b`, not `origin/main`. Create an allowlisted, path-filtered
tracked archive from that commit, transfer it over the authenticated SSH channel, and verify the
commit hash and archive checksum on the host. A raw full-tree archive or Git bundle is insufficient:
the pinned commit contains tracked report artifacts that must not enter this backend-only release.
Activate the filtered archive through a separately reviewed staging/activation path in the
existing runtime directory; do not treat it as a Git checkout or fetch/detach from it. Never use
`git clean`, copy the local `.env`, private material payloads, current task files, or reports.

## Rollout sequence

1. Run local release checks and confirm local automatic processes are stopped.
2. Run server read-only preflight: OS/Docker/Compose, disk/inodes, runtime/volumes, active
   profiles, migration head, safe counts, listeners/firewall, backup timer, and manifest checksum.
3. Stop write-producing API/schedulers/workers/dispatcher while retaining PostgreSQL and MinIO.
4. Create and verify fresh server-local backups; record only safe identifiers and checksums.
5. Stage and activate the pinned release while preserving `.env`, brand materials, and evidence.
6. Validate Compose, build backend services, start PostgreSQL/MinIO and `minio-init`, then run
   `backend-migrate` and verify the unchanged head `20260807_0019`.
7. Restart previously active base, governance, content, and WeCom services in dependency order.
   Do not start a profile that the preflight found intentionally stopped.
8. Verify health, service stability, manifest access, timeout configuration, network bindings,
   safe queues, and release evidence. Do not enqueue or send a test message.

## Configuration contract

The server `.env` is read and edited only through redacted, allowlisted checks. Existing provider
keys, Comfly base URL/model, database/MinIO credentials, brand manifest path, and WeCom settings
are preserved. The two approved non-secret image wait settings are explicitly normalized to
`IMAGE_PROVIDER_TIMEOUT_SECONDS=300` and `IMAGE_PROVIDER_WINDOW_SECONDS=300`; no other setting is
changed, and no secret is inferred from local development values.

## Verification and rollback

The release is healthy only when all intended long-lived containers are up without restart loops,
the API health check succeeds, the migration head is unchanged, and safe logs show no startup
failure. A failed preflight, backup, Compose render, build, migration, or health check stops the
rollout. Roll back by stopping application profiles first, restoring the previous checkout/image
reference and configuration, and preserving volumes. Never downgrade Alembic by guesswork or
delete durable rows/volumes.

If the active WeCom dispatcher reports a provider or unknown delivery state during the restart,
preserve the durable state and stop the dispatcher before any retry; do not resend an unknown
outcome automatically.
