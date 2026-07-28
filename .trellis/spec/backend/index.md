# Backend Development Guidelines

## Status and source of truth

These documents are the initial implementation contract for a greenfield backend. The repository
now contains a minimal environment-verification API shell in
[`backend/app/api_main.py`](../../../backend/app/api_main.py), but no product pipeline or domain
vertical slice. The contracts are derived from `技术报告.pdf` version 0.2 and the bootstrap decision record at
`.trellis/tasks/archive/2026-07/00-bootstrap-guidelines/research/technical-report-decisions.md`;
rules that name future pipeline modules still describe the intended first product slice.

The first vertical slice must follow these defaults unless its task records an explicit design
decision. After that slice is merged, replace illustrative paths and snippets with links to real
source and tests, and revise any rule that the implementation has intentionally superseded.

## Guidelines index

| Guide | Scope |
|---|---|
| [Directory Structure](./directory-structure.md) | Backend package ownership and deployable entry points |
| [Database Guidelines](./database-guidelines.md) | PostgreSQL, pgvector, SQLAlchemy 2 async, and Alembic |
| [Agent Pipeline](./agent-pipeline.md) | Source governance, scoring, evidence bindings, audit, and job semantics |
| [Error Handling](./error-handling.md) | Typed failures, API responses, retries, and terminal states |
| [Logging Guidelines](./logging-guidelines.md) | Structured observability, privacy, and audit fields |
| [Quality Guidelines](./quality-guidelines.md) | Type, test, migration, security, and contract gates |

## Non-negotiable backend boundaries

- Target Python 3.11 with FastAPI and Pydantic v2.
- Run API, scheduler, and workers as separate processes or containers.
- Keep evidence retrieval separate from brand-knowledge retrieval.
- Bind every externally verifiable core claim to stored source evidence.
- Run deterministic validation before the LLM audit; the audit is not a fact source.
- Persist idempotency keys, attempts, and stage transitions for every durable job.
- Treat fetched text and model output as untrusted data, including prompt-injection content.
- Produce packages for manual copy/download only. Do not implement automated social publishing.

**Documentation language:** English.
