# Independent check: minimal visual startup and queue repair

- Checked at: 2026-09-07T05:53:42Z (Asia/Shanghai 13:53:42).
- Reviewer: `/root/strict_visual_startup_check`; no nested agents.
- Candidate: `.trellis/worktrees/visual-quality-preview`, incremental working-tree changes above
  `4c353b2d924403efda91a5ad1967a6f8c50eaa79`.
- Scope: approved R18–R19 / AC16–AC17 only. Both implementation owners explicitly released their
  files before this independent gate. Root runtime and unrelated work were not used or edited.

## Verdict

**LOCAL_STARTUP_QUEUE_CHECK_PASS**. No new runtime or test defect requiring a reviewer code fix
was found. This is not deployment approval, whole-DAG completion, or production recovery evidence.

The minimal patch fixes the reproduced policy/execution coupling through the real Compose maps.
The bounded queue tests explain both practical completion and visible failure under the unchanged
wait/concurrency/budget configuration. No provider, SSH, daemon, build, migration, push, old-week
replay, draft replacement or public-publishing operation was performed by this reviewer.

## Verified behavior

- Actual `docker compose --env-file /dev/null --profile '*' config --format json` output is parsed
  through real `Settings(_env_file=None)` under a cleared process environment. All **15 Python
  roles** pass in disabled, strict and legacy-generated modes, including optional IP/fixture roles.
  The separately checked no-model-credential configuration also passes all 15 Settings projections.
- These matrices explicitly supply the observed live `IMAGE_PROVIDER_WINDOW_SECONDS=300`.
  They do **not** prove untouched zero-override Compose defaults: the pre-existing 900-second
  fallback versus Settings' 300-second bound is deliberately unchanged and remains documented in
  `visual-release-readiness-review-20260907.md`.
- The four Article identity owners select exactly equal full identities: no generated policy in
  disabled mode, literal V4 in strict mode, and literal V3 in legacy-generated mode. Reviewed actual
  API, weekly planner and DAG constructor call sites all use the shared identity builder.
- Only the Article worker receives generated execution permission and the explicit audit model.
  The three policy-only owners receive the default-false legacy alias derived from the existing
  generated opt-in; it neither grants execution nor requires another operator switch. Strict wins.
  Exact existing per-role credential-key sets are asserted; the incremental Compose diff adds no
  provider credential projection. Observe remains worker-only.
- Policy-only scheduler dependencies and the actual production DAG registry construct without an
  HTTP model client. Real Article `run_worker()` composes and reaches one fake idle claim in all
  three modes. Missing execution fails before engine creation/claim; missing or blank required
  keys and wrong strict model/base/image configuration fail Settings validation. No HTTP request
  reaches the rejecting MockTransport. Frozen strict execution disabled later fails explicitly
  with `strict_visual_configuration_changed`, without legacy fallback or fresh model work.
- Three controlled 288.249-second Articles execute serially exactly once each, complete at
  288.249 / 576.498 / 864.747 seconds, and are all observed ready by 866 seconds. The third wait
  times out at 720, receives the real service's available-at backoff of 722, and retries the exact
  frozen identity despite current-settings drift. Root cumulative elapsed is **1732 seconds**,
  not 866; all child reservations close.
- With 1000 seconds per Article, three first waits consume 2160 seconds. The first retry reserves
  900; the next two allocations are denied by the real 70% delegation calculation. Governance
  records `budget_denied` / `delegation_threshold_reached`; existing weekly mapping exposes terminal
  `permission_denied`. This pre-existing mapping is not broadened into a runtime change. Independent
  Articles finish by 3000 without changing the failed weekly results or repeating production.
- An unknown Article result remains terminal even after its initial queue timeout; duplicate
  enqueue resolves the same in-memory identity and never requeues its producer.

The timing tests execute real production handlers, `PostgresOfficialAccountWeeklyDagGovernance`,
`CapabilityGateway`, service failure/backoff, and repository `allocate_child` arithmetic. Storage,
its three allocation SQL reads/insert, and one serial Article producer are test doubles. This is
not PostgreSQL lock/idempotency proof, all 16 DAG checkpoints, or actual model latency. Earlier
committed strict PostgreSQL/provider-contract evidence remains separate and unchanged.

## Findings and spec synchronization

- Runtime/tests: no findings requiring a code fix after independent review and the gates below.
- The main-owned strict spec's two newly added generic `configuration_changed` labels did not
  match the existing exact runtime error. Reported to main; main corrected both to
  `strict_visual_configuration_changed` in root and candidate, and this reviewer rechecked them.
  The remaining new policy/capability/legacy-alias and queue paragraphs match actual code.
- Existing general-release baseline failures, the unrelated default-window mismatch, and the
  separately required current release transaction remain out of scope. No full-general-gate pass
  or live latency guarantee is inferred from this local increment.

## Verification

All commands below ran from the candidate repository, using the existing `edu-ai` interpreter.

```sh
PYTHONPATH=backend /root/anaconda3/envs/edu-ai/bin/python -m pytest \
  backend/tests/unit/test_official_account_strict_compose.py \
  backend/tests/unit/test_official_account_strict_visual_policy.py \
  backend/tests/unit/test_official_account_strict_visual_worker.py \
  backend/tests/unit/test_official_account_visual_generation.py \
  backend/tests/unit/test_official_account_local_api.py \
  backend/tests/unit/test_official_account_weekly_production.py \
  backend/tests/unit/test_official_account_weekly_dag.py \
  backend/tests/unit/test_official_account_weekly_material_preflight.py \
  backend/tests/unit/test_official_account_weekly_queue_timing.py \
  backend/tests/unit/test_execution_governance.py -o addopts='' -q
```

Result: **151 passed in 12.93s**, no failures or skips. Coverage was intentionally not collected;
the prior full baseline report is `visual-production-check-20260907.md`.

```sh
/root/anaconda3/envs/edu-ai/bin/ruff check \
  backend/app/core/config.py backend/app/infrastructure/official_account_runtime.py \
  backend/app/official_account_worker_main.py \
  backend/tests/unit/test_official_account_strict_visual_policy.py \
  backend/tests/unit/test_official_account_strict_compose.py \
  backend/tests/unit/test_official_account_weekly_queue_timing.py
/root/anaconda3/envs/edu-ai/bin/ruff format --check \
  backend/app/core/config.py backend/app/infrastructure/official_account_runtime.py \
  backend/app/official_account_worker_main.py \
  backend/tests/unit/test_official_account_strict_visual_policy.py \
  backend/tests/unit/test_official_account_strict_compose.py \
  backend/tests/unit/test_official_account_weekly_queue_timing.py
PYTHONPATH=backend /root/anaconda3/envs/edu-ai/bin/mypy --config-file backend/pyproject.toml \
  backend/app/core/config.py backend/app/infrastructure/official_account_runtime.py \
  backend/app/official_account_worker_main.py
git diff --check
```

Results: **Lint pass; all 6 Python files formatted; strict TypeCheck pass for 3 runtime files;
diff check pass.** No unchanged frontend, image generation, full integration infrastructure or
historical failure cleanup was repeated for this configuration-only runtime increment.
