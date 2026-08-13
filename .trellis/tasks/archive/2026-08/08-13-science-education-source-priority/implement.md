# Implementation plan: science-education and product-aligned source priority

## Preconditions

- Preserve all existing worktree changes, including unrelated Trellis report artifacts; inspect overlapping diffs before editing.
- Do not start until the user explicitly approves the latest planning summary and `task.py start` changes this task to `in_progress`.
- At implementation start, load `trellis-before-dev` for backend/domain, ingestion, persistence, API, and test guidance.
- Keep historical `ai-title-v1`, `moe-science-v1`, `science-policy-priority-v2`, and old scoring snapshots executable.

## Ordered implementation checklist

1. [x] Refresh task/spec context, inspect the dirty worktree, record the current migration head and source/scoring versions, and run the narrow baseline tests for relevance, connectors, acquisition, and topic selection.
2. [x] Add pure `science-ai-education-v1` and `product-matrix-fit-v1` domain policies with typed results, bilingual normalization, bounded body handling, stable reason/direction IDs, and exhaustive positive/negative unit tests.
3. [x] Add list/detail fixtures and dedicated connector registrations for Xinhua Education, CAST science education, and EdSurge AI education. Enforce exact host/path/article shapes, canonical URLs, publication time/language parsing, and sponsored/external/HTTP/API exclusions.
4. [x] Add conservative source profiles for all three proposed sources; activate only Xinhua Education after its live gate and retain CAST/EdSurge in `PENDING_SOURCE_SEEDS`. Change the existing active source configurations to new immutable source versions using `science-ai-education-v1`, while retaining the Ministry's exact HTTP fallback and historical topic-policy metadata.
5. [x] Wire the new policies into acquisition: deterministic title relevance/product ordering, bounded neutral body probes, full title+body eligibility, freshness, observations/extraction metadata, zero-match behavior, idempotency, and `acquisition-v4-science-education-fit`.
6. [x] Add acquisition source/profile/repository/API and real-PostgreSQL cases for the fail-closed 10-active/2-pending registry, source-version fingerprints, metadata round trips, English candidates, filtered/deferred counts, retry/lease behavior, and no unrelated detail-fill.
7. [x] Extend event-to-topic projection with explicit science-education and product-fit features/reasons. Add `outside_science_ai_education_scope` as a hard veto based on stored governed projections, not source identity.
8. [x] Implement `scoring-v1-preview.5-science-education-product-fit` with the approved 30%/25% editorial weights, preserved threshold/penalties/tie-break/no-topic behavior, no absolute source priority, and a compatibility adapter for historical feature maps/config snapshots.
9. [x] Persist and expose the two rule versions, reason codes, product directions, feature components, veto, and source-priority-disabled explanation through existing JSON score/config APIs. No migration or response-schema change was required.
10. [x] Add English-evidence governance/copy tests proving Chinese factual output remains bound to original English passages and brand/product context never becomes factual evidence.
11. [x] Update source-count/operator documentation and the executable backend specs for the current 10-active/2-pending science/AI-education acquisition contract and `.5` topic-selection contract.
12. [x] Run focused domain/connector/acquisition/topic/governance tests and the full quality gate. Run bounded entry + one-detail live checks for all three proposed sources; keep CAST and EdSurge pending after typed `non_public_address` failures rather than relaxing safety policy.
13. [x] Run `trellis-check`, review the complete diff for spec drift and accidental overlap with user changes, and record exact verification results in the task handoff.

## Focused validation commands

Exact test filenames may be extended using existing naming patterns, but the implementation loop starts with:

```bash
conda run --name edu-ai pytest -q \
  backend/tests/unit/test_title_relevance.py \
  backend/tests/unit/test_science_relevance.py \
  backend/tests/unit/test_topic_selection.py

conda run --name edu-ai pytest -q \
  backend/tests/contract/test_source_connectors.py \
  backend/tests/contract/test_fetch_policy.py \
  backend/tests/contract/test_safe_fetcher.py

conda run --name edu-ai pytest -q \
  backend/tests/integration/test_title_relevance_ingestion.py \
  backend/tests/integration/test_acquisition_repositories.py \
  backend/tests/integration/test_topic_selection_repositories.py
```

Add new focused test modules if that produces clearer ownership, for example `test_editorial_relevance.py` and `test_science_education_ingestion.py`; do not overload legacy rule tests with unrelated cases.

## Final validation commands

```bash
make backend-check
make frontend-check
make api-contract-check
docker compose config --quiet
make doctor
git diff --check
```

Live verification stays opt-in, bounded to the controlled registry, and records only safe run/job/title/URL/status metadata. It must not persist response bodies in task artifacts.

## Risky areas and rollback points

- Highest-risk code: `execute_acquisition.py`, the source connector registry, source profiles, `topic_selection.py`, and the database topic projection. Batch changes by contract and keep focused tests green before crossing layers.
- Historical compatibility: config parsing must branch on stored feature keys/rule versions; never silently interpret an old `ai_relevance` value as the new science-education score.
- Source activation: adding a seed makes the scheduler enqueue it. Do not land a seed whose fixture and bounded live smoke fail; connector code without an active seed may be removed or deferred.
- English evidence: a provider/fixture failure to produce valid Chinese evidence-bound facts blocks EdSurge activation; do not discard passage binding or pretend translated text is an original quote.
- No schema migration is expected. If implementation discovers that a typed column is genuinely required, stop and revise `design.md`, migration/rollback scope, and the final planning summary before adding it.
- Ranking rollback is configuration/version based: use `.4` for new runs while preserving all `.5` artifacts.

## Final review checklist before task start

- [x] PRD convergence pass completed with no blocking product or scope decisions.
- [x] `design.md` names active/deferred sources, rules, weights, data flow, compatibility, activation, and rollback.
- [x] `implement.jsonl` and `check.jsonl` contain only real spec/research entries and no seed placeholder row.
- [x] The latest planning summary has been presented to the user.
- [x] A subsequent user message explicitly approved that summary for implementation.

## Implementation outcome

- Implemented and independently checked on 2026-08-13.
- Active registry: 10 sources. Xinhua Education passed the production-safe entry and one-detail
  live gate and is active.
- Pending activation: CAST science education and EdSurge AI education. Both were blocked during
  DNS preflight with typed `non_public_address`; no HTTP detail request or safety bypass occurred.
- Final checks: backend 618 passed; strict mypy and Ruff passed; frontend 27 passed plus production
  build; API contract, Compose, doctor, and diff hygiene passed. Alembic remains
  `20260807_0019`; no public API/generated-schema change was introduced.
- Remaining external gate: each pending source must resolve to a real public address and then pass
  its own bounded entry plus at-most-one-detail smoke before it can move into `SOURCE_SEEDS`.
