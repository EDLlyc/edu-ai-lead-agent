# Database Guidelines

## Initial persistence contract

Use PostgreSQL with pgvector. SQLAlchemy 2.x's asynchronous API with `asyncpg` and Alembic is the
greenfield default selected during bootstrap; it is not an inherited codebase convention. The
first vertical slice must validate this choice with real integration tests, after which this
guide must link to the actual models, repositories, and migrations.

The database is the durable source of truth for pipeline runs, jobs, source snapshots, evidence,
brand knowledge, generation artifacts, and material packages. Never rely on scheduler memory for
whether a daily job ran.

## Data-domain separation

Use distinct models, repositories, and foreign-key paths for:

- **Evidence data:** sources, immutable source snapshots, normalized articles, event clusters,
  extracted evidence passages, and claim-to-evidence bindings.
- **Brand data:** versioned brand documents/chunks, audience and validity metadata, safety rules,
  approved examples, and visual guidance.

Both domains may have vector columns, but a brand chunk cannot satisfy a factual claim's evidence
foreign key. Prefer database constraints over convention alone where possible.

Expected initial entities include `sources`, `source_snapshots`, `articles`, `event_clusters`,
`topic_scores`, `brand_documents`, `brand_chunks`, `pipeline_runs`, `stage_jobs`,
`generation_artifacts`, `claims`, `claim_evidence_bindings`, and `material_packages`. Implement
only the subset needed by each slice; do not create unused tables speculatively.

## SQLAlchemy 2 async pattern

Use typed declarative mappings (`Mapped[...]`, `mapped_column`) and `select()` statements. Inject
`AsyncSession` or a repository into the use case. Do not use legacy `Query`, implicit global
sessions, or lazy-loading that performs hidden async I/O.

```python
class PipelineRunModel(Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[UUID] = mapped_column(primary_key=True)
    schedule_date: Mapped[date]
    timezone: Mapped[str]
    pipeline_version: Mapped[str]
    status: Mapped[str]
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint(
            "schedule_date", "timezone", "pipeline_version",
            name="uq_pipeline_runs_schedule_business_key",
        ),
    )
```

Load relationships explicitly with `selectinload` when needed. Select only required columns for
list endpoints. Avoid per-row queries and bound batch sizes for embeddings and bulk inserts.

## Transactions and external calls

- The application service owns transaction boundaries.
- Keep transactions short and never hold one open across web scraping, LLM, embedding, reranking,
  image generation, or object-storage network calls.
- Use a short transaction to claim a job, perform the external call outside it, and use another
  transaction to persist the fingerprint/result and transition state.
- For competing workers, use `SELECT ... FOR UPDATE SKIP LOCKED`, a lease/heartbeat, or an
  equivalent tested claim mechanism.
- Use a unique idempotency key and upsert/conflict handling for scheduled runs and stage artifacts;
  do not implement check-then-insert races in Python.

Retries must not duplicate external side effects. Persist the request fingerprint, provider
request ID when available, prompt/model version, attempt number, and artifact status.

## Time, identifiers, and naming

- Use UUIDs for externally exposed and distributed entity identifiers unless a measured reason
  justifies another choice.
- Use `snake_case`, plural table names, and singular Python model names.
- Store instants as timezone-aware `TIMESTAMPTZ` values in UTC.
- Store the business schedule date and IANA timezone separately; the product default is
  `Asia/Shanghai`, not a hard-coded UTC offset.
- Name constraints and indexes explicitly: `pk_<table>`, `fk_<table>_<column>`,
  `uq_<table>_<purpose>`, and `ix_<table>_<purpose>`.
- Use database enums only when migration cost is accepted. Otherwise use validated text plus a
  check constraint and a domain enum.

## Snapshots, provenance, and auditability

Preserve the raw or canonical source snapshot before normalization, subject to lawful storage
and retention. Record source URL, canonical URL, publication/fetch times, content SHA-256, parser
version, normalization version, source tier, and extraction metadata. A duplicate record points
to the retained article/event; deduplication must not erase provenance.

Every score stores feature values, weights, penalties, total, threshold, rule/model version,
eligibility, and veto reasons. Every generated artifact stores prompt version, model/provider,
input artifact references, and validation/audit verdicts.

Claims and evidence are relational records, not just a prose `source_note`. A binding records the
claim ID, evidence passage/snapshot ID, exact quote or offsets, URL, source tier, and retrieval
time. Enforce that accepted core claims have at least one eligible binding in application logic
and test it at the database/service boundary.

## Vector and full-text search

- Keep embedding provider, model, dimension, and normalization version with each vectorized row.
- Configure vector dimensions in one place and encode changes through migrations/re-index jobs.
- Add HNSW or IVFFlat indexes only after representative data and query measurements exist.
- Apply metadata filters (audience, validity, source eligibility) before or alongside retrieval.
- PostgreSQL `tsvector`/`ts_rank` is full-text ranking, not BM25. Do not label it BM25.
- If exact BM25 is required, document and migrate a PostgreSQL extension such as `pg_search`, or
  select a search service through an explicit architecture decision.
- Fuse keyword and vector results with a documented, testable algorithm such as reciprocal rank
  fusion, then rerank a bounded candidate set.

Evidence and brand retrieval use separate queries and return separately typed results.

## Alembic migrations

- Every schema change is an Alembic revision reviewed with its generated SQL.
- Never call `Base.metadata.create_all()` in production startup.
- Keep migrations deterministic; do not call application services or external APIs from them.
- Split large backfills from blocking schema changes and make deployment order explicit.
- Test upgrade from a clean database to `head`; for risky changes, test the previous release to
  `head` and document downgrade limitations.
- Enable PostgreSQL extensions, including `vector`, through a migration or documented provisioning
  step with a corresponding integration check.

## Avoid

- Storing evidence and brand chunks in an unlabeled shared collection.
- Treating JSONB as a substitute for core foreign keys, state, and claim bindings.
- Deleting source history when a page changes.
- Comparing naive and aware datetimes.
- Writing raw SQL in routes or pipeline prompts.
- Unit tests with SQLite for PostgreSQL/pgvector behavior; use a real ephemeral PostgreSQL service.
