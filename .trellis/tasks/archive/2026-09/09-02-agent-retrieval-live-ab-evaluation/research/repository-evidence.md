# Agent retrieval live A/B — repository evidence

## Existing execution path

- `backend/app/application/services/agent_workbench_graph.py` owns the bounded LangGraph loop,
  run-scoped exact invocation cache, trace projection, citations and terminal states.
- `backend/app/application/services/agent_tools.py` owns the four strict tools and their Pydantic
  input/output limits; the experiment must not introduce an evaluation-only tool registry.
- `backend/app/infrastructure/db/agent_workbench.py` supplies the real PostgreSQL reader. Evidence
  search uses governed current-event projections and a read-only transaction; brand retrieval calls
  the shared hybrid retrieval service with the configured embedding identity.
- `backend/app/application/services/agent_retrieval.py` decorates only evidence and brand searches
  with planner/original-query parallelism, one optional rewritten retrieval, weighted RRF and a
  bounded reranker. `get_event` and copy-validation context pass through unchanged.
- `backend/app/infrastructure/ai/agent_retrieval.py` already supplies the one-shot strict Zhipu query
  planner and Zhipu reranker. Malformed/timeout responses degrade to the original ranked candidates.
- `backend/app/agent_workbench_runtime.py` can construct either the plain reader registry or the
  enhanced reader registry without changing tool schemas, making reader composition the clean A/B
  seam.
- `backend/app/infrastructure/ai/agent_workbench.py` supplies the OpenAI-compatible tool-calling
  adapter at temperature zero and projects provider/model/usage/latency into the typed run result.

## Existing evidence and gap

- `backend/evals/agent_workbench/` has 42 deterministic, provider-free cases. It is authoritative for
  tool, citation, budget and refusal contracts, but explicitly is not live model intelligence.
- `backend/evals/brand_retrieval/` has a sanitized provider-free retrieval canonical; it does not
  establish private-corpus live embedding/retrieval quality.
- `.trellis/tasks/archive/2026-09/09-02-evaluation-next-stage-audit/research/repository-audit.md`
  identifies live Agent repeated-trial trajectory quality as a missing evidence layer and requires
  model/provider/version binding, failure preservation and truthful maturity labels.
- `backend/evals/official_account_reviewer_live_ab/` is the closest harness precedent for opt-in
  execution, manifests, budgets, failure ledgers, paired statistics and privacy checks. Its article
  quality task is separate and must not be coupled to this retrieval experiment.

## Design consequence

The new track should reuse the application runner, registries and provider adapters rather than fork
production logic. A provider-free harness test can use fakes, while the one authorized real run reads
local PostgreSQL and writes only ignored eval artifacts. Because the labels are Codex-reviewed Seed
and the sample is small, the report is evidence for a portfolio case study, not human preference or
production uplift.
