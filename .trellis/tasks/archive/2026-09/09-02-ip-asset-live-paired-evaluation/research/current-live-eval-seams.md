# Current live-evaluation seams (2026-09-02)

## Verified local prerequisites

- `private/brand-materials/visual-assets.manifest.json` exists.
- `.env` contains non-empty visual embedding provider mode, endpoint, API key, model, dimensions and
  input-policy settings. Secret values were not printed or copied into task artifacts.
- Local PostgreSQL reports 46 `ready` IP assets and 46 compatible
  `alibaba-model-studio/qwen3-vl-embedding/2048/brand-visual-embedding-input-v2` asset embeddings.
- `make ip-asset-grounded-eval-preflight` passed and mapped all 41 safe catalog assets before any
  query embedding request.

## Existing code boundaries

- `run_live_grounded_v2(...)` executes the production `search_text_for_evaluation(...)` path and
  returns `GroundedRetrievalRunV2` with safe refs, bounded decision evidence, hashes, timing and
  provider request count.
- `report-selective-v2` evaluates one Seed V2 run and selects an abstention candidate on dev before
  reporting holdout. It compares a threshold policy with the no-threshold policy inside one run;
  it does not compare hybrid-v2 with hybrid-v3-rrf.
- Existing `compare-runs` loads the V1 `GroundedRetrievalRun` and 100-query V1 bundle. It cannot
  accept the 124-query Seed V2 run without violating strict schema identity.
- Existing safe manifest binds one V2 run to one selective report. It intentionally discloses
  Codex-only labels, no human agreement, no online evidence, and unavailable cost when null.
- Evaluation search bypasses anonymous business-search aggregation; ordinary product search keeps
  its existing best-effort aggregate write.

## Required implementation boundary

- Add an independent Seed V2 paired comparator and report command; do not widen or change the V1
  comparator schema.
- Keep `eval-check` provider-free. Live commands remain explicit and never join CI.
- Store generated live artifacts in ignored `output/evals/`; do not make them canonical fixtures.
- Preserve privacy rejection for query text, labels/grades, score/vector/provider payload, paths,
  dynamic identities and actor/request fields.
- Do not edit production V2/V3 ranking behavior, asset metadata, vectors, database schema or HTTP/UI.

## Dirty-worktree boundary

The shared worktree contains unrelated official-account, migration and topic-rerank V5 changes.
This task owns only the Grounded evaluator, its tests, relevant Make/docs/spec updates and this task
directory. It must stage and commit explicit owned paths and must never format or revert unrelated
files.
