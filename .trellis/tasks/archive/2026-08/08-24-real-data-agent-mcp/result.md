# Result: Real-data Agent MCP retrieval enhancement

## Implemented

- Kept the four canonical MCP tools and fixture server unchanged while composing the real-data
  server over the existing read-only PostgreSQL reader.
- Added a versioned one-shot QueryPlan, NFKC normalization, semantic-drift guard, original/rewrite
  weighted RRF (`k=60`, weights `1.0/0.8`) and bounded Top-10 reranking.
- Added Zhipu `glm-5.2` strict-JSON planning with thinking disabled and the dedicated Zhipu
  `rerank` endpoint. Brand RAG now uses the existing Alibaba multimodal
  `alibaba-model-studio/qwen3-vl-embedding` 2048-dimensional identity; governance event/article
  vectors remain on Zhipu `embedding-3`.
- Added one brand-only adapter/factory and wired upload derivations, ingestion claims, API/content
  retrieval, MCP retrieval and cache namespaces to that same Alibaba identity. This avoids mixing
  Alibaba query vectors with historical Zhipu brand vectors.
- Decoupled brand ingestion availability from the governance AI provider: an enabled Alibaba brand
  provider can process brand jobs while governance AI is disabled, with OCR remaining optional;
  copy generation retains its existing fake/Zhipu provider requirement.
- Added a development-only, dry-run-by-default reindex command. It derives current v3 versions from
  immutable originals, processes them through the canonical ingestion executor and activates only
  ready targets; failed/incomplete documents keep their previous active version.
- Added a process-local TTL/LRU/single-flight brand Embedding cache whose namespace binds provider,
  model and embedding-input version and whose key also binds artifact identity, plus a per-Agent-run
  exact successful-tool result cache keyed by registry Schema hash and canonical validated
  arguments.
- Fixed Alibaba identical-text persistence collisions by deriving the brand request fingerprint
  from a version label, chunk ID and upstream visual fingerprint. Provider requests and vectors stay
  identical for identical text, while different chunks now receive distinct safe 64-hex metadata;
  no parser/chunk/input-policy or provider/model version bump is required.
- Added safe structured retrieval logs with hashes, plan/fusion versions, counts and fallback state;
  no query/result/provider body or credential is persisted.

## Verification

- Scoped Ruff, Ruff format check and Mypy: passed for all changed
  application/provider/domain/runtime files.
- Focused unit/provider/MCP suites passed, including Alibaba brand identity/hash mapping and
  text beyond the public visual-query cap, existing visual adapter contracts, query drift, RRF,
  rerank response validation, planner/rerank fallback, cache single-flight/TTL/LRU/failure
  behavior, exact run-level tool reuse, independent brand-worker enablement, reindex mutation
  opt-in/failed-target handling, real-data guards and canonical Schema equivalence.
- `make agent-portfolio-check`: passed; Agent eval `42/42`, registry hash unchanged, backend Agent
  tests passed, and five frontend files / 72 tests passed.
- `make brand-retrieval-eval`: passed `36/36`; Recall@5 `0.95`, nDCG@5 `0.928633`, parent-diversity
  delta `+0.15`, factual-evidence violations `0`.
- Live provider checks: configured `glm-5.2` planner and Zhipu `rerank` returned valid typed results;
  the configured Alibaba multimodal endpoint returned a finite 2048-dimensional text vector.
- The corrective local migration subsequently activated all four active brand documents in the
  Alibaba/current-v3 vector space. Aggregate verification reported four active-ready documents,
  zero provider/model identity mismatches and no remaining enqueue work; no private text or
  document identifiers were recorded.
- A real MCP STDIO smoke returned five bounded brand results while using Alibaba multimodal
  embeddings for retrieval and Zhipu only for QueryPlanner/rerank. The canonical four-tool Schema
  and five-second tool boundary remained unchanged between fixture and real-data MCP adapters.
- PostgreSQL/MinIO-backed Agent reader and brand-RAG integration tests passed, including read-only
  transactions, identity filtering, immutable ingestion and retrieval.

## Repository-wide pre-existing checks

- Repository-wide Ruff lint is currently blocked by unrelated import-order/unused-import changes in
  `backend/app/official_account_weekly_edition_live_demo.py` and
  `backend/tests/unit/test_official_account_weekly_edition_live.py`.
- Repository-wide format check remains blocked by three unrelated pre-existing dirty files:
  `backend/app/domain/topic_selection.py`,
  `backend/tests/integration/test_title_relevance_ingestion.py`, and
  `backend/tests/unit/test_topic_selection_delivery.py`.
- Repository-wide Mypy remains blocked by two unrelated literal-type errors in
  `backend/app/local_exact_target_selection.py`. All files changed for this task pass Mypy.
- Repository-wide pytest reached 1,594 passing tests and 27 unrelated failures: one in the
  in-progress topic-rerank v5 integration path and 26 copy-generation tests whose `Settings()`
  instances inherited incompatible current-workspace IP-recognition toggles. The task-owned
  focused suites and both affected PostgreSQL integration paths pass independently.

No server deployment, production data write, public HTTP MCP, or commit was performed.
