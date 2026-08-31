# Backend Development Guidelines

## Status and source of truth

These documents are the implementation contract for the backend. Five production-shaped
capabilities now exist: governed acquisition from eleven active approved sources, with two more
approved connector profiles pending independent live activation gates; versioned
normalization, evidence-bound factual analysis, duplicate relations, and event organization;
deterministic daily Top 1/`no_topic` selection; private versioned brand-document ingestion with
separated hybrid retrieval; an internal no-auth IP visual-asset hub with dynamic multimodal
retrieval; and reviewed material-package delivery to one internal Enterprise WeChat sales
recipient. PostgreSQL owns durable run/job and derived-artifact
state; MinIO keeps immutable acquisition snapshots; API, schedulers, and workers remain independent
processes. The contracts remain aligned with the editable
[`main.tex`](../../../main.tex) source and generated
[`技术报告-v0.3.pdf`](../../../技术报告-v0.3.pdf), version 0.3. The bootstrap decision record at
`.trellis/tasks/archive/2026-07/00-bootstrap-guidelines/research/technical-report-decisions.md`
preserves the version 0.2 starting decisions as historical context; version 0.3 and these specs
control where the old report differs. Generation and material-package rules remain prospective;
acquisition, governance, topic-selection, and brand-retrieval rules link to implemented code and
tests.

## Guidelines index

| Guide | Scope |
|---|---|
| [Directory Structure](./directory-structure.md) | Backend package ownership and deployable entry points |
| [Database Guidelines](./database-guidelines.md) | PostgreSQL, pgvector, SQLAlchemy 2 async, and Alembic |
| [Local Agent Workbench](./agent-workbench.md) | One typed read-only registry for bounded Agent, MCP stdio, deterministic eval, and a loopback-only API |
| [Execution Governance](./execution-governance.md) | Shared run identity, atomic budgets, default-deny capabilities, safe causal trace, and artifact lineage for Agents and deterministic DAG nodes |
| [Agent Pipeline](./agent-pipeline.md) | End-to-end stage boundaries, implemented scoring handoff, and future generation semantics |
| [Official-Account Editorial Repackage](./official-account-editorial-repackage.md) | Frozen offline repackages plus durable V10 five-visual/news-context generation, disjoint staging attempts, polished deterministic local export, and permanent no-publish truth |
| [Factual Governance and Event Organization](./governance-event-organization.md) | Implemented normalization, LangGraph, provider, duplicate, event, API, and operational contracts |
| [Daily Topic Selection](./topic-selection.md) | Implemented versioned veto, scoring, Top 1/no-topic, persistence, API, and worker contracts |
| [Three-Slot Independent Content Production](./content-slot-production.md) | Optional morning/noon/evening acquisition, post-eligibility ranking, independent artifacts, delivery windows, API/UI, and compatibility contracts |
| [Controlled Visual Diversity](./visual-diversity.md) | Versioned 3D-brand visual planning, seven-day reservation, one perceptual repair, warning acceptance, API, and tests |
| [Brand Multimodal Visual Retrieval](./visual-retrieval.md) | Approved-catalog image indexing, text/image query, semantic-primary selection, and deterministic fallback |
| [IP Digital Asset Hub](./ip-asset-hub.md) | Intranet/no-auth dynamic upload, naming, private object storage, partial-index retrieval, download, and generation-to-library contracts |
| [Brand Knowledge RAG](./brand-knowledge-rag.md) | Implemented private upload, immutable versions, parser safety, provider-scoped embeddings, retrieval, API, UI, and tests |
| [WeCom Sales Delivery](./wecom-delivery.md) | Implemented reviewed material-package enqueueing, bounded Enterprise WeChat delivery, leases, idempotency, and safe provider error projection |
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
- Keep Enterprise WeChat side effects in the independent dispatcher; the API only enqueues
  material-package jobs that satisfy the configured manual-review or direct-quality policy, and
  the dispatcher never publishes to a social platform.
- Run deterministic validation before the LLM audit; the audit is not a fact source.
- Persist idempotency keys, attempts, and stage transitions for every durable job.
- Treat fetched text and model output as untrusted data, including prompt-injection content.
- Never persist or expose Enterprise WeChat secrets, access tokens, raw user IDs, temporary media
  IDs, provider response bodies, or private MinIO object locations.
- Produce packages for manual copy/download only. Do not implement automated social publishing.

**Documentation language:** English.
