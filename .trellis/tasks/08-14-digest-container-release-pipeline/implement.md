# Implementation plan

## Preconditions

- Do not create or mutate Codeup, Flow, ACR, GitHub credentials or the production Runner until the
  user approves the latest planning summary and `task.py start` marks this task `in_progress`.
- Preserve unrelated dirty `.agents/skills/` and `reports/` paths. Migration and release artifacts
  come from committed Git objects only.
- Use the Yunxiao PAT only through a transient non-echoing process environment; never persist or
  print it. Do not reuse the server password disclosed in chat.
- Any resource-level 403, ACR isolation failure, expired Runner command, checksum mismatch or
  unexpected production state is a hard stop.
- The approved current production path is a developer-PC one-command release from committed Codeup
  `main`; private/VPC Flow build clusters are deferred. Repository implementation and dry-run tests
  must not contact registry, SSH, production, provider or WeCom.

## Phase 0 — Reconfirm baseline and exact scope

- [x] Snapshot local/GitHub refs, `main` SHA, object/commit/tag counts, remotes, dirty paths and
      `origin/main`; verify no secret or private path is tracked.
- [ ] Reconfirm Yunxiao organization, code group `2071662` still empty for the target name, ACR
      connection `79934`, absence/presence of GitHub connections and host groups, and current PAT
      permissions without exposing credentials.
- [ ] Record the current production release/digests/health/backup timer/queues with read-only checks;
      do not install Runner or quiesce services.
- [ ] Run baseline Compose/API contract/backend/frontend/doctor checks and record current lock/
      Docker behavior.

## Phase 1 — Create and verify the Codeup authority

- [x] Create `marketingUseOnly/edu-ai-lead-agent` as an EMPTY private repository. If it already
      exists, stop unless its ID, emptiness/expected refs and ownership are independently verified.
- [x] Generate a dedicated expiring Ed25519 developer SSH key, mode `0600`; register only its public
      key with Codeup and verify the fingerprint. Do not replace existing personal SSH identities.
- [x] Push all committed branches and tags to Codeup; compare `show-ref`, default `main` SHA and
      object/reference coverage with the migration snapshot.
- [x] Rename remotes to `origin` (Codeup) and `github-backup` (existing GitHub), set Codeup upstream,
      and prove fetch/push routing without pushing dirty worktree files.
- [ ] Protect Codeup `main`, disable force push, and retain a server-side rollback path for an
      accidental empty/wrong repository without deleting the source GitHub repository.

## Phase 2 — Add deterministic build/release inputs

- [x] Add generated hash-locked runtime/dev Python dependency files plus a documented regeneration
      and drift-check command; keep `pyproject.toml` as the human source.
- [x] Pin the Python base image by digest and refactor `backend/Dockerfile` into deterministic
      builder/runtime stages with OCI revision/source/created labels and non-root runtime.
- [x] Add/review `.dockerignore` so secrets, `.git`, `.trellis`, reports, caches, local envs, tests
      not needed at runtime and private brand assets cannot enter the image context.
- [x] Give all nine application/migration services one shared `APP_IMAGE` contract while preserving
      local `build:` behavior; add a non-secret production release environment and `--no-build`
      deployment path.
- [x] Keep frontend build/type/test and API generation as local/CI-only gates; exclude frontend
      images, `frontend/dist`, and frontend services from ACR, release bundles, and production.
- [x] Add a versioned release-manifest schema, minimal release-bundle builder/verifier, migration
      rollback-compatibility declaration and secret/path allowlist checks.

## Phase 3 — Implement reusable deployment automation

- [x] Refactor common safe helpers rather than copying backup/evidence parsing. Add a root-owned
      deployment entrypoint with strict manifest/digest validation, `flock`, typed phase failures
      and safe structured output.
- [x] Implement preflight/pull/offline-image verification while production remains active.
- [x] Implement ordered quiesce, reuse and verify `edu-ai-backup.sh`, create previous runtime/image
      inventory, atomically activate runtime/release env/markers, and render full Compose profiles.
- [x] Implement one-shot MinIO/migration gates and phased API/acquisition/governance/content/WeCom
      restart with health, restart, queue and delivery invariants.
- [x] Extend `edu-ai-production-evidence.sh` and doctor/Compose checks with safe commit/digest/
      Runner/release-manifest fields; never emit credentials, private paths or content.
- [x] Implement bounded previous-application rollback only for unchanged or declared-compatible
      migrations; never restore database backups or run Alembic downgrade automatically.
- [x] Add unit/sandbox tests for malformed manifests, tag-only images, checksum/path traversal,
      concurrent deploy locks, phase ordering, pre/post gate failures, rollback eligibility,
      rollback failure and secret redaction. Provider/WeCom calls must be fake or absent.

## Phase 4 — Define and validate Flow without production activation

- [x] Add `deploy/yunxiao/pipeline.yaml` with source identity, branch CI, full quality gates,
      image build/test, main-only ACR publish, GitHub backup and Tencent Runner deployment stages.
- [x] Prove Flow builds only the `backend/` image and that the published bundle/deployment matrix
      contains no frontend artifact or production frontend action.
- [x] Reference only non-secret resource IDs in YAML. Bind feature jobs to no-production
      credentials; bind main-only jobs to the narrow ACR/backup/Runner scopes.
- [x] Replace reliance on the managed runner's Python 3.5 with a local Python 3.11 CI image and a
      digest-pinned Node 20 wrapper. Mask existing regular Pydantic/Vite environment files without
      creating absent paths, reject symlink/non-regular targets, preserve runner UID/GID, isolate
      HOME/tmp, and pass only fixed non-production DB/MinIO settings to the Python container.
- [x] Default both tool containers to no network, allow registry egress only for `npm ci`, then
      start/wait PostgreSQL/MinIO, run MinIO initialization synchronously, attach Python quality
      commands to the resolved project network, and keep frontend install/check/build CI-only.
- [ ] Create the project-specific Flow resource with production trigger disabled; read back and
      compare normalized YAML/name/source/branch conditions.
- [ ] Run feature/branch CI and a local-only candidate image build. Require complete checks and no
      ACR push, Runner job, production connection or external provider side effect.
- [ ] Bind the Flow check to Codeup protected `main` only after the pipeline ID and branch behavior
      are verified.

Safe activation progress: pipeline `5202972` exists as a CI-only bootstrap with every external
activation flag false. Codeup checkout succeeded; run 2 failed closed before tests because the
managed image exposed Python 3.5.0. The containerized runtime correction was committed/pushed as
`286a83ba2f1751e1511d500bc38618ae9f99006b`, applied successfully to that CI-only pipeline, and
started as run `4`. Run 4 cloned the correct commit, then failed closed because the default runner
had no `docker` command. Commit `e225ebdc7474e5e60c7939f8bc87208e06ca6a81` changed the two jobs
to the digest-pinned official specified-container mapping. Run 6 cloned that exact commit and
proved Docker CLI plus Compose v2 were present, but the injected local Docker endpoint had no
reachable daemon; it failed before dependency installation, ACR, backup, Runner, or production.
Official step/source review confirms `DockerBuildPush` always pushes through a temporary
image-build sidecar and cannot replace the ordinary Command/Compose gate. The next activation input
is no longer a private build cluster: the user approved the local immutable-release path below.
Do not use the production host for CI and do not auto-create a potentially billable managed VPC
cluster. Keep the checked-in Flow contract as a later portability target.

## Phase 4.1 — Add the developer-PC immutable release path

- [x] Add a `make release-prod`-style shell entrypoint with required non-secret OCI repository and
      strict SSH host-alias inputs, plus a no-mutation dry-run.
- [x] Resolve real releases from freshly fetched Codeup `origin/main`, create a detached temporary
      worktree, and run all quality/build/artifact operations there rather than the caller worktree.
- [x] Reuse local/registry Docker cache, push a commit tag, resolve and pull-verify a full OCI digest;
      rely only on the existing Docker credential store and expose no password/token flags.
- [x] Reuse `release_tool.py` to create/verify the bundle, member checksums and manifest; transfer
      only those fixed non-secret artifacts over strict batch SSH.
- [x] Invoke the existing root-owned `/usr/local/sbin/edu-ai-deploy`; do not duplicate its backup,
      migration, restart, evidence or rollback state machine.
- [x] Add sandbox tests for dirty-worktree isolation, missing/invalid config, dry-run non-mutation,
      command ordering, digest/tag rejection, strict SSH options, artifact allowlist and redaction.
- [x] Update README/runbook/quality spec, run focused static tests, and report a checkpoint.
- [x] Independently harden exact Codeup/committed-orchestrator identity, non-interactive fetch,
      local-Docker enforcement, ambient Compose/provider/WeCom isolation, pre-push and digest image
      exercise, persistent artifact evidence, known-host validation and interruption-safe cleanup;
      pass 19 local-entrypoint and 49 full release-tool focused tests.
- [x] Run the full gate once after the last production-code edit: lock drift, Ruff, mypy, 724
      backend tests, 49 release tests, API/format/lint/type/38 frontend tests/build, local image
      build, migration, doctor, full-profile Compose, all shell syntax and diff checks passed in one
      isolated side-effect-disabled run.

## Phase 5 — Activate ACR and GitHub backup boundaries

- [ ] Through service connection `79934`, enumerate only permitted ACR resources and select/create
      an isolated project repository. If authorization, edition, region, network or isolation fails,
      stop for administrator action.
- [ ] Verify Flow builder connectivity/allowlist and push one candidate commit tag; resolve and
      record the exact ACR digest, then run pull-by-digest and offline image verification. Do not
      deploy it.
- [ ] Create a GitHub repository-scoped backup identity/service credential without exporting an
      existing global token. Verify a no-op exact-SHA push and prohibit reverse synchronization.
- [ ] Exercise a safe backup failure and verify it is visible/degraded without changing Codeup or
      authorizing production from GitHub.

## Phase 6 — Enroll Tencent Runner and dry-run deployment

- [ ] Obtain the time-limited official non-Aliyun Runner install command from the Yunxiao UI. Audit
      its target organization/cluster and execute it interactively on the exact production host;
      do not store the command/token.
- [ ] Verify Runner systemd state, identity, workspace mode, outbound connectivity, project/task
      scope, concurrency=1 and documented stop/uninstall path. Confirm it cannot run feature jobs.
- [ ] Provision a target-repository pull-only ACR identity in the server's root-only credential
      store; verify pull-by-digest and deny/avoid push capability.
- [ ] Run the deployment entrypoint in dry-run mode against the candidate manifest: validate pull,
      labels, bundle, Compose, backups/readiness and predicted phase order without stopping services,
      migrating, enqueuing jobs, sending messages or calling AI providers.

## Phase 7 — Controlled first automatic release

- [ ] Re-snapshot production, require no running/ambiguous provider jobs, verify fresh rollback
      prerequisites and enable the protected-main production trigger.
- [ ] Create one reviewed no-business-change release commit through Codeup and let Flow run without
      manual approval. Do not manually invoke deploy or enqueue provider/WeCom work.
- [ ] Require CI, ACR digest, bundle, preflight, backup, migration, staged recreation, health/data/
      delivery evidence and stability sample to pass; verify all nine services use one digest and
      production performed no PyPI build.
- [ ] Verify GitHub backup reaches the same commit, Codeup remains authoritative, and no reverse
      trigger occurs.
- [ ] If a safe injected pre-activation failure test is feasible, prove failure closes before
      mutation. Do not deliberately fail a live post-migration deployment solely to test rollback;
      cover that branch in sandbox and retain the production rollback manifest.

## Phase 8 — Full checks, documentation and handoff

- [x] Run backend/frontend/API contract/Compose/doctor/shell syntax/lock drift/Docker build and
      runtime/full test gates; run `git diff --check` and high-confidence secret/history scans.
- [ ] Verify Codeup repository/protection/Flow read-back, ACR tag→digest, Runner status, GitHub exact
      backup SHA, production release manifest, backups, service matrix, queues, evidence and logs.
- [x] Update README/runbook/specs with daily push/release behavior, ACR/Runner credential rotation,
      failure diagnosis, rollback, Runner stop/uninstall and administrator-only activation inputs.
- [x] Independently review implementation against every PRD requirement and acceptance criterion;
      fix verified findings, rerun affected gates, then run the final complete quality gate once.
      Phase 2.2 covered source/commit/digest/manifest identity, hash locks, secrets, archive paths,
      migration compatibility, deployment locking/state/backup/application-only rollback, one-way
      GitHub backup, branch capabilities, closed external flags, Flow schema, the shared nine-service
      image contract, production `--no-build`, and the frontend local/CI-only boundary.
- [x] Record safe resource IDs, commit/digest/checksum evidence and any permission-blocked activation
      step in `result.md`; never record tokens, passwords, private keys or authenticated URLs.

## Validation commands and evidence

Exact commands may be adapted to the generated lock tool and Flow YAML schema, but the gates must
cover at least:

```bash
make backend-check
make frontend-check
make api-contract-check
make doctor
docker compose --profile governance --profile content --profile wecom config --quiet
bash -n scripts/*.sh
git diff --check
docker build --pull --label org.opencontainers.image.revision="$COMMIT" backend
docker run --rm --network none --read-only <candidate-digest> python -m pip check
```

Remote evidence must use the production release wrapper and safe SQL/count probes rather than
`make doctor` when Conda is absent. All log scans report counts only and never print matches.

## Rollback points

- **Before Codeup creation:** no external mutation.
- **After Codeup creation/before push:** leave an empty private repository or archive it only after
  explicit review; GitHub remains untouched.
- **After push/before authority switch:** restore local remote names; compare refs before retry.
- **After repository-side changes/before Flow activation:** delete/disable only the new Flow and
  leave Codeup history intact.
- **After ACR candidate push/before Runner:** retain the unused immutable image; do not deploy.
- **After Runner enrollment/before trigger:** stop/disable Runner using the documented command;
  production application remains unchanged.
- **During deployment:** use the server-local previous digest/runtime manifest and verified backups;
  automatic rollback is application-only and compatibility-gated. Database recovery is always an
  explicit incident action.
