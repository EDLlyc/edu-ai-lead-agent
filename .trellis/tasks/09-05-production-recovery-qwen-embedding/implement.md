# Execution plan

## Phase gate and ownership

- User approved the final recovery-first planning summary with "继续" on 2026-09-05.
- The implementation phase may now start within that reviewed scope.
- Main owns operations, production rollout, task/spec records and scoped commit. Once approved,
  Trellis implement/check sub-agents receive bounded file ownership and dirty-worktree fences,
  with native context injection or child-side fallback.

## Ordered work

1. Refresh baseline, full release markers and the seven-job frozen cohort; recheck time windows.
2. Audit/build bounded no-send diagnostics with explicit call caps and zero delivery side effects.
   Exercise current provider/client wiring, active-brand retrieval and copy input/output bounds.
   Historical input-limit failures are leads only until reproduced or otherwise evidenced.
3. Fix only confirmed blockers; add focused regression tests. Do not manufacture a patch if
   current code needs none. Review any newly required recovery operation against the PRD first.
4. Run focused offline and real isolated test-database checks. Independently review diagnostic
   isolation and release/rollback behavior before live provider calls or production writes.
5. If needed, ship a clean, task-only immutable release with the required backup/config fences.
6. Follow a fresh eligible slot through accepted copy, package validation and formal delivery.
   Respect no-topic, audit failures, unknown outcomes and expired windows.
7. Verify another scheduler/dispatcher pass does not duplicate sends. Record safe lineage and
   timestamps; report partial-source failures and unused official-account paths accurately.
8. Update actual learned specs, check and commit scoped work. Archive only when recovery
   acceptance is met; never present deferred Qwen migration as implemented.

## Approved follow-up: substantive scope (R7 / AC6)

1. Implement agent maps acquisition versus governed-selection inputs, literal version dispatch,
   configuration activation and expired-slot idempotency on the exact deployed source.
2. Main owns this task's artifacts/spec updates and operations. Implement agent owns scoped
   backend implementation/tests in the persistent `.trellis/worktrees/substantive-news-scope`, branch
   `release/substantive-news-scope-20260905`. Preserve unrelated main work and all historical
   version semantics. Do not include the unrelated reranker/Reviewer WIP.
3. Add new immutable substantive-topic and scoring identities with deterministic positive,
   incidental-mention, title/body and historical replay tests. No model/SSH calls by sub-agents.
4. Native check agent independently reviews/fixes only scoped implementation and tests in that
   clean worktree. Run lint/type/format, relevant unit/contract tests and isolated PostgreSQL
   tests for any affected config/projection/persistence boundaries.
5. Main verifies source/image/config rollout and no expired-slot replay before a scoped commit
   or activation. Preserve existing delivery windows and frozen jobs. Production recovery remains
   open until fresh actual formal delivery and repeat-pass nonduplication are observed.
6. A separate native implementer owns only `research/substantive-release/`: a narrowly bound
   derivative of the tested offline transaction for current base 5c560da and one-key scoring
   activation. Archived scripts stay untouched. The check agent independently reviews both code
   and release regressions before main may perform any production mutation. No generic release
   migration or unreviewed environment modification is included.

## Validation commands

```bash
python3 .trellis/scripts/task.py validate .trellis/tasks/09-05-production-recovery-qwen-embedding
conda run --name edu-ai pytest backend/tests/unit/test_content_worker_validation_wiring.py backend/tests/unit/test_brand_embedding_zhipu.py backend/tests/unit/test_content_scheduler.py backend/tests/unit/test_copy_generation.py backend/tests/unit/test_wecom_delivery.py -q
conda run --name edu-ai pytest backend/tests/integration/test_copy_generation_repositories.py backend/tests/integration/test_wecom_slot_delivery_concurrency.py -q
conda run --name edu-ai pytest deploy/release/tests -q
git diff --check
```

Read quality-guidelines before selecting exact Ruff/Mypy commands; expand gates by changed scope.
Integration tests use isolated test services, never production writes. Offline tests alone do
not satisfy terminal production delivery acceptance.

Context validation passes, but quality-guidelines.md exceeds the native 32 KiB injection limit.
The check agent must detect this warning and read the complete required guidance in bounded
chunks using child-side loading; a truncated injected prefix is not the complete quality contract.

## Operational gates

- Natural September 6 morning execution satisfied recovery AC2/AC3 with three independent formal
  deliveries and subsequent no-duplicate polling. The `.12` rollout is a separate transaction:
  the expired September 5 baseline cannot be reused, and the reviewed September 6 bytes must reject
  execution until the noon window closes at 13:30 CST or after the evening safety margin at 16:45.
- Production has no Qwen endpoint/key. Recovery stays on Zhipu; credential setup is deferred.
- Dirty config/Compose/doctor/topic-selection overlap: never stage or build the full workspace.
- Unknown future source/model outcomes remain possible; completion needs actual delivered state.
