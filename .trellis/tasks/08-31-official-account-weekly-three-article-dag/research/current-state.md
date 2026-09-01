# Current-state evidence

- `backend/app/domain/official_account_weekly_edition.py:27-33` owns versioned schedule/selection identity, timezone and fixed role order.
- `backend/app/domain/official_account_weekly_edition.py:403-475` owns due/week calculations; `:477-746` owns governed candidates, three-role selection and strict projection.
- `backend/app/application/services/official_account_weekly_edition.py:60-99,298-568` owns finalized child binding, aggregate validation, immutable artifact construction and no-clobber writer.
- `backend/app/official_account_weekly_edition_demo.py` and `official_account_weekly_edition_live_demo.py` currently execute whole local flows in one process and produce final artifacts without durable node state.
- `backend/tests/unit/test_official_account_weekly_edition.py` freezes schedule, selection, visual distinctness, child integrity, deterministic aggregate, operator state and writer behavior.
- Existing governance/copy/IP workers provide repository patterns for idempotent enqueue, `SKIP LOCKED` claim, leases, heartbeat/fencing and safe retries.
- `.trellis/tasks/08-27-official-account-editor-automation-v2/` owns the current weekly implementation but is still `in_progress` and uncommitted in a shared dirty worktree.

## Planning consequence

The DAG task is an orchestration/persistence layer over existing weekly domain/application functions. It may not recreate the selection policy, article renderer, mobile validator, aggregate bundle, visuals, live acquisition or operator-state machine.

## Prerequisite ownership resolution

- `trellis mem` sessions `01a0558f-3cd7-7b00-8bd9-3af9b47aee23` through
  `01a05686-1719-7860-b9fd-3290535c645e` identify the uncommitted weekly domain,
  service, CLIs, tests and spec as work owned by active task
  `08-27-official-account-editor-automation-v2`, not unknown user edits.
- Those sessions recorded passing focused weekly/V2 checks and explicitly reported that no commit
  was created. The DAG may depend on this owned baseline but must not rewrite its artifact rules;
  final delivery must make the baseline-before-DAG commit order explicit.
- Shared execution governance is committed in `19fe3ec` and archived under
  `.trellis/tasks/archive/2026-08/08-31-agent-budget-permission-trace/`.
