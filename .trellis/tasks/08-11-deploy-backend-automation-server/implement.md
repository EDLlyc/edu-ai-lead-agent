# Backend release deployment checklist

Implementation starts only after `task.py start` and explicit approval of the final planning
summary. All SSH commands must use an interactive password prompt; never put the password in a
command, file, task artifact, shell history, or log.

## 1. Local release gate

- [x] Confirm `git rev-parse HEAD` is `a29588b` and inspect only tracked release files.
- [x] Confirm the image-generation/parser tests and `make backend-check` are green; run
      `docker compose config --quiet` and the full-profile service listing.
- [x] Record local brand manifest checksum/count without copying or printing private contents.
- [x] Confirm local acquisition, governance, content, and WeCom automatic processes are stopped.

## 2. Server read-only preflight

- [x] Log in as `ubuntu` to `124.222.207.221` without exposing credentials.
- [x] Verify `/opt/edu-ai-lead-agent`, the Compose project/volume names, current release, Docker/
      Compose versions, disk/inodes, firewall/listeners, migration head, backup timer, safe queue
      counts, active profile state, and manifest checksum.
- [x] The runtime matched the recorded provisioned host and the manifest matched; no stop was
      required.

## 3. Quiesce and backup

- [x] Stop active application API/schedulers/workers/dispatcher; retain PostgreSQL/MinIO volumes.
- [x] Create PostgreSQL, MinIO, and brand-material backups under `/var/backups/edu-ai`.
- [x] Verify checksums and record old commit/image IDs, migration head, and safe queue counters.

## 4. Transfer and activate

- [x] Create an allowlisted, path-filtered tracked archive for `a29588b`; a raw full-tree archive
      or Git bundle is insufficient because the pinned commit contains tracked report artifacts.
      Verify the archive excludes `.env`, private material payloads, reports, current task files,
      and all other worktree files before transfer.
- [x] Transfer and checksum the filtered archive on the host; activate the release in the existing
      runtime directory without changing Compose project/volume identity.
- [x] Preserve mode `0600` on `.env`, read-only brand mounts, and the previous release reference;
      update only the two approved non-secret image wait settings to `300`.

## 5. Build and migrate

- [x] Run `docker compose config --quiet` and inspect service/port names only.
- [x] Build only backend services needed by the preflight-active profiles.
- [x] Start/verify PostgreSQL and MinIO, run `minio-init`, then `backend-migrate`.
- [x] Verify migration head `20260807_0019`, active source count, private bucket health, and no
      direct business-row mutation.

## 6. Restart automation

- [x] Start the base API/acquisition services, then previously active governance, content, and
      WeCom profiles in dependency order.
- [x] Verify content worker manifest access and effective Comfly timeout/window values are 300.
- [x] Preserve existing WeCom configuration and profile state; do not enqueue a test delivery.

## 7. Acceptance and rollback evidence

- [x] Check full intended Compose status, API `/healthz`, migration, MinIO, private bindings,
      restart counts, and bounded logs.
- [x] Verify no duplicate delivery job/fingerprint was created and local automatic processes remain
      stopped.
- [x] Write secret-free deployment evidence with release, backup, manifest, migration, service,
      and bounded-error results.
- [x] No gate failed; the prior release, volumes, and backups remain available for rollback without
      an ad-hoc Alembic downgrade.

## Validation commands

```bash
make backend-check
docker compose config --quiet
docker compose --profile governance --profile content --profile wecom config --services
git diff --check
```

Remote validation uses the exact runbook commands for `docker compose ps --all`, `/healthz`,
Alembic head, MinIO health, manifest readability, safe logs, and the server evidence script. No
command may print `.env`, secrets, provider bodies, signed URLs, prompts, or private object keys.
