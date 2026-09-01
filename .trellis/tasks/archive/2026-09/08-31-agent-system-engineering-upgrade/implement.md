# Agent 系统检索、编排与治理升级：实施计划

## Phase 0 — planning and protection

- [x] Validate parent and all child artifacts; preserve the current dirty worktree and identify ownership of overlapping files.
- [x] Confirm the current Alembic head and freeze focused baselines before each child starts.

## Phase 1 — IP retrieval V3 child

- [x] Start `08-31-ip-asset-retrieval-v3`, dispatch implementation/check, update specs and create one scoped work commit.
- [x] Verify V2 rollback, V3 evaluator, anonymous aggregate schema and frontend origin wiring before archiving the child.

## Phase 2 — Agent governance child

- [x] Start `08-31-agent-budget-permission-trace`, dispatch implementation/check, update specs and create one scoped work commit.
- [x] Verify real-database budget atomicity, execution-layer default deny and exact Workbench/MCP compatibility before archiving the child.

## Phase 3 — weekly DAG child

- [x] Confirm the existing weekly implementation has a safe committed baseline or isolate its exact ownership before editing.
- [x] Start `08-31-official-account-weekly-three-article-dag`, dispatch implementation/check, update specs and create one scoped work commit.
- [x] Verify checkpoint recovery, branch-local retry, existing child byte preservation, unified governance events and zero WeChat calls before archiving the child.

## Phase 4 — parent integration

- [x] Run the cross-child privacy/contract/migration integration matrix and focused/full quality gates.
- [x] Update parent acceptance criteria and shared specs only for verified final contracts.
- [x] Present the scoped commit plan, commit any parent-only integration changes, archive the parent and record the session.

## Risky files and rollback points

- High collision: `models.py`, migration head tests, migration compatibility, Doctor, API routes/schemas, `backend/openapi.json`, generated TypeScript and shared Trellis specs.
- Roll back one child at a time through its version/config and migration contract; never revert unrelated working-tree changes.
- Do not start the weekly DAG child until the Agent governance work commit is available.

## Pre-start gate

- [x] Parent and child PRDs/designs/implementation plans agree on scope and dependency order.
- [x] Every `implement.jsonl` and `check.jsonl` has real spec/research entries.
- [x] `task.py validate` passes for parent and children.
- [x] User approves the final planning summary after these artifacts are presented.
