# Implementation Plan

1. [x] Add explicit historical-v2 and current-v3 broad-hard-tech editorial identities and version-dispatched behavior in `backend/app/domain/editorial_relevance.py`.
2. [x] Add aerospace vocabulary plus typed completed/planned/failed/capital/event/product signals and unrelated/version-replay unit tests.
3. [x] Route acquisition evaluation from the persisted source relevance-rule version; bump the current acquisition identity and source-version fingerprints without changing the ten-source registry.
4. [x] Add a production-shaped Xinhua Tech fixture and connector/acquisition tests for the verified 2026-08-19 article shape.
5. [x] Add the next immutable topic-scoring version; map `.6`/`.7`/`.8` to editorial v2 and the new default to v3 while preserving threshold, weights, delivered-history veto, Ministry priority and rerank behavior. Add a separate audited broad-hard-tech pool policy instead of lowering `0.59` globally.
6. [x] Make governed topic candidate projection consume the run-pinned editorial version and add real repository/config replay coverage.
7. [x] Update `.env.example`, Compose defaults and backend acquisition/topic-selection specs. Do not touch production secrets or deploy.
8. [x] Run focused Ruff, strict mypy, domain/connector/acquisition/topic tests, API contract/Compose checks, then `make backend-check` and `git diff --check`.
9. [x] Run an independent spec/replay/false-positive review and record results in `result.md`.

## Risky seams / rollback

- `SCIENCE_TECH_EDITORIAL_RULE_VERSION`, acquisition version and default scoring version are immutable identities; a failed implementation is rolled back as one unit rather than partially retaining defaults.
- Any historical metadata drift, source-count change, generic-launch false positive or config fingerprint conflict blocks completion.
- No database migration or production operation is authorized by this task.
