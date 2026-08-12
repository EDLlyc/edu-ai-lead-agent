# Deploy compact Moments copy patch

## Goal

Deploy the verified compact Moments-copy release `dbd2c42` to the existing
backend automation host. Subsequent newly generated materials should use the
shorter default copy rules without changing delivery behavior or historical
business data.

## Confirmed Facts

- The server runtime is the existing Ubuntu Compose deployment at
  `124.222.207.221:/opt/edu-ai-lead-agent`.
- `dbd2c42` was locally validated with focused unit tests, formatter, Ruff,
  mypy, and a real no-persistence Zhipu preview.
- The patch changes copy-generation defaults only; it has no Alembic migration
  and no changes to Enterprise WeChat routing or image generation.
- The previous deployment established server-local backups under
  `/var/backups/edu-ai`; production `.env`, PostgreSQL/MinIO volumes, and
  `private/brand-materials` must remain authoritative on the host.
- During the rollout, the server revealed that automatic reconciliation creates
  new copy runs for every historical selected topic missing the current version
  fingerprint. The content services are paused while this is corrected.

## Requirements

1. Verify the remote runtime, current release, Compose services, protected
   inputs, disk headroom, and existing backup location before mutation.
2. Preserve server `.env`, brand materials, PostgreSQL/MinIO volumes, and all
   business history. Do not copy local uncommitted report files or skills.
3. Synchronize the tracked release through Git and activate only `dbd2c42` and
   its already-required ancestor commits.
4. Create a fresh server-local rollback reference/backup before rebuilding.
5. Rebuild and restart only backend services affected by the patch:
   `acquisition-api`, `content-scheduler`, and `content-worker`, retaining
   infrastructure services and the existing delivery-profile state.
6. Do not run database migrations unnecessarily, create test content, call an
   image provider, or send Enterprise WeChat messages.
7. Verify the running code/configuration and service health after activation.
8. Restrict automatic copy reconciliation and claiming to the current
   `BUSINESS_TIMEZONE` business date, so a service restart cannot generate or
   send historical materials. Preserve historical queued rows without deletion.

## Acceptance Criteria

- [ ] Server records the intended release at or after `dbd2c42` with protected
      inputs and durable data unchanged.
- [ ] A server-local pre-deployment rollback reference/backup exists.
- [ ] The three affected services run the rebuilt code without restart loops;
      PostgreSQL and MinIO remain healthy.
- [ ] No database migration, image request, test material, or Enterprise
      WeChat delivery is created by this rollout.
- [ ] Verification confirms compact copy configuration is effective for future
      generation and reports only redacted operational details.
- [ ] Restarting the content services does not create or claim historical
      business-date copy runs; current-date automatic processing resumes.

## Out Of Scope

- Frontend, reverse proxy, public HTTP configuration, brand asset changes, and
  any change to delivery recipient/review policy.
- Retrying or regenerating historical materials.
- Changing server credentials, copying secrets, or moving backups off-host.
