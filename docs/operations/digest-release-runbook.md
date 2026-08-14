# Immutable Digest Release Runbook

This runbook covers the repository contract for Codeup-triggered, ACR-backed releases. It is not
an activation record. The checked-in Flow definition keeps registry publication, GitHub backup,
and production deployment disabled until an administrator verifies every external gate.

## Authority and daily development

- Codeup repository `marketingUseOnly/edu-ai-lead-agent` (repository ID `7328051`) is the
  authoritative write source. Push daily branches and reviewed `main` changes to `origin`.
- GitHub `EDLlyc/edu-ai-lead-agent` is a one-way backup destination. Never fetch GitHub state and
  force it over Codeup, and never use GitHub to trigger production.
- Feature branches receive only branch-safe quality and local image-build jobs. A protected
  `main` update may publish or deploy only after the corresponding disabled Flow gates are
  explicitly enabled.
- Frontend format/type/test/Vite build and API generation are local/CI gates only. The release
  creates no frontend image or artifact and does not deploy or modify production frontend/static
  hosting.
- Do not push a dirty worktree, generated release bundle, production `.env`, private materials,
  credentials, Runner registration commands, or authenticated URLs.

Before pushing, use:

```bash
make python-lock-check
make check
docker compose --profile governance --profile content --profile wecom config --quiet
git diff --check
git push origin HEAD
```

## Reproducible Python and image inputs

`backend/pyproject.toml` remains the human-maintained dependency source. The generated
`backend/requirements/runtime.lock` and `backend/requirements/dev.lock` are both required release
inputs and contain package hashes. Regenerate them only in the supported Python 3.11 environment:

```bash
make python-lock
make python-lock-check
```

Review all version changes before committing both locks. `pip-tools==7.6.1` is the lock compiler
contract, and the compiler index URL is explicit so host pip configuration cannot alter generated
headers. Alembic remains below 1.19 until the named-check-constraint autogenerate behavior and
existing migration drift contract are deliberately migrated together. Do not hand-edit a lock or
bypass `--require-hashes` to make a build pass.

Flow must not call the managed runner's preinstalled `python3`, `node`, or a host-created virtual
environment. It builds the non-published `backend/Dockerfile.ci` Python 3.11 image from `dev.lock`
and runs Python tools through `scripts/ci-python.sh`; frontend quality uses the digest-pinned Node
20 image through `scripts/ci-node.sh`. The wrappers use the checkout UID/GID, isolated HOME/tmp,
and an allowlisted command name. Existing regular Pydantic/Vite environment files receive a
read-only `/dev/null` overlay; absent files remain absent, while symlink/non-regular mask targets
fail closed. The wrappers do not pass an env-file, host environment, Docker socket, or privileged
mode.

The Flow `quality_job` and local-candidate `image_job` run in the official Yunxiao alinux3
linux/amd64 manifest pinned by digest. Run 4 proved that the deprecated/default environment may
lack Docker entirely even when checkout succeeds. `source_identity` therefore runs a redacted
`docker info` server-version probe followed by `docker compose version` before any build. The
official image inventory is useful review evidence, but these live probes are authoritative for
daemon and Compose availability; do not download an unpinned Compose plugin inside the job.

Before `backend-check`, Flow waits for healthy `postgres` and `minio`, then runs `minio-init`
synchronously, resolves the Compose project network, and supplies only fixed
development-placeholder DB/MinIO and provider-disabled variables to the Python quality container.
The Python wrapper otherwise uses no network. Node receives ordinary registry egress only for
`npm ci`; later frontend checks run with no network. Neither quality container receives Flow
secrets, and neither quality image is tagged for ACR, added to the release bundle, or deployed.

Local Compose keeps its existing developer workflow:

```bash
docker compose up -d --build
```

The shared default image is `edu-ai-lead-agent-backend:local`. A production release writes a
root-owned mode-600 `.release.env` containing one digest-only `APP_IMAGE`. All nine application
and migration services must render that exact value, and production commands always use
`--no-build`. The pinned Python base digest and the runtime hash lock make the application image
independent of production PyPI access.

## Release artifacts

Flow builds artifacts from the exact committed Git object, never from uncommitted workspace files.
The backend release consists of:

- `release-bundle-<40-character-commit>.tar.gz`;
- its deterministic per-member checksum list;
- `release-manifest.json`, conforming to `deploy/release/release-manifest.schema.json`;
- one ACR reference in `registry/namespace/repository@sha256:<64-hex>` form.

The manifest binds the Codeup commit, source URL, OCI build timestamp and input hashes, image
digest, bundle checksums, Alembic head, migration-compatibility declaration, and all required gate
result IDs. The verifier rejects unknown manifest keys, tags in place of digests, missing gates,
checksum drift, non-regular files, traversal, symlinks, oversized members, non-allowlisted paths,
secret-shaped content, and migration declarations that do not match the bundled Alembic graph.
The allowlist excludes `frontend/` and `frontend/dist`; the only ACR image context is `backend/`.

For a committed release candidate, the same repository-side tools are:

```bash
make release-bundle COMMIT=<40-character-commit>
python deploy/release/release_tool.py verify-bundle \
  --manifest <release-manifest.json> \
  --bundle <release-bundle.tar.gz> \
  --expected-commit <40-character-commit>
```

Manifest creation also requires all nine named gate IDs. Flow owns those arguments; operators must
not invent successful IDs manually.

## External activation gates

The following values are deliberately inactive or placeholders in `deploy/yunxiao/pipeline.yaml`:

| Gate | Required administrator evidence before activation |
| --- | --- |
| Codeup source connection | Project-scoped connection ID, normalized Flow read-back, branch CI success, and pipeline ID available for protected `main` |
| `ACR_PUBLISH_ENABLED` | Project-isolated repository, connection inventory `79934` / YAML-facing ID `c8jknt8rkk1w7tc1` authorized only as intended, builder network access, tag-to-digest resolution, and pull-by-digest/offline probes |
| `GITHUB_BACKUP_ENABLED` | Repository-scoped write identity, strict known-host verification, exact-SHA no-op test, and no reverse synchronization |
| `PRODUCTION_DEPLOY_ENABLED` | Tencent Runner identity and machine group, concurrency one, root-owned entrypoint, pull-only project ACR identity, successful dry run, and verified prior digest release |

Keep every flag false if its evidence is incomplete. A live Flow import and normalized read-back are
required because repository YAML tests cannot prove organization-specific schema, built-in variable,
artifact-download, or service-connection behavior.

Codeup `main` protection is activated only after the real pipeline ID and branch behavior are
known. A candidate ACR push must not imply permission to deploy it.

## Credential boundaries and rotation

| Identity | Minimum scope | Storage and rotation rule |
| --- | --- | --- |
| Developer Codeup SSH key | This Codeup workflow only; expiring | Local SSH agent/config outside Git; remove at expiry and issue a distinct replacement |
| Flow Codeup source | Read the project repository | Yunxiao protected service connection; rotate without putting key material in YAML |
| Flow ACR publisher | Push only the isolated project repository | Connection inventory `79934` / YAML-facing `c8jknt8rkk1w7tc1` only after resource isolation is proven; administrator rotates it |
| Production ACR identity | Pull only the isolated project repository | Root-only credential store on the host; verify it cannot push before and after rotation |
| GitHub backup key | Write only `EDLlyc/edu-ai-lead-agent` | Protected Flow file/credential plus pinned official known-host entry; rotate independently of Codeup |
| Tencent Runner token | One-time registration only | Never store the install command or token; reissue from the official UI when reenrolling |

After any rotation, repeat the least-privilege and exact-target checks before re-enabling the
affected gate. Never print a key, password, token, Docker auth file, or full environment while
collecting evidence.

## Production bootstrap and dry run

The automatic deployer intentionally refuses an undocumented first release. Before enabling it,
the active host must already have a verified digest-based rollback baseline with all of:

- `/opt/edu-ai-lead-agent/.env` and `.release.env`, both mode 600;
- `.release-commit`, `.release-manifest.json`, and `.release-runner` matching one another;
- `/var/lib/edu-ai/releases/current.json` equal to the active release manifest;
- the prior digest locally pullable, a healthy backup timer, at least 5 GiB free, and no running or
  ambiguous durable jobs;
- the shared nine-service `APP_IMAGE` Compose contract in the active runtime.

Install the small root-owned deploy wrapper once; it always executes the checksum-verified
deployer in the active runtime. Install the tracked systemd unit with its active-runtime backup
path so timer runs receive future verified backup fixes without copying credentials or scripts into
the unit directory:

```bash
install -o root -g root -m 0755 scripts/edu-ai-deploy.sh /usr/local/sbin/edu-ai-deploy
install -o root -g root -m 0644 deploy/systemd/edu-ai-backup.service \
  /etc/systemd/system/edu-ai-backup.service
install -o root -g root -m 0644 deploy/systemd/edu-ai-backup.timer \
  /etc/systemd/system/edu-ai-backup.timer
systemctl daemon-reload
systemctl enable --now edu-ai-backup.timer
```

Read back `ExecStart`, wrapper ownership/mode, timer state, and wrapper/runtime checksums before
enabling Flow. The backup script takes its own non-blocking lock, so a timer run and deployment
backup cannot write the same timestamped evidence concurrently.

Establishing that baseline is an administrator-controlled migration step, not an automatic
bootstrap shortcut. Do not fabricate a prior manifest for a locally built or unknown image.

Once the candidate digest, manifest, bundle, Runner ID, and baseline are verified, invoke the
root-owned wrapper with `--dry-run`. The dry run verifies the bundle, lock, prior-release markers,
queues, image labels, non-root image identity, offline imports, `pip check`, and the full Compose
digest rendering. It does not quiesce, back up, migrate, restart services, enqueue work, contact an
AI provider, or send WeCom messages.

```bash
/usr/local/sbin/edu-ai-deploy \
  --manifest <release-manifest.json> \
  --bundle <release-bundle.tar.gz> \
  --expected-commit <40-character-flow-commit> \
  --runner-id <verified-runner-id> \
  --dry-run
```

## Automatic deployment phases

The non-dry-run entrypoint requires root and takes a non-blocking `flock`. It then runs one typed,
serialized state machine:

1. verify the host, prior release, backup timer, disk, queues, and protected inputs;
2. pull the exact digest and run network-none/read-only image probes while production is active;
3. stop dispatcher, content, governance, acquisition workers/schedulers, then API;
4. run and verify PostgreSQL, MinIO, and private-brand backups;
5. snapshot the previous runtime, manifest, markers, and digest environment;
6. atomically activate the checksum-verified runtime bundle and `.release.env`;
7. run MinIO initialization and the one-shot migration/seed container;
8. recreate API/acquisition, governance, content, and WeCom in that order with `--no-build`;
9. verify health, zero restarts, one digest, queue/delivery invariants, evidence, and a stability
   sample; then persist the new current manifest and evidence.

Backup evidence is parsed as a strict key set and cross-checked against the previous commit/image,
all three backup checksums, the MinIO object count, and the MinIO member checksum manifest before
activation. The production release does not run `git pull`, `pip install`, `docker build`, frontend build or
deployment, provider smoke tests, or message-delivery tests.

## Failure and rollback

| Failure point | Automatic action |
| --- | --- |
| Preflight or image verification | Stop with no production mutation |
| During or after partial quiesce, before activation | Restart the complete unchanged previous digest and verify services |
| During activation, or after activation before migration | Restore the previous runtime snapshot and digest, then verify services |
| Migration attempt fails | Stop writers and preserve the incident state; no automatic application rollback |
| Post-migration failure, unchanged Alembic head | Restore the previous application runtime/digest, refresh previous-release evidence, and verify it |
| Post-migration failure, explicitly reviewed backward-compatible schema | Restore the previous application runtime/digest and verify it |
| Post-migration failure, incompatible or unreviewed schema | Stop writers and require incident response |
| Rollback verification fails | Stop writers and raise a typed rollback failure |

Automation never restores a database backup and never runs `alembic downgrade`. A database restore
is a separate, explicitly approved incident action. Preserve `delivery_unknown` and partial delivery
records; never blindly resend them.

## Evidence and diagnosis

Successful releases retain safe values only: commit, image digest, manifest and bundle checksums,
Alembic head, backup ID, Runner ID, service states/restarts, queue/delivery counts, and completion
time. Primary locations are mode-600 files under `/var/lib/edu-ai/releases`, the verified backup
evidence under `/var/backups/edu-ai/releases`, and the existing production evidence file.

Diagnose by the emitted `phase` and stable failure `code`. Do not paste full Docker inspection,
environment, provider response, object keys, or content into logs or tickets. A GitHub backup
failure is degraded backup status; it must not reverse-sync, roll back Codeup, or block a healthy
production release unless policy is later changed explicitly.

## Runner stop and removal

Record the exact Runner service name, workspace, stop command, disable command, and official
uninstall command from the Yunxiao enrollment UI during installation. The registration command is
time-limited and must not be copied into this runbook or a task result. In an incident, disable the
production Flow gate first, let any active `flock` owner finish or fail safely, then use the recorded
host-local stop command. Removal requires administrator approval and verification that no release
is active. Do not guess a package or service name.

## Final activation checklist

- Branch-safe Flow run passes without ACR, GitHub, Runner, provider, or WeCom side effects.
- Candidate image builds, resolves to one ACR digest, and passes offline/read-only probes.
- GitHub backup identity passes the exact-SHA dry run with strict host verification.
- Runner scope/concurrency, pull-only ACR identity, and recorded stop/uninstall procedure pass.
- Prior digest release and rollback snapshot prerequisites pass.
- Root entrypoint dry run passes against the exact candidate artifacts.
- Codeup protected `main` binds the verified pipeline ID.
- Only then may an administrator enable the relevant flags in order; production deployment remains
  last.
