# Research: Smallest local-only Agent Research Workbench

- Query: What is the smallest high-resume-value local Agent Research Workbench that reuses this repository's LangGraph, PostgreSQL/pgvector, governed evidence, brand RAG, deterministic copy validation, preview UI, and stored model token/latency metadata, while exposing the same read-only tools over MCP without creating production behavior?
- Scope: mixed
- Date: 2026-08-16

## Findings

### Recommendation in one paragraph

Build one **local CLI-driven, fixture-first research graph** around a canonical three-tool
`ResearchToolCatalog`; persist its resumable control state with the existing PostgreSQL LangGraph
checkpointer and persist a safe, explicit trace in two new workbench tables. Export a redacted static
manifest to `output/workbench/` and render it in a small React panel by copying the existing preview
manifest pattern. Adapt the exact same catalog to an **stdio-only MCP 2.0 server** that refuses
production and live-provider modes. Keep the production FastAPI app, schedulers, content workers,
publishing/delivery paths, and provider defaults untouched. Make deterministic scripted cases the
quality gate; make real GLM tool calling an explicitly gated, small, non-CI experiment.

```text
local CLI / eval case
        |
        v
LangGraph: plan -> guard -> execute one tool -> plan -> finalize
        |                     |
        |                     +--> canonical ResearchToolCatalog
        |                              |- search_governed_evidence (PostgreSQL)
        |                              |- retrieve_brand_context (FTS + pgvector RRF)
        |                              `- validate_copy_contract (pure deterministic gate)
        v
Postgres checkpoint + workbench_runs/workbench_steps
        |
        `--> redacted output/workbench/{index,latest,runs/...}.json --> React portfolio panel

canonical ResearchToolCatalog --> thin MCPServer adapter --> stdio only
```

The key boundary is that **tools are read-only; the local runner may write only its own run,
checkpoint, trace, and exported manifest**. MCP calls never create workbench runs and never enter a
mutating application service.

### Existing assets and gaps

| File | Reusable pattern / relevant gap |
| --- | --- |
| `backend/app/application/services/governance_graph.py:48` | Typed, body-free checkpoint state; `governance_thread_id()` at line 116 and compiled conditional graph at lines 120-138 are the closest graph pattern. |
| `backend/app/application/services/governance_worker.py:51` | Durable attempt + checkpoint lookup/resume pattern; it resumes with `ainvoke(None)` rather than replaying completed work. |
| `backend/app/infrastructure/db/governance_checkpointer.py:13` | Wraps the official async PostgreSQL saver and deliberately leaves checkpoint DDL to Alembic (`saver.setup()` is forbidden at runtime at line 30). |
| `backend/app/application/services/copy_generation_graph.py:14` | Enforces body-free state, but its graph is only `START -> orchestrate -> END` (lines 49-64); it is not an agent/tool loop to extend. |
| `backend/app/infrastructure/db/models.py:705` | `normalized_passages` stores bounded source text and offsets, but has no general evidence-search vector/FTS column. |
| `backend/app/infrastructure/db/models.py:788` and `:856` | Accepted analyses and accepted facts are the safe governed search surface. |
| `backend/app/infrastructure/db/models.py:964` | Evidence bindings preserve validated exact quote, passage, candidate, occurrence, and snapshot provenance. |
| `backend/app/infrastructure/db/governance_queries.py:190` | Existing candidate detail projection already resolves accepted/reused analyses and their evidence; factor or parallel its joins instead of calling HTTP routes. |
| `backend/app/application/services/brand_knowledge.py:244` | Existing bounded brand query service validates input and obtains a purpose-specific query embedding. |
| `backend/app/infrastructure/db/brand_knowledge.py:896` | Existing brand retrieval is the real hybrid FTS + pgvector RRF implementation, with active/version/audience/date/provider/model filters and limits. |
| `backend/app/domain/copy_generation.py:50` | `EligibleEvidence` and `ActiveBrandContext` keep evidence and brand material separately typed. |
| `backend/app/domain/copy_generation.py:555` | `validate_material_draft()` is already the deterministic authority gate; it checks provenance IDs, brand/evidence separation, source footer, policy, personal data, and unsupported facts before any LLM audit. |
| `backend/app/application/ports/copy_generation.py:27` | Existing provider results define the telemetry contract: provider/model/fingerprint/request ID plus prompt, completion, reasoning tokens and latency. |
| `backend/app/infrastructure/db/models.py:749` and `:2589` | Governance and copy model-attempt tables already persist the same telemetry shape, but both are foreign-keyed to their own jobs and cannot safely store research-planner calls. |
| `backend/app/infrastructure/db/governance_queries.py:96` | Existing aggregation of invocation token/latency fields is a direct pattern for workbench totals. |
| `backend/app/infrastructure/ai/fake.py:83` | Deterministic 2,048-dimension fake embeddings support offline pgvector fixtures without a provider. |
| `backend/app/infrastructure/ai/copy_generation.py:281` | The current raw Zhipu client has safe HTTPS validation, retries, output bounds, and telemetry, but is private and JSON-only; function calling needs a small new planner adapter, not reuse of this class as-is. |
| `backend/app/preview_run.py:542` | Existing manifest builder/redactor and `latest.json` export pattern are suitable; running `preview_run` itself is not, because it invokes the full live pipeline. |
| `frontend/vite.config.ts:9` | Vite already serves generated local artifacts from `../output/preview` through a traversal-safe, no-store middleware. |
| `frontend/src/features/preview/hooks.ts:1` and `PreviewPanel.tsx:24` | Static manifest + React Query + explicit loading/empty/terminal states are the smallest safe UI pattern to copy. |
| `backend/pyproject.toml:9` and `backend/requirements/runtime.lock:635` | Python is 3.11; LangGraph is exactly 1.2.10 and its PostgreSQL saver is 3.1.0. MCP is not currently declared or locked. |
| `scripts/compile-python-locks.sh:25` and `backend/Dockerfile:12` | Runtime and `dev` locks are separate; the production image installs only `runtime.lock`, enabling MCP to remain a local/dev dependency. |

### MVP contracts

#### 1. One canonical, typed, read-only tool catalog

Define Pydantic inputs/outputs and one injected handler per tool. Both the LangGraph executor and MCP
adapter call these handlers; neither adapter owns business logic or a second JSON schema.

1. `search_governed_evidence(query, limit=5, candidate_id=None)`
   - Bounds: query 1-500 characters; limit 1-8; optional UUID scope.
   - Search only `candidate_analyses.status='accepted'`, `analysis_facts.status='accepted'`, and
     `evidence_bindings.validated=true`.
   - For the small local corpus, rank parameterized
     `websearch_to_tsquery('simple', query)` against a computed `to_tsvector` over accepted summary
     and fact text. Return exact quote, governed statement, evidence/fact/candidate/passage IDs,
     public source URL, source name/tier, and publication time. Do not return snapshot bucket/object
     keys, raw HTML, full normalized articles, or unvalidated passages.
   - This is honestly PostgreSQL full-text ranking, **not BM25** and not vector evidence search.

2. `retrieve_brand_context(query, valid_on, audience, document_kinds=(), limit=3)`
   - Reuse `retrieve_brand_context()` and the existing repository implementation unchanged in
     semantics; cap the workbench at five hits even though the underlying service allows ten.
   - Deterministic/MCP mode injects the existing fake 2,048-dimensional embedding adapter and uses a
     fixture corpus embedded with the same provider/model. Optional live CLI mode may inject the
     configured Zhipu embedding adapter only after its independent live gate passes.
   - Every result carries `evidence_eligible=false`; the answer/citation checker must reject a brand
     chunk used as factual evidence.

3. `validate_copy_contract(copy_run_id, draft, brand_chunk_ids=())`
   - Add a read-only projector that loads the locked topic/evidence and active requested brand chunks
     for an existing copy run, then calls `validate_material_draft()` with the persisted rule version.
   - Return only `accepted`, stable issue codes/severities/fields/claim IDs, and context IDs. Do not
     enqueue generation, create a draft, call the LLM auditor, or repair copy.

The catalog constructor is the hard allowlist. Do not include generic SQL, filesystem, URL fetch,
source acquisition, brand upload/activation, copy generation, image generation, WeCom delivery,
publishing, shell, or trace-write tools. Tool text is untrusted data; render it as bounded data and
never interpolate it into control instructions or log event names.

#### 2. Explicitly bounded LangGraph loop

Use a small custom `StateGraph`, not `create_agent`. A custom executor is preferable to the prebuilt
`ToolNode` here because the latter supports parallel execution, while this MVP needs deterministic
one-at-a-time budgets and a durable step record.

```text
START -> plan -> guard_calls -- final/no-call --> finalize -> END
                    |
                    `-- one valid call --> execute_tool -> plan
```

- State contains IDs, fingerprints, counters, statuses, selected tool/result IDs, and compact issue
  codes only. Store question, answer, excerpts, model messages, and structured tool payloads outside
  the checkpoint, following `GovernanceGraphState` and `CopyGenerationGraphState`.
- Use `thread_id = "research-workbench:{run_id}"`; when a run has a checkpoint, resume with
  `ainvoke(None, config)` rather than replaying tool calls.
- Hard limits: at most **4 planner turns, 6 total proposed calls, 1 executed call per turn, 8 rows per
  retrieval, 8 KiB structured output per tool, 5 s tool timeout, and `recursion_limit=16`**. Invalid
  arguments/unknown tools consume a call budget. On exhaustion, route to a typed partial final result
  with `budget_exhausted`; never rely on LangGraph's recursion exception as the normal stop rule.
- Execute sequentially. Use a local PostgreSQL statement timeout and a read-only transaction for
  repository tools. A tool failure becomes a small typed result (`invalid_arguments`, `timeout`,
  `not_found`, `unavailable`) and may be observed by the planner; never expose SQL/provider bodies.
- Planner port: `ResearchPlanner.plan(...) -> PlannerTurn` with structured tool calls/final answer and
  the established provider/model/fingerprint/token/latency fields. Implement a scripted deterministic
  planner first. The optional GLM adapter may use the existing safe HTTP/retry pattern, but needs the
  official `tools`/`tool_calls` message protocol and strict Pydantic argument validation.

LangGraph's official docs allow low-level graphs without LangChain and document explicit conditional
termination. The current default recursion limit is high, so the workbench must set its own limit and
track a separate business budget.

#### 3. Minimal durable trace and resume data

Add only two inert, workbench-owned tables through Alembic:

- `workbench_runs`: UUID, case/mode/status, bounded question/final answer (local artifact),
  question/answer fingerprints, graph/tool/prompt/schema/policy versions, aggregate prompt/completion/
  reasoning tokens, aggregate planner/tool/end-to-end latency, error code, timestamps.
- `workbench_steps`: run UUID + unique ordinal, node/kind/status, tool name/call ID, request fingerprint,
  bounded safe input/output projection JSONB, evidence/brand IDs, per-call tokens/latency, safe provider
  request ID, error code, timestamp.

The checkpoint remains the orchestration source for resumption; these tables are the human-readable
trace/eval source. Writes use short transactions before/after planner or tool execution, never across
provider or pgvector work. Stable `(run_id, ordinal)` and request fingerprints make resume writes
idempotent. Do not mine opaque checkpoint blobs for the UI and do not repurpose `model_invocations` or
`copy_generation_attempts`, whose foreign keys and capability constraints belong to other workflows.

#### 4. Same tools through MCP, without a production server

- Add `backend/app/workbench_mcp_main.py` as a separate import/run target using
  `from mcp.server import MCPServer`; register the catalog's three typed handlers.
- Support **stdio only**. Never mount it in `app.api_main`, never bind a socket, and never add it to
  Docker Compose/release manifests. Stdout is protocol framing; all application logs go to stderr.
- Startup refuses `APP_ENV=production`, refuses `AI_PROVIDER_MODE=zhipu`, and constructs only the
  local/fake embedding path. Repository operations run read-only. MCP annotations use
  `readOnlyHint=true` and `openWorldHint=false`, but these are descriptive hints, not enforcement;
  the allowlist, injected dependencies, startup guards, and database transaction mode are the real
  controls.
- Test tool discovery, schemas, structured output, bad arguments, and all three calls in process with
  the SDK's `Client(server)`; add one stdio smoke test with an allowlisted environment. No HTTP/SSE/
  WebSocket transport test is needed for the MVP.

This is materially safer than a localhost HTTP server: the SDK's own security page lists recent high
severity advisories around DNS rebinding, HTTP session principals, WebSocket Host/Origin validation,
and cross-client tasks. A subprocess-only stdio server avoids those network surfaces.

#### 5. Deterministic evaluation first; optional live metrics second

Create versioned synthetic cases under `backend/tests/fixtures/workbench/` (for example
`cases/*.json`) containing `case_id`, question, scripted planner turns, seeded evidence/brand records,
draft when applicable, required/forbidden tools, expected evidence IDs, expected brand IDs, expected
validation issue codes, and expected terminal status. Do not use real provider output as a fixture.

Deterministic pass/fail metrics:

| Metric | Contract |
| --- | --- |
| Completion/schema | terminal state reached; final answer and every tool result validate |
| Budget safety | calls/turns/bytes/rows/time never exceed configured caps; unknown or mutating tool count is zero |
| Tool routing | required-tool recall and forbidden-tool count; exact scripted sequence only in fake-mode graph tests |
| Retrieval | evidence Recall@k and MRR against expected IDs; selected IDs must come from returned rows |
| Citation integrity | citation precision (all IDs observed), factual-claim citation coverage, and brand-as-evidence violations = 0 |
| Copy gate | exact issue-code set plus error/warning severity match; hard-error escape rate = 0 |
| Replay | same case/version/fixture yields the same trace-result fingerprint after a clean run and after checkpoint resume |
| Telemetry | all planner calls have non-negative prompt/completion/reasoning tokens and latency; fake values remain zero by design |

Optional live evaluation is a separate CLI flag and report, never a pytest default. Require all of:
`APP_ENV=development`, `WORKBENCH_LIVE_ENABLED=true`, `AI_PROVIDER_MODE=zhipu`, an explicit `--live`,
and `--max-cases` (default at most 5). Reuse the deterministic citation/retrieval/validation metrics;
also report call count, prompt/completion/reasoning tokens, provider latency, tool latency, end-to-end
latency, and failures per case. Do not add an LLM judge to the MVP, do not make exact prose a pass
condition, and do not check live responses/credentials into the repository.

#### 6. Local trace / portfolio UI

Export a redacted manifest after each step and at terminal completion:

```text
output/workbench/index.json
output/workbench/latest.json
output/workbench/runs/<run-id>/manifest.json
```

Extend the existing traversal-safe Vite local-asset middleware with a sibling `/workbench` root and
add `frontend/src/features/workbench/{api.ts,hooks.ts,AgentWorkbenchPanel.tsx,...}`. Use React Query
and the preview panel's explicit empty/loading/failed/ready states. Gate rendering behind a local Vite
flag so production builds have no active workbench surface.

The panel needs only: case/question, mode and version fingerprint; plan/tool/final timeline; expanded
typed tool arguments and safe result excerpts; evidence citations versus brand context; metric cards
for calls, retrieval/citation/validation, tokens and latency; resume/replay status; and download of the
redacted manifest. It must have **no run, retry-provider, upload, activation, generation, delivery, or
publish control**. Render all model/source content as text.

#### 7. Dependency and lock implications

- Keep current runtime pins: `langgraph==1.2.10`,
  `langgraph-checkpoint-postgres==3.1.0`, `psycopg==3.3.4`,
  `psycopg-pool==3.3.1`, and locked `pgvector==0.5.0`. No `langchain`, model-provider SDK,
  LangSmith service, tracing SaaS, or frontend graph library is needed.
- Pin plain `mcp==2.0.0` (not `mcp[cli]`) in the existing `dev` optional dependency group, so
  `pip-compile --extra=dev` places it only in `dev.lock`. This matches local-only scope because the
  production Dockerfile installs only `runtime.lock`. MCP imports must therefore remain confined to
  the local MCP entrypoint/adapter.
- MCP 2.0.0 is the current stable line as of this research date and supports Python 3.10+. Its
  metadata requires Pydantic >=2.12, AnyIO, Starlette, Uvicorn, `mcp-types==2.0.0`, and a new
  `httpx2>=2.5.0` dependency family. Current Python/Pydantic/AnyIO/Starlette/Uvicorn bounds are
  compatible, but the generated hashed `dev.lock` is the authority; run normal lock-drift and full
  backend checks after regeneration.
- If MCP ever becomes a shipped/runtime capability, moving it to base dependencies, adding an HTTP
  transport, or mounting it in FastAPI requires a separate threat model and task. It is not an
  incremental toggle of this MVP.

### Suggested implementation slices

1. Tool contracts + accepted-evidence read query + read-only copy-context projector; unit/integration
   tests prove evidence/brand separation and zero writes.
2. Scripted planner + bounded LangGraph + two trace tables + checkpoint-resume test.
3. Deterministic fixtures/evaluator + redacted exporter + React manifest panel.
4. MCP dev dependency + stdio adapter + in-process protocol tests.
5. Optional GLM function-calling planner and explicitly gated live report last.

This order yields a complete portfolio artifact after slice 3; MCP and live inference cannot distort
the core safety/evaluation contract.

### MVP non-goals

- No arbitrary web browsing, URL fetch, filesystem/shell, SQL, email/chat, publishing, delivery, image
  generation, brand ingestion/activation, or other mutating tool.
- No production route, worker, scheduler, container, deployment unit, remote MCP transport, OAuth,
  multi-user tenancy, or public demo endpoint.
- No general conversation product, memory/vector store for chat, autonomous long-running research,
  multi-agent delegation, human approval workflow, or write-back from the UI.
- No evidence-passage vector migration in this slice. Existing article vectors are purpose-specific
  (`near_duplicate`/`event_assignment`) and must not be relabeled as research embeddings.
- No BM25 claim, external observability SaaS, LLM-as-judge, cost estimate without a versioned price
  table, or flaky provider call in CI.
- No attempt to turn the existing copy orchestration wrapper into the research agent graph.

### External references

- LangGraph graph API documents conditional loops and the standalone `recursion_limit` setting:
  https://docs.langchain.com/oss/python/langgraph/graph-api
- LangGraph's tool documentation describes `ToolNode`, conditional routing, parallel execution, and
  error handling; the MVP deliberately keeps a custom sequential executor for tighter budgets:
  https://docs.langchain.com/oss/python/langchain/tools
- LangGraph is usable without LangChain, supporting the current raw-HTTP provider architecture:
  https://docs.langchain.com/oss/python/langgraph/overview
- MCP Python SDK 2.0.0 (released 2026-07-28) is the current stable line; PyPI also documents
  `MCPServer`, plain-vs-CLI installation, Python compatibility, and in-process `Client(server)` tests:
  https://pypi.org/project/mcp/
- MCP transport docs designate stdio for local subprocess servers and explain that stdout is the wire:
  https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/run/index.md
- MCP tool annotations are hints, not a security boundary:
  https://modelcontextprotocol.io/specification/2025-11-25/schema#toolannotations
- MCP SDK supported-version policy and current transport/session advisories:
  https://github.com/modelcontextprotocol/python-sdk/security
- Zhipu's official function-calling guide documents `tools`, `tool_choice=auto`, `tool_calls`, JSON
  arguments, call IDs, and tool-result messages for GLM-5.2:
  https://docs.bigmodel.cn/cn/guide/capabilities/function-calling
- Zhipu's official chat-completions schema documents tool messages and token usage:
  https://docs.bigmodel.cn/api-reference/%E6%A8%A1%E5%9E%8B-api/%E5%AF%B9%E8%AF%9D%E8%A1%A5%E5%85%A8

### Related specs

- `.trellis/spec/backend/index.md` — stored evidence, provider-call boundaries, deterministic validation,
  and no automatic publishing.
- `.trellis/spec/backend/agent-pipeline.md` — small checkpoint state, typed stages, evidence/brand
  separation, idempotency, and bounded repair.
- `.trellis/spec/backend/brand-knowledge-rag.md` — internal-only, versioned, filtered hybrid retrieval
  with `evidence_eligible=false`.
- `.trellis/spec/backend/database-guidelines.md:83` — short transactions, durable provenance, truthful
  FTS terminology, separate evidence/brand queries, and Alembic ownership.
- `.trellis/spec/backend/logging-guidelines.md:52` — no prompts, responses, embeddings, provider payloads,
  storage paths, secrets, or sensitive child data in logs.
- `.trellis/spec/backend/error-handling.md:78` — safe typed errors rather than traces/provider bodies.
- `.trellis/spec/frontend/index.md` and `.trellis/spec/frontend/quality-guidelines.md:88` — typed local
  review UI, visible provenance, safe text rendering, accessibility, and no publishing controls.

## Caveats / Not Found

- At research start the task PRD was still the Trellis placeholder, so this document records an
  evaluated design option rather than the final product decision. The converged `prd.md`/`design.md`
  control where they intentionally choose an ephemeral trace instead of the durable-table option here.
- There is no existing MCP dependency, MCP entrypoint, research tool registry, workbench schema, or
  reusable workbench eval-case format in the repository.
- There is no general factual-evidence pgvector index. Brand RAG legitimately reuses pgvector, but
  evidence search should remain accepted-fact PostgreSQL FTS until a separately versioned evidence
  embedding schema and migration exist.
- Existing candidate detail HTTP responses include internal snapshot metadata; workbench tools and
  manifests need a narrower projection and must not reuse those responses wholesale.
- Existing token/latency tables cannot represent research planner calls because their foreign keys and
  check constraints are workflow-specific; a small workbench-owned trace record is required.
- The deterministic fake embedding is suitable only when the seeded brand corpus uses the same fake
  provider/model identity. It cannot query a corpus embedded with Zhipu because the current brand RAG
  correctly filters provider/model identity.
- MCP 2.0.0 is new and has a larger transitive dev dependency surface. Exact pinning, generated hashes,
  in-process conformance tests, and keeping it out of the production runtime lock are important.
- No provider, production database, SSH host, deployment, scheduler, worker, or preview pipeline was
  invoked during this research.
