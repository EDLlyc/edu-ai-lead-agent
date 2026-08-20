# Implementation Plan

1. [x] Add the immutable v3 layered-auto-finalize rerank identity while preserving literal v1/v2 config, prompt, payload and parser behavior.
2. [x] Add pure daily/slot automatic finalizers that bind outcome base order and event/version pairs to the exact frozen pool and convert any mismatch to deterministic fallback.
3. [x] Route daily and content-slot executors through the finalizers before atomic persistence; retain lease-loss and durable retry behavior.
4. [x] Make LLM rerank default-on only for an enabled content-selection pipeline, while allowing the globally disabled content stage to coexist with `AI_PROVIDER_MODE=disabled`.
5. [x] Update `.env.example`, Compose defaults and Doctor/config contracts without changing downstream copy/image/WeCom review or delivery settings.
6. [x] Add unit/contract tests for v1/v2 replay, v3 config, exact pool binding, cross-run/event-version mismatch, missing/extra IDs, priority barrier, slot same-day exclusion, fallback parity, and zero/one-candidate skip.
7. [x] Add focused real-PostgreSQL daily/slot persistence tests proving applied/fallback audits and atomic final decision without a human-review state.
8. [x] Update topic-selection, content-slot, agent-pipeline, error/logging and quality specs with the four-layer automatic contract.
9. [x] Run focused Ruff/mypy/tests, provider-free rerank eval, API contract, Compose/Doctor checks, migration-head parity, `make backend-check`, `git diff --check`, and an independent Trellis review. Repository migration declarations were repaired to the existing `0022` head; Doctor now passes those declarations and the new rerank check, then correctly reports that the running local development database itself remains at `0021`.

## Risky seams / rollback

- Do not mutate v1/v2 policy behavior or historical JSON snapshot fields; a replay drift blocks completion.
- The current `.9` scoring/hard-veto contract remains unchanged; this task changes orchestration after eligibility, not the score or threshold.
- A finalizer defect must fail to deterministic order, never to `review_required`, a second model call or direct publication.
- No provider/live-source/SSH/deploy/replay/delivery action is authorized.
