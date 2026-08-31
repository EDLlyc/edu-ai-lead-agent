# IP 图片检索 V3：实施计划

## Phase 0 — baseline and collision check

- [x] Read the task context and IP/database/quality specs; inspect scoped diffs and current migration head.
- [x] Freeze V2 ranking fixtures, current search API contract and provider-degraded tests.

## Phase 1 — V3 domain ranking

- [x] Extract or add one typed production rank-fusion helper with frozen constants and stable identities.
- [x] Keep a callable V2 selector, add V3 dispatcher/config and preserve filter/degraded/explanation behavior.
- [x] Add unit cases for metadata-only, semantic-only, overlap, ties, exact metadata priority and stale-turn filters.

## Phase 2 — offline evaluation

- [x] Add at least 40 sanitized cases, strict loader, dataset hash, V2/V3 scoring and oracle-isolation tests.
- [x] Emit canonical JSON/Markdown with Recall@5, MRR@5, nDCG@5, zero-result and category metrics.
- [x] Gate V3 non-regression and truthful report wording; add make/check integration if consistent with existing evals.

## Phase 3 — aggregate telemetry

- [x] Add migration/model/domain/port/repository for enum-keyed daily atomic counters and 30-day summary.
- [x] Count successful search/zero-result server-side and expose strict anonymous action/summary endpoints.
- [x] Wire search-origin preview/favorite/download telemetry in the frontend without blocking the primary action.
- [x] Add concurrency/timezone/privacy/API/generated-type/component tests.

## Phase 4 — checks and delivery

- [x] Run focused Ruff/format/mypy/unit/integration/eval/API/frontend tests, then applicable full gates and privacy scan.
- [x] Dispatch Trellis check and repair verified findings.
- [x] Update IP/backend/frontend specs.
- [x] Prepare and verify one scoped commit.

## Risky files and rollback points

- High collision: IP service/route/schema/repository/models, migration head checks, OpenAPI/generated types and IP frontend API/components.
- Rollback search through config to frozen V2; aggregate table is additive and independent.
- Stage generated/high-collision files by task hunk only.

## Pre-start gate

- [x] PRD/design/implement agree on strict aggregate privacy and V2 rollback.
- [x] Context manifests validate.
- [x] User approves the latest parent planning summary.
