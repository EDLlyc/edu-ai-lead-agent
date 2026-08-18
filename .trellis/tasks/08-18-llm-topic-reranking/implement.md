# LLM 选题重排：实施计划

## Phase 1 — Domain contracts and pure ordering

- [x] Add versioned rerank config/request/result/outcome domain types and canonical fingerprints.
- [x] Add strict structured-output schemas, reason-code allowlist and bounded prompt builder.
- [x] Implement shared pool builder and pure rerank applier for daily and slot decisions.
- [x] Preserve threshold, veto, priority group, same-day exclusion, score totals and out-of-cap order.
- [x] Add deterministic fake independent from eval expected answers.
- [x] Unit-test 0/1 skip, cap 8, valid order, invalid IDs/permutation/group, daily Top 1, slot Top N and fallback parity.

## Phase 2 — Provider and composition

- [x] Add `TopicReranker` port and Zhipu JSON adapter using existing transport limits and safe error patterns.
- [x] Add settings/defaults/Compose example keys; enabling requires fake or Zhipu provider.
- [x] Build one optional shared reranker in `content_worker_main.py` and inject it into both executors.
- [x] Ensure repository read sessions close before network calls and no executor loops provider calls after a slot conflict.
- [x] MockTransport-test request schema, prompt isolation, timeouts/errors, usage, latency and redaction.

## Phase 3 — Durable config, audit and API

- [x] Add Alembic migration for run-level rerank config snapshots/fingerprints and `topic_rerank_records`.
- [x] Extend enqueue/reconcile identity checks to pin rerank config for daily and slot runs.
- [x] Persist final selection, score ranks and rerank audit atomically under the existing lease.
- [x] Add safe read projections and additive daily/slot API response fields.
- [x] Cover existing rows, feature-off behavior, lease loss, conflicts and DB constraints in real PostgreSQL tests.
- [x] Regenerate production OpenAPI and frontend client types; confirm Agent Workbench contract remains unchanged unless generated shared types require formatting only.

## Phase 4 — Eval, specs and final verification

- [x] Add sanitized provider-free contract cases for daily, morning, noon, evening, priority, hard veto, same-day exclusion and fallback.
- [x] Generate stable JSON/Markdown report clearly labelled fixture contract conformance.
- [x] Update topic-selection, content-slot, agent-pipeline, database and quality specs.
- [x] Run focused Ruff, strict mypy, unit/adapter/PG/API tests, migration head, eval drift, OpenAPI/client drift, Compose render, `git diff --check` and secret scan.
- [x] Run full backend gate only if focused changes or migration/shared-model changes reveal cross-layer risk; record the exact decision and result.

## Risk and rollback points

- Existing `.8` config snapshots are immutable: do not add rerank fields to `TopicScoringConfig` or change its fingerprint.
- Final rank must not erase deterministic evidence: persist base and final order separately.
- A fake adapter must not consume case oracle output; eval must not claim live editorial accuracy.
- Never use governance `ModelInvocationModel` for topic rerank; preserve its foreign-key/usage semantics.
- Do not hold DB sessions during provider calls or claim exactly-once provider behavior.
- Preserve unrelated report modifications and `.trellis/tasks/08-17-agent-workbench-public-portfolio/`.

## Pre-start gate

- [x] Goal, scope, hard-rule boundary, shared daily/slot behavior and deterministic fallback are documented.
- [x] Repository evidence and prior session search are complete; `trellis mem` returned no older matching decision.
- [x] Complex-task PRD, design and implementation plan are complete.
- [x] `implement.jsonl` and `check.jsonl` contain real task-specific context and validate without truncation warnings.
- [x] User reviews the final planning summary and explicitly approves implementation in a subsequent message.
