# Backend Directory Structure

## Contract status

The first three backend capabilities are implemented under [`backend/app`](../../../backend/app):
versioned acquisition and governance APIs, application services/ports, provider-independent domain
rules, SQLAlchemy repositories/models, safe source connectors, MinIO snapshot and private brand
original storage, optional Zhipu adapters, LangGraph orchestration, deterministic topic selection,
brand ingestion/retrieval, and separate API,
acquisition, governance, and content processes. OpenAPI is exported through
[`scripts/export_openapi.py`](../../../backend/scripts/export_openapi.py). Extend this real layout;
do not recreate the earlier greenfield-only tree or collapse the process boundaries.

## Target layout

```text
backend/
├── pyproject.toml
├── alembic.ini
├── alembic/
│   ├── env.py
│   └── versions/
├── app/
│   ├── api/
│   │   ├── dependencies.py
│   │   └── v1/routes/
│   ├── application/
│   │   ├── services/
│   │   └── ports/
│   ├── core/
│   │   ├── config.py
│   │   ├── errors.py
│   │   ├── logging.py
│   │   └── security.py
│   ├── domain/
│   │   ├── entities.py
│   │   ├── enums.py
│   │   ├── state.py
│   │   ├── title_relevance.py
│   │   └── value_objects.py
│   ├── infrastructure/
│   │   ├── ai/
│   │   ├── db/
│   │   │   ├── models.py
│   │   │   ├── repositories.py
│   │   │   └── session.py
│   │   ├── ingestion/
│   │   └── storage/
│   ├── schemas/
│   ├── api_main.py
│   ├── scheduler_main.py
│   ├── worker_main.py
│   ├── governance_scheduler_main.py
│   ├── governance_worker_main.py
│   ├── content_scheduler_main.py
│   └── content_worker_main.py
└── tests/
    ├── contract/
    ├── integration/
    └── unit/
```

The deployable entry points share application and infrastructure modules but must not import one
another. Docker Compose starts acquisition and governance processes independently. Provider/LangGraph
modules belong only to factual governance and later approved model-oriented capabilities; they do
not move into acquisition or authorize arbitrary browsing.

## Ownership rules

### API boundary

`app/api/` owns HTTP routing, dependency injection, authentication/authorization when introduced,
and translation between Pydantic API schemas and application commands. Route handlers do not
perform ingestion, retrieval, scoring, generation, image calls, or multi-step transactions.

```python
@router.post("/pipeline-runs", response_model=PipelineRunResponse, status_code=202)
async def create_run(
    request: CreatePipelineRunRequest,
    service: Annotated[PipelineRunService, Depends(get_pipeline_run_service)],
) -> PipelineRunResponse:
    run = await service.enqueue_manual_run(request.run_date)
    return PipelineRunResponse.model_validate(run)
```

### Application layer

`app/application/` coordinates use cases and pipeline stages. It depends on typed ports for the
database, model providers, object storage, and clocks. It owns transaction boundaries at the use-
case level and returns domain results rather than HTTP responses.

Pipeline stages are small, named operations with typed input/output artifacts. Do not implement
the entire workflow as one agent prompt or one untestable service method.

### Domain layer

`app/domain/` contains provider-independent concepts such as source tiers, run/stage states,
claim bindings, scoring results, and veto reasons. It must not import FastAPI, SQLAlchemy, an LLM
SDK, or object-storage clients.

### Infrastructure layer

`app/infrastructure/` implements outbound ports. Keep provider-specific request/response models
inside the adapter. Convert them to domain/application types before returning. Separate evidence
repositories and brand-knowledge repositories even if both use PostgreSQL and pgvector.

### Schemas

`app/schemas/` contains Pydantic v2 request, response, configuration, and structured model-output
schemas. Database ORM classes stay under `infrastructure/db/models`; never reuse an ORM model as
an HTTP or LLM-output schema.

## Scheduler and worker boundaries

- `scheduler_main.py` calculates due schedules and enqueues durable run records.
- It obtains a database-backed lease/advisory lock and uses a unique schedule business key.
- `worker_main.py` claims jobs, heartbeats long-running work, records attempts, and executes one
  resumable stage at a time.
- `api_main.py` may enqueue a manual run but cannot start an in-process scheduler or background
  thread for durable work.

This separation prevents each multi-process FastAPI worker from firing the same daily schedule.

## Governance ownership

- `application/services/governance_*` owns enqueueing, version-bundle composition, typed graph
  nodes, worker classification, and planner reconciliation.
- `application/ports/governance.py` is the only application-facing contract for factual analysis,
  embeddings, checkpointer inspection, repositories, clocks, and IDs.
- `domain/governance_*`, `domain/event_assignment.py`, and
  `domain/governance_semantic.py` own deterministic normalization, validation, duplicate, and
  event-policy rules; they import neither SQLAlchemy nor httpx.
- `infrastructure/ai/` contains provider-specific transport parsing and safe error projection.
  `infrastructure/db/governance_*` contains durable operational/artifact/query/checkpoint adapters.
- `api/v1/routes/governance_runs.py`, `candidate_analyses.py`, and `events.py` only validate/project
  HTTP contracts. They do not execute LangGraph or call Zhipu.
- `governance_scheduler_main.py` plans durable work; `governance_worker_main.py` claims and executes
  it. Both remain independently enabled and deployable.

See [`governance-event-organization.md`](./governance-event-organization.md) for the executable
cross-layer contract.

## Topic-selection ownership

- `domain/topic_selection.py` owns pure deterministic feature normalization, vetoes, score totals,
  stable ranking, and Top 1/`no_topic` decisions.
- `application/services/topic_selection.py` owns enqueue, schedule reconciliation, execution, and
  heartbeat coordination through `application/ports/topic_selection.py`.
- `infrastructure/db/topic_selection.py` owns PostgreSQL config/run/job/score/lock persistence and
  governed-event projections at the immutable run cutoff.
- `api/v1/routes/topic_selection_runs.py` and `topic_selection_views.py` only validate/project the
  HTTP contract; they do not score in the request process.
- `content_scheduler_main.py` and `content_worker_main.py` are independently enabled deployables.

See [`topic-selection.md`](./topic-selection.md) for the executable cross-layer contract.

## Brand-knowledge ownership

- `domain/brand_knowledge.py` owns document metadata, upload validation, stable metadata
  fingerprints, deterministic chunks, and brand-only retrieval results.
- `application/ports/brand_knowledge.py` and `application/services/brand_knowledge.py` own the
  separate storage/parser/embedding/repository contracts and resumable ingestion execution.
- `infrastructure/brand/parser.py`, `storage/minio_brand_store.py`, and
  `db/brand_knowledge.py` own bounded parsing, immutable originals, durable jobs, activation, and
  hybrid retrieval.
- `api/v1/routes/brand_knowledge.py` projects multipart and retrieval contracts; it does not parse,
  embed, or rank in the request handler.
- `content_worker_main.py` alternates topic and brand claims to prevent either durable queue from
  starving the other.

See [`brand-knowledge-rag.md`](./brand-knowledge-rag.md) for the executable cross-layer contract.

## Naming conventions

- Packages, modules, functions, database attributes, and variables: `snake_case`.
- Classes, Pydantic models, domain entities, and exceptions: `PascalCase`.
- Constants and environment-variable names: `UPPER_SNAKE_CASE`.
- Ports name the capability (`EvidenceRepository`, `ImageGenerator`); adapters name the provider
  (`PostgresEvidenceRepository`, `CompanyPlatformImageGenerator`).
- Stage modules use explicit action names such as `normalize_candidates.py`,
  `score_topics.py`, and `audit_draft.py`, not generic names such as `helper.py`.
- Test modules mirror the target module and begin with `test_`.

## Avoid

- A generic `utils.py` containing unrelated behavior.
- Business rules in route handlers, ORM event hooks, or provider adapters.
- Importing `app.api` from workers or the scheduler.
- Running external HTTP/model calls while holding a database transaction open.
- Circular imports resolved through local imports rather than corrected ownership.
- Reintroducing speculative `ai/`, `search/`, or pipeline packages before a task owns real code.
