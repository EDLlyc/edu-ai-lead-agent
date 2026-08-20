# Result

## Outcome

Implemented the new immutable current bundle:

- scoring: `scoring-v1-preview.10-substantive-science-education-priority`;
- Ministry priority: `ministry-education-priority-v4-substantive-science-education`;
- rerank: `topic-rerank-v4-minimal-order-contract`.

The real Tibet education-support meeting regression no longer receives Ministry priority or a
threshold bypass under v4. Authenticated science-education policies, curriculum/teaching practice,
and talent-development actions remain eligible, while event-only wrappers, promotions, homonyms,
and every hard veto fail closed. General hard-tech candidates continue through the unchanged broad
Tier-A/B pool rather than inheriting Ministry priority.

Zhipu v4 now receives the frozen governed candidates but may return only
`{"order":["candidate UUID"]}`. The adapter derives ordinals, `model_rank_order`, and a fixed safe
explanation locally. Unknown, duplicate, missing, extra, malformed, or cross-priority IDs retain
the one-call deterministic fallback and the existing automatic finalizer.

Independent review tightened this boundary further: v4 now parses only the exact top-level JSON
object and rejects Markdown fences or prose affixes, while literal v2/v3 keep their historical
bounded envelope parser. Applied diagnostics are also policy-bound at the domain boundary: v4
accepts only the locally derived `model_rank_order` and fixed explanation; v1/v2/v3 accept only
their historical reason codes. A custom/fake/provider result therefore cannot blur immutable
wire identities.

Literal `.9 + ministry-v3` and rerank v1/v2/v3 remain explicitly routed. Tests lock the `.9`
configuration fingerprint and all three historical prompt fingerprints.

## Verification

- Initial implementation gate before independent review: `make backend-check` passed Ruff,
  strict mypy for 170 source files, and `1124` tests.
- Independent review after its self-fixes: Ruff format/lint and strict mypy passed; focused
  topic-selection/rerank/provider/slot tests passed `177` tests.
- Focused PostgreSQL/API persistence set: `6 passed`; the rerank repository test persists v4
  applied/fallback/slot audit rows and asserts their policy identity.
- Provider-free rerank eval: `8/8` passing and canonical artifacts refreshed.
- Release tests: `54 passed`; migration-head test passed; `make api-contract-check` passed with no
  OpenAPI drift; Compose rendered successfully; Doctor completed successfully with the v4 bundle.
- `git diff --check`, scoped secret scan, and scoped raw-provider-retention scan passed.

## Isolated Zhipu compatibility probe

Executed exactly once after all deterministic gates with two frozen synthetic candidates,
`max_attempts=1`, no repository/database/scheduler/worker/publication access, and no raw response
retention.

- outcome: `succeeded`;
- policy: `topic-rerank-v4-minimal-order-contract`;
- candidate count: `2`;
- complete permutation: `true`;
- local reason projection: `true`;
- usage: prompt `705`, completion `41`, reasoning `0` tokens;
- latency: `1208 ms`;
- attempts: `1`.

This confirms only current provider transport/wire compatibility. It is not a fresh-news run,
deployment, publication, or editorial-quality claim.

## Boundaries preserved

No news acquisition, 2026-08-20 business replay, copy/image/OCR job, delivery, SSH, deployment,
commit, or push was performed. No migration or public API change was required. User-owned report
modifications and deletions were not touched.

## Review disposition

Independent Trellis review completed with all findings fixed and no remaining blocking findings.
Production deployment remains outside this task; commit/archive handoff belongs to the main
session.
