# PRD: Broad Workspace Offline Production Release

## Goal

Commit and push the repository's current meaningful, non-secret work to authoritative Codeup
`main`, then deploy the production runtime from that exact clean commit through a reviewed offline
image/source fast path. The release includes `小赛洞察`, delivered-repeat `.7`, reviewed Agent
Workbench source/shared refactors, OCR evidence/tooling, portfolio/report deliverables, and all other
safe worktree content. Production must preserve enabled OCR/diversity, keep Workbench local-only,
and cause no manual business/provider/delivery action.

## Background and confirmed facts

- Fresh read-only production preflight on 2026-08-17 verified `f20db2060abcfd49b6236137838473ac6f0b7dd4`
  on local image `sha256:ce673857...`, with `IMAGE_DIVERSITY_ENABLED=true`,
  `IMAGE_OCR_ENABLED=true`, and scoring `.6`. This supersedes the older recorded c66 baseline.
- The active source overlay is not the complete f20 Git tree: all 307 paths are a Git-proven hybrid
  of the c66 baseline, the five f20 runtime copy-generation files, and `.gitignore` from
  `b0a4aab...`; the two f20-only test changes were never installed. The exact hybrid manifest,
  rather than a guessed commit-wide manifest, is the rollback source authority.
- Codeup `main` contains `小赛洞察`, delivered-repeat, Workbench, OCR evidence, reports, and the
  reviewed release tooling. The deployable identity is always the final fetched full SHA recorded
  in release evidence, never an earlier planning SHA.
- Initial inventory: 24 modified and 98 untracked paths covering Agent Workbench, shared DB/security
  refactors, OCR evidence/operators/tests, Trellis artifacts, portfolio assets, reports, and one
  skill-formatting edit.
- Workbench is intentionally local-only. Its source/shared helpers enter Git and the backend image,
  but the supported production Compose/release service graph, `api_main`, production OpenAPI,
  runtime lock, and production frontend do not expose it. `mcp==2.0.0` remains dev-only; manually
  overriding a container command to launch a dormant module is unsupported and not part of release.
- OCR runtime is already deployed. Current dirty OCR paths are task-local evidence/tooling; release
  acceptance preserves true/true flags and makes no paid/provider fixture call.
- No project `RELEASE_IMAGE_REPOSITORY` or Docker registry credential is configured locally, and
  production lacks a proven standard previous-digest/current-manifest baseline. A digest bootstrap
  is therefore an external follow-up, not a prerequisite for this user-requested release.

## Requirements

### R1. Publish the full safe workspace

- Preserve existing history and fast-forward push; never rewrite or force-push Codeup `main`.
- Commit every meaningful status-listed code, test, spec, task, Workbench, OCR evidence/tool,
  portfolio, report source, report deliverable, and skill-formatting path after review.
- Include user-facing PDF/DOCX/TeX and generators. Add ignore coverage for reproducible LaTeX
  `*.fls`, `*.fdb_latexmk`, and `*.xdv`; `.fls` exposes absolute local build paths, so compiler
  intermediates are not meaningful deliverables.
- Never add ignored/private material: real `.env`, `.gemini`, `private/`, `output/`, caches,
  dependencies, builds, credentials, or provider data.
- Rewrite the two Workbench authenticated-URL fixtures that match committed-secret policy while
  preserving their userinfo-rejection assertions. Require final committed-history scans to pass.
- Split coherent commits, push all to Codeup `main`, and do not push GitHub unless separately asked.

### R2. Final-tree quality and provenance

- Run backend, real-PostgreSQL, frontend, Workbench portfolio/eval, Python lock, release-tool,
  Compose, Doctor, shell, generated-contract, migration, secret, and diff gates on the exact final
  tree. Shared DB/security refactors require production regression coverage.
- Fetch Codeup again before push, require fast-forward, then fetch again and build only from a fresh
  clean detached worktree at the exact authoritative full SHA.
- Bind the explicit backend image-input manifest, separately reviewed active-source overlay
  manifest, OCI labels, offline image bundle, operator hash, remote stage, and production
  full/short markers to that SHA. The transport bundle and image build have distinct contracts; no
  dirty byte is a build or deployment input.
- Prove runtime dependency compatibility with c66 despite the Workbench dev-only pyproject change:
  production dependency declarations and `runtime.lock` must be byte/semantically unchanged,
  supported entrypoints must not import `mcp`, and the candidate must pass non-root imports plus
  `pip check`. Record the final pyproject hash separately instead of pretending it equals the base.

### R3. Production runtime boundary

- Deploy every production-runtime change present in the final commit, including `小赛洞察`,
  delivered-repeat, and reviewed shared Workbench query/security refactors.
- Keep Workbench unreachable through the supported production graph: no production route/OpenAPI/
  Compose service/runtime MCP/frontend chunk or deployment. Dormant image bytes are accepted;
  source availability is not production activation.
- Preserve exact OCR/diversity true/true settings, `glm-ocr` separation, and reviewed limits. Do not
  run OCR, Comfly, image generation, or any fixture.
- `小赛洞察` retains its implemented warning-enforced behavior; missing prefix is not a hard package
  rejection. Prove code/tests now, and inspect only a future natural run read-only.

### R4. Reviewed offline fast path

- Do not call `make release-prod`: it would require unavailable registry capabilities and a genuine
  previous digest baseline. Use one task-local, independently reviewed, checksum-bound operator
  derived from the proven c66 offline release controls.
- This local-tag path is a one-time exception to the committed digest-only release specification.
  The final Phase 1.4 summary must request explicit user approval of that exact exception; general
  approval to “push everything” is not treated as approval of the release mechanism.
- Transfer a verified mode-0600 image bundle, source archive/manifests, and operator into one unique
  mode-0700 protected stage. Load only an isolated candidate tag before quiescence; active tags and
  source remain unchanged.
- The operator is not application payload. It uses absolute paths, null stdin, exclusive backup
  lock, explicit phase flags, bounded cleanup, one invocation, and one recovery path.
- After backup/quiescence, retag the shared local tag and all nine service tags to the exact
  candidate image ID, atomically overlay the exact reviewed runtime source/Compose manifest while preserving active
  restrictive modes/owners, and update `.release-commit` full plus legacy `RELEASE_COMMIT` short
  markers. Preserve `.release.env` selecting the reviewed shared local tag.

### R5. Scoring activation and compatibility

- `.env` is the sole permitted owner of `CONTENT_SCORING_VERSION`; `.release.env` contains no
  scoring key. Duplicate/unexpected values block mutation.
- Keep effective scoring at literal `.6` while installing/probing candidate code. If absent, add
  explicit `.6` under old Compose only after rollback evidence exists.
- With all application writers stopped, offline-probe literal `.6`/v3 and `.7`/v4, then atomically
  change only `.env` to `scoring-v1-preview.7-delivered-repeat-history`.
- Preserve all other env bytes, especially OCR/diversity. Persisted `.6` runs retain their snapshot;
  no replay or manual new run is allowed.

### R6. Bounded production execution

- Revalidate the exact Git-proven hybrid source manifest plus f20 image/markers, eight restart-zero application services, healthy infra/API,
  env ownership, flags, volumes/capacity/timer, and safe logs before mutation.
- Take two aggregate-only samples at least 15 seconds apart. Require stable vectors, zero running/
  actionable/nonterminal/unknown work, and a safe scheduler window.
- Require no actionable legacy copy/package/delivery work using the prior `小赛洞察` prompt identity;
  do not let an old v17 job cross the content-worker upgrade.
- Historical copy jobs whose business date is before today and historical `awaiting_manual_use`
  packages are retained business records, not startup-actionable work: the copy worker claims only
  the current business date and direct WeCom auto-reconcile selects only today's packages. Count
  every running copy job, current-day due queued/retry copy jobs, current-day legacy packages, and
  every nonterminal WeCom job; do not block on inert historical rows.
- No complete pure read-only application API projects every startup reconcile create/claim, so this
  release does not claim predictive zero-create/zero-claim coverage and does not introduce an
  unverified SQL mirror. Immediately before each scheduler/dispatcher restart, require the existing
  actionable/nonterminal and legacy-prompt vectors to remain zero plus a sufficient safe window;
  start them sequentially and require the same observed vectors to remain zero after each start.
- If a scheduler/dispatcher creates work or any protected vector drifts after `.7`, stop all eight
  application services under the existing incident contract.
- Acquire the backup lock before stopping dispatcher, then content, governance, acquisition, and
  API until only PostgreSQL/MinIO remain.
- Create a fresh PostgreSQL dump/catalog plus env/source/marker/container/tag/image evidence; record
  MinIO/brand manifests and volumes without object mutation.
- Do not run `minio-init`, because it performs bucket/policy writes and this release has no MinIO
  change. Do not run the default `backend-migrate` command either, because it also executes
  `app.seed_sources`. Use an explicit no-build/no-deps command override for only
  `alembic -c alembic.ini upgrade head`; Alembic remains `20260815_0021` and source metadata/counters
  must remain unchanged.
- Restore API and application layers in dependency order with explicit `--no-deps` service
  recreation/start so Compose cannot rerun `minio-init` or the default seed command; dispatcher
  last. No enqueue, replay, retry, resend, fixture, provider call, or WeCom send is authorized.

### R7. Acceptance and rollback

- Require all eight services on the exact candidate image ID/revision at restart zero, healthy
  infra/API, unchanged Alembic, old-image running count zero, runtime `.7`/v4, OCR/diversity
  true/true, no production Workbench route/service, and immediate plus 30-second stable aggregates.
- Before durable `.7`, failure restores `.6`, f20 source/image/tags/markers/services, dispatcher
  last. Database restore and downgrade are never automatic.
- After durable/nonterminal `.7`, or whenever the operator cannot prove that both durable and
  nonterminal `.7` work are absent, stop all eight application services—API, dispatcher, acquisition
  scheduler/worker, governance scheduler/worker, content scheduler/worker—retain candidate + `.7`,
  keep only PostgreSQL/MinIO, and request incident direction.
- Record Codeup SHA, image ID/bundle/source hashes, backup evidence, env transition, service matrix,
  aggregates, and recovery disposition. Commit/fast-forward push final evidence after production
  actions stop; do not redeploy an evidence-only commit.

## Acceptance criteria

- [ ] Codeup `main` contains every meaningful non-secret current artifact; ignored/private material
      and compiler intermediates are absent.
- [ ] Full backend/frontend/Workbench/lock/release/Compose/Doctor/contract/migration/secret/diff gates
      pass on the committed authoritative tree.
- [ ] Offline image inputs, source-overlay artifacts, and production markers bind the exact Codeup
      full SHA and candidate image ID; no dirty/unreviewed byte enters the payload.
- [ ] Production runs `小赛洞察`, delivered-repeat `.7`, and reviewed shared runtime refactors;
      Workbench remains unreachable through the supported production graph and OCR/diversity
      remains true/true.
- [ ] Eight services are candidate/restart-zero; PostgreSQL, MinIO, and API are healthy; Alembic is
      `20260815_0021`; old image running count is zero.
- [ ] Runtime proves `.7` and `topic-veto-v4-delivered-content`; immediate and 30-second aggregates
      show zero release-caused business/provider/image/WeCom delta.
- [ ] Any failure performs at most one phase-correct recovery; no DB restore, downgrade, second
      deployment invocation, or hidden live test occurs.
- [ ] Final approval explicitly authorizes this one-time local-tag/offline exception to the
      repository's digest-only `make release-prod` contract.

## Out of scope

- Making Workbench production-accessible, installing runtime MCP, or deploying the frontend.
- Force-adding configuration, credentials, private assets, caches/output, dependencies/builds, or
  compiler intermediates.
- Forcing a `小赛洞察` delivery, replaying a topic run, or making any provider/WeCom test call.
- Establishing the standard registry digest/current-manifest baseline; this remains blocked on an
  exact project registry plus developer-push and production-pull credentials.
- Schema changes, MinIO/brand mutation, automatic DB restore, Alembic downgrade, or force pushes.

## Risks and deferred items

- Report deliverables enter Codeup history and must pass privacy/credential/path scans; production
  bundles still exclude them.
- Workbench shared query/security changes affect production even though the feature is local-only;
  full real-PG regression gates are mandatory.
- `小赛洞察` is best-effort/warning-enforced, not a hard acceptance gate.
- Future standard `make release-prod` requires the separate digest-container task's registry and
  previous-digest activation blockers to be completed.
