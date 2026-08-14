# Deployment implementation plan

## Preconditions

- Do not mutate production until the user explicitly approves the latest planning summary and
  `task.py start` changes the task to `in_progress`.
- Use interactive SSH password entry only. Never place the password in a command, environment
  variable, archive, file, log, task artifact, or Git.
- Preserve all unrelated local dirty paths under `.agents/skills/` and `reports/`.
- Pinned runtime target is `0a0988c`; local documentation-only commits after it are not deployed.

## Checklist

1. [x] Reconfirm local `origin/main=0a0988c`, target ancestry from `a2660dd`, no runtime migration/
       API/frontend change, prior full quality results, local Compose render, and stopped local
       automatic processes.
2. [x] Create a temporary filtered `git archive` for the reviewed runtime allowlist; scan member
       paths, reject forbidden/sensitive paths, generate archive and file-manifest checksums, and
       remove the local temporary directory after verified transfer.
3. [x] Reconnect read-only and reconfirm server markers, healthy infra/application services,
       migration/source/queue counts, active profiles, image IDs/restarts, disk, timer/backups,
       bindings/firewall, `.env` mode, and private manifest checksum/readability.
4. [x] Transfer through SSH to a new staging path, verify checksum/member manifest, extract, and run
       full-profile `docker compose config --quiet`. Record that two primary Dockerfile builds
       stopped on the same external pip-download timeout with production unchanged. Build the
       approved offline overlay from exact current API image digest after proving dependency-input
       checksum equality; validate complete in-image target app/Alembic hashes, imports, constants,
       and non-root execution before attaching it to production services.
5. [x] Stop dispatcher, content, governance, acquisition schedulers/workers, and API in that order;
       verify only PostgreSQL/MinIO and completed one-shots remain.
6. [x] Run the installed server backup procedure; verify fresh PostgreSQL, MinIO, brand-material,
       checksum artifacts. Create a server-local allowlisted code/marker rollback archive and record
       previous container image IDs/restart counts.
7. [x] Activate only the staged runtime allowlist in `/opt/edu-ai-lead-agent`; preserve `.env`,
       private materials, volumes, project name, and unrelated files. Verify the active manifest and
       normalize `RELEASE_COMMIT` plus `.release-commit` to `0a0988c`.
8. [x] Render full profiles, tag the one validated offline target digest for `backend-migrate` and
       every previously active backend application service, recreate with `--no-build`, run
       `minio-init`, then require migration/seed exit 0,
       Alembic `20260807_0019`, exactly 10 active sources, and CAST/EdSurge still pending/no jobs.
9. [x] Start API/acquisition and require health, then governance, then content; verify liveness,
       target constants, manifest access, current-date claim behavior, and no historical replay.
10. [x] Start WeCom last. Verify no new unexpected delivery/unknown state, zero duplicate request
        fingerprints, the unchanged one-group/two-row historical content-fingerprint baseline, and
        no restart loop. Do not enqueue or resend anything.
11. [x] Run final Compose/service/image/health/SQL/binding/timer/evidence/bounded-log checks. Compare
        safe pre/post counters, scan evidence for secrets, and retain exact rollback identifiers.
12. [x] Update task result/checklist, independently review the production state, and report the
        target, downtime, backups, expected source-count change, service health, and any deferred
        issue. Recommend rotating the shared password.

## Local validation

```bash
git diff --check 0a0988c
docker compose --profile governance --profile content --profile wecom config --quiet
make backend-check
make doctor
```

The target's previous final gates already recorded backend 680 passed, Ruff/mypy, frontend 27
tests/build, API contract, Compose, and doctor. Rerun the backend/Compose/doctor gate immediately
before release transfer; no frontend deploy is performed.

## Remote validation

- `docker compose --profile governance --profile content --profile wecom config --quiet`
- existing-volume/project identity and all intended `docker compose ps -a` states
- API `http://127.0.0.1:8000/healthz`
- Alembic revision and enabled active/pending-source counts via PostgreSQL
- in-container target version constants and private manifest read
- identical target digest for every application/migration container, expected dependency-base
  label/checksum, complete target app/Alembic manifests, imports, and non-root user
- safe queue/delivery status counts, restart counts, bounded logs, loopback listeners, backup timer,
  and `scripts/edu-ai-production-evidence.sh`

Do not run `make doctor` remotely because the production host intentionally lacks Conda.

## Rollback points

- Before quiesce: discard staging and leave production untouched.
- After quiesce/before seed: restore previous code markers or recreate recorded old images.
- After seed/before writers: if exact source-registry rollback is required, restore the fresh
  PostgreSQL backup with all writers stopped; preserve MinIO and verify compatibility.
- After writers reopen: stop dispatcher/workers/schedulers immediately and review durable changes;
  do not automatically restore the database or resend provider work.
