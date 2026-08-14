# Codeup / Flow / ACR fixed-digest delivery design

## 1. Architecture and trust boundaries

```text
developer
  │ SSH, normal Git writes
  ▼
Codeup marketingUseOnly/edu-ai-lead-agent (authoritative)
  ├── feature branch ──> Flow CI only
  ├── protected main ──> developer-PC explicit immutable release (current)
  ├── protected main ──> Flow CI/build/push/deploy (portable later path)
  └── one-way backup ──> GitHub EDLlyc/edu-ai-lead-agent (never a trigger)

Flow managed build environment
  ├── quality gates
  ├── deterministic application image build and offline runtime tests
  ├── ACR push via service connection 79934
  └── signed/checksummed non-secret release bundle + release manifest

ACR project repository
  ├── readable git tag
  └── immutable sha256 digest ──pull-only──> Tencent Cloud production host

Tencent Cloud production host
  └── Yunxiao Runner deploy job
      ├── verify release bundle/digest
      ├── lock + preflight + backup
      ├── migrate + staged Compose recreation
      ├── health/data/delivery evidence
      └── bounded previous-image rollback

Developer release workstation (online only during release)
  ├── fetch and isolate exact Codeup origin/main commit
  ├── locked quality gates + cached backend image build
  ├── OCI push and registry digest verification
  ├── existing release_tool bundle/manifest build + verification
  └── strict SSH transfer ──> existing root-owned production deploy entrypoint
```

Codeup owns source truth, ACR owns built-image truth, and the server-local release manifest owns the
deployed commit/digest/backup relationship. No layer infers one identifier from a mutable tag.

## 2. Repository cutover

Create the target Codeup repository with `readMeType=EMPTY`, `visibility=private`, and
`namespaceId=2071662`. Before pushing, snapshot the source `git show-ref`, object count, `main` SHA,
branches, and tags. Push all branches and tags from committed Git objects only; the dirty worktree
and untracked reports/task artifacts cannot enter migration by accident.

After remote verification:

- rename the current GitHub remote to `github-backup`;
- add Codeup as `origin` using a dedicated expiring developer SSH key;
- set `main` upstream to Codeup;
- protect Codeup `main`, disable force push, bind its required Flow check, and prevent ordinary
  feature branches from receiving production credentials;
- keep GitHub outside the source/trigger configuration.

The GitHub backup is a one-way Flow job using a repository-scoped write identity. It pushes the
exact Codeup `main` SHA and release tags, never force-fetches from GitHub, and never feeds a result
back into Codeup. Because Codeup remains the durable source, backup failure is recorded as a
degraded/alerted job but does not authorize a reverse sync or corrupt a completed production
release. The organization currently has no GitHub service connection, so this identity is a
one-time activation input.

## 3. Version-controlled pipeline contract

Keep the auditable Flow YAML under `deploy/yunxiao/pipeline.yaml`. External resource IDs and names
may be committed; credentials and one-time enrollment tokens may not. Create or update the Flow
resource from this YAML with the official DevOps CLI, then read it back and compare the normalized
configuration before enabling triggers.

The pipeline has branch-scoped capabilities:

1. **Source/identity** — checkout Codeup, require a full 40-character commit, reject dirty or
   unexpected refs, and calculate source/release manifests.
2. **Quality** — lock drift, backend, frontend, API contract, Compose, doctor, shell syntax,
   migration-head, diff, and secret-shaped-content gates. Frontend work ends at this local/CI
   gate; no frontend artifact is promoted.
3. **Image build/test** — build one backend application image from the exact commit and run non-root,
   import, migration, entrypoint, file/provenance, `pip check`, read-only and network-disabled
   runtime probes.
4. **Main-only ACR publish** — push a readable `git-<short-sha>` tag through connection `79934`,
   query the registry result, and persist the full repository digest. Never deploy a local image ID
   or a tag.
5. **Main-only GitHub backup** — push the exact commit/release tags using a repository-scoped
   credential; expose only safe status metadata.
6. **Main-only production deploy** — transfer the checksum manifest, release bundle and digest-only
   release manifest to the Tencent Runner and invoke the root-owned deployment entrypoint.

The managed runner's preinstalled language runtimes are not part of the contract. Flow first builds
a local, non-published Python 3.11 quality image from the hash-locked dev dependencies and uses the
digest-pinned Node 20 image for frontend quality only. Both wrappers run as the workspace UID/GID,
use isolated HOME/tmp paths, mask existing regular Pydantic/Vite environment files without creating
absent paths, reject symlink/non-regular mask targets, allowlist commands, and never pass through
the host environment. Before backend tests, Flow waits for healthy PostgreSQL/MinIO, runs the
one-shot initializer synchronously, resolves the Compose project network, and gives only the Python
quality container that network plus fixed non-production database/storage settings. Python
otherwise uses no network. Node uses registry egress only for `npm ci`; later frontend checks are
offline. The Node container is never an application image and is never published or deployed.

The Docker-dependent quality and candidate-image jobs require a real Docker daemon. Live run 6
proved that Yunxiao's public specified-container environment exposes Docker CLI and Compose but no
reachable daemon. The native `DockerBuildPush` step receives a temporary image-build BuildKit
sidecar and always pushes; it is not a reusable Compose runtime for ordinary Command steps. The
accepted execution environment is therefore a separate private build-cluster node in default VM
mode with Docker daemon and Compose installed. It must not be the Tencent production host. A
managed VPC cluster is an administrator-selected, potentially billable alternative and is never
created automatically.

### 3.1 Current activation path: developer-PC immutable release

The supported current release is an explicit local operator action such as `make release-prod`.
The repository root may be dirty, so the orchestrator fetches Codeup `origin/main`, resolves one
full commit, and creates a detached temporary worktree from that object. Every quality/build and
artifact command runs in that isolated worktree; no report, local `.env`, current branch edit, or
untracked task file can enter the image or release bundle.

Dry-run is a local plan/preflight mode: it does not fetch, create a worktree, build, push, open an
SSH connection, transfer files, or invoke production. It validates required non-secret inputs,
cached `origin/main`, executable capabilities, repository/SSH target syntax, existing SSH config
resolution, and the ordered stage plan. Real mode then:

1. fetches only Codeup `main` through the existing `origin` configuration and verifies the resolved
   commit/source identity;
2. runs locked quality/release gates in the detached worktree with provider/WeCom disabled;
3. reuses a registry cache image when present, builds the backend with commit/source/created OCI
   labels, pushes a readable commit tag, resolves and pulls the exact registry manifest digest;
4. builds and independently verifies the existing allowlisted bundle, member checksum file and
   release manifest bound to that commit/digest and local gate IDs;
5. creates a mode-0700 remote inbox over `BatchMode`, strict host-key checking and disabled
   password/keyboard-interactive authentication; transfers only the three verified non-secret
   artifacts with fixed filenames;
6. invokes `/usr/local/sbin/edu-ai-deploy` through non-interactive sudo with those fixed paths. The
   existing root-owned state machine exclusively owns pull/preflight, backup, quiesce, migration,
   staged recreation, evidence and compatibility-gated application rollback.

The OCI repository and SSH host alias are required operator inputs. They are validated but never
invented. Docker obtains registry authentication from its configured credential store; SSH obtains
identity and host-key policy from OpenSSH config/known_hosts. The orchestrator has no password,
token or private-key command-line option and never generates a credential file.

The image context is `backend/`; the release allowlist excludes `frontend/`; and deployment covers
only the nine backend application/migration services. The pipeline never creates or publishes a
frontend image, uploads `frontend/dist`, or changes production frontend/static hosting.

Production deployment is serialized. A newer main update may supersede a queued older run, but an
already-started migration/deploy cannot be interrupted by another release.

## 4. Deterministic image and dependency contract

`backend/pyproject.toml` remains the human-maintained dependency source. Add generated,
version-controlled hash-locked runtime and dev requirement files. Regeneration uses one documented
tool version and CI fails when regeneration changes either lock file.

Refactor `backend/Dockerfile` to:

- pin the Python base image by digest;
- resolve/download dependencies only in a builder stage from the checked-in hash lock;
- install the built application into a minimal runtime stage without resolving dependencies;
- retain `USER app` and `/app` ownership;
- accept OCI label build arguments for full Codeup revision, source URL and build timestamp;
- exclude caches, tests, local environments, reports, task files, `.git`, secrets and private brand
  materials through a reviewed `.dockerignore`.

The nine backend migration/application services share one Compose image variable. Local
development may keep the existing build path and a local default tag; production always supplies a
validated `APP_IMAGE=<acr-repository>@sha256:<64-hex>` through a non-secret release environment and
uses `docker compose --no-build`.

The build publishes a release manifest containing only safe data:

- schema version;
- full Codeup commit and short release marker;
- image repository/digest and readable tag;
- Dockerfile/base-image/dependency-lock hashes;
- release-bundle/member-manifest hashes;
- Alembic head and backward-compatibility declaration;
- gate result identifiers and build timestamp.

## 5. ACR boundary

Use service connection `79934` only after a live resource-level preflight shows a suitable ACR
instance and an isolated project repository. Prefer a namespace derived from the marketing project
and repository name `edu-ai-lead-agent`; accept an administrator-supplied existing namespace when
it remains project-isolated. Do not create a second service connection or use another project's
repository as fallback.

For a managed Flow builder using a public ACR endpoint, verify the Flow egress allowlist before the
first push. If the organization provides a compatible private/VPC build cluster, VPC push is
allowed, but production remains the Tencent host. The production Docker credential is pull-only,
root-readable, scoped to the target repository and separate from the Flow push identity.

Do not modify ACR lifecycle deletion in this task. The current and immediately previous successful
production digests and their manifests are hard rollback dependencies. Key-backed image signing is
deferred until the company provides a KMS/signing identity; source commit + hash lock + OCI labels +
release manifest + content digest form the first provenance boundary.

## 6. Release bundle and server layout

CI creates a minimal allowlisted runtime bundle from the commit, not the working tree. It contains
only Compose/deployment/backup/evidence inputs needed on the host and excludes `.env`, `private/`,
`.git`, `.trellis`, reports, build output and caches. A member list and per-file SHA-256 manifest
travel with it.

```text
/opt/edu-ai-lead-agent/                active runtime; .env/private preserved
/opt/edu-ai-releases/<full-commit>/    immutable verified staging tree
/var/lib/edu-ai/releases/              release manifests and final evidence, mode 0700/0600
/var/backups/edu-ai/releases/          previous runtime/image/marker inventory
/var/backups/edu-ai/{postgres,minio,brand-materials}/
/var/lock/edu-ai-deploy.lock           deployment serialization
```

The active runtime gains a non-secret release environment holding only the exact application image
digest and release marker. Production `.env` remains mode `0600`, is checksummed before/after, and
is never transferred to Flow. Runner execution uses a root-owned, argument-validating deployment
script through the narrowest supported service identity; its workspace and enrollment files are
not part of the application release.

## 7. Deployment state machine

1. Acquire the deployment lock and reject a duplicate/older commit.
2. Verify the release manifest schema, commit, digest format, bundle/member checksums, active
   Compose project/volumes, disk/inodes, backup timer, runner identity and safe queue state.
3. Pull the digest with the server's repository-scoped credential while production is live; inspect
   labels/user/workdir, run offline/read-only imports and require the digest to match the manifest.
4. Quiesce dispatcher, content, governance, acquisition workers/schedulers and API in dependency
   order. PostgreSQL and MinIO remain healthy; all durable running-job counts must be zero.
5. Reuse `edu-ai-backup.sh`, verify PostgreSQL/MinIO/brand checksums, and record old bundle,
   markers, full image digests, protected inputs and restart counts.
6. Stage/activate only the runtime allowlist; preserve `.env`, private data, volumes and unrelated
   files. Atomically switch the non-secret release environment and markers.
7. Render all Compose profiles with the digest and `--no-build`; run `minio-init`, then one-shot
   migration. Require the expected Alembic head and invariant source/queue counts.
8. Start API/acquisition, then governance, then content, then WeCom. Gate each phase on target
   digest, health, restart count, bounded safe logs and durable queue/delivery invariants.
9. Run the production evidence script, secret scan and a stability sample; persist final evidence
   and mark the release successful.

No manual provider smoke, manual job enqueue, external message resend or business-data mutation is
part of deployment verification.

## 8. Automatic application rollback

Before migration, compare the target Alembic head with production. Automatic image rollback is
eligible only when the head is unchanged or the release contains an explicit reviewed declaration
that the previous application remains compatible with the new schema. CI rejects migration changes
without that declaration.

On post-activation failure:

1. stop newly started application services in reverse dependency order;
2. restore the previous runtime bundle, release environment and application digest;
3. recreate the previous application with `--no-build` and verify health/data/delivery invariants;
4. record the failed target and rollback result without deleting either manifest.

PostgreSQL/MinIO backups are never restored automatically, and Alembic downgrade is never called.
If migration is failed/ambiguous or rollback compatibility is absent, leave writers stopped,
preserve evidence and require explicit incident handling.

## 9. Secrets and operational controls

- Yunxiao PAT is provisioning-only and transient; it is not a pipeline secret. The PAT disclosed in
  chat should be rotated before long-term administration.
- Developer Codeup SSH, GitHub backup identity, Flow ACR push connection, production ACR pull
  identity and Runner enrollment are separate credentials with separate scopes.
- Pipeline commands never place secrets in command-line arguments or generated manifests. Secret
  scans run before artifact upload and on bounded server logs without printing matches.
- The local release command accepts only non-secret repository/host identifiers. Registry login and
  SSH authentication must already exist in Docker/OpenSSH stores; secret flags, password stdin,
  generated auth files, relaxed host-key checking and `sshpass` are forbidden.
- Runner installation is a one-time controlled change. Verify its systemd service, owner,
  workspace permissions, outbound endpoints and uninstall command before enabling the production
  stage. Thereafter normal main releases are fully automatic.

## 10. Compatibility and rollout

No business schema/API behavior is intentionally changed. Compose local developer commands continue
to work. Production migration from local `build:` tags to `APP_IMAGE@digest` is staged:

1. create/verify Codeup repository and remotes;
2. land repository-side locks, Docker/Compose/release scripts and Flow YAML through normal review;
3. configure only the non-secret OCI repository and strict SSH host alias, then run the local
   release entrypoint in no-mutation dry-run mode;
4. perform one controlled developer-PC digest release with no manual AI/provider/WeCom side
   effects and retain its manifest/evidence;
5. keep Flow CI-only until a suitable non-production Docker daemon becomes available;
6. optionally migrate the same repository contract to Flow automation without changing production
   digest, bundle or root deploy semantics.

Every phase has an explicit stop point; no partial resource setup is represented as production
ready.
