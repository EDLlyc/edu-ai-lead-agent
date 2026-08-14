# Production backend deployment design

## Release boundary

Deploy pinned GitHub commit `0a0988c` through the established archive-based runtime. The server is
not a Git checkout, so source transfer is an explicit allowlisted artifact rather than a branch
pull. The release contains only backend runtime inputs needed by the existing Compose deployment:

```text
.env.example
Makefile
README.md
backend/
compose.yaml
deploy/
docs/
environment.yml
infra/
scripts/
```

The archive is created from the commit object, not the dirty working tree. `.env`, `private/`,
`reports/`, `.trellis/`, frontend output, caches, and current task files cannot enter the archive.
Before transfer, list and scan the archive, produce SHA-256 and a per-file manifest, and reject any
forbidden path or secret-shaped file.

## Server layout and activation

```text
/opt/edu-ai-lead-agent/              existing runtime and Compose project
  .env                               preserved, mode 0600
  private/brand-materials/           preserved host-authoritative inputs
  RELEASE_COMMIT                     normalize to 0a0988c after activation
  .release-commit                    normalize to 0a0988c after activation

/opt/edu-ai-releases/0a0988c/        checksum-verified staging tree
/var/backups/edu-ai/releases/        previous code/marker/image evidence
/var/backups/edu-ai/{postgres,minio,brand-materials}/
                                      fresh maintenance-window backup set
```

Extract the verified archive into a new staging directory. The direct backend image build was
attempted twice and both attempts failed only while downloading pip from the external PyPI file
host; production was never quiesced. Because dependency inputs are byte-identical, the reviewed
fallback uses current production API image digest
`sha256:e0565c49a63e85d1708d1c114292ca7b350b51bf3e7934b7b5103596fe854d42` as an offline dependency
base and replaces these paths from the verified target staging tree:

```text
/app/pyproject.toml
/app/alembic.ini
/app/alembic/
/app/app/
```

The overlay Dockerfile starts from the exact digest, switches to root only for complete directory
replacement/copy with `app:app` ownership, restores `USER app`, and adds only non-secret release/
dependency-base labels. It does not run pip or inherit any host secret. Validate in-image per-file
hashes for the application/Alembic payload, dependency imports, source/rule constants, entrypoint
imports, and the non-root user before the maintenance stop. Tag this one tested digest for every
Compose-built application service so no mixed source image is used.

Activation overlays only the
allowlisted staged paths onto the existing runtime without `--delete`; there are no runtime-file
deletions between `a2660dd` and `0a0988c`. Protected paths and unrelated server files remain in
place. Record a checksum manifest after activation, then update both markers.

## Maintenance sequence

1. Reconfirm target/ancestor relationship, local checks, archive allowlist/checksum, server release,
   service state, migration, source/queue counts, bindings, backups, and protected inputs.
2. Upload, verify, extract, and prebuild the target offline overlay image in staging while
   production remains active; require target source hashes/imports and the exact dependency-base
   checksum/digest.
3. Stop WeCom, content, governance, acquisition scheduler/worker, then API. Retain PostgreSQL and
   MinIO and verify no application producer remains running.
4. Run the installed protected backup procedure and create a code/marker bundle plus image digest
   inventory. Verify new artifacts/checksums before activation.
5. Overlay staged runtime paths, preserve `.env`/private inputs, normalize markers, and render all
   active Compose profiles.
6. Tag the one validated offline target image as the image for migration and every previously
   active application service. Use Compose `--no-build` during recreation so the known PyPI outage
   cannot silently trigger a different build path.
7. Run `minio-init`, run/recreate `backend-migrate`, and require exit 0, migration `0019`, active
   source count 10, and no pending-source job/activation.
8. Start base API/acquisition and wait for health; start governance and verify liveness; start
   content and verify current-date boundaries; finally start WeCom and inspect delivery counts.
9. Verify runtime constants from inside containers, manifests, service/image/restart state, bounded
   logs, bindings, timer/evidence, and safe pre/post counters.

## Data and compatibility

- No Alembic file changes exist between server and target; schema head remains `20260807_0019`.
- Source seeding creates/activates the approved Xinhua Education version and preserves historical
  source/version rows. CAST/EdSurge connector code remains pending and is excluded from scheduling.
- `.4`/`.5` scoring and older acquisition/source/copy versions remain executable by the target.
- Existing queued jobs and artifacts are never deleted. The target preserves the current-business-
  date guard introduced in ancestor `a2660dd`, preventing the seven historical queued copy runs
  from being automatically claimed merely because services restart.
- All application containers are recreated together to avoid mixed rule/config interpretation.

## Delivery safety

The production `.env` and existing direct-delivery policy are preserved. There are no queued or
unknown WeCom jobs at preflight. The dispatcher starts last only after upstream health succeeds.
No test or manual package is enqueued. Compare total/status counts and recent safe fingerprints
before/after. Request fingerprints, the durable idempotency keys, have zero duplicate groups.
Content fingerprints identify package content and have one historical two-row group made of a
failed distinct request followed by a delivered distinct request for the same package; require
that group and its two status rows to remain exactly unchanged. If an unexpected new delivery,
request/content group, retry, or `delivery_unknown` appears, stop the dispatcher and preserve
durable state for review.

## Verification

Deployment success requires all of the following:

- archive/staging/active manifest and both release markers identify `0a0988c`;
- Compose full-profile render succeeds and uses the existing project/volumes;
- migration remains `0019`, active source count becomes 10, pending sources remain unscheduled;
- application constants report acquisition v5, scoring `.6`, and Ministry v3;
- all intended long-lived services run with target images and zero new restart loops;
- all application and migration containers use the same validated target digest built from the
  recorded dependency base, and in-image target manifests/constants pass;
- `/healthz`, PostgreSQL, MinIO, private manifest access, loopback bindings, backup timer, and
  bounded logs pass;
- no test jobs, historical copy claims, duplicate delivery, unknown provider state, or secret leak.

The server lacks Conda, so repository `make doctor` is not a valid production-host gate. Use
Compose render/health, migration/source SQL, container imports, service states, bindings, and the
production evidence script instead. Local `make doctor` remains part of the local gate.

## Rollback

Stop services in reverse dependency order. If failure occurs before writers reopen, restore the
code/markers or retag/recreate the recorded previous images; if source seeding must be reversed,
restore the fresh PostgreSQL backup while writers remain stopped. Keep named volumes and never run
an Alembic downgrade. After production writes resume, do not restore the database automatically;
preserve state and review the incident. Restart the previous release in dependency order and verify
its health/source compatibility before restoring WeCom.
