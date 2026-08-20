# Implementation Result

## Outcome

Implemented the reviewed broad hard-tech recall design locally. Current source versions use
`science-tech-editorial-v3-broad`, while historical v2 source versions and `.6`/`.7`/`.8` topic
snapshots continue to execute with their original semantics. The active scoring identity is
`scoring-v1-preview.9-broad-hard-tech-pool`; its numeric threshold remains `0.59`.

The current classifier now accepts a governed hard-tech topic without requiring a completed
breakthrough phrase. It records completed progress, plan/in-progress, failure/setback,
capital/market, event/conference, product/service release, or general-hard-tech signals. A v3
frontier candidate that has eligible Tier-A/B evidence, completed governance, and no hard veto may
enter the existing LLM rerank pool below `0.59`; the score, failed numeric-threshold state, policy
identity, and bypass reason remain explicit. This path does not override unverified, stale,
delivered-repeat, evidence, Tier-C-only, privacy/legal/safety, or prohibited-marketing vetoes.

The verified Xinhua Tech 2026-08-19 article shape is covered by a local connector fixture. Its exact
headline is classified as frontier science/technology with `completed_progress` and
`aerospace_recovery_or_landing`; no source, host, path, or registry-count expansion was made.

## Files changed

- Editorial and acquisition behavior:
  - `backend/app/domain/editorial_relevance.py`
  - `backend/app/application/services/execute_acquisition.py`
- Topic selection and persistence:
  - `backend/app/domain/topic_selection.py`
  - `backend/app/application/services/topic_selection.py`
  - `backend/app/infrastructure/db/topic_selection.py`
- Local/default identities:
  - `backend/app/core/config.py`
  - `.env.example`
  - `compose.yaml`
- Fixtures and tests:
  - `backend/tests/fixtures/sources/xinhua_tech_v1/list.html`
  - `backend/tests/fixtures/sources/xinhua_tech_v1/detail.html`
  - `backend/tests/contract/test_source_connectors.py`
  - `backend/tests/unit/test_editorial_relevance.py`
  - `backend/tests/unit/test_topic_selection.py`
  - `backend/tests/unit/test_topic_selection_delivery.py`
  - `backend/tests/integration/test_title_relevance_ingestion.py`
  - `backend/tests/integration/test_acquisition_repositories.py`
  - `backend/tests/integration/test_acquisition_api.py`
  - `backend/tests/integration/test_topic_selection_repositories.py`
  - `backend/tests/integration/test_topic_selection_api.py`
- Executable project guidance:
  - `.trellis/spec/backend/agent-pipeline.md`
  - `.trellis/spec/backend/database-guidelines.md`
  - `.trellis/spec/backend/topic-selection.md`
  - `.trellis/spec/backend/content-slot-production.md`

## Validation

- Focused editorial/topic unit suite: `161 passed` before the final repository assertion was added;
  all affected tests are also included in the final full gate.
- Source connector contract: `27 passed`.
- Focused PostgreSQL/MinIO acquisition and topic-selection integration suite: `26 passed`.
- New repository replay tests run independently after isolation fix: `2 passed`.
- `make topic-rerank-eval`: `8/8` cases passed without a provider call.
- `make api-contract-check`: passed; generated frontend API types remain current.
- `docker compose config --quiet`: passed.
- `make backend-check`: Ruff format/check passed, strict mypy passed for `170` source files, and
  backend pytest passed `1084/1084` with `82%` coverage.
- `git diff --check`: passed.

## Scope and remaining review

No provider, live-source, SSH, deployment, replay, delivery, database migration, or production
mutation was performed.

## Independent reviewer findings

The independent spec/replay review confirmed that acquisition uses the stored source-version rule,
topic projection uses the immutable scoring snapshot, `.6`/`.7`/`.8` remain pinned to v2, and the
v3 below-threshold pool cannot override any hard veto. No migration, API schema, source count, host,
or path drift was found.

One false-positive boundary was found and fixed: v3 initially audited legacy exclusions but could
still admit explicit consumer/admissions promotions or non-technical aerospace homonyms solely
because they contained words such as AI, robot, rocket, airline, or satellite. The reviewer added a
narrow v3-only recall exclusion for those cases, while preserving genuine hard-tech product
launches, conferences, financing, plans, failures, and completed progress. Regression tests now
cover both sides of that boundary. The reviewer also added the missing
`unsuitable_negative_incident` hard-veto non-bypass case.

Reviewer verification after the fix:

- Focused editorial/topic/delivery/connector suite: `200 passed`.
- Impacted acquisition and topic-repository integration suite: `9 passed`.
- Ruff format/check: passed.
- Strict mypy: passed for `170` source files.
- `git diff --check`: passed.

Implementation-plan step 9 is complete. The earlier full `make backend-check` result remains
`1084/1084` passed; the reviewer did not repeat the whole suite because the corrective change was
bounded to the classifier and was covered by the complete affected domain suites plus impacted
integration paths.
