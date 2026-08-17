# Repository reuse seams for the Agent portfolio workbench

## Current strengths

- Governed facts already have typed eligibility and binding semantics in
  `backend/app/domain/copy_generation.py::EligibleEvidence`.
- The production copy query in `backend/app/infrastructure/db/copy_generation.py::_load_evidence`
  already joins an EventVersion to validated Tier A/B bindings, exact quotes, sources and URLs.
- Event list/detail projections live in
  `backend/app/infrastructure/db/governance_queries.py::{list_event_rows,get_event_detail}` and are
  mapped by the governance API views.
- General brand retrieval lives in
  `backend/app/application/services/brand_knowledge.py::retrieve_brand_context`, backed by the
  provider/model-scoped hybrid RRF repository. It already preserves the rule that brand chunks are
  not factual evidence.
- The pure deterministic copy boundary is
  `backend/app/domain/copy_generation.py::validate_material_draft` over `MaterialDraft`, eligible
  evidence and active brand context.
- Existing invocation/attempt tables record useful provider metrics, but their strong foreign keys
  and capability-specific constraints make them unsuitable for generic workbench traces.

## Gaps confirmed by repository search

- No Model Context Protocol dependency, server or client contract exists.
- No shared Function Calling/tool registry or bounded model->tool loop exists.
- No dedicated Agent evaluation dataset, metric runner or checked-in report exists.
- Existing observability is split across capability-specific records and logs; there is no single
  recruiter-facing action/observation trace.
- `repositories.py::list_candidates` is chronological pagination, not an evidence search contract;
  calling it `search_evidence` would misrepresent behavior.

## Recommended seams

1. Extract/promote the governed evidence read query behind a narrow application port so the copy
   path and workbench share eligibility rules.
2. Adapt the existing event projection, brand retrieval service and copy validator. Do not expose
   ORM models or reproduce rules in tool handlers.
3. Create one immutable typed registry consumed by the Agent graph, MCP adapter and evaluator.
4. Return workbench trace in the single run response and export eval reports as files. Defer
   persistent Agent runs until a separately approved migration.
5. Provide a deterministic fixture-backed reader for CI/demo and an explicit local-database reader
   for integration. Never use a fake query vector against provider-scoped production embeddings.

## Suggested files and tests

- Backend: `domain/agent_workbench.py`, `application/ports/agent_workbench.py`,
  `application/services/agent_tools.py`, `application/services/agent_workbench_graph.py`,
  `application/services/agent_workbench.py`, `infrastructure/db/agent_workbench.py`,
  `infrastructure/ai/agent_workbench.py`, `schemas/agent_workbench.py`,
  `api/v1/routes/agent_workbench.py`, and `agent_mcp_main.py`.
- Eval: `backend/evals/agent_workbench/` with cases, runner, metrics and README.
- Frontend: `frontend/src/features/agent-workbench/` with mapper, hook, panel, styles and behavior tests.
- Tests: tool/graph/API/eval unit tests, MCP contract tests, DB query/API integration tests, and
  frontend mapper/component/accessibility tests.

## Risks

- Brand hybrid retrieval is provider/model scoped. A fixture mode must stay explicit rather than
  silently mixing fake query vectors with real embeddings.
- Refactoring the copy validator input must preserve the production caller and historical contracts;
  use a structural read-only Protocol only if necessary.
- Model-facing event/evidence results must be smaller than existing HTTP detail responses; bound
  member counts, excerpts and serialized bytes at the tool boundary.
