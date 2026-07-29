# Backend Directory Structure

## Contract status

The first backend slice is implemented under [`backend/app`](../../../backend/app): versioned API
routes, acquisition application services and ports, provider-independent domain rules, SQLAlchemy
repositories/models, safe source connectors/fetching, MinIO snapshot storage, and separate API,
scheduler, and worker entry points. OpenAPI is exported through
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
│   │   ├── db/
│   │   │   ├── models.py
│   │   │   ├── repositories.py
│   │   │   └── session.py
│   │   ├── ingestion/
│   │   └── storage/
│   ├── schemas/
│   ├── api_main.py
│   ├── scheduler_main.py
│   └── worker_main.py
└── tests/
    ├── contract/
    ├── integration/
    └── unit/
```

The deployable entry points share application and infrastructure modules but must not import one
another. Docker Compose starts `api_main`, `scheduler_main`, and `worker_main` independently. Add
future AI/search packages only when their own task implements them; LangGraph is a downstream
workflow dependency, not part of acquisition.

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
