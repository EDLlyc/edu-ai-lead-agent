# Admin reliability candidate — not deployed

The change is based on `97ece80` and the currently deployed release-2 application image
`sha256:24e967081b2e9b303a1f295e7e99eacd24ed96304d5cbb5bd3645270fe159249`.
It changes 12 backend files (including migrations 0060/0061), with no dependency changes.
`files.txt` is the exact base/candidate byte manifest. A new admin bundle must be paired with
this backend because its statistics and publication response contracts add required fields.

## Candidate validation

See `../research/final-review.md`, `../research/browser-review.md` and `../result.md`.
Unit, real PostgreSQL integration, generated-contract and frontend checks run locally with
fake providers. The candidate smoke also passes against local final source (12 hashes / head 0061).
Read-only production preflight on 2026-10-10 verified all 12 base states, schema 0059, zero
occupied-draft conflicts and zero publish jobs; repeat it at deployment. No real publication, model probe, or production configuration write is part
of this task. The production-base image is not installed on the local Docker daemon, so the
actual image build/offline container smoke remains a deployment prerequisite, not a claimed
completed check.

## Deployment sequence after owner approval

1. Re-check the server's image and migration head (`20261009_0059`), and compare every base hash
   in `files.txt` against `/app/<path>` in acquisition-api. Missing files must remain absent.
   Reconcile any drift before continuing. Check occupied draft conflicts with `preflight.sql`;
   the migration repeats this check under a table lock and aborts without deleting any history.
2. Build a minimal context from this folder and its listed backend paths (strip `backend/`).
   Tag the exact verified deployed image ID as
   `offline.local/edu-ai/edu-ai-lead-agent-backend:admin-reliability-base-24e96708`, then build
   this Dockerfile with `--pull=false`. Record the candidate image ID.
3. Run `smoke.py` in that image with `--network none`, no production environment or mounts,
   and `--entrypoint python`; mount only the smoke file read-only. Every manifest hash and
   the single Alembic head must match. Build admin assets into a separate staging directory.
4. Choose a quiet time outside slot windows (06:00–08:30, 11:00–13:30, 17:00–19:30 CST).
   Confirm no active acquisition/content/copy/infographic/delivery work or due/open publish
   jobs. Back up PostgreSQL with verified `pg_dump -Fc`, `.release.env`, `compose.yaml` and
   `/var/www/edu-ai-admin`; preserve credentials without printing or rotating them.
5. Stop acquisition-api briefly to prevent an old publication loop writing during cutover.
   Set the new image pin and run the candidate migration job through `20261010_0061`.
   If conflict preflight fails, restore the old pin/service and investigate; do not modify
   historical rows automatically to force the migration through.
6. Recreate only acquisition-api, acquisition-worker, content-scheduler, content-worker,
   wecom-infographic-producer and wecom-dispatcher. Keep the other seven services on their
   existing images. Upgrade backend before atomically replacing admin assets.
7. Verify health and unauthenticated admin 401 responses; authenticated reads must show new
   response fields, correct statistics date coverage and three consumers' safe heartbeats.
   Check publication counts/state have not changed unexpectedly. Do not create a publish job
   to smoke-test deployment. Confirm no tracebacks and no heartbeat schema errors.
8. Restart the loopback production preview with the approved bundle/config, then verify known
   admin deep routes and refresh. Keep the isolated demo separate. Record exact digest,
   schema, bundle checksums, backup location and outcome; update mainline only after success.

## Rollback

Restore the old image pin and matching frontend asset backup, then recreate the same six
services. Leave schema 0061 in place: additions are nullable and old code can read them.
The stronger occupancy constraint still prevents duplicate drafts. If operators have used
manual reconciliation, freeze publishing during rollback because the old UI cannot explain
that provenance. Do not downgrade as a routine rollback: 0060 intentionally refuses unknown
or reconciled history, and dropping 0061 would discard load-error evidence.
