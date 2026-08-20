# Bounded implementation/check contract

This task-local summary extracts only the authoritative clauses needed from the oversized
`agent-pipeline.md` and `quality-guidelines.md` files so sub-agent context is not truncated.

## Pipeline boundary

- News selection consumes immutable governed event/evidence/source projections. It does not browse,
  generate copy/images, publish, replay, or mutate delivery state.
- Current scoring is `scoring-v1-preview.9-broad-hard-tech-pool`, threshold 0.59. Its hard vetoes
  remain authoritative: unresolved governance, ineligible evidence, Tier-C-only, unverified,
  unsuitable negative incident, privacy/legal/safety uncertainty, prohibited marketing,
  delivered repeat and stale event.
- `.9` may admit governed Tier-A/B hard-tech plans, failures, financing, events and product releases
  below the numeric threshold only with zero vetoes. Literal `.6`/`.7`/`.8` retain historical
  semantics.
- Topic rerank is ordering only. It receives at most eight already-eligible candidates, cannot
  change candidate identity/version, score, eligibility, veto, Ministry priority or slot same-day
  exclusion, and must preserve priority groups.
- Literal `topic-rerank-v1` and `topic-rerank-v2-zhipu-json-contract` are durable policy identities.
  Unknown policy identities and request/config mismatches fail before transport. Current v2 uses
  strict JSON-object mode, one complete permutation, allowlisted reason codes, disabled
  thinking/sampling and deterministic fallback.
- Model/provider/output failure must use the exact deterministic base order. No second judge call,
  unbounded retry or human-review state is permitted in this task.
- No database session may remain open across the provider call. Persistence atomically binds
  scoring/rerank snapshots, deterministic/final ranks, one rerank audit and one daily/slot decision
  under lease, FK, uniqueness and date/profile constraints.
- Public/durable audit contains safe IDs/orders/reasons/fingerprints/usage/latency/outcome/failure,
  never raw prompts, provider bodies, full articles, secrets or private paths.

## Automatic finalization requirements

- A new immutable policy owns the layered auto-finalization behavior; v1/v2 replay cannot be
  reinterpreted.
- Bind the outcome base order to the exact rerank pool produced for that run and bind every pool
  event/version to an eligible score in the frozen decision.
- Applied output must keep the exact candidate set, priority barriers, configured cap and slot
  same-day exclusion. A mismatch becomes typed deterministic fallback, not an exception that waits
  for human action.
- Zero candidates persists `no_topic` with no provider call; one candidate skips provider and uses
  deterministic selection.
- The finalizer reads the frozen run decision, not live defaults or a freshly crawled page.
  Persistence continues to enforce lease/config/date/FK/unique constraints.
- Downstream copy/image/OCR/Enterprise WeChat review and delivery settings are explicitly outside
  this task and must remain bytewise unchanged.

## Quality gates

- Pure domain tests: pool cap, zero/one skip, complete permutation, group barrier, cross-run pool
  mismatch, event/version mismatch, daily fallback parity, slot same-day behavior and no human state.
- Provider contracts: literal v1/v2 payload/parser replay and new policy strict JSON behavior;
  invalid provider output exposes only bounded typed diagnostics.
- Real PostgreSQL integration: immutable run config, one atomic rerank/decision audit, applied and
  finalization-fallback paths, lease loss and constraints.
- Provider-free canonical rerank eval must pass; it proves fixture contract conformance only.
- Run Ruff format/lint, strict mypy, focused tests, API drift, Compose render, Doctor contract,
  Alembic single-head/metadata parity, full `make backend-check`, `git diff --check`, and scoped
  secret/raw-provider-log scans.
- No live provider, source fetch, SSH, deployment, replay, delivery or production mutation.
