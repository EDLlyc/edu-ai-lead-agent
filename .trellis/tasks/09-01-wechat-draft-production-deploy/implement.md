# Implementation Plan

## Phase 1: Production eligibility and settings

- [x] Add default-off production acknowledgement and optional minimum-week settings with strict
      production/development cross-validation.
- [x] Add manifest-bound Monday eligibility to artifact staging, discovery, reconciliation, and
      explicit enqueue with a typed pre-activation skip.
- [x] Ensure a bounded complete scan filters historical candidates before eligible limiting and
      fails closed on scan overflow.
- [x] Extend settings/artifact/worker/CLI tests for missing/invalid cutoffs, historical skip, no
      copy/job/client call, next-week enqueue, starvation prevention, and safe projections.

## Phase 2: Optional runtime and release contracts

- [x] Add the portless optional Compose worker, read-only weekly inbox mount, separate persistent
      artifact volume, explicit settings, and Make/Doctor commands without adding it to the default
      service graph.
- [x] Extend release/static image entrypoint checks to recognize the optional service while keeping
      the ordinary production start/restore set unchanged.
- [ ] Mark migration review complete with `previous_application_compatible=false`; prove the exact
      `20260901_0042` graph and compatibility command pass.
- [x] Update the WeChat draft, directory, quality, and database specs to record the implemented
      production/cutoff/optional-release contracts.

## Phase 3: Local verification and commit

- [ ] Run focused unit/contract tests for settings, artifacts, worker, adapter, Compose, release,
      and doctor.
- [ ] Run PostgreSQL migration/job integration tests, strict Ruff/mypy, relevant weekly/WeCom
      regressions, full backend and release gates, Compose profiles, shell syntax, secret scan,
      task validation, and `git diff --check`.
- [ ] Independently run `trellis-check`; fix verified findings and rerun affected gates.
- [ ] Stage only this task's paths around the existing dirty workspace, commit coherent code/spec
      changes, fetch Codeup, require fast-forward, push Codeup `main`, and record the final SHA.

## Phase 4: New offline release artifacts

- [x] Create task-local builder/validator/operator/harness files with a new version/identity; do
      not edit or invoke the prior task's frozen operator.
- [ ] Capture and checksum-bind the read-only production `0036` baseline; accept an absent weekly
      volume as zero during preflight and create required named volumes only after activation.
- [ ] Derive clean Codeup source/image manifests and current Compose entrypoints including the
      optional worker; build one linux/amd64 candidate and validate its complete archive graph,
      labels, non-root imports, locks, Alembic, settings, and no-publish surface.
- [ ] Exercise fake preflight/backup/activation/recovery cases, including migration failure,
      optional-worker failure, null stdin, stale one-shot identity, volume-helper failure, cutoff
      drift, historical backlog, and no second invocation.
- [ ] Commit/push the reviewed task-local release evidence if it changes the authoritative operator;
      rebuild the candidate whenever the final commit changes.

## Phase 5: Production preflight and activation

- [ ] Fetch exact Codeup SHA; run read-only server preflight and two stable samples. Verify current
      baseline, backup capacity/locks, existing services, PostgreSQL/MinIO/API, credential presence
      booleans, WeChat IP allowlist prerequisites, weekly candidate count below the scan ceiling,
      zero current draft work, safe scheduler window, and no provider/business drift.
- [ ] Derive the first Monday strictly after activation in Asia/Shanghai and bind it into the
      operator/environment evidence.
- [ ] Transfer protected artifacts, load only the isolated candidate, and invoke the physical
      mode-0600 operator once with null stdin through the server-owned transient boundary.
- [ ] Quiesce, back up, activate source/image with draft flags false, migrate only to `0042`, restore
      and verify ordinary services, then atomically enable/start the optional worker.
- [ ] Require historical skips, zero draft jobs/attempts/provider writes at activation, worker and
      ordinary service health/restart-zero, safe logs, exact head, and immediate/30-second stable
      evidence.

## Phase 6: Closeout

- [ ] Record exact Codeup SHA, candidate/operator/source hashes, backup ID, migration result,
      cutoff, service matrix, safe job counters, provider-zero evidence, and recovery disposition.
- [ ] If code/evidence changes after activation, commit/push evidence only and do not redeploy it.
- [ ] Run final task/spec/diff/secret checks, archive the task, and record the Trellis journal.

## Validation commands

```text
conda run --name edu-ai pytest backend/tests/unit/test_wechat_official_account_draft*.py -q --no-cov
conda run --name edu-ai pytest backend/tests/contract/test_wechat_official_account_draft_cli.py -q --no-cov
conda run --name edu-ai pytest backend/tests/integration/test_wechat_official_account_draft_jobs*.py -q --no-cov
make backend-format-check backend-lint backend-typecheck
make release-tool-check
docker compose --profile wechat-official-account-draft config --quiet
bash -n scripts/*.sh
python deploy/release/release_tool.py check-migration-compatibility --base <full-base> --commit <full-head>
python3 ./.trellis/scripts/task.py validate 09-01-wechat-draft-production-deploy
git diff --check
```

## Rollback points

1. Before Codeup push: no remote/server change; fix and rerun gates.
2. After push but before quiescence: retain candidate evidence; production unchanged.
3. After quiescence but before migration: restore exact previous runtime and services.
4. After migration: no downgrade/DB restore/automatic previous-runtime rollback; stop application
   writers and request incident handling.
5. Optional activation with provable zero side effects: disable/remove only the optional worker and
   retain the verified candidate/core runtime; otherwise use rollback point 4.
