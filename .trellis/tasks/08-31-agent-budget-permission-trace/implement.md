# Agent 预算权限追踪统一化：实施计划

## Phase 0 — baseline

- [x] Read Agent Workbench, database, error/logging and quality contracts; inspect current high-collision diffs and migration head.
- [x] Freeze Workbench/MCP API, four-tool registry, limit/error and eval/portfolio baselines.

## Phase 1 — shared domain and ports

- [x] Add typed identity, role, event, artifact and budget policies with strict construction/serialization tests.
- [x] Add repository/gateway ports and pure authorization/allocation rules; recursion remains disabled by default.

## Phase 2 — durable ledger and gateway

- [x] Add migration/models/repository for governed runs, allocations, events and artifact metadata.
- [x] Implement atomic multi-dimension reservation/reconciliation, contiguous event append and artifact binding.
- [x] Implement default-deny capability gateway with role/task/artifact scope, timeout and byte limits.
- [x] Add real PostgreSQL concurrency, replay, cross-run, budget oversell and denial-before-handler tests.

## Phase 3 — Workbench compatibility

- [x] Adapt existing Workbench limits/tools/trace to the shared core without changing public wire projections.
- [x] Rerun MCP official SDK, model contract, loopback/API, citation, eval and portfolio capture suites.
- [x] Add bounded development-only shared timeline/status projection only if required by the weekly consumer contract.

## Phase 4 — checks and delivery

- [x] Run focused/full Ruff, mypy, unit/contract/integration, migration, API, Agent portfolio and privacy gates.
- [x] Dispatch Trellis check and repair verified findings.
- [x] Update the shared execution-governance code-spec and backend index.
- [x] Create one scoped commit after staged-boundary review and user confirmation.

## Risky files and rollback points

- High collision: Agent domain/runtime/tools/config/API/schema, DB models/migration head/OpenAPI and Agent specs.
- Prefer new shared modules and adapters; do not wholesale rewrite existing Workbench types.
- Disable new governed-run creation for rollback; do not delete existing trace rows silently.

## Pre-start gate

- [x] PRD/design/implement agree on default deny, safe trace and immutable root budgets.
- [x] Context manifests validate.
- [x] User approves the latest parent planning summary.
