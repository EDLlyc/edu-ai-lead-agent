# Immutable Digest Release Runbook

This runbook covers the repository contract for Codeup-authoritative, OCI/ACR-backed releases. The
current supported activation path is an explicit developer-PC immutable release; the developer PC
only needs to be online for that release. It is not an activation record. The checked-in Flow
definition remains a later portability path and keeps registry publication, GitHub backup, and
production deployment disabled until an administrator verifies every external gate.

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

Run 6 proved the public specified-container boundary more precisely: Docker CLI and Compose v2
were present, but the injected `DOCKER_HOST` had no reachable daemon. Yunxiao's native
`DockerBuildPush` step receives a temporary BuildKit sidecar for an image-build task and always
pushes its result; it does not provide a documented reusable daemon for later ordinary Command
steps. It therefore cannot replace the repository's PostgreSQL/MinIO Compose quality gate.

If automated Flow release is enabled later, assign both Docker-dependent CI jobs to a separate
non-production build-cluster node in default VM mode with a healthy Docker daemon and Compose
plugin. The current activation path does not require or create that cluster. The node must not be
the Tencent production host: CI image builds, test containers, caches, and cleanup are outside the
production trust boundary. Creating a managed VPC build cluster may incur charges and requires an
explicit administrator choice; never create one as an automatic fallback. A private Runner
enrollment command is generated only in the Yunxiao console and is short-lived, so neither the
command nor its token belongs in this repository or pipeline output.

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

## Developer-PC one-command release

Use this path only after the target OCI repository and production host are separately provisioned.
The command does not accept positional arguments. Configure the developer Docker credential store
for push access and an OpenSSH host alias whose normal config/agent and `known_hosts` entry are
already correct; do not pass a password, token, private-key path, or authenticated URL.

First perform the orchestration dry run:

```bash
RELEASE_IMAGE_REPOSITORY=registry.example/namespace/edu-ai-lead-agent \
RELEASE_SSH_HOST=edu-ai-production RELEASE_DRY_RUN=true make release-prod
```

This checks required commands, a local Unix-socket Docker daemon, Compose, the cached authoritative
`origin/main` commit, and strict local SSH alias plus `known_hosts` resolution. The Codeup remote
must be the exact project HTTPS/SSH URL or the dedicated `codeup-edu-ai` alias resolving to
`git@codeup.aliyun.com:22`; lookalike hostnames are rejected. The dry run does not fetch, create a
worktree, build, push, call `scp`, establish an SSH connection, or invoke the production deployer.
A missing repository/host, tag-shaped repository, inline auth environment, unknown `RELEASE_*`
input, missing capability, non-local Docker context, or non-Codeup origin is a typed failure.

After reviewing that plan, run the real release with the same two non-secret inputs:

```bash
RELEASE_IMAGE_REPOSITORY=registry.example/namespace/edu-ai-lead-agent \
RELEASE_SSH_HOST=edu-ai-production make release-prod
```

The entrypoint takes a local release lock, proves strict batch SSH and the installed root-owned
deployer, then fetches the explicit Codeup main refspec with terminal/askpass authentication
disabled. It creates a clean detached worktree at that exact commit and requires the running
orchestrator to match the committed copy. Ambient Git/Make overrides are removed; Compose is pinned
to the worktree, dotenv loading is disabled, local DB/MinIO placeholders replace host values, all
provider/WeCom credentials are blank, and every external-effect flag is forced off. The release
starts isolated PostgreSQL/MinIO, runs lock/backend/release/frontend/Compose/shell/source/secret
gates, reuses a repository-scoped `build-cache` image when available, and builds only `backend/`.
The local candidate passes migration and doctor before any push. After pushing the readable commit
tag, the entrypoint resolves and pulls the registry's full digest, verifies OCI
source/commit/created labels, and repeats migration plus doctor with that digest as the shared
nine-service `APP_IMAGE`; only then is the optional cache tag updated.

Only then does it use the existing release tool to build and verify exactly three non-secret
artifacts: bundle, member-checksum file, and manifest. The external member file is cross-checked
against the manifest, and each attempt is retained mode 0700/0600 under the local Git common
directory for audit and safe retry after a post-push failure. It copies only those files into a
mode-0700 remote temporary directory and invokes `/usr/local/sbin/edu-ai-deploy`. SSH/SCP use a bounded
10-second connection timeout plus 30-second keepalives with three missed replies allowed, so a bad
endpoint fails promptly while a valid long deployment retains liveness checks. The root-owned
state machine remains the sole owner of production preflight, backup, activation, migration,
phased restart, evidence, and rollback. Local tool containers/worktree and Compose volumes are
cleaned on exit; retained local evidence is not removed. The remote inbox is cleaned after
pre-deploy failures and completed deploy commands. If SSH transport fails or the client is
interrupted after deploy starts, status is unknown and the remote inbox is deliberately retained
until the root deployment lock/state is reconciled. A failed candidate may leave its immutable
commit tag/cache in the registry, but no production deployment can occur without the verified
digest artifacts and root entrypoint.

## Release artifacts

Release tooling builds artifacts from the exact committed Codeup Git object, never from
uncommitted workspace files.
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

Manifest creation also requires all nine named gate IDs. The checked-in release entrypoint or Flow
job derives those arguments from its completed gates; operators must not invent successful IDs
manually.

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
| Developer OCI publisher | Push only the isolated project repository | Local Docker credential store/helper; never a command argument or repository environment file; rotate independently |
| Developer production SSH | Host alias plus root deploy invocation only | Local OpenSSH config/agent and strict known-host entry; batch mode rejects password prompts |
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
the first local release or any later Flow activation. The backup script takes its own non-blocking
lock, so a timer run and deployment backup cannot write the same timestamped evidence concurrently.

Establishing that baseline is an administrator-controlled migration step, not an automatic
bootstrap shortcut. Do not fabricate a prior manifest for a locally built or unknown image.

Once a candidate digest, manifest, bundle, operator runner ID, and baseline are verified, invoke
the root-owned wrapper with `--dry-run`. This is separate from the local orchestration dry run
because it validates actual candidate artifacts and host state. It verifies the bundle, lock,
prior-release markers,
queues, image labels, non-root image identity, offline imports, `pip check`, and the full Compose
digest rendering. It does not quiesce, back up, migrate, restart services, enqueue work, contact an
AI provider, or send WeCom messages.

```bash
/usr/local/sbin/edu-ai-deploy \
  --manifest <release-manifest.json> \
  --bundle <release-bundle.tar.gz> \
  --expected-commit <40-character-codeup-commit> \
  --runner-id developer-pc \
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

- Reviewed Codeup `main` is the intended source, and the local orchestration dry run reports its
  cached commit with `mutation=false`.
- Developer push scope, production pull-only scope, strict SSH alias/known host, and the root-owned
  deploy entrypoint are independently verified without recording credentials.
- Prior digest release and rollback snapshot prerequisites pass.
- Candidate image resolves to one OCI/ACR digest and passes offline/read-only probes; the root
  entrypoint dry run passes against the exact candidate artifacts. A genuine prior digest/current
  manifest and root-owned deployment baseline remain mandatory; `make release-prod` does not
  create or guess them.
- Only then may an administrator execute the real `make release-prod` and verify safe evidence for
  the nine backend services. Frontend remains local/CI-only.
- If Flow automation is later resumed, independently obtain a green branch-safe run, strict
  GitHub exact-SHA backup proof, scoped Runner proof, and Codeup protected-main binding before
  enabling any corresponding flag. Production activation remains last.
