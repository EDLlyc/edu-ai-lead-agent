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

- MCP over stdio only:
  - fixture/portfolio: `python -m app.agent_mcp_main`;
  - explicit development PostgreSQL: `python -m app.agent_mcp_real_data_main` with
    `AGENT_MCP_DATA_MODE=postgres` and `AGENT_MCP_REAL_DATA_ENABLED=true`.
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
- The real-data MCP is a separate development-only stdio entrypoint, not a mode that changes the
  fixture process. It requires the two explicit MCP settings above, configured Zhipu
  planning/reranking, and the independent Alibaba multimodal brand Embedding provider. It composes
  the canonical registry over `PostgresAgentKnowledgeReader` and owns the engine/HTTP-client
  lifecycle. It may return bounded real tool projections only to the local caller; it never
  connects to production, exposes HTTP, writes, or falls back to fixture.
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
- Real-data MCP unit tests cover explicit opt-in, development/provider rejection, registry schema
  equivalence, and resource cleanup. Existing PostgreSQL integration coverage remains the proof of
  read-only transactions, stable durable counts, and returned pool connections.
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

## Scenario: Explicit development PostgreSQL MCP

### 1. Scope / Trigger

Use this contract when a developer deliberately needs the local MCP client to query governed data in
the current development PostgreSQL database. It prevents a convenience switch from silently changing
the deterministic fixture portfolio server, connecting to production, or leaking real data into an
unbounded process.

### 2. Signatures

```bash
APP_ENV=development \
AGENT_MCP_DATA_MODE=postgres \
AGENT_MCP_REAL_DATA_ENABLED=true \
python -m app.agent_mcp_real_data_main
```

The entrypoint composes `build_postgres_agent_tool_registry(...)` and returns the same four
`TypedToolRegistry` schemas as `python -m app.agent_mcp_main`.

### 3. Contracts

- `AGENT_MCP_DATA_MODE` is `fixture` by default. `postgres` requires
  `AGENT_MCP_REAL_DATA_ENABLED=true`; the latter is development-only.
- `Settings.app_env` and `AgentWorkbenchSettings.app_env` must both be `development`; the real entry
  requires configured Zhipu planning/reranking plus the independent Alibaba multimodal brand
  Embedding provider.
- The real entry owns the SQLAlchemy engine and its HTTP Embedding client in the MCP lifespan and
  closes both when STDIO exits. It uses `PostgresAgentKnowledgeReader`, which retains its read-only
  transaction, timeout and rollback guarantees.
- `search_evidence`, `get_event`, `retrieve_brand_context`, and `validate_copy` retain their normal
  bounded projections. Brand excerpts and validation context are returned only to the local MCP
  caller; brand chunks remain factual-evidence ineligible.
- This command does not bind a port, enqueue work, mutate data, publish content, expose raw files or
  provider bodies, or introduce a fallback from PostgreSQL to fixture data.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| `APP_ENV` is not development | Startup fails before engine/provider construction |
| Real-data enablement is absent | Startup fails with an explicit-enable error |
| Data mode is not `postgres` | Startup fails; fixture is not selected implicitly |
| Alibaba brand Embedding is disabled or fake | Startup fails; a brand identity mismatch is not hidden |
| Active brand vector provider/model differs | `retrieve_brand_context` returns bounded `agent_tool_unavailable` |
| STDIO server exits | HTTP client closes and engine disposes |

### 5. Good / Base / Bad Cases

- Good: a local Codex MCP process explicitly starts the real entry, lists the unchanged four tools,
  and queries bounded governed projections through PostgreSQL read-only sessions.
- Base: the fixture entry remains available for deterministic evaluation and public portfolio demos.
- Bad: replacing the fixture entry's default reader, allowing fake embeddings to query real brand
  vectors, starting this command in production, or retaining an engine/client after the server exits.

### 6. Tests Required

- Unit-test the settings opt-in, development/provider rejection, schema equivalence with fixture,
  and engine/client lifetime cleanup without constructing a real provider request.
- Keep the existing official MCP fixture contract tests unchanged.
- Keep the PostgreSQL workbench integration test proving Tier A/B evidence filtering, read-only write
  rejection, unchanged durable counts and returned pool connections.
- A manually authorized developer smoke may invoke all four tools against local data, but records
  only tool status/counts and never commits real text, identifiers, URLs or credentials.

### 7. Wrong vs Correct

#### Wrong

```python
def build_agent_mcp_server() -> AgentWorkbenchMCPServer:
    return AgentWorkbenchMCPServer(build_postgres_agent_tool_registry(...))
```

This silently changes the portfolio MCP's default data boundary.

#### Correct

```python
# app.agent_mcp_main: fixture only
build_agent_mcp_server(build_agent_tool_registry(build_fixture_reader()))

# app.agent_mcp_real_data_main: explicit development composition
create_real_data_mcp_server().run(transport="stdio")
```

Separate entrypoints make the invocation boundary visible and preserve deterministic fixture use.

## Scenario: Controlled retrieval enhancement for the real-data MCP

### 1. Scope / Trigger

Use this contract when changing query normalization/rewrite, multi-query fusion, reranking, or
process-local retrieval caches used by `app.agent_mcp_real_data_main`. The enhancement decorates the
real PostgreSQL reader only. It is not a second Agent and must not change the fixture registry,
canonical four-tool schemas, five-second tool timeout, evidence governance, or brand filters.

### 2. Signatures

```python
AgentQueryPlanner.plan(
    *, query: str, retrieval_kind: AgentRetrievalKind
) -> AgentQueryPlan

AgentTextReranker.rerank(
    *, query: str, documents: tuple[str, ...], limit: int
) -> AgentTextRerankResult

build_postgres_agent_tool_registry(
    session_factory,
    *,
    brand_embeddings,
    brand_retrieval_version,
    query_planner=None,
    text_reranker=None,
) -> TypedToolRegistry
```

The Zhipu planner uses `POST <AI_PLATFORM_BASE_URL>/chat/completions` with the configured
`AI_CHAT_MODEL`, JSON response mode, thinking disabled, deterministic sampling, and at most one
rewrite. The Zhipu text reranker uses `POST <AI_PLATFORM_BASE_URL>/rerank`, model `rerank`, at most
ten bounded documents, and `return_documents=false`. Brand vectors use the separately configured
Alibaba multimodal `qwen3-vl-embedding` identity at 2048 dimensions; governance event/article
vectors continue to use Zhipu `embedding-3` and are not migrated by this scenario.

### 3. Contracts

- `AgentQueryPlan` always keeps the normalized original query. It contains zero or one rewritten
  query, a retrieval-kind-matching closed intent, source, stable version, and fingerprint.
- A rewrite must differ from and retain lexical overlap with the original. Provider output cannot
  add an unrelated entity/event and cannot create an open-ended rewrite loop.
- Start original retrieval concurrently with planning. If a valid rewrite exists, execute one
  additional retrieval through the same reader. Each branch requests at most five governed
  candidates; no branch bypasses SQL audience, effective-date, kind, Tier, current-version, or
  provider/model filters.
- Fuse stable evidence/chunk identities with weighted RRF: `k=60`, original weight `1.0`, rewrite
  weight `0.8`. Submit at most ten fused candidates to one rerank request and return at most the
  caller's existing limit.
- Query planning and reranking each have an internal deadline no greater than two seconds and one
  provider attempt. Planner failure returns an original-only plan; rerank failure preserves RRF.
  Embedding/authoritative PostgreSQL failure remains a typed tool failure and is never fabricated.
- `CachedBrandEmbeddingModel` is process-local TTL/LRU with single-flight loading. Its key binds the
  cache version, configured provider/model/input-version namespace, artifact/chunk ID, supplied
  input hash, and actual text hash. Artifact identity is mandatory because the persisted Alibaba
  brand request fingerprint binds the chunk even when two chunks contain identical text. It caches
  only successful typed results, has no Redis/database persistence, and disappears with the MCP
  process.
- `BoundedAgentRunner` caches successful exact tool invocations only within one `run()`. The key
  binds registry schema hash, tool name, and canonical validated arguments. A hit still consumes one
  tool-call budget and creates a normal observation; trace records only `cache_hit` and
  `cache_scope=agent_run`, never arguments or result bodies.

The real entry reuses `AI_PLATFORM_BASE_URL`, `AI_PLATFORM_API_KEY`, `AI_CHAT_MODEL`, and
`AI_PROVIDER_CONCURRENCY` for planner/rerank plus `BRAND_EMBEDDING_PROVIDER_MODE` and the existing
`VISUAL_EMBEDDING_*` Alibaba endpoint/key/model settings for brand vectors. API upload, content
worker ingestion/retrieval, and MCP retrieval must resolve the same brand provider/model identity.

Existing active versions from another vector space must not be relabeled or queried with Alibaba
vectors. `app.brand_embedding_reindex_main` provides a development-only, dry-run-by-default path
that derives current parser/chunk/input versions from immutable originals, processes them through
the canonical ingestion executor, and activates only ready target versions. A failed or incomplete
target leaves the old version active.

### 4. Validation & Error Matrix

| Condition | Required result |
|---|---|
| Planner timeout, provider error, malformed JSON, wrong intent, or semantic drift | Original query only; safe hash/kind warning; no tool failure |
| Rewrite retrieval fails after original succeeds | Ignore rewrite branch and continue with original candidates |
| Rerank timeout, malformed/duplicate/out-of-range indexes, non-finite score, or wrong result count | Preserve stable weighted-RRF order |
| Original Embedding or authoritative DB retrieval fails | Existing typed `agent_tool_unavailable`; do not hide it with rewrite results |
| Planner configured without reranker, or inverse | Composition raises `ValueError` before registry construction |
| Brand provider is not Alibaba or stored active provider/model differs | Startup fails closed or retrieval returns existing typed unavailable; never cross vector spaces |
| Brand reindex is invoked without `--execute` | Plan remains read-only; mutating action is rejected |
| One document's Alibaba reindex fails | Its old active version remains authoritative; ready documents may switch independently |
| Same embedding input is requested concurrently | Exactly one underlying provider call; waiters share the typed result |
| Embedding cache entry expires or is evicted | One new provider call; old result is not returned |
| Same valid tool call repeats in one Agent run | Handler runs once; both calls receive successful observations |
| Invalid call repeats | Validation fails every time; failure is not cached |

### 5. Good / Base / Bad Cases

- Good: an ambiguous brand query is rewritten once by GLM, original and rewritten hybrid retrieval
  results are fused with RRF, Zhipu rerank selects the final Top K, and all returned chunks still
  carry `evidence_eligible=false`.
- Base: the planner or reranker is unavailable, so the same tool returns governed original/RRF
  results within its existing schema and deadline.
- Bad: let the Agent freely generate many searches, cache cross-user result lists without corpus
  versions, rerank before governance filtering, use a rewrite result when original authoritative
  retrieval failed, or describe `search_evidence` as vector/BM25 retrieval.

### 6. Tests Required

- Domain unit tests freeze NFKC normalization, overlap rejection, RRF weights/K, duplicate rejection,
  and deterministic ties.
- Service unit tests assert original/rewrite calls, identity deduplication, rerank order, exact-tool
  delegation, and planner/rewrite/rerank fail-soft behavior.
- Provider MockTransport tests assert exact Zhipu paths/payload controls, strict JSON, disabled
  thinking, dedicated rerank fields, and malformed/duplicate/out-of-range response rejection.
- Cache tests assert hit/miss, concurrent single flight, expiry, bounded eviction, failure non-cache,
  and actual-text participation in the embedding key.
- Runner tests assert a repeated exact call invokes its handler once, still counts twice in the
  bounded tool budget, and emits only safe cache trace metadata.
- Existing fixture/MCP schema, PostgreSQL read-only, brand retrieval/eval, and portfolio gates remain
  mandatory regression coverage. Default tests use MockTransport/fakes and make no live call.

### 7. Wrong vs Correct

#### Wrong

```python
queries = await agent.generate_queries_until_satisfied(user_query)
results = await gather(*(unfiltered_search(query) for query in queries))
return await rerank(results)
```

This is open-ended, bypasses authoritative filters, has no stable fallback, and cannot be evaluated
or bounded by the existing tool contract.

#### Correct

```python
plan = await one_shot_planner.plan(query=original, retrieval_kind=kind)
rankings = [await governed_reader.search(original)]
if plan.rewritten_query is not None:
    rankings.append(await governed_reader.search(plan.rewritten_query))
fused = weighted_reciprocal_rank_fusion(rankings)
return await rerank_or_return_rrf(fused[:10])
```

Keep intelligence at the retrieval service boundary while the MCP adapter remains a strict,
versioned, auditable projection of the same four tools.
