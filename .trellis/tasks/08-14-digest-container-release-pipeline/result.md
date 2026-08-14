# Repository implementation result

## Status

Repository-side Phases 2–4 and their local verification are complete. The current supported
activation path has pivoted to an explicit developer-PC immutable release from Codeup `main`;
repository implementation, independent review, focused verification, and the final full gate for
that Phase 4.1 path are complete. Flow pipeline `5202972`
was updated from commit `e225ebdc7474e5e60c7939f8bc87208e06ca6a81`; CI-only run `6` failed
closed in the first capability probe because Docker CLI and Compose were present but the public
specified-container environment had no reachable Docker daemon. The source clone and commit
identity were correct. ACR,
GitHub-backup, Runner, and production activation remain intentionally incomplete; all three Flow
activation flags are checked in as `false`.

The frontend boundary is explicit and tested: `frontend-check` and API generation are local/CI
gates only. Both image builds use the `backend/` context, the release bundle allowlist excludes
`frontend/`, and the production matrix contains only the nine backend application/migration
services. The local/CI Vite gate may create an ignored `frontend/dist`; it is never included in a
release bundle or image, pushed to ACR, or deployed.

## Safe external facts verified by the operator

- Private Codeup repository ID `7328051`, path `marketingUseOnly/edu-ai-lead-agent`.
- Migrated `main` was verified at `4148acb581434c07ae1c08398c94e879acf00ef9`; the unintended empty
  `master` was inspected and removed after switching the default to `main`.
- `origin` is Codeup. `github-backup` is fetch-only locally with its push URL disabled; migrated
  reference SHAs were compared exactly.
- A dedicated expiring Codeup SSH identity was registered without replacing other identities.
- The GitHub repository-scoped backup key passed a strict-known-host dry-run write check. No key
  material or credential is recorded here.
- Codeup `main` protection is deferred until the real Flow pipeline ID and branch behavior exist.
- The reviewed repository implementation was committed as `a90ff18` and `3c2a507`; Codeup `main`
  was pushed and read back at `3c2a507c617e3c8752cbc7a9b9e1646f2fe1eba3`.
- The user created the private Codeup source connection in the Yunxiao console. CLI read-back
  verified type `Codeup`, numeric inventory ID `934667`, and the YAML-facing service connection ID
  `w4de9kbiwbdh3ncn`; the latter is now bound only at `sources.source.certificate`.
- Yunxiao Flow pipeline `5202972` was created as a safe CI-only bootstrap. Codeup checkout passed;
  run 2 failed closed because the managed runner's default `python3` is 3.5.0. No ACR, GitHub, or
  production stage was enabled or executed.
- The containerized runtime correction was committed and pushed to Codeup `main` as
  `286a83ba2f1751e1511d500bc38618ae9f99006b`. The existing CI-only pipeline was updated successfully
  with every external flag still `false`. Run `4` cloned the exact commit, then failed with the
  typed root cause `docker: command not found`; it did not reach ACR, backup, Runner, or production.
- The specified-container correction was committed and pushed as
  `e225ebdc7474e5e60c7939f8bc87208e06ca6a81`. Run `6` cloned that exact commit; its official
  alinux3 container exposed Docker CLI and Compose v2, but `docker info` could not reach the
  injected local Docker endpoint. It failed before any dependency, image, ACR, backup, Runner, or
  production action.
- Read-only official documentation/source review verified that public image-build tasks receive a
  temporary BuildKit sidecar and `DockerBuildPush` always uses `buildx --push`. That step cannot be
  treated as a documented reusable Docker/Compose daemon for later ordinary commands. A separate
  private build-cluster VM with Docker daemon/Compose would be required for future Flow automation;
  it is not being created for the current path, and the production host is explicitly excluded.

## Repository outcome

- Hash-locked runtime/dev Python inputs, pinned compiler version, regeneration/drift commands.
- Digest-pinned two-stage non-root backend image with OCI audit labels and defensive context.
- One local-or-digest `APP_IMAGE` contract shared by all nine backend/migration services.
- Strict manifest/schema, deterministic committed-object bundle, checksum/path/secret/migration
  verifier, and compatibility declaration.
- Serialized root deployment state machine with preflight, offline image probes, ordered quiesce,
  verified backup/snapshot, atomic activation, migration, staged restart, evidence, and bounded
  application-only rollback. Database restore/downgrade is never automatic.
- Inactive Yunxiao Flow contract for branch CI, backend image build, main-only ACR publication,
  one-way GitHub backup, and Tencent Runner deployment.
- Dockerized CI quality runtime: pinned Python 3.11/dev-lock image, digest-pinned Node 20, explicit
  UID/GID and HOME/tmp, command allowlists, fixed test-only DB/MinIO environment, and no default
  network. Existing regular Pydantic/Vite environment files are masked without creating absent
  paths; symlink/non-regular targets fail closed. Only `npm ci` receives registry egress; Python
  receives Compose-network access for the complete quality step after healthy PostgreSQL/MinIO and
  synchronous MinIO initialization.
- Both Docker-dependent CI jobs use mapping-form `runsOn` with the exact official Yunxiao alinux3
  linux/amd64 manifest digest. The quality job fails before dependency installation unless the
  scheduled environment exposes a working Docker daemon and Compose plugin.
- Updated doctor, backup/evidence helpers, README, production checklist/runbook, immutable-release
  runbook, and backend quality specification.
- `make release-prod` now performs a fail-closed local immutable release. Its dry run makes no
  fetch/build/push/SSH connection/transfer/deploy mutation. Real mode locks locally, fetches
  authoritative Codeup `main` into a detached temporary worktree, requires the local orchestrator
  to match that commit, runs the existing quality gates with sanitized side-effect-disabled local
  Compose inputs, reuses an OCI cache, builds only the backend, resolves/pulls/verifies the full
  digest, and runs migration/doctor before push and again against that digest.
- The local entrypoint creates and verifies the existing three-file release artifact set, copies
  each attempt into protected Git-common-dir evidence, transfers only those non-secret files using
  strict batch SSH with bounded connection/liveness settings, and calls the existing root-owned
  deployer. It accepts no positional or credential input and relies on the developer Docker
  credential store plus OpenSSH config/agent/known-host state.

## Independent Phase 4.1 local-release review fixes

- Source authority now accepts only the exact project Codeup URLs or the dedicated alias when it
  resolves to `git@codeup.aliyun.com:22`. Fetch uses an explicit main refspec with terminal and
  askpass authentication disabled; ambient Git/Make overrides are removed.
- Local build work rejects non-Unix Docker contexts and inline Docker auth. Compose is pinned to the
  isolated worktree with dotenv disabled, fixed local DB/MinIO values, blank provider/WeCom
  credentials, and every external-effect flag false.
- The local candidate passes migration/doctor before its first push. The pulled repository digest
  then has revision/source/created labels checked and passes migration/doctor again before the
  optional cache tag is updated.
- The external member checksum is bound back to the manifest. All three mode-0600 artifacts are
  retained under a mode-0700 local evidence directory, while only that fixed set crosses SSH.
- The production SSH alias must resolve to a distinct configured host with an existing known-host
  entry. If transport loss or interruption makes deploy status unknown, remote cleanup is deferred
  so it cannot race the root-owned state machine; completed/pre-deploy attempts still clean up.

## Independent Phase 2.2 review fixes

- Deployment now treats any attempted quiesce as mutable state, restores the prior release after a
  partial stop failure, waits for bounded health convergence, and rejects target-service restarts.
- Preflight and activation now enforce root-owned regular mode-600 release inputs/state, validate
  the prior eight-service digest/restart baseline, and bind the candidate to its pinned base-image
  label as well as commit/source labels.
- Backup execution has its own lock, keeps MinIO credentials out of process arguments, and requires
  strict mode-600 evidence whose PostgreSQL, brand-material, and MinIO hashes/counts are rechecked
  before activation. Rollback writes separate protected evidence and remains application-only.
- Migration graph validation now rejects duplicate revisions, missing parents, cycles, disconnected
  histories, and multiple heads. Archive/path and committed-secret regression coverage was retained.
- The host backup unit and root deploy wrapper resolve the active immutable runtime rather than a
  stale installed copy. Python lock checking restores the original locks even if compilation fails.
- Flow dependencies use job IDs accepted by the documented schema, both locally built and published
  images receive offline probes, display names fit documented limits, and the release-tool tests run
  inside the quality job. All external activation flags remain false.

## Verification

- Dockerized `make backend-check`: Ruff clean; mypy clean for 145 source files; 724 tests passed,
  79% coverage under Python 3.11.15 and the checked-in dev lock.
- Dockerized `make frontend-check`: OpenAPI contract, Prettier, ESLint, TypeScript, 38 Vitest tests,
  and local Vite build passed under Node 20.20.2; no artifact was promoted.
- Dockerized lock drift gate: `python_lock_check result=ok`; the package index is now explicit and
  Alembic is bounded below 1.19 to retain the migration-autogenerate contract.
- Dockerized `make doctor`: completed successfully against healthy Compose PostgreSQL/MinIO after
  the application image migration reached `20260814_0020`.
- Before the run-4 correction, the Dockerized release gate passed 29 tests. After the correction,
  the focused pipeline contract subset passed 8/8 and covers mapping-form pinned outer runtime,
  capability-probe order, wrapper arguments, environment masks, network isolation, and Flow order.
- Full-profile Compose render, all shell syntax, Flow YAML parse, `git diff --check`, and a
  high-confidence working-tree secret scan passed across 997 text files with zero matched patterns.
- Reachable Git history was scanned count-only across 1,513 text blobs with zero matched
  high-confidence secret patterns; no matching content or credential-shaped value was printed.
- Local backend image built from the pinned Python base digest. Network-none/read-only non-root
  `pip check`, application-import, OCI-label, workdir, and runtime-user probes passed. Because the
  review changes are not committed yet, this was a local candidate build; exact committed-object
  identity must be re-established by Flow after the reviewed commit exists.
- No live provider, WeCom, ACR, GitHub-backup, Runner enrollment, or production operation was
  performed. Flow was mutated only as the CI-only pipeline described above, with all external
  activation flags false; its failures occurred before any external release stage.
- Focused Phase 4.1 checks: `bash -n scripts/*.sh` passed,
  `deploy/release/tests/test_local_release.py` passed 19 tests, and the full focused
  `deploy/release/tests` suite passed 49 tests. Ruff and `git diff --check` also passed. The sandbox
  proves dry run reaches only local Unix-socket Docker/Compose, strict `ssh -G`/known-host, and
  cached exact Codeup identity probes; invalid repository/host/dry-run/secret/unknown environment,
  lookalike Codeup, missing known-host, and remote Docker inputs fail closed. Dynamic/static
  contracts cover dirty-source isolation, ambient environment neutralization, pre-push and exact-
  digest migration/doctor ordering, persistent artifacts, interruption-safe cleanup,
  noisy-output-safe result passing, nine gates, the exact artifact transfer, and strict SSH options.
- Final isolated Phase 4.1 full gate passed in one run: Python lock drift; Ruff; mypy for 145 source
  files; 724 backend tests at 79% coverage; 49 release tests under the hardened `/tmp:noexec` CI
  container; frontend OpenAPI/Prettier/ESLint/TypeScript, 38 Vitest tests, and Vite build; local
  application image build; migration to `20260814_0020`; doctor; all-profile Compose render; every
  shell syntax check; and `git diff --check`. PostgreSQL/MinIO used isolated disposable volumes and
  fixed local placeholders; provider/image/WeCom effects remained disabled and no external release
  operation ran.

## External activation blockers

1. Provision or select the exact project OCI/ACR repository and developer push scope without
   storing credentials in the repository; configure the production host's separate pull-only
   identity and strict developer SSH alias/known-host entry.
2. Establish a genuine previous digest release/current manifest on the host, verify the root-owned
   deploy entrypoint and backup timer, then pass the local orchestration dry run and the deployer's
   independent artifact dry run. Do not fabricate a rollback baseline from an unknown local image.
3. Perform one controlled developer-PC release from reviewed Codeup `main`, record the resolved
   digest and safe deployment evidence, and verify all nine backend services. No production
   frontend image/artifact/deployment is part of this action.
4. For optional later Flow automation, create or select a separate non-production private build
   cluster and obtain a green CI-only run. Do not install the CI Runner on production or
   auto-create a billable managed VPC cluster.
5. Bind the already dry-run-tested repository-scoped GitHub backup identity as a protected Flow
   credential and verify exact-SHA one-way behavior in Flow.
6. If Flow production automation is later approved, enroll the Tencent Runner from the official UI,
   record its exact stop/uninstall procedure,
   enforce concurrency one, and install a project-repository pull-only ACR identity.
