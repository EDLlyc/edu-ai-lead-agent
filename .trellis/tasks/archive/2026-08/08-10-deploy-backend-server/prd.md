# Deploy Backend Automation Release

## Goal

Update the already provisioned backend runtime on the Ubuntu host at `124.222.207.221` to the
pushed release `a14847a`, and leave the daily acquisition, governance, content, image, material
package, and Enterprise WeChat group-webhook automation running without the local machine also
producing or sending business work.

## Background and confirmed facts

- `main` at `a14847a` is pushed to `origin/main`.
- Repository journal evidence records an earlier backend-only deployment to the target host,
  including PostgreSQL, MinIO, brand materials, scheduled services, and seven-day local backups.
  The actual host state must be checked before any mutation because the last verification left the
  WeCom dispatcher stopped.
- The Compose topology contains PostgreSQL, MinIO, `backend-migrate`, acquisition API/scheduler/
  worker, and opt-in `governance`, `content`, and `wecom` profiles. The frontend is not required
  by the production workflow.
- `private/brand-materials/` is Git-ignored and is about 219 MiB locally. Its visual manifest and
  image files must be copied separately and mounted read-only for the content worker.
- The business timezone is `Asia/Shanghai`; acquisition is configured for 06:30 and content
  selection/production for 07:30, with a ten-day freshness window and the current science-policy
  priority rules.
- Enterprise WeChat delivery uses the official outbound group-webhook route. It does not require
  an inbound callback URL, trusted domain, trusted IP, self-built-app recipient ID, or public API.
- Direct automatic delivery is approved: enable the dispatcher, set the group-webhook provider,
  enable automatic reconciliation, and disable the manual-review gate. Existing hard validation,
  idempotency, provider, storage, and private-network safeguards remain part of the deployed code.
- Production credentials, including provider keys and the webhook key, must remain in the server
  `.env` or secret store. They must not appear in this task, Git, shell history, logs, or evidence.
- The user requested a server-local backup only. The target backup root is `/var/backups/edu-ai`,
  with seven-day retention; off-host backup is deferred.

## Requirements

1. **Pinned release:** Deploy exactly commit `a14847a`; do not track a moving branch and do not
   include local uncommitted files.
2. **Incremental update:** Preserve the server's PostgreSQL/MinIO volumes and durable pipeline,
   topic, material-package, and delivery history. Do not use `docker compose down -v`, direct
   business-row edits, timestamp-based test deletion, or an unreviewed database reset.
3. **Protected inputs:** Transfer the current Git-ignored brand-material directory through a
   protected staging path, verify its manifest and checksum, and expose it to containers as a
   read-only bind mount with application-readable permissions.
4. **Production configuration:** Keep the existing protected provider/model configuration, use
   production mode and `Asia/Shanghai`, and set group-webhook automatic delivery as approved.
   Generate or retain fresh server-local database and MinIO credentials; never copy development
   placeholders.
5. **Ordered startup:** Back up durable state, stop write-producing workers, update/build the
   release, run `backend-migrate` successfully, then start acquisition, governance, content, and
   WeCom services in dependency order.
6. **No public surface:** Deploy no frontend, reverse proxy, domain, TLS endpoint, inbound WeCom
   callback, or public application route. Keep API, PostgreSQL, and MinIO loopback/private and
   expose only the administrator SSH path.
7. **Automatic delivery:** The dispatcher must poll and deliver eligible current-business-date
   packages through the group webhook, send only the copy body plus the image according to the
   existing provider contract, and preserve idempotent durable delivery states.
8. **Evidence and rollback:** Record safe release, service, migration, backup, object, and queue
   evidence. Keep the previous release and matching backups available for rollback without
   destructive volume removal.

## Out of scope

- Frontend deployment, reverse proxy, public API, domain, TLS certificates, or WeCom callbacks.
- Replacing the group webhook with the self-built-app API route.
- Changing copy/image policy code, crawler scope, model prompts, or database business data as part
  of this release deployment.
- Off-host backups or SSH key-only hardening; both remain follow-up operational work.

## Acceptance criteria

- [ ] The target release directory records `a14847a` and has no uncommitted release-code changes.
- [ ] The host has healthy PostgreSQL and MinIO containers, and `backend-migrate` completes at the
      release migration head without a destructive reset.
- [ ] Acquisition API/scheduler/worker, governance scheduler/worker, content scheduler/worker,
      and the WeCom dispatcher are running without restart loops.
- [ ] The brand manifest is readable by the non-root content worker, the expected visual catalog is
      present, and the bind mount remains read-only.
- [ ] All application/database/object-store host bindings remain loopback/private; no frontend or
      public HTTP service is started.
- [ ] The dispatcher configuration is group-webhook + automatic delivery + no manual-review gate,
      while the durable eligibility, validation, idempotency, retry, and unknown-outcome rules
      remain active.
- [ ] Existing current-date delivery candidates are reconciled at most once; no duplicate job or
      provider send is created during the upgrade.
- [ ] A root-owned `/var/backups/edu-ai` backup set and seven-day timer are present and a fresh
      pre-upgrade backup has a verifiable checksum.
- [ ] Safe deployment evidence contains the release hash, migration head, service states, backup
      identifiers/checksums, and bounded error summaries, with no secret or private object URL.

## Risks and deferred items

- The host may differ from the journal evidence. If the release directory, volumes, or backup
  timer are missing, stop the incremental procedure and use the reviewed bootstrap path rather
  than guessing or deleting data.
- A provider, DNS, or PyPI outage can prevent image builds or first-day generation. Keep the old
  image/runtime available and do not mark the release healthy until Compose and liveness checks
  pass.
- Enabling the dispatcher may send an eligible current-date package as intended. No extra manual
  test package or duplicate daily selection will be manufactured during deployment.
- Password SSH remains enabled by explicit user choice. Key-based access and cloud security-group
  CIDR restriction are separate hardening work.

## Open questions

No product or scope decision blocks the deployment plan. The remaining transition is the Trellis
review gate: implementation begins only after the user explicitly approves the final plan below.
