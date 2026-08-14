# Deploy today's completed backend changes to production

## Goal

Deploy the already verified science/technology education acquisition, ranking, source-registry,
and copy-safety changes through GitHub release `0a0988c` to the existing Ubuntu production runtime
at `124.222.207.221:/opt/edu-ai-lead-agent`, while preserving secrets, private brand materials,
durable PostgreSQL/MinIO data, automated delivery safeguards, and a tested rollback path.

## Confirmed facts

- The host is the established Ubuntu 24.04 Compose runtime accessed as `ubuntu`. Password
  authentication is accepted; credentials must remain interactive and must not enter commands,
  files, task artifacts, Git, shell history, or deployment evidence.
- `/opt/edu-ai-lead-agent` is an archive-based release directory, not a Git checkout. Deployment
  must use a verified filtered release archive and must not run `git pull`, `git clean`, or invent
  a new Compose project.
- The effective server release marker is `RELEASE_COMMIT=a2660dd`; `.release-commit=3383841` is
  stale from an earlier overlay and must be normalized with the effective marker during this
  deployment. `a2660dd` is an ancestor of target `0a0988c`.
- GitHub `origin/main` is `0a0988c`. Local commits after it (`4992988`, `507a41a`, `affceee`) contain
  only the completed DNS-diagnostic task/archive/journal and do not belong in the runtime release.
- Compared with `a2660dd`, the target changes 17 runtime files under `.env.example`, `backend/app`,
  `compose.yaml`, and `scripts/doctor.sh`. It adds no Alembic migration, public API schema, frontend,
  report, private material, or credential change.
- Production migration head is `20260807_0019`. The server currently has 9 enabled active sources;
  target seeding should produce 10 active sources while CAST and EdSurge remain pending in code and
  absent from production rows/jobs.
- All intended services are currently active with zero restart counts: base API/acquisition,
  governance, content, and WeCom profiles. PostgreSQL and MinIO are healthy. API `/healthz` returns
  production/Asia-Shanghai status.
- The production `.env` is mode `0600`. It preserves production provider/database/storage/WeCom
  secrets and has no explicit acquisition/scoring-version overrides, so target immutable defaults
  will take effect. Direct WeCom automation remains enabled under the already approved policy.
- Durable volumes are `edu-ai-lead-agent_postgres_data` and `edu-ai-lead-agent_minio_data`. The
  backup timer is enabled/active, existing protected backups are present, and 62 GB disk is free;
  a fresh maintenance-window backup is still required.
- Private brand materials contain 256 files; the manifest checksum is
  `dbf0d94b6bf8abbae88bf769f0f319365ccdd40ba0f028be6aae8dc8ef2f4290` and is readable from the
  content-worker image. The deployment must preserve this host-authoritative directory unchanged.
- Safe preflight counts include 29 acquisition runs, 123 evidence candidates, 29 governance runs,
  11 daily selections, 46 copy runs, 22 material packages, and 13 WeCom jobs. WeCom has 12
  delivered and 1 failed, with no queued or unknown delivery. Seven copy runs remain queued and
  must be preserved; the current-date claim guard must continue preventing historical replay.
- WeCom request fingerprints have zero duplicate groups. Content fingerprints are package-content
  identities rather than the unique request key, and have one pre-existing historical group: two
  formal copy-plus-image jobs for the same package/recipient, where the earlier distinct request
  failed without an unknown outcome and the later distinct request delivered. The deployment must
  keep this baseline exactly unchanged and must not create another request or content group.
- Host firewall exposes only rate-limited SSH. PostgreSQL, MinIO, and API ports remain loopback-only.
  Frontend, reverse proxy, public HTTP/TLS, OS upgrades, and firewall changes are not part of this
  release.
- Two staging Dockerfile builds stopped before production mutation because downloading the pip
  wheel from `files.pythonhosted.org` timed out. Production stayed healthy and unchanged. The target,
  previous release, and current API image all have identical `backend/pyproject.toml` SHA-256
  `e8686a2e336a5840f1edc87558a836411c881ad8878abf8d918b529f44f57556`; `backend/Dockerfile` and
  `environment.yml` are also unchanged. The current production dependency image imports FastAPI,
  SQLAlchemy, and LangGraph successfully, so the established offline source-overlay fallback is
  eligible after renewed user approval.

## Requirements

1. Pin runtime deployment to `0a0988c`, not the local unpushed documentation-only commits and not a
   floating branch. Reconfirm the target still matches GitHub before creating the release archive.
2. Use `git archive` from the pinned commit with an explicit backend-runtime allowlist. Exclude
   `.env`, `private/`, `reports/`, `.trellis/`, local dirty files, credentials, generated artifacts,
   and frontend assets. Transfer through the authenticated SSH channel and verify SHA-256 on both
   sides.
3. Stage and prebuild the target backend before the maintenance stop. The primary clean Dockerfile
   build has exhausted its two bounded attempts on the external PyPI timeout. Build the reviewed
   offline fallback from the current API image only after proving identical dependency inputs;
   replace the complete `/app/app`, `/app/alembic`, `/app/alembic.ini`, and `/app/pyproject.toml`
   payloads from the verified target staging tree, then test target imports/version constants. Do
   not create or attach a second Compose project or new durable volumes.
4. Record the previous markers, code checksum/archive, container image IDs/restart counts,
   migration, source count, safe queue counts, brand checksum, active profiles, and protected paths.
5. Stop write-producing services in dependency-safe order: WeCom, content, governance,
   acquisition scheduler/worker, and API. Keep PostgreSQL and MinIO healthy.
6. Create and verify fresh server-local PostgreSQL, MinIO, brand-material, and current-code backups
   before activation. Do not copy production backups or secrets into Git/local task artifacts.
7. Activate the staged archive atomically or through a checksum-verified overlay in the existing
   runtime. Preserve `.env`, `private/brand-materials`, named volumes, Compose project identity, and
   unrelated server files. Normalize both release markers to `0a0988c` only after activation.
8. Render the full Compose configuration without exposing values, build all previously active
   backend service images from the same target, run MinIO initialization, then run the existing
   `backend-migrate` migration-plus-seed command. Verify migration remains `20260807_0019` and
   active sources become exactly 10.
9. Start API/acquisition, governance, content, then WeCom in order. Do not enqueue a test run,
   manufacture content, call an image provider, retry historical work, or send a test message.
10. Verify release/version constants, private manifest readability, health, restart counts,
    loopback bindings, bounded startup logs, queue state, historical-copy claim guard, source
    registry, and absence of unexpected WeCom delivery/unknown state.
11. If a build, backup, migration/seed, health, queue, delivery, or registry gate fails, stop the
    rollout and use the recorded code/images/backups. Never delete volumes, downgrade Alembic by
    guesswork, resend unknown delivery, or directly edit business rows.
12. Record only redacted release/backup/checksum/status/counter evidence. Recommend rotating the
    password shared in chat after the deployment; credential rotation itself is out of scope.

## Acceptance criteria

- [x] The production runtime and all rebuilt application containers are pinned to `0a0988c`; both
      release markers agree and the activated runtime manifest matches the transferred archive.
- [x] The offline release image records the reviewed dependency-base digest and proves its
      `pyproject.toml` checksum matches the target before complete target source/Alembic overlay;
      no mixed old application module remains in `/app/app`.
- [x] A fresh, checksum-verified rollback set exists for PostgreSQL, MinIO, brand materials, current
      runtime code, previous image IDs, and prior release markers.
- [x] `.env`, the private brand manifest/checksum, named volumes, Compose project identity, and
      durable business counts are preserved except for expected source seeding and ordinary
      current-date automation after reopening services.
- [x] `backend-migrate` succeeds at unchanged Alembic head `20260807_0019`; production has exactly
      10 enabled active sources. CAST and EdSurge remain unscheduled/pending.
- [x] API, acquisition, governance, content, and WeCom services are all running without restart
      loops; PostgreSQL/MinIO remain healthy and API `/healthz` succeeds.
- [x] Running configuration reports `acquisition-v5-tiered-science-tech`,
      `scoring-v1-preview.6-tiered-science-tech-priority`, and
      `ministry-education-priority-v3`, with historical replay compatibility retained.
- [x] No test acquisition/content/image/WeCom job or manual business-row change is created by the
      deployment. Pre-existing seven queued copy runs remain governed by the current-date claim
      boundary; WeCom request-fingerprint duplicate groups remain zero, the one historical
      content-fingerprint group remains unchanged, and no replay or unknown delivery appears.
- [x] Bounded logs, bindings, backup timer, release evidence, and rollback commands pass a final
      independent review without secret exposure.

## Out of scope

- Fixing or activating the CAST/EdSurge live parsers; both remain pending.
- Deploying frontend assets, reports/PDFs, `.trellis` task history, local skills, DNS/Clash host
  configuration, reverse proxy, TLS, public API exposure, OS packages, firewall rules, or a new
  Compose project.
- Changing production credentials, provider modes, recipient/review policy, brand materials,
  historical business data, or automatic delivery semantics.
- Running a live provider smoke, manually triggering today's pipeline, retrying failed deliveries,
  or deleting queued jobs.

## Risks and rollback boundary

- Rebuilding all application services creates a maintenance window but prevents mixed-version
  workers from interpreting the same durable queues differently.
- Reusing a dependency image is safe only because all dependency/build inputs are byte-identical.
  The fallback replaces complete application and Alembic trees, validates their manifests inside
  the image, and deploys one resulting digest to every application service. Any checksum/import/
  manifest mismatch stops before the maintenance window.
- `backend-migrate` has no schema upgrade at this target but does reconcile immutable source
  versions. A failure before writers restart may use the fresh database backup for an exact source
  registry rollback. After new production writes resume, any database restore requires explicit
  incident review to avoid losing legitimate data.
- Starting the already enabled WeCom dispatcher may reconcile eligible current-date work. The
  preflight has no queued/unknown WeCom job; counts and status must be checked before and after
  startup. Any new unknown/provider-side ambiguity stops the dispatcher and is never blindly sent.
- Rollback stops dispatcher/workers/schedulers first, restores the previous code/markers or recorded
  image IDs, keeps volumes, runs only compatible migration/health checks, and restores the fresh
  database/MinIO backup only when required by the failure point.
