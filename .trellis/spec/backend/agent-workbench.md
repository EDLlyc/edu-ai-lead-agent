# Local Agent Workbench

## Scenario: Read-only portfolio Agent with one canonical tool registry

### 1. Scope / Trigger

Use this contract for a recruiter-facing Agent demonstration that reuses governed evidence, event,
brand, and copy-validation capabilities without joining the production API or business automation.
The workbench is a separate, ephemeral, local-only vertical slice. It must not add a production
route, Compose service, migration, delivery action, arbitrary URL fetch, shell, or durable trace.

The canonical architecture is one immutable typed registry consumed by three adapters:

1. the bounded LangGraph runner;
2. the stdio-only MCP server;
3. the deterministic evaluation runner.

Do not create protocol-specific tool implementations or duplicate business rules.

### 2. Signatures

- Local API launcher:

  ```bash
  AGENT_WORKBENCH_ENABLED=true \
    uvicorn app.agent_workbench_api_main:app --host 127.0.0.1 --port 8010
  ```

- HTTP:

  ```text
  POST /api/v1/agent-workbench/runs
  request  = {query, scenario_id?, model_mode?}
  response = {run_id, status, summary, claims, citations, steps, metrics}
  ```

- MCP: `python -m app.agent_mcp_main` over stdio only.
- Eval: `cd backend && python -m evals.agent_workbench.runner --check`.
- Digital-IP projection eval: `cd backend && python -m evals.digital_ip.runner --check`.
- Portfolio gate: `make agent-portfolio-check`.
- Real deterministic portfolio capture: `make agent-portfolio-capture`.
- One-shot live preflight/capture: `make agent-portfolio-live-zhipu-preflight` followed by
  `make agent-portfolio-live-zhipu-capture`; only the separately authorized operator may run the
  second command.
- Registry tools: `search_evidence`, `get_event`, `retrieve_brand_context`, `validate_copy`.

### 3. Contracts

#### Registry and runner

- Each `ToolDefinition` owns one name, bounded description, strict Pydantic argument/result models,
  timeout, output-size cap, and read-only metadata.
- Agent, MCP, and eval derive JSON Schema from the same `TypedToolRegistry`; adapters may add their
  protocol envelope but may not alter tool semantics.
- The graph executes one tool at a time and enforces at most four model turns and four tool calls,
  plus explicit deadline, token, argument, result, and response limits. Four completed calls may be
  followed by a remaining final-synthesis turn; a proposed fifth call is rejected.
- Final output uses bounded claims with citation IDs. The runner builds a claim-used-only citation
  catalog from successful results in the same run. Brand chunks remain `evidence_eligible=false`.
- Trace fields are safe action/observation projections. Never expose hidden reasoning, full prompts,
  provider bodies, secrets, database URLs, private object paths, or fetched/brand full text.

#### Read boundaries

- PostgreSQL workbench sessions execute `SET TRANSACTION READ ONLY`, apply a statement timeout, map
  ORM rows before rollback, and release the connection before any model turn.
- `search_evidence` reuses governed, validated Tier A/B evidence predicates and performs bounded
  PostgreSQL full-text search. It must not be described as pgvector or BM25.
- Event versions are built from the production event aggregate. Workbench-specific duplicate
  suppression stays in its adapter/query; do not narrow shared event/copy semantics merely to shape
  a workbench response.
- `get_event` projects at most eight distinct member cards and eight sources globally.
- Brand embedding/provider work completes before opening the retrieval DB session. An absent or
  incompatible active embedding identity returns typed unavailable, never an implicit fallback.
- `validate_copy` calls `validate_material_draft`. Acceptance is calculated from the complete issue
  sequence; only the displayed issue list is capped at 32.

#### Local-only boundary

- `app.agent_workbench_api_main` is independent from `app.api_main`; production OpenAPI, Dockerfile,
  and Compose do not import or register it.
- The feature defaults disabled and refuses production startup. Every path, including health/docs,
  rejects a non-loopback socket peer and any `Forwarded` or `X-Forwarded-*` header.
- CORS allows exactly `http://127.0.0.1:5173`, with no wildcard and no credentials.
- Deterministic fixture mode is the default. OpenAI-compatible mode requires development, explicit
  live opt-in, a configured base URL/key, and is never part of CI-authoritative results.
- Recruiter-facing real-run evidence starts independent Uvicorn and Vite processes on the exact
  loopback ports, records a browser-originated POST without route fulfillment, and compares its
  safe terminal/tool/citation/step projection with a separate direct HTTP probe. Run IDs and
  latency are diagnostic and may differ. Screenshot JSON must be the response for the same browser
  run shown in the screenshot.
- The deterministic capture owns three sanitized cases in one checked manifest, strips PNG
  metadata, stores only relative paths and SHA-256 hashes, scans public artifacts for credentials
  and private paths, and cleans all child process groups on success, failure, or signal.
- The authorized live capture selects only the multi-tool fixture case and performs exactly one
  browser Agent run with at most four model decisions and no whole-case retry. It maps existing
  local AI platform settings internally into the isolated Workbench process, accepts only the
  credential-free official Zhipu API root, never passes provider settings to Vite, and reserves a
  one-shot output path before the call. Typed failure is evidence and must not trigger a second run.
- Public citation projection accepts normalized HTTPS only and rejects credentials, fragments, IP
  literals, ambiguous/local hostnames, and reserved/special-use suffixes such as `.test`, `.example`,
  `.invalid`, `.onion`, and `home.arpa`.
- The separate five-case digital-IP eval reuses the versioned profile projection for positioning,
  tone, prohibited-language, safety, and visual fixtures. Its canonical JSON/Markdown reports
  fixture contract conformance, expected kind/tag coverage, prohibited-rule hits, and
  brand-as-fact violations. It must never be described as live retrieval, embedding, or model
  accuracy.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Disabled flag | HTTP 404 `agent_workbench_disabled`; zero model/tool calls |
| Production + enabled | Settings failure before startup |
| Non-loopback peer or forwarding header | HTTP 403 `agent_workbench_loopback_required` on every path |
| Unknown/invalid tool arguments | Stable safe tool error; handler is not called |
| Tool timeout, oversized args/result, provider failure | Typed bounded failure; no raw exception/body and no retry loop |
| Fifth proposed tool call or deadline reached | `budget_exhausted`; no execution |
| External claim cites brand or unknown ID | Refuse/reject final answer; do not publish an unattached citation |
| Invalid/reserved/non-public URL | Omit/reject the link; never render it as clickable |
| Validator issue 33 is a hard error | `accepted=false` while response still contains at most 32 issues |
| DB write attempted in a tool transaction | PostgreSQL rejects it; rollback and connection counts remain stable |
| MCP receives unknown/invalid call | Stable structured error through official SDK; no second registry |

### 5. Good / Base / Bad Cases

- Good: fixture Agent selects a registered tool, returns one grounded claim with a citation from the
  same successful result, exposes a redacted timeline, and stays within four calls.
- Base: insufficient governed evidence returns a typed refusal with no fabricated citation.
- Good: a real local PostgreSQL test proves governed search/event projection, read-only rejection,
  durable-count stability, and pool release without using production data.
- Bad: letting `issues[:32]` determine acceptance, storing trace in an unrelated business table,
  fetching arbitrary URLs, holding a DB session across embedding/model execution, or reporting the
  deterministic fixture score as live-model accuracy.

### 6. Tests Required

- Unit: registry duplicate/unknown/invalid/timeout/size cases; four-call boundary; cancellation;
  citation binding; trace privacy; full-issue acceptance with bounded projection.
- Provider contract: MockTransport request/response schemas, malformed/duplicate tool calls, safe
  usage/error projection, and zero network in the default path.
- MCP contract: official in-memory and subprocess stdio clients list and call the exact four registry
  tools, including read-only annotations and safe failures.
- PostgreSQL integration: governed search/event, duplicate projection, `READ ONLY` write rejection,
  durable-count stability, rollback, and pool checkout return.
- HTTP: disabled/local/production, loopback peer, forwarding spoof, exact CORS preflight, request ID,
  cancellation, response bounds, and proof that normal `api_main` lacks the route.
- Eval: versioned sanitized cases, oracle isolation, paired tool-call/tool-result grading, stable
  canonical JSON/Markdown, and registry hash drift.
- Final gates: `make agent-portfolio-check`, `make backend-check`, lock/OpenAPI/Alembic/Compose/Doctor
  checks, shell syntax, diff check, and scoped secret scan.
- Portfolio capture harness: case-manifest schema/uniqueness/safe text, exact-host and port-collision
  rejection, forbidden API interception, direct/UI semantic mismatch, process cleanup, PNG metadata,
  relative-link/hash verification, and public-artifact privacy scanning.

### 7. Wrong vs Correct

#### Wrong

```python
visible = issues[:32]
return ValidateCopyResult(
    accepted=not any(issue.severity == "error" for issue in visible),
    issues=visible,
)
```

This lets response truncation change a safety verdict.

#### Correct

```python
all_issues = validate_material_draft(...)
return ValidateCopyResult(
    accepted=not any(issue.severity == "error" for issue in all_issues),
    issues=all_issues[:32],
)
```

Likewise, keep workbench-only projection constraints in the workbench adapter; never rewrite shared
production event/copy semantics to make a portfolio response easier to shape.
