# Implementation Plan

## Phase 1: Curate workspace and release tooling

- [ ] Freeze path/size/hash inventory for every modified/untracked path; prove ignored `.env`,
  `.gemini`, `private/`, `output/`, caches, dependencies, and builds are not staged.
- [ ] Ignore LaTeX `.fls`, `.fdb_latexmk`, `.xdv`; retain report sources/generator/PDF/DOCX. Scan
  report/portfolio binary metadata without printing private content.
- [x] Rewrite the two Workbench authenticated-URL fixtures while preserving rejection assertions.
- [x] Implement a task-local mode-0600 offline release operator/harness consuming exact Codeup SHA,
  candidate image ID/bundle/source manifests, and current f20 baseline. Reuse reviewed fast-path
  controls without executing the unrelated dirty OCR driver.
- [x] Run `bash -n`, fake early/mid/late/signal recovery, source/image/archive/mode/owner/entrypoint
  tests, secret/diff scans, and independent Trellis review. Freeze operator hash.

## Phase 2: Full gates, commit, and authoritative push

- [ ] Run backend/real-PG, frontend, Workbench portfolio/eval, Python lock, release-tool, Compose,
  Doctor, shell, OpenAPI/generated contract, Alembic, secret, and diff gates.
- [ ] Review/stage all meaningful non-secret work in coherent commits: Workbench/shared refactors,
  OCR evidence/tools, reports, Trellis/spec/skill metadata, operator/harness, and release task.
- [ ] Run prospective committed-tree secret scan, fetch Codeup, require fast-forward, push all
  commits to `origin/main`, fetch again, and record exact full SHA. Do not push GitHub.

## Phase 3: Immutable offline candidate

- [ ] Create a clean detached worktree from fetched Codeup `origin/main`; rerun provenance-sensitive
  gates and prove no dirty byte is reachable from build inputs.
- [ ] Build the candidate from the explicit committed backend Docker context and exact verified
  production dependency base. Export a separate mode-0600 runtime-source overlay archive, image
  bundle, and exact manifests; label with full release/base/source identities.
- [ ] Validate exact image ID, OCI/classic graph, non-root ownership/imports, all Compose entrypoints,
  source hashes, `pip check`, production OpenAPI/runtime lock, Alembic `20260815_0021`, `.6`/`.7`,
  and no Workbench path through the supported production route/service/dependency graph or
  production frontend chunk, while accepting dormant modules in the image.
- [ ] Prove c66-to-final production dependency declarations and `runtime.lock` are unchanged;
  record the new pyproject hash separately, prove `mcp` remains dev-only, and reject any supported
  entrypoint import of it rather than requiring the old full-pyproject hash.

## Phase 4: Read-only preflight and protected stage

- [ ] Revalidate production f20 source/image/full+short markers, eight services/restarts,
  API/PostgreSQL/MinIO, scoring cardinality/effective `.6`, OCR/diversity true/true, volumes/
  capacity/timer, `.release.env` local tag, and safe logs.
- [ ] Capture two aggregate samples at least 15 seconds apart; require stable durable/provider/image/
  WeCom vectors, zero running/actionable/nonterminal/unknown work, no actionable legacy prompt job,
  and a sufficient scheduler window. Do not claim predictive create/claim coverage: no complete
  pure read-only projection API exists, and an unverified SQL mirror is out of scope.
- [x] Verify the retained seven queued copy rows are dated 2026-08-04 through 2026-08-11 and the
  retained legacy packages are before today; current-day actionable copy/package counts are zero.
  Gate current-day due copy work plus all running copy and nonterminal WeCom work, not inert history.
- [ ] Transfer exact checksum-bound artifacts to mode-0700 stage/all members mode-0600, load isolated
  candidate tag, revalidate hashes/image, and require candidate running count zero.
- [ ] Stop before mutation on any identity, env, business-state, scheduler, provider, or secret
  mismatch.

## Phase 5: Single offline activation

- [ ] Invoke reviewed operator exactly once with absolute paths/null stdin; lock before stopping
  dispatcher -> content -> governance -> acquisition -> API.
- [ ] Create/catalog-validate fresh PostgreSQL backup; verify env/source/markers/container/tag/image
  evidence and MinIO/brand manifests/volumes before `backup_ready=1`.
- [ ] Enforce `.env` sole scoring ownership; add explicit `.6` under old Compose only if absent;
  preserve OCR/diversity true/true and every unrelated byte.
- [ ] Retag rollback/shared/nine service tags to exact image ID; atomically overlay the exact
  reviewed runtime source/Compose manifest and full/short markers while effective scoring remains
  `.6`.
- [ ] Skip `minio-init` and the default `backend-migrate` command. Run only an explicit no-build/
  no-deps override `alembic -c alembic.ini upgrade head`; prove source metadata/counters unchanged,
  then run offline `.6`/v3 + `.7`/v4 probes and atomically switch only `.6 -> .7`.
- [ ] Recreate/start API, acquisition, governance, and content sequentially with explicit
  `--no-deps`; dispatcher last. Immediately before each scheduler/dispatcher require sufficient
  safe time and observed actionable/nonterminal plus legacy-prompt vectors zero, then require those
  vectors zero again after its start.
- [ ] Require exact candidate/restart-zero services, healthy infra/API, unchanged Alembic, `.7`/v4,
  OCR/diversity true/true, no Workbench production endpoint/service, old-image-running-zero, safe
  logs, and immediate plus 30-second aggregate stability.

## Phase 6: Evidence and closeout

- [ ] Run one independent read-only production review using actual paths/manifests; report PASS or
  exact recovery state and never make a second deployment invocation.
- [ ] Record Codeup SHA, image/source/bundle hashes, backup evidence, env transition, service/counter
  matrix, flags, and recovery disposition; mark unavailable evidence honestly.
- [ ] Run final task/diff/secret scans, commit and fast-forward push deployment evidence, update
  durable specs if needed, archive/journal, and do not redeploy the evidence-only commit.

## Rollback points

1. **Before Codeup push:** no remote/production change; fix and rerun gates.
2. **After push, before first stop:** stage/candidate may exist; production unchanged.
3. **Stopped, backup incomplete:** restart captured f20 containers; never use partial backup.
4. **Candidate installed under `.6`:** restore f20 source/tags/markers/image/services, dispatcher last.
5. **`.7`, no durable/nonterminal `.7`:** restore `.6` first, then f20 rollback is allowed.
6. **Durable/nonterminal `.7`, or zero cannot be proved:** stop all eight services—API,
   dispatcher, acquisition scheduler/worker, governance scheduler/worker, content scheduler/worker—
   retain candidate + `.7`, leave only PostgreSQL/MinIO, and request incident direction. No DB
   restore/downgrade/second run.
