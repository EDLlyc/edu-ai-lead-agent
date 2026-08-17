# Implementation Plan — 图片供应商输出容错与品牌素材兜底

## Phase 1 — Adapter contract

- [x] Change the Comfly `gpt-image-2` request representation to explicit `url`.
- [x] Preserve closed-world URL/Base64/direct-raster/task parsing and all current download/raster gates.
- [x] Update adapter contract tests for URL primary plus valid Base64 compatibility and safe invalid-representation diagnostics.

## Phase 2 — Durable one-recovery state machine

- [x] Parameterize the existing one-shot provider-output recovery transition with an allowlisted initial error/recovery kind.
- [x] Persist and rehydrate the recovery cause through the existing safe fallback snapshot without a migration.
- [x] Keep the original controlled prompt/plan for representation recovery while deriving a distinct, replay-stable provider request fingerprint.
- [x] Route only `image_output_representation_invalid` through one recovery, then the existing validated catalog fallback.
- [x] Keep all URL/raster/security/integrity failures terminal and retain old provider-rejection/transient/quality/diversity behavior.

## Phase 3 — Cross-layer tests

- [x] Add non-isomorphic material-worker tests: first invalid → retry success; second invalid → catalog success; no asset/store failure → terminal.
- [x] Assert provider call counts, prompt/fingerprint identity, attempt counters, lease/replay behavior, one object, and one delivery job.
- [x] Assert fallback packages remain direct-delivery eligible and raw provider values never appear in snapshots/logs/API.
- [x] Run focused unit/contract/integration tests without live providers.

## Phase 4 — Specs and gates

- [x] Update backend error-handling, agent-pipeline, visual-diversity, WeCom and quality contracts where behavior changes.
- [x] Run Ruff format/lint, strict mypy, focused tests, full backend tests, API drift and repository diff/secret checks.
- [x] Use `trellis-break-loop` to record why format failures previously bypassed fallback and how tests prevent recurrence.
- [x] Record exact gates and changed files in `result.md`.

## Release Boundary

- [x] Do not call Comfly/Zhipu/WeCom or production during ordinary implementation gates.
- [x] Do not replay or resend the 2026-08-17 noon package.
- [x] Do not deploy until separately authorized after implementation/check completion.
