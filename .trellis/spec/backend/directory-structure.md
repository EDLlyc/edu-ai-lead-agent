# Backend Directory Structure

## Contract status

The repository contains only the installable environment shell:
[`api_main.py`](../../../backend/app/api_main.py),
[`core/config.py`](../../../backend/app/core/config.py), and
[`test_health.py`](../../../backend/tests/test_health.py). The environment tooling also exports
[`openapi.json`](../../../backend/openapi.json) through
[`scripts/export_openapi.py`](../../../backend/scripts/export_openapi.py). The expanded tree below remains the
required layout for the first product capability slices based on [`main.tex`](../../../main.tex)
and [`技术报告-v0.3.pdf`](../../../技术报告-v0.3.pdf); the environment shell does not establish
pipeline, domain, scheduler, or worker behavior.

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
│   │   ├── pipeline/
│   │   └── ports/
│   ├── core/
│   │   ├── config.py
│   │   ├── errors.py
│   │   ├── logging.py
│   │   └── security.py
│   ├── domain/
│   │   ├── entities/
│   │   ├── enums.py
│   │   └── value_objects/
│   ├── infrastructure/
│   │   ├── ai/
│   │   ├── db/
│   │   │   ├── models/
│   │   │   ├── repositories/
│   │   │   └── session.py
│   │   ├── ingestion/
│   │   ├── search/
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
another. Docker Compose starts `api_main`, `scheduler_main`, and `worker_main` independently.

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
- Treating this proposed tree as permanent evidence: update it after the first vertical slice.
