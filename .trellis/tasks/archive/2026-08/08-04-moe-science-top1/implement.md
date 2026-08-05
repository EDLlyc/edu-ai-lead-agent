# Implementation plan: Ministry science-news Top 1

## Preconditions

- Keep all existing user worktree changes intact; inspect overlapping diffs before editing.
- Do not start implementation until the latest planning summary is explicitly approved and `task.py start` changes the task to `in_progress`.
- At implementation start, load `trellis-before-dev` context for backend and test layers.

## Ordered checklist

1. [x] Refresh the task context and backend specs; confirm the migration head and current image-task changes still coexist.
2. [x] Add `allow_http_fallback` and `topic_priority_policy` to source seed/profile/version mapping and add the additive Alembic migration. Update seed/source API contracts, source count limits, and migration assertions.
3. [x] Extend source URL normalization/fetch policy with a strict source-scoped HTTP fallback. Add default-deny, same-source-allow, off-domain, path, redirect, DNS and response-bound tests.
4. [x] Add the `moe_news_v1` connector and list/detail fixtures. Verify fixed selectors, dated article paths, relative/HTTP URLs, metadata dates, canonical URL, and parser-drift failure.
5. [x] Add `moe-science-v1` deterministic relevance evaluation and wire it into acquisition without changing `ai-title-v1`. Keep scan/detail limits, freshness behavior, observations, match metadata, and idempotency explicit.
6. [x] Add acquisition unit/integration cases for title-only, body-only, non-science, stale, unknown-date, off-domain and policy-blocked Ministry records.
7. [x] Carry `topic_priority_policy` from governed source occurrences into `TopicCandidate`; bump and version the scoring config; implement priority-before-score ordering only after eligibility/veto evaluation.
8. [x] Persist priority explanation in `topic_scores.explanation`, expose it in topic score/daily-topic API responses, regenerate OpenAPI and frontend types, and add API/integration tests.
9. [x] Add the end-to-end same-day provisional `all_vetoed` recovery case: later Ministry acquisition/governance produces a new immutable revision, existing downstream reconciliation sees only the current revision, and replay is idempotent.
10. [ ] Run an opt-in Ministry source smoke with the production-safe fetcher. Capture only bounded run/job/result metadata and do not broaden the source scope if the live page drifts or is blocked.
11. [x] Run the full verification gate and review the diff for unintended changes to the user's existing image-generation work.

## Validation commands

```bash
make backend-check
make frontend-check
make api-contract-check
docker compose config -q
make doctor
git diff --check
```

Focused commands during implementation:

```bash
pytest -q backend/tests/unit/test_science_relevance.py backend/tests/unit/test_topic_selection.py
pytest -q backend/tests/contract/test_fetch_policy.py backend/tests/contract/test_safe_fetcher.py backend/tests/contract/test_source_connectors.py
pytest -q backend/tests/integration/test_title_relevance_ingestion.py backend/tests/integration/test_topic_selection_repositories.py
```

Use the repository's existing `make` targets and environment files for migration, seed, and live smoke; never put provider keys or response bodies in task artifacts.

## Risky files and rollback points

- Risky backend files: `source_profiles.py`, `fetcher.py`, `connectors.py`, `execute_acquisition.py`, `topic_selection.py`, `infrastructure/db/topic_selection.py`, `models.py`, and the new migration.
- Schema rollback point: the migration is additive; downgrade must fail safely if the new source/version is active or must first be deactivated through the controlled source registry.
- Policy rollback point: set the new source version's fallback flag false or disable the source; do not alter the default URL policy.
- Selection rollback point: use the previous scoring profile/version for new runs; preserve historical runs and daily selections.
- Integration rollback point: if generated OpenAPI/types drift, regenerate from the backend route and inspect the diff rather than hand-editing duplicate types.

## Final review gates before task start

- [x] PRD has no blocking open question and reflects the accepted source-scoped HTTP fallback.
- [x] Design names every changed contract, migration, compatibility rule, and test boundary.
- [x] `implement.jsonl` and `check.jsonl` contain real spec/research entries and no seed placeholder.
- [x] The user has explicitly approved the latest planning summary.

Step 10 remains intentionally opt-in: the fixture-backed contracts and production-safe URL policy
are the ordinary verification boundary; no unbounded external crawl is required for task closure.
