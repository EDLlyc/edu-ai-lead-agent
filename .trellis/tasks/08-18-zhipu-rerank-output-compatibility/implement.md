# Implementation Plan: Zhipu Topic-Rerank Output Compatibility

## Phase 1 — Freeze version and shared contracts

- [x] Add explicit legacy/current rerank policy constants and supported-policy validation.
- [x] Bump current defaults in domain config, `Settings`, Compose, and `.env.example`; preserve
  historical migration snapshots and literal v1 parsing.
- [x] Extract the existing bounded JSON-object envelope scanner into a shared provider helper with
  behavior-preserving copy-generation imports/tests.
- [x] Add the topic-specific invalid-output error carrying only bounded diagnostics and metrics.

## Phase 2 — Implement the versioned prompt and adapter

- [x] Keep the v1 prompt and request/parsing behavior as the legacy branch.
- [x] Add the v2 exact JSON shape, seven literal reason codes, exact count/ordinal/permutation rules,
  priority barrier, no-Markdown/no-prose rule, and existing untrusted-data isolation.
- [x] Add v2 `thinking=disabled` and `do_sample=false` while retaining JSON mode, zero temperature,
  timeouts, response-byte bounds, one configured operation, and output-token cap.
- [x] Route v2 content through the shared bounded envelope scanner, then the unchanged strict item
  and semantic validators.
- [x] Split completion, JSON-envelope, and schema error diagnostics; preserve safe metrics in
  deterministic fallback.

## Phase 3 — Regression tests

- [x] Unit-test v1/v2 metadata and prompt selection, exact reason-code/schema text, candidate-data
  isolation, and unknown-policy rejection before transport.
- [x] Contract-test exact v2 payload, pure/fenced/bounded-affix JSON compatibility, and independent
  provider-shaped success output.
- [x] Test arrays, multiple structures, ambiguous fences, oversized affixes/content, malformed
  JSON, extra fields, string ordinals, unknown reason codes, invalid UUIDs, blank/long text, and
  output usage beyond bounds.
- [x] Test bounded `loc`/`type` diagnostics and absence of API key, prompt, candidate text,
  completion content, response body, and exception text.
- [x] Test that invalid output performs one provider operation, returns the exact base order, keeps
  safe prompt/usage/latency, and exposes only generic `invalid_provider_output` publicly.
- [x] Keep full permutation, duplicate/missing/unknown ID, and priority-barrier tests green.

## Phase 4 — Documentation and local gates

- [x] Update backend topic-selection, Agent pipeline, error-handling, and relevant quality/logging
  contracts with the versioned structured-output behavior and privacy boundary.
- [x] Run focused tests for topic reranking, shared provider JSON extraction, copy generation, worker
  fallback, and API projections.
- [x] Run Ruff format/lint, strict mypy, provider-free `evals.topic_rerank.runner --check`, full
  `make backend-check`, `make api-contract-check`, Compose render, `git diff --check`, and a scoped
  secret/raw-content scan.
- [x] Verify Alembic remains a single unchanged head and no OpenAPI/client regeneration is needed.

## Phase 5 — One controlled live validation

Completed once by the root session after independent review. Neither sub-agent loaded credentials
or made a provider call.

- [x] Load credentials without printing them and construct the same three bounded synthetic
  candidates used by the failed observation.
- [x] Invoke the production adapter once with `max_attempts=1`, no database, no service mutation,
  and no business data.
- [x] Record only the accepted/fallback outcome, safe IDs/order/fingerprints, usage/latency, and
  bounded issue codes in `result.md`.
- [x] The call returned a strictly accepted complete permutation, so no failure retry or diagnostic
  branch was entered.

## Risk and rollback points

- Prompt/payload changes are inseparable from the policy-version bump. Do not change v1 in place.
- The shared envelope extraction must be a move/reuse with copy behavior unchanged; any copy test
  drift blocks completion.
- Never solve compatibility by allowing extra fields, coercing ordinal strings, accepting partial
  lists, or stripping arbitrary model prose.
- Preserve unrelated dirty report files and the separate untracked Agent Workbench portfolio task.

## Planned validation commands

```bash
conda run --name edu-ai pytest -q \
  backend/tests/unit/test_topic_rerank.py \
  backend/tests/contract/test_topic_rerank_provider.py \
  backend/tests/unit/test_copy_generation.py
conda run --name edu-ai python -m evals.topic_rerank.runner --check
make backend-check
make api-contract-check
docker compose config --quiet
git diff --check
```
