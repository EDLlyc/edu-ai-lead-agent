# Result: Delivered Repeat Window

## Outcome

Implemented `scoring-v1-preview.7-delivered-repeat-history` with
`topic-veto-v4-delivered-content` as the new repository default. The v4 hard-repeat projection now
counts only typed daily/slot selection -> copy run -> material package -> Enterprise WeChat jobs
whose mode is `formal` and terminal status is `delivered`.

Literal `scoring-v1-preview.6-tiered-science-tech-priority` remains supported with
`topic-veto-v3-governed-content` and selection-backed replay. `.6` and `.7` retain identical
weights, threshold, editorial/product rules, penalties, Ministry priority/threshold bypass, and
tie-break ordering. Selected rows continue to own `theme_repetition`, and same-day slot exclusion
remains selection-backed.

The delivery projection filters before latest-date aggregation, uses `DISTINCT` event/version/date
rows, binds the redundant daily/slot copy identities, and binds a slot delivery job back to the
same slot selection. Absent, test, queued, running, partial, failed, cancelled,
`delivery_window_expired`, and `delivery_unknown` jobs cannot create a false v4 repeat veto.

## Files changed

- `backend/app/domain/topic_selection.py`
- `backend/app/application/services/topic_selection.py`
- `backend/app/infrastructure/db/topic_selection.py`
- `backend/app/core/config.py`
- `backend/tests/unit/test_topic_selection.py`
- `backend/tests/unit/test_topic_selection_delivery.py`
- `backend/tests/integration/test_wecom_slot_delivery_concurrency.py`
- `backend/tests/integration/test_topic_selection_api.py`
- `.env.example` (target scoring-default line only; unrelated existing workbench additions preserved)
- `compose.yaml`
- `.trellis/spec/backend/topic-selection.md`
- `.trellis/spec/backend/content-slot-production.md`
- `.trellis/spec/backend/wecom-delivery.md`
- `.trellis/spec/backend/agent-pipeline.md`
- `.trellis/spec/guides/cross-layer-thinking-guide.md`
- `.trellis/tasks/08-17-delivered-repeat-window/implement.md`
- `.trellis/tasks/08-17-delivered-repeat-window/result.md`

## Bug analysis and prevention

- **Root-cause category**: cross-layer contract plus implicit assumption. The audience-frequency
  rule used the durable editorial-selection clock because it was nearby and already queryable, even
  though the business fact was successful audience delivery.
- **Why it escaped**: unit coverage proved the seven-day arithmetic but did not contrast a selected
  row with an undelivered delivery lineage in PostgreSQL.
- **Architecture prevention**: v4 derives hard-repeat dates only from the complete typed
  selection -> copy -> package -> formal-delivered lineage; selection history remains a separate
  input for theme diversity and same-day exclusion.
- **Compatibility prevention**: the semantic clock is part of the immutable scoring/veto identity,
  so literal `.6` runs retain their original meaning while `.7` owns delivered-backed behavior.
- **Test prevention**: real-PostgreSQL coverage now includes proxy-positive/outcome-negative rows,
  every non-authoritative delivery state, daily and slot origins, fan-out duplicates, latest-date
  aggregation, and the day-six/day-seven boundary.
- **Knowledge capture**: the backend topic/slot/delivery contracts and the general cross-layer
  thinking guide now require choosing the authoritative business fact rather than an upstream
  proxy. This repository has no `src/templates/markdown/spec/` mirror, so no generated spec
  template required synchronization.

## Verification

- `conda run --name edu-ai ruff format --check <8 affected Python files>`: passed.
- `conda run --name edu-ai ruff check <8 affected Python files>`: passed.
- `make backend-typecheck`: passed, strict mypy reported no issues in 162 source files.
- Focused unit/domain tests including same-day behavior: 74 passed.
- Real-PostgreSQL delivery-history and literal `.6` replay tests: 3 passed.
- Real-PostgreSQL topic-selection API/default-version test: 1 passed.
- `docker compose config --quiet`: passed.
- `git diff --check`: passed.
- Independent `make backend-check`: passed; Ruff format/lint, strict mypy across 162 source files,
  and all 950 backend tests are green.
- Independent collision regression: 2 passed together after moving the new delivery-history
  fixture off a business date already owned by an existing slot-dispatch test.
- `make api-contract-check`: passed; backend OpenAPI and generated frontend types are drift-free.
- `make doctor`: passed; Compose, service settings, PostgreSQL/pgvector, migrations, and MinIO are
  healthy without provider calls.

The PostgreSQL matrix covers formal delivered, test delivered, absent delivery, every durable
non-delivered state, duplicate package/job lineage, an older formal success followed by newer
failed/test jobs, daily and slot origins, selected-row theme history, and projected day 6/day 7.
No migration or OpenAPI change was needed.

## Independent review finding

The first complete-suite run exposed a PostgreSQL fixture collision: the new slot delivery-history
test and an existing stale-running dispatcher test both used the same scheduled morning acquisition
business key. The checker moved only the new fixture to an unused date, reran the conflicting pair,
the delivery-history/API matrix, Ruff, and the complete backend gate, and all passed. No SSH,
deployment, production mutation, provider call, Enterprise WeChat send, commit, or push was
performed.
