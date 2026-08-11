# Deploy backend automation release

## Goal

Deploy the current tracked backend release `a29588b` to the already provisioned Ubuntu host
`124.222.207.221` so the Comfly image-response parser fix and the 300-second provider wait
configuration are active in the server's backend automation. The server remains the only
automatic producer and delivery runtime; the frontend is not deployed.

## Background and confirmed facts

- Local `HEAD` is `a29588b`; `origin/main` is older, so the release must be transferred from this
  local tracked commit rather than fetched from the current remote branch.
- Previous deployment evidence records the runtime at `/opt/edu-ai-lead-agent`, PostgreSQL/MinIO
  named volumes, migration head `20260807_0019`, server-local backups under `/var/backups/edu-ai`,
  and a read-only `private/brand-materials/` bind mount. The host state must be verified read-only
  before any mutation.
- The current Compose topology has base acquisition services plus opt-in `governance`, `content`,
  and `wecom` profiles. All backend services build from `backend/Dockerfile`; no frontend service
  is part of this deployment.
- The local brand directory is approximately 219 MiB with 256 files. Its manifest checksum is
  `dbf0d94b6bf8abbae88bf769f0f319365ccdd40ba0f028be6aae8dc8ef2f4290`. The image parser fix does
  not change these assets, so the existing server copy is preserved after a checksum comparison.
- The previous live Comfly verification already produced valid local images. This deployment does
  not make another billable image request or send a real Enterprise WeChat message.
- Production credentials and delivery policy remain in the server's protected `.env`; they must
  not be copied to the local task, Git, shell history, logs, or deployment evidence.

## Requirements

1. **Pinned release:** Deploy exactly `a29588b` from the local tracked repository. Do not include
   reports (tracked or untracked), Trellis skill edits, local `.env`, or other worktree files.
2. **Read-only preflight:** Verify the SSH account, runtime directory, Docker/Compose, active
   containers, Compose project/volume names, migration head, backup root, disk space, host
   listeners, and brand manifest before changing the host. Stop and report if the host is not the
   previously provisioned runtime.
3. **Durable-state preservation:** Keep PostgreSQL/MinIO volumes and all pipeline, topic,
   package, image, and delivery history. Never use `docker compose down -v`, direct business-row
   edits, timestamp-based deletion, or an improvised migration downgrade.
4. **Protected inputs:** Preserve the server `.env`, evidence directory, and brand materials;
   compare the manifest and asset count before activation. Only replace brand inputs after a
   separately verified backup and an explicit mismatch-handling decision.
5. **Backup and rollback:** Quiesce write-producing application services, create a fresh
   server-local PostgreSQL/MinIO/brand backup with checksums, retain the previous release/image
   reference, and keep the old runtime recoverable.
6. **Backend-only build:** Transfer the tracked release, validate Compose, set the two approved
   non-secret image wait values to `300`, rebuild backend images for the existing service set, and
   run the normal `minio-init` then `backend-migrate` order.
7. **Service continuity:** Start or restart only the backend profiles that were active in the
   verified preflight, in dependency order. Preserve the existing WeCom provider, automatic-send
   flag, review policy, and recipient configuration; do not enable a previously stopped delivery
   profile as part of a code-only update.
8. **Verification:** Confirm healthy infrastructure, migration head, API health, stable intended
   services, content-worker brand-manifest readability, private/loopback host bindings, the new
   image parser code in the running image, and no restart loop or duplicate delivery job.
9. **Local exclusivity:** Confirm local automatic scheduler/worker/dispatcher processes remain
   stopped, so the server is the only automatic runtime.

## Acceptance criteria

- [x] The server runtime records release `a29588b` with no release-code changes outside the pinned
      bundle.
- [x] A fresh server-local backup set exists with verifiable checksums before the new application
      images are activated.
- [x] PostgreSQL and MinIO remain healthy, `backend-migrate` completes, and the migration head is
      `20260807_0019` without destructive reset.
- [x] Every backend service that was active before the update is running on the new image without
      restart loops; no frontend or public HTTP service is started.
- [x] The content worker can read the existing brand manifest through its read-only mount, and
      the configured Comfly timeout values are `300` seconds for both request and provider window.
- [x] Existing WeCom settings and profile state are unchanged; no real provider message or image
      generation test is sent during deployment.
- [x] No duplicate delivery request fingerprint or test-mode task exists after the upgrade; the
      migration did not reset business data or manufacture a test package.
- [x] Safe deployment evidence records release, migration, service, backup, manifest, and bounded
      error status without secrets, prompts, provider bodies, signed URLs, or private object keys.

## Out of scope

- Frontend build/deployment, reverse proxy, public API, domain, TLS, or inbound WeCom callback.
- Replacing the group webhook with the self-built-app route or changing delivery/review policy.
- Re-copying brand materials when the remote manifest matches the local one.
- New crawler, copy, image prompt, safety-policy, database-business-data, or provider changes.
- A real Comfly generation, real Enterprise WeChat send, or manual historical package retry.
- Off-host backups or SSH key/security-group hardening.

## Risks and deferred items

- If the host path, Compose project, volumes, backup system, or brand manifest differs from the
  recorded deployment, the rollout stops before mutation rather than guessing.
- A provider/DNS/PyPI failure can prevent a rebuild. The previous images and release remain the
  rollback point; the release is not marked healthy after a partial build.
- Restarting an already-active dispatcher can reconcile an eligible current-date package as part
  of normal operation. Its existing idempotency and date scope remain the guard; no test package
  is created.
- SSH password authentication remains as currently configured and is not changed here.

## Open questions

No product or scope decision blocks this plan. The remaining gate is explicit approval of the
final planning summary before `task.py start` and implementation.
