# Backend Release Deployment Checklist

This checklist is executed only after `task.py start` and explicit approval of the final planning
summary. Commands must be run without echoing `.env`, passwords, webhook keys, provider responses,
signed URLs, private object keys, or full prompts.

## 1. Local release gate

1. Confirm `git rev-parse HEAD` is `a14847a`, `origin/main` points to the same commit, and
   `git diff --check origin/main..main` passes.
2. Confirm the worktree's uncommitted task/report files are not part of the release transfer.
3. Run `docker compose config --quiet` and the full-profile service listing:

   ```bash
   docker compose --profile governance --profile content --profile wecom config --services
   ```

4. Record the brand directory byte count, manifest checksum, and visual-asset count without
   printing file contents. Confirm local acquisition/content/governance/WeCom automatic services
   are stopped before any migration export.

## 2. Server read-only preflight

1. Log in interactively as `ubuntu` over SSH; do not place the password in a command, file, or
   shell history.
2. Inspect OS/Docker/Compose versions, system clock, free disk/inodes, UFW status, host listeners,
   and cloud-visible ports. The only intended inbound path is SSH.
3. In `/opt/edu-ai-lead-agent`, record current checkout, Compose service status, image IDs, current
   Alembic revision, safe row/object counts, backup timer status, and whether the WeCom dispatcher
   is stopped.
4. Compare the server's current brand manifest checksum and asset count with the local release.
5. If the expected release directory, durable volumes, or backup system is absent, stop and switch
   to the archived clean-host bootstrap procedure. Never infer a missing volume is disposable.

## 3. Backup and quiesce

1. Verify `/var/backups/edu-ai` is root-owned with mode `0700` and has enough free space for a
   complete local backup set with seven-day retention.
2. Stop `acquisition-api`, acquisition scheduler/worker, governance scheduler/worker, content
   scheduler/worker, and `wecom-dispatcher`; do not remove PostgreSQL/MinIO volumes.
3. Create a custom-format PostgreSQL dump, private MinIO mirror/snapshot, and brand-material
   archive in dated subdirectories. Write SHA-256 checksums and verify them before proceeding.
4. Record old Git commit, image IDs, migration head, safe queue counts, and backup identifiers in a
   server-local evidence file with secrets and private paths omitted.

## 4. Release and private inputs

1. Fetch `origin/main` and detach the server checkout at `a14847a`; do not use a moving branch as
   the runtime pointer and do not run `git clean`.
2. Stage local `private/brand-materials/` through the protected SSH channel. Verify the staged
   manifest checksum and file count, then preserve the old directory as a rollback copy before
   activating the new directory.
3. Set directories to `0755` and regular files to `0644` so the non-root `app` user can read them;
   keep the Compose mount read-only. Verify the manifest from a one-shot content-worker container.
4. Keep `.env` untracked and mode `0600`. Preserve provider credentials already present on the
   server; update only required non-secret release flags and verify their redacted values.

## 5. Build and migrate

1. Run `docker compose config --quiet` and inspect service names/port bindings only.
2. Build the backend images with the pinned checkout. If dependency resolution or provider DNS
   fails, retain the old images and stop rather than declaring a partial deployment healthy.
3. Start `postgres` and `minio`, wait for health checks, ensure the private bucket exists, and run
   `backend-migrate` (`alembic upgrade head` followed by source seeding).
4. Verify migration head, active source count, MinIO health, and database/object counts. Do not edit
   business rows or manufacture a daily selection.

## 6. Start automation and delivery

1. Start `acquisition-api`, `acquisition-scheduler`, and `acquisition-worker`; verify API health and
   stable container state.
2. Start `governance-scheduler` and `governance-worker` with the `governance` profile; verify
   upstream acquisition state and governance liveness.
3. Start `content-scheduler` and `content-worker` with the `content` profile; verify the ten-day
   freshness and science-policy-priority configuration, brand catalog access, and image provider
   configuration.
4. Start `wecom-dispatcher` with the `wecom` profile only after the upstream checks pass. Verify
   group-webhook mode, automatic reconciliation, and manual-review-disabled flags through redacted
   configuration/status output. Do not invoke a separate manual delivery test.

## 7. Verification and handoff

1. Run `docker compose --profile governance --profile content --profile wecom ps --all`; every
   long-lived service must be up without a restart loop, and one-shot services must have completed.
2. Check `http://127.0.0.1:8000/healthz` over SSH, PostgreSQL migration head, MinIO private health,
   visual manifest readability, and safe pipeline/delivery counters.
3. Inspect bounded recent logs for acquisition, governance, content, image recovery, and WeCom
   state transitions. Treat provider failures, `review_required`, `no_topic`, and `delivery_unknown`
   as typed outcomes, not as successful delivery.
4. Confirm current-business-date reconciliation created no duplicate job/fingerprint and that any
   intended current-date candidate has a durable delivery state. Do not send historical packages.
5. Run one backup timer/manual-backup verification, confirm seven-day retention, and write final
   secret-free evidence including release hash and rollback reference.
6. Leave local automatic workers stopped and hand off the server as the only automatic runtime.

## Rollback points

- Before release activation: restore the previous brand directory/release checkout and leave
  durable services unchanged.
- After activation but before migration: stop application services and restore the prior checkout;
  retain the backup bundle.
- After migration/startup failure: stop schedulers, workers, and dispatcher first; preserve volumes;
  restore the matching release/configuration and use a reviewed database restore only if required.
