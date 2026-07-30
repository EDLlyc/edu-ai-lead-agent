# Backend Development Guidelines

## Status and source of truth

These documents are the implementation contract for the backend. Two production-shaped
capabilities now exist: governed acquisition from eight authoritative sources, followed by
versioned normalization, evidence-bound factual analysis, exact/semantic duplicate relations, and
auditable event organization. PostgreSQL owns durable run/job and derived-artifact state; MinIO
keeps immutable acquisition snapshots; API, scheduler, acquisition worker, governance planner, and
governance worker remain independent processes. The contracts remain aligned with the editable
[`main.tex`](../../../main.tex) source and generated
[`技术报告-v0.3.pdf`](../../../技术报告-v0.3.pdf), version 0.3. The bootstrap decision record at
`.trellis/tasks/archive/2026-07/00-bootstrap-guidelines/research/technical-report-decisions.md`
preserves the version 0.2 starting decisions as historical context; version 0.3 and these specs
control where the old report differs. Rules for later scoring/generation stages remain prospective;
acquisition rules link to the implemented source and tests.

## Guidelines index

| Guide | Scope |
|---|---|
| [Directory Structure](./directory-structure.md) | Backend package ownership and deployable entry points |
| [Database Guidelines](./database-guidelines.md) | PostgreSQL, pgvector, SQLAlchemy 2 async, and Alembic |
| [Agent Pipeline](./agent-pipeline.md) | End-to-end stage boundaries, implemented handoffs, and future scoring/generation semantics |
| [Factual Governance and Event Organization](./governance-event-organization.md) | Implemented normalization, LangGraph, provider, duplicate, event, API, and operational contracts |
| [Error Handling](./error-handling.md) | Typed failures, API responses, retries, and terminal states |
| [Logging Guidelines](./logging-guidelines.md) | Structured observability, privacy, and audit fields |
| [Quality Guidelines](./quality-guidelines.md) | Type, test, migration, security, and contract gates |

## Non-negotiable backend boundaries

- Target Python 3.11 with FastAPI and Pydantic v2.
- Run API, scheduler, and workers as separate processes or containers.
- Keep evidence retrieval separate from brand-knowledge retrieval.
- Bind every externally verifiable core claim to stored source evidence.
- Preserve content-bearing candidates and source occurrences as separate governed concepts.
- Keep provider calls outside API handlers and database transactions.
- Run deterministic validation before the LLM audit; the audit is not a fact source.
- Persist idempotency keys, attempts, and stage transitions for every durable job.
- Treat fetched text and model output as untrusted data, including prompt-injection content.
- Produce packages for manual copy/download only. Do not implement automated social publishing.

**Documentation language:** English.
