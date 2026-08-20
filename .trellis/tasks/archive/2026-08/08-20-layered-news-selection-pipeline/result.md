# Implementation Result

## Outcome

Implemented the news-selection-only four-layer pipeline:

```text
authoritative hard vetoes
  -> current .9 broad deterministic eligible pool
  -> one bounded v3 LLM permutation
  -> automatic deterministic finalizer or typed fallback
  -> existing atomic daily/slot persistence
```

The new immutable current identity is `topic-rerank-v3-layered-auto-finalize`. Literal v1 and v2
prompt, wire payload, parser, snapshot and application behavior remain replayable. V3 binds the
outcome to the exact request fingerprint and pool, revalidates event/version, eligibility, empty
veto, priority, same-day and cap/item boundaries, and turns every mismatch into the exact
deterministic base order with an allowlisted failure code. Its prompt now explicitly evaluates news
value and breakthrough significance while literal v2 keeps its exact previous wording.

Reranking is enabled by default only when the content pipeline itself is enabled. The global
content default remains disabled, so disabled local development remains provider-free. No copy,
image, OCR, WeCom review/delivery implementation or setting was changed.

## Verification

- Focused rerank unit/provider contracts: `53 passed`.
- Focused real PostgreSQL/API slice: `4 passed`.
- Full project backend gate: `make backend-check` passed; Ruff format/lint passed, mypy passed for
  `170 source files`, and `1103 passed` with 82% aggregate coverage.
- Release contracts: `54 passed`.
- OpenAPI contract/type generation check: passed.
- Compose rendering for governance/content/WeCom profiles: passed.
- Provider-free rerank eval: `8/8` passed and canonical JSON/Markdown reports match.
- `git diff --check`: passed.
- Alembic reports the single repository head `20260818_0022`; the full backend integration suite,
  including migration contracts and the new v3 atomic persistence test, passed.

## Independent review fixes

- Split the v3 prompt from literal v2 so the new policy explicitly names the PRD-required news-value
  and breakthrough dimensions without changing v1/v2 replay.
- Repaired the pre-existing release/Doctor migration-head drift from `0021` to the repository's
  existing single head `0022`, and added a repository-level contract test that binds the Alembic
  graph, compatibility declaration and Doctor expectation together.

`make doctor` now passes the repository migration declaration and the layered rerank check. It then
correctly stops because the currently running local development database is still at `0021`; no
local database migration was performed in this code-only task.

## Scope safety

No live provider call, source fetch, SSH, deployment, replay, message delivery, local database
migration or manual review action was performed. Unrelated dirty reports and archived/user-deleted
artifacts were preserved.
