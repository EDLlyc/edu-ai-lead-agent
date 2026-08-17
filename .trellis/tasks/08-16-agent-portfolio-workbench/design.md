# 本地 Agent 求职作品集工作台 — Design

## 1. Design intent

本设计增加一条独立的本地演示纵向切片，不改变现有新闻采集、治理、内容、图片和企微流程。
它复用现有事实/事件 read models、品牌 RAG service 与确定性文案校验，但用新的 application
boundary 把它们投影为四个受控只读 tools。Tool registry 是 Function Calling、MCP 与 eval 的
共同 source of truth。

工作台不是“让模型自由行动”的聊天框。它是一个最多四步、每一步都有 schema、预算和
trace 的 orchestrator。Trace 只解释系统采取的动作与观察结果，不收集隐藏思维链。

## 2. Architecture

```text
React AgentWorkbenchPanel
          |
          | generated OpenAPI
          v
agent_workbench_api_main.py -- loopback + socket-peer gate
POST /api/v1/agent-workbench/runs
          |
          v
Bounded LangGraph Runner ---- ToolCallingModel port
    |                         |-- Deterministic policy adapter (default)
    |                         |-- Recorded adapter (focused tests only)
    |                         `-- OpenAI-compatible adapter (explicit local opt-in)
    |
    v
TypedToolRegistry
    |-- search_evidence ------ governed evidence read adapter
    |-- get_event ------------ existing governance event projection
    |-- retrieve_brand_context existing brand retrieval boundary
    `-- validate_copy -------- existing deterministic validation boundary
    |
    +------------------------> MCP stdio adapter (official SDK)
    `------------------------> Offline eval runner

Run result = summary + claims + safe citation catalog + redacted steps + metrics
             (response/export only; no new durable table)
```

## 3. Component ownership

Exact filenames may be adjusted to match nearby modules during Phase 2, but ownership boundaries are
fixed.

### 3.1 Domain and application contracts

- `backend/app/domain/agent_workbench.py`
  - provider-independent statuses, citation kinds, budgets and trace event value objects;
  - no FastAPI, SQLAlchemy, MCP or provider imports.
- `backend/app/application/ports/agent_workbench.py`
  - `ToolCallingModel`, evidence/event/brand read ports and a monotonic clock;
  - model output is a discriminated `final_answer | tool_calls` result.
- `backend/app/application/services/agent_workbench.py`
  - shared `TypedToolRegistry` and four tool handlers;
  - run facade, citation validation, budget enforcement and redacted metrics;
  - no transaction spans a model/tool call and no handler writes durable state.
- `backend/app/application/services/agent_workbench_graph.py`
  - a small typed LangGraph (`model -> one tool -> model | terminal`) with explicit step/tool/time
    guards in addition to the framework recursion limit;
  - no PostgreSQL checkpointer because the run is intentionally ephemeral.

Tool definitions contain a stable name, bounded description, Pydantic argument model, Pydantic result
model, timeout and maximum serialized result size. Registry construction rejects duplicate names and
non-read-only metadata. Model-facing JSON Schema, MCP registration and eval snapshots are derived from
these definitions.

### 3.2 Read adapters and business reuse

- Evidence search promotes the validated EventVersion -> Tier A/B binding logic currently owned by
  `infrastructure/db/copy_generation.py::_load_evidence` behind a shared read port; it does not reuse the
  merely chronological candidate listing, crawl, or create snapshots.
- Event detail delegates to `infrastructure/db/governance_queries.py::get_event_detail` and its existing
  projection rather than reconstructing event membership.
- Brand retrieval calls `application/services/brand_knowledge.py::retrieve_brand_context` and preserves
  `evidence_eligible=false` in every result.
- Copy validation calls `domain/copy_generation.py::validate_material_draft`. If the existing concrete
  topic type is too broad, it is narrowed to a structural read-only Protocol implemented by both the
  production context and fixture context; rules are not copied. The tool returns typed issues only and
  does not generate, repair, persist or enqueue a draft.

Tests provide an in-memory sanitized backend implementing the same ports. The default portfolio demo
uses that backend so it has no database/provider prerequisite; an explicitly selected local-database
adapter may read an existing developer stack but is never the CI source of truth.

### 3.3 Tool-calling model adapters

- `RecordedToolCallingModel` consumes versioned decisions only in focused runner/adapter tests. It must
  never receive an eval case's expected tools, citations or outcome and cannot be used to claim model
  quality.
- `DeterministicPolicyToolCallingModel` is the no-key demo/offline baseline. It applies one fixed policy
  to query + successful trace + registry only; it cannot inspect eval oracle fields. Its report proves
  the evaluator, boundaries and reproducibility, not LLM intelligence.
- `OpenAICompatibleToolCallingModel` serializes registry schemas into the standard `tools` request,
  accepts only known tool call IDs/names and bounded JSON arguments, and projects only safe usage and
  finish metadata. `httpx.MockTransport` owns all required tests.
- The adapter does not log or persist system/user messages, response bodies or provider reasoning.
  Optional local live mode reuses existing secret settings and requires an explicit setting/CLI flag.

The runner processes at most four model responses and four tool executions. Parallel calls returned in
one model response are executed in stable order and count individually; calls beyond the remaining
budget are rejected without execution. A final answer after budget exhaustion is not silently accepted.

### 3.4 MCP

- Add the official MCP Python SDK to the development/local toolchain with a bounded stable-major pin.
- `backend/app/agent_mcp_main.py` constructs the same registry and exposes it through stdio only.
- No MCP server is imported by `api_main`, added to Compose, or bound to a TCP port.
- MCP errors contain stable codes and bounded safe messages. Tool results remain structured and carry
  the same citation/brand boundary as direct Agent calls.

The implementation must follow the installed official SDK's current v2 API (`MCPServer` line at the
time of planning), not copy v1 `FastMCP` examples. Pin `mcp==2.0.0` in the dev extra/lock. An in-memory
official client test is authoritative for discovery, list, call and lifecycle behavior; v2 has no normal
handshake/session contract, so legacy initialize fallback is out of scope.

### 3.5 API and schemas

- Add `backend/app/schemas/agent_workbench.py` for HTTP requests/responses. MCP types never become HTTP
  schemas.
- Add `backend/app/agent_workbench_api_main.py` as an independent local ASGI app plus a route module
  with one synchronous-run endpoint:

  ```text
  POST /api/v1/agent-workbench/runs
  -> AgentWorkbenchRunResponse
  ```

- Request contains a bounded query and optional allowlisted fixture scenario/model mode. It cannot
  supply arbitrary provider URL, model key, tool list, prompt or budget.
- Response contains `run_id`, terminal status, bounded summary, structured claims with per-claim
  citation IDs, a runner-built citation catalog, ordered steps and metrics. Catalog entries are
  `id`, `kind`, bounded `source_name`/`title`, validated HTTPS `url` for factual evidence, and
  `evidence_eligible`; brand entries have no public URL and remain evidence-ineligible. Every catalog
  entry must be referenced by a claim and originate from this run's successful tool result. The final
  schema is validated before citation checks; unattached or invented entries are rejected.
- Existing `app.api_main`, Dockerfile and Compose never import/register this router. A separate exporter
  creates `backend/openapi.agent-workbench.json` and a separate generated frontend schema; both have
  drift checks.
- The Make/demo launcher binds `127.0.0.1` explicitly. ASGI middleware/dependency independently checks
  the real socket peer (`request.client.host`) with `ipaddress.ip_address(...).is_loopback`; it does not
  consume proxy metadata and rejects any `Forwarded`/`X-Forwarded-*` header or non-loopback peer.
  Settings also reject production or a disabled flag. This remains safe even if someone manually
  launches uvicorn on `0.0.0.0`.

No migration is expected. If a durable run table becomes necessary, implementation must stop and return
to planning instead of silently expanding scope.

### 3.6 Exact bounded contracts

Global run limits:

- user query: 1–500 Unicode characters;
- at most 4 model turns, 4 executed/proposed tool calls, one sequential execution at a time;
- model HTTP timeout 15 seconds, tool timeout 5 seconds, end-to-end deadline 30 seconds;
- final summary at most 1,200 characters; at most 8 claims, 400 characters per claim and 5 citation
  IDs per claim; citation catalog at most 20 entries, source name <=120 and title <=200 characters;
- model response at most 256 KiB, tool arguments at most 16 KiB, each structured tool result at most
  32 KiB, redacted run response at most 128 KiB.

| Tool | Input bounds | Output bounds / behavior |
| --- | --- | --- |
| `search_evidence` | `query` 1–500 chars; `limit` 1–5; optional candidate UUID | Up to 5 validated Tier A/B hits; quote <=500 chars each; stable evidence/event/source IDs and HTTPS URL only |
| `get_event` | exact event UUID | One governed event; summary <=1,000 chars; up to 8 members/sources, title <=200 chars each |
| `retrieve_brand_context` | `query` 1–500 chars; one ISO date; audience fixed to `parents`; <=4 allowlisted kinds; `limit` 1–5 | Up to 5 excerpts <=500 chars; every item carries `evidence_eligible=false` |
| `validate_copy` | exact `copy_run_id` UUID plus existing bounded `MaterialDraft`; serialized args <=16 KiB | Load immutable validation context; at most 32 typed issues; never generate, repair, persist or audit |

The fixture reader uses stable fake UUIDs and the same contracts. The local database adapter uses
read-only transactions with a statement timeout. PostgreSQL evidence search is honestly described as
`websearch_to_tsquery`/`to_tsvector` FTS over accepted facts/bindings; no evidence pgvector/BM25 claim is
allowed.

Stable errors:

| Condition | Result |
| --- | --- |
| Feature disabled | HTTP 404 `agent_workbench_disabled`; no model/tool call |
| Workbench enabled in production | Settings validation failure before startup |
| Non-loopback socket peer or any forwarding header | HTTP 403 `agent_workbench_loopback_required`; no model/tool call |
| Invalid HTTP/tool args or oversized request | HTTP 422 or trace code `agent_tool_invalid_arguments`; no handler call |
| Unknown tool | `agent_tool_unknown`, consumes one call budget, no handler call |
| Tool timeout/unavailable/not found | `agent_tool_timeout` / `agent_tool_unavailable` / `agent_tool_not_found`; safe observation, no automatic retry |
| Model timeout/unavailable/malformed response | HTTP 503 or terminal `agent_model_unavailable` / `agent_model_invalid_output`; no raw body |
| Four-step/call/deadline limit | terminal `budget_exhausted`; no fifth call |
| Unsupported or brand-as-fact citation | terminal `unsupported_citation`; answer not accepted |
| Caller cancellation | owned work cancelled; typed internal `cancelled`; no retry or partial success |

### 3.7 Trace projection

Allowed step fields:

- ordinal, kind (`model_decision`, `tool_call`, `tool_result`, `final`, `error`), stable status/code;
- tool name and an allowlisted argument summary (IDs, query length/hash, requested limit; no raw secret);
- duration, item/issue counts, citation IDs and truncated safe display labels;
- provider/model identity and token counts only when supplied as typed metadata.

Forbidden fields:

- hidden reasoning/chain-of-thought, full system/user prompts, provider body or exception text;
- API keys, headers, DB/MinIO URLs, private object keys, full brand documents or fetched pages;
- arbitrary model-generated HTML/Markdown rendered as HTML.

The UI may show a deterministic action label such as “检索事实证据”, not a fabricated narrative of
the model's private reasoning.

### 3.8 Frontend

Create a focused `frontend/src/features/agent-workbench/` feature consuming the separately generated
workbench OpenAPI schema:

- `api.ts`: generated wire types -> readonly view models and safe status labels;
- `hooks.ts`: one mutation owner with cancellation and stale-response isolation;
- `AgentWorkbenchPanel.tsx`: presets/query form, answer/citations, trace timeline and metrics;
- small components for RunStatus, TraceStep, CitationList and EvalSummary as justified by the final
  layout; component props remain local.

The page renders untrusted text as text, validates external HTTPS links, provides keyboard focus and
aria-live result/error announcements, and uses text/icon labels in addition to color. It has explicit
idle/running/completed/refused/budget-exhausted/failed states and no publish/send controls.
The App renders this feature only when `import.meta.env.DEV` and an explicit Vite workbench flag are
both true; a production Vite build contains no active navigation entry or runnable workbench surface.

## 4. Eval design

### 4.1 Dataset

Store at least 40 JSONL cases under a dedicated backend eval/fixture path. Cases contain only synthetic
or short sanitized public-source excerpts and stable fake IDs. Six categories must each have multiple
positive and negative examples:

1. evidence search;
2. event detail;
3. brand-context retrieval and evidence separation;
4. deterministic copy validation;
5. multi-tool synthesis;
6. insufficient evidence, injection, side-effect or unsupported-tool refusal.

Each case defines allowed/required/forbidden tools, expected argument constraints, allowed citation
IDs, required fact IDs, expected terminal class, maximum steps and deterministic safety assertions. It
does not encode a single exact prose answer as the primary oracle, and those oracle fields are never
passed into the model adapter.

### 4.2 Metrics

- task success by category;
- exact/set tool-selection precision and recall;
- valid argument rate and unknown-tool count;
- citation precision, citation coverage and unsupported citation count;
- deterministic groundedness/required-fact coverage for fixture facts;
- refusal precision/recall for unsafe or insufficient-evidence tasks;
- budget/timeout violations, step/tool-call counts and terminal-state accuracy;
- p50/p95 latency and token usage when typed usage exists.

Deterministic rules are authoritative. An optional judge score may be reported separately but cannot
turn a deterministic safety/grounding failure into a pass.

### 4.3 Reports and commands

- A stable contract baseline report is checked in as canonical JSON plus human-readable Markdown.
  Canonical output excludes timestamps, random run IDs and wall-clock latency/token fields; cases and
  aggregates use stable ordering. Volatile runtime diagnostics are emitted only to an ignored report.
- `make agent-eval` runs the offline dataset; `make agent-portfolio-check` additionally verifies
  registry/MCP schema parity and report drift. Final names may change only to fit existing Make naming.
- Optional live/local model output goes to an ignored timestamped location and is explicitly labeled
  non-authoritative; CI never needs a key or network.

## 5. Security and configuration matrix

| Condition | Required result |
| --- | --- |
| Workbench flag absent/false | Route unavailable; existing application unchanged |
| Route requested through normal `api_main`/Docker | Route absent |
| Workbench true + production/non-loopback socket peer | Startup or request rejected; forwarding headers ignored |
| Default fake mode | No external provider or database required |
| Optional live mode without explicit opt-in/key | Typed configuration failure before HTTP |
| Unknown tool / invalid args / oversized output | No execution; safe typed trace error |
| Tool timeout/cancellation | Cancel owned work, record bounded status, no retry loop |
| Request asks for write/send/shell/web | Refusal; zero side effects |
| Brand chunk cited as factual evidence | Deterministic final-answer validation failure/refusal |
| Model cites ID absent from successful tool results | Unsupported-citation failure |
| MCP client connects over stdio | Same four tools/schema/result contracts |
| MCP HTTP/SSE requested | Unsupported in this task |

## 6. Verification strategy

Focused implementation gates:

- pure registry, budget, trace and citation unit tests;
- tool adapters with fake repositories and existing validator regressions;
- MockTransport tool-calling adapter contract tests;
- official MCP in-memory client contract tests and schema parity snapshot;
- API enabled/disabled/production-config tests and OpenAPI export;
- independent-entrypoint tests proving normal `api_main` lacks the route and non-loopback/spoofed peers
  are rejected;
- eval golden/report-drift tests;
- frontend mapper, interaction, error-state and accessibility tests.

Final gates run once after production code freezes:

- backend Ruff, strict mypy and full pytest;
- frontend OpenAPI drift, Prettier, ESLint, TypeScript, Vitest and Vite build;
- Python lock drift, Compose render/Doctor compatibility, shell syntax and diff/secret scans;
- explicit proof that no normal API route, Compose production service, Alembic head, delivery route or
  server setting was changed.

## 7. Portfolio narrative

The case study must distinguish facts from claims:

- existing system context: governed evidence, pgvector brand RAG, LangGraph and deterministic audits;
- problem: powerful pipeline but no standardized Agent tool boundary or measurable Agent evaluation;
- solution: one registry reused by bounded Function Calling, MCP and eval;
- safety: read-only allowlist, schema validation, four-step budget, citation enforcement, local-only flag;
- evidence: reproducible metric report, contract tests, trace screenshot and architecture diagram;
- limitations: deterministic baseline is not a real-model quality claim; auth/persistent AgentOps/HTTP MCP
  are deferred.

Resume bullets will be generated only from measured repository outputs and will avoid unverified
production or accuracy claims.

## 8. Trade-offs and rejected alternatives

- The research option proposed PostgreSQL checkpoints plus `workbench_runs/workbench_steps`. This MVP
  deliberately rejects that design: resume/history is not required to prove Function Calling, MCP,
  evaluation or trace projection, while two tables and checkpoint lifecycle would add migration,
  recovery and privacy obligations. Run trace therefore lives in the current response; canonical eval
  artifacts provide reproducible evidence. Durable AgentOps is a separately planned follow-up.
- The research option proposed a static manifest-only UI. This design keeps one local-only HTTP vertical
  slice because generated OpenAPI, cancellation and live trace states are existing strengths worth
  showing. The default model/data remain fixtures, so the page is still deterministic and provider-free.
- Four tools are retained rather than three because `get_event` demonstrates multi-step drill-down
  without overloading `search_evidence`; both use the same governed read model and remain read-only.
- A custom LangGraph is retained as a resume-relevant engineering signal, but it has only two behavior
  nodes, no checkpoint and explicit business budgets. A generic prebuilt agent, memory, parallel tools
  and multi-agent delegation are intentionally excluded.
- The local PostgreSQL adapter is covered as an integration boundary because it proves reuse of real
  governed data. The default UI/eval use fixtures. Actual live-model execution and any production data
  demonstration are deferred even though the MockTransport-tested adapter is implemented.
